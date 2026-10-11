from datetime import UTC, date
from typing import Annotated, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class _DTO(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        revalidate_instances="always",
    )


class WorkInterval(_DTO):
    start_minute: int = Field(ge=0, lt=1440, strict=True)
    end_minute: int = Field(gt=0, le=1440, strict=True)

    @model_validator(mode="after")
    def positive_interval(self) -> Self:
        if self.end_minute <= self.start_minute:
            raise ValueError("INVALID_CALENDAR: split overnight intervals at midnight")
        return self


class Calendar(_DTO):
    key: str = Field(default="default", min_length=1, max_length=80)
    version: str = Field(min_length=1, max_length=80)
    timezone: str = Field(min_length=1, max_length=100)
    working_weekdays: tuple[Annotated[int, Field(ge=0, le=6, strict=True)], ...] = Field(
        min_length=1,
    )
    intervals: tuple[WorkInterval, ...] = Field(min_length=1)
    holidays: tuple[date, ...] = Field(default=())
    timezone_rules_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("INVALID_TIMEZONE: a valid IANA timezone is required") from exc
        return value

    @model_validator(mode="after")
    def valid_calendar(self) -> Self:
        if any(isinstance(day, bool) or not 0 <= day <= 6 for day in self.working_weekdays):
            raise ValueError("INVALID_CALENDAR: weekdays must be Monday=0 through Sunday=6")
        if len(set(self.working_weekdays)) != len(self.working_weekdays):
            raise ValueError("INVALID_CALENDAR: weekdays cannot repeat")
        if len(set(self.holidays)) != len(self.holidays):
            raise ValueError("INVALID_CALENDAR: holidays cannot repeat")
        ordered = sorted(self.intervals, key=lambda item: item.start_minute)
        if any(
            left.end_minute > right.start_minute
            for left, right in zip(ordered, ordered[1:], strict=False)
        ):
            raise ValueError("INVALID_CALENDAR: working intervals cannot overlap")
        return self


class PlanTask(_DTO):
    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    title: str = Field(min_length=1, max_length=200)
    # A discipline label is not an appointment, permission or personal qualification.
    discipline: str = Field(min_length=1, max_length=80)
    depends_on: tuple[str, ...] = Field(default=())
    duration_min_minutes: int | None = Field(default=None, ge=0, le=525600, strict=True)
    duration_max_minutes: int | None = Field(default=None, ge=0, le=525600, strict=True)
    estimate_source: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def coherent_duration(self) -> Self:
        if self.duration_min_minutes is not None and self.duration_max_minutes is not None:
            if self.duration_min_minutes > self.duration_max_minutes:
                raise ValueError("INVALID_DURATION: minimum duration cannot exceed maximum")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("INVALID_DEPENDENCY: a dependency cannot repeat")
        if any(not key.strip() or len(key) > 80 for key in self.depends_on):
            raise ValueError("INVALID_DEPENDENCY: dependency keys must be nonempty")
        return self


class ScheduleInput(_DTO):
    start: AwareDatetime
    calendar: Calendar
    tasks: tuple[PlanTask, ...] = Field(min_length=1)

    @field_validator("start")
    @classmethod
    def utc_start(cls, value):
        if value.utcoffset().total_seconds() != 0:
            raise ValueError("INVALID_START: start must be an aware UTC instant")
        return value.astimezone(UTC)


class CalendarRef(_DTO):
    key: str
    version: str
    timezone: str
    timezone_rules_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class TaskSchedule(_DTO):
    key: str
    title: str
    discipline: str
    depends_on: tuple[str, ...]
    duration_min_minutes: int | None
    duration_max_minutes: int | None
    estimate_source: str | None
    earliest_start: AwareDatetime | None
    earliest_finish: AwareDatetime | None
    latest_start: AwareDatetime | None
    latest_finish: AwareDatetime | None
    calendar_ref: CalendarRef
    unknown_reasons: tuple[str, ...] = ()
    blocked_by: tuple[str, ...] = ()


class ScheduleResult(_DTO):
    algorithm_version: str = "planning.fs-duration-bounds@1"
    input_start: AwareDatetime
    calendar_ref: CalendarRef
    tasks: tuple[TaskSchedule, ...]
    earliest_finish: AwareDatetime | None
    latest_finish: AwareDatetime | None
    warnings: tuple[str, ...] = ()
