from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.contracts.common_objects import TimeWindow, WorkCalendar
from app.domain.work_calendars import (
    MAX_SCAN_DAYS,
    CalendarCalculationError,
    WorkCalendarCalculator,
)


def calculator(
    timezone: str = "America/Los_Angeles",
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4),
    holidays: tuple[date, ...] = (),
) -> WorkCalendarCalculator:
    return WorkCalendarCalculator(
        WorkCalendar(
            id=uuid4(),
            tenant_id=uuid4(),
            version=1,
            timezone=timezone,
            working_weekdays=weekdays,
            holidays=holidays,
            hours_per_workday=Decimal("7.5"),
        )
    )


def test_shift_skips_weekend_and_explicit_holiday_in_both_directions() -> None:
    calc = calculator(holidays=(date(2026, 9, 7),))
    assert calc.shift_workdays(date(2026, 9, 4), 1) == date(2026, 9, 8)
    assert calc.shift_workdays(date(2026, 9, 8), -1) == date(2026, 9, 4)
    assert calc.shift_workdays(date(2026, 9, 6), 0) == date(2026, 9, 6)


def test_period_is_half_open_and_nominal_hours_are_decimal() -> None:
    calc = calculator(holidays=(date(2026, 9, 7),))
    result = calc.period(date(2026, 9, 4), date(2026, 9, 9))
    assert result.working_dates == (date(2026, 9, 4), date(2026, 9, 8))
    assert result.nominal_hours == Decimal("15.0")
    assert calc.period(date(2026, 9, 9), date(2026, 9, 9)).nominal_hours == 0


@pytest.mark.parametrize("day,hours", [(date(2026, 3, 8), 23), (date(2026, 11, 1), 25)])
def test_dst_utc_day_length_is_not_nominal_work_effort(day: date, hours: int) -> None:
    result = calculator(weekdays=tuple(range(7))).day(day)
    assert result.elapsed_seconds == hours * 3600
    assert result.nominal_hours == Decimal("7.5")
    assert result.start_utc.tzinfo == UTC and result.end_utc.tzinfo == UTC


def test_same_instant_is_resolved_against_each_site_calendar() -> None:
    instant = datetime(2026, 9, 7, 0, 30, tzinfo=UTC)
    assert calculator().local_date(instant) == date(2026, 9, 6)
    assert calculator("Asia/Shanghai").local_date(instant) == date(2026, 9, 7)
    with pytest.raises(CalendarCalculationError, match="aware_instant"):
        calculator().local_date(datetime(2026, 9, 7))


def test_empty_workweek_is_known_zero_but_cannot_resolve_positive_duration() -> None:
    calc = calculator(weekdays=())
    assert calc.period(date(2026, 9, 1), date(2026, 10, 1)).nominal_hours == 0
    with pytest.raises(CalendarCalculationError, match="no_working_weekdays"):
        calc.shift_workdays(date(2026, 9, 1), 1)


def test_fully_blocked_horizon_stops_without_fabricated_date() -> None:
    calc = calculator(holidays=(date(2026, 9, 7), date(2026, 9, 8)))
    with pytest.raises(CalendarCalculationError, match="scan_limit"):
        calc.shift_workdays(date(2026, 9, 4), 1, scan_limit=4)


def test_skipped_local_date_does_not_get_an_invented_utc_boundary() -> None:
    with pytest.raises(CalendarCalculationError, match="date_nonexistent"):
        calculator("Pacific/Apia").day(date(2011, 12, 30))


@pytest.mark.parametrize(
    "zone,day,start,end",
    [
        (
            "America/Havana",
            date(2020, 11, 1),
            datetime(2020, 11, 1, 4, tzinfo=UTC),
            datetime(2020, 11, 2, 5, tzinfo=UTC),
        ),
        (
            "America/Sao_Paulo",
            date(2018, 11, 4),
            datetime(2018, 11, 4, 3, tzinfo=UTC),
            datetime(2018, 11, 5, 2, tzinfo=UTC),
        ),
        (
            "Pacific/Apia",
            date(2011, 12, 29),
            datetime(2011, 12, 29, 10, tzinfo=UTC),
            datetime(2011, 12, 30, 10, tzinfo=UTC),
        ),
        (
            "Australia/Lord_Howe",
            date(2026, 10, 4),
            datetime(2026, 10, 3, 13, 30, tzinfo=UTC),
            datetime(2026, 10, 4, 13, tzinfo=UTC),
        ),
    ],
)
def test_civil_day_boundaries_follow_real_transition_not_midnight_fold(
    zone: str, day: date, start: datetime, end: datetime
) -> None:
    result = calculator(zone, weekdays=tuple(range(7))).day(day)
    assert (result.start_utc, result.end_utc) == (start, end)
    assert result.nominal_hours == Decimal("7.5")
    # Independent UTC -> local membership check, including both edge instants.
    actual_zone = ZoneInfo(zone)
    assert (start - timedelta(microseconds=1)).astimezone(actual_zone).date() != day
    assert end.astimezone(actual_zone).date() != day
    assert (end - timedelta(microseconds=1)).astimezone(actual_zone).date() == day
    instant = start
    while instant < end:
        assert instant.astimezone(actual_zone).date() == day
        instant += timedelta(minutes=1)


