"""Project-scoped recurring meeting setup, exact preview and local generation."""

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, or_, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.meeting_preparation import TEMPLATES, MeetingPreparationService
from app.domain.meeting_recurrence_roster import Participant, record
from app.domain.meeting_scheduling import (
    MeetingSchedulingService,
    RecurrenceRecord,
    _recurrence,
    occurrence_times,
    occurrences_between,
)
from app.domain.meetings import MEETING_TYPES, MeetingService, MeetingStateError
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

CREATE = "meeting_recurrence.created"
GENERATE = "meeting_recurrence.generated"


class Agenda(Contract):
    title: str = Field(min_length=1, max_length=256, pattern=r"\S")
    detail: str | None = Field(default=None, max_length=10000)
    owner_user_id: UUID | None = None
    item_kind: Literal["topic", "review", "decision", "information", "exception"] = "topic"


class Timing(Contract):
    cadence: Literal["weekly", "biweekly", "monthly"]
    start_date: date
    day_of_week: int | None = Field(default=None, ge=1, le=7)
    day_of_month: int | None = Field(default=None, ge=1, le=28)
    start_minute_of_day: int = Field(ge=0, le=1439)
    duration_minutes: int = Field(ge=5, le=720)
    timezone: str = Field(max_length=64)

    @model_validator(mode="after")
    def validate_schedule(self) -> Self:
        if self.cadence == "monthly":
            valid = self.day_of_month is not None and self.day_of_week is None
        else:
            valid = self.day_of_week is not None and self.day_of_month is None
        if not valid:
            raise ValueError("请按周期填写星期或每月日期")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("请选择有效的 IANA 时区") from error
        return self


class Create(Timing):
    request_id: UUID
    meeting_type: str
    title: str = Field(min_length=1, max_length=240, pattern=r"\S")
    participants: tuple[Participant, ...] = Field(default=(), max_length=100)
    agenda: tuple[Agenda, ...] = Field(default=(), max_length=100)
    reason: Text

    @model_validator(mode="after")
    def validate_people_and_type(self) -> Self:
        if self.meeting_type not in MEETING_TYPES:
            raise ValueError("请选择已有会议类型")
        if len({p.user_id for p in self.participants}) != len(self.participants):
            raise ValueError("默认参会人不能重复")
        return self

    def recurrence(self, project: UUID) -> RecurrenceRecord:
        return RecurrenceRecord(
            id=self.request_id,
            project_id=project,
            meeting_type=self.meeting_type,
            title=self.title,
            cadence=self.cadence,
            day_of_week=self.day_of_week,
            day_of_month=self.day_of_month,
            start_minute_of_day=self.start_minute_of_day,
            duration_minutes=self.duration_minutes,
            timezone=self.timezone,
            default_participants=[p.model_dump(mode="json") for p in self.participants],
            agenda_template=[p.model_dump(mode="json") for p in self.agenda],
            auto_conference=False,
            status="active",
            start_date=self.start_date,
        )


class Window(Contract):
    since: date
    through: date

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if not 0 <= (self.through - self.since).days <= 93:
            raise ValueError("请选择不超过94个自然日的生成范围")
        return self


class Generate(Window):
    request_id: UUID
    expected_digest: Digest
    preview_digest: Digest
    reason: Text


def authorize(c: Connection, ctx: AuthContext, project: UUID, *, write: bool = False) -> str:
    KnowledgeCorrectionService._authorize(
        c,
        ctx.tenant.id,
        ctx.user.id,
        project,
        Action.MEETING_MANAGE if write else Action.MEETING_VIEW,
    )
    status: str = c.execute(
        select(tables.projects.c.status).where(
            tables.projects.c.tenant_id == ctx.tenant.id, tables.projects.c.id == project
        )
    ).scalar_one()
    if write and status in ("completed", "archived"):
        raise MeetingStateError("已结束项目保留原会议安排")
    return status


def validate_people(c: Connection, ctx: AuthContext, project: UUID, rec: RecurrenceRecord) -> None:
    MeetingService._require_project_members(
        c,
        tenant_id=ctx.tenant.id,
        project_id=project,
        user_ids={ctx.user.id}
        | {UUID(p["user_id"]) for p in rec.default_participants}
        | {UUID(p["owner_user_id"]) for p in rec.agenda_template if p.get("owner_user_id")},
    )


