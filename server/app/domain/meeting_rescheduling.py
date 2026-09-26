"""Named local rescheduling and independently recorded external confirmation."""

from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, model_validator
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.meeting_recurrence_commands import authorize, replay
from app.domain.meetings import MeetingNotFoundError, MeetingStateError
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

RESCHEDULE = "meeting.rescheduled"
CONFIRM = "meeting.external_schedule_confirmed"


class Reschedule(Contract):
    request_id: UUID
    expected_digest: Digest
    scheduled_start_at: AwareDatetime
    scheduled_end_at: AwareDatetime
    reason: Text

    @model_validator(mode="after")
    def ordered(self) -> Self:
        duration = (
            self.scheduled_end_at.astimezone(UTC) - self.scheduled_start_at.astimezone(UTC)
        ).total_seconds()
        if not 300 <= duration <= 43200:
            raise ValueError("会议时长须在5分钟至12小时之间")
        return self


class ExternalConfirmation(Contract):
    request_id: UUID
    expected_digest: Digest
    external_handled: Literal[True]
    evidence: Text
    reason: Text


def record(c: Connection, ctx: AuthContext, project: UUID, id: UUID) -> Any:
    t = tables.meetings
    row = (
        c.execute(
            select(t).where(t.c.tenant_id == ctx.tenant.id, t.c.project_id == project, t.c.id == id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise MeetingNotFoundError
    return row


def external_signature(row: Any) -> str:
    return digest(
        _plain(
            {
                key: row[key]
                for key in (
                    "id",
                    "scheduled_start_at",
                    "scheduled_end_at",
                    "external_provider",
                    "external_meeting_id",
                    "external_join_url",
                    "external_bound_at",
                )
            }
        )
        | {"cancelled": row["status"] == "cancelled"}
    )


def external_state(c: Connection, ctx: AuthContext, project: UUID, row: Any) -> dict[str, Any]:
    if not row["external_provider"]:
        return {"state": "not_bound", "confirmation": None}
    from app.domain.meeting_conference_requests import meeting_snapshot

    t = tables.meeting_conference_requests
    receipt = (
        c.execute(
            select(t)
            .where(
                t.c.tenant_id == ctx.tenant.id,
                t.c.project_id == project,
                t.c.meeting_id == row["id"],
                t.c.status.in_(("succeeded", "resolved")),
                t.c.operation.in_(("create", "update", "cancel")),
                t.c.result["current_meeting_digest"].astext == digest(meeting_snapshot(row)),
            )
            .order_by(t.c.sequence.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if receipt is not None:
        return {
            "state": "provider_confirmed"
            if receipt["result"]["method"] == "provider_response"
            else "request_manually_confirmed",
            "confirmation": None,
            "request_id": str(receipt["id"]),
        }
    a = tables.audit_log
    scope = (a.c.tenant_id == ctx.tenant.id, a.c.project_id == project, a.c.entity_id == row["id"])
    last_change = c.execute(
        select(func.max(a.c.id)).where(
            *scope,
            a.c.action.in_((RESCHEDULE, "meeting.conference_bound", "meeting.status_cancelled")),
        )
    ).scalar_one()
    last = (
        c.execute(select(a).where(*scope, a.c.action == CONFIRM).order_by(a.c.id.desc()).limit(1))
        .mappings()
        .one_or_none()
    )
    matched = (
        last is not None
        and last["id"] > (last_change or 0)
        and last["after_snapshot"]["confirmation"]["signature"] == external_signature(row)
    )
    return {
        "state": "manually_confirmed" if matched else "needs_confirmation",
        "confirmation": _plain(last) if matched else None,
    }


def read(
    engine: Engine, ctx: AuthContext, project: UUID, id: UUID, before: int | None = None
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        status = authorize(c, ctx, project)
        row = record(c, ctx, project, id)
        a = tables.audit_log
        q = select(
            a.c.id,
            a.c.timestamp,
            a.c.actor_user_id,
            a.c.action,
            a.c.before_snapshot,
            a.c.after_snapshot,
            a.c.context,
        ).where(
            a.c.tenant_id == ctx.tenant.id,
            a.c.project_id == project,
            a.c.entity_id == id,
            a.c.action.in_((RESCHEDULE, CONFIRM)),
        )
        if before is not None:
            q = q.where(a.c.id < before)
        rows = list(c.execute(q.order_by(a.c.id.desc()).limit(21)).mappings())
        return {
            "record": _plain(row),
            "digest": digest(_plain(row)),
            "external": external_state(c, ctx, project, row),
            "can_manage": is_allowed(ctx.user.role, Action.MEETING_MANAGE)
            and status not in ("completed", "archived"),
            "history": [_plain(r) for r in rows[:20]],
            "next_before_id": rows[19]["id"] if len(rows) > 20 else None,
        }


def save(
    engine: Engine,
    ctx: AuthContext,
    project: UUID,
    id: UUID,
    command: Reschedule | ExternalConfirmation,
) -> dict[str, Any]:
    action = RESCHEDULE if isinstance(command, Reschedule) else CONFIRM
    signature = digest({"meeting_id": str(id), **command.model_dump(mode="json")})
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
            raise MeetingNotFoundError
        authorize(c, ctx, project, write=True)
        prior = replay(c, ctx, project, action, command.request_id, signature)
        if prior:
            return prior
        before = record(c, ctx, project, id)
        if command.expected_digest != digest(_plain(before)):
            raise MeetingStateError("会议安排或绑定已变化，请重新核对")
        if before["deleted_at"] or before["archived_at"]:
            raise MeetingStateError("已删除或归档会议保留原记录")
        now = datetime.now(UTC)
        if isinstance(command, Reschedule):
            if before["status"] != "scheduled":
                raise MeetingStateError("仅尚未开始的已排程会议可改期")
            start = command.scheduled_start_at.astimezone(UTC)
            end = command.scheduled_end_at.astimezone(UTC)
            if (start, end) == (before["scheduled_start_at"], before["scheduled_end_at"]):
                raise MeetingStateError("新旧时间相同，无需改期")
            t = tables.meetings
            c.execute(
                t.update()
                .where(t.c.tenant_id == ctx.tenant.id, t.c.id == id, t.c.project_id == project)
                .values(
                    scheduled_start_at=start,
                    scheduled_end_at=end,
                    updated_at=now,
                )
            )
            after = {"meeting_id": str(id), "record": _plain(record(c, ctx, project, id))}
        else:
            if not before["external_provider"] or before["status"] not in (
                "scheduled",
                "in_progress",
                "cancelled",
            ):
                raise MeetingStateError("当前会议没有可核对的外部绑定或已结束")
            after = {
                "meeting_id": str(id),
                "record": _plain(before),
                "confirmation": {
                    "signature": external_signature(before),
                    "evidence": command.evidence,
                    "external_handled": True,
                    "method": "human_attestation",
                    "confirmed_by": str(ctx.user.id),
                    "confirmed_at": now.isoformat(),
                },
            }
        written = EventAuditWriter(
            c, tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, project_id=project
        ).record(
            EventDraft(
                event_id=f"{action}:{id}:{command.request_id}",
                event_type="MEETING_STATE_CHANGED",
                source="meeting_service",
                entity_id=id,
                payload={
                    "meeting_id": str(id),
                    "meeting_type": before["meeting_type"],
                    "status": before["status"],
                    "action": action.removeprefix("meeting."),
                },
            ),
            AuditDraft(
                action=action,
                before_snapshot=_plain(before),
                after_snapshot=after,
                context={
                    "request_id": str(command.request_id),
                    "request_digest": signature,
                    "reason": command.reason,
                    "actor_name": ctx.user.display_name,
                },
            ),
        )
        return {"request_id": str(command.request_id), "audit_id": written.audit_row_id, **after}
