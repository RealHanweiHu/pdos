"""Reverse unconsumed AI Issue creation; preserve the business history and receipts."""

from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, RowMapping, func, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.ai_issue_write_access import authorize
from app.domain.ai_write_policy import WritePolicyError
from app.domain.issues import IssueService, _issue_snapshot
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

REASONS = {
    "reused_issue": "原问题仅被复用，不能在此撤回原业务记录。",
    "already_withdrawn": "该问题已经撤回，原历史保留。",
    "human_edited": "该问题已经被后续编辑或办理，请沿原问题继续处理。",
    "source_changed": "原测试或其关联已经变化，请先核对原业务记录。",
    "business_reference": "该问题已被其他记录引用，请沿原业务记录处理。",
    "reference_needs_review": "存在待核对的历史引用，暂不自动撤回。",
    "withdrawn": "已撤回AI创建的问题，并恢复本次创建前的测试关联；历史保留。",
}


class WithdrawalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    reason: str = Field(min_length=1, max_length=1000)


class SingleWithdrawalRequest(WithdrawalRequest):
    application_id: UUID


def _issue(c: Connection, app: Any, *, lock: bool = False) -> RowMapping:
    t = tables.issues
    query = select(t).where(
        t.c.tenant_id == app["tenant_id"],
        t.c.project_id == app["project_id"],
        t.c.id == app["issue_id"],
    )
    return c.execute(query.with_for_update() if lock else query).mappings().one()


def _eligibility(c: Connection, app: Any, issue: Any) -> tuple[str | None, str | None]:
    if app["disposition"] != "created":
        return "reused_issue", None
    if issue["withdrawn_at"] is not None:
        return "already_withdrawn", None
    if issue["created_by_ai_principal_id"] != app["principal_id"] or issue["status"] != "open":
        return "human_edited", None
    record = IssueService._get_record(
        c, tenant_id=app["tenant_id"], project_id=app["project_id"], issue_id=app["issue_id"]
    )
    current = {
        "id": str(record.id),
        "updated_at": record.updated_at.isoformat(),
        **_issue_snapshot(record),
    }
    original = dict(app["receipt"]["issue_snapshot"])
    for value in (current, original):
        value.pop("withdrawn_at", None)
        value.pop("ai_withdrawal_id", None)
    if current != original:
        return "human_edited", None
    case_after = app["receipt"].get("source_case_after")
    if not isinstance(case_after, dict) or not case_after.get("id"):
        return "source_changed", None
    case = (
        c.execute(
            select(tables.test_cases).where(
                tables.test_cases.c.tenant_id == app["tenant_id"],
                tables.test_cases.c.project_id == app["project_id"],
                tables.test_cases.c.id == UUID(case_after["id"]),
            )
        )
        .mappings()
        .one_or_none()
    )
    if case is None or _plain(dict(case)) != case_after:
        return "source_changed", None
    from app.domain.ai_issue_withdrawal_references import withdrawal_reference

    reference = withdrawal_reference(c, app["tenant_id"], app["project_id"], app["issue_id"], app)
    if reference:
        return (
            "reference_needs_review"
            if any(v in reference.lower() for v in ("unknown", "review", "unclassified"))
            else "business_reference"
        ), reference
    return None, None


def _receipt(c: Connection, row: Any) -> dict[str, Any]:
    name = c.execute(
        select(tables.users.c.display_name).where(
            tables.users.c.tenant_id == row["tenant_id"], tables.users.c.id == row["actor_user_id"]
        )
    ).scalar_one()
    return _plain({**dict(row), "actor_name": name})


def application_withdrawal_state(c: Connection, app: Any, *, may_write: bool) -> dict[str, Any]:
    issue = _issue(c, app)
    reason, _ = _eligibility(c, app, issue)
    t = tables.ai_issue_withdrawal_receipts
    previous = None
    if issue["ai_withdrawal_id"] is not None:
        previous = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == app["tenant_id"],
                    t.c.project_id == app["project_id"],
                    t.c.id == issue["ai_withdrawal_id"],
                )
            )
            .mappings()
            .one()
        )
    return _plain(
        {
            "withdrawn_at": issue["withdrawn_at"],
            "can_withdraw": may_write and reason is None,
            "withdrawal_notice": REASONS[reason]
            if reason
            else (
                "可以撤回本次AI创建的问题；不会删除原建议、调用和办理历史。"
                if may_write
                else "当前没有撤回该问题的办理权限。"
            ),
            "withdrawal_receipt": _receipt(c, previous) if previous else None,
        }
    )