def list_configurations(
    engine: Engine, ctx: AuthContext, project: UUID, before: UUID | None = None
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        status = authorize(c, ctx, project)
        t = tables.meeting_recurrences
        q = select(t).where(t.c.tenant_id == ctx.tenant.id, t.c.project_id == project)
        if before:
            q = q.where(t.c.id < before)
        rows = list(c.execute(q.order_by(t.c.id.desc()).limit(31)).mappings())
        return {
            "items": [
                {
                    **_plain(r),
                    "effective_start_date": str(_recurrence(r).start_date),
                    "digest": digest(_plain(r)),
                }
                for r in rows[:30]
            ],
            "next_before": str(rows[29]["id"]) if len(rows) > 30 else None,
            "members": MeetingPreparationService.members(c, ctx.tenant.id, project),
            "templates": TEMPLATES,
            "can_manage": is_allowed(ctx.user.role, Action.MEETING_MANAGE)
            and status not in ("completed", "archived"),
        }


def draft_preview(
    engine: Engine, ctx: AuthContext, project: UUID, command: Create
) -> dict[str, Any]:
    with engine.connect() as c:
        authorize(c, ctx, project, write=True)
        rec = command.recurrence(project)
        validate_people(c, ctx, project, rec)
        items = []
        for day in occurrences_between(
            rec, start=rec.start_date, end=rec.start_date + timedelta(days=93)
        ):
            start, end = occurrence_times(rec, day)
            items.append(
                {"date": str(day), "start_at": start.isoformat(), "end_at": end.isoformat()}
            )
        return {
            "items": items,
            "timezone": rec.timezone,
            "command_digest": digest(command.model_dump(mode="json")),
        }


def replay(
    c: Connection, ctx: AuthContext, project: UUID, action: str, request: UUID, signature: str
) -> dict[str, Any] | None:
    a = tables.audit_log
    prior = (
        c.execute(
            select(a).where(
                a.c.tenant_id == ctx.tenant.id,
                a.c.project_id == project,
                a.c.actor_user_id == ctx.user.id,
                a.c.action == action,
                a.c.context["request_id"].as_string() == str(request),
            )
        )
        .mappings()
        .one_or_none()
    )
    if prior:
        if prior["context"]["request_digest"] != signature:
            raise MeetingStateError("此请求已用于不同的周期会议办理，请核对原回执")
        return {"request_id": str(request), "audit_id": prior["id"], **prior["after_snapshot"]}
    return None


def receipt(
    c: Connection,
    ctx: AuthContext,
    project: UUID,
    rec: RecurrenceRecord,
    action: str,
    request: UUID,
    signature: str,
    reason: str,
    before: dict[str, Any] | None,
    after: dict[str, Any],
) -> dict[str, Any]:
    person_ids = (
        {ctx.user.id}
        | {UUID(p["user_id"]) for p in rec.default_participants}
        | {UUID(p["owner_user_id"]) for p in rec.agenda_template if p.get("owner_user_id")}
    )
    people = {
        str(p.id): p.display_name
        for p in c.execute(
            select(tables.users.c.id, tables.users.c.display_name).where(
                tables.users.c.tenant_id == ctx.tenant.id, tables.users.c.id.in_(person_ids)
            )
        )
    }
    written = EventAuditWriter(
        c, tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, project_id=project
    ).record(
        EventDraft(
            event_id=f"{action}:{rec.id}:{request}",
            event_type="MEETING_RECURRENCE_UPDATED",
            source="meeting_scheduling_service",
            entity_id=rec.id,
            payload={"recurrence_id": str(rec.id), "status": rec.status},
        ),
        AuditDraft(
            action=action,
            before_snapshot=before,
            after_snapshot=after,
            context={
                "request_id": str(request),
                "request_digest": signature,
                "reason": reason,
                "actor_name": ctx.user.display_name,
                "people": people,
            },
        ),
    )
    return {"request_id": str(request), "audit_id": written.audit_row_id, **after}


def create(engine: Engine, ctx: AuthContext, project: UUID, command: Create) -> dict[str, Any]:
    signature = digest(command.model_dump(mode="json"))
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
            raise MeetingStateError("项目不存在")
        authorize(c, ctx, project, write=True)
        prior = replay(c, ctx, project, CREATE, command.request_id, signature)
        if prior:
            return prior
        rec = command.recurrence(project)
        validate_people(c, ctx, project, rec)
        for day in occurrences_between(
            rec, start=rec.start_date, end=rec.start_date + timedelta(days=93)
        ):
            occurrence_times(rec, day)
        created = MeetingSchedulingService(engine).create_recurrence(
            tenant_id=ctx.tenant.id,
            project_id=project,
            actor_user_id=ctx.user.id,
            meeting_type=rec.meeting_type,
            title=rec.title,
            cadence=rec.cadence,
            start_minute_of_day=rec.start_minute_of_day,
            duration_minutes=rec.duration_minutes,
            day_of_week=rec.day_of_week,
            day_of_month=rec.day_of_month,
            default_participants=rec.default_participants,
            agenda_template=rec.agenda_template,
            auto_conference=False,
            timezone_name=rec.timezone,
            start_date=rec.start_date,
            connection=c,
        )
        return receipt(
            c,
            ctx,
            project,
            created,
            CREATE,
            command.request_id,
            signature,
            command.reason,
            None,
            {"recurrence_id": str(created.id), "record": _plain(asdict(created))},
        )


def existing_in_window(
    c: Connection, ctx: AuthContext, project: UUID, rec: RecurrenceRecord, window: Window
) -> dict[date, Any]:
    zone = ZoneInfo(rec.timezone)
    lower = datetime.combine(window.since, datetime.min.time(), zone).astimezone(UTC)
    upper = datetime.combine(
        window.through + timedelta(days=1), datetime.min.time(), zone
    ).astimezone(UTC)
    t = tables.meetings
    rows = list(
        c.execute(
            select(t)
            .where(
                t.c.tenant_id == ctx.tenant.id,
                t.c.project_id == project,
                t.c.recurrence_id == rec.id,
                or_(
                    t.c.occurrence_date.between(window.since, window.through),
                    (t.c.scheduled_start_at < upper) & (t.c.scheduled_end_at > lower),
                ),
            )
            .order_by(t.c.scheduled_start_at, t.c.id)
            .limit(201)
        ).mappings()
    )
    if len(rows) > 200:
        raise MeetingStateError("此范围有超过200个历史场次，请缩短预览日期范围")
    return {r["occurrence_date"]: r for r in rows}


def existing_item(row: Any) -> dict[str, Any]:
    return {
        "date": str(row["occurrence_date"]),
        "start_at": row["scheduled_start_at"].isoformat(),
        "end_at": row["scheduled_end_at"].isoformat(),
        "meeting_id": str(row["id"]),
        "status": row["status"],
        "archived": row["archived_at"] is not None,
        "deleted": row["deleted_at"] is not None,
    }


def preview_in(
    c: Connection, ctx: AuthContext, project: UUID, id: UUID, window: Window
) -> dict[str, Any]:
    row = record(c, ctx, project, id)
    rec = _recurrence(row)
    if rec.status != "active":
        raise MeetingStateError("周期会议已暂停，请先核对人员并恢复")
    validate_people(c, ctx, project, rec)
    existing = existing_in_window(c, ctx, project, rec, window)
    items = []
    for day in occurrences_between(rec, start=window.since, end=window.through):
        old = existing.get(day)
        if old is not None:
            start, end = old["scheduled_start_at"], old["scheduled_end_at"]
        else:
            start, end = occurrence_times(rec, day)
        items.append(
            {
                "date": str(day),
                "start_at": start.isoformat(),
                "end_at": end.isoformat(),
                "meeting_id": str(old["id"]) if old else None,
                "status": old["status"] if old else None,
                "archived": old["archived_at"] is not None if old else False,
                "deleted": old["deleted_at"] is not None if old else False,
            }
        )
    included = {item["date"] for item in items}
    retained = [existing_item(r) for day, r in existing.items() if str(day) not in included]
    result = {
        "items": items,
        "retained_items": retained,
        "expected_digest": digest(_plain(row)),
        "timezone": rec.timezone,
        "organizer_user_id": str(ctx.user.id),
        "record": _plain(row),
    }
    return {**result, "preview_digest": digest(result)}


def preview(
    engine: Engine, ctx: AuthContext, project: UUID, id: UUID, window: Window
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        authorize(c, ctx, project, write=True)
        return preview_in(c, ctx, project, id, window)


def generate(
    engine: Engine, ctx: AuthContext, project: UUID, id: UUID, command: Generate
) -> dict[str, Any]:
    signature = digest({"recurrence_id": str(id), **command.model_dump(mode="json")})
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
            raise MeetingStateError("项目不存在")
        authorize(c, ctx, project, write=True)
        prior = replay(c, ctx, project, GENERATE, command.request_id, signature)
        if prior:
            return prior
        before = preview_in(c, ctx, project, id, command)
        if (
            before["expected_digest"] != command.expected_digest
            or before["preview_digest"] != command.preview_digest
        ):
            raise MeetingStateError("配置或已生成场次已变化，请重新预览")
        rec = _recurrence(record(c, ctx, project, id))
        generated = []
        for item in before["items"]:
            result = MeetingSchedulingService(engine)._materialise(
                tenant_id=ctx.tenant.id,
                recurrence=rec,
                occurrence=date.fromisoformat(item["date"]),
                actor_user_id=ctx.user.id,
                now=datetime.now(UTC),
                connection=c,
            )
            generated.append(
                {
                    **item,
                    "meeting_id": str(result.meeting.id),
                    "created": result.created,
                    "status": result.meeting.status,
                }
            )
        return receipt(
            c,
            ctx,
            project,
            rec,
            GENERATE,
            command.request_id,
            signature,
            command.reason,
            before,
            {
                "recurrence_id": str(id),
                "items": generated,
                "retained_items": before["retained_items"],
                "timezone": rec.timezone,
                "since": str(command.since),
                "through": str(command.through),
            },
        )


def history(
    engine: Engine, ctx: AuthContext, project: UUID, id: UUID, before: int | None
) -> dict[str, Any]:
    with engine.connect() as c:
        authorize(c, ctx, project)
        record(c, ctx, project, id)
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
            a.c.action.in_((CREATE, GENERATE, "meeting_recurrence.schedule_changed")),
        )
        if before is not None:
            q = q.where(a.c.id < before)
        rows = list(c.execute(q.order_by(a.c.id.desc()).limit(21)).mappings())
        return {
            "items": [_plain(r) for r in rows[:20]],
            "next_before_id": rows[19]["id"] if len(rows) > 20 else None,
        }
