"""Named sample opinions over direct Issue applications; never edit business state."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, RowMapping, func, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest
from app.db.schema import tables
from app.domain.ai_issue_applications import IssueApplicationError
from app.domain.ai_issue_write_access import authorize
from app.domain.issues import IssueService, _issue_snapshot
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class SampleReviewRequest(Contract):
    request_id: UUID
    expected_digest: Digest
    verdict: Literal["accepted", "needs_correction"]
    reason: str = Field(min_length=1, max_length=1000)


def _application(c: Connection, tenant: UUID, project: UUID, run: UUID) -> RowMapping | None:
    a, r = tables.ai_issue_applications, tables.agent_runs
    exists = c.execute(
        select(r.c.id).where(
            r.c.tenant_id == tenant,
            r.c.project_id == project,
            r.c.id == run,
            r.c.context_version == "event-issue-request-v1",
        )
    ).first()
    if exists is None:
        raise LookupError("原范围没有该事件建议运行")
    return (
        c.execute(
            select(a).where(
                a.c.tenant_id == tenant,
                a.c.project_id == project,
                a.c.run_id == run,
            )
        )
        .mappings()
        .one_or_none()
    )


def _sampled(application: Any) -> bool:
    return bool(
        application is not None
        and application["capture_mode"] == "direct"
        and application["receipt"].get("write_receipt", {}).get("sampled") is True
    )


def _snapshot(c: Connection, application: Any) -> dict[str, Any]:
    issue = IssueService._get_record(
        c,
        tenant_id=application["tenant_id"],
        project_id=application["project_id"],
        issue_id=application["issue_id"],
    )
    return _plain({"id": issue.id, "updated_at": issue.updated_at, **_issue_snapshot(issue)})


def _receipt(c: Connection, row: Any) -> dict[str, Any]:
    actor_name = c.execute(
        select(tables.users.c.display_name).where(
            tables.users.c.tenant_id == row["tenant_id"],
            tables.users.c.id == row["actor_user_id"],
        )
    ).scalar_one()
    return _plain({**dict(row), "actor_name": actor_name})


def _read(
    c: Connection, context: AuthContext, project: UUID, run: UUID, before_id: UUID | None = None
) -> dict[str, Any]:
    authorize(c, context, project, write=False)
    application = _application(c, context.tenant.id, project, run)
    if application is None:
        if before_id is not None:
            raise IssueApplicationError("SAMPLE_CURSOR_INVALID", "请从原应用的抽检历史继续读取")
        return dict(
            application_id=None,
            can_review=False,
            expected_digest=None,
            history=[],
            next_before_id=None,
            notice="原运行尚未形成可抽检的自动应用。",
        )
    snapshot = _snapshot(c, application)
    may_write = True
    try:
        authorize(c, context, project, write=True)
    except PermissionError:
        may_write = False
    can_review = _sampled(application) and may_write and snapshot["withdrawn_at"] is None
    t = tables.ai_issue_sample_reviews
    query = select(t).where(
        t.c.tenant_id == context.tenant.id,
        t.c.project_id == project,
        t.c.application_id == application["id"],
    )
    if before_id is not None:
        cursor = c.execute(query.where(t.c.id == before_id)).mappings().one_or_none()
        if cursor is None:
            raise IssueApplicationError("SAMPLE_CURSOR_INVALID", "请从原应用的抽检历史继续读取")
        query = query.where(t.c.version < cursor["version"])
    rows = list(c.execute(query.order_by(t.c.version.desc()).limit(21)).mappings())
    notice = (
        "请核对本次自动应用的当前问题。接受只记录抽检意见；需修正请到原问题具名办理。"
        if can_review
        else "原问题已撤回，抽检历史保留。"
        if snapshot["withdrawn_at"]
        else "本次应用未被选入自动抽检。"
        if not _sampled(application)
        else "当前仅可读取原抽检记录，没有办理权限。"
    )
    return _plain(
        dict(
            application_id=application["id"],
            can_review=can_review,
            expected_digest=digest(snapshot) if can_review else None,
            history=[_receipt(c, row) for row in rows[:20]],
            next_before_id=rows[19]["id"] if len(rows) > 20 else None,
            notice=notice,
        )
    )


class IssueSampleReviews:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self, context: AuthContext, project: UUID, run: UUID, before_id: UUID | None = None
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return _read(c, context, project, run, before_id)

    def change(
        self, context: AuthContext, project: UUID, run: UUID, change: SampleReviewRequest
    ) -> dict[str, Any]:
        tenant, actor = context.tenant.id, context.user.id
        signature = digest(
            dict(
                project_id=str(project),
                run_id=str(run),
                **change.model_dump(mode="json", exclude={"request_id"}),
            )
        )
        with self.engine.begin() as c:
            c.execute(
                select(tables.tenants.c.id).where(tables.tenants.c.id == tenant).with_for_update()
            )
            if not lock_project_write_scope(c, tenant_id=tenant, project_id=project):
                raise LookupError("原项目已不可办理")
            authorize(c, context, project, write=True)
            application = _application(c, tenant, project, run)
            t = tables.ai_issue_sample_reviews
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
                    raise IssueApplicationError("REQUEST_ID_REUSED", "本请求已用于其他抽检意见")
                return {
                    **_read(c, context, project, run),
                    "replayed": True,
                    "review_receipt": _receipt(c, old),
                }
            if not _sampled(application):
                raise IssueApplicationError(
                    "SAMPLE_NOT_SELECTED", "只有选入抽检的自动应用可记录意见"
                )
            assert application is not None
            c.execute(
                select(tables.issues.c.id)
                .where(
                    tables.issues.c.tenant_id == tenant,
                    tables.issues.c.project_id == project,
                    tables.issues.c.id == application["issue_id"],
                )
                .with_for_update()
            ).scalar_one()
            snapshot = _snapshot(c, application)
            if snapshot["withdrawn_at"] is not None:
                raise IssueApplicationError("SAMPLE_ISSUE_WITHDRAWN", "原问题已撤回，抽检历史保留")
            issue_digest = digest(snapshot)
            if issue_digest != change.expected_digest:
                raise IssueApplicationError(
                    "SAMPLE_ISSUE_CHANGED", "原问题已有变化，请刷新并重新核对"
                )
            version = (
                c.execute(
                    select(func.coalesce(func.max(t.c.version), 0)).where(
                        t.c.tenant_id == tenant, t.c.application_id == application["id"]
                    )
                ).scalar_one()
                + 1
            )
            identity, now = uuid4(), c.execute(select(func.clock_timestamp())).scalar_one()
            after = dict(
                review_id=str(identity),
                application_id=str(application["id"]),
                issue_id=str(application["issue_id"]),
                version=version,
                verdict=change.verdict,
                reason=change.reason,
                issue_digest=issue_digest,
                issue_snapshot=snapshot,
            )
            written = EventAuditWriter(
                c, tenant_id=tenant, project_id=project, actor_user_id=actor
            ).record(
                EventDraft(
                    event_id=f"ai-issue-sample:{identity}",
                    event_type="AI_ISSUE_SAMPLE_REVIEWED",
                    source="ai_issue_sample_service",
                    entity_id=identity,
                    occurred_at=now,
                    payload={
                        key: after[key]
                        for key in ("review_id", "application_id", "issue_id", "verdict")
                    },
                ),
                AuditDraft(action="ai_issue.sample_review", after_snapshot=after),
            )
            saved = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=tenant,
                        project_id=project,
                        application_id=application["id"],
                        issue_id=application["issue_id"],
                        actor_user_id=actor,
                        request_id=change.request_id,
                        request_digest=signature,
                        version=version,
                        verdict=change.verdict,
                        reason=change.reason,
                        issue_snapshot=snapshot,
                        issue_digest=issue_digest,
                        issue_updated_at=datetime.fromisoformat(snapshot["updated_at"]),
                        output_event_row_id=written.event_row_id,
                        created_at=now,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            return {
                **_read(c, context, project, run),
                "replayed": False,
                "review_receipt": _receipt(c, saved),
            }
