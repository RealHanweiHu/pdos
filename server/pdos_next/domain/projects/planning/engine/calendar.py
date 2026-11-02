"""UTC arithmetic over explicit local working intervals and frozen TZif rules."""

import hashlib
import io
from datetime import UTC, date, datetime, time, timedelta
from importlib.resources import files
from pathlib import Path
from zoneinfo import TZPATH, ZoneInfo

from .dto import CalendarSnapshot


class CalendarError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def ceil_minute(moment: datetime) -> datetime:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise CalendarError("aware_instant_required", "An aware instant is required")
    try:
        point = moment.astimezone(UTC)
        floor = point.replace(second=0, microsecond=0)
        return floor if point == floor else floor + timedelta(minutes=1)
    except OverflowError as exc:
        raise CalendarError("datetime_overflow", "Minute rounding exceeds datetime range") from exc


def _offset_day(day: date, offset: int) -> date:
    try:
        return day + timedelta(days=offset)
    except OverflowError as exc:
        raise CalendarError("datetime_overflow", "Calendar exceeds supported date range") from exc


def frozen_timezone(name: str) -> tuple[ZoneInfo, str]:
    ZoneInfo(name)  # Validate the key before using it as a relative path.
    for root in TZPATH:
        path = Path(root) / name
        if path.is_file():
            data = path.read_bytes()
            break
    else:
        try:
            data = files("tzdata.zoneinfo").joinpath(*name.split("/")).read_bytes()
        except (ModuleNotFoundError, FileNotFoundError) as exc:
            raise CalendarError("timezone_rules_unavailable", "TZif rules unavailable") from exc
    return ZoneInfo.from_file(io.BytesIO(data), key=name), hashlib.sha256(data).hexdigest()


class WorkingTime:
    def __init__(self, definition: CalendarSnapshot, horizon_days: int = 366):
        if not 1 <= horizon_days <= 3660:
            raise ValueError("Calendar horizon must be between 1 and 3660 days")
        self.definition = definition
        self.horizon_days = horizon_days
        self.zone, self.timezone_rules_sha256 = frozen_timezone(definition.timezone)
        expected = definition.timezone_rules_sha256
        if expected is not None and expected != self.timezone_rules_sha256:
            raise CalendarError("timezone_rules_changed", "Pinned timezone rules do not match")
        self._weekly = {item.weekday: item.intervals for item in definition.weekly}
        self._exceptions = {item.day: item.intervals for item in definition.exceptions}
        self._cache: dict[date, tuple[tuple[datetime, datetime], ...]] = {}

    def _instant(self, wall: datetime) -> datetime:
        candidates = sorted(
            {
                value.astimezone(UTC)
                for fold in (0, 1)
                if (value := wall.replace(tzinfo=self.zone, fold=fold))
                .astimezone(UTC)
                .astimezone(self.zone)
                .replace(tzinfo=None)
                == wall
            }
        )
        if not candidates:
            raise CalendarError("nonexistent_local_time", "Shift endpoint falls in a DST gap")
        if len(candidates) > 1 and self.definition.ambiguous_time == "reject":
            raise CalendarError("ambiguous_local_time", "Shift endpoint requires a fold policy")
        return candidates[-1] if self.definition.ambiguous_time == "later" else candidates[0]

    def intervals(self, day: date) -> tuple[tuple[datetime, datetime], ...]:
        if day in self._cache:
            return self._cache[day]
        intervals = self._exceptions.get(day, self._weekly.get(day.weekday(), ()))
        midnight = datetime.combine(day, time())
        values = []
        for interval in sorted(intervals, key=lambda value: value.start_minute):
            try:
                start = self._instant(midnight + timedelta(minutes=interval.start_minute))
                end = self._instant(midnight + timedelta(minutes=interval.end_minute))
            except OverflowError as exc:
                raise CalendarError("datetime_overflow", "Shift exceeds datetime range") from exc
            if end <= start or (values and start < values[-1][1]):
                raise CalendarError("invalid_utc_interval", "Timezone transition invalidates shift")
            if start.second or end.second:
                raise CalendarError("subminute_timezone_offset", "Second-based historical offset")
            values.append((start, end))
        self._cache[day] = tuple(values)
        return tuple(values)

    def snap(self, instant: datetime) -> datetime:
        point = ceil_minute(instant)
        day = point.astimezone(self.zone).date()
        for offset in range(self.horizon_days + 1):
            for start, end in self.intervals(_offset_day(day, offset)):
                if point < end:
                    return max(point, start)
        raise CalendarError("calendar_horizon_exhausted", "No working time in calculation horizon")

    def advance(self, instant: datetime, minutes: int) -> datetime:
        if not isinstance(minutes, int) or isinstance(minutes, bool):
            raise CalendarError("whole_minutes_required", "Advance requires signed whole minutes")
        point = ceil_minute(instant)
        if minutes == 0:
            return point
        remaining, forward = abs(minutes), minutes > 0
        day = point.astimezone(self.zone).date()
        for offset in range(self.horizon_days + 1):
            intervals = self.intervals(_offset_day(day, offset if forward else -offset))
            for start, end in intervals if forward else reversed(intervals):
                cursor = max(point, start) if forward else min(point, end)
                available = max(
                    0, int(((end - cursor) if forward else (cursor - start)).total_seconds() // 60)
                )
                if remaining <= available:
                    return cursor + timedelta(minutes=remaining if forward else -remaining)
                remaining -= available
        raise CalendarError("calendar_horizon_exhausted", "Duration exceeds calculation horizon")

    def segments(self, start: datetime, finish: datetime) -> tuple[tuple[datetime, datetime], ...]:
        # Convert before comparison: equal-zone wall-time subtraction is wrong across DST.
        start, finish = ceil_minute(start), ceil_minute(finish)
        if finish <= start:
            return ()
        first = start.astimezone(self.zone).date()
        last = (finish - timedelta(microseconds=1)).astimezone(self.zone).date()
        if (last - first).days > self.horizon_days:
            raise CalendarError(
                "calendar_horizon_exhausted", "Interval exceeds calculation horizon"
            )
        return tuple(
            (max(start, left), min(finish, right))
            for offset in range((last - first).days + 1)
            for left, right in self.intervals(_offset_day(first, offset))
            if max(start, left) < min(finish, right)
        )

    def working_minutes(self, start: datetime, finish: datetime) -> int:
        return sum(int((b - a).total_seconds() // 60) for a, b in self.segments(start, finish))
