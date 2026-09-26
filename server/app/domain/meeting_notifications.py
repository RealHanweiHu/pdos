"""Explicit, version-bound meeting notices using the existing reminder/outbox ledgers."""

from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID, uuid5

from pydantic import Field, model_validator
from sqlalchemy import ColumnElement, Connection, Engine, and_, exists, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.meeting_conference_requests import meeting_snapshot
from app.domain.meeting_recurrence_commands import authorize
from app.domain.meeting_rescheduling import record
from app.domain.meetings import MeetingNotFoundError, MeetingStateError
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.integrations.dingtalk_delivery import DingTalkDeliveryError
from app.integrations.dingtalk_outbox import DingTalkIntentService
from app.settings import Settings

T = tables.meeting_notification_batches
LABELS = {"invite": "参会通知", "update": "会议安排更新", "cancel": "会议取消通知"}
READ_ROLES = tuple(r.value for r in Role if is_allowed(r, Action.MEETING_VIEW))


class Draft(Contract):
    request_id: UUID
    kind: Literal["invite", "update", "cancel"]
    recipient_user_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)
    dingtalk: bool = False
    reason: Text

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len(set(self.recipient_user_ids)) != len(self.recipient_user_ids):
            raise ValueError("收件人不能重复")
        return self


class Submit(Draft):
    preview_digest: Digest
    confirmed: Literal[True]


def recipient_scope(user: Any, meeting: Any) -> ColumnElement[bool]:
    member, participant = tables.project_members, tables.meeting_participants
    return and_(
        user.c.is_active.is_(True),
        user.c.role.in_(READ_ROLES),
        exists(
            select(member.c.id)
            .correlate(user, meeting)
            .where(
                member.c.tenant_id == meeting.c.tenant_id,
                member.c.project_id == meeting.c.project_id,
                member.c.user_id == user.c.id,
            )
        ),
        exists(
            select(participant.c.id)
            .correlate(user, meeting)
            .where(
                participant.c.tenant_id == meeting.c.tenant_id,
                participant.c.meeting_id == meeting.c.id,
                participant.c.user_id == user.c.id,
            )
        ),
    )


def visible() -> ColumnElement[bool]:
    r, m, u, tenant = tables.reminders, tables.meetings, tables.users, tables.tenants
    return exists(
        select(m.c.id)
        .select_from(m)
        .correlate(r)
        .join(u, (u.c.tenant_id == m.c.tenant_id) & (u.c.id == r.c.recipient_user_id))
        .join(tenant, tenant.c.id == m.c.tenant_id)
        .where(
            m.c.tenant_id == r.c.tenant_id,
            m.c.project_id == r.c.project_id,
            m.c.id == r.c.target_entity_id,
            m.c.deleted_at.is_(None),
            tenant.c.status == "active",
            recipient_scope(u, m),
        )
    )


def roster(c: Connection, tenant: UUID, project: UUID, meeting: UUID) -> list[dict[str, Any]]:
    p, u, m, b = (
        tables.meeting_participants,
        tables.users,
        tables.meetings,
        tables.dingtalk_user_bindings,
    )
    rows = c.execute(
        select(
            u.c.id,
            u.c.display_name,
            p.c.participation,
            recipient_scope(u, m).label("eligible"),
            b.c.id.label("binding_id"),
            b.c.staff_id,
            b.c.corp_id,
            b.c.bound_at,
        )
        .select_from(
            p.join(u, (u.c.tenant_id == p.c.tenant_id) & (u.c.id == p.c.user_id))
            .join(m, (m.c.tenant_id == p.c.tenant_id) & (m.c.id == p.c.meeting_id))
            .outerjoin(
                b,
                (b.c.tenant_id == p.c.tenant_id)
                & (b.c.user_id == p.c.user_id)
                & (b.c.status == "active"),
            )
        )
        .where(p.c.tenant_id == tenant, p.c.meeting_id == meeting, m.c.project_id == project)
        .order_by(u.c.display_name, u.c.id)
    ).mappings()
    return [_plain(row) for row in rows]


def channel(c: Connection, tenant: UUID, settings: Settings) -> dict[str, Any] | None:
    t = tables.dingtalk_tenant_bindings
    row = (
        c.execute(
            select(t.c.corp_id, t.c.client_id, t.c.robot_code).where(
                t.c.tenant_id == tenant,
                t.c.status == "active",
                t.c.client_id == settings.dingtalk_client_id,
                t.c.robot_code.is_not(None),
            )
        )
        .mappings()
        .one_or_none()
    )
    return _plain(row) if row is not None else None


