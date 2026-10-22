"""Pure planning invariants; no shared fixtures, persistence or model transport."""

from datetime import UTC, datetime
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from pdos_next.engines.planning import calculate_forecast
from pdos_next.engines.planning.dto import (
    CalendarSnapshot,
    Dependency,
    DurationEstimate,
    ExternalWait,
    ForecastInput,
    NodeSnapshot,
    Occupancy,
    Reference,
    ResourceRequirement,
    ResourceSnapshot,
    TimeRecord,
    TimeWindow,
    WeekdaySchedule,
    WorkInterval,
)

REF = Reference(source_id="synthetic-input", version="v1")
NOW = datetime(2026, 10, 2, 9, tzinfo=UTC)
CALENDAR = CalendarSnapshot(
    calendar_id="factory",
    version="v1",
    timezone="UTC",
    weekly=tuple(
        WeekdaySchedule(weekday=day, intervals=(WorkInterval(start_minute=540, end_minute=1020),))
        for day in range(5)
    ),
)


def instant(day=2, hour=9, minute=0, second=0):
    return datetime(2026, 10, day, hour, minute, second, tzinfo=UTC)


def duration(minimum=60, maximum="same", measure="total"):
    return DurationEstimate(
        minimum=minimum,
        maximum=minimum if maximum == "same" else maximum,
        measure=measure,
        source=REF,
    )


def node(key, work=60, waiting=0, **kwargs):
    return NodeSnapshot(
        node_id=key,
        calendar_id="factory",
        work=work if isinstance(work, DurationEstimate) else duration(work),
        waiting=waiting if isinstance(waiting, DurationEstimate) else duration(waiting),
        allocation_basis="Explicit single divisible-work allocation assumption",
        **kwargs,
    )


def edge(left, right, relation="FS", lag=0, clock="working"):
    return Dependency(
        predecessor_id=left,
        successor_id=right,
        relation=relation,
        lag_minutes=lag,
        lag_clock=clock,
        source=REF,
    )


def request(*nodes, dependencies=(), **kwargs):
    return ForecastInput(
        snapshot_id="synthetic-plan",
        version="v1",
        as_of=NOW,
        calendars=(CALENDAR,),
        nodes=nodes,
        dependencies=dependencies,
        **kwargs,
    )


def rows(result):
    return {item.node_id: item for item in result.nodes}


def codes(result):
    return {issue.code for issue in result.issues}


def fact(start=None, finish=None, kind="Actual"):
    return TimeRecord(
        time_kind=kind,
        version="v1",
        original_timezone="UTC",
        source=REF,
        start=start,
        finish=finish,
    )


def wait(*, ready=None, latest="same", target="start", blocking=True):
    return ExternalWait(
        wait_id="external",
        version="v1",
        source=REF,
        original_timezone="UTC",
        target=target,
        blocking=blocking,
        ready=TimeWindow(earliest=ready, latest=ready if latest == "same" else latest),
    )


def resource(*occupancies, capacity=1):
    return ResourceSnapshot(
        resource_id="bench",
        version="v1",
        calendar_id="factory",
        capacity=capacity,
        source=REF,
        occupancies=occupancies,
    )


def occupancy(start, finish, units=1):
    return Occupancy(occupancy_id="existing", start=start, finish=finish, units=units, source=REF)


NEED = (ResourceRequirement(resource_id="bench", units=1),)


def test_fs_schedule_and_float_are_based_on_current_finish_not_commitment():
    result = calculate_forecast(
        request(
            node("A", 120),
            node("B", 60),
            node("C", 60),
            dependencies=(edge("A", "B"),),
        )
    )
    by_id = rows(result)
    assert result.status == "complete"
    assert result.project_finish.exact and result.project_finish.latest == instant(hour=12)
    assert by_id["B"].start.earliest == instant(hour=11)
    assert by_id["A"].critical and by_id["B"].critical
    assert by_id["C"].float_minutes == by_id["C"].working_float_minutes == 120
    assert by_id["C"].latest_start == instant(hour=11)
    assert result.capacity_status == "not_requested"
    assert result.float_status == "calculated"


