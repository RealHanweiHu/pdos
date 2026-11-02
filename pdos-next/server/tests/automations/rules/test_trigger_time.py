"""Pure schedule slots retain actual instants, expiration and persisted dedupe watermarks."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from pdos_next.domain.automations.trigger_time import Schedule, next_due

FIRST = datetime(2026, 10, 18, 10, tzinfo=UTC)


def schedule(**values):
    return Schedule.model_validate(
        {"first_at": FIRST, "original_timezone": "Asia/Shanghai", **values}
    )


def test_closed_schedule_accepts_canonical_utc_and_retains_original_iana_zone_without_default_ttl():
    fixed = schedule()
    assert fixed.first_at == FIRST and fixed.original_timezone == "Asia/Shanghai"
    assert fixed.interval_seconds is None and fixed.expires_at is None
    assert Schedule.model_validate_json(fixed.model_dump_json()) == fixed
    for extra in ({"cron": "* * * * *"}, {"timezone_offset": "+08:00"}, {"authorized": True}):
        with pytest.raises(ValidationError):
            schedule(**extra)


@pytest.mark.parametrize("interval", [0, -1, True, "60", 1.5])
def test_interval_is_a_positive_integer_or_one_shot(interval):
    with pytest.raises(ValidationError):
        schedule(interval_seconds=interval)
    with pytest.raises(ValueError):
        next_due(FIRST, interval, FIRST)


@pytest.mark.parametrize("timezone", ["", "UTC+08:00", "No/Such_Zone"])
def test_timezone_must_be_an_actual_iana_name(timezone):
    with pytest.raises(ValidationError):
        schedule(original_timezone=timezone)


def test_given_non_utc_offset_must_match_the_iana_zone_at_that_instant():
    correct = datetime.fromisoformat("2026-10-18T18:00:00+08:00")
    fixed = schedule(first_at=correct)
    assert fixed.due(FIRST) == FIRST
    for incorrect in (
        datetime.fromisoformat("2026-10-18T18:00:00+07:00"),
        datetime.fromisoformat("2026-03-08T02:30:00-08:00"),
    ):
        with pytest.raises(ValidationError):
            schedule(
                first_at=incorrect,
                original_timezone="America/Los_Angeles"
                if incorrect.month == 3
                else "Asia/Shanghai",
            )
    with pytest.raises(ValidationError):
        schedule(expires_at=datetime.fromisoformat("2026-10-19T18:00:00+07:00"))


def test_due_is_inclusive_but_explicit_expiration_is_exclusive():
    expiry = FIRST + timedelta(seconds=20)
    fixed = schedule(interval_seconds=10, expires_at=expiry)
    assert fixed.due(FIRST - timedelta(microseconds=1)) is None
    assert fixed.due(FIRST) == FIRST
    assert fixed.due(FIRST + timedelta(seconds=10)) == FIRST + timedelta(seconds=10)
    assert fixed.due(expiry - timedelta(microseconds=1)) == FIRST + timedelta(seconds=10)
    assert fixed.due(expiry) is None and fixed.due(expiry + timedelta(days=1)) is None
    assert schedule().due(FIRST + timedelta(days=36500)) == FIRST


def test_one_shot_returns_the_original_slot_once_even_after_a_late_wakeup():
    fixed = schedule()
    assert fixed.due(FIRST + timedelta(days=5)) == FIRST
    assert fixed.due(FIRST + timedelta(days=5), last_due=FIRST) is None
    assert fixed.due(FIRST, last_due=FIRST) is None


def test_missed_intervals_coalesce_to_one_latest_original_slot_for_deduplication():
    fixed = schedule(interval_seconds=3600)
    late = FIRST + timedelta(days=36500, hours=3, minutes=59, seconds=59)
    expected = FIRST + timedelta(days=36500, hours=3)
    assert fixed.due(late) == expected
    assert fixed.due(late + timedelta(microseconds=1), last_due=expected) is None
    assert fixed.due(expected + timedelta(hours=1), last_due=expected) == expected + timedelta(
        hours=1
    )
    # Completion or retry time never replaces the original scheduled slot.
    assert fixed.due(late, last_due=FIRST) == expected


def test_microsecond_anchor_is_preserved_without_float_rounding_or_catchup_loops():
    anchor = FIRST.replace(microsecond=123456)
    fixed = schedule(first_at=anchor, interval_seconds=3)
    assert fixed.due(anchor + timedelta(seconds=8, microseconds=999999)) == anchor + timedelta(
        seconds=6
    )
    assert fixed.due(anchor + timedelta(seconds=9)) == anchor + timedelta(seconds=9)
    assert schedule(interval_seconds=10**30).due(FIRST + timedelta(days=36500)) == FIRST


def test_dst_spring_gap_and_fall_fold_do_not_change_absolute_interval_seconds():
    zone = ZoneInfo("America/Los_Angeles")
    spring = schedule(
        first_at=datetime(2026, 3, 8, 1, 30, tzinfo=zone),
        original_timezone=zone.key,
        interval_seconds=3600,
    )
    spring_due = spring.due(datetime(2026, 3, 8, 3, 30, tzinfo=zone))
    assert spring_due == datetime(2026, 3, 8, 10, 30, tzinfo=UTC)
    assert (spring_due - spring.first_at.astimezone(UTC)).total_seconds() == 3600
    fall = schedule(
        first_at=datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0),
        original_timezone=zone.key,
        interval_seconds=3600,
    )
    folded = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
    due = fall.due(folded)
    assert due == datetime(2026, 11, 1, 9, 30, tzinfo=UTC)
    assert due > fall.first_at.astimezone(UTC)
    assert fall.due(folded, last_due=due) is None


def test_future_watermark_is_explicitly_rejected_instead_of_regressing_it():
    with pytest.raises(ValueError, match="watermark"):
        next_due(FIRST, 60, FIRST, last_due=FIRST + timedelta(seconds=1))
    prior = FIRST + timedelta(seconds=30)
    assert next_due(FIRST, 60, prior, last_due=prior) is None
    assert next_due(FIRST, 60, FIRST + timedelta(seconds=60), last_due=prior) == FIRST + timedelta(
        seconds=60
    )


def test_naive_times_are_never_interpreted_using_the_host_machine_timezone():
    naive = FIRST.replace(tzinfo=None)
    for fields in ({"first_at": naive}, {"expires_at": naive}):
        with pytest.raises(ValidationError):
            schedule(**fields)
    for args in (
        (naive, None, FIRST, None),
        (FIRST, None, naive, None),
        (FIRST, None, FIRST, naive),
    ):
        with pytest.raises(ValueError, match="aware"):
            next_due(*args)
    with pytest.raises(ValueError, match="aware"):
        next_due(FIRST, None, FIRST, expires_at=naive)


def test_supervision_wake_uses_original_slot_and_bounds_huge_periods():
    point = FIRST + timedelta(seconds=4, microseconds=500_000)
    bound = point + timedelta(seconds=30)
    assert schedule(interval_seconds=10).wake_before(point, bound) == FIRST + timedelta(seconds=10)
    assert schedule(interval_seconds=10**30).wake_before(point, bound) == bound
    assert schedule(first_at=bound + timedelta(days=1)).wake_before(point, bound) == bound
    assert schedule().wake_before(point, bound) == bound
    with pytest.raises(ValueError):
        schedule().wake_before(point, point - timedelta(microseconds=1))
