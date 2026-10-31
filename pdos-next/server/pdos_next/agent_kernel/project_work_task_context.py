"""Bounded current work facts, read in the requester's ordinary Human snapshot.

This is a projection of existing work/plan owners. It adds no task/date writes,
no tool, and no source body reading. Identity heads, receipt groups and source
metadata are loaded in batches; historical ACL checks consume the fixed refs.
"""

# The common model registry initializes before its domain children.
# ruff: noqa: I001
from collections import defaultdict
from types import SimpleNamespace
from uuid import UUID

from pydantic import Field
from sqlalchemy import String, and_, cast, func, select
from sqlalchemy.orm import load_only

from pdos_next.database import require_context
from pdos_next.domain.preproject.models import ProjectOpenItem
from pdos_next.domain.projects.models import PlanRevision, ProjectTask
from pdos_next.domain.work_management import g0_sources
from pdos_next.domain.work_management.constants import OPERATIONS
from pdos_next.domain.work_management.models import (
    WorkCommitmentCurrent, WorkCommitmentVersion, WorkTaskCurrent, WorkTaskVersion,
)
from pdos_next.domain.work_management.schemas import CommitmentSnapshot, TaskSnapshot
from pdos_next.enterprise_search.safety import safe_originals
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Audit, OriginalSecurity, Outbox, Principal, Product
from pdos_next.models import Receipt, UploadedOriginal
from pdos_next.schema_base import StrictModel
from pdos_next.service import digest

SCOPE = ("tenant_id", "category_id", "product_id", "project_id")
BINDING = (*SCOPE, "owner_id", "visibility")
LIMIT = 20


class Reference(StrictModel):
    kind: str
    id: str
    revision: int | None = None
    receipt_id: str | None = None
    url: str


class TaskPlan(StrictModel):
    state: str = "not_linked"
    task_reference: Reference | None = None
    plan_reference: Reference | None = None
    earliest_finish: str | None = None
    latest_finish: str | None = None
    date_nature: str = "forecast"
    unknown_reasons: list[str] = Field(default_factory=list)


class TaskCommitment(StrictModel):
    reference: Reference
    series_id: str
    task_revision: int
    promisor_id: str
    recipient_id: str
    promised_at: str | None = None


class Task(StrictModel):
    reference: Reference
    task_id: str
    title: str
    record_status: str
    assignee_id: str | None = None
    assignee_name: str | None = None
    plan: TaskPlan = Field(default_factory=TaskPlan)
    commitments: list[TaskCommitment] = Field(default_factory=list)
    commitments_has_more: bool = False


def _same(left, right, fields):
    return and_(*(getattr(left, field) == getattr(right, field) for field in fields))


def task_query(ctx, project):
    current, task = WorkTaskCurrent, WorkTaskVersion
    planned, plan = ProjectTask, PlanRevision
    # Outer joins retain a broken/missing fixed plan as explicitly unavailable;
    # neither a title match nor the current project plan replaces its identity.
    return (select(task, current, planned, plan, Principal.id, Principal.name)
            .select_from(current).join(task, and_(
                _same(current, task, (*BINDING, "task_id", "revision", "state")),
                current.version_id == task.id,
            )).outerjoin(planned, and_(
                cast(planned.id, String) == task.body["plan_task"]["id"].astext,
                _same(planned, task, SCOPE),
            )).outerjoin(plan, and_(plan.id == planned.plan_id, _same(plan, task, SCOPE)))
            .outerjoin(Principal, and_(
                cast(Principal.id, String) == task.body["assignee_id"].astext,
                Principal.tenant_id == task.tenant_id, Principal.kind == "human",
            )).where(current.tenant_id == ctx.tenant_id, current.category_id == ctx.category_id,
                     current.product_id == project.product_id, current.project_id == project.id)
            .order_by(current.task_id).limit(LIMIT + 1)
            .prefix_with("/* project_work_task_heads */"))


def commitment_query(ctx, project, identities):
    current, version = WorkCommitmentCurrent, WorkCommitmentVersion
    return (select(version, current).select_from(current).join(version, and_(
        _same(current, version, (*BINDING, "task_id", "promisor_id", "recipient_id",
                                "series_id", "revision")), current.version_id == version.id,
    )).where(current.tenant_id == ctx.tenant_id, current.category_id == ctx.category_id,
             current.product_id == project.product_id, current.project_id == project.id,
             current.task_id.in_(identities))
            .order_by(current.task_id, current.series_id).limit(LIMIT + 1)
            .prefix_with("/* project_work_commitment_heads */"))


def _integrity(condition):
    if not condition:
        raise DomainError("INTEGRITY_MISMATCH", "项目工作的固定版本或共同回执无法核对。")


