"""Date-grain calculations for the approved WorkCalendar contract.

Pure calculations: no authorization, reservations, shifts, database or model calls.
hours_per_workday is nominal effort, never an inferred intraday shift or capacity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
from importlib import resources
from io import BytesIO
from pathlib import Path
from uuid import UUID
from zoneinfo import TZPATH, ZoneInfo

from app.contracts.common_objects import WorkCalendar

ALGORITHM_VERSION = "work_calendar.date_grain.v2"
MAX_SCAN_DAYS = 36600


class CalendarCalculationError(ValueError):
    """A stable reason code; the caller must expose missing/unsupported inputs."""


@dataclass(frozen=True)
class CalendarEvidence:
    calendar_id: UUID
    calendar_version: int
    calendar_digest: str
    timezone: str
    timezone_rules_digest: str
    algorithm_version: str = ALGORITHM_VERSION


@dataclass(frozen=True)
class CalendarDay:
    local_date: date
    start_utc: datetime
    end_utc: datetime
    working: bool
    nominal_hours: Decimal
    evidence: CalendarEvidence

    @property
    def elapsed_seconds(self) -> int:
        return int((self.end_utc - self.start_utc).total_seconds())


@dataclass(frozen=True)
class CalendarPeriod:
    start_date: date
    end_date_exclusive: date
    working_dates: tuple[date, ...]
    skipped_dates: tuple[date, ...]
    nominal_hours: Decimal
    evidence: CalendarEvidence


def _zone_rules(key: str) -> bytes:
    # WorkCalendar already validates ZoneInfo keys. Keep file access constrained
    # even if a caller bypassed Pydantic construction with model_construct().
    if not key or key.startswith("/") or any(p in {"", ".", ".."} for p in key.split("/")):
        raise CalendarCalculationError("calendar_timezone_invalid")
    for directory in TZPATH:
        candidate = Path(directory) / key
        if candidate.is_file():
            return candidate.read_bytes()
    try:
        package, _, resource = key.rpartition("/")
        return (
            resources.files(
                "tzdata.zoneinfo" + ("." + package.replace("/", ".") if package else "")
            )
            .joinpath(resource or key)
            .read_bytes()
        )
    except (ModuleNotFoundError, FileNotFoundError) as exc:
        raise CalendarCalculationError("calendar_timezone_rules_unavailable") from exc


@dataclass(frozen=True)
class WorkCalendarCalculator:
    calendar: WorkCalendar
    evidence: CalendarEvidence = field(init=False)
    _zone: ZoneInfo = field(init=False, repr=False)

    def __post_init__(self) -> None:
        rules = _zone_rules(self.calendar.timezone)
        object.__setattr__(
            self, "_zone", ZoneInfo.from_file(BytesIO(rules), key=self.calendar.timezone)
        )
        object.__setattr__(
            self,
            "evidence",
            CalendarEvidence(
                calendar_id=self.calendar.id,
                calendar_version=self.calendar.version,
                calendar_digest=sha256(self.calendar.model_dump_json().encode()).hexdigest(),
                timezone=self.calendar.timezone,
                timezone_rules_digest=sha256(rules).hexdigest(),
            ),
        )

    def local_date(self, instant: datetime) -> date:
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise CalendarCalculationError("calendar_aware_instant_required")
        try:
            return instant.astimezone(self._zone).date()
        except OverflowError as exc:
            raise CalendarCalculationError("calendar_date_out_of_range") from exc

    def _day_boundary(self, day: date) -> datetime:
        """First instant of a civil date, or the jump past an omitted date.

        This is a date boundary, not disambiguation of a user's wall-clock
        appointment. A repeated midnight starts at its first occurrence; a gap
        starts at the transition. Dates that leave and re-enter across a backward
        date change cannot be represented by our single interval and are rejected.
        """
        local = datetime.combine(day, time.min)
        candidates: set[datetime] = set()
        projections: set[datetime] = set()
        for fold in (0, 1):
            instant = local.replace(tzinfo=self._zone, fold=fold).astimezone(UTC)
            projections.add(instant)
            if instant.astimezone(self._zone).replace(tzinfo=None) == local:
                candidates.add(instant)
        if candidates:
            first, last = min(candidates), max(candidates)
            if (
                first != last
                and (last - timedelta(microseconds=1)).astimezone(self._zone).date() < day
            ):
                raise CalendarCalculationError("calendar_noncontiguous_date")
            return first

        before, after = min(projections), max(projections)
        if not before.astimezone(self._zone).date() < day <= after.astimezone(self._zone).date():
            raise CalendarCalculationError("calendar_boundary_unresolvable")
        # TZif offsets and transitions have integral-second precision. Search the
        # fold projections of this gap, never infer that midnight exists or that
        # every civil date is 24 hours long.
        while (after - before).total_seconds() > 1:
            middle = before + timedelta(seconds=int((after - before).total_seconds()) // 2)
            if middle.astimezone(self._zone).date() < day:
                before = middle
            else:
                after = middle
        return after

    def day(self, day: date) -> CalendarDay:
        if isinstance(day, datetime):
            raise CalendarCalculationError("calendar_date_required")
        try:
            following = day + timedelta(days=1)
            start, end = self._day_boundary(day), self._day_boundary(following)
        except OverflowError as exc:
            raise CalendarCalculationError("calendar_date_out_of_range") from exc
        if start.astimezone(self._zone).date() != day or start == end:
            raise CalendarCalculationError("calendar_date_nonexistent")
        if end < start:
            raise CalendarCalculationError("calendar_boundary_unresolvable")
        working = (
            day.weekday() in self.calendar.working_weekdays and day not in self.calendar.holidays
        )
        return CalendarDay(
            local_date=day,
            start_utc=start,
            end_utc=end,
            working=working,
            nominal_hours=self.calendar.hours_per_workday if working else Decimal(0),
            evidence=self.evidence,
        )

    def period(self, start: date, end_exclusive: date) -> CalendarPeriod:
        if isinstance(start, datetime) or isinstance(end_exclusive, datetime):
            raise CalendarCalculationError("calendar_date_required")
        days = (end_exclusive - start).days
        if days < 0:
            raise CalendarCalculationError("calendar_period_reversed")
        if days > MAX_SCAN_DAYS:
            raise CalendarCalculationError("calendar_scan_limit")
        working, skipped = [], []
        for offset in range(days):
            current = start + timedelta(days=offset)
            result = self._existing_day(current)
            if result is None:
                skipped.append(current)
            elif result.working:
                working.append(current)
        return CalendarPeriod(
            start_date=start,
            end_date_exclusive=end_exclusive,
            working_dates=tuple(working),
            skipped_dates=tuple(skipped),
            nominal_hours=len(working) * self.calendar.hours_per_workday,
            evidence=self.evidence,
        )

    def _existing_day(self, day: date) -> CalendarDay | None:
        try:
            return self.day(day)
        except CalendarCalculationError as exc:
            if str(exc) != "calendar_date_nonexistent":
                raise
            return None

    def shift_workdays(self, anchor: date, days: int, *, scan_limit: int = 3660) -> date:
        """Exclude anchor; move to the Nth working date in either direction.

        Zero preserves anchor, even if non-working. This is not start normalization
        or a fractional-hour/lag engine. Empty calendars and exhausted searches fail.
        """
        if isinstance(anchor, datetime):
            raise CalendarCalculationError("calendar_date_required")
        if type(days) is not int:
            raise CalendarCalculationError("calendar_integer_workdays_required")
        if type(scan_limit) is not int or not 1 <= scan_limit <= MAX_SCAN_DAYS:
            raise CalendarCalculationError("calendar_scan_limit_invalid")
        if self._existing_day(anchor) is None:
            raise CalendarCalculationError("calendar_date_nonexistent")
        if days == 0:
            return anchor
        if not self.calendar.working_weekdays:
            raise CalendarCalculationError("calendar_no_working_weekdays")
        direction = 1 if days > 0 else -1
        remaining = abs(days)
        current = anchor
        for _ in range(scan_limit):
            try:
                current += timedelta(days=direction)
            except OverflowError as exc:
                raise CalendarCalculationError("calendar_date_out_of_range") from exc
            result = self._existing_day(current)
            if result is not None and result.working:
                remaining -= 1
                if remaining == 0:
                    return current
        raise CalendarCalculationError("calendar_scan_limit")
