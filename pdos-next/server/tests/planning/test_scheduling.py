from copy import deepcopy
from datetime import UTC, date, datetime

import pytest

from pdos_next.domain.planning.calendar import ScheduleError, WorkingCalendar
from pdos_next.domain.planning.scheduling import schedule
from pdos_next.schemas.planning import Calendar, ScheduleInput


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def calendar(**changes):
    return {
        "key": "synthetic-site",
        "version": "synthetic-calendar@1",
        "timezone": "UTC",
        "working_weekdays": [0, 1, 2, 3, 4],
        "intervals": [{"start_minute": 540, "end_minute": 1020}],
        "holidays": [],
        **changes,
    }


def task(key, minimum=60, maximum=60, **changes):
    return {
        "key": key,
        "title": f"Synthetic {key}",
        "discipline": "engineering",
        "depends_on": [],
        "duration_min_minutes": minimum,
        "duration_max_minutes": maximum,
        "estimate_source": "Synthetic human estimate, no real commitment",
        **changes,
    }


def request(*tasks, start="2026-10-05T09:00:00Z", definition=None):
    return {"start": start, "calendar": definition or calendar(), "tasks": list(tasks)}


def index(result):
    return {item.key: item for item in result.tasks}


def test_parallel_fs_ranges_cross_weekend_without_serializing_independent_work():
    source = request(
        task("quality", 60, 120, discipline="quality", depends_on=["engineering"]),
        task("npi", 30, 30, discipline="npi"),
        task("engineering", 60, 180),
        start="2026-10-02T16:00:00Z",
    )
    original = deepcopy(source)
    result = schedule(source)
    items = index(result)
    assert items["engineering"].earliest_finish == instant("2026-10-02T17:00:00Z")
    assert items["engineering"].latest_finish == instant("2026-10-05T11:00:00Z")
    assert items["quality"].earliest_start == instant("2026-10-05T09:00:00Z")
    assert items["quality"].earliest_finish == instant("2026-10-05T10:00:00Z")
    assert items["quality"].latest_start == instant("2026-10-05T11:00:00Z")
    assert items["quality"].latest_finish == instant("2026-10-05T13:00:00Z")
    assert items["npi"].earliest_start == instant("2026-10-02T16:00:00Z")
    assert items["npi"].latest_finish == instant("2026-10-02T16:30:00Z")
    assert result.earliest_finish == items["quality"].earliest_finish
    assert result.latest_finish == items["quality"].latest_finish
    assert source == original
    assert result.calendar_ref.version == "synthetic-calendar@1"
    assert all(item.earliest_start.tzinfo is UTC for item in result.tasks)
    reversed_source = {**source, "tasks": list(reversed(source["tasks"]))}
    assert schedule(reversed_source).model_dump(mode="json") == result.model_dump(mode="json")


def test_lunch_break_holiday_and_shift_boundary_are_real_constraints():
    definition = calendar(
        intervals=[
            {"start_minute": 540, "end_minute": 720},
            {"start_minute": 780, "end_minute": 1020},
        ],
        holidays=["2026-10-05"],
    )
    result = schedule(
        request(task("npi", 150, 150), start="2026-10-02T16:00:00Z", definition=definition)
    )
    item = result.tasks[0]
    assert item.earliest_finish == instant("2026-10-06T10:30:00Z")
    lunch = schedule(
        request(task("engineering", 120, 120), start="2026-10-06T11:00:00Z", definition=definition)
    )
    assert lunch.tasks[0].earliest_finish == instant("2026-10-06T14:00:00Z")


def test_unknown_duration_propagates_without_zero_or_fake_completion():
    result = schedule(
        request(
            task("research", None, None, estimate_source=None),
            task("engineering", depends_on=["research"]),
            task("quality", depends_on=["engineering"]),
            task("npi", 15, 15),
        )
    )
    items = index(result)
    assert items["research"].earliest_start == instant("2026-10-05T09:00:00Z")
    assert items["research"].earliest_finish is None and items["research"].latest_finish is None
    assert items["research"].duration_min_minutes is None
    for key in ("engineering", "quality"):
        assert items[key].earliest_start is None and items[key].latest_start is None
        assert items[key].earliest_finish is None and items[key].latest_finish is None
        assert "DEPENDENCY_MIN_UNKNOWN" in items[key].unknown_reasons
        assert "DEPENDENCY_MAX_UNKNOWN" in items[key].unknown_reasons
    assert items["engineering"].blocked_by == ("research",)
    assert items["quality"].blocked_by == ("engineering",)
    assert items["npi"].earliest_finish == instant("2026-10-05T09:15:00Z")
    assert result.earliest_finish is None and result.latest_finish is None


