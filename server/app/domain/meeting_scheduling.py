"""Recurring meeting generation and conference booking (vNext V2-2, D35).

The generator is deterministic and idempotent: a recurrence plus an occurrence
date yields exactly one meeting, enforced by a unique constraint rather than by
the caller remembering what it already did. That matters because this runs on a
schedule — a retried or double-fired job must not produce two Monday reviews.

Conference booking is deliberately *after* meeting creation and allowed to
fail. "API 失败降级为手工建会" is the requirement, and the shape that delivers
it is: create the meeting, try to book, record the failure, move on.
"""

from __future__ import annotations

from contextlib import nullcontext, suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import Connection, Engine, RowMapping, select

from app.db.schema import tables
from app.domain.meetings import MeetingRecord, MeetingService
from app.domain.project_write_lock import lock_project_write_scope
from app.integrations.conference import (
    ConferenceProvider,
    ConferenceProviderError,
)

SchedulingList = list

WEEKLY = "weekly"
BIWEEKLY = "biweekly"
MONTHLY = "monthly"


class RecurrenceNotFoundError(LookupError):
    """Raised when the recurrence is absent from the project."""


class RecurrenceValidationError(ValueError):
    """Raised when a cadence policy is malformed."""


@dataclass(frozen=True)
class RecurrenceRecord:
    id: UUID
    project_id: UUID
    meeting_type: str
    title: str
    cadence: str
    day_of_week: int | None
    day_of_month: int | None
    start_minute_of_day: int
    duration_minutes: int
    timezone: str
    default_participants: list[dict[str, Any]]
    agenda_template: list[dict[str, Any]]
    auto_conference: bool
    status: str
    start_date: date = date(1970, 1, 5)


@dataclass(frozen=True)
class GeneratedMeeting:
    meeting: MeetingRecord
    occurrence_date: date
    created: bool
    conference_booked: bool
    conference_error: str | None


def _recurrence(row: RowMapping) -> RecurrenceRecord:
    return RecurrenceRecord(
        id=row["id"],
        project_id=row["project_id"],
        meeting_type=row["meeting_type"],
        title=row["title"],
        cadence=row["cadence"],
        day_of_week=row["day_of_week"],
        day_of_month=row["day_of_month"],
        start_minute_of_day=row["start_minute_of_day"],
        duration_minutes=row["duration_minutes"],
        timezone=row["timezone"],
        default_participants=list(row["default_participants"] or []),
        agenda_template=list(row["agenda_template"] or []),
        auto_conference=row["auto_conference"],
        status=row["status"],
        start_date=row["start_date"]
        or row["created_at"].astimezone(ZoneInfo(row["timezone"])).date(),
    )


