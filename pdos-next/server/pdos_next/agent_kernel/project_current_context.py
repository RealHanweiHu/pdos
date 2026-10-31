"""Bounded native project facts under the actual requester's ordinary RLS.

The Run stores only classification and a digest/fixed source footprint. Existing
project, work and governance owners remain the facts; no tool or fact store is added.
"""

# The common registry must initialize before importing domain model children.
# ruff: noqa: I001
from copy import deepcopy
from types import SimpleNamespace
from urllib.parse import urlencode
from uuid import UUID

from pydantic import Field, PrivateAttr
from sqlalchemy import func, select

from pdos_next.database import require_context
from pdos_next.models import Artifact, Principal
from pdos_next.domain.preproject.claim_access import source_privacy
from pdos_next.domain.preproject.models import ProjectOpenItem
from pdos_next.domain.project_governance import service as governance
from pdos_next.domain.projects.models import PlanRevision
from pdos_next.domain.work_management.models import ProjectStatusUpdate, WorkCommitmentVersion
from pdos_next.domain.work_management.owner import sources_current
from pdos_next.errors import DomainError
from pdos_next.project_work_summaries import latest as latest_updates
from pdos_next.schema_base import StrictModel
from pdos_next.service import Context, digest, require_access, source_for

from .execution import check_run_binding
from .models import AgentRun
from .project_scope import require_project
from .project_work_task_context import Task, collect as collect_tasks
from .project_work_task_context import current_proof as current_source_proof

KEY = "project_current_context"
LEGACY_KIND = "project-current-facts/v1"
KIND = "project-current-facts/v2"
LIMIT = 20
TEXT_LIMIT = 1200
EXPECTED_MISSING = {"FORBIDDEN_SCOPE", "NOT_FOUND", "SOURCE_UNAVAILABLE", "SOURCE_STALE",
                    "VERSION_CONFLICT", "RECHECK_REQUIRED"}


class Link(StrictModel):
    kind: str
    id: str
    revision: int | None = None
    receipt_id: str | None = None
    url: str


class NamedStatus(StrictModel):
    state: str
    reference: Link | None = None
    actor_id: str | None = None
    actor_name: str | None = None
    recorded_at: str | None = None
    fact_summary: str | None = None
    next_steps: str | None = None


class Plan(StrictModel):
    state: str
    reference: Link | None = None
    record_status: str | None = None
    earliest_finish: str | None = None
    latest_finish: str | None = None


class RuleCheck(StrictModel):
    key: str
    state: str
    detail: str


class GateCheck(StrictModel):
    key: str
    label: str
    state: str
    detail: str
    blocked: list[str] = Field(default_factory=list)
    unknown: list[str] = Field(default_factory=list)
    rule_checks: list[RuleCheck] = Field(default_factory=list)
    decisions: list[Link] = Field(default_factory=list)
    conditions: list[Link] = Field(default_factory=list)


class Gate(StrictModel):
    stage_id: str | None = None
    state: str
    release: Link | None = None
    review_current: bool = False
    checks: list[GateCheck] = Field(default_factory=list)


class Stage(StrictModel):
    id: str
    key: str
    name: str
    status: str | None = None


class Times(StrictModel):
    earliest_finish: str | None = None
    latest_finish: str | None = None


class Timeline(StrictModel):
    task_key: str | None = None
    baseline: Times | None = None
    forecast: Times | None = None
    actual: str | None = None


class Governance(StrictModel):
    state: str
    reference: Link | None = None
    current_stage: Stage | None = None
    stages: list[Stage] = Field(default_factory=list)
    gate: Gate | None = None
    next_gate: Gate | None = None
    timeline: Timeline | None = None
    completed: bool = False


class OpenItem(StrictModel):
    reference: Link
    kind: str
    title: str
    owner_id: str
    due_date: str
    record_status: str


class Commitment(StrictModel):
    reference: Link
    task_id: str
    promisor_id: str
    recipient_id: str
    promised_at: str | None = None
    fulfilled: bool


