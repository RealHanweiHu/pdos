"""Monday-to-Friday estimate used by follow-up rules until the tenant calendar (P41-10)."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from pdos_next.domain.projects.work import business_days as days

SH = timezone(timedelta(hours=8))


def at(y, m, d, h=0, minute=0):
    return datetime(y, m, d, h, minute, tzinfo=SH)


@pytest.mark.parametrize(
    ("start", "count", "expected"),
    [
        (at(2026, 11, 9, 10), 1, at(2026, 11, 10, 10)),  # Monday -> Tuesday
        (at(2026, 11, 12, 15), 1, at(2026, 11, 13, 15)),  # Thursday -> Friday
        (at(2026, 11, 13, 15), 1, at(2026, 11, 16, 15)),  # Friday -> Monday
        (at(2026, 11, 14, 10), 1, at(2026, 11, 17, 0)),  # Saturday: clock starts Monday 00:00
        (at(2026, 11, 15, 23, 59), 1, at(2026, 11, 17, 0)),  # Sunday too
        (at(2026, 11, 13, 0), 1, at(2026, 11, 16, 0)),  # Friday midnight -> Monday midnight
        (at(2026, 11, 9, 10), 5, at(2026, 11, 16, 10)),  # one working week
        (at(2026, 11, 9, 10), 0, at(2026, 11, 9, 10)),
        (at(2026, 11, 14, 10), 0, at(2026, 11, 16, 0)),  # zero days still leaves the weekend
    ],
)
def test_weekday_estimate(start, count, expected):
    result = days.add_weekdays(start, count, "Asia/Shanghai")
    assert result == expected and result.tzinfo is UTC


def test_zone_decides_the_local_day():
    # Friday 20:00 UTC is already Saturday 04:00 in Shanghai.
    friday_utc = datetime(2026, 11, 13, 20, tzinfo=UTC)
    assert days.add_weekdays(friday_utc, 1, "UTC") == datetime(2026, 11, 16, 20, tzinfo=UTC)
    assert days.add_weekdays(friday_utc, 1, "Asia/Shanghai") == at(2026, 11, 17, 0)


def test_at_least_one_full_day_passes_for_one_working_day():
    start = datetime(2026, 11, 2, tzinfo=UTC)
    for hour in range(0, 24 * 14, 5):
        point = start + timedelta(hours=hour)
        assert days.add_weekdays(point, 1, "Asia/Shanghai") - point >= timedelta(days=1)
        assert not days.is_past(point, 1, point + timedelta(hours=23), "Asia/Shanghai")


def test_every_result_says_it_is_an_estimate():
    assert days.basis() == {
        "basis": "weekdays_estimate",
        "basis_label": "按周一至周五估算，未扣节假日与停线",
        "timezone": "Asia/Shanghai",
    }


@pytest.mark.parametrize(
    "bad",
    [
        (datetime(2026, 11, 9), 1, "Asia/Shanghai"),  # naive
        (at(2026, 11, 9), -1, "Asia/Shanghai"),
        (at(2026, 11, 9), 367, "Asia/Shanghai"),
        (at(2026, 11, 9), 1.0, "Asia/Shanghai"),
        (at(2026, 11, 9), 1, "Mars/Base"),
    ],
)
def test_invalid_inputs_are_refused(bad):
    with pytest.raises(ValueError):
        days.add_weekdays(*bad)
