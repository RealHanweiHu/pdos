"""Deterministic Forecast candidates; no database, models, booking or command side effects."""

import hashlib
import heapq
import json
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal, localcontext

from .calendar import CalendarError, WorkingTime, ceil_minute
from .dto import (
    Dependency,
    ForecastInput,
    ForecastResult,
    Issue,
    NodeForecast,
    NodeSnapshot,
    TimeWindow,
)

ALGORITHM_VERSION = "planning.minute_forecast.v2"
UNKNOWN = TimeWindow(earliest=None, latest=None)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _minutes(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def _exact(value: datetime | None) -> TimeWindow:
    return TimeWindow(earliest=value, latest=value)


def _maximum(windows: list[TimeWindow]) -> TimeWindow:
    # Missing predecessor anchors are not replaced by zero or by the current time.
    return TimeWindow(
        earliest=None
        if any(item.earliest is None for item in windows)
        else max(item.earliest for item in windows),
        latest=None
        if any(item.latest is None for item in windows)
        else max(item.latest for item in windows),
    )


def _issue(code: str, message: str, key: str, source: str = "", blocking=True) -> Issue:
    return Issue(
        code=code,
        message=message,
        node_ids=(key,),
        source_ids=(source,) if source else (),
        blocking=blocking,
    )


def _structure(snapshot: ForecastInput) -> tuple[list[str], tuple[Issue, ...]]:
    issues = []
    for label, values in (
        ("node", [item.node_id for item in snapshot.nodes]),
        ("calendar", [item.calendar_id for item in snapshot.calendars]),
        ("resource", [item.resource_id for item in snapshot.resources]),
    ):
        if len(values) != len(set(values)):
            issues.append(Issue(code=f"duplicate_{label}_id", message=f"Duplicate {label} ID"))
    nodes = {item.node_id: item for item in snapshot.nodes}
    calendars = {item.calendar_id for item in snapshot.calendars}
    for node in snapshot.nodes:
        if node.calendar_id not in calendars:
            issues.append(
                _issue("missing_calendar", "Node calendar snapshot missing", node.node_id)
            )
        for record in node.time_records:
            if record.time_kind == "Actual" and any(
                point is not None and point > snapshot.as_of
                for point in (record.start, record.finish)
            ):
                issues.append(
                    _issue("actual_after_as_of", "Actual is after snapshot", node.node_id)
                )
    edges = set()
    incoming = dict.fromkeys(nodes, 0)
    outgoing: dict[str, list[str]] = {key: [] for key in nodes}
    for edge in snapshot.dependencies:
        identity = (edge.predecessor_id, edge.successor_id, edge.relation)
        if identity in edges:
            issues.append(Issue(code="duplicate_dependency", message="Duplicate dependency"))
        edges.add(identity)
        if edge.predecessor_id not in nodes or edge.successor_id not in nodes:
            issues.append(
                Issue(code="missing_dependency_node", message="Dependency endpoint missing")
            )
            continue
        incoming[edge.successor_id] += 1
        outgoing[edge.predecessor_id].append(edge.successor_id)
    queue = [key for key, count in incoming.items() if not count]
    heapq.heapify(queue)
    order = []
    while queue:
        key = heapq.heappop(queue)
        order.append(key)
        for successor in outgoing[key]:
            incoming[successor] -= 1
            if incoming[successor] == 0:
                heapq.heappush(queue, successor)
    if len(order) != len(nodes):
        issues.append(
            Issue(
                code="dependency_cycle",
                message="Execution dependency graph is cyclic; no schedule produced",
                node_ids=tuple(sorted(set(nodes) - set(order))),
            )
        )
    return order, tuple(issues)


def _lag(edge: Dependency, point: datetime, calendar: WorkingTime) -> datetime:
    # Constraint lower bounds round toward the future, including negative fractions.
    minutes = _minutes(edge.lag_minutes)
    return (
        calendar.advance(point, minutes)
        if edge.lag_clock == "working"
        else ceil_minute(point) + timedelta(minutes=minutes)
    )


def _profile(node: NodeSnapshot, calendar: WorkingTime, point: datetime, upper: bool):
    effort = node.work.maximum if upper else node.work.minimum
    waiting = node.waiting.maximum if upper else node.waiting.minimum
    return _duration_profile(node, calendar, point, effort, waiting)


def _duration_profile(node, calendar, point, effort, waiting):
    # Unknown work still has a possible start; its completion remains unknown.
    start = calendar.snap(point) if effort != 0 else ceil_minute(point)
    if effort is None:
        return start, None, None
    work_finish = calendar.advance(start, _minutes(effort / node.parallel_units))
    if waiting is None:
        return start, work_finish, None
    minutes = _minutes(waiting)
    finish = (
        calendar.advance(work_finish, minutes)
        if node.waiting_clock == "working"
        else work_finish + timedelta(minutes=minutes)
    )
    return start, work_finish, finish


def _floor_profile(node, calendar, lower, floor, effort, waiting):
    """Earliest minute-grid profile for one fixed, finite duration and finish floor."""
    first = _duration_profile(node, calendar, lower, effort, waiting)
    if first[2] >= floor:
        return first
    lo, hi = 0, max(0, int((ceil_minute(floor) - lower).total_seconds() // 60))
    while lo < hi:
        mid = (lo + hi) // 2
        if (
            _duration_profile(node, calendar, lower + timedelta(minutes=mid), effort, waiting)[2]
            >= floor
        ):
            hi = mid
        else:
            lo = mid + 1
    return _duration_profile(node, calendar, lower + timedelta(minutes=lo), effort, waiting)


def _finish_windows(node, calendar, lower, floor):
    """Enclose coupled duration/finish scenarios, without treating corners as scenarios.

    Within each zero/positive-work branch, a longer duration weakly decreases
    the earliest feasible start. Completion is NOT monotone in that duration:
    moving the start across a shift gap can overshoot a finish floor. Therefore
    propagate the enclosing start interval through independent duration bounds.
    These component bounds need not be jointly attainable or tight.
    """
    if lower.earliest is None or floor.earliest is None:
        return UNKNOWN, UNKNOWN, UNKNOWN
    work, waiting = node.work, node.waiting
    minimum_known = work.minimum is not None and waiting.minimum is not None
    maximum_known = work.maximum is not None and waiting.maximum is not None

    def solve(release, finish, effort, wait):
        return _floor_profile(node, calendar, ceil_minute(release), finish, effort, wait)

    if maximum_known:
        starts = [solve(lower.earliest, floor.earliest, work.maximum, waiting.maximum)[0]]
        if work.minimum == 0 and work.maximum > 0:
            starts.append(solve(lower.earliest, floor.earliest, Decimal(0), waiting.maximum)[0])
        earliest = min(starts)
    else:
        # A release is still a known lower bound; it is not an invented duration.
        earliest = (
            ceil_minute(lower.earliest)
            if work.minimum in (None, 0)
            else calendar.snap(lower.earliest)
        )

    latest = None
    if minimum_known and lower.latest is not None and floor.latest is not None:
        starts = [solve(lower.latest, floor.latest, work.minimum, waiting.minimum)[0]]
        if work.minimum == 0 and work.maximum != 0:
            # [0, max] includes a positive one-minute effective-work branch.
            # It snaps to a working interval; the zero-work branch does not.
            positive = (
                min(node.parallel_units, work.maximum) if work.maximum else node.parallel_units
            )
            starts.append(solve(lower.latest, floor.latest, positive, waiting.minimum)[0])
        latest = max(starts)

    start = TimeWindow(earliest=earliest, latest=latest)
    low = _profile(node, calendar, earliest, False)
    high = _profile(node, calendar, latest, True) if latest is not None else (None, None, None)
    finish_low = max(floor.earliest, low[2]) if low[2] is not None else floor.earliest
    finish_high = high[2]

    if maximum_known and work.minimum == work.maximum and waiting.minimum == waiting.maximum:
        # With fixed durations, both floor and release are monotone. Retain the
        # exact endpoint results, including a calendar gap's finish overshoot.
        low = solve(lower.earliest, floor.earliest, work.minimum, waiting.minimum)
        finish_low = low[2]

    return (
        start,
        TimeWindow(earliest=low[1], latest=high[1]),
        TimeWindow(earliest=finish_low, latest=finish_high),
    )


def _node(
    node: NodeSnapshot,
    snapshot: ForecastInput,
    calendar: WorkingTime,
    incoming: list[Dependency],
    results: dict[str, NodeForecast],
) -> NodeForecast:
    issues = []
    actual = next((item for item in node.time_records if item.time_kind == "Actual"), None)
    actual_start, actual_finish = (actual.start, actual.finish) if actual else (None, None)
    start_bounds = [_exact(max(snapshot.as_of, node.not_before or snapshot.as_of))]
    finish_bounds = []
    anchored_bounds: list[tuple[str, TimeWindow, str]] = []
    for edge in incoming:
        predecessor = results[edge.predecessor_id]
        source = predecessor.start if edge.relation[0] == "S" else predecessor.finish
        bound = TimeWindow(
            earliest=_lag(edge, source.earliest, calendar) if source.earliest else None,
            latest=_lag(edge, source.latest, calendar) if source.latest else None,
        )
        target = edge.relation[1]
        (start_bounds if target == "S" else finish_bounds).append(bound)
        anchored_bounds.append((target, bound, edge.source.source_id))
        if not bound.exact:
            issues.append(
                _issue(
                    "dependency_uncertain",
                    "Dependency endpoint is a range or unknown",
                    node.node_id,
                    edge.source.source_id,
                    blocking=False,
                )
            )
    for wait in node.external_waits:
        if wait.blocking:
            (start_bounds if wait.target == "start" else finish_bounds).append(wait.ready)
            anchored_bounds.append(
                ("S" if wait.target == "start" else "F", wait.ready, wait.source.source_id)
            )
        if not wait.ready.exact:
            issues.append(
                _issue(
                    "external_wait_uncertain",
                    "External readiness is a range or unknown",
                    node.node_id,
                    wait.source.source_id,
                    blocking=wait.blocking and wait.ready.latest is None,
                )
            )
    for target, bound, source in anchored_bounds:
        point = actual_start if target == "S" else actual_finish
        if point is not None and bound.earliest is not None and point < bound.earliest:
            issues.append(
                _issue(
                    "actual_constraint_conflict",
                    "Actual predates constraint; preserved",
                    node.node_id,
                    source,
                )
            )
    if actual_start and node.not_before and actual_start < node.not_before:
        issues.append(
            _issue("actual_constraint_conflict", "Actual predates release; preserved", node.node_id)
        )
    start, finish, work_start, work_finish = UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN
    origin = (
        "actual_anchor" if actual_finish else "actual_and_remaining" if actual_start else "estimate"
    )
    if actual_finish is not None:
        start, finish = _exact(actual_start), _exact(actual_finish)
    else:
        missing_remaining = bool(actual_start) and (
            node.work.measure != "remaining" or node.waiting.measure != "remaining"
        )
        if missing_remaining:
            issues.append(
                _issue(
                    "remaining_estimate_required",
                    "Started node needs remaining work and wait",
                    node.node_id,
                )
            )
        for label, estimate in (("work", node.work), ("waiting", node.waiting)):
            if estimate.maximum is None:
                issues.append(
                    _issue(
                        f"{label}_duration_unknown",
                        "No finite upper duration supplied",
                        node.node_id,
                        estimate.source.source_id,
                    )
                )
        lower = _maximum(start_bounds)
        if actual_start:
            # A start dependency already violated by a fact is reported, not moved forward.
            lower = _exact(max(snapshot.as_of, node.not_before or snapshot.as_of))
            blocking_waits = [
                wait.ready
                for wait in node.external_waits
                if wait.blocking and wait.target == "start"
            ]
            if blocking_waits:
                lower = _maximum([lower, *blocking_waits])
        floor = _maximum(finish_bounds) if finish_bounds else None
        exact_duration = (
            node.work.minimum is not None
            and node.work.minimum == node.work.maximum
            and node.waiting.minimum is not None
            and node.waiting.minimum == node.waiting.maximum
        )
        if floor is not None and not exact_duration and not actual_start:
            issues.append(
                _issue(
                    "finish_constraint_envelope",
                    "Coupled finish/duration bounds are conservative, not jointly attainable dates",
                    node.node_id,
                    blocking=False,
                )
            )
        if not missing_remaining and lower.earliest is not None:
            if floor is not None and not actual_start:
                work_start, work_finish, finish = _finish_windows(node, calendar, lower, floor)
            else:
                points = []
                for upper, bound in ((False, lower.earliest), (True, lower.latest)):
                    if bound is None:
                        points.append((None, None, None))
                        continue
                    begin, worked, end = _profile(node, calendar, bound, upper)
                    if floor is not None:
                        limit = floor.latest if upper else floor.earliest
                        end = max(end, limit) if end is not None and limit is not None else None
                    points.append((begin, worked, end))
                work_start = TimeWindow(earliest=points[0][0], latest=points[1][0])
                work_finish = TimeWindow(earliest=points[0][1], latest=points[1][1])
                finish = TimeWindow(earliest=points[0][2], latest=points[1][2])
            start = work_start
        if actual_start:
            start = _exact(actual_start)
    if any(item.code == "actual_constraint_conflict" for item in issues):
        status = "conflicted"
    elif not finish.latest:
        status = "unknown"
    else:
        status = "exact" if finish.exact and (start.exact or actual_finish) else "range"
    return NodeForecast(
        node_id=node.node_id,
        calendar_id=node.calendar_id,
        calendar_version=calendar.definition.version,
        original_timezone=calendar.definition.timezone,
        start=start,
        finish=finish,
        remaining_work_start=work_start,
        remaining_work_finish=work_finish,
        status=status,
        origin=origin,
        issues=tuple(issues),
    )


def _capacity(snapshot: ForecastInput, results: dict[str, NodeForecast], calendars):
    requested = any(
        node.resources and results[node.node_id].origin != "actual_anchor"
        for node in snapshot.nodes
    )
    if not requested:
        return "not_requested", ()
    resources = {item.resource_id: item for item in snapshot.resources}
    proposals: dict[str, list[tuple[datetime, datetime, Decimal, str]]] = {}
    issues, uncertain = [], False
    for node in snapshot.nodes:
        row = results[node.node_id]
        if row.origin == "actual_anchor" or (
            row.remaining_work_start.exact
            and row.remaining_work_finish.exact
            and row.remaining_work_start.earliest == row.remaining_work_finish.earliest
        ):
            continue
        for need in node.resources:
            resource = resources.get(need.resource_id)
            if resource is None:
                uncertain = True
                issues.append(
                    _issue(
                        "resource_snapshot_missing",
                        "Required capacity snapshot missing",
                        node.node_id,
                        need.resource_id,
                    )
                )
                continue
            if need.units > resource.capacity:
                issues.append(
                    _issue(
                        "resource_capacity_exceeded",
                        "Node demand exceeds pool capacity",
                        node.node_id,
                        need.resource_id,
                    )
                )
            if (
                not row.remaining_work_start.exact
                or not row.remaining_work_finish.exact
                or any(item.code == "finish_constraint_envelope" for item in row.issues)
            ):
                uncertain = True
                issues.append(
                    _issue(
                        "resource_interval_unknown",
                        "Capacity requires exact remaining work",
                        node.node_id,
                        need.resource_id,
                    )
                )
                continue
            engine = calendars[node.calendar_id]
            resource_calendar = calendars.get(resource.calendar_id)
            if resource_calendar is None:
                uncertain = True
                issues.append(
                    _issue(
                        "resource_calendar_missing",
                        "Resource calendar snapshot missing",
                        node.node_id,
                        need.resource_id,
                    )
                )
                continue
            try:
                segments = engine.segments(
                    row.remaining_work_start.earliest, row.remaining_work_finish.earliest
                )
                if any(
                    resource_calendar.working_minutes(start, end)
                    != int((end - start).total_seconds() // 60)
                    for start, end in segments
                ):
                    issues.append(
                        _issue(
                            "resource_calendar_unavailable",
                            "Work interval falls outside resource working time",
                            node.node_id,
                            need.resource_id,
                        )
                    )
            except (CalendarError, OverflowError) as exc:
                uncertain = True
                issues.append(
                    _issue(
                        getattr(exc, "code", "datetime_overflow"),
                        str(exc),
                        node.node_id,
                        need.resource_id,
                    )
                )
                continue
            for start, end in segments:
                proposals.setdefault(need.resource_id, []).append(
                    (start, end, need.units, node.node_id)
                )
    for key, intervals in proposals.items():
        resource = resources[key]
        events: dict[datetime, list[tuple[Decimal, tuple[str, str]]]] = {}
        tagged = [
            (start, end, units, ("candidate", identity))
            for start, end, units, identity in intervals
        ]
        tagged += [
            (item.start, item.finish, item.units, ("occupancy", item.occupancy_id))
            for item in resource.occupancies
        ]
        for start, end, units, identity in tagged:
            events.setdefault(start, []).append((units, identity))
            events.setdefault(end, []).append((-units, identity))
        active: dict[tuple[str, str], Decimal] = {}
        for point, changes in sorted(events.items()):
            for units, identity in changes:
                active[identity] = active.get(identity, Decimal(0)) + units
                if not active[identity]:
                    del active[identity]
            candidate_nodes = tuple(
                sorted(identity[1] for identity in active if identity[0] == "candidate")
            )
            if candidate_nodes and sum(active.values()) > resource.capacity:
                issues.append(
                    Issue(
                        code="resource_capacity_conflict",
                        message=f"Pool {key} over capacity at {point.isoformat()}",
                        node_ids=candidate_nodes,
                        source_ids=(resource.source.source_id,),
                    )
                )
    conflict = any(
        item.code
        in {
            "resource_capacity_conflict",
            "resource_capacity_exceeded",
            "resource_calendar_unavailable",
        }
        for item in issues
    )
    return "conflicted" if conflict else "unknown" if uncertain else "checked", tuple(issues)


def _floats(snapshot, order, results, calendars, outgoing):
    for key in reversed(order):
        node = next(item for item in snapshot.nodes if item.node_id == key)
        calendar = calendars[node.calendar_id]
        earliest = results[key].start.earliest
        deadline = max(row.finish.latest for row in results.values())

        def feasible(
            minutes, node=node, calendar=calendar, earliest=earliest, deadline=deadline, key=key
        ):
            start, _, finish = _profile(
                node, calendar, earliest + timedelta(minutes=minutes), False
            )
            if finish > deadline:
                return False
            for edge in outgoing[key]:
                successor = results[edge.successor_id]
                target = (
                    successor.latest_start if edge.relation[1] == "S" else successor.latest_finish
                )
                point = start if edge.relation[0] == "S" else finish
                if _lag(edge, point, calendars[successor.calendar_id]) > target:
                    return False
            return True

        low, high = 0, max(0, int((deadline - earliest).total_seconds() // 60))
        while low < high:
            middle = (low + high + 1) // 2
            if feasible(middle):
                low = middle
            else:
                high = middle - 1
        start, _, finish = _profile(node, calendar, earliest + timedelta(minutes=low), False)
        slack = int((start - earliest).total_seconds() // 60)
        results[key] = results[key].model_copy(
            update={
                "latest_start": start,
                "latest_finish": finish,
                "float_minutes": slack,
                "working_float_minutes": calendar.working_minutes(earliest, start),
                "critical": slack == 0,
            }
        )


def calculate_forecast(snapshot: ForecastInput) -> ForecastResult:
    """Compute only a candidate from immutable snapshots, under fixed Decimal precision."""
    with localcontext() as arithmetic:
        arithmetic.prec = 48
        return _calculate(snapshot)


def _calculate(snapshot: ForecastInput) -> ForecastResult:
    order, issues = _structure(snapshot)
    engines, rule_digests = {}, []
    for calendar in sorted(snapshot.calendars, key=lambda item: item.calendar_id):
        try:
            engine = WorkingTime(calendar, snapshot.horizon_days)
            engines[calendar.calendar_id] = engine
            rule_digests.append((calendar.calendar_id, engine.timezone_rules_sha256))
        except CalendarError as exc:
            issues += (Issue(code=exc.code, message=str(exc)),)
    results: dict[str, NodeForecast] = {}
    capacity = "unknown" if any(node.resources for node in snapshot.nodes) else "not_requested"
    float_status = "not_calculated"
    if not issues:
        incoming: dict[str, list[Dependency]] = {key: [] for key in order}
        outgoing: dict[str, list[Dependency]] = {key: [] for key in order}
        for edge in snapshot.dependencies:
            incoming[edge.successor_id].append(edge)
            outgoing[edge.predecessor_id].append(edge)
        nodes = {item.node_id: item for item in snapshot.nodes}
        for key in order:
            node, calendar = nodes[key], engines[nodes[key].calendar_id]
            try:
                row = _node(node, snapshot, calendar, incoming[key], results)
                horizon = snapshot.as_of + timedelta(days=snapshot.horizon_days)
                if any(
                    point and point > horizon
                    for window in (row.start, row.finish)
                    for point in (window.earliest, window.latest)
                ):
                    raise CalendarError(
                        "forecast_horizon_exhausted", "Forecast exceeds snapshot horizon"
                    )
            except (CalendarError, OverflowError) as exc:
                issue = _issue(getattr(exc, "code", "datetime_overflow"), str(exc), key)
                actual = next(
                    (item for item in node.time_records if item.time_kind == "Actual"), None
                )
                actual_start, actual_finish = (
                    (actual.start, actual.finish) if actual else (None, None)
                )
                row = NodeForecast(
                    node_id=key,
                    calendar_id=node.calendar_id,
                    calendar_version=calendar.definition.version,
                    original_timezone=calendar.definition.timezone,
                    start=_exact(actual_start),
                    finish=_exact(actual_finish),
                    remaining_work_start=UNKNOWN,
                    remaining_work_finish=UNKNOWN,
                    status="conflicted" if actual_finish else "unknown",
                    origin="actual_anchor"
                    if actual_finish
                    else "actual_and_remaining"
                    if actual_start
                    else "estimate",
                    issues=(issue,),
                )
            results[key] = row
        capacity, capacity_issues = _capacity(snapshot, results, engines)
        issues += tuple(item for row in results.values() for item in row.issues) + capacity_issues
        if (
            all(row.status == "exact" for row in results.values())
            and not any(item.blocking for item in issues)
            and not any(item.code == "finish_constraint_envelope" for item in issues)
            and capacity == "not_requested"
            and all(row.origin == "estimate" for row in results.values())
        ):
            try:
                _floats(snapshot, order, results, engines, outgoing)
                float_status = "calculated"
            except (CalendarError, OverflowError) as exc:
                issues += (Issue(code="float_not_calculated", message=str(exc), blocking=False),)
                results = {
                    key: row.model_copy(
                        update={
                            "latest_start": None,
                            "latest_finish": None,
                            "float_minutes": None,
                            "working_float_minutes": None,
                            "critical": None,
                        }
                    )
                    for key, row in results.items()
                }
    finish = _maximum([row.finish for row in results.values()]) if results else UNKNOWN
    status = (
        "invalid"
        if not results
        else "partial"
        if (finish.latest is None or any(item.blocking for item in issues))
        else "complete"
    )
    evidence = {"input": snapshot.model_dump(mode="json"), "timezone_rules": rule_digests}
    output = dict(
        algorithm_version=ALGORITHM_VERSION,
        input_sha256=_digest(evidence),
        input_snapshot=snapshot,
        timezone_rule_digests=tuple(rule_digests),
        status=status,
        project_finish=finish,
        nodes=tuple(results.values()),
        issues=issues,
        capacity_status=capacity,
        float_status=float_status,
    )
    candidate = {
        "input_sha256": output["input_sha256"],
        "algorithm_version": ALGORITHM_VERSION,
        "status": status,
        "nodes": [row.model_dump(mode="json") for row in results.values()],
        "issues": [item.model_dump(mode="json") for item in issues],
        "capacity_status": capacity,
        "float_status": float_status,
    }
    return ForecastResult(**output, candidate_sha256=_digest(candidate))