@pytest.mark.parametrize("field", ["work", "waiting"])
def test_unknown_quantity_propagates_only_to_finish_dependencies(field):
    result = calculate_forecast(
        request(
            node("A", **{field: duration(None)}),
            node("B"),
            node("C"),
            node("D"),
            dependencies=(edge("A", "B"), edge("A", "D", "SS")),
        )
    )
    by_id = rows(result)
    assert by_id["A"].start.exact
    assert by_id["A"].finish.latest is None
    assert by_id["B"].start.earliest is None and by_id["B"].finish.latest is None
    assert by_id["C"].finish.latest == by_id["D"].finish.latest == instant(hour=10)
    assert f"{field}_duration_unknown" in codes(result)
    assert result.project_finish.latest is None and result.float_status == "not_calculated"


def test_finite_fs_estimate_ranges_propagate_bounds_without_point_dates():
    result = calculate_forecast(
        request(
            node("A", duration(60, 120)),
            node("B", duration(30, 90)),
            dependencies=(edge("A", "B"),),
        )
    )
    by_id = rows(result)
    assert result.status == "complete" and by_id["B"].status == "range"
    assert by_id["B"].start == TimeWindow(earliest=instant(hour=10), latest=instant(hour=11))
    assert by_id["B"].finish == TimeWindow(
        earliest=instant(hour=10, minute=30), latest=instant(hour=12, minute=30)
    )
    assert result.float_status == "not_calculated" and by_id["A"].critical is None


def test_open_upper_range_keeps_a_lower_bound_but_never_claims_a_deadline():
    result = calculate_forecast(
        request(
            node("A", duration(60, None)),
            node("B"),
            dependencies=(edge("A", "B"),),
        )
    )
    assert rows(result)["B"].finish.earliest == instant(hour=11)
    assert rows(result)["B"].finish.latest is None
    assert result.status == "partial" and result.project_finish.latest is None


@pytest.mark.parametrize("relation", ["FF", "SF"])
def test_finish_dependency_with_duration_range_returns_a_conservative_envelope(relation):
    result = calculate_forecast(
        request(
            node("A", 480),
            node("B", duration(60, 480)),
            dependencies=(edge("A", "B", relation),),
        )
    )
    assert rows(result)["A"].finish.latest == instant(hour=17)
    assert rows(result)["B"].start.earliest == NOW
    assert rows(result)["B"].finish.latest is not None
    assert "finish_constraint_envelope" in codes(result)
    assert "finish_constraint_range_not_supported" not in codes(result)
    assert result.status == "complete" and result.float_status == "not_calculated"


@pytest.mark.parametrize(
    "relation,start_hour,finish_hour",
    [
        ("FS", 11, 12),
        ("SS", 9, 10),
        ("FF", 10, 11),
        ("SF", 9, 10),
    ],
)
def test_exact_fs_ss_ff_sf_constraints(relation, start_hour, finish_hour):
    result = calculate_forecast(
        request(node("A", 120), node("B", 60), dependencies=(edge("A", "B", relation),))
    )
    assert rows(result)["B"].start.earliest == instant(hour=start_hour)
    assert rows(result)["B"].finish.latest == instant(hour=finish_hour)


@pytest.mark.parametrize(
    "clock,lag,expected",
    [
        ("working", 60, instant(day=5, hour=10)),
        ("elapsed", 60, instant(day=5, hour=9)),
        ("working", -60, instant(hour=16)),
    ],
)
def test_signed_lag_uses_successor_calendar_or_elapsed_utc(clock, lag, expected):
    result = calculate_forecast(
        request(node("A", 480), node("B", 60), dependencies=(edge("A", "B", lag=lag, clock=clock),))
    )
    assert rows(result)["B"].start.earliest == expected