class LegacyCurrentFacts(StrictModel):
    version: str = LEGACY_KIND
    as_of: str
    project_revision: int
    named_status: NamedStatus
    plan: Plan
    governance: Governance
    open_items: list[OpenItem] = Field(default_factory=list)
    open_items_has_more: bool = False
    commitments: list[Commitment] = Field(default_factory=list)
    commitments_has_more: bool = False
    references: list[Link] = Field(default_factory=list)
    complete: bool = True
    missing: list[str] = Field(default_factory=list)


class CurrentFacts(LegacyCurrentFacts):
    version: str = KIND
    tasks: list[Task] = Field(default_factory=list)
    tasks_has_more: bool = False
    _tasks_metadata: dict = PrivateAttr(default_factory=dict)


def _url(project, tab=None):
    query = {"area": "cockpit", "category": str(project.category_id),
             "product": str(project.product_id), "project": str(project.id),
             "projectView": {"governance": "gates", "work": "tasks"}.get(tab, "now")}
    return "/?" + urlencode(query)


def _link(project, kind, identity, revision=None, receipt=None, *, tab=None):
    return Link(kind=kind, id=str(identity), revision=revision,
                receipt_id=str(receipt) if receipt else None, url=_url(project, tab))


def _text(value, missing):
    value = str(value)
    if len(value) > TEXT_LIMIT:
        missing.add("text_truncated")
        return value[:TEXT_LIMIT]
    return value


def _bounded(values, missing, key):
    if len(values) > LIMIT:
        missing.add(key)
    return values[:LIMIT]


def _gate(project, value, missing):
    if value is None:
        return None
    checks = []
    for check in _bounded(value["checks"], missing, "gate_checks_truncated"):
        assessment = check.get("assessment") or {}
        details = [RuleCheck(key=item["key"], state=item["state"],
                             detail=_text(item["detail"], missing))
                   for item in _bounded(assessment.get("checks", []), missing,
                                        "assessment_checks_truncated")]
        decisions = [_link(project, "release_decision", item["id"], item["revision"],
                           item["receipt_id"], tab="governance")
                     for item in _bounded(check.get("decisions", []), missing,
                                          "decisions_truncated")]
        checks.append(GateCheck(
            key=check["key"], label=check["label"], state=check["state"],
            detail=_text(check["detail"], missing),
            blocked=[_text(item, missing) for item in _bounded(
                assessment.get("blocked", []), missing, "blocked_checks_truncated")],
            unknown=[_text(item, missing) for item in _bounded(
                assessment.get("unknown", []), missing, "unknown_checks_truncated")],
            rule_checks=details, decisions=decisions,
            conditions=[_link(project, "release_exception", item["id"], item["revision"],
                              tab="governance")
                        for item in _bounded(assessment.get("conditions", []), missing,
                                             "conditions_truncated")],
        ))
    release = value.get("release")
    return Gate(stage_id=value["stage_id"], state=value["state"],
                release=_link(project, "release_package", release["id"], release["revision"],
                              release["receipt_id"], tab="governance") if release else None,
                review_current=value.get("review_current", False), checks=checks)


def _stage(value):
    return Stage(**{key: value.get(key) for key in ("id", "key", "name", "status")})


def _times(value):
    return Times(**{key: value.get(key) for key in ("earliest_finish", "latest_finish")}) \
        if value else None


def _source_proof(session, ctx, refs):
    """Exact ordinary source checks and the existing server egress classification."""
    proof, private, categories = {}, False, {"internal"}
    for ref in refs:
        identity, revision = UUID(str(ref["artifact_id"])), ref["expected_revision"]
        previous = proof.get(identity)
        if previous and previous["expected_revision"] != revision:
            raise DomainError("SOURCE_STALE", "项目当前依据指向不同原件版本，请重新核对。")
        head = session.get(Artifact, identity)
        if head is None:
            raise DomainError("SOURCE_UNAVAILABLE", "项目当前依据已不可读。", 403)
        actual = source_for(session, ctx, head.product_id, identity, revision)
        private |= source_privacy(
            session, ctx, SimpleNamespace(source_kind="artifact", artifact_id=identity),
        ) != "shared"
        if actual.original_id is not None:
            categories.add("customer_original")
        proof[identity] = {
            "artifact_id": str(actual.id), "expected_revision": actual.revision,
            "product_id": str(actual.product_id) if actual.product_id else None,
            "content_hash": actual.content_hash, "visibility": actual.visibility,
            "original_id": str(actual.original_id) if actual.original_id else None,
        }
    return [proof[key] for key in sorted(proof, key=str)], private, categories


