"""D221: what a calendar version accepts and the working-day arithmetic. No database."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from pdos_next.domain.projects.planning.engine.calendar import WorkingTime
from pdos_next.domain.projects.planning.engine.dto import WorkInterval
from pdos_next.domain.work_calendar import rules
from pdos_next.domain.work_calendar.rules import (
    Calendar,
    CalendarError,
    Definition,
    add_working_days,
    is_working_day,
    working_days_between,
)

SH = ZoneInfo("Asia/Shanghai")


def local(*args):
    return datetime(*args, tzinfo=SH)


def entry(kind, start, end=None, label="合成"):
    return {"kind": kind, "start": start, "end": end or start, "label": label}


def calendar(*entries, weekdays=(1, 2, 3, 4, 5), kind="factory", name="factory", revision=3):
    return Calendar(
        calendar_id="c-1",
        kind=kind,
        name=name,
        revision=revision,
        definition=Definition(working_weekdays=weekdays, entries=entries),
    )


# 2027 春节 (synthetic dates): the factory stops four weeks; the statutory holiday
# and a makeup Saturday fall inside the stop, a makeup Sunday after it.
SPRING_2027 = calendar(
    entry("shutdown", "2027-01-30", "2027-02-21", "2027 春节停线"),
    entry("holiday", "2027-02-05", "2027-02-13", "春节"),
    entry("makeup_workday", "2027-02-20", label="春节调休"),
    entry("makeup_workday", "2027-02-28", label="春节调休"),
)


@pytest.mark.parametrize(
    "start,days,expected",
    [
        (local(2026, 11, 13, 15), 1, local(2026, 11, 16, 15)),  # Friday 15:00 → Monday
        (local(2026, 11, 14, 10), 1, local(2026, 11, 17, 0)),  # Saturday → Tuesday 00:00
        (local(2026, 11, 14, 10), 0, local(2026, 11, 16, 0)),  # Saturday → Monday 00:00
        (local(2026, 11, 10, 9, 30), 0, local(2026, 11, 10, 9, 30)),
        (local(2026, 11, 10, 9, 30), 5, local(2026, 11, 17, 9, 30)),
    ],
)
def test_without_a_calendar_the_monday_to_friday_estimate_is_unchanged(start, days, expected):
    assert add_working_days(None, start, days) == expected.astimezone(UTC)
    assert rules.basis(None) == {
        "basis": "weekdays_estimate",
        "basis_label": "按周一至周五估算，未扣节假日与停线",
        "timezone": "Asia/Shanghai",
    }


def test_spring_festival_shutdown_is_skipped():
    assert add_working_days(SPRING_2027, local(2027, 1, 29, 10), 1) == local(2027, 2, 22, 10)
    assert add_working_days(SPRING_2027, local(2027, 2, 1, 10), 0) == local(2027, 2, 22, 0)
    # Five working days from the last day before the stop: 22–26 Feb.
    assert add_working_days(SPRING_2027, local(2027, 1, 29, 8), 5) == local(2027, 2, 26, 8)
    # The makeup Sunday after the stop is worked; the one inside it is not.
    assert is_working_day(SPRING_2027, date(2027, 2, 28))
    assert not is_working_day(SPRING_2027, date(2027, 2, 20))
    assert add_working_days(SPRING_2027, local(2027, 2, 26, 17), 1) == local(2027, 2, 28, 17)
    assert working_days_between(SPRING_2027, date(2027, 1, 25), date(2027, 3, 1)) == 5 + 5 + 1
    assert working_days_between(SPRING_2027, date(2027, 3, 1), date(2027, 1, 25)) == -11


def test_holiday_on_a_weekday_and_makeup_on_a_weekend():
    national = calendar(
        entry("holiday", "2026-10-01", "2026-10-07", "国庆"),
        entry("makeup_workday", "2026-10-10", label="国庆调休"),
    )
    assert not is_working_day(national, date(2026, 10, 1))
    assert is_working_day(national, date(2026, 10, 10))
    assert add_working_days(national, local(2026, 9, 30, 12), 1) == local(2026, 10, 8, 12)
    assert add_working_days(national, local(2026, 10, 9, 12), 1) == local(2026, 10, 10, 12)


def test_supplier_calendar_is_its_own_and_says_so():
    supplier = calendar(
        entry("shutdown", "2027-01-20", "2027-02-28", "供应商春节停产"),
        kind="supplier",
        name="合成电芯厂",
    )
    assert not is_working_day(supplier, date(2027, 2, 22))
    assert is_working_day(SPRING_2027, date(2027, 2, 22))
    assert rules.basis(supplier) == {
        "basis": "tenant_calendar",
        "basis_label": "按供应商日历（合成电芯厂）第 3 版计算",
        "timezone": "Asia/Shanghai",
        "calendar_id": "c-1",
        "calendar_name": "供应商日历（合成电芯厂）",
        "calendar_revision": 3,
    }


def test_six_day_week_and_another_time_zone():
    berlin = Calendar(
        calendar_id="c-2",
        kind="factory",
        name="factory",
        revision=1,
        definition=Definition(timezone="Europe/Berlin", working_weekdays=(6, 1, 2, 3, 4, 5)),
    )
    assert berlin.definition.working_weekdays == (1, 2, 3, 4, 5, 6)
    saturday = datetime(2026, 11, 14, 9, tzinfo=ZoneInfo("Europe/Berlin"))
    assert add_working_days(berlin, saturday, 1) == saturday + timedelta(days=2)


@pytest.mark.parametrize(
    "definition,message",
    [
        ({"entries": [entry("makeup_workday", "2026-11-10")]}, "本来就是工作日"),
        (
            {
                "entries": [
                    entry("holiday", "2026-11-14", "2026-11-15"),
                    entry("makeup_workday", "2026-11-15"),
                ]
            },
            "同时登记了法定假日和调休上班",
        ),
        ({"entries": [entry("shutdown", "2026-11-15", "2026-11-14")]}, "结束日期"),
        ({"entries": [entry("shutdown", "2026-01-01", "2027-01-02")]}, "366"),
        ({"entries": [entry("holiday", "2026-11-11"), entry("holiday", "2026-11-11")]}, "重复"),
        ({"entries": [entry("holiday", "2026-11-11", label="   ")]}, "说明"),
        ({"working_weekdays": []}, "至少一天"),
        ({"working_weekdays": [0, 1]}, "至少一天"),
        ({"working_weekdays": [1, 1]}, "重复"),
        ({"timezone": "Mars/Base"}, "时区"),
        ({"entries": [entry("closure", "2026-11-11")]}, "kind"),
    ],
)
def test_invalid_versions_are_refused(definition, message):
    with pytest.raises(ValidationError, match=message):
        Definition.model_validate(definition)


def test_entries_are_kept_in_date_order_with_trimmed_labels():
    value = Definition.model_validate(
        {
            "entries": [
                entry("holiday", "2026-12-31", label="  元旦  "),
                entry("shutdown", "2026-12-01", "2026-12-03", "检修"),
            ]
        }
    )
    assert [(e.start.isoformat(), e.label) for e in value.entries] == [
        ("2026-12-01", "检修"),
        ("2026-12-31", "元旦"),
    ]


@pytest.mark.parametrize("days", [-1, 367, 1.0, True])
def test_day_count_is_bounded_like_the_estimate(days):
    with pytest.raises(CalendarError):
        add_working_days(None, local(2026, 11, 10, 9), days)


def test_naive_instant_is_refused():
    with pytest.raises(CalendarError):
        add_working_days(None, datetime(2026, 11, 10, 9), 1)


def _sundays_only(*entries):
    return Calendar(
        calendar_id="c",
        kind="factory",
        name="factory",
        revision=1,
        definition=Definition(working_weekdays=(7,), entries=entries),
    )


def test_calendar_without_any_working_day_ahead_fails_plainly():
    stopped = _sundays_only(entry("shutdown", "2026-11-01", "2027-10-31", "停产"))
    assert add_working_days(stopped, local(2026, 11, 2, 9), 0) == local(2027, 11, 7, 0)
    blocked = _sundays_only(
        *(entry("shutdown", f"{2026 + y}-11-01", f"{2027 + y}-10-31", "停产") for y in range(11))
    )
    with pytest.raises(CalendarError, match="十年"):
        add_working_days(blocked, local(2026, 11, 2, 9), 1)


def test_planning_snapshot_deducts_the_stop_in_minute_arithmetic():
    shift = (WorkInterval(start_minute=8 * 60, end_minute=17 * 60),)
    snapshot = rules.planning_snapshot(SPRING_2027, shift, date(2027, 1, 25), date(2027, 3, 5))
    assert snapshot.calendar_id == "c-1" and snapshot.version == "3"
    closed = {item.day for item in snapshot.exceptions if not item.intervals}
    opened = {item.day for item in snapshot.exceptions if item.intervals}
    assert date(2027, 2, 1) in closed and date(2027, 2, 19) in closed
    assert opened == {date(2027, 2, 28)}
    clock = WorkingTime(snapshot)
    # One nine-hour shift after Friday 29 January 17:00 ends on Monday 22 February.
    finish = clock.advance(local(2027, 1, 29, 17), 9 * 60)
    assert finish == local(2027, 2, 22, 17).astimezone(UTC)


def test_planning_snapshot_without_a_calendar_is_the_plain_week():
    shift = (WorkInterval(start_minute=0, end_minute=1440),)
    snapshot = rules.planning_snapshot(None, shift, date(2027, 2, 1), date(2027, 2, 28))
    assert snapshot.exceptions == () and len(snapshot.weekly) == 5
    assert snapshot.calendar_id == "weekdays_estimate"