@pytest.mark.parametrize(
    "clock,expected",
    [
        ("elapsed", instant(day=3, hour=17)),
        ("working", instant(day=7, hour=17)),
    ],
)
def test_waiting_clock_is_explicit_and_distinct_from_effort(clock, expected):
    result = calculate_forecast(request(node("A", 480, 1440, waiting_clock=clock)))
    assert rows(result)["A"].finish.latest == expected


def test_known_unknown_and_nonblocking_external_readiness_are_distinct():
    result = calculate_forecast(
        request(
            node("known", external_waits=(wait(ready=instant(day=5)),)),
            node("unknown", external_waits=(wait(),)),
            node("advisory", external_waits=(wait(blocking=False),)),
        )
    )
    by_id = rows(result)
    assert by_id["known"].finish.latest == instant(day=5, hour=10)
    assert by_id["unknown"].start.earliest is None
    assert by_id["advisory"].finish.latest == instant(hour=10)


def test_finite_external_start_range_does_not_claim_exact_readiness():
    result = calculate_forecast(
        request(node("A", external_waits=(wait(ready=instant(hour=10), latest=instant(hour=12)),)))
    )
    assert result.status == "complete"
    assert rows(result)["A"].finish == TimeWindow(
        earliest=instant(hour=11), latest=instant(hour=13)
    )


def test_actual_started_node_requires_explicit_remaining_both_work_and_wait():
    result = calculate_forecast(request(node("A", time_records=(fact(instant(day=1)),))))
    row = rows(result)["A"]
    assert row.start.earliest == instant(day=1)
    assert row.finish.latest is None and "remaining_estimate_required" in codes(result)


def test_remaining_estimate_does_not_recompute_total_from_actual_start():
    snapshot = request(
        node(
            "A",
            duration(60, measure="remaining"),
            duration(0, measure="remaining"),
            time_records=(fact(instant(day=1, second=17)),),
        )
    )
    row = rows(calculate_forecast(snapshot))["A"]
    assert row.start.earliest == instant(day=1, second=17)
    assert row.remaining_work_start.earliest == NOW
    assert row.finish.latest == instant(hour=10)


def test_actual_completed_constraint_conflict_keeps_original_seconds_and_successor_anchor():
    result = calculate_forecast(
        request(
            node("A", 120),
            node(
                "B",
                time_records=(fact(instant(day=1, second=19), instant(day=1, hour=10, second=31)),),
            ),
            node("C"),
            dependencies=(edge("A", "B"), edge("B", "C")),
        )
    )
    by_id = rows(result)
    assert by_id["B"].status == "conflicted"
    assert by_id["B"].finish.latest == instant(day=1, hour=10, second=31)
    assert by_id["C"].finish.latest == instant(hour=10)
    assert "actual_constraint_conflict" in codes(result)


def test_input_four_times_and_resource_snapshot_remain_unchanged_on_repeat():
    records = tuple(
        fact(instant(day=1), instant(day=1, hour=10), kind)
        for kind in ("Baseline", "Forecast", "Commitment", "Actual")
    )
    snapshot = request(node("A", time_records=records))
    before = snapshot.model_dump_json()
    first, second = calculate_forecast(snapshot), calculate_forecast(snapshot)
    assert snapshot.model_dump_json() == before
    assert first.model_dump_json() == second.model_dump_json()
    assert first.time_kind == "Forecast" and first.disposition == "candidate"
    assert first.input_snapshot.nodes[0].time_records == records
    assert len(first.input_sha256) == len(first.candidate_sha256) == 64


def test_input_digest_covers_calendar_intervals_versions_and_not_just_id():
    snapshot = request(node("A"))
    result = calculate_forecast(snapshot)
    shifted = CALENDAR.model_copy(
        update={
            "version": "v2",
            "weekly": tuple(
                WeekdaySchedule(
                    weekday=day, intervals=(WorkInterval(start_minute=600, end_minute=1020),)
                )
                for day in range(5)
            ),
        }
    )
    assert (
        calculate_forecast(snapshot.model_copy(update={"calendars": (shifted,)})).input_sha256
        != result.input_sha256
    )