def _collect(session, ctx, project, *, version=KIND):
    """Same authoritative models as personal_views, without changing its personal API scope."""
    require_context(session, ctx)
    missing, refs, references = set(), [], [_link(project, "project", project.id, project.revision)]
    value_type = CurrentFacts if version == KIND else LegacyCurrentFacts
    value = value_type(
        as_of=session.scalar(select(func.transaction_timestamp())).isoformat(),
        project_revision=project.revision, named_status=NamedStatus(state="not_recorded"),
        plan=Plan(state="not_created"), governance=Governance(state="not_adopted"),
    )
    update = latest_updates(session, ctx, [project]).get(project.id)
    if update is not None:
        row = session.get(ProjectStatusUpdate, UUID(update["id"]))
        try:
            if row is None:
                raise DomainError("SOURCE_UNAVAILABLE", "具名状态依据不可读。", 403)
            sources_current(session, ctx, project.product_id, row.source_basis)
            update_proof, _, _ = _source_proof(session, ctx, row.reads)
            refs.extend(update_proof)
            link = _link(project, "project_status_update", row.id, row.revision, row.receipt_id)
            value.named_status = NamedStatus(
                state="available", reference=link, actor_id=update["actor"]["id"],
                actor_name=update["actor"]["name"], recorded_at=update["created_at"],
                fact_summary=_text(update["fact_summary"], missing),
                next_steps=_text(update["next_steps"], missing),
            )
            references.append(link)
        except DomainError as error:
            if error.code not in EXPECTED_MISSING:
                raise
            value.named_status = NamedStatus(state="unavailable")
            missing.add("named_status_sources_unavailable")
    if project.current_plan_id:
        plan = session.get(PlanRevision, project.current_plan_id)
        if plan is not None and (
            plan.tenant_id, plan.category_id, plan.product_id, plan.project_id,
        ) == (ctx.tenant_id, ctx.category_id, project.product_id, project.id):
            link = _link(project, "plan", plan.id, plan.revision, tab="work")
            value.plan = Plan(state="available", reference=link, record_status=plan.status,
                              earliest_finish=plan.forecast.get("earliest_finish"),
                              latest_finish=plan.forecast.get("latest_finish"))
            references.append(link)
        else:
            value.plan = Plan(state="unavailable")
            missing.add("current_plan_unavailable")
    rows = list(session.scalars(select(ProjectOpenItem).where(
        ProjectOpenItem.tenant_id == ctx.tenant_id,
        ProjectOpenItem.category_id == ctx.category_id,
        ProjectOpenItem.product_id == project.product_id,
        ProjectOpenItem.project_id == project.id,
    ).order_by(ProjectOpenItem.due_date, ProjectOpenItem.id).limit(LIMIT + 1)))
    value.open_items_has_more = len(rows) > LIMIT
    for row in _bounded(rows, missing, "open_items_truncated"):
        link = _link(project, "project_open_item", row.id, tab="work")
        value.open_items.append(OpenItem(
            reference=link, kind=row.kind, title=_text(row.title, missing),
            owner_id=str(row.owner_id),
            due_date=row.due_date.isoformat(), record_status=row.status,
        ))
        references.append(link)
    try:
        native = governance.view(session, ctx, project.product_id, project.id)
        _, _, fixed_definition = governance._project(session, ctx, project.product_id, project.id)
        references.append(_link(project, "definition", fixed_definition["id"],
                                fixed_definition["revision"], tab="governance"))
        baseline = native.get("baseline")
        if baseline:
            references.append(_link(project, "plan", baseline["plan"]["id"],
                                    baseline["plan"]["revision"], tab="work"))
        gates = [native["gate"], native["next_gate"]]
        gate_refs = [ref for gate in gates if gate for ref in gate["required_source_read_set"]]
        native_proof, _, _ = _source_proof(session, ctx, gate_refs)
        refs.extend(native_proof)
        history = native["history"]
        link = _link(project, "project_governance", history[-1]["id"], native["revision"],
                     history[-1]["receipt_id"], tab="governance") if history else None
        value.governance = Governance(
            state="available" if native["stages"] else "not_adopted", reference=link,
            current_stage=_stage(native["current_stage"]) if native["current_stage"] else None,
            stages=[_stage(item) for item in _bounded(
                native["stages"], missing, "stages_truncated")],
            gate=_gate(project, native["gate"], missing),
            next_gate=_gate(project, native["next_gate"], missing),
            timeline=Timeline(task_key=native["timeline"]["task_key"],
                              baseline=_times(native["timeline"]["baseline"]),
                              forecast=_times(native["timeline"]["forecast"]),
                              actual=native["timeline"]["actual"]),
            completed=native["completed"],
        )
        if link:
            references.append(link)
        promises = native["commitments"]
        value.commitments_has_more = len(promises) > LIMIT
        for promise in _bounded(promises, missing, "commitments_truncated"):
            row = session.get(WorkCommitmentVersion, UUID(promise["id"]))
            try:
                if row is None:
                    raise DomainError("SOURCE_UNAVAILABLE", "承诺依据不可读。", 403)
                sources_current(session, ctx, project.product_id, row.source_basis)
                promise_proof, _, _ = _source_proof(session, ctx, row.reads)
                refs.extend(promise_proof)
                link = _link(project, "work_commitment", row.id, row.revision, row.receipt_id,
                             tab="work")
                value.commitments.append(Commitment(
                    reference=link, task_id=promise["task_id"], promisor_id=promise["promisor_id"],
                    recipient_id=promise["recipient_id"], promised_at=promise["promised_at"],
                    fulfilled=promise["fulfilled"],
                ))
                references.append(link)
            except DomainError as error:
                if error.code not in EXPECTED_MISSING:
                    raise
                missing.add("commitment_sources_unavailable")
    except DomainError as error:
        if error.code not in EXPECTED_MISSING:
            raise
        value.governance = Governance(state="unavailable")
        missing.add("governance_sources_unavailable")
    for gate in (value.governance.gate, value.governance.next_gate):
        if gate:
            if gate.release:
                references.append(gate.release)
            for check in gate.checks:
                references.extend(check.decisions)
                references.extend(check.conditions)
    task_private, task_categories = False, set()
    if version == KIND:
        def task_link(kind, identity, revision=None, receipt=None):
            return _link(project, kind, identity, revision, receipt, tab="work").model_dump()

        (value.tasks, value.tasks_has_more, task_refs, task_proof, task_private,
         task_categories, task_missing, value._tasks_metadata) = collect_tasks(
             session, ctx, project, link=task_link,
         )
        references.extend(Link.model_validate(ref) for ref in task_refs)
        # Task sources are already checked as a single metadata batch. Do not
        # send them through the legacy per-reference source/body reader again.
        missing.update(task_missing)
    else:
        task_proof = []
    proof, source_private, categories = _source_proof(session, ctx, refs)
    proof = list({(ref["artifact_id"], ref["expected_revision"]): ref
                  for ref in [*proof, *task_proof]}.values())
    proof.sort(key=lambda ref: ref["artifact_id"])
    categories.update(task_categories)
    product = require_access(session, ctx, project.product_id)
    private = (source_private or task_private or project.visibility != "category"
               or product.visibility != "category")
    value.references = list({(ref.kind, ref.id, ref.revision): ref for ref in references}.values())
    value.missing = sorted(missing)
    value.complete = not missing
    return value, proof, private, categories


