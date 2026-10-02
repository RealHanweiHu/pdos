"""Named proposal decisions, distinct from creating or withdrawing business Issues."""

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, RowMapping, func, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.ai_issue_write_access import authorize
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    result_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_version: int = Field(strict=True, ge=0)
    action: Literal["decline", "reopen"]
    reason: str = Field(min_length=1, max_length=1000)


def latest(c: Connection, result: Any) -> RowMapping | None:
    t = tables.ai_issue_proposal_reviews
    return (
        c.execute(
            select(t)
            .where(
                t.c.tenant_id == result["tenant_id"],
                t.c.project_id == result["project_id"],
                t.c.result_id == result["id"],
            )
            .order_by(t.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def public_receipt(c: Connection, row: Any) -> dict[str, Any]:
    name = c.execute(
        select(tables.users.c.display_name).where(
            tables.users.c.tenant_id == row["tenant_id"], tables.users.c.id == row["actor_user_id"]
        )
    ).scalar_one()
    return _plain({**dict(row), "actor_name": name})


def state(
    c: Connection, result: Any, *, applied: bool, may_write: bool, before_version: int | None = None
) -> dict[str, Any]:
    from app.domain.ai_issue_applications import IssueApplicationError

    current = latest(c, result)
    version = current["version"] if current else 0
    current_state = (
        "declined"
        if current and current["action"] == "decline"
        else "reopened"
        if current
        else "unreviewed"
    )
    t = tables.ai_issue_proposal_reviews
    query = select(t).where(
        t.c.tenant_id == result["tenant_id"],
        t.c.project_id == result["project_id"],
        t.c.result_id == result["id"],
    )
    if before_version is not None:
        if c.execute(query.where(t.c.version == before_version)).first() is None:
            raise IssueApplicationError("REVIEW_CURSOR_INVALID", "请从原建议的办理历史继续读取")
        query = query.where(t.c.version < before_version)
    rows = list(c.execute(query.order_by(t.c.version.desc()).limit(21)).mappings())
    notice = (
        "同一来源已经实际办理，请沿原问题继续处理；原建议意见保留。"
        if applied
        else "当前仅可查看原建议的具名意见。"
        if not may_write
        else "该建议已标记不采纳；重新考虑后仍须核对来源和实际办理条件。"
        if current_state == "declined"
        else "可以记录不采纳及原因，不会创建、修改或撤回原业务问题。"
    )
    return {
        "version": version,
        "state": current_state,
        "can_change": may_write and not applied,
        "notice": notice,
        "items": [public_receipt(c, row) for row in rows[:20]],
        "next_before_version": rows[19]["version"] if len(rows) > 20 else None,
    }


class IssueProposalReviews:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self, context: AuthContext, project: UUID, run: UUID, before_version: int | None = None
    ) -> dict[str, Any]:
        from app.domain.ai_issue_applications import _existing, _result

        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            authorize(c, context, project, write=False)
            result = _result(c, context.tenant.id, project, run)
            may_write = True
            try:
                authorize(c, context, project, write=True)
            except PermissionError:
                may_write = False
            return state(
                c,
                result,
                applied=_existing(
                    c, context.tenant.id, project, result["source_snapshot"]["source_key"]
                )
                is not None,
                may_write=may_write,
                before_version=before_version,
            )

    def change(
        self, context: AuthContext, project: UUID, run: UUID, change: ReviewRequest
    ) -> dict[str, Any]:
        from app.domain.ai_issue_applications import (
            IssueApplicationError,
            _existing,
            _read,
            _result,
        )

        tenant, actor = context.tenant.id, context.user.id
        signature = digest(
            {
                "project_id": str(project),
                "run_id": str(run),
                **change.model_dump(mode="json", exclude={"request_id"}),
            }
        )
        with self.engine.begin() as c:
            c.execute(
                select(tables.tenants.c.id).where(tables.tenants.c.id == tenant).with_for_update()
            )
            if not lock_project_write_scope(c, tenant_id=tenant, project_id=project):
                raise LookupError("原项目已不可办理")
            authorize(c, context, project, write=True)
            result = _result(c, tenant, project, run)
            if (
                result["id"] != change.result_id
                or result["source_digest"] != change.expected_digest
            ):
                raise IssueApplicationError("RESULT_CHANGED", "请按原建议与依据记录意见")
            t = tables.ai_issue_proposal_reviews
            old = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == tenant,
                        t.c.actor_user_id == actor,
                        t.c.request_id == change.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["request_digest"] != signature:
                    raise IssueApplicationError("REQUEST_ID_REUSED", "本请求已用于其他建议意见")
                return {**_read(c, context, project, run), "review_receipt": public_receipt(c, old)}
            if _existing(c, tenant, project, result["source_snapshot"]["source_key"]):
                raise IssueApplicationError(
                    "SOURCE_ALREADY_APPLIED", "同一来源已实际办理，请沿原问题继续处理"
                )
            current = latest(c, result)
            version = current["version"] if current else 0
            if version != change.expected_version:
                raise IssueApplicationError("REVIEW_CHANGED", "建议意见已有后续版本，请刷新核对")
            required = "reopen" if current and current["action"] == "decline" else "decline"
            if change.action != required:
                raise IssueApplicationError(
                    "REVIEW_ACTION_INVALID", "当前建议不能重复执行该意见，请刷新核对"
                )
            identity, now = uuid4(), c.execute(select(func.clock_timestamp())).scalar_one()
            event = EventAuditWriter(
                c, tenant_id=tenant, project_id=project, actor_user_id=actor
            ).record(
                EventDraft(
                    event_id=f"ai-issue-review:{identity}",
                    event_type="AI_ISSUE_PROPOSAL_REVIEW_RECORDED",
                    source="ai_issue_review_service",
                    entity_id=identity,
                    payload={
                        "review_id": str(identity),
                        "result_id": str(result["id"]),
                        "action": change.action,
                        "version": version + 1,
                    },
                ),
                AuditDraft(
                    action="ai_issue.proposal_review",
                    before_snapshot={
                        "version": version,
                        "action": current["action"] if current else None,
                    },
                    after_snapshot={
                        "review_id": str(identity),
                        "result_id": str(result["id"]),
                        "version": version + 1,
                        "action": change.action,
                        "reason": change.reason,
                    },
                ),
            )
            saved = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=tenant,
                        project_id=project,
                        run_id=run,
                        result_id=result["id"],
                        actor_user_id=actor,
                        version=version + 1,
                        action=change.action,
                        reason=change.reason,
                        request_id=change.request_id,
                        request_digest=signature,
                        output_event_row_id=event.event_row_id,
                        created_at=now,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            return {**_read(c, context, project, run), "review_receipt": public_receipt(c, saved)}