class IssueWithdrawalService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def withdraw(
        self,
        context: AuthContext,
        project_id: UUID,
        run_id: UUID,
        change: WithdrawalRequest | SingleWithdrawalRequest,
    ) -> dict[str, Any]:
        tenant, actor = context.tenant.id, context.user.id
        application_id = (
            change.application_id if isinstance(change, SingleWithdrawalRequest) else None
        )
        kind = "single" if application_id else "run"
        fingerprint = digest(
            {
                "project_id": str(project_id),
                "run_id": str(run_id),
                "kind": kind,
                **change.model_dump(mode="json", exclude={"request_id"}),
            }
        )
        with self.engine.begin() as c:
            c.execute(
                select(tables.tenants.c.id).where(tables.tenants.c.id == tenant).with_for_update()
            )
            if not lock_project_write_scope(c, tenant_id=tenant, project_id=project_id):
                raise LookupError("原项目已不可办理")
            authorize(c, context, project_id, write=True)
            t = tables.ai_issue_withdrawal_receipts
            previous = (
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
            if previous:
                if previous["request_digest"] != fingerprint:
                    raise WritePolicyError("REQUEST_ID_REUSED", "该请求已用于另一撤回操作")
                return _receipt(c, previous)
            a = tables.ai_issue_applications
            query = select(a).where(
                a.c.tenant_id == tenant, a.c.project_id == project_id, a.c.run_id == run_id
            )
            if application_id:
                query = query.where(a.c.id == application_id)
            apps = list(c.execute(query.order_by(a.c.id).with_for_update()).mappings())
            if not apps:
                raise LookupError("本次运行没有可核对的办理记录")
            receipt_id, now = uuid4(), c.execute(select(func.clock_timestamp())).scalar_one()
            items: list[dict[str, Any]] = []
            for app in apps:
                issue = _issue(c, app, lock=True)
                case_after = app["receipt"].get("source_case_after")
                if isinstance(case_after, dict) and case_after.get("id"):
                    c.execute(
                        select(tables.test_cases.c.id)
                        .where(
                            tables.test_cases.c.tenant_id == tenant,
                            tables.test_cases.c.project_id == project_id,
                            tables.test_cases.c.id == UUID(case_after["id"]),
                        )
                        .with_for_update()
                    )
                reason, reference = _eligibility(c, app, issue)
                item: dict[str, Any] = {
                    "application_id": str(app["id"]),
                    "issue_id": str(app["issue_id"]),
                    "status": "skipped" if reason else "withdrawn",
                    "reason_code": reason or "withdrawn",
                    "reason": REASONS[reason or "withdrawn"],
                    "reference_check": reference,
                }
                if reason is None:
                    # No business status edge is fabricated: open/analysis history is
                    # separate from the withdrawal overlay used by active projections.
                    c.execute(
                        tables.issues.update()
                        .where(
                            tables.issues.c.tenant_id == tenant,
                            tables.issues.c.project_id == project_id,
                            tables.issues.c.id == app["issue_id"],
                            tables.issues.c.withdrawn_at.is_(None),
                        )
                        .values(withdrawn_at=now, ai_withdrawal_id=receipt_id, updated_at=now)
                    )
                    before_case = app["receipt"]["source_case_before"]
                    restored = before_case.get("related_issue_id")
                    c.execute(
                        tables.test_cases.update()
                        .where(
                            tables.test_cases.c.tenant_id == tenant,
                            tables.test_cases.c.project_id == project_id,
                            tables.test_cases.c.id == UUID(case_after["id"]),
                            tables.test_cases.c.related_issue_id == app["issue_id"],
                        )
                        .values(
                            related_issue_id=UUID(restored) if restored else None, updated_at=now
                        )
                    )
                    item.update(
                        issue_before=_plain(dict(issue)),
                        source_case_before=case_after,
                        source_case_restored_issue_id=restored,
                        withdrawn_at=now.isoformat(),
                    )
                items.append(item)
            values = dict(
                id=receipt_id,
                tenant_id=tenant,
                project_id=project_id,
                run_id=run_id,
                application_id=application_id,
                actor_user_id=actor,
                request_id=change.request_id,
                request_digest=fingerprint,
                kind=kind,
                reason=change.reason,
                items=items,
                created_at=now,
            )
            c.execute(t.insert().values(**values))
            EventAuditWriter(
                c, tenant_id=tenant, project_id=project_id, actor_user_id=actor
            ).record(
                EventDraft(
                    event_id=f"ai-issue-withdrawal:{receipt_id}",
                    event_type="AI_ISSUE_WITHDRAWAL_RECORDED",
                    source="ai_issue_withdrawal_service",
                    entity_id=receipt_id,
                    occurred_at=now,
                    payload={
                        "withdrawal_id": str(receipt_id),
                        "run_id": str(run_id),
                        "items": items,
                    },
                ),
                AuditDraft(
                    action="ai_issue.withdraw",
                    after_snapshot={
                        "withdrawal_id": str(receipt_id),
                        "kind": kind,
                        "reason": change.reason,
                        "items": items,
                    },
                    context={"run_id": str(run_id), "actor_user_id": str(actor)},
                ),
            )
            # Latch an automatic-writing stop in the withdrawal transaction,
            # rather than waiting for another model call to notice the threshold.
            from app.domain.ai_issue_write_monitor import quality_monitor

            for app, item in zip(apps, items, strict=True):
                execution = app["receipt"].get("write_receipt")
                if app["capture_mode"] == "direct" and item["status"] == "withdrawn":
                    assert isinstance(execution, dict)
                    quality_monitor(
                        c,
                        tenant_id=tenant,
                        project_id=project_id,
                        policy_id=app["policy_id"],
                        binding_digest=execution["binding_digest"],
                        protocol_id=UUID(execution["protocol_id"]),
                        configuration=execution["configuration"],
                        as_of=now,
                    )
            return _receipt(c, values)