def snapshot(
    c: Connection, ctx: AuthContext, project: UUID, id: UUID, draft: Draft, settings: Settings
) -> dict[str, Any]:
    authorize(c, ctx, project, write=True)
    row = record(c, ctx, project, id)
    if row["deleted_at"] or row["archived_at"]:
        raise MeetingStateError("归档或删除的会议保留历史通知")
    if draft.kind == "cancel":
        if row["status"] != "cancelled":
            raise MeetingStateError("请先在原会议中完成取消，再通知参会人")
    elif row["status"] != "scheduled" or row["scheduled_start_at"] <= datetime.now(UTC):
        raise MeetingStateError("仅未开始的已排程会议可发送参会或改期通知")
    people = {p["id"]: p for p in roster(c, ctx.tenant.id, project, id)}
    chosen = []
    for user_id in sorted(draft.recipient_user_ids, key=str):
        p = people.get(str(user_id))
        if p is None or not p["eligible"]:
            raise MeetingStateError("收件人须为当前有效项目成员和本场参会人，请刷新名单")
        chosen.append(p)
    delivery_channel = channel(c, ctx.tenant.id, settings) if draft.dingtalk else None
    base = (
        DingTalkIntentService(c.engine, settings)._validated_public_base_url()
        if draft.dingtalk
        else ""
    )
    title = f"{LABELS[draft.kind]}：{row['title']}"[:512]
    # User titles are rendered as text, never as Markdown links or inline HTML.
    import html
    import re

    safe_title = (
        re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", html.escape(title))
        .replace("\n", " ")
        .replace("\r", " ")
    )
    text = (
        f"{safe_title}\n\n原安排：{row['scheduled_start_at'].isoformat()} — "
        f"{row['scheduled_end_at'].isoformat()}\n\n"
        f"[查看会议当前安排]({base}/projects?project={project}&tab=decisions&meeting={id})"
    )
    recipients = []
    for p in chosen:
        skip = None
        if draft.dingtalk:
            if not delivery_channel:
                skip = "企业消息通道未配置"
            elif not p["binding_id"] or p["corp_id"] != delivery_channel["corp_id"]:
                skip = "参会人未绑定当前企业钉钉账号"
        recipients.append({**p, "dingtalk_skip": skip})
    return {
        "meeting": meeting_snapshot(row),
        "actor_name": ctx.user.display_name,
        "kind": draft.kind,
        "reason": draft.reason,
        "dingtalk": draft.dingtalk,
        "channel": delivery_channel,
        "recipients": recipients,
        "title": title,
        "text": text if draft.dingtalk else None,
        "delivery_enabled": settings.dingtalk_delivery_enabled if draft.dingtalk else False,
    }


