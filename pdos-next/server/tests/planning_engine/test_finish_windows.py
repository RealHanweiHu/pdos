"""Finish-constraint envelopes must contain realizations across calendar gaps."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import product
from zoneinfo import ZoneInfo

import pytest

from pdos_next.engines.planning import calculate_forecast
from pdos_next.engines.planning.dto import (
    CalendarSnapshot,
    Dependency,
    DurationEstimate,
    ExternalWait,
    ForecastInput,
    NodeSnapshot,
    Reference,
    TimeRecord,
    TimeWindow,
    WeekdaySchedule,
    WorkInterval,
)

REF = Reference(source_id="finish-window-fixture", version="v1")
CALENDAR = CalendarSnapshot(
    calendar_id="weekdays",
    version="v1",
    timezone="UTC",
    weekly=tuple(
        WeekdaySchedule(weekday=day, intervals=(WorkInterval(start_minute=540, end_minute=1020),))
        for day in range(5)
    ),
)


def _at(day=2, hour=9, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


def _estimate(lower, upper, *, remaining=False):
    return DurationEstimate(
        minimum=lower,
        maximum=upper,
        measure="remaining" if remaining else "total",
        source=REF,
    )


def _wait(lower, upper, *, target="finish", blocking=True):
    return ExternalWait(
        wait_id="release",
        version="v1",
        source=REF,
        original_timezone="UTC",
        target=target,
        blocking=blocking,
        ready=TimeWindow(earliest=lower, latest=upper),
    )


def _node(key="B", work=(60, 60), waiting=(0, 0), *, actual_start=None, **kwargs):
    return NodeSnapshot(
        node_id=key,
        calendar_id=CALENDAR.calendar_id,
        work=_estimate(*work, remaining=actual_start is not None),
        waiting=_estimate(*waiting, remaining=actual_start is not None),
        allocation_basis="Explicit single work allocation for isolated regression",
        time_records=(
            TimeRecord(
                time_kind="Actual",
                version="v1",
                original_timezone="UTC",
                source=REF,
                start=actual_start,
            ),
        )
        if actual_start is not None
        else (),
        **kwargs,
    )


def _edge(left, right, relation="FS"):
    return Dependency(
        predecessor_id=left,
        successor_id=right,
        relation=relation,
        source=REF,
    )


def _request(*nodes, as_of=None, dependencies=()):
    return ForecastInput(
        snapshot_id="finish-windows",
        version="v1",
        as_of=as_of or _at(),
        horizon_days=14,
        calendars=(CALENDAR,),
        nodes=nodes,
        dependencies=dependencies,
    )


def _rows(result):
    return {row.node_id: row for row in result.nodes}


def _contains(window, point, *, context=""):
    # A finite input must produce usable finite bounds, not pass vacuously as unknown.
    assert window.earliest is not None and window.latest is not None, context
    assert window.earliest <= point <= window.latest, (context, window, point)


@pytest.mark.parametrize("relation", ["FF", "SF"])
def test_finite_finish_dependency_produces_a_usable_envelope(relation):
    predecessor = _node(
        "A",
        work=(120, 120),
        external_waits=(_wait(_at(hour=11), _at(hour=13), target="start"),),
    )
    result = calculate_forecast(
        _request(predecessor, _node(work=(60, 180)), dependencies=(_edge("A", "B", relation),))
    )
    row = _rows(result)["B"]
    assert result.status == "complete"
    assert row.status == "range"
    assert row.start.latest is not None and row.finish.latest is not None
    assert "finish_constraint_range_not_supported" not in {issue.code for issue in result.issues}
    for release_hour, effort in product(range(11, 14), range(60, 181, 30)):
        exact = calculate_forecast(
            _request(
                _node(
                    "A",
                    work=(120, 120),
                    external_waits=(
                        _wait(_at(hour=release_hour), _at(hour=release_hour), target="start"),
                    ),
                ),
                _node(work=(effort, effort)),
                dependencies=(_edge("A", "B", relation),),
            )
        )
        realization = _rows(exact)["B"]
        _contains(row.start, realization.start.earliest)
        _contains(row.finish, realization.finish.earliest)


def test_actual_start_is_preserved_while_finish_bounds_use_separate_release_bounds():
    actual = _at(day=1, hour=15, minute=7)
    result = calculate_forecast(
        _request(
            _node(
                work=(60, 120),
                actual_start=actual,
                external_waits=(_wait(_at(hour=11), _at(hour=13)),),
            ),
        )
    )
    row = _rows(result)["B"]
    assert row.origin == "actual_and_remaining"
    assert row.start == TimeWindow(earliest=actual, latest=actual)
    assert row.remaining_work_start == TimeWindow(earliest=_at(), latest=_at())
    assert row.remaining_work_finish == TimeWindow(earliest=_at(hour=10), latest=_at(hour=11))
    assert row.finish == TimeWindow(earliest=_at(hour=11), latest=_at(hour=13))


@pytest.mark.parametrize("actual_start", [None, _at(day=1)])
def test_open_finish_release_keeps_a_lower_bound_without_claiming_a_deadline(actual_start):
    result = calculate_forecast(
        _request(
            _node(
                work=(60, 120),
                actual_start=actual_start,
                external_waits=(_wait(_at(hour=11), None),),
            )
        )
    )
    row = _rows(result)["B"]
    assert row.finish.earliest is not None and row.finish.earliest >= _at(hour=11)
    assert row.finish.latest is None and result.project_finish.latest is None
    assert result.status == "partial"
    if actual_start:
        assert row.start == TimeWindow(earliest=actual_start, latest=actual_start)
        assert row.remaining_work_finish.latest == _at(hour=11)


@pytest.mark.parametrize("quantity", ["work", "waiting"])
def test_open_duration_with_a_finite_finish_floor_does_not_become_a_point(quantity):
    result = calculate_forecast(
        _request(
            _node(
                **{quantity: (60, None)},
                external_waits=(_wait(_at(hour=12), _at(hour=12)),),
            )
        )
    )
    row = _rows(result)["B"]
    assert row.finish.earliest is not None and row.finish.earliest >= _at(hour=12)
    assert row.finish.latest is None
    assert f"{quantity}_duration_unknown" in {issue.code for issue in result.issues}


@pytest.mark.parametrize("quantity", ["work", "waiting"])
def test_unknown_duration_is_not_replaced_with_zero_to_satisfy_a_finish_floor(quantity):
    result = calculate_forecast(
        _request(
            _node(
                **{quantity: (None, None)},
                external_waits=(_wait(_at(hour=12), _at(hour=12)),),
            )
        )
    )
    row = _rows(result)["B"]
    assert row.finish.latest is None and row.status == "unknown"
    assert f"{quantity}_duration_unknown" in {issue.code for issue in result.issues}


def test_unknown_blocking_finish_release_remains_unknown_but_advisory_does_not_block():
    result = calculate_forecast(
        _request(
            _node("B", external_waits=(_wait(None, None),)),
            _node("C", external_waits=(_wait(None, None, blocking=False),)),
        )
    )
    assert _rows(result)["B"].finish.latest is None
    assert _rows(result)["C"].finish == TimeWindow(earliest=_at(hour=10), latest=_at(hour=10))


def _oracle_request(as_of, floor, work, waiting, clock, target, actual_start=None):
    """Create the same business input with either intervals or point estimates."""
    nodes = [_node("C", work=(1, 1))]
    dependencies = [_edge("B", "C")]
    waits = ()
    if target == "external":
        waits = (_wait(*floor),)
    else:
        nodes.append(_node("A", work=(0, 0), external_waits=(_wait(*floor, target="start"),)))
        dependencies.append(_edge("A", "B", target))
    nodes.append(
        _node(
            work=work,
            waiting=waiting,
            waiting_clock=clock,
            external_waits=waits,
            actual_start=actual_start,
        )
    )
    return _request(*nodes, as_of=as_of, dependencies=tuple(dependencies))


GAP_CASES = (
    (_at(hour=16, minute=58), _at(hour=17), _at(hour=17, minute=2)),
    (_at(hour=16, minute=58), _at(day=5, hour=8, minute=59), _at(day=5, hour=9, minute=1)),
    (_at(day=3, hour=12), _at(day=3, hour=12), _at(day=3, hour=12, minute=2)),
)


@pytest.mark.parametrize("target", ["external", "FF", "SF"])
@pytest.mark.parametrize("clock", ["elapsed", "working"])
@pytest.mark.parametrize("as_of,floor_lower,floor_upper", GAP_CASES)
def test_finish_envelope_contains_every_small_integer_realization_across_weekend(
    target, clock, as_of, floor_lower, floor_upper
):
    envelope = calculate_forecast(
        _oracle_request(as_of, (floor_lower, floor_upper), (0, 3), (0, 3), clock, target)
    )
    assert envelope.status == "complete"
    by_id = _rows(envelope)
    minutes = int((floor_upper - floor_lower).total_seconds() // 60)
    # Checking all small point realizations catches the positive-one-minute branch
    # between zero and maximum effort; no scheduling formula is reproduced here.
    for effort, waiting, offset in product(range(4), range(4), range(minutes + 1)):
        floor = floor_lower + timedelta(minutes=offset)
        exact = calculate_forecast(
            _oracle_request(
                as_of, (floor, floor), (effort, effort), (waiting, waiting), clock, target
            )
        )
        assert exact.status == "complete"
        for key in ("B", "C"):
            for field in ("start", "remaining_work_start", "remaining_work_finish", "finish"):
                realization = getattr(_rows(exact)[key], field)
                assert realization.exact
                _contains(
                    getattr(by_id[key], field),
                    realization.earliest,
                    context=(target, clock, effort, waiting, floor, key, field),
                )
        _contains(envelope.project_finish, exact.project_finish.earliest)


@pytest.mark.parametrize("clock", ["elapsed", "working"])
def test_started_remaining_envelope_contains_realizations_without_moving_the_fact(clock):
    as_of, floor_lower, floor_upper = GAP_CASES[0]
    actual = _at(day=1, hour=16, minute=7)
    envelope = calculate_forecast(
        _oracle_request(
            as_of, (floor_lower, floor_upper), (0, 3), (0, 3), clock, "external", actual
        )
    )
    by_id = _rows(envelope)
    assert by_id["B"].start == TimeWindow(earliest=actual, latest=actual)
    for effort, waiting, offset in product(range(4), range(4), range(3)):
        floor = floor_lower + timedelta(minutes=offset)
        exact = calculate_forecast(
            _oracle_request(
                as_of,
                (floor, floor),
                (effort, effort),
                (waiting, waiting),
                clock,
                "external",
                actual,
            )
        )
        for key in ("B", "C"):
            for field in ("start", "remaining_work_start", "remaining_work_finish", "finish"):
                realization = getattr(_rows(exact)[key], field)
                assert realization.exact
                _contains(
                    getattr(by_id[key], field),
                    realization.earliest,
                    context=(clock, effort, waiting, floor, key, field),
                )


def _assert_realization_is_covered(envelope, realization, *, context):
    assert realization.status == "complete", (context, realization.issues)
    by_id = _rows(envelope)
    for row in realization.nodes:
        for field in ("start", "remaining_work_start", "remaining_work_finish", "finish"):
            point = getattr(row, field)
            assert point.exact, (context, row.node_id, field)
            _contains(
                getattr(by_id[row.node_id], field),
                point.earliest,
                context=(context, row.node_id, field),
            )
    _contains(envelope.project_finish, realization.project_finish.earliest, context=context)


def test_elapsed_wait_internal_extreme_after_shift_is_covered_for_every_minute():
    as_of, floor = _at(day=6), _at(day=6, hour=18)
    envelope = calculate_forecast(
        _oracle_request(as_of, (floor, floor), (60, 60), (0, 600), "elapsed", "external")
    )
    assert envelope.status == "complete"
    observed = {}
    for waiting in range(601):
        exact = calculate_forecast(
            _oracle_request(
                as_of, (floor, floor), (60, 60), (waiting, waiting), "elapsed", "external"
            )
        )
        _assert_realization_is_covered(envelope, exact, context=("elapsed-wait", waiting))
        observed[waiting] = _rows(exact)["B"].finish.earliest
    # At 59 minutes, a one-minute work overflow crosses the overnight gap.
    # Neither the zero-wait nor maximum-wait scenario is the latest finish.
    assert observed[59] == _at(day=7, hour=10)
    assert observed[59] > max(observed[0], observed[600])


@pytest.mark.parametrize("clock", ["elapsed", "working"])
def test_fractional_parallel_effort_and_second_resolution_release_envelope(clock):
    efforts = tuple(map(Decimal, ("0", "0.01", "0.5", "1", "2", "2.01")))
    waits = tuple(map(Decimal, ("0", "0.1", "1.1")))
    releases = tuple(_at(hour=16, minute=58) + timedelta(minutes=n, seconds=1) for n in range(3))
    floors = tuple(_at(hour=17) + timedelta(minutes=n, seconds=31) for n in range(3))

    def scenario(work, waiting, release, floor):
        return _request(
            _node(
                work=work,
                waiting=waiting,
                waiting_clock=clock,
                parallel_units=Decimal("2"),
                divisible_work=True,
                external_waits=(
                    _wait(*release, target="start").model_copy(update={"wait_id": "start-release"}),
                    _wait(*floor),
                ),
            ),
            _node("C", work=(1, 1)),
            as_of=_at(hour=16, minute=58),
            dependencies=(_edge("B", "C"),),
        )

    envelope = calculate_forecast(
        scenario(
            (efforts[0], efforts[-1]),
            (waits[0], waits[-1]),
            (releases[0], releases[-1]),
            (floors[0], floors[-1]),
        )
    )
    assert envelope.status == "complete"
    for effort, waiting, release, floor in product(efforts, waits, releases, floors):
        exact = calculate_forecast(
            scenario((effort, effort), (waiting, waiting), (release, release), (floor, floor))
        )
        _assert_realization_is_covered(
            envelope, exact, context=(clock, effort, waiting, release, floor)
        )
        row = _rows(exact)["B"]
        assert row.start.earliest >= release and row.finish.earliest >= floor
        assert row.start.earliest.second == row.finish.earliest.second == 0


@pytest.mark.parametrize("relation", ["FF", "SF"])
@pytest.mark.parametrize("lag_clock", ["working", "elapsed"])
@pytest.mark.parametrize("lag", [Decimal("-1.5"), Decimal("1.5")])
def test_cross_site_finish_ranges_cover_dst_transition_and_signed_lags(relation, lag_clock, lag):
    los_angeles = CALENDAR.model_copy(
        update={
            "calendar_id": "los-angeles",
            "timezone": "America/Los_Angeles",
            "weekly": (
                *CALENDAR.weekly,
                WeekdaySchedule(
                    weekday=6, intervals=(WorkInterval(start_minute=60, end_minute=240),)
                ),
            ),
        }
    )
    shanghai = CALENDAR.model_copy(
        update={
            "calendar_id": "shanghai",
            "timezone": "Asia/Shanghai",
            "weekly": tuple(
                WeekdaySchedule(
                    weekday=day, intervals=(WorkInterval(start_minute=540, end_minute=1200),)
                )
                for day in range(7)
            ),
        }
    )
    as_of = datetime(2026, 3, 8, 8, 58, tzinfo=UTC)
    releases = tuple(
        datetime(2026, 3, 8, 9, 59, tzinfo=UTC) + timedelta(minutes=n) for n in range(3)
    )
    efforts = (0, 1, 60, 61, 120, 121)

    def scenario(release, work, waiting):
        predecessor = _node(
            "A", work=(1, 1), external_waits=(_wait(*release, target="start"),)
        ).model_copy(update={"calendar_id": shanghai.calendar_id})
        successor = _node(work=work, waiting=waiting).model_copy(
            update={"calendar_id": los_angeles.calendar_id}
        )
        follow_on = _node("C", work=(1, 1)).model_copy(
            update={"calendar_id": los_angeles.calendar_id}
        )
        edge = _edge("A", "B", relation).model_copy(
            update={"lag_minutes": lag, "lag_clock": lag_clock}
        )
        return _request(
            predecessor,
            successor,
            follow_on,
            as_of=as_of,
            dependencies=(edge, _edge("B", "C")),
        ).model_copy(update={"calendars": (shanghai, los_angeles)})

    envelope = calculate_forecast(
        scenario((releases[0], releases[-1]), (efforts[0], efforts[-1]), (0, 2))
    )
    assert envelope.status == "complete"
    assert _rows(envelope)["A"].original_timezone == "Asia/Shanghai"
    assert _rows(envelope)["B"].original_timezone == "America/Los_Angeles"
    # The sampled release window crosses 01:59 PST -> 03:00 PDT in actual UTC time.
    zone = ZoneInfo("America/Los_Angeles")
    assert releases[0].astimezone(zone).utcoffset() == timedelta(hours=-8)
    assert releases[-1].astimezone(zone).utcoffset() == timedelta(hours=-7)
    for release, effort, waiting in product(releases, efforts, range(3)):
        exact = calculate_forecast(
            scenario((release, release), (effort, effort), (waiting, waiting))
        )
        _assert_realization_is_covered(
            envelope, exact, context=(relation, lag_clock, lag, release, effort, waiting)
        )