def _basis(value):
    return digest(value.model_dump(mode="json", exclude={"as_of"}))


def bind(session, ctx, project):
    """Called by existing Human create_run; only actual native facts classify egress."""
    if ctx.actor_id != ctx.requester_id or ctx.run_id or ctx.agent_run_id:
        raise DomainError("FORBIDDEN_SCOPE", "项目事实须绑定当前本人实际运行。", 403)
    value, proof, private, categories = _collect(session, ctx, project, version=KIND)
    return {
        "kind": KIND, "tenant_id": str(ctx.tenant_id), "category_id": str(ctx.category_id),
        "project_id": str(project.id), "product_id": str(project.product_id),
        "requester_id": str(ctx.requester_id), "basis_digest": _basis(value),
        "as_of": value.as_of,
        "source_proof": proof, "references": [ref.model_dump(mode="json")
                                             for ref in value.references],
        "private_context": private, "data_categories": sorted(categories),
        "metadata_snapshot": {
            "version": "project-current-metadata/v1", "project_revision": project.revision,
            "current_plan_id": str(project.current_plan_id) if project.current_plan_id else None,
            **value._tasks_metadata,
            "named_status": {"id": value.named_status.reference.id,
                             "revision": value.named_status.reference.revision}
            if value.named_status.reference else None,
            "named_status_known": value.named_status.state in {"available", "not_recorded"},
            "governance": {"id": value.governance.reference.id,
                           "revision": value.governance.reference.revision}
            if value.governance.reference else None,
            "governance_known": value.governance.state in {"available", "not_adopted"},
        },
    }