def _scope(ctx, project, row):
    return row is not None and tuple(getattr(row, key) for key in SCOPE) == (
        ctx.tenant_id, ctx.category_id, project.product_id, project.id,
    )


def _groups(session, ctx, project, versions):
    """Batch the existing retained/common_group contract, including peer key proof.

    The existing DB function returns only an exact, currently-readable receipt's
    key-binding boolean. No RequestKey or different actor identity is exposed.
    """
    if not versions:
        return {}
    rows = session.execute(select(
        Receipt, Audit, Outbox,
        func.work_receipt_key_bound(ctx.tenant_id, project.product_id, Receipt.id),
    ).outerjoin(Audit, and_(Audit.tenant_id == Receipt.tenant_id,
                           Audit.receipt_id == Receipt.id))
      .outerjoin(Outbox, and_(Outbox.tenant_id == Receipt.tenant_id,
                             Outbox.receipt_id == Receipt.id))
      .where(Receipt.tenant_id == ctx.tenant_id, Receipt.product_id == project.product_id,
             Receipt.id.in_([row.receipt_id for row in versions]))
      .prefix_with("/* project_work_receipt_groups */")).all()
    grouped = defaultdict(list)
    for receipt, audit, outbox, key_bound in rows:
        grouped[receipt.id].append((receipt, audit, outbox, key_bound))
    checked = {}
    for row in versions:
        proof = grouped[row.receipt_id]
        if len(proof) != 1:
            checked[row.id] = False
            continue
        receipt, audit, outbox, key_bound = proof[0]
        checked[row.id] = bool(
            audit and outbox and key_bound is True
            and receipt.subject_id == row.id and receipt.subject_revision == row.revision
            and receipt.operation == row.operation and receipt.visibility == row.visibility
            and str(receipt.result.get("id")) == str(row.id)
            and receipt.result.get("revision") == row.revision
            and audit.actor_id == receipt.actor_id and audit.operation == row.operation
            and (outbox.type, outbox.actor_id, outbox.correlation_id, outbox.subject_id,
                 outbox.subject_revision) == (
                     OPERATIONS[row.operation][1], receipt.actor_id,
                     receipt.agent_run_id or receipt.run_id or receipt.command_id,
                     row.id, row.revision,
                 )
        )
    return checked


