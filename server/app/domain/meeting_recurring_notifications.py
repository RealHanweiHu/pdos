"""Standing notice authority for newly generated meetings, retained with booking receipts."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain import meeting_notifications as notices
from app.domain.meeting_recurring_conferences import authority
from app.domain.meeting_rescheduling import record
from app.domain.meetings import MeetingStateError
from app.domain.product_workspace import _plain, digest
from app.settings import Settings


def notification_scope(
    c: Connection, ctx: AuthContext, project: UUID, source: Any, mode: str, settings: Settings
) -> dict[str, Any] | None:
    if mode == "none":
        return None
    participants = {
        p["user_id"]: p.get("participation", "required") for p in source["default_participants"]
    }
    participants[str(ctx.user.id)] = "organizer"
    if len(participants) > 100:
        raise MeetingStateError("周期自动通知最多100位参会人，请调整名单或使用单场通知")
    u, b, member = tables.users, tables.dingtalk_user_bindings, tables.project_members
    rows = c.execute(
        select(
            u.c.id,
            u.c.display_name,
            b.c.id.label("binding_id"),
            b.c.staff_id,
            b.c.corp_id,
            b.c.bound_at,
        )
        .select_from(
            u.join(
                member, (member.c.tenant_id == u.c.tenant_id) & (member.c.user_id == u.c.id)
            ).outerjoin(
                b,
                (b.c.tenant_id == u.c.tenant_id)
                & (b.c.user_id == u.c.id)
                & (b.c.status == "active"),
            )
        )
        .where(
            u.c.tenant_id == ctx.tenant.id,
            u.c.id.in_([UUID(id) for id in participants]),
            u.c.is_active.is_(True),
            u.c.role.in_(notices.READ_ROLES),
            member.c.project_id == project,
        )
    ).mappings()
    people = sorted([_plain(row) for row in rows], key=lambda p: p["id"])
    if {p["id"] for p in people} != set(participants):
        raise MeetingStateError("默认参会人须仍具备当前项目和会议读取权限")
    channel = notices.channel(c, ctx.tenant.id, settings) if mode == "dingtalk" else None
    if mode == "dingtalk" and channel is None:
        raise MeetingStateError("自动钉钉通知须先配置当前企业的个人消息通道")
    recipients = []
    for p in people:
        if mode != "dingtalk":
            p = {key: p[key] for key in ("id", "display_name")}
        recipients.append({**p, "participation": participants[p["id"]], "eligible": True})
    return {"mode": mode, "recipients": recipients, "channel": channel}


def approval(c: Connection, row: Any) -> dict[str, Any]:
    a = tables.audit_log
    receipt = (
        c.execute(
            select(a.c.id, a.c.after_snapshot)
            .where(
                a.c.tenant_id == row["tenant_id"],
                a.c.project_id == row["project_id"],
                a.c.entity_id == row["recurrence_id"],
                a.c.actor_user_id == row["organizer_user_id"],
                a.c.action == "meeting_recurrence.automation_changed",
                a.c.after_snapshot["policy"]["id"].astext == str(row["id"]),
                a.c.after_snapshot["policy"]["version"].astext == str(row["version"]),
            )
            .order_by(a.c.id.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if receipt is None or authority(receipt["after_snapshot"]["policy"]) != authority(row):
        raise MeetingStateError("未找到本版自动通知的原具名授权")
    return {"policy": authority(row), "approval_audit_id": receipt["id"]}


def validate_authority(
    c: Connection,
    frozen: dict[str, Any],
    tenant: UUID,
    project: UUID,
    actor: UUID,
    meeting_id: UUID,
    now: datetime,
) -> Any:
    p, r, m, u, a = (
        tables.meeting_generation_policies,
        tables.meeting_recurrences,
        tables.meetings,
        tables.users,
        tables.audit_log,
    )
    row = (
        c.execute(
            select(p).where(
                p.c.tenant_id == tenant,
                p.c.project_id == project,
                p.c.id == UUID(frozen["policy"]["id"]),
            )
        )
        .mappings()
        .one_or_none()
    )
    if (
        row is None
        or row["status"] != "enabled"
        or not row["notification_scope"]
        or row["organizer_user_id"] != actor
        or authority(row) != frozen["policy"]
    ):
        raise MeetingStateError("原自动通知授权已调整或暂停，请在单场会议重新核对")
    source = (
        c.execute(
            select(r).where(
                r.c.tenant_id == tenant, r.c.project_id == project, r.c.id == row["recurrence_id"]
            )
        )
        .mappings()
        .one()
    )
    meeting = (
        c.execute(
            select(m).where(
                m.c.tenant_id == tenant, m.c.project_id == project, m.c.id == meeting_id
            )
        )
        .mappings()
        .one()
    )
    version = c.execute(
        select(u.c.auth_version).where(
            u.c.tenant_id == tenant, u.c.id == actor, u.c.is_active.is_(True)
        )
    ).scalar_one_or_none()
    approved = c.execute(
        select(a.c.id).where(
            a.c.tenant_id == tenant,
            a.c.project_id == project,
            a.c.id == frozen["approval_audit_id"],
            a.c.actor_user_id == actor,
            a.c.entity_id == row["recurrence_id"],
            a.c.action == "meeting_recurrence.automation_changed",
            a.c.after_snapshot["policy"]["version"].astext == str(row["version"]),
            a.c.after_snapshot["policy"]["id"].astext == str(row["id"]),
        )
    ).scalar_one_or_none()
    if (
        approved is None
        or version != row["organizer_auth_version"]
        or source["status"] != "active"
        or digest(_plain(source)) != row["recurrence_digest"]
        or meeting["recurrence_id"] != row["recurrence_id"]
        or str(meeting["occurrence_date"]) != frozen["occurrence_date"]
        or not row["active_from"] <= meeting["occurrence_date"] <= row["active_until"]
        or now.astimezone(ZoneInfo(source["timezone"])).date() > row["active_until"]
    ):
        raise MeetingStateError("自动通知的原周期、组织人身份或适用日期需要重新核对")
    return row


def register(
    c: Connection,
    ctx: AuthContext,
    frozen: dict[str, Any],
    meeting_id: UUID,
    settings: Settings,
    now: datetime,
    conference_request_id: UUID | None = None,
) -> dict[str, Any]:
    project = UUID(frozen["policy"]["project_id"])
    row = validate_authority(c, frozen, ctx.tenant.id, project, ctx.user.id, meeting_id, now)
    scope = row["notification_scope"]
    id = uuid5(row["id"], f"notification:{row['version']}:{meeting_id}")
    prior = c.execute(
        select(notices.T.c.id).where(notices.T.c.tenant_id == ctx.tenant.id, notices.T.c.id == id)
    ).scalar_one_or_none()
    if prior is not None:
        return {"status": "registered", "batch_id": str(id)}
    draft = notices.Draft(
        request_id=id,
        kind="invite",
        dingtalk=scope["mode"] == "dingtalk",
        recipient_user_ids=tuple(UUID(p["id"]) for p in scope["recipients"]),
        reason=f"周期第{row['version']}版具名授权通知本次新生成场次",
    )
    snap = notices.snapshot(c, ctx, project, meeting_id, draft, settings)
    actual = {p["id"]: p for p in snap["recipients"]}
    if (
        snap["channel"] != scope["channel"]
        or any({k: actual.get(p["id"], {}).get(k) for k in p} != p for p in scope["recipients"])
        or {p["id"] for p in notices.roster(c, ctx.tenant.id, project, meeting_id)} != set(actual)
    ):
        raise MeetingStateError("本场参会名单或钉钉绑定已变化，请在单场会议重新预览通知")
    snap["standing_authority"] = frozen
    snap["conference_request_id"] = str(conference_request_id) if conference_request_id else None
    notices.register(c, ctx, project, meeting_id, id, digest(snap), snap, settings)
    return {"status": "registered", "batch_id": str(id), "mode": scope["mode"]}


def local(
    c: Connection, ctx: AuthContext, row: Any, meeting_id: UUID, settings: Settings, now: datetime
) -> dict[str, Any] | None:
    if not row["notification_scope"]:
        return None
    if row["conference_provider"]:
        return {"status": "waiting_conference", "mode": row["notification_scope"]["mode"]}
    meeting = record(c, ctx, row["project_id"], meeting_id)
    frozen = {**approval(c, row), "occurrence_date": str(meeting["occurrence_date"])}
    return register(c, ctx, frozen, meeting_id, settings, now)


def after_booking(
    c: Connection,
    ctx: AuthContext | None,
    request: Any,
    result: dict[str, Any],
    settings: Settings,
    now: datetime,
) -> None:
    frozen = request["snapshot"].get("standing_authority")
    if (
        request["operation"] != "create"
        or not frozen
        or not frozen["policy"].get("notification_scope")
    ):
        return
    if not result.get("matches_current_meeting"):
        result["notification"] = {
            "status": "needs_review",
            "message": "预约未绑定当前安排，请核对本场会议后通知",
        }
        return
    try:
        with c.begin_nested():
            if (
                ctx is None
                or ctx.tenant.id != request["tenant_id"]
                or ctx.tenant.status != "active"
                or not ctx.user.is_active
                or ctx.user.auth_version != request["actor_auth_version"]
            ):
                raise MeetingStateError("原组织者身份或授权已变化，请重新核对参会通知")
            notice = register(c, ctx, frozen, request["meeting_id"], settings, now, request["id"])
        result["notification"] = notice
    except Exception as error:
        # Keep the real booking receipt even if notice registration fails. A new
        # explicit single-meeting notice is available; never retry the booking.
        result["notification"] = {
            "status": "needs_review",
            "message": str(error)
            if isinstance(error, MeetingStateError)
            else "通知登记未完成，请在本场通知入口重新核对",
        }
