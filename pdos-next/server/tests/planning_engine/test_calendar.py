"""Calendar boundary cases using only immutable snapshots and UTC arithmetic."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from pdos_next.engines.planning.calendar import (
    CalendarError,
    WorkingTime,
    ceil_minute,
    frozen_timezone,
)
from pdos_next.engines.planning.dto import (
    CalendarException,
    CalendarSnapshot,
    Reference,
    WeekdaySchedule,
    WorkInterval,
)


def shift(start: int, end: int) -> WorkInterval:
    return WorkInterval(start_minute=start, end_minute=end)


def snapshot(
    *,
    timezone: str = "UTC",
    weekly: tuple[WeekdaySchedule, ...] | None = None,
    exceptions: tuple[CalendarException, ...] = (),
    ambiguous_time: str = "reject",
    rules_digest: str | None = None,
) -> CalendarSnapshot:
    return CalendarSnapshot(
        calendar_id="factory-calendar",
        version="v1",
        timezone=timezone,
        weekly=weekly
        if weekly is not None
        else tuple(
            WeekdaySchedule(weekday=day, intervals=(shift(540, 720), shift(780, 1020)))
            for day in range(5)
        ),
        exceptions=exceptions,
        ambiguous_time=ambiguous_time,
        timezone_rules_sha256=rules_digest,
    )


def exception(day: date, *intervals: WorkInterval) -> CalendarException:
    return CalendarException(
        day=day,
        intervals=intervals,
        source=Reference(source_id="approved-calendar-input", version="v1"),
    )


def test_lunch_break_is_excluded_from_positive_and_negative_work() -> None:
    engine = WorkingTime(snapshot())
    before_lunch = datetime(2026, 10, 2, 11, 30, tzinfo=UTC)
    after_lunch = datetime(2026, 10, 2, 14, tzinfo=UTC)

    assert engine.advance(before_lunch, 90) == after_lunch
    assert engine.advance(after_lunch, -90) == before_lunch
    assert engine.working_minutes(before_lunch, after_lunch) == 90
    assert engine.snap(datetime(2026, 10, 2, 12, tzinfo=UTC)) == datetime(
        2026, 10, 2, 13, tzinfo=UTC
    )


def test_weekend_and_closed_holiday_are_skipped_in_both_directions() -> None:
    engine = WorkingTime(snapshot(exceptions=(exception(date(2026, 10, 5)),)))
    friday = datetime(2026, 10, 2, 16, tzinfo=UTC)
    tuesday = datetime(2026, 10, 6, 10, tzinfo=UTC)

    assert engine.advance(friday, 120) == tuesday
    assert engine.advance(tuesday, -120) == friday
    assert engine.intervals(date(2026, 10, 5)) == ()
    assert engine.snap(datetime(2026, 10, 2, 17, tzinfo=UTC)) == datetime(
        2026, 10, 6, 9, tzinfo=UTC
    )


def test_weekend_overtime_exception_replaces_the_weekly_schedule() -> None:
    engine = WorkingTime(snapshot(exceptions=(exception(date(2026, 10, 3), shift(600, 720)),)))
    friday = datetime(2026, 10, 2, 16, tzinfo=UTC)

    assert engine.advance(friday, 120) == datetime(2026, 10, 3, 11, tzinfo=UTC)
    assert engine.snap(datetime(2026, 10, 3, 9, tzinfo=UTC)) == datetime(
        2026, 10, 3, 10, tzinfo=UTC
    )
    assert (
        engine.working_minutes(datetime(2026, 10, 3, tzinfo=UTC), datetime(2026, 10, 4, tzinfo=UTC))
        == 120
    )


def test_overnight_work_is_explicitly_split_at_local_midnight() -> None:
    engine = WorkingTime(
        snapshot(
            weekly=(
                WeekdaySchedule(weekday=0, intervals=(shift(1320, 1440),)),
                WeekdaySchedule(weekday=1, intervals=(shift(0, 360),)),
            )
        )
    )
    start = datetime(2026, 10, 5, 22, tzinfo=UTC)
    midnight = datetime(2026, 10, 6, tzinfo=UTC)
    finish = datetime(2026, 10, 6, 6, tzinfo=UTC)

    assert engine.advance(start, 480) == finish
    assert engine.advance(finish, -480) == start
    assert engine.segments(start, finish) == ((start, midnight), (midnight, finish))
    with pytest.raises(ValidationError, match="Split overnight shifts"):
        shift(1320, 360)


def test_next_date_closure_overrides_the_after_midnight_shift_fragment() -> None:
    engine = WorkingTime(
        snapshot(
            weekly=(
                WeekdaySchedule(weekday=0, intervals=(shift(1320, 1440),)),
                WeekdaySchedule(weekday=1, intervals=(shift(0, 360),)),
            ),
            exceptions=(exception(date(2026, 10, 6)),),
        )
    )
    start = datetime(2026, 10, 5, 22, tzinfo=UTC)
    assert engine.working_minutes(start, datetime(2026, 10, 6, 6, tzinfo=UTC)) == 120
    assert engine.advance(start, 180) == datetime(2026, 10, 12, 23, tzinfo=UTC)


@pytest.mark.parametrize(
    "day,start,finish,elapsed_minutes",
    [
        (
            date(2026, 3, 8),
            datetime(2026, 3, 8, 8, tzinfo=UTC),
            datetime(2026, 3, 8, 11, tzinfo=UTC),
            180,
        ),
        (
            date(2026, 11, 1),
            datetime(2026, 11, 1, 7, tzinfo=UTC),
            datetime(2026, 11, 1, 12, tzinfo=UTC),
            300,
        ),
    ],
)
def test_la_dst_work_uses_real_elapsed_minutes(
    day: date, start: datetime, finish: datetime, elapsed_minutes: int
) -> None:
    engine = WorkingTime(
        snapshot(
            timezone="America/Los_Angeles",
            weekly=(WeekdaySchedule(weekday=6, intervals=(shift(0, 240),)),),
        )
    )

    assert engine.intervals(day) == ((start, finish),)
    assert engine.working_minutes(start, finish) == elapsed_minutes
    assert engine.advance(start, elapsed_minutes) == finish
    assert engine.advance(finish, -elapsed_minutes) == start


def test_dst_gap_endpoint_is_rejected_without_inventing_a_work_instant() -> None:
    engine = WorkingTime(
        snapshot(
            timezone="America/Los_Angeles",
            weekly=(WeekdaySchedule(weekday=6, intervals=(shift(120, 180),)),),
        )
    )
    with pytest.raises(CalendarError) as failure:
        engine.intervals(date(2026, 3, 8))
    assert failure.value.code == "nonexistent_local_time"


def test_repeated_endpoint_requires_an_explicit_fold_policy() -> None:
    engine = WorkingTime(
        snapshot(
            timezone="America/Los_Angeles",
            weekly=(WeekdaySchedule(weekday=6, intervals=(shift(90, 120),)),),
        )
    )
    with pytest.raises(CalendarError) as failure:
        engine.intervals(date(2026, 11, 1))
    assert failure.value.code == "ambiguous_local_time"


@pytest.mark.parametrize("policy,start_hour,minutes", [("earlier", 8, 90), ("later", 9, 30)])
def test_repeated_endpoint_fold_selection_changes_the_real_interval(
    policy: str, start_hour: int, minutes: int
) -> None:
    engine = WorkingTime(
        snapshot(
            timezone="America/Los_Angeles",
            weekly=(WeekdaySchedule(weekday=6, intervals=(shift(90, 120),)),),
            ambiguous_time=policy,
        )
    )
    start = datetime(2026, 11, 1, start_hour, 30, tzinfo=UTC)
    finish = datetime(2026, 11, 1, 10, tzinfo=UTC)

    assert engine.intervals(date(2026, 11, 1)) == ((start, finish),)
    assert engine.working_minutes(start, finish) == minutes


def test_local_inputs_and_all_calculated_segments_return_utc() -> None:
    engine = WorkingTime(snapshot(timezone="Asia/Shanghai"))
    local = datetime(2026, 10, 2, 16, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    finish = engine.advance(local, 60)

    assert finish == datetime(2026, 10, 5, 1, 30, tzinfo=UTC)
    assert finish.tzinfo is UTC
    assert engine.advance(local, 0).tzinfo is UTC
    assert all(
        left.tzinfo is UTC and right.tzinfo is UTC for left, right in engine.segments(local, finish)
    )


def test_minute_ceiling_normalizes_timezone_and_rejects_naive_instants() -> None:
    local = datetime(2026, 10, 2, 9, 0, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert ceil_minute(local) == datetime(2026, 10, 2, 1, 1, tzinfo=UTC)
    with pytest.raises(CalendarError) as failure:
        ceil_minute(datetime(2026, 10, 2, 9))
    assert failure.value.code == "aware_instant_required"


def test_timezone_rule_digest_can_be_pinned_and_replayed() -> None:
    zone, digest = frozen_timezone("America/Los_Angeles")
    definition = snapshot(timezone="America/Los_Angeles", rules_digest=digest)
    first = WorkingTime(definition)
    second = WorkingTime(definition)
    day = date(2026, 10, 2)

    assert zone.key == "America/Los_Angeles"
    assert len(digest) == 64 and int(digest, 16) >= 0
    assert first.timezone_rules_sha256 == second.timezone_rules_sha256 == digest
    assert first.intervals(day) == second.intervals(day)
    assert definition.timezone_rules_sha256 == digest


def test_changed_timezone_rule_digest_refuses_calculation() -> None:
    _, digest = frozen_timezone("America/Los_Angeles")
    different = ("1" if digest[0] != "1" else "0") + digest[1:]
    with pytest.raises(CalendarError) as failure:
        WorkingTime(snapshot(timezone="America/Los_Angeles", rules_digest=different))
    assert failure.value.code == "timezone_rules_changed"


@pytest.mark.parametrize("operation", ["snap", "forward", "backward"])
def test_empty_calendar_stops_at_its_finite_horizon(operation: str) -> None:
    engine = WorkingTime(snapshot(weekly=()), horizon_days=2)
    anchor = datetime(2026, 10, 2, 9, tzinfo=UTC)
    with pytest.raises(CalendarError) as failure:
        if operation == "snap":
            engine.snap(anchor)
        else:
            engine.advance(anchor, 1 if operation == "forward" else -1)
    assert failure.value.code == "calendar_horizon_exhausted"
    assert engine.advance(anchor, 0) == anchor


def test_long_segment_request_respects_the_calendar_horizon() -> None:
    engine = WorkingTime(snapshot(), horizon_days=2)
    start = datetime(2026, 10, 2, 9, tzinfo=UTC)
    with pytest.raises(CalendarError) as failure:
        engine.working_minutes(start, start + timedelta(days=3))
    assert failure.value.code == "calendar_horizon_exhausted"


@pytest.mark.parametrize("horizon", [0, 3661])
def test_calendar_horizon_is_bounded(horizon: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 3660"):
        WorkingTime(snapshot(), horizon_days=horizon)