def test_decimal_environment_does_not_change_candidate():
    snapshot = request(node("A", Decimal("10.001"), parallel_units=Decimal(3), divisible_work=True))
    first = calculate_forecast(snapshot)
    with localcontext() as arithmetic:
        arithmetic.prec = 3
        second = calculate_forecast(snapshot)
    assert first.candidate_sha256 == second.candidate_sha256
    assert first.project_finish.latest == instant(minute=4)


@pytest.mark.parametrize(
    "start,finish,conflict",
    [
        (instant(hour=8), instant(hour=9), False),
        (instant(hour=10), instant(hour=11), False),
        (instant(hour=9, minute=30), instant(hour=10, minute=30), True),
    ],
)
def test_half_open_resource_occupancy_conflicts(start, finish, conflict):
    result = calculate_forecast(
        request(node("A", resources=NEED), resources=(resource(occupancy(start, finish)),))
    )
    assert result.capacity_status == ("conflicted" if conflict else "checked")
    assert ("resource_capacity_conflict" in codes(result)) is conflict
    assert result.float_status == "not_calculated"


def test_resource_check_includes_other_forecast_nodes_without_booking_or_reordering():
    snapshot = request(
        node("A", resources=NEED), node("B", resources=NEED), resources=(resource(),)
    )
    before = snapshot.model_dump_json()
    result = calculate_forecast(snapshot)
    assert result.capacity_status == "conflicted"
    assert result.status == "partial"
    assert rows(result)["A"].start.earliest == rows(result)["B"].start.earliest == NOW
    assert snapshot.model_dump_json() == before


def test_capacity_demand_exceeds_pool_and_unknown_ranges_are_not_certified():
    result = calculate_forecast(
        request(node("A", duration(60, 120), resources=NEED), resources=(resource(capacity="0.5"),))
    )
    assert result.capacity_status == "conflicted"
    assert {"resource_capacity_exceeded", "resource_interval_unknown"} <= codes(result)
    assert calculate_forecast(request(node("A", resources=NEED))).capacity_status == "unknown"


@pytest.mark.parametrize("check_resource", [False, True])
def test_coupled_envelope_is_not_certified_when_minute_rounding_collapses_the_dates(check_resource):
    snapshot = request(
        node(
            "A",
            duration("60.1", "60.9"),
            resources=NEED if check_resource else (),
            external_waits=(wait(ready=instant(hour=12), target="finish"),),
        ),
        resources=(resource(),) if check_resource else (),
    )
    before = snapshot.model_dump_json()
    first, repeated = calculate_forecast(snapshot), calculate_forecast(snapshot)
    row = rows(first)["A"]
    assert row.start.exact and row.finish.exact
    assert "finish_constraint_envelope" in codes(first)
    assert first.float_status == "not_calculated"
    assert first.capacity_status == ("unknown" if check_resource else "not_requested")
    assert first.candidate_sha256 == repeated.candidate_sha256
    assert snapshot.model_dump_json() == before
    assert first.algorithm_version == "planning.minute_forecast.v2"


def test_fixed_duration_keeps_tight_endpoints_for_ranged_finish_readiness():
    result = calculate_forecast(
        request(
            node(
                "A",
                60,
                external_waits=(
                    wait(ready=instant(hour=12), latest=instant(hour=14), target="finish"),
                ),
            )
        )
    )
    row = rows(result)["A"]
    assert row.start == TimeWindow(earliest=instant(hour=11), latest=instant(hour=13))
    assert row.finish == TimeWindow(earliest=instant(hour=12), latest=instant(hour=14))
    assert "finish_constraint_envelope" not in codes(result)


def test_capacity_applies_to_work_only_and_wait_does_not_reserve_a_pool():
    result = calculate_forecast(
        request(
            node("A", 60, 60, resources=NEED),
            resources=(resource(occupancy(instant(hour=10), instant(hour=11))),),
        )
    )
    assert result.capacity_status == "checked"
    assert rows(result)["A"].finish.latest == instant(hour=11)


