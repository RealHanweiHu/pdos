"""Independent decisions on exact supply recovery result versions."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.material_exceptions import _authorize, _editable
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.supplier_recovery_results import (
    Evidence,
    item,
    latest,
    result_sources_current,
    source_state,
)
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class ReviewDraft(Contract):
    request_id: UUID
    result_id: UUID
    decision: Literal["confirmed", "returned"]
    reason: Text
    follow_up: str = ""
    evidence_checked: bool = False
    verification_verified: bool = False
    criteria_verified: bool = False
    remaining_resolved: bool = False

    @model_validator(mode="after")
    def complete(self) -> "ReviewDraft":
        if self.decision == "confirmed" and not all(
            (
                self.evidence_checked,
                self.verification_verified,
                self.criteria_verified,
                self.remaining_resolved,
            )
        ):
            raise ValueError("确认须核对原证据、验证要求、完成判据和剩余缺项")
        if self.decision == "returned" and not self.follow_up.strip():
            raise ValueError("退回须说明补齐内容及后续要求")
        if len(self.follow_up) > 4000:
            raise ValueError("后续要求不能超过4000字")
        return self


class ReviewApply(ReviewDraft):
    expected_digest: Digest


def task_owner(c: Connection, tenant: UUID, project: UUID, task_id: UUID) -> Any:
    return c.execute(
        select(tables.tasks.c.assignee_user_id).where(
            tables.tasks.c.tenant_id == tenant,
            tables.tasks.c.project_id == project,
            tables.tasks.c.id == task_id,
        )
    ).scalar_one()


def preview(
    c: Connection, context: AuthContext, project: UUID, item_id: UUID, command: ReviewDraft
) -> dict[str, Any]:
    _authorize(c, context, project, write=True)
    work = item(c, context.tenant.id, project, item_id)
    result = latest(c, context.tenant.id, project, item_id)
    if result is None or result["id"] != command.result_id:
        raise ProductWorkError("请选择最新提交的结果版本；旧版保留历史")
    if result["report"]["disposition"] != "ready_for_review":
        raise ProductWorkError("本版尚未提交恢复核对，请先由负责人补齐并提交")
    if context.user.id in {
        result["created_by_user_id"],
        task_owner(c, context.tenant.id, project, work["task_id"]),
    }:
        raise ProductWorkError("结果登记人和当前任务负责人不能独立核对本结果")
    t = tables.supplier_recovery_reviews
    if c.execute(
        select(t.c.id).where(
            t.c.tenant_id == context.tenant.id,
            t.c.project_id == project,
            t.c.result_id == result["id"],
        )
    ).scalar_one_or_none():
        raise ProductWorkError("本版已有独立裁决，请在原记录继续或由负责人提交新结果")
    try:
        current = source_state(
            c,
            context.tenant.id,
            project,
            work,
            [Evidence.model_validate(e) for e in result["report"]["evidence"]],
        )
        source_error = None
    except (LookupError, ValueError):
        current = None
        source_error = "原业务资料当前不可用，须补齐后重新提交"
    sources_current = current is not None and result_sources_current(result, current)
    if command.decision == "confirmed" and (
        not sources_current
        or current is None
        or not all(t["ready"] for t in current["targets"])
        or current["task"]["status"] == "skipped"
    ):
        raise ProductWorkError("任务、供应状态或证据已变化；请退回补齐后重新提交")
    snapshot = {
        "result": _plain(result),
        "current_source": current,
        "source_error": source_error,
        "sources_current": sources_current,
    }
    body = command.model_dump(mode="json", exclude={"expected_digest"})
    return {
        "digest": digest({"review": body, "snapshot": snapshot}),
        "review": body,
        "snapshot": snapshot,
    }


def readout(
    c: Connection,
    context: AuthContext,
    project: UUID,
    work: dict[str, Any],
    results: list[dict[str, Any]],
    current_result: Any,
) -> dict[str, Any]:
    ids = [UUID(r["id"]) for r in results]
    if current_result is not None:
        ids.append(current_result["id"])
    t, u = tables.supplier_recovery_reviews, tables.users
    reviews = (
        c.execute(
            select(t, u.c.display_name.label("reviewer_name"))
            .join(u, (u.c.tenant_id == t.c.tenant_id) & (u.c.id == t.c.created_by_user_id))
            .where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.result_id.in_(ids),
            )
        )
        .mappings()
        .all()
    )
    by_result = {str(r["result_id"]): _plain(r) for r in reviews}
    for result in results:
        result["review"] = by_result.get(result["id"])
    if current_result is None:
        return {"recovery_state": "no_result", "can_review": False, "latest_review": None}
    last = by_result.get(str(current_result["id"]))
    try:
        current = source_state(
            c,
            context.tenant.id,
            project,
            work,
            [Evidence.model_validate(e) for e in current_result["report"]["evidence"]],
        )
        unchanged = result_sources_current(current_result, current)
    except (LookupError, ValueError):
        unchanged = False
    state = (
        "pending_review"
        if current_result["report"]["disposition"] == "ready_for_review"
        else "in_progress"
    )
    if last:
        state = (
            "returned"
            if last["decision"] == "returned"
            else "confirmed"
            if unchanged
            else "source_changed"
        )
    elif not unchanged:
        state = "source_changed"
    eligible = _editable(c, context, project) and context.user.id not in {
        current_result["created_by_user_id"],
        task_owner(c, context.tenant.id, project, work["task_id"]),
    }
    return {
        "recovery_state": state,
        "latest_review": last,
        "latest_result_id": str(current_result["id"]),
        "can_review": eligible
        and last is None
        and current_result["report"]["disposition"] == "ready_for_review",
    }


class SupplierRecoveryReviews:
    def __init__(self, engine: Engine):
        self.engine = engine

    def preview(
        self, context: AuthContext, project: UUID, item_id: UUID, command: ReviewDraft
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return preview(c, context, project, item_id, command)

    def apply(
        self, context: AuthContext, project: UUID, item_id: UUID, command: ReviewApply
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
            t = tables.supplier_recovery_reviews
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
                    raise ProductWorkError("原请求已用于另一核对，请保留原裁决")
                return _plain(prior)
            observed = preview(c, context, project, item_id, command)
            if observed["digest"] != command.expected_digest:
                raise ProductWorkError("原结果、来源或办理状态发生变化，请重新预览")
            identity = uuid4()
            values = dict(
                id=identity,
                tenant_id=context.tenant.id,
                project_id=project,
                item_id=item_id,
                result_id=command.result_id,
                decision=command.decision,
                request_id=command.request_id,
                request_digest=signature,
                review=observed["review"],
                snapshot=observed["snapshot"],
                created_by_user_id=context.user.id,
                created_at=datetime.now(UTC),
            )
            c.execute(t.insert().values(**values))
            EventAuditWriter(
                c, tenant_id=context.tenant.id, project_id=project, actor_user_id=context.user.id
            ).record(
                EventDraft(
                    event_id=f"supplier-recovery-review:{identity}",
                    event_type="SUPPLIER_RECOVERY_RESULT_REVIEWED",
                    source="supplier_service",
                    entity_id=identity,
                    payload={
                        "item_id": str(item_id),
                        "result_id": str(command.result_id),
                        "decision": command.decision,
                    },
                ),
                AuditDraft(
                    action="supplier.recovery.result_reviewed", after_snapshot=_plain(values)
                ),
            )
            return _plain(values)