def _current(session, ctx, run):
    stored = run.versions.get(KEY)
    if not stored:
        return None  # Existing Runs retain their original metadata-only contract.
    project = require_project(session, ctx, run.project_id, run.product_id)
    version = stored.get("kind")
    if version not in {LEGACY_KIND, KIND} or any(stored.get(key) != expected for key, expected in {
        "tenant_id": str(run.tenant_id), "category_id": str(run.category_id),
        "project_id": str(project.id), "product_id": str(run.product_id),
        "requester_id": str(run.requester_id),
    }.items()):
        raise DomainError("FORBIDDEN_SCOPE", "项目事实绑定与实际运行不一致。", 403)
    if (version == LEGACY_KIND
            or not stored.get("metadata_snapshot", {}).get("tasks", {}).get("items")):
        original_proof, _, _ = _source_proof(session, ctx, stored["source_proof"])
    else:
        original_proof = current_source_proof(session, ctx, project, stored["source_proof"])
    if original_proof != stored["source_proof"]:
        raise DomainError("SOURCE_STALE", "项目原依据版本已变化，请读取当前记录。")
    value, proof, private, categories = _collect(session, ctx, project, version=version)
    if (proof != stored["source_proof"] or _basis(value) != stored["basis_digest"]):
        raise DomainError("SOURCE_STALE", "项目状态或门禁依据已变化，请从当前项目继续读取。")
    if private and not run.private_context or not categories <= set(run.data_categories):
        raise DomainError("FORBIDDEN_SCOPE", "项目事实尚未绑定本运行的实际资料分类。", 403)
    value.as_of = stored["as_of"]
    return value


def read(store, scope):
    """No arbitrary owner parameter; the ordinary owner comes only from a verified Run."""
    if scope.project_id is None or scope.isolation != "main":
        return None
    with store.transaction(scope) as (_session, run):
        if not run.versions.get(KEY):
            return None
        check_run_binding(run, scope, for_write=False)
    from pdos_next.enterprise_search.assistant_sources import human_snapshot

    with human_snapshot(store.engine, scope) as session:
        run = session.get(AgentRun, scope.run_id)
        check_run_binding(run, scope, for_write=False)
        ctx = Context(run.tenant_id, run.requester_id, run.requester_id,
                      category_id=run.category_id)
        actor = session.get(Principal, run.requester_id)
        if actor is None or not actor.active or actor.kind != "human":
            raise DomainError("FORBIDDEN_SCOPE", "项目事实请求者已不可用。", 403)
        value = _current(session, ctx, run)
        return value.model_dump(mode="json") if value else None


def check(store, scope):
    read(store, scope)


def _basis_view(value, *, currentness="current"):
    return {"version": value["version"], "as_of": value["as_of"], "currentness": currentness,
            "complete": value["complete"], "missing": deepcopy(value["missing"]),
            "references": deepcopy(value["references"])}