@pytest.mark.parametrize(
    "case,expected",
    [
        ("cycle", "dependency_cycle"),
        ("self", "dependency_cycle"),
        ("missing", "missing_dependency_node"),
        ("duplicate", "duplicate_node_id"),
        ("calendar", "missing_calendar"),
        ("future_actual", "actual_after_as_of"),
    ],
)
def test_unusable_structure_fails_closed(case, expected):
    a, b = node("A"), node("B")
    nodes, deps = (a, b), ()
    if case == "cycle":
        deps = (edge("A", "B"), edge("B", "A"))
    elif case == "self":
        deps = (edge("A", "A"),)
    elif case == "missing":
        deps = (edge("missing", "B"),)
    elif case == "duplicate":
        nodes = (a, a)
    elif case == "calendar":
        nodes = (a.model_copy(update={"calendar_id": "missing"}),)
    else:
        nodes = (node("A", time_records=(fact(instant(day=3)),)),)
    result = calculate_forecast(request(*nodes, dependencies=deps))
    assert result.status == "invalid" and not result.nodes
    assert result.project_finish.latest is None and expected in codes(result)


def test_exhausted_horizon_is_a_structured_missing_input_not_a_fallback_date():
    result = calculate_forecast(request(node("A", 10000), horizon_days=2))
    assert result.project_finish.latest is None
    assert "calendar_horizon_exhausted" in codes(result)
    elapsed = calculate_forecast(request(node("A", 0, 10000), horizon_days=2))
    assert "forecast_horizon_exhausted" in codes(elapsed)


@pytest.mark.parametrize("minimum,maximum", [(-1, 0), (2, 1), (None, 1), ("NaN", None), (True, 1)])
def test_invalid_durations_are_rejected_before_arithmetic(minimum, maximum):
    with pytest.raises(ValidationError):
        duration(minimum, maximum)


def test_nondivisible_parallel_work_and_zero_capacity_are_rejected():
    with pytest.raises(ValidationError, match="divisible work"):
        node("A", parallel_units=2)
    with pytest.raises(ValidationError):
        resource(capacity=0)
    with pytest.raises(ValidationError):
        TimeWindow(earliest=NOW, latest=instant(hour=8))
    with pytest.raises(ValidationError):
        fact(instant(hour=10), NOW)


@pytest.mark.parametrize("clock", ["working", "elapsed"])
def test_negative_fractional_lag_never_rounds_a_lower_bound_to_an_earlier_minute(clock):
    result = calculate_forecast(
        request(
            node("A", 60), node("B", 0), dependencies=(edge("A", "B", lag="-0.1", clock=clock),)
        )
    )
    assert rows(result)["B"].start.earliest == instant(hour=10)


def test_stable_node_id_prefix_cannot_hide_a_resource_candidate():
    result = calculate_forecast(
        request(
            node("occupancy:A", resources=NEED),
            resources=(resource(occupancy(NOW, instant(hour=10))),),
        )
    )
    assert result.capacity_status == "conflicted"
    assert next(
        item for item in result.issues if item.code == "resource_capacity_conflict"
    ).node_ids == ("occupancy:A",)


def test_failed_calendar_keeps_actual_start_and_does_not_invent_remaining_finish():
    snapshot = request(
        node(
            "A",
            duration(60, measure="remaining"),
            duration(0, measure="remaining"),
            time_records=(fact(instant(day=1, second=31)),),
        ),
        horizon_days=2,
    )
    snapshot = snapshot.model_copy(
        update={"calendars": (CALENDAR.model_copy(update={"weekly": ()}),)}
    )
    row = rows(calculate_forecast(snapshot))["A"]
    assert row.start.earliest == instant(day=1, second=31)
    assert row.finish.latest is None and row.origin == "actual_and_remaining"


@pytest.mark.parametrize("provide_resource", [False, True])
def test_completed_actual_does_not_require_future_capacity_snapshot(provide_resource):
    result = calculate_forecast(
        request(
            node(
                "A", resources=NEED, time_records=(fact(instant(day=1), instant(day=1, hour=10)),)
            ),
            resources=(resource(capacity="0.5"),) if provide_resource else (),
        )
    )
    assert result.capacity_status == "not_requested"
    assert not ({"resource_capacity_exceeded", "resource_snapshot_missing"} & codes(result))
    assert rows(result)["A"].finish.latest == instant(day=1, hour=10)


