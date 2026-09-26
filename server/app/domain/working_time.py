"""Explicit working intervals and deterministic minute-grain time arithmetic."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Literal, Self
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from app.contracts.common_objects import Contract, WorkCalendar
from app.domain.work_calendars import CalendarCalculationError, WorkCalendarCalculator


class WorkInterval(Contract):
    start_minute: int = Field(ge=0, lt=1440)
    end_minute: int = Field(gt=0, le=1440)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end_minute <= self.start_minute:
            raise ValueError("工作时段结束须晚于开始；跨夜时段按日期拆分")
        return self


class CalendarDefinition(Contract):
    calendar: WorkCalendar
    intervals: tuple[WorkInterval, ...] = Field(min_length=1, max_length=12)
    ambiguous_time: Literal["reject", "earlier", "later"] = "reject"

    @model_validator(mode="after")
    def coherent(self) -> Self:
        ordered = sorted(self.intervals, key=lambda item: item.start_minute)
        if not self.calendar.working_weekdays:
            raise ValueError("至少设置一个工作日")
        if any(
            left.end_minute > right.start_minute
            for left, right in zip(ordered, ordered[1:], strict=False)
        ):
            raise ValueError("工作时段不能重叠")
        if (
            sum(item.end_minute - item.start_minute for item in ordered)
            != self.calendar.hours_per_workday * 60
        ):
            raise ValueError("明确时段的名义工时须与日历工时一致")
        return self


def ceil_minute(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise CalendarCalculationError("calendar_aware_instant_required")
    value = moment.astimezone(UTC)
    floor = value.replace(second=0, microsecond=0)
    return floor if value == floor else floor + timedelta(minutes=1)


def minute_quantity(hours: Decimal) -> int:
    return int((abs(hours) * 60).to_integral_value(rounding=ROUND_CEILING))


@dataclass
class WorkingTime:
    definition: CalendarDefinition

    def __post_init__(self) -> None:
        self.zone = ZoneInfo(self.definition.calendar.timezone)
        self.evidence = WorkCalendarCalculator(self.definition.calendar).evidence
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
            raise CalendarCalculationError("工作时段端点落在不存在的本地时间，请调整此日历版本")
        if len(candidates) > 1 and self.definition.ambiguous_time == "reject":
            raise CalendarCalculationError("工作时段端点处于重复时间，须明确选择较早或较晚时刻")
        return candidates[-1] if self.definition.ambiguous_time == "later" else candidates[0]

    def intervals(self, day: date) -> tuple[tuple[datetime, datetime], ...]:
        if day in self._cache:
            return self._cache[day]
        calendar = self.definition.calendar
        values = []
        if day.weekday() in calendar.working_weekdays and day not in calendar.holidays:
            midnight = datetime.combine(day, time())
            for interval in sorted(self.definition.intervals, key=lambda item: item.start_minute):
                start, end = (
                    self._instant(midnight + timedelta(minutes=interval.start_minute)),
                    self._instant(midnight + timedelta(minutes=interval.end_minute)),
                )
                if end <= start:
                    raise CalendarCalculationError("时区跳变使工作时段非正，请调整日历")
                if start.second or end.second:
                    raise CalendarCalculationError("本算法不支持历史秒级时区偏移")
                values.append((start, end))
        self._cache[day] = tuple(values)
        return tuple(values)

    def snap(self, instant: datetime) -> datetime:
        point = ceil_minute(instant)
        day = point.astimezone(self.zone).date()
        for offset in range(36601):
            for start, end in self.intervals(day + timedelta(days=offset)):
                if point < end:
                    return max(point, start)
        raise CalendarCalculationError("工作日历在100年窗口内没有可用时段")

    def advance(self, instant: datetime, minutes: int) -> datetime:
        point = ceil_minute(instant)
        if minutes == 0:
            return point
        remaining, forward = abs(minutes), minutes > 0
        day = point.astimezone(self.zone).date()
        for offset in range(36601):
            intervals = self.intervals(day + timedelta(days=offset if forward else -offset))
            for start, end in intervals if forward else reversed(intervals):
                if forward:
                    cursor = max(point, start)
                    available = max(0, int((end - cursor).total_seconds() // 60))
                    if remaining <= available:
                        return cursor + timedelta(minutes=remaining)
                else:
                    cursor = min(point, end)
                    available = max(0, int((cursor - start).total_seconds() // 60))
                    if remaining <= available:
                        return cursor - timedelta(minutes=remaining)
                remaining -= available
        raise CalendarCalculationError("所需工期超出100年计算窗口")

    def working_minutes(self, start: datetime, end: datetime) -> int:
        if end <= start:
            return 0
        first, last = start.astimezone(self.zone).date(), end.astimezone(self.zone).date()
        if (last - first).days > 36600:
            raise CalendarCalculationError("工期超出100年窗口")
        return sum(
            max(0, int((min(end, b) - max(start, a)).total_seconds() // 60))
            for offset in range((last - first).days + 1)
            for a, b in self.intervals(first + timedelta(days=offset))
        )