def test_skipped_date_is_reported_without_nominal_capacity_or_workday() -> None:
    calc = calculator("Pacific/Apia", weekdays=tuple(range(7)))
    result = calc.period(date(2011, 12, 29), date(2012, 1, 1))
    assert result.working_dates == (date(2011, 12, 29), date(2011, 12, 31))
    assert result.skipped_dates == (date(2011, 12, 30),)
    assert result.nominal_hours == Decimal("15.0")
    assert calc.shift_workdays(date(2011, 12, 29), 1) == date(2011, 12, 31)
    assert calc.shift_workdays(date(2011, 12, 31), -1) == date(2011, 12, 29)
    with pytest.raises(CalendarCalculationError, match="date_nonexistent"):
        calc.shift_workdays(date(2011, 12, 30), 0)


def test_date_that_leaves_and_reenters_cannot_silently_include_another_date() -> None:
    # The clock crossed midnight, then moved back into the previous date.
    # A single [start,end) would falsely include part of that previous date.
    calc = calculator("America/Goose_Bay")
    with pytest.raises(CalendarCalculationError, match="noncontiguous_date"):
        calc.day(date(1988, 10, 30))
    with pytest.raises(CalendarCalculationError, match="noncontiguous_date"):
        calc.period(date(1988, 10, 29), date(1988, 10, 31))


def test_extreme_date_offset_overflow_uses_the_domain_error() -> None:
    with pytest.raises(CalendarCalculationError, match="date_out_of_range"):
        calculator().local_date(datetime.min.replace(tzinfo=UTC))
    with pytest.raises(CalendarCalculationError, match="date_out_of_range"):
        calculator("Asia/Shanghai").day(date.min)


def test_time_window_compares_instants_across_repeated_hour() -> None:
    zone = ZoneInfo("America/Los_Angeles")
    # 08:45Z -> 09:15Z is chronological even though wall clocks say 1:45 -> 1:15.
    first = datetime(2026, 11, 1, 1, 45, tzinfo=zone, fold=0)
    second = datetime(2026, 11, 1, 1, 15, tzinfo=zone, fold=1)
    window = TimeWindow(start=first, end=second)
    assert window.start == first and window.end == second
    with pytest.raises(ValidationError, match="time_window_reversed"):
        TimeWindow(start=second, end=first)


def test_identical_instants_in_different_zones_remain_a_valid_zero_window() -> None:
    instant = datetime(2026, 9, 10, tzinfo=UTC)
    local = instant.astimezone(ZoneInfo("Asia/Shanghai"))
    assert TimeWindow(start=instant, end=local).end == local


def test_version_and_timezone_rules_are_part_of_calculation_evidence() -> None:
    calc = calculator()
    before = calc.calendar.model_dump_json()
    result = calc.day(date(2026, 9, 10))
    same = WorkCalendarCalculator(calc.calendar).evidence
    assert result.evidence == same
    changed = WorkCalendarCalculator(calc.calendar.model_copy(update={"version": 2}))
    assert changed.evidence.calendar_digest != same.calendar_digest
    assert len(same.timezone_rules_digest) == 64
    assert changed.evidence.timezone_rules_digest == same.timezone_rules_digest
    assert calc.calendar.model_dump_json() == before


@pytest.mark.parametrize("offset", [True, 1.5])
def test_bool_and_fractional_days_are_not_coerced(offset: object) -> None:
    with pytest.raises(CalendarCalculationError, match="integer_workdays"):
        calculator().shift_workdays(date(2026, 9, 1), offset)  # type: ignore[arg-type]


def test_invalid_date_ranges_and_scan_limits_are_bounded() -> None:
    calc = calculator()
    with pytest.raises(CalendarCalculationError, match="period_reversed"):
        calc.period(date(2026, 9, 2), date(2026, 9, 1))
    with pytest.raises(CalendarCalculationError, match="scan_limit"):
        calc.period(date(2026, 1, 1), date(2026, 1, 1) + timedelta(days=MAX_SCAN_DAYS + 1))
    with pytest.raises(CalendarCalculationError, match="scan_limit_invalid"):
        calc.shift_workdays(date(2026, 9, 1), 1, scan_limit=0)
    with pytest.raises(CalendarCalculationError, match="date_out_of_range"):
        calc.shift_workdays(date.max, 1)
    with pytest.raises(CalendarCalculationError, match="date_required"):
        calc.day(datetime(2026, 9, 1))