def test_zero_remaining_work_has_no_capacity_demand():
    result = calculate_forecast(request(node("A", 0, 60, resources=NEED)))
    assert result.capacity_status == "checked"
    assert result.status == "complete"


def test_resource_calendar_is_a_distinct_availability_constraint():
    equipment_calendar = CALENDAR.model_copy(update={"calendar_id": "equipment", "weekly": ()})
    snapshot = request(
        node("A", resources=NEED),
        resources=(resource().model_copy(update={"calendar_id": "equipment"}),),
    )
    snapshot = snapshot.model_copy(update={"calendars": (CALENDAR, equipment_calendar)})
    result = calculate_forecast(snapshot)
    assert result.capacity_status == "conflicted"
    assert "resource_calendar_unavailable" in codes(result)
    missing = snapshot.model_copy(update={"calendars": (CALENDAR,)})
    assert calculate_forecast(missing).capacity_status == "unknown"


def test_capacity_half_open_midnight_does_not_scan_an_unrelated_dst_gap():
    night_calendar = CALENDAR.model_copy(
        update={
            "timezone": "America/Los_Angeles",
            "weekly": (
                WeekdaySchedule(
                    weekday=5, intervals=(WorkInterval(start_minute=1320, end_minute=1440),)
                ),
                WeekdaySchedule(
                    weekday=6, intervals=(WorkInterval(start_minute=120, end_minute=180),)
                ),
            ),
        }
    )
    saturday_night = datetime(2026, 3, 8, 6, tzinfo=UTC)
    snapshot = request(node("A", 120, resources=NEED), resources=(resource(),))
    snapshot = snapshot.model_copy(update={"as_of": saturday_night, "calendars": (night_calendar,)})
    result = calculate_forecast(snapshot)
    assert rows(result)["A"].finish.latest == datetime(2026, 3, 8, 8, tzinfo=UTC)
    assert result.capacity_status == "checked"


def test_cross_site_calendar_constraint_and_timezone_are_preserved():
    shanghai = CALENDAR.model_copy(update={"calendar_id": "shanghai", "timezone": "Asia/Shanghai"})
    b = node("B", 60).model_copy(update={"calendar_id": "shanghai"})
    snapshot = request(node("A", 60), b, dependencies=(edge("A", "B"),))
    snapshot = snapshot.model_copy(update={"calendars": (CALENDAR, shanghai)})
    row = rows(calculate_forecast(snapshot))["B"]
    assert row.start.earliest == datetime(2026, 10, 5, 1, tzinfo=UTC)
    assert row.finish.latest == datetime(2026, 10, 5, 2, tzinfo=UTC)
    assert row.original_timezone == "Asia/Shanghai"


def test_unrelated_calendar_error_keeps_completed_actual_finish():
    a = node("A", time_records=(fact(instant(day=1), instant(day=1, hour=10)),))
    b = node("B", time_records=(fact(instant(day=1, hour=11), instant(day=1, hour=12, second=19)),))
    snapshot = request(a, b, dependencies=(edge("A", "B", lag=60),))
    snapshot = snapshot.model_copy(
        update={"calendars": (CALENDAR.model_copy(update={"weekly": ()}),)}
    )
    result = calculate_forecast(snapshot)
    assert rows(result)["B"].finish.latest == instant(day=1, hour=12, second=19)
    assert rows(result)["B"].origin == "actual_anchor"
    assert "calendar_horizon_exhausted" in codes(result)


def test_datetime_overflow_is_reported_as_unavailable_forecast():
    snapshot = request(node("A"))
    snapshot = snapshot.model_copy(update={"as_of": datetime(9999, 12, 31, 23, tzinfo=UTC)})
    result = calculate_forecast(snapshot)
    assert "datetime_overflow" in codes(result)
    assert result.project_finish.latest is None
