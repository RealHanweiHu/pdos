"""Frozen, bounded recurring authority feeding the normal conference request queue."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain import meeting_conference_requests as conferences
from app.domain.meetings import MeetingStateError
from app.domain.product_workspace import _plain, digest
from app.settings import Settings

AUTHORITY_FIELDS = (
    "id",
    "tenant_id",
    "project_id",
    "recurrence_id",
    "version",
    "organizer_user_id",
    "organizer_auth_version",
    "active_from",
    "active_until",
    "lead_days",
    "recurrence_digest",
    "conference_provider",
    "conference_identity",
)


def authority(row: Any) -> dict[str, Any]:
    value = _plain({key: row[key] for key in AUTHORITY_FIELDS})
    if row.get("notification_scope") is not None:
        value["notification_scope"] = row["notification_scope"]
    return value


def pending(c: Connection, tenant: UUID, policy_id: UUID) -> list[Any]:
    t = conferences.T
    return list(
        c.execute(
            select(t)
            .where(
                t.c.tenant_id == tenant,
                t.c.status == "pending",
                t.c.snapshot["standing_authority"]["policy"]["id"].astext == str(policy_id),
            )
            .order_by(t.c.sequence)
        ).mappings()
    )


def withdraw_pending(c: Connection, ctx: AuthContext, row: Any, now: datetime) -> list[str]:
    ids = []
    for request in pending(c, ctx.tenant.id, row["id"]):
        # Match the worker's request lock without waiting behind active network IO.
        from sqlalchemy import text

        if not c.execute(
            text("SELECT pg_try_advisory_xact_lock(:key)"),
            {"key": conferences.lock_key(request["id"])},
        ).scalar_one():
            continue
        result = {
            "method": "policy_change",
            "outcome": "withdrawn",
            "evidence": "周期授权已经调整，旧版尚未派发请求撤回；原会议保留，可单独重新核对预约。",
            "confirmed_name": ctx.user.display_name,
            "confirmed_by": str(ctx.user.id),
        }
        c.execute(
            conferences.T.update()
            .where(conferences.T.c.id == request["id"], conferences.T.c.status == "pending")
            .values(status="withdrawn", completed_at=now, result=result)
        )
        conferences.emit(c, request, "authority_withdrawn", result, ctx.user.id)
        ids.append(str(request["id"]))
    return ids


def enqueue(
    c: Connection, ctx: AuthContext, row: Any, meeting_id: UUID, settings: Settings, now: datetime
) -> dict[str, Any]:
    provider = row["conference_provider"]
    if provider is None:
        return {"status": "local_only"}
    id = uuid5(row["id"], f"conference-create:{row['version']}:{meeting_id}")
    t = conferences.T
    previous = (
        c.execute(select(t).where(t.c.tenant_id == ctx.tenant.id, t.c.id == id))
        .mappings()
        .one_or_none()
    )
    if previous is not None:
        return {"request_id": str(id), "status": previous["status"], "provider": provider}
    meeting = (
        c.execute(
            select(tables.meetings).where(
                tables.meetings.c.tenant_id == ctx.tenant.id,
                tables.meetings.c.project_id == row["project_id"],
                tables.meetings.c.id == meeting_id,
            )
        )
        .mappings()
        .one()
    )
    a = tables.audit_log
    approval = c.execute(
        select(a.c.id)
        .where(
            a.c.tenant_id == ctx.tenant.id,
            a.c.project_id == row["project_id"],
            a.c.entity_id == row["recurrence_id"],
            a.c.action == "meeting_recurrence.automation_changed",
            a.c.after_snapshot["policy"]["id"].astext == str(row["id"]),
            a.c.after_snapshot["policy"]["version"].astext == str(row["version"]),
        )
        .order_by(a.c.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if approval is None:
        raise MeetingStateError("周期外部预约缺少原具名授权回执")
    draft = conferences.Draft(
        request_id=id,
        provider=provider,
        operation="create",
        expected_digest=digest(conferences.meeting_snapshot(meeting)),
        reason=f"周期会议第{row['version']}版具名授权自动预约",
    )
    snapshot = conferences.request_snapshot(c, ctx, row["project_id"], meeting_id, draft, settings)
    if snapshot["identity"] != row["conference_identity"]:
        raise MeetingStateError("外部会议账号映射已变化，请重新确认周期授权")
    snapshot["standing_authority"] = {
        "policy": authority(row),
        "approval_audit_id": approval,
        "occurrence_date": str(meeting["occurrence_date"]),
    }
    saved = (
        c.execute(
            t.insert()
            .values(
                id=id,
                provider=provider,
                tenant_id=ctx.tenant.id,
                project_id=row["project_id"],
                meeting_id=meeting_id,
                actor_user_id=ctx.user.id,
                actor_auth_version=ctx.user.auth_version,
                operation="create",
                request_digest=digest(snapshot),
                snapshot=snapshot,
                status="pending",
                created_at=now,
            )
            .returning(t)
        )
        .mappings()
        .one()
    )
    conferences.emit(c, saved, "queued", saved, ctx.user.id)
    return {
        "request_id": str(id),
        "status": "pending",
        "provider": provider,
        "service_enabled": conferences.enabled(settings, provider),
        "approval_audit_id": approval,
    }


def validate_dispatch(c: Connection, request: Any, now: datetime) -> dict[str, Any]:
    frozen = request["snapshot"]["standing_authority"]
    snapshot = frozen["policy"]
    p, r, m, a = (
        tables.meeting_generation_policies,
        tables.meeting_recurrences,
        tables.meetings,
        tables.audit_log,
    )
    row = (
        c.execute(
            select(p).where(
                p.c.tenant_id == request["tenant_id"],
                p.c.project_id == request["project_id"],
                p.c.id == UUID(snapshot["id"]),
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["status"] != "enabled" or authority(row) != snapshot:
        raise MeetingStateError("原周期外部预约授权已暂停或修订")
    source = (
        c.execute(
            select(r).where(
                r.c.tenant_id == request["tenant_id"],
                r.c.project_id == request["project_id"],
                r.c.id == row["recurrence_id"],
            )
        )
        .mappings()
        .one()
    )
    meeting = (
        c.execute(
            select(m).where(
                m.c.tenant_id == request["tenant_id"],
                m.c.project_id == request["project_id"],
                m.c.id == request["meeting_id"],
            )
        )
        .mappings()
        .one()
    )
    approval = (
        c.execute(
            select(a).where(
                a.c.tenant_id == request["tenant_id"],
                a.c.project_id == request["project_id"],
                a.c.id == frozen["approval_audit_id"],
                a.c.entity_id == row["recurrence_id"],
                a.c.action == "meeting_recurrence.automation_changed",
                a.c.actor_user_id == request["actor_user_id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    if (
        approval is None
        or authority(approval["after_snapshot"]["policy"]) != snapshot
        or digest(_plain(source)) != row["recurrence_digest"]
        or source["status"] != "active"
        or row["organizer_user_id"] != request["actor_user_id"]
        or row["conference_provider"] != request["provider"]
        or request["operation"] != "create"
        or meeting["recurrence_id"] != row["recurrence_id"]
        or str(meeting["occurrence_date"]) != frozen["occurrence_date"]
        or not row["active_from"] <= meeting["occurrence_date"] <= row["active_until"]
        or now.astimezone(ZoneInfo(source["timezone"])).date() > row["active_until"]
    ):
        raise MeetingStateError("周期授权、具名人员或适用日期已变化，原请求须重新核对")
    return frozen  # type: ignore[no-any-return]
