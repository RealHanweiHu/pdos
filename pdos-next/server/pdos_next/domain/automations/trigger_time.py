"""Deterministic due slots; Temporal owns waiting and only actual owners supply milestones."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

MICROSECONDS_PER_SECOND = 1_000_000


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("An aware server instant is required")
    try:
        return value.astimezone(UTC)
    except OverflowError as exc:
        raise ValueError("The instant is outside the supported UTC datetime range") from exc


def _offset_matches(value: datetime, timezone: str) -> None:
    instant = _utc(value)
    # Existing PDOS facts use canonical UTC plus an original IANA display zone.
    # A supplied non-UTC wall offset must actually exist in that zone at this instant.
    if (
        value.utcoffset() != timedelta(0)
        and value.utcoffset() != instant.astimezone(ZoneInfo(timezone)).utcoffset()
    ):
        raise ValueError("The supplied offset does not match the original IANA timezone")


class Schedule(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, str_strip_whitespace=True, revalidate_instances="always"
    )

    first_at: AwareDatetime
    calendar: Literal["weekly_monday", "weekdays"] | None = None
    original_timezone: str = Field(min_length=1, max_length=160)
    interval_seconds: int | None = Field(default=None, gt=0, strict=True)
    expires_at: AwareDatetime | None = None

    @model_serializer(mode="wrap")
    def saved_shape(self, handler):
        value = handler(self)
        if value.get("calendar") is None:
            value.pop("calendar", None)
        return value

    @field_validator("original_timezone")
    @classmethod
    def iana_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("An actual IANA timezone is required") from exc
        return value

    @model_validator(mode="after")
    def actual_offsets(self):
        _offset_matches(self.first_at, self.original_timezone)
        if self.calendar is not None:
            if self.interval_seconds is not None:
                raise ValueError("Calendar schedules cannot also use a UTC interval")
            local = self.first_at.astimezone(ZoneInfo(self.original_timezone))
            if local.weekday() not in self._weekdays():
                raise ValueError("The first slot must be an actual selected local weekday")
            if self._slot(local.date()) != _utc(self.first_at):
                raise ValueError("The first local slot must be the unambiguous canonical instant")
        if self.expires_at is not None:
            _offset_matches(self.expires_at, self.original_timezone)
        return self

    def wake_before(self, now: datetime, upper: datetime) -> datetime:
        """Next arrived slot within a bounded supervision window, even for huge periods."""
        point, bound, first = _utc(now), _utc(upper), _utc(self.first_at)
        if bound < point:
            raise ValueError("The supervision bound cannot precede its server instant")
        if point < first:
            return min(bound, first)
        if self.calendar is not None:
            local = point.astimezone(ZoneInfo(self.original_timezone))
            for offset in range(15):
                try:
                    day = local.date() + timedelta(days=offset)
                except OverflowError:
                    break
                candidate = self._slot(day)
                if candidate is not None and candidate > point and candidate >= first:
                    return min(bound, candidate)
            return bound
        if self.interval_seconds is None:
            return bound
        elapsed, window = point - first, bound - point
        elapsed_us = (
            elapsed.days * 86400 + elapsed.seconds
        ) * MICROSECONDS_PER_SECOND + elapsed.microseconds
        window_us = (
            window.days * 86400 + window.seconds
        ) * MICROSECONDS_PER_SECOND + window.microseconds
        period = self.interval_seconds * MICROSECONDS_PER_SECOND
        remaining = period - elapsed_us % period
        return bound if remaining > window_us else point + timedelta(microseconds=remaining)

    def due(self, now: datetime, *, last_due: datetime | None = None) -> datetime | None:
        if self.calendar is not None:
            point, first = _utc(now), _utc(self.first_at)
            previous = _utc(last_due) if last_due is not None else None
            if previous is not None and previous > point:
                raise ValueError("The persisted due watermark is later than the server instant")
            if point < first or (self.expires_at is not None and point >= _utc(self.expires_at)):
                return None
            local = point.astimezone(ZoneInfo(self.original_timezone))
            for offset in range(15):
                try:
                    day = local.date() - timedelta(days=offset)
                except OverflowError:
                    break
                candidate = self._slot(day)
                if candidate is not None and first <= candidate <= point:
                    return candidate if previous is None or candidate > previous else None
            return None
        return next_due(
            self.first_at,
            self.interval_seconds,
            now,
            last_due,
            expires_at=self.expires_at,
        )

    def _weekdays(self):
        return {0} if self.calendar == "weekly_monday" else {0, 1, 2, 3, 4}

    def _slot(self, day):
        if day.weekday() not in self._weekdays():
            return None
        zone = ZoneInfo(self.original_timezone)
        wall = self.first_at.astimezone(zone).replace(
            year=day.year, month=day.month, day=day.day, fold=0,
        )
        # A missing local wall time is skipped, never shifted. A repeated wall
        # time uses its earlier UTC instant once, so repeated ticks share a key.
        candidates = []
        for fold in (0, 1):
            instant = wall.replace(fold=fold).astimezone(UTC)
            if instant.astimezone(zone).replace(tzinfo=None) == wall.replace(tzinfo=None):
                candidates.append(instant)
        return min(candidates) if candidates else None


def next_due(
    first_at: datetime,
    interval_seconds: int | None,
    now: datetime,
    last_due: datetime | None = None,
    *,
    expires_at: datetime | None = None,
) -> datetime | None:
    """Return at most the latest arrived original UTC slot, never a backlog of missed runs.

    Due boundaries are inclusive; an explicitly declared expiration is exclusive.
    ``last_due`` is the persisted scheduled slot, not a completion or delivery time.
    A future watermark is rejected instead of rolling the persisted clock backward.
    """
    first, point = _utc(first_at), _utc(now)
    if interval_seconds is not None and (
        type(interval_seconds) is not int or interval_seconds <= 0
    ):
        raise ValueError("The interval must be positive integer seconds or None")
    previous = _utc(last_due) if last_due is not None else None
    expiry = _utc(expires_at) if expires_at is not None else None
    if previous is not None and previous > point:
        raise ValueError("The persisted due watermark is later than the server instant")
    if point < first or (expiry is not None and point >= expiry):
        return None
    if interval_seconds is None:
        due = first
    else:
        elapsed = point - first
        microseconds = (
            elapsed.days * 86400 + elapsed.seconds
        ) * MICROSECONDS_PER_SECOND + elapsed.microseconds
        period = interval_seconds * MICROSECONDS_PER_SECOND
        slot = microseconds // period
        due = first + timedelta(microseconds=slot * period)
    return due if previous is None or due > previous else None