def attach(store, scope, output):
    """Grounding is native context, never a fabricated retrieval/citation result."""
    if scope.project_id is None or scope.isolation != "main":
        return output
    with store.transaction(scope) as (_session, run):
        used = run.versions.get(KEY) and any(
            "project" in snapshot.get("fields", [])
            for snapshot in run.versions.get("context_snapshots", {}).values()
        )
    if not used:
        return output
    value = read(store, scope)
    result = deepcopy(output)
    body = result.setdefault("result", {})
    answer = body.setdefault("assistant", {"version": 1})
    if answer.get("lookup") == "not_run":
        # The existing UI uses not_run to claim no company records were read.
        # Omit that marker; do not invent a RAG lookup or citation.
        answer = body["assistant"] = {"version": 1}
    answer["project_basis"] = _basis_view(value)
    if not value["complete"] and result.get("status") == "completed":
        result["status"] = "partial"
        result["unfinished"] = [*result.get("unfinished", []), "项目当前记录有未读取或不可用部分。"]
    return result


def checked_result(session, ctx, run, result):
    """P32: preserve the fixed answer after updates, hide it after actual ACL loss.

    API calls this only after its existing Run/enterprise history guards. Native
    rows are checked in the same ordinary owner snapshot, never a writer session.
    """
    answer = (result or {}).get("result", {}).get("assistant", {})
    basis = answer.get("project_basis") if isinstance(answer, dict) else None
    if basis is None or not run.versions.get(KEY):
        return result
    require_context(session, ctx)
    if (ctx.actor_id != ctx.requester_id or ctx.requester_id != run.requester_id
            or ctx.tenant_id != run.tenant_id or ctx.category_id != run.category_id
            or ctx.run_id or ctx.agent_run_id):
        raise DomainError("FORBIDDEN_SCOPE", "项目历史回答不在当前本人范围。", 403)
    project = require_project(session, ctx, run.project_id, run.product_id)
    stored = run.versions[KEY]
    updated = False
    for ref in stored["source_proof"]:
        head = session.get(Artifact, UUID(ref["artifact_id"]))
        if head is None:
            raise DomainError("FORBIDDEN_SCOPE", "项目历史回答的原依据已不可读。", 403)
        try:
            actual = source_for(session, ctx, head.product_id, head.id)
        except DomainError as error:
            if error.code not in EXPECTED_MISSING:
                raise
            raise DomainError("FORBIDDEN_SCOPE", "项目历史回答的原依据已不可读。", 403) from None
        updated |= (actual.revision != ref["expected_revision"]
                    or actual.content_hash != ref["content_hash"])
    from pdos_next.domain.project_governance.models import GovernanceEvent
    from pdos_next.domain.projects.models import Project
    from pdos_next.domain.projects.models import ProjectTask
    from pdos_next.domain.products.models import DefinitionRevision
    from pdos_next.domain.release.models import ReleaseDecision, ReleasePackage
    from pdos_next.domain.release_exceptions.models import ReleaseExceptionDecision
    from pdos_next.domain.work_management.models import WorkTaskVersion

    models = {"project": Project, "plan": PlanRevision, "project_open_item": ProjectOpenItem,
              "project_status_update": ProjectStatusUpdate, "project_governance": GovernanceEvent,
              "work_commitment": WorkCommitmentVersion, "release_decision": ReleaseDecision,
              "release_exception": ReleaseExceptionDecision, "release_package": ReleasePackage,
              "definition": DefinitionRevision, "work_task": WorkTaskVersion,
              "plan_task": ProjectTask}
    for ref in stored["references"]:
        row = session.get(models[ref["kind"]], UUID(ref["id"]))
        if (row is None or row.tenant_id != run.tenant_id or row.category_id != run.category_id
                or row.product_id != run.product_id
                or (ref["kind"] not in {"project", "definition"}
                    and row.project_id != run.project_id)
                or ref["kind"] == "project" and row.id != run.project_id):
            raise DomainError("FORBIDDEN_SCOPE", "项目历史回答的固定记录已不可读。", 403)
    current, *_ = _collect(session, ctx, project, version=stored.get("kind", LEGACY_KIND))
    updated |= _basis(current) != stored["basis_digest"]
    restored = deepcopy(result)
    historical = restored["result"]["assistant"]["project_basis"]
    historical["currentness"] = "updated" if updated else "current"
    if updated:
        historical["notice"] = "项目记录已更新；保留本回答原版本，当前事实请重新读取。"
    return restored