def _sources(session, ctx, project, versions):
    """Same current metadata tests as work.owner.sources_current, batched by root.

    Only these actual immutable work source_basis/read sets are interpreted.
    Original scan safety uses the existing batch gate, not status-only trust.
    """
    roots = {UUID(ref["id"]) for row in versions
             for ref in row.source_basis.get("artifacts", [])}
    roots.update(UUID(ref["artifact_id"]) for row in versions for ref in row.reads)
    artifact_fields = ("id", "tenant_id", "category_id", "product_id", "revision", "status",
                       "content_hash", "owner_id", "visibility", "original_id")
    artifacts = {row.id: row for row in session.scalars(select(Artifact).options(
        load_only(*(getattr(Artifact, key) for key in artifact_fields), raiseload=True),
    ).where(Artifact.tenant_id == ctx.tenant_id, Artifact.category_id == ctx.category_id,
            Artifact.id.in_(roots))).all()} if roots else {}
    originals = {row.original_id for row in artifacts.values() if row.original_id}
    safe = safe_originals(session, originals)
    original_rows = {row.id: row for row in session.scalars(select(UploadedOriginal).options(
        load_only(UploadedOriginal.id, UploadedOriginal.product_id, UploadedOriginal.visibility,
                  raiseload=True),
    ).where(UploadedOriginal.id.in_(originals))).all()} if originals else {}
    states = {(row.original_id, row.product_id): row for row in session.scalars(select(
        OriginalSecurity,
    ).where(
        OriginalSecurity.tenant_id == ctx.tenant_id,
        OriginalSecurity.original_id.in_(originals),
    )).all()} if originals else {}
    product_ids = {row.product_id for row in [*artifacts.values(), *original_rows.values()]
                   if row.product_id}
    products = {row.id: row for row in session.scalars(select(Product).options(
        load_only(Product.id, Product.visibility, raiseload=True),
    ).where(Product.id.in_(product_ids))).all()} if product_ids else {}
    native_ids = {UUID(row.source_basis["g0_open_item"]["id"]) for row in versions
                  if row.source_basis.get("g0_open_item")}
    native = {row.id: row for row in session.scalars(select(ProjectOpenItem).where(
        ProjectOpenItem.tenant_id == ctx.tenant_id, ProjectOpenItem.category_id == ctx.category_id,
        ProjectOpenItem.product_id == project.product_id, ProjectOpenItem.project_id == project.id,
        ProjectOpenItem.id.in_(native_ids),
    )).all()} if native_ids else {}
    result = {}
    for row in versions:
        try:
            private, categories, proof = row.visibility != "category", {"internal"}, []
            expected_roots = {ref["id"]: ref for ref in row.source_basis.get("artifacts", [])}
            for read in row.reads:
                identity = read["artifact_id"]
                if identity in expected_roots:
                    if expected_roots[identity]["revision"] != read["expected_revision"]:
                        raise DomainError("SOURCE_STALE", "任务依据与原读取版本不一致。")
                else:
                    expected_roots[identity] = {"id": identity,
                                                "revision": read["expected_revision"]}
            for expected in expected_roots.values():
                actual = artifacts.get(UUID(expected["id"]))
                if actual is None or actual.status != "active":
                    raise DomainError("SOURCE_UNAVAILABLE", "任务依据已不可读或撤回。", 403)
                current = (actual.revision, actual.content_hash,
                           str(actual.owner_id), actual.visibility)
                if actual.revision != expected["revision"] or "hash" in expected and current != (
                    expected["revision"], expected["hash"], expected["owner_id"],
                    expected["visibility"],
                ):
                    raise DomainError("SOURCE_STALE", "任务依据版本已变化，请核对当前记录。")
                if actual.product_id and actual.product_id not in products:
                    raise DomainError("SOURCE_UNAVAILABLE", "任务依据型号已不可读。", 403)
                private |= actual.visibility != "category" or bool(
                    actual.product_id and products[actual.product_id].visibility != "category")
                if actual.original_id:
                    original, state = original_rows.get(actual.original_id), states.get(
                        (actual.original_id, actual.product_id))
                    frozen = expected.get("original")
                    if (actual.original_id not in safe or original is None or state is None
                            or frozen is not None and (str(actual.original_id) != frozen["id"]
                                                       or state.epoch != frozen["epoch"])
                            or state.source_state != "active" or state.disposition != "active"):
                        raise DomainError("SOURCE_UNAVAILABLE", "任务原件状态已变化。", 403)
                    if original.product_id and original.product_id not in products:
                        raise DomainError("SOURCE_UNAVAILABLE", "任务原件型号已不可读。", 403)
                    private |= original.visibility != "category" or bool(
                        original.product_id
                        and products[original.product_id].visibility != "category")
                    categories.add("customer_original")
                proof.append({"artifact_id": str(actual.id), "expected_revision": actual.revision,
                              "product_id": str(actual.product_id) if actual.product_id else None,
                              "content_hash": actual.content_hash, "visibility": actual.visibility,
                              "original_id": str(actual.original_id)
                              if actual.original_id else None})
            frozen = row.source_basis.get("g0_open_item")
            if frozen:
                native_row = native.get(UUID(frozen["id"]))
                current = g0_sources._basis(
                    {key: getattr(native_row, "g0_decision_id" if key == "decision_id" else key)
                     for key in (*SCOPE, *g0_sources._FIXED)} if native_row else None,
                    ctx, project.product_id, project.id,
                )
                if current != frozen:
                    raise DomainError("SOURCE_STALE", "任务的原 G0 依据已变化。")
            result[row.id] = (proof, private, categories, None)
        except DomainError as error:
            if error.code not in {"SOURCE_UNAVAILABLE", "SOURCE_STALE"}:
                raise
            result[row.id] = ([], False, set(), error.code)
    return result


def current_proof(session, ctx, project, references):
    """Recheck the persisted server footprint through the same metadata batch.

    This transient view contains only that actual footprint, never a fabricated
    business fact/ledger record. Its opaque key is local to this guard call.
    """
    key = object()
    view = SimpleNamespace(id=key, visibility="category", source_basis={"artifacts": []},
                           reads=references)
    proof, _private, _categories, error = _sources(session, ctx, project, [view])[key]
    if error:
        raise DomainError(error, "项目原依据已不可读或变化，请核对当前记录。", 403
                          if error == "SOURCE_UNAVAILABLE" else 409)
    return sorted(proof, key=lambda ref: ref["artifact_id"])


