"""Reviewable default roster changes for future periodic meetings."""

from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.meeting_preparation import MeetingPreparationService
from app.domain.meeting_scheduling import _recurrence
from app.domain.meetings import MeetingService, MeetingStateError
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

ACTION = "meeting_recurrence.roster_changed"


class Participant(Contract):
    user_id: UUID
    participation: Literal["required", "optional"]


class RosterChange(Contract):
    request_id: UUID
    expected_digest: Digest
    participants: tuple[Participant, ...] = Field(max_length=100)
    agenda_owners: tuple[UUID | None, ...] = Field(max_length=100)
    status: Literal["active", "paused"]
    reason: Text

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({p.user_id for p in self.participants}) != len(self.participants):
            raise ValueError("默认参会人不能重复")
        return self


def record(c: Connection, context: AuthContext, project: UUID, id: UUID) -> Any:
    t = tables.meeting_recurrences
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == context.tenant.id, t.c.project_id == project, t.c.id == id
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise MeetingStateError("周期会议不存在或不属于当前项目")
    return row


def read(
    engine: Engine, context: AuthContext, project: UUID, id: UUID, before: int | None = None
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        KnowledgeCorrectionService._authorize(
            c, context.tenant.id, context.user.id, project, Action.MEETING_VIEW
        )
        row = record(c, context, project, id)
        a = tables.audit_log
        query = select(
            a.c.id,
            a.c.timestamp.label("created_at"),
            a.c.actor_user_id,
            a.c.before_snapshot,
            a.c.after_snapshot,
            a.c.context,
        ).where(
            a.c.tenant_id == context.tenant.id,
            a.c.project_id == project,
            a.c.entity_id == id,
            a.c.action == ACTION,
        )
        if before is not None:
            query = query.where(a.c.id < before)
        history = list(c.execute(query.order_by(a.c.id.desc()).limit(21)).mappings())
        p = c.execute(
            select(tables.projects.c.status).where(
                tables.projects.c.tenant_id == context.tenant.id, tables.projects.c.id == project
            )
        ).scalar_one()
        return {
            "record": _plain(row),
            "effective_start_date": str(_recurrence(row).start_date),
            "digest": digest(_plain(row)),
            "members": MeetingPreparationService.members(c, context.tenant.id, project),
            "can_manage": is_allowed(context.user.role, Action.MEETING_MANAGE)
            and p not in ("completed", "archived"),
            "history": [_plain(r) for r in history[:20]],
            "next_before_id": history[19]["id"] if len(history) > 20 else None,
        }


def save(
    engine: Engine, context: AuthContext, project: UUID, id: UUID, command: RosterChange
) -> dict[str, Any]:
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
            raise MeetingStateError("项目不存在")
        KnowledgeCorrectionService._authorize(
            c, context.tenant.id, context.user.id, project, Action.MEETING_MANAGE
        )
        row = record(c, context, project, id)
        signature = digest({"recurrence_id": str(id), **command.model_dump(mode="json")})
        a = tables.audit_log
        prior = (
            c.execute(
                select(a).where(
                    a.c.tenant_id == context.tenant.id,
                    a.c.project_id == project,
                    a.c.action == ACTION,
                    a.c.actor_user_id == context.user.id,
                    a.c.context["request_id"].as_string() == str(command.request_id),
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior:
            if prior["context"]["request_digest"] != signature:
                raise MeetingStateError("此请求已用于其他周期会议调整")
            return {"request_id": str(command.request_id), "audit_id": prior["id"]}
        project_status = c.execute(
            select(tables.projects.c.status).where(
                tables.projects.c.tenant_id == context.tenant.id, tables.projects.c.id == project
            )
        ).scalar_one()
        if project_status in ("completed", "archived"):
            raise MeetingStateError("已结束项目保留原配置")
        if digest(_plain(row)) != command.expected_digest or len(command.agenda_owners) != len(
            row["agenda_template"]
        ):
            raise MeetingStateError("周期会议配置已变化，请重新核对")
        original_ids = {
            UUID(p["user_id"]) for p in row["default_participants"] if p.get("user_id")
        } | {UUID(p["owner_user_id"]) for p in row["agenda_template"] if p.get("owner_user_id")}
        new_ids = {p.user_id for p in command.participants} | {
            p for p in command.agenda_owners if p
        }
        # Pausing can retain unavailable original people; new people must still qualify.
        MeetingService._require_project_members(
            c,
            tenant_id=context.tenant.id,
            project_id=project,
            user_ids=new_ids if command.status == "active" else new_ids - original_ids,
        )
        agenda = [
            {**entry, "owner_user_id": str(owner) if owner else None}
            for entry, owner in zip(row["agenda_template"], command.agenda_owners, strict=True)
        ]
        people = {
            str(p.id): p.display_name
            for p in c.execute(
                select(tables.users.c.id, tables.users.c.display_name).where(
                    tables.users.c.tenant_id == context.tenant.id,
                    tables.users.c.id.in_(original_ids | new_ids | {context.user.id}),
                )
            )
        }
        t = tables.meeting_recurrences
        after = (
            c.execute(
                t.update()
                .where(t.c.tenant_id == context.tenant.id, t.c.id == id)
                .values(
                    default_participants=[p.model_dump(mode="json") for p in command.participants],
                    agenda_template=agenda,
                    status=command.status,
                    updated_at=datetime.now(UTC),
                )
                .returning(t)
            )
            .mappings()
            .one()
        )
        written = EventAuditWriter(
            c, tenant_id=context.tenant.id, actor_user_id=context.user.id, project_id=project
        ).record(
            EventDraft(
                event_id=f"meeting-recurrence:{id}:{command.request_id}",
                event_type="MEETING_RECURRENCE_UPDATED",
                source="meeting_scheduling_service",
                entity_id=id,
                payload={"recurrence_id": str(id), "status": command.status},
            ),
            AuditDraft(
                action=ACTION,
                before_snapshot=_plain(row),
                after_snapshot=_plain(after),
                context={
                    "request_id": str(command.request_id),
                    "request_digest": signature,
                    "reason": command.reason,
                    "people": people,
                },
            ),
        )
        return {"request_id": str(command.request_id), "audit_id": written.audit_row_id}
