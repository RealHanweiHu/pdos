"""Planning DTO v1: fixed read snapshots, never commands or business authority."""

from datetime import UTC, date
from decimal import Decimal
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=200)]
Version = Annotated[str, Field(min_length=1, max_length=160)]
Minutes = Annotated[Decimal, Field(ge=0, le=100_000_000, allow_inf_nan=False)]
Instant = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(UTC))]


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Reference(Snapshot):
    source_id: Identifier
    version: Version


class WorkInterval(Snapshot):
    start_minute: int = Field(ge=0, lt=1440)
    end_minute: int = Field(gt=0, le=1440)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end_minute <= self.start_minute:
            raise ValueError("Split overnight shifts at local midnight")
        return self


def validate_intervals(intervals: tuple[WorkInterval, ...]) -> None:
    ordered = sorted(intervals, key=lambda item: item.start_minute)
    if any(a.end_minute > b.start_minute for a, b in zip(ordered, ordered[1:], strict=False)):
        raise ValueError("Working intervals overlap")


class WeekdaySchedule(Snapshot):
    weekday: int = Field(ge=0, le=6)
    intervals: tuple[WorkInterval, ...] = Field(max_length=12)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        validate_intervals(self.intervals)
        return self


class CalendarException(Snapshot):
    day: date
    intervals: tuple[WorkInterval, ...] = Field(max_length=12)
    source: Reference

    @model_validator(mode="after")
    def coherent(self) -> Self:
        validate_intervals(self.intervals)
        return self


class CalendarSnapshot(Snapshot):
    calendar_id: Identifier
    version: Version
    timezone: Identifier
    weekly: tuple[WeekdaySchedule, ...] = Field(max_length=7)
    exceptions: tuple[CalendarException, ...] = Field(default=(), max_length=4000)
    ambiguous_time: Literal["reject", "earlier", "later"] = "reject"
    timezone_rules_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def coherent(self) -> Self:
        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("Unknown IANA timezone") from exc
        if len({item.weekday for item in self.weekly}) != len(self.weekly):
            raise ValueError("Duplicate weekday")
        if len({item.day for item in self.exceptions}) != len(self.exceptions):
            raise ValueError("Duplicate calendar exception date")
        return self


class DurationEstimate(Snapshot):
    """None is unknown; zero must be explicit and sourced. Units are always minutes."""

    minimum: Minutes | None
    maximum: Minutes | None
    measure: Literal["total", "remaining"]
    source: Reference
    confidence: Literal["unknown", "low", "medium", "high"] = "unknown"

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.minimum is None and self.maximum is not None:
            raise ValueError("An upper estimate requires a lower estimate")
        if self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("Estimate maximum is below minimum")
        return self


class TimeWindow(Snapshot):
    earliest: Instant | None
    latest: Instant | None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.latest is not None and (self.earliest is None or self.latest < self.earliest):
            raise ValueError("Time window requires ordered bounds")
        return self

    @property
    def exact(self) -> bool:
        return self.earliest is not None and self.earliest == self.latest


class TimeRecord(Snapshot):
    time_kind: Literal["Baseline", "Forecast", "Commitment", "Actual"]
    version: Version
    original_timezone: Identifier
    source: Reference
    start: Instant | None = None
    finish: Instant | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        ZoneInfo(self.original_timezone)
        if self.start is not None and self.finish is not None and self.finish < self.start:
            raise ValueError("Finish is before start")
        return self


class ExternalWait(Snapshot):
    wait_id: Identifier
    version: Version
    source: Reference
    original_timezone: Identifier
    target: Literal["start", "finish"]
    blocking: bool
    ready: TimeWindow  # (None, None) is an explicitly unknown external readiness.

    @model_validator(mode="after")
    def coherent(self) -> Self:
        ZoneInfo(self.original_timezone)
        return self


class ResourceRequirement(Snapshot):
    resource_id: Identifier
    units: Decimal = Field(gt=0, le=1000, allow_inf_nan=False)
    occupation: Literal["work_only"] = "work_only"


