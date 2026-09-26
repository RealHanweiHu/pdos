"""Versioned owner reports bind actual supply observations and original task criteria."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.document_previews import document_row, metadata
from app.domain.material_exceptions import _authorize, _editable, _row
from app.domain.material_schedule import observations
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.tooling_schedule import assess as tooling_assess
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class Evidence(Contract):
    document_id: UUID
    location: Text
    supports: Text


class ReportDraft(Contract):
    request_id: UUID
    expected_version: int = Field(ge=0)
    disposition: Literal["progress", "ready_for_review", "unable_to_recover"]
    actual_result: Text
    verification_response: Text
    criteria_response: Text
    remaining_work: Text
    evidence: list[Evidence] = Field(min_length=1, max_length=20)
    response_to_review_id: UUID | None = None
    review_response: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def distinct(self) -> "ReportDraft":
        if len({(e.document_id, e.location) for e in self.evidence}) != len(self.evidence):
            raise ValueError("同一资料位置无需重复引用")
        return self


class ReportApply(ReportDraft):
    expected_digest: Digest


def item(c: Connection, tenant: UUID, project: UUID, item_id: UUID) -> dict[str, Any]:
    i, a, f = tables.supplier_recovery_items, tables.supplier_recovery_applications, tables.findings
    row = (
        c.execute(
            select(i, a.c.finding_id, a.c.review, f.c.accepted_payload)
            .join(
                a,
                (a.c.tenant_id == i.c.tenant_id)
                & (a.c.project_id == i.c.project_id)
                & (a.c.id == i.c.application_id),
            )
            .join(
                f,
                (f.c.tenant_id == a.c.tenant_id)
                & (f.c.project_id == a.c.project_id)
                & (f.c.id == a.c.finding_id),
            )
            .where(i.c.tenant_id == tenant, i.c.project_id == project, i.c.id == item_id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("恢复工作不存在或不属于本项目")
    return dict(row)


def source_state(
    c: Connection, tenant: UUID, project: UUID, work: dict[str, Any], evidence: list[Evidence]
) -> dict[str, Any]:
    proposal = next(
        o
        for o in work["accepted_payload"]["assessment"]["options"]
        if o["key"] == work["proposal_key"]
    )
    choice = next(o for o in work["review"]["choices"] if o["key"] == work["proposal_key"])
    task = (
        c.execute(
            select(tables.tasks).where(
                tables.tasks.c.tenant_id == tenant,
                tables.tasks.c.project_id == project,
                tables.tasks.c.id == work["task_id"],
            )
        )
        .mappings()
        .one()
    )
    targets = []
    for ref in proposal["target_reference_ids"]:
        kind, value = ref.split(":", 1)
        identity = UUID(value)
        if kind == "material_exception":
            entry = _row(c, tenant, project, identity)
            current = observations(c, tenant, project, [entry])[identity]
            targets.append(
                {
                    "reference_id": ref,
                    "ready": current["supply_ready"],
                    "source_digest": current["source_digest"],
                    "review_current": current["review_current"],
                    "review_id": str(current["latest_review"]["id"]),
                    "material": current["material"],
                    "issue_id": str(entry["issue_id"]),
                    "build_id": str(entry["build_id"]),
                }
            )
        elif kind == "tooling_round":
            row = NpiExecutionService._row(
                c, tables.tooling_rounds, tenant_id=tenant, project_id=project, record_id=identity
            )
            current = tooling_assess(c, tenant, project, row)
            targets.append(
                {"reference_id": ref, "ready": current["status"] == "ready", "tooling": current}
            )
        else:
            raise ProductWorkError("原恢复对象不支持结果回链，请核对原候选")
    documents = [
        {
            **e.model_dump(mode="json"),
            "document": metadata(document_row(c, tenant, project, e.document_id)),
        }
        for e in evidence
    ]
    return {
        "item_id": str(work["id"]),
        "finding_id": str(work["finding_id"]),
        "proposal": proposal,
        "accepted_choice": choice,
        "task": _plain(
            {
                k: task[k]
                for k in (
                    "id",
                    "title",
                    "status",
                    "assignee_user_id",
                    "stage_id",
                    "due_date",
                    "expected_output",
                    "updated_at",
                )
            }
        ),
        "targets": targets,
        "evidence": documents,
    }


def result_sources_current(result: Any, current: dict[str, Any]) -> bool:
    # Normal task execution does not retract unchanged physical supply evidence.
    # Ownership, due date and expected output remain part of the checked scope.
    def basis(value: dict[str, Any]) -> dict[str, Any]:
        return {
            **value,
            "task": {k: v for k, v in value["task"].items() if k not in {"status", "updated_at"}},
        }

    return current["task"]["status"] != "skipped" and digest(basis(current)) == digest(
        basis(result["source_snapshot"])
    )


def latest(c: Connection, tenant: UUID, project: UUID, item_id: UUID) -> Any:
    t = tables.supplier_recovery_results
    return (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.project_id == project, t.c.item_id == item_id)
            .order_by(t.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def preview(
    c: Connection, context: AuthContext, project: UUID, item_id: UUID, command: ReportDraft
) -> dict[str, Any]:
    _authorize(c, context, project, write=True)
    work = item(c, context.tenant.id, project, item_id)
    snapshot = source_state(c, context.tenant.id, project, work, command.evidence)
    if snapshot["task"]["assignee_user_id"] != str(context.user.id):
        raise ProductWorkError("请由当前任务负责人本人登记结果")
    previous = latest(c, context.tenant.id, project, item_id)
    version = previous["version"] if previous else 0
    if command.expected_version != version:
        raise ProductWorkError("已有新结果，请读取最新版本后继续登记")
    if command.disposition == "ready_for_review" and not all(
        t["ready"] for t in snapshot["targets"]
    ):
        raise ProductWorkError("原对象尚无当前合格供给核对或实际工装可用证据，可先记录进展")
    reviews = tables.supplier_recovery_reviews
    returned = (
        c.execute(
            select(reviews).where(
                reviews.c.tenant_id == context.tenant.id,
                reviews.c.project_id == project,
                reviews.c.result_id == previous["id"],
                reviews.c.decision == "returned",
            )
        )
        .mappings()
        .one_or_none()
        if previous
        else None
    )
    if returned:
        if command.response_to_review_id != returned["id"] or not command.review_response.strip():
            raise ProductWorkError("请对原退回要求逐项回应，并绑定该裁决后提交新结果")
    elif command.response_to_review_id is not None:
        raise ProductWorkError("本轮没有对应的退回裁决，请读取最新结果")
    body = command.model_dump(mode="json", exclude={"expected_digest"})
    return {
        "digest": digest({"report": body, "source": snapshot, "previous_version": version}),
        "source": snapshot,
        "report": body,
        "previous_version": version,
    }


class SupplierRecoveryResults:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self, context: AuthContext, project: UUID, item_id: UUID, before_version: int | None = None
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _authorize(c, context, project)
            work = item(c, context.tenant.id, project, item_id)
            current_error = None
            try:
                current = source_state(c, context.tenant.id, project, work, [])
            except (LookupError, ValueError):
                current = {}
                current_error = "当前任务或供应资料暂不可用；原结果及证据版本保留"
            t = tables.supplier_recovery_results
            query = (
                select(t, tables.users.c.display_name.label("author_name"))
                .join(
                    tables.users,
                    (tables.users.c.tenant_id == t.c.tenant_id)
                    & (tables.users.c.id == t.c.created_by_user_id),
                )
                .where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.project_id == project,
                    t.c.item_id == item_id,
                )
            )
            if before_version is not None:
                query = query.where(t.c.version < before_version)
            found = c.execute(query.order_by(t.c.version.desc()).limit(21)).mappings().all()
            results = []
            for r in found[:20]:
                try:
                    now = source_state(
                        c,
                        context.tenant.id,
                        project,
                        work,
                        [Evidence.model_validate(e) for e in r["report"]["evidence"]],
                    )
                    unchanged = result_sources_current(r, now)
                except (LookupError, ValueError):
                    unchanged = False
                results.append({**_plain(r), "sources_current": unchanged})
            docs = (
                c.execute(
                    select(tables.documents)
                    .where(
                        tables.documents.c.tenant_id == context.tenant.id,
                        tables.documents.c.project_id == project,
                    )
                    .order_by(tables.documents.c.created_at.desc(), tables.documents.c.id.desc())
                    .limit(101)
                )
                .mappings()
                .all()
            )
            last = latest(c, context.tenant.id, project, item_id)
            from app.domain.supplier_recovery_reviews import readout

            review_state = readout(c, context, project, work, results, last)
            return {
                **review_state,
                "current": current,
                "current_error": current_error,
                "latest_version": last["version"] if last else 0,
                "can_report": current_error is None
                and current["task"]["assignee_user_id"] == str(context.user.id)
                and _editable(c, context, project),
                "documents": [metadata(row) for row in docs[:100]],
                "more_documents": len(docs) > 100,
                "items": results,
                "next_before_version": found[19]["version"] if len(found) > 20 else None,
            }

    def preview(
        self, context: AuthContext, project: UUID, item_id: UUID, command: ReportDraft
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return preview(c, context, project, item_id, command)

    def apply(
        self, context: AuthContext, project: UUID, item_id: UUID, command: ReportApply
    ) -> dict[str, Any]:
        signature = digest(
            {
                "project": str(project),
                "item": str(item_id),
                "command": command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as c:
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project, lock=True
            )
            _authorize(c, context, project, write=True)
            t = tables.supplier_recovery_results
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.created_by_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != signature:
                    raise ProductWorkError("原请求已用于其他结果，请保留原回执")
                return _plain(prior)
            observed = preview(c, context, project, item_id, command)
            if observed["digest"] != command.expected_digest:
                raise ProductWorkError("任务、供应对象或证据发生变化，请重新预览")
            identity = uuid4()
            values = dict(
                id=identity,
                tenant_id=context.tenant.id,
                project_id=project,
                item_id=item_id,
                version=command.expected_version + 1,
                response_to_review_id=command.response_to_review_id,
                request_id=command.request_id,
                request_digest=signature,
                source_digest=digest(observed["source"]),
                source_snapshot=observed["source"],
                report=observed["report"],
                created_by_user_id=context.user.id,
                created_at=datetime.now(UTC),
            )
            c.execute(t.insert().values(**values))
            EventAuditWriter(
                c, tenant_id=context.tenant.id, project_id=project, actor_user_id=context.user.id
            ).record(
                EventDraft(
                    event_id=f"supplier-recovery-result:{identity}",
                    event_type="SUPPLIER_RECOVERY_RESULT_RECORDED",
                    source="supplier_service",
                    entity_id=identity,
                    payload={"item_id": str(item_id), "version": values["version"]},
                ),
                AuditDraft(
                    action="supplier.recovery.result_recorded", after_snapshot=_plain(values)
                ),
            )
            return _plain(values)