@pytest.mark.parametrize(
    ("minimum", "maximum", "unknown_side"), [(60, None, "latest"), (None, 60, "earliest")]
)
def test_partial_estimate_keeps_only_the_known_prediction_bound(minimum, maximum, unknown_side):
    result = schedule(
        request(
            task("engineering", minimum, maximum),
            task("quality", 30, 30, depends_on=["engineering"]),
        )
    )
    items = index(result)
    assert getattr(items["engineering"], f"{unknown_side}_finish") is None
    assert getattr(items["quality"], f"{unknown_side}_start") is None
    assert getattr(items["quality"], f"{unknown_side}_finish") is None
    known_side = "earliest" if unknown_side == "latest" else "latest"
    assert getattr(items["quality"], f"{known_side}_finish") == instant("2026-10-05T10:30:00Z")
    assert items["quality"].blocked_by == ("engineering",)


def test_zero_duration_milestone_does_not_reserve_a_shift():
    start = "2026-10-04T00:00:00Z"
    items = index(
        schedule(request(task("decision", 0, 0), task("npi", depends_on=["decision"]), start=start))
    )
    assert items["decision"].earliest_start == items["decision"].latest_finish == instant(start)
    assert items["npi"].earliest_start == instant("2026-10-05T09:00:00Z")
    work = schedule(request(task("range", 0, 60), start=start)).tasks[0]
    assert work.earliest_start == instant("2026-10-05T09:00:00Z")


def test_rounding_and_missing_estimate_provenance_are_explicit():
    result = schedule(
        request(task("engineering", 1, 1, estimate_source=None), start="2026-10-05T09:00:01Z")
    )
    assert result.input_start == instant("2026-10-05T09:00:01Z")
    assert result.tasks[0].earliest_start == instant("2026-10-05T09:01:00Z")
    assert result.tasks[0].earliest_finish == instant("2026-10-05T09:02:00Z")
    assert result.warnings == ("START_ROUNDED_UP_TO_MINUTE", "ESTIMATE_SOURCE_UNSPECIFIED")


def test_iana_local_working_hours_return_utc_instants_and_version():
    result = schedule(
        request(
            task("engineering"),
            start="2026-10-05T01:00:00Z",
            definition=calendar(timezone="Asia/Shanghai"),
        )
    )
    assert result.tasks[0].earliest_start == instant("2026-10-05T01:00:00Z")
    assert result.tasks[0].earliest_finish == instant("2026-10-05T02:00:00Z")
    assert result.tasks[0].calendar_ref.timezone == "Asia/Shanghai"
    assert len(result.calendar_ref.timezone_rules_sha256) == 64