class NodeSnapshot(Snapshot):
    node_id: Identifier
    calendar_id: Identifier
    work: DurationEstimate
    waiting: DurationEstimate
    waiting_clock: Literal["elapsed", "working"] = "elapsed"
    parallel_units: Decimal = Field(default=Decimal(1), gt=0, le=1000, allow_inf_nan=False)
    divisible_work: bool = False
    allocation_basis: Identifier
    not_before: Instant | None = None
    external_waits: tuple[ExternalWait, ...] = ()
    resources: tuple[ResourceRequirement, ...] = ()
    time_records: tuple[TimeRecord, ...] = ()

    @model_validator(mode="after")
    def unique(self) -> Self:
        if self.parallel_units != 1 and not self.divisible_work:
            raise ValueError("Parallel effort division requires explicit divisible work")
        for values in (
            [value.time_kind for value in self.time_records],
            [value.resource_id for value in self.resources],
            [value.wait_id for value in self.external_waits],
        ):
            if len(values) != len(set(values)):
                raise ValueError("Duplicate node snapshot identity")
        return self


class Dependency(Snapshot):
    predecessor_id: Identifier
    successor_id: Identifier
    relation: Literal["FS", "SS", "FF", "SF"] = "FS"
    lag_minutes: Decimal = Field(default=Decimal(0), allow_inf_nan=False, ge=-1e8, le=1e8)
    lag_clock: Literal["elapsed", "working"] = "working"
    source: Reference


class Occupancy(Snapshot):
    occupancy_id: Identifier
    start: Instant
    finish: Instant
    units: Decimal = Field(gt=0, le=1000, allow_inf_nan=False)
    source: Reference

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.finish <= self.start:
            raise ValueError("Occupancy must have positive elapsed duration")
        return self


class ResourceSnapshot(Snapshot):
    resource_id: Identifier
    version: Version
    calendar_id: Identifier
    capacity: Decimal = Field(gt=0, le=1000, allow_inf_nan=False)
    source: Reference
    occupancies: tuple[Occupancy, ...] = ()

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({item.occupancy_id for item in self.occupancies}) != len(self.occupancies):
            raise ValueError("Duplicate occupancy identity")
        return self


class ForecastInput(Snapshot):
    dto_version: Literal["planning.v1"] = "planning.v1"
    snapshot_id: Identifier
    version: Version
    as_of: Instant
    horizon_days: int = Field(default=366, ge=1, le=3660)
    calendars: tuple[CalendarSnapshot, ...] = Field(min_length=1, max_length=100)
    nodes: tuple[NodeSnapshot, ...] = Field(min_length=1, max_length=1000)
    dependencies: tuple[Dependency, ...] = Field(default=(), max_length=10000)
    resources: tuple[ResourceSnapshot, ...] = Field(default=(), max_length=1000)


class Issue(Snapshot):
    code: str
    message: str
    node_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    blocking: bool = True


class NodeForecast(Snapshot):
    node_id: str
    calendar_id: str
    calendar_version: str
    original_timezone: str
    start: TimeWindow
    finish: TimeWindow
    remaining_work_start: TimeWindow
    remaining_work_finish: TimeWindow
    status: Literal["exact", "range", "unknown", "conflicted"]
    origin: Literal["estimate", "actual_and_remaining", "actual_anchor"]
    issues: tuple[Issue, ...] = ()
    latest_start: Instant | None = None
    latest_finish: Instant | None = None
    float_minutes: int | None = None
    working_float_minutes: int | None = None
    critical: bool | None = None


class ForecastResult(Snapshot):
    dto_version: Literal["planning.v1"] = "planning.v1"
    algorithm_version: str
    time_kind: Literal["Forecast"] = "Forecast"
    disposition: Literal["candidate"] = "candidate"
    input_sha256: str
    candidate_sha256: str
    input_snapshot: ForecastInput
    timezone_rule_digests: tuple[tuple[str, str], ...]
    status: Literal["complete", "partial", "invalid"]
    project_finish: TimeWindow
    nodes: tuple[NodeForecast, ...]
    issues: tuple[Issue, ...]
    capacity_status: Literal["not_requested", "checked", "unknown", "conflicted"]
    float_status: Literal["calculated", "not_calculated"]
