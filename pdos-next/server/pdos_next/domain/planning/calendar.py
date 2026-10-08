"""Narrow calendar DTO adapter over the independent engine's frozen timezone arithmetic."""

from datetime import date, datetime

from pdos_next.engines.planning.calendar import CalendarError, WorkingTime
from pdos_next.engines.planning.calendar import ceil_minute as engine_ceil_minute
from pdos_next.engines.planning.dto import (
    CalendarException,
    CalendarSnapshot,
    Reference,
    WeekdaySchedule,
    WorkInterval,
)
from pdos_next.schemas.planning import Calendar


class ScheduleError(ValueError):
    def __init__(self, code: str, message: str, *, task_keys: tuple[str, ...] = ()):
        super().__init__(message)
        self.code, self.message, self.task_keys = code, message, task_keys

    def as_dict(self):
        return {"code": self.code, "message": self.message, "task_keys": list(self.task_keys)}


ERROR_CODES = {
    "aware_instant_required": "INVALID_START",
    "nonexistent_local_time": "NONEXISTENT_LOCAL_TIME",
    "ambiguous_local_time": "AMBIGUOUS_LOCAL_TIME",
    "invalid_utc_interval": "INVALID_CALENDAR",
    "subminute_timezone_offset": "UNSUPPORTED_TIMEZONE_OFFSET",
    "calendar_horizon_exhausted": "HORIZON_EXCEEDED",
    "timezone_rules_unavailable": "TIMEZONE_RULES_UNAVAILABLE",
    "timezone_rules_changed": "TIMEZONE_RULES_CHANGED",
}


def _translated(error: CalendarError) -> ScheduleError:
    return ScheduleError(ERROR_CODES.get(error.code, "INVALID_CALENDAR"), str(error))


def ceil_minute(instant: datetime) -> datetime:
    try:
        return engine_ceil_minute(instant)
    except CalendarError as exc:
        raise _translated(exc) from exc


class WorkingCalendar:
    """Translate one supplied calendar version; add no approval or resource facts."""

    def __init__(self, calendar: Calendar, *, horizon_days: int = 3660):
        if not 1 <= horizon_days <= 3660:
            raise ScheduleError("INVALID_CALENDAR", "Calendar horizon must be within ten years")
        self.calendar, self.horizon_days = calendar, horizon_days
        intervals = tuple(WorkInterval(**item.model_dump()) for item in calendar.intervals)
        source = Reference(source_id=calendar.key, version=calendar.version)
        definition = CalendarSnapshot(
            calendar_id=calendar.key,
            version=calendar.version,
            timezone=calendar.timezone,
            weekly=tuple(
                WeekdaySchedule(weekday=day, intervals=intervals)
                for day in calendar.working_weekdays
            ),
            # Each closure comes from this supplied calendar, not a new approval.
            exceptions=tuple(
                CalendarException(day=day, intervals=(), source=source) for day in calendar.holidays
            ),
            ambiguous_time="reject",
            timezone_rules_sha256=calendar.timezone_rules_sha256,
        )
        try:
            self._engine = WorkingTime(definition, horizon_days=horizon_days)
        except CalendarError as exc:
            raise _translated(exc) from exc
        self.timezone_rules_sha256 = self._engine.timezone_rules_sha256

    def intervals(self, day: date) -> tuple[tuple[datetime, datetime], ...]:
        try:
            return self._engine.intervals(day)
        except CalendarError as exc:
            raise _translated(exc) from exc
        except OverflowError as exc:
            raise ScheduleError(
                "HORIZON_EXCEEDED", "Calendar exceeds the supported date range"
            ) from exc

    def snap(self, instant: datetime) -> datetime:
        try:
            return self._engine.snap(instant)
        except CalendarError as exc:
            raise _translated(exc) from exc
        except OverflowError as exc:
            raise ScheduleError(
                "HORIZON_EXCEEDED", "Calculation exceeds the supported date range"
            ) from exc

    def advance(self, instant: datetime, minutes: int) -> datetime:
        if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
            raise ScheduleError(
                "INVALID_DURATION", "Working duration must be nonnegative integer minutes"
            )
        try:
            return self._engine.advance(instant, minutes)
        except CalendarError as exc:
            raise _translated(exc) from exc
        except OverflowError as exc:
            raise ScheduleError(
                "HORIZON_EXCEEDED", "Calculation exceeds the supported date range"
            ) from exc