def test_pinned_timezone_rules_cannot_be_silently_replaced():
    initial = schedule(request(task("engineering")))
    pinned = calendar(timezone_rules_sha256=initial.calendar_ref.timezone_rules_sha256)
    assert schedule(request(task("engineering"), definition=pinned)).tasks == initial.tasks
    with pytest.raises(ScheduleError) as error:
        schedule(request(task("engineering"), definition=calendar(timezone_rules_sha256="0" * 64)))
    assert error.value.code == "TIMEZONE_RULES_CHANGED"


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"start": "2026-10-05T09:00:00"}, "INVALID_START"),
        ({"start": "2026-10-05T09:00:00+08:00"}, "INVALID_START"),
        ({"calendar": calendar(timezone="Synthetic/NoSuchTimezone")}, "INVALID_TIMEZONE"),
        ({"calendar": calendar(working_weekdays=[True])}, "INVALID_CALENDAR"),
        ({"calendar": calendar(working_weekdays=[0, 0])}, "INVALID_CALENDAR"),
        (
            {
                "calendar": calendar(
                    intervals=[
                        {"start_minute": 540, "end_minute": 720},
                        {"start_minute": 600, "end_minute": 800},
                    ]
                )
            },
            "INVALID_CALENDAR",
        ),
        ({"tasks": [task("engineering", -1, 60)]}, "INVALID_DURATION"),
        ({"tasks": [task("engineering", 120, 60)]}, "INVALID_DURATION"),
        ({"tasks": [task("engineering", True, 60)]}, "INVALID_DURATION"),
        ({"tasks": [task("engineering", 1.5, 60)]}, "INVALID_DURATION"),
        ({"tasks": [task("engineering", depends_on=["absent"])]}, "MISSING_DEPENDENCY"),
        ({"tasks": [task("engineering"), task("engineering")]}, "DUPLICATE_TASK"),
        (
            {
                "tasks": [
                    task("engineering", depends_on=["quality"]),
                    task("quality", depends_on=["engineering"]),
                ]
            },
            "DEPENDENCY_CYCLE",
        ),
        ({"tasks": [task("engineering", depends_on=["engineering"])]}, "DEPENDENCY_CYCLE"),
    ],
)
def test_invalid_graph_calendar_and_duration_fail_with_stable_codes(changes, code):
    with pytest.raises(ScheduleError) as error:
        schedule({**request(task("engineering")), **changes})
    assert error.value.code == code


@pytest.mark.parametrize(
    ("start", "interval_start", "code"),
    [
        ("2026-03-08T05:00:00Z", 150, "NONEXISTENT_LOCAL_TIME"),
        ("2026-11-01T04:00:00Z", 90, "AMBIGUOUS_LOCAL_TIME"),
    ],
)
def test_dst_undefined_local_endpoints_are_rejected_without_adjustment(start, interval_start, code):
    definition = calendar(
        timezone="America/New_York",
        working_weekdays=[6],
        intervals=[{"start_minute": interval_start, "end_minute": 240}],
    )
    with pytest.raises(ScheduleError) as error:
        schedule(request(task("engineering"), start=start, definition=definition))
    assert error.value.code == code


@pytest.mark.parametrize(
    ("start", "minutes", "finish"),
    [
        ("2026-03-08T05:00:00Z", 180, "2026-03-08T08:00:00Z"),
        ("2026-11-01T04:00:00Z", 300, "2026-11-01T09:00:00Z"),
    ],
)
def test_valid_dst_spans_count_actual_elapsed_minutes(start, minutes, finish):
    definition = calendar(
        timezone="America/New_York",
        working_weekdays=[6],
        intervals=[{"start_minute": 0, "end_minute": 240}],
    )
    result = schedule(
        request(task("engineering", minutes, minutes), start=start, definition=definition)
    )
    assert result.tasks[0].earliest_finish == instant(finish)
    assert (
        result.tasks[0].earliest_finish - result.tasks[0].earliest_start
    ).total_seconds() == minutes * 60


def test_holiday_excludes_its_dst_gap_and_calendar_no_work_horizon_is_explicit():
    definition = calendar(
        timezone="America/New_York",
        working_weekdays=[6],
        holidays=["2026-03-08"],
        intervals=[{"start_minute": 150, "end_minute": 240}],
    )
    result = schedule(
        request(task("engineering", 10, 10), start="2026-03-08T05:00:00Z", definition=definition)
    )
    assert result.tasks[0].earliest_start == instant("2026-03-15T06:30:00Z")
    engine = WorkingCalendar(
        Calendar(
            **calendar(working_weekdays=[0], holidays=[date(2026, 10, 5), date(2026, 10, 12)])
        ),
        horizon_days=7,
    )
    with pytest.raises(ScheduleError) as error:
        engine.snap(instant("2026-10-05T09:00:00Z"))
    assert error.value.code == "HORIZON_EXCEEDED"


def test_copied_dto_cannot_bypass_aware_start_or_duration_validation():
    source = ScheduleInput.model_validate(request(task("engineering")))
    with pytest.raises(ScheduleError) as error:
        schedule(source.model_copy(update={"start": datetime(2026, 10, 5, 9)}))
    assert error.value.code == "INVALID_START"