def occurrences_between(
    recurrence: RecurrenceRecord, *, start: date, end: date
) -> SchedulingList[date]:
    """Every date this cadence falls on within the window, inclusive.

    Pure and deterministic — the horizon is the caller's choice, and the same
    window always yields the same dates.
    """
    start = max(start, recurrence.start_date)
    if end < start:
        return []
    dates: list[date] = []
    if recurrence.cadence in {WEEKLY, BIWEEKLY}:
        if recurrence.day_of_week is None:
            raise RecurrenceValidationError("a weekly cadence needs a day of week")
        # Anchor phase to the saved start date, independent of the query window.
        anchor = recurrence.start_date
        offset = (recurrence.day_of_week - anchor.isoweekday()) % 7
        first = anchor + timedelta(days=offset)
        step = 7 if recurrence.cadence == WEEKLY else 14
        current = first + timedelta(days=max(0, (start - first).days + step - 1) // step * step)
        while current <= end:
            dates.append(current)
            current += timedelta(days=step)
        return dates

    if recurrence.day_of_month is None:
        raise RecurrenceValidationError("a monthly cadence needs a day of month")
    year, month = start.year, start.month
    while True:
        try:
            candidate = date(year, month, recurrence.day_of_month)
        except ValueError:  # pragma: no cover - day_of_month is capped at 28
            break
        if candidate > end:
            break
        if candidate >= start:
            dates.append(candidate)
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return dates


def occurrence_times(recurrence: RecurrenceRecord, occurrence: date) -> tuple[datetime, datetime]:
    """Resolve a local wall time without silently shifting DST gaps or overlaps."""
    try:
        zone = ZoneInfo(recurrence.timezone)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise RecurrenceValidationError("请选择有效的 IANA 时区") from error
    wall = datetime.combine(occurrence, datetime.min.time()) + timedelta(
        minutes=recurrence.start_minute_of_day
    )
    candidates = {
        local.astimezone(UTC)
        for fold in (0, 1)
        if (local := wall.replace(tzinfo=zone, fold=fold))
        .astimezone(UTC)
        .astimezone(zone)
        .replace(tzinfo=None)
        == wall
    }
    if len(candidates) != 1:
        raise RecurrenceValidationError(f"{occurrence} 的当地时间因夏令时不存在或重复，请另选时间")
    start = candidates.pop()
    return start, start + timedelta(minutes=recurrence.duration_minutes)


class MeetingSchedulingService:
    def __init__(
        self,
        engine: Engine,
        *,
        conference_provider: ConferenceProvider | None = None,
    ) -> None:
        self._engine = engine
        self._meetings = MeetingService(engine)
        self._conference = conference_provider

    def create_recurrence(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        meeting_type: str,
        title: str,
        cadence: str,
        start_minute_of_day: int,
        duration_minutes: int,
        day_of_week: int | None = None,
        day_of_month: int | None = None,
        default_participants: list[dict[str, Any]] | None = None,
        agenda_template: list[dict[str, Any]] | None = None,
        auto_conference: bool = True,
        timezone_name: str = "Asia/Shanghai",
        now: datetime | None = None,
        start_date: date | None = None,
        connection: Connection | None = None,
    ) -> RecurrenceRecord:
        if cadence not in {WEEKLY, BIWEEKLY, MONTHLY}:
            raise RecurrenceValidationError(f"unknown cadence: {cadence}")
        if cadence in {WEEKLY, BIWEEKLY} and not day_of_week:
            raise RecurrenceValidationError("a weekly cadence needs a day of week")
        if cadence == MONTHLY and not day_of_month:
            raise RecurrenceValidationError("a monthly cadence needs a day of month")
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        recurrence_id = uuid4()
        try:
            zone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise RecurrenceValidationError("请选择有效的 IANA 时区") from error
        if not 0 <= start_minute_of_day <= 1439 or not 5 <= duration_minutes <= 720:
            raise RecurrenceValidationError("开始时刻或时长无效")
        if (cadence != MONTHLY and not 1 <= (day_of_week or 0) <= 7) or (
            cadence == MONTHLY and not 1 <= (day_of_month or 0) <= 28
        ):
            raise RecurrenceValidationError("周期日期无效")
        with (
            nullcontext(connection)
            if connection is not None
            else self._engine.begin() as connection
        ):
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise RecurrenceNotFoundError("项目不存在")
            MeetingService._require_project_members(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                user_ids={actor_user_id}
                | {UUID(p["user_id"]) for p in default_participants or []}
                | {
                    UUID(p["owner_user_id"])
                    for p in agenda_template or []
                    if p.get("owner_user_id")
                },
            )
            connection.execute(
                tables.meeting_recurrences.insert(),
                {
                    "id": recurrence_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "meeting_type": meeting_type,
                    "title": title,
                    "cadence": cadence,
                    "start_date": start_date or occurred_at.astimezone(zone).date(),
                    "day_of_week": day_of_week if cadence != MONTHLY else None,
                    "day_of_month": day_of_month if cadence == MONTHLY else None,
                    "start_minute_of_day": start_minute_of_day,
                    "duration_minutes": duration_minutes,
                    "timezone": timezone_name,
                    "default_participants": default_participants or [],
                    "agenda_template": agenda_template or [],
                    "auto_conference": auto_conference,
                    "status": "active",
                    "created_by_user_id": actor_user_id,
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            return self._get(connection, tenant_id=tenant_id, recurrence_id=recurrence_id)

    def generate(
        self,
        *,
        tenant_id: UUID,
        recurrence_id: UUID,
        actor_user_id: UUID,
        through: date,
        since: date | None = None,
        now: datetime | None = None,
    ) -> SchedulingList[GeneratedMeeting]:
        """Materialise meetings for every occurrence up to `through`.

        Safe to re-run: an occurrence that already has a meeting is returned
        with `created=False` rather than duplicated.
        """
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        start = since
        with self._engine.connect() as connection:
            recurrence = self._get(connection, tenant_id=tenant_id, recurrence_id=recurrence_id)
            existing = {
                row.occurrence_date: row.id
                for row in connection.execute(
                    select(tables.meetings.c.id, tables.meetings.c.occurrence_date).where(
                        tables.meetings.c.tenant_id == tenant_id,
                        tables.meetings.c.recurrence_id == recurrence_id,
                    )
                ).all()
            }
        if recurrence.status != "active":
            return []

        generated: list[GeneratedMeeting] = []
        for occurrence in occurrences_between(
            recurrence,
            start=start or occurred_at.astimezone(ZoneInfo(recurrence.timezone)).date(),
            end=through,
        ):
            if occurrence in existing:
                generated.append(
                    GeneratedMeeting(
                        meeting=self._meetings.get(
                            tenant_id=tenant_id,
                            project_id=recurrence.project_id,
                            meeting_id=existing[occurrence],
                        ),
                        occurrence_date=occurrence,
                        created=False,
                        conference_booked=False,
                        conference_error=None,
                    )
                )
                continue
            generated.append(
                self._materialise(
                    tenant_id=tenant_id,
                    recurrence=recurrence,
                    occurrence=occurrence,
                    actor_user_id=actor_user_id,
                    now=occurred_at,
                )
            )
        return generated

    def _materialise(
        self,
        *,
        tenant_id: UUID,
        recurrence: RecurrenceRecord,
        occurrence: date,
        actor_user_id: UUID,
        now: datetime,
        connection: Connection | None = None,
    ) -> GeneratedMeeting:
        shared_connection = connection is not None
        with (
            nullcontext(connection)
            if connection is not None
            else self._engine.begin() as connection
        ):
            if not lock_project_write_scope(
                connection, tenant_id=tenant_id, project_id=recurrence.project_id
            ):
                raise RecurrenceNotFoundError("项目不存在")
            expected = recurrence
            recurrence = self._get(connection, tenant_id=tenant_id, recurrence_id=recurrence.id)
            if recurrence != expected:
                raise RecurrenceValidationError("周期配置已变化，请重新读取生成范围")
            if recurrence.status != "active":
                raise RecurrenceValidationError("周期会议已暂停，请重新读取")
            existing = connection.execute(
                select(tables.meetings.c.id).where(
                    tables.meetings.c.tenant_id == tenant_id,
                    tables.meetings.c.recurrence_id == recurrence.id,
                    tables.meetings.c.occurrence_date == occurrence,
                )
            ).scalar_one_or_none()
            if existing is not None:
                return GeneratedMeeting(
                    meeting=MeetingService._get(
                        connection,
                        tenant_id=tenant_id,
                        project_id=recurrence.project_id,
                        meeting_id=existing,
                    ),
                    occurrence_date=occurrence,
                    created=False,
                    conference_booked=False,
                    conference_error=None,
                )
            start_at, end_at = occurrence_times(recurrence, occurrence)
            participants = [
                (UUID(entry["user_id"]), entry.get("participation", "required"))
                for entry in recurrence.default_participants
                if entry.get("user_id")
            ]
            meeting = self._meetings.create(
                tenant_id=tenant_id,
                project_id=recurrence.project_id,
                actor_user_id=actor_user_id,
                meeting_type=recurrence.meeting_type,
                title=f"{recurrence.title}（{occurrence.isoformat()}）",
                scheduled_start_at=start_at,
                scheduled_end_at=end_at,
                participants=participants,
                now=now,
                connection=connection,
            )
            connection.execute(
                tables.meetings.update()
                .where(
                    tables.meetings.c.tenant_id == tenant_id,
                    tables.meetings.c.id == meeting.id,
                )
                .values(recurrence_id=recurrence.id, occurrence_date=occurrence)
            )
            if recurrence.agenda_template:
                self._meetings.replace_agenda(
                    tenant_id=tenant_id,
                    project_id=recurrence.project_id,
                    meeting_id=meeting.id,
                    actor_user_id=actor_user_id,
                    items=[
                        {
                            **item,
                            **{
                                key: UUID(str(item[key]))
                                for key in (
                                    "owner_user_id",
                                    "source_entity_id",
                                    "carried_from_item_id",
                                )
                                if item.get(key)
                            },
                        }
                        for item in recurrence.agenda_template
                    ],
                    now=now,
                    connection=connection,
                )

        if shared_connection:
            return GeneratedMeeting(
                meeting=MeetingService._get(
                    connection,
                    tenant_id=tenant_id,
                    project_id=recurrence.project_id,
                    meeting_id=meeting.id,
                ),
                occurrence_date=occurrence,
                created=True,
                conference_booked=False,
                conference_error=None,
            )
        booked = False
        error: str | None = None
        if not shared_connection and recurrence.auto_conference and self._conference is not None:
            try:
                booking = self._conference.create(
                    tenant_id=tenant_id,
                    subject=meeting.title,
                    start_at=start_at,
                    end_at=end_at,
                    # Same occurrence, same key: a retried generation reuses the
                    # provider's booking instead of creating a second room.
                    idempotency_key=f"{recurrence.id}:{occurrence.isoformat()}",
                )
                self._meetings.bind_external_conference(
                    tenant_id=tenant_id,
                    project_id=recurrence.project_id,
                    meeting_id=meeting.id,
                    actor_user_id=actor_user_id,
                    provider=booking.provider,
                    external_meeting_id=booking.external_meeting_id,
                    join_url=booking.join_url,
                    now=now,
                )
                booked = True
            except (ConferenceProviderError, ValueError) as failure:
                # 降级为手工建会: the meeting stands, someone books a room by
                # hand. Losing the agenda because a conference API blipped
                # would be a far worse outcome.
                error = str(failure)

        return GeneratedMeeting(
            meeting=self._meetings.get(
                tenant_id=tenant_id,
                project_id=recurrence.project_id,
                meeting_id=meeting.id,
            ),
            occurrence_date=occurrence,
            created=True,
            conference_booked=booked,
            conference_error=error,
        )

    def list_recurrences(
        self, *, tenant_id: UUID, project_id: UUID
    ) -> SchedulingList[RecurrenceRecord]:
        with self._engine.connect() as connection:
            return [
                _recurrence(row)
                for row in connection.execute(
                    select(tables.meeting_recurrences)
                    .where(
                        tables.meeting_recurrences.c.tenant_id == tenant_id,
                        tables.meeting_recurrences.c.project_id == project_id,
                    )
                    .order_by(tables.meeting_recurrences.c.created_at)
                ).mappings()
            ]

    def set_status(
        self,
        *,
        tenant_id: UUID,
        recurrence_id: UUID,
        status: str,
        now: datetime | None = None,
    ) -> RecurrenceRecord:
        if status not in {"active", "paused"}:
            raise RecurrenceValidationError(f"unknown recurrence status: {status}")
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            record = self._get(connection, tenant_id=tenant_id, recurrence_id=recurrence_id)
            if not lock_project_write_scope(
                connection, tenant_id=tenant_id, project_id=record.project_id
            ):
                raise RecurrenceNotFoundError("项目不存在")
            record = self._get(connection, tenant_id=tenant_id, recurrence_id=recurrence_id)
            if status == "active":
                MeetingService._require_project_members(
                    connection,
                    tenant_id=tenant_id,
                    project_id=record.project_id,
                    user_ids={
                        UUID(p["user_id"]) for p in record.default_participants if p.get("user_id")
                    }
                    | {
                        UUID(p["owner_user_id"])
                        for p in record.agenda_template
                        if p.get("owner_user_id")
                    },
                )
            connection.execute(
                tables.meeting_recurrences.update()
                .where(
                    tables.meeting_recurrences.c.tenant_id == tenant_id,
                    tables.meeting_recurrences.c.id == recurrence_id,
                )
                .values(status=status, updated_at=occurred_at)
            )
            return self._get(connection, tenant_id=tenant_id, recurrence_id=recurrence_id)

    def cancel_occurrence(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        meeting_id: UUID,
        actor_user_id: UUID,
        reason: str,
        now: datetime | None = None,
    ) -> MeetingRecord:
        """Cancel one generated meeting and release its conference room."""
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        meeting = self._meetings.get(
            tenant_id=tenant_id, project_id=project_id, meeting_id=meeting_id
        )
        cancelled = self._meetings.change_status(
            tenant_id=tenant_id,
            project_id=project_id,
            meeting_id=meeting_id,
            actor_user_id=actor_user_id,
            status="cancelled",
            cancelled_reason=reason,
            now=occurred_at,
        )
        if self._conference is not None and meeting.external_meeting_id:
            # The meeting is already cancelled in PDOS, which is the record
            # people act on; a stale conference room is a smaller problem than
            # a cancellation that failed to stick.
            with suppress(ConferenceProviderError):
                self._conference.cancel(
                    tenant_id=tenant_id,
                    external_meeting_id=meeting.external_meeting_id,
                )
        return cancelled

    @staticmethod
    def _get(connection: Connection, *, tenant_id: UUID, recurrence_id: UUID) -> RecurrenceRecord:
        row = (
            connection.execute(
                select(tables.meeting_recurrences).where(
                    tables.meeting_recurrences.c.tenant_id == tenant_id,
                    tables.meeting_recurrences.c.id == recurrence_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise RecurrenceNotFoundError
        return _recurrence(row)


__all__ = [
    "GeneratedMeeting",
    "MeetingSchedulingService",
    "RecurrenceNotFoundError",
    "RecurrenceRecord",
    "RecurrenceValidationError",
    "occurrences_between",
]