def preview(
    engine: Engine, ctx: AuthContext, project: UUID, id: UUID, draft: Draft, settings: Settings
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        value = snapshot(c, ctx, project, id, draft, settings)
        return {"snapshot": value, "preview_digest": digest(value)}


def reminder_id(batch: UUID, user: str) -> UUID:
    return uuid5(batch, f"meeting-notice:{user}")


def dm_payload(batch: UUID, user: dict[str, Any], snap: dict[str, Any]) -> dict[str, str]:
    return {
        "batch_id": str(batch),
        "recipient_user_id": user["id"],
        "staff_id": user["staff_id"],
        "title": "PDOS 会议通知",
        "text": snap["text"],
    }


def receipt(c: Connection, row: Any) -> dict[str, Any]:
    snap = row["snapshot"]
    ids = [reminder_id(row["id"], p["id"]) for p in snap["recipients"]]
    r, o = tables.reminders, tables.integration_outbox
    reminders = {
        str(item["recipient_user_id"]): _plain(item)
        for item in c.execute(
            select(
                r.c.id, r.c.recipient_user_id, r.c.status, r.c.fired_at, r.c.acknowledged_at
            ).where(r.c.tenant_id == row["tenant_id"], r.c.id.in_(ids))
        ).mappings()
    }
    outboxes = {
        item["payload"]["recipient_user_id"]: _plain(item)
        for item in c.execute(
            select(
                o.c.id,
                o.c.payload,
                o.c.status,
                o.c.attempt_count,
                o.c.remote_reference,
                o.c.last_error_code,
                o.c.updated_at,
            ).where(
                o.c.tenant_id == row["tenant_id"],
                o.c.project_id == row["project_id"],
                o.c.operation == "meeting_invite_dm",
                o.c.payload["batch_id"].astext == str(row["id"]),
            )
        ).mappings()
    }
    for item in outboxes.values():
        item.pop("payload")
    return {
        **_plain(row),
        "receipts": [
            {
                "user_id": p["id"],
                "name": p["display_name"],
                "in_app": reminders.get(p["id"]),
                "dingtalk": outboxes.get(p["id"]),
                "dingtalk_skip": p["dingtalk_skip"],
            }
            for p in snap["recipients"]
        ],
    }


def read(
    engine: Engine,
    ctx: AuthContext,
    project: UUID,
    id: UUID,
    settings: Settings,
    before: int | None = None,
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        status = authorize(c, ctx, project)
        meeting = record(c, ctx, project, id)
        # Binding identities and recipient receipts belong to meeting managers.
        if not is_allowed(ctx.user.role, Action.MEETING_MANAGE):
            return {"can_manage": False, "items": [], "participants": [], "next_before_id": None}
        q = select(T).where(
            T.c.tenant_id == ctx.tenant.id, T.c.project_id == project, T.c.meeting_id == id
        )
        if before is not None:
            q = q.where(T.c.sequence < before)
        rows = list(c.execute(q.order_by(T.c.sequence.desc()).limit(11)).mappings())
        return {
            "can_manage": status not in ("completed", "archived")
            and not meeting["deleted_at"]
            and not meeting["archived_at"],
            "meeting": meeting_snapshot(meeting),
            "participants": roster(c, ctx.tenant.id, project, id),
            "delivery_enabled": settings.dingtalk_delivery_enabled,
            "items": [receipt(c, r) for r in rows[:10]],
            "next_before_id": rows[9]["sequence"] if len(rows) > 10 else None,
        }


def submit(
    engine: Engine, ctx: AuthContext, project: UUID, id: UUID, command: Submit, settings: Settings
) -> dict[str, Any]:
    signature = digest({"meeting_id": str(id), **command.model_dump(mode="json")})
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
            raise MeetingNotFoundError
        authorize(c, ctx, project)
        if not is_allowed(ctx.user.role, Action.MEETING_MANAGE):
            raise MeetingStateError("当前没有会议通知管理权限")
        prior = c.execute(select(T).where(T.c.id == command.request_id)).mappings().one_or_none()
        if prior is not None:
            if (
                prior["tenant_id"],
                prior["project_id"],
                prior["actor_user_id"],
                prior["request_digest"],
            ) != (ctx.tenant.id, project, ctx.user.id, signature):
                raise MeetingStateError("该请求编号已用于其他内容")
            return receipt(c, prior)
        snap = snapshot(c, ctx, project, id, command, settings)
        if digest(snap) != command.preview_digest:
            raise MeetingStateError("安排、收件人或消息通道已变化，请重新预览")
        return register(c, ctx, project, id, command.request_id, signature, snap, settings)


def register(
    c: Connection,
    ctx: AuthContext,
    project: UUID,
    id: UUID,
    request_id: UUID,
    signature: str,
    snap: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    batch = (
        c.execute(
            T.insert()
            .values(
                id=request_id,
                tenant_id=ctx.tenant.id,
                project_id=project,
                meeting_id=id,
                actor_user_id=ctx.user.id,
                actor_auth_version=ctx.user.auth_version,
                request_digest=signature,
                snapshot=snap,
                created_at=now,
            )
            .returning(T)
        )
        .mappings()
        .one()
    )
    service = DingTalkIntentService(c.engine, settings)
    for user in snap["recipients"]:
        rid = reminder_id(request_id, user["id"])
        c.execute(
            tables.reminders.insert().values(
                id=rid,
                tenant_id=ctx.tenant.id,
                project_id=project,
                recipient_user_id=UUID(user["id"]),
                policy_key=f"meeting_{snap['kind']}",
                target_entity="meeting",
                target_entity_id=id,
                title=snap["title"],
                dedupe_key=f"meeting-notice:{request_id}:{user['id']}",
                fire_at=now,
                fired_at=now,
                status="fired",
                escalation_level=0,
                created_at=now,
                updated_at=now,
            )
        )
        if snap["dingtalk"] and user["dingtalk_skip"] is None:
            service._insert_outbox(
                c,
                tenant_id=ctx.tenant.id,
                project_id=project,
                actor_user_id=ctx.user.id,
                operation="meeting_invite_dm",
                idempotency_key=f"meeting-notice:{request_id}:{user['id']}",
                payload=dm_payload(request_id, user, snap),
            )
    EventAuditWriter(
        c, tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, project_id=project
    ).record(
        EventDraft(
            event_id=f"meeting-notice:{request_id}",
            event_type="MEETING_STATE_CHANGED",
            source="meeting_service",
            entity_id=id,
            payload={
                "meeting_id": str(id),
                "action": "notification_submitted",
                "meeting_type": snap["meeting"]["meeting_type"],
                "status": snap["meeting"]["status"],
            },
        ),
        AuditDraft(
            action="meeting.notification_submitted",
            before_snapshot=None,
            after_snapshot={"batch_id": str(request_id), "snapshot": snap},
            context={"request_id": str(request_id)},
        ),
    )
    return receipt(c, batch)


def validate_delivery(c: Connection, row: Any, settings: Settings) -> None:
    """Also runs on operator replay; a queued old invitation never follows new identity data."""

    def stale() -> None:
        raise DingTalkDeliveryError("MEETING_NOTIFICATION_CHANGED")

    try:
        batch_id = UUID(row["payload"]["batch_id"])
        user_id = UUID(row["payload"]["recipient_user_id"])
    except (KeyError, ValueError, TypeError):
        stale()
        return
    batch = (
        c.execute(
            select(T).where(
                T.c.id == batch_id,
                T.c.tenant_id == row["tenant_id"],
                T.c.project_id == row["project_id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    if batch is None:
        stale()
        return
    snap = batch["snapshot"]
    if snap.get("standing_authority"):
        from app.domain.meeting_recurring_notifications import validate_authority

        try:
            validate_authority(
                c,
                snap["standing_authority"],
                batch["tenant_id"],
                batch["project_id"],
                batch["actor_user_id"],
                batch["meeting_id"],
                datetime.now(UTC),
            )
        except MeetingStateError:
            stale()
    user = next((u for u in snap["recipients"] if u["id"] == str(user_id)), None)
    if not snap["dingtalk"] or user is None or user["dingtalk_skip"] is not None:
        stale()
        return
    m, a, tenant, project = tables.meetings, tables.users, tables.tenants, tables.projects
    meeting = (
        c.execute(
            select(m).where(
                m.c.tenant_id == batch["tenant_id"],
                m.c.project_id == batch["project_id"],
                m.c.id == batch["meeting_id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    actor = c.execute(
        select(a.c.role).where(
            a.c.tenant_id == batch["tenant_id"],
            a.c.id == batch["actor_user_id"],
            a.c.is_active.is_(True),
            a.c.auth_version == batch["actor_auth_version"],
        )
    ).scalar_one_or_none()
    active = c.execute(
        select(project.c.id)
        .join(tenant, tenant.c.id == project.c.tenant_id)
        .where(
            project.c.tenant_id == batch["tenant_id"],
            project.c.id == batch["project_id"],
            project.c.status.not_in(("completed", "archived")),
            tenant.c.status == "active",
        )
    ).scalar_one_or_none()
    if (
        meeting is None
        or active is None
        or actor is None
        or not is_allowed(Role(actor), Action.MEETING_MANAGE)
        or digest(meeting_snapshot(meeting)) != digest(snap["meeting"])
        or (snap["kind"] != "cancel" and meeting["scheduled_start_at"] <= datetime.now(UTC))
    ):
        stale()
        return
    from app.domain.knowledge_corrections import KnowledgeCorrectionService
    from app.domain.knowledge_push import KnowledgeAccessError

    try:
        KnowledgeCorrectionService._authorize(
            c,
            batch["tenant_id"],
            batch["actor_user_id"],
            batch["project_id"],
            Action.MEETING_MANAGE,
        )
    except KnowledgeAccessError:
        stale()
    current = next(
        (
            p
            for p in roster(c, batch["tenant_id"], batch["project_id"], batch["meeting_id"])
            if p["id"] == str(user_id)
        ),
        None,
    )
    frozen = {k: v for k, v in user.items() if k != "dingtalk_skip"}
    if (
        current != frozen
        or channel(c, batch["tenant_id"], settings) != snap["channel"]
        or dict(row["payload"]) != dm_payload(batch_id, user, snap)
        or row["idempotency_key"] != f"meeting-notice:{batch_id}:{user_id}"
    ):
        stale()
