"""Tenant working calendar: what one version says and working-day arithmetic (D221).

A calendar version is complete on its own: time zone, the usual working weekdays,
and dated entries. Entries are inclusive local date ranges:

- ``holiday`` 法定假日: a usual working day off;
- ``makeup_workday`` 调休上班: a usual day off worked instead;
- ``shutdown`` 停线: the factory (or, on a supplier calendar, that supplier) is
  stopped. A shutdown wins over a makeup workday inside it.

The arithmetic matches the Monday-to-Friday estimate it replaces (P41 第 10 项,
``projects/work/business_days.add_weekdays`` on the follow-up branch) so callers
switch without changing meaning: one working day after a working day at 15:00 is
the next working day at 15:00; a start on a day off begins at 00:00 of the next
working day. ``public.work_calendar_add`` (migration s0_0910) is the SQL twin.
Without a calendar the fallback is Monday to Friday in Asia/Shanghai, and every
result carries a basis saying holidays and line stops were not deducted.
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_WEEKDAYS = (1, 2, 3, 4, 5)
MAX_DAYS = 366
MAX_ENTRIES = 500
MAX_SPAN_DAYS = 366
# A run of days off longer than this means the calendar has no working day ahead.
MAX_SEARCH_DAYS = 3660

ESTIMATE_BASIS = "weekdays_estimate"
ESTIMATE_LABEL = "按周一至周五估算，未扣节假日与停线"
CALENDAR_BASIS = "tenant_calendar"
KIND_LABELS = {"holiday": "法定假日", "makeup_workday": "调休上班", "shutdown": "停线"}


class CalendarError(ValueError):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Entry(_Strict):
    kind: Literal["holiday", "makeup_workday", "shutdown"]
    start: date
    end: date
    label: str = Field(min_length=1, max_length=80)

    @field_validator("label")
    @classmethod
    def trimmed(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("说明不能为空")
        return value

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start:
            raise ValueError("结束日期不能早于开始日期")
        if (self.end - self.start).days >= MAX_SPAN_DAYS:
            raise ValueError("单条登记不能超过 366 天")
        return self

    def covers(self, day: date) -> bool:
        return self.start <= day <= self.end


class Definition(_Strict):
    """The content of one calendar version, as an administrator saves it."""

    timezone: str = DEFAULT_TIMEZONE
    working_weekdays: tuple[int, ...] = DEFAULT_WEEKDAYS
    entries: tuple[Entry, ...] = Field(default=(), max_length=MAX_ENTRIES)

    @field_validator("timezone")
    @classmethod
    def zone(cls, value: str) -> str:
        _zone(value)
        return value

    @field_validator("working_weekdays")
    @classmethod
    def weekdays(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if not value or any(day not in range(1, 8) for day in value):
            raise ValueError("工作日须是周一（1）至周日（7）中的至少一天")
        if len(set(value)) != len(value):
            raise ValueError("工作日不能重复")
        return tuple(sorted(value))

    @field_validator("entries")
    @classmethod
    def ordered(cls, value: tuple[Entry, ...]) -> tuple[Entry, ...]:
        if len(set(value)) != len(value):
            raise ValueError("有重复的登记")
        return tuple(sorted(value, key=lambda e: (e.start, e.end, e.kind, e.label)))

    @model_validator(mode="after")
    def coherent(self):
        days_off = {
            kind: [e for e in self.entries if e.kind == kind] for kind in ("holiday", "shutdown")
        }
        for entry in self.entries:
            if entry.kind != "makeup_workday":
                continue
            day = entry.start
            while day <= entry.end:
                if day.isoweekday() in self.working_weekdays:
                    raise ValueError(f"{day} 本来就是工作日，不能登记为调休上班")
                if any(h.covers(day) for h in days_off["holiday"]):
                    raise ValueError(f"{day} 同时登记了法定假日和调休上班")
                day += timedelta(days=1)
        return self


class Calendar(_Strict):
    """One saved version, as the arithmetic and a result's basis see it."""

    calendar_id: str
    kind: Literal["factory", "supplier"]
    name: str
    revision: int = Field(ge=1)
    definition: Definition


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError, TypeError) as exc:
        raise CalendarError("须是有效的 IANA 时区") from exc


def _definition(calendar: Calendar | None) -> Definition:
    return calendar.definition if calendar is not None else Definition()