def collect(session, ctx, project, *, link):
    require_context(session, ctx)
    rows = session.execute(task_query(ctx, project)).all()
    has_more, rows = len(rows) > LIMIT, rows[:LIMIT]
    missing = {"tasks_truncated"} if has_more else set()
    metadata_snapshot = {
        "tasks": {"items": [{"task_id": str(row[0].task_id),
                              "version_id": str(row[0].id), "revision": row[0].revision}
                             for row in rows], "has_more": has_more},
        "task_commitments": {"items": [], "has_more": False},
    }
    if not rows:
        return [], has_more, [], [], False, {"internal"}, missing, metadata_snapshot
    versions = [row[0] for row in rows]
    promises = session.execute(commitment_query(
        ctx, project, [row.task_id for row in versions],
    )).all()
    promises_more, promises = len(promises) > LIMIT, promises[:LIMIT]
    metadata_snapshot["task_commitments"] = {
        "items": [{"task_id": str(row.task_id), "version_id": str(row.id),
                   "revision": row.revision, "series_id": str(row.series_id),
                   "promisor_id": str(row.promisor_id), "recipient_id": str(row.recipient_id)}
                  for row, _pointer in promises], "has_more": promises_more,
    }
    all_versions = [*versions, *(row[0] for row in promises)]
    groups = _groups(session, ctx, project, all_versions)
    sources = _sources(session, ctx, project, all_versions)
    by_task = defaultdict(list)
    for commitment, pointer in promises:
        _integrity(_scope(ctx, project, commitment) and _scope(ctx, project, pointer))
        by_task[commitment.task_id].append(commitment)
    tasks, refs, proof, private, categories = [], [], [], False, {"internal"}

    def retained(row):
        nonlocal private
        _integrity(digest(row.body) == row.body_sha256)
        if not groups[row.id]:
            missing.add("work_receipt_unavailable")
            return False
        actual, restricted, classes, error = sources[row.id]
        if error:
            missing.add("task_sources_" + error.lower())
            return False
        proof.extend(actual)
        private |= restricted
        categories.update(classes)
        return True

    for row, pointer, planned, plan, assignee_id, assignee_name in rows:
        _integrity(_scope(ctx, project, row) and _scope(ctx, project, pointer))
        snapshot = TaskSnapshot.model_validate(row.body)
        _integrity((snapshot.task_id, snapshot.revision, snapshot.state)
                   == (row.task_id, row.revision, row.state))
        if not retained(row):
            continue
        ref = link("work_task", row.id, row.revision, row.receipt_id)
        task = Task(reference=ref, task_id=str(row.task_id), title=snapshot.title,
                    record_status=row.state,
                    assignee_id=str(snapshot.assignee_id) if snapshot.assignee_id else None,
                    assignee_name=assignee_name if assignee_id == snapshot.assignee_id else None,
                    commitments_has_more=promises_more)
        refs.append(ref)
        if row.source_basis.get("g0_open_item"):
            refs.append(link("project_open_item", row.source_basis["g0_open_item"]["id"]))
        if snapshot.assignee_id and assignee_id is None:
            missing.add("task_assignee_unavailable")
        if snapshot.plan_task:
            if (not _scope(ctx, project, planned) or not _scope(ctx, project, plan)
                    or planned.id != snapshot.plan_task.id
                    or plan.revision != snapshot.plan_task.revision):
                task.plan.state = "unavailable"
                missing.add("task_plan_unavailable")
            else:
                private |= plan.visibility != "category"
                task.plan = TaskPlan(
                    state="available" if project.current_plan_id == plan.id else "historical",
                    task_reference=link("plan_task", planned.id, plan.revision),
                    plan_reference=link("plan", plan.id, plan.revision),
                    earliest_finish=planned.forecast.get("earliest_finish"),
                    latest_finish=planned.forecast.get("latest_finish"),
                    unknown_reasons=list(planned.forecast.get("unknown_reasons", [])),
                )
                refs.extend([task.plan.task_reference, task.plan.plan_reference])
        for promise in by_task[row.task_id]:
            if not retained(promise):
                continue
            value = CommitmentSnapshot.model_validate(promise.body)
            _integrity((value.task_id, value.revision, value.task_revision, value.promisor_id,
                        value.recipient_id) == (promise.task_id, promise.revision,
                                               promise.task_revision, promise.promisor_id,
                                               promise.recipient_id))
            promise_ref = link("work_commitment", promise.id, promise.revision, promise.receipt_id)
            refs.append(promise_ref)
            if promise.source_basis.get("g0_open_item"):
                refs.append(link("project_open_item", promise.source_basis["g0_open_item"]["id"]))
            task.commitments.append(TaskCommitment(
                reference=promise_ref, series_id=str(promise.series_id),
                task_revision=value.task_revision,
                promisor_id=str(value.promisor_id), recipient_id=str(value.recipient_id),
                promised_at=value.promised_at.isoformat() if value.promised_at else None,
            ))
        tasks.append(task)
    if promises_more:
        missing.add("task_commitments_truncated")
    refs = [ref.model_dump(mode="json") if isinstance(ref, Reference) else ref for ref in refs]
    return tasks, has_more, refs, proof, private, categories, missing, metadata_snapshot