def is_working_day(calendar: Calendar | None, day: date) -> bool:
    definition = _definition(calendar)
    covering = [entry.kind for entry in definition.entries if entry.covers(day)]
    if "shutdown" in covering or "holiday" in covering:
        return False
    if "makeup_workday" in covering:
        return True
    return day.isoweekday() in definition.working_weekdays


def _next_working_day(calendar: Calendar | None, day: date) -> date:
    for _ in range(MAX_SEARCH_DAYS):
        day += timedelta(days=1)
        if is_working_day(calendar, day):
            return day
    raise CalendarError("日历在之后十年内没有工作日")


def add_working_days(calendar: Calendar | None, at: datetime, days: int) -> datetime:
    """The UTC instant ``days`` working days after ``at`` (same rule as the estimate)."""
    if not isinstance(at, datetime) or at.utcoffset() is None:
        raise CalendarError("须是带时区的时刻")
    if type(days) is not int or not 0 <= days <= MAX_DAYS:
        raise CalendarError("工作日数须是 0 至 366 的整数")
    zone = _zone(_definition(calendar).timezone)
    local = at.astimezone(zone).replace(tzinfo=None)
    day, clock = local.date(), local.time()
    if not is_working_day(calendar, day):
        day, clock = _next_working_day(calendar, day), time()
    for _ in range(days):
        day = _next_working_day(calendar, day)
    return datetime.combine(day, clock).replace(tzinfo=zone).astimezone(UTC)


def is_past(calendar: Calendar | None, anchor: datetime, days: int, at: datetime) -> bool:
    """Whether ``at`` is at or after ``days`` working days from ``anchor``."""
    return at >= add_working_days(calendar, anchor, days)


def working_days_between(calendar: Calendar | None, start: date, end: date) -> int:
    """Working days in [start, end); negative when end is before start."""
    if end < start:
        return -working_days_between(calendar, end, start)
    if (end - start).days > MAX_SEARCH_DAYS:
        raise CalendarError("区间不能超过十年")
    return sum(
        is_working_day(calendar, start + timedelta(days=offset))
        for offset in range((end - start).days)
    )


def basis(calendar: Calendar | None) -> dict:
    """What every result built on this arithmetic carries (P41 第 10 项)."""
    if calendar is None:
        return {
            "basis": ESTIMATE_BASIS,
            "basis_label": ESTIMATE_LABEL,
            "timezone": DEFAULT_TIMEZONE,
        }
    return {
        "basis": CALENDAR_BASIS,
        "basis_label": f"按{calendar_label(calendar)}第 {calendar.revision} 版计算",
        "timezone": calendar.definition.timezone,
        "calendar_id": calendar.calendar_id,
        "calendar_revision": calendar.revision,
    }


def calendar_label(calendar: Calendar) -> str:
    return "工厂日历" if calendar.kind == "factory" else f"供应商日历（{calendar.name}）"


def planning_snapshot(calendar: Calendar | None, intervals, start: date, end: date):
    """The planning engine's CalendarSnapshot for [start, end].

    ``intervals`` are the WorkInterval shifts of one working day (the calendar holds
    days, not shifts). Days off on a usual working weekday and makeup workdays become
    dated exceptions, so the engine's minute arithmetic deducts holidays and stops.
    """
    from pdos_next.domain.projects.planning.engine.dto import (
        CalendarException,
        CalendarSnapshot,
        Reference,
        WeekdaySchedule,
    )

    definition = _definition(calendar)
    identity = calendar.calendar_id if calendar is not None else ESTIMATE_BASIS
    version = str(calendar.revision) if calendar is not None else "1"
    source = Reference(source_id=identity, version=version)
    exceptions, day = [], start
    while day <= end:
        usual = day.isoweekday() in definition.working_weekdays
        working = is_working_day(calendar, day)
        if working != usual:
            shifts = tuple(intervals) if working else ()
            exceptions.append(CalendarException(day=day, intervals=shifts, source=source))
        day += timedelta(days=1)
    return CalendarSnapshot(
        calendar_id=identity,
        version=version,
        timezone=definition.timezone,
        weekly=tuple(
            WeekdaySchedule(weekday=weekday - 1, intervals=tuple(intervals))
            for weekday in definition.working_weekdays
        ),
        exceptions=tuple(exceptions),
    )
