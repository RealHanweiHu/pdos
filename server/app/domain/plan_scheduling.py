"""Deterministic FS/SS/FF/SF plan scenarios; capacity reservations remain separate."""

from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, localcontext
from typing import Any

from pydantic import AwareDatetime, Field

from app.contracts.common_objects import Contract, PlanCandidate, PlanDependency, Quantity
from app.domain.working_time import CalendarDefinition, WorkingTime, ceil_minute, minute_quantity

ALGORITHM_VERSION = "initial_plan.minute_constraints.v1"


class NodeAllocation(Contract):
    calendar_key: str
    parallel_units: Quantity = Field(gt=0, le=1000)
    allocation_basis: str = Field(min_length=1, max_length=2048)
    not_before: AwareDatetime | None = None


def _schedule_plan(
    plan: PlanCandidate,
    start: datetime,
    calendars: dict[str, CalendarDefinition],
    allocations: dict[str, NodeAllocation],
) -> dict[str, Any]:
    nodes = {node.node_key: node for node in plan.nodes}
    if set(allocations) != set(nodes):
        raise ValueError("每个节点须明确日历和资源投入假设")
    if any(item.calendar_key not in calendars for item in allocations.values()):
        raise ValueError("节点引用的日历不存在")
    engines = {key: WorkingTime(value) for key, value in calendars.items()}
    incoming: dict[str, list[PlanDependency]] = {key: [] for key in nodes}
    outgoing: dict[str, list[PlanDependency]] = {key: [] for key in nodes}
    for edge in plan.dependencies:
        incoming[edge.successor].append(edge)
        outgoing[edge.predecessor].append(edge)
    pending = {key: len(incoming[key]) for key in nodes}
    queue = sorted(key for key, count in pending.items() if count == 0)
    order = []
    while queue:
        key = queue.pop(0)
        order.append(key)
        for edge in outgoing[key]:
            pending[edge.successor] -= 1
            if pending[edge.successor] == 0:
                queue.append(edge.successor)
                queue.sort()
    if len(order) != len(nodes):
        raise ValueError("执行依赖存在循环")
    origin = ceil_minute(start)
    durations = {
        key: None
        if node.effort_hours is None
        else minute_quantity(node.effort_hours / allocations[key].parallel_units)
        for key, node in nodes.items()
    }

    def engine(key: str) -> WorkingTime:
        return engines[allocations[key].calendar_key]

    def finish(key: str, point: datetime) -> tuple[datetime, datetime | None]:
        duration = durations[key]
        begin = engine(key).snap(point) if duration != 0 else ceil_minute(point)
        return begin, None if duration is None else engine(key).advance(
            begin, duration
        ) + timedelta(days=nodes[key].waiting_days)

    def lag(edge: Any, point: datetime) -> datetime:
        if edge.lag_unit == "calendar_days":
            value = int((abs(edge.lag) * 1440).to_integral_value(rounding=ROUND_CEILING))
            return point + timedelta(minutes=value if edge.lag >= 0 else -value)
        value = minute_quantity(edge.lag)
        return engine(edge.successor).advance(point, value if edge.lag >= 0 else -value)

    def known_finish(key: str, point: datetime) -> datetime:
        end = finish(key, point)[1]
        if end is None:
            raise ValueError("缺工时，无法计算完成约束")
        return end

    def lower_bound(key: str, lower: datetime, end_bound: datetime) -> datetime:
        if known_finish(key, lower) >= end_bound:
            return lower
        lo, hi = 0, max(0, int((ceil_minute(end_bound) - lower).total_seconds() // 60))
        while lo < hi:
            mid = (lo + hi) // 2
            if known_finish(key, lower + timedelta(minutes=mid)) >= end_bound:
                hi = mid
            else:
                lo = mid + 1
        return lower + timedelta(minutes=lo)

    result: dict[str, dict[str, Any]] = {}
    for key in order:
        start_bound = max(origin, ceil_minute(allocations[key].not_before or origin))
        finish_bounds = []
        blockers = []
        for edge in incoming[key]:
            source = result[edge.predecessor]["start" if edge.relation[0] == "s" else "finish"]
            if source is None:
                blockers.append(f"前置{edge.predecessor}的约束时间未知")
                continue
            bound = lag(edge, source)
            if edge.relation[1] == "s":
                start_bound = max(start_bound, bound)
            else:
                finish_bounds.append(bound)
        if finish_bounds and durations[key] is None:
            blockers.append("缺工时，无法反推完成约束对应的开始时间")
        if blockers:
            begin, end = None, None
        else:
            for bound in finish_bounds:
                start_bound = lower_bound(key, start_bound, bound)
            begin, end = finish(key, start_bound)
        if durations[key] is None:
            blockers.append("工作量待估算")
        result[key] = {
            "start": begin,
            "finish": end,
            "unknown_reasons": blockers,
            "work_minutes": durations[key],
            "waiting_days": nodes[key].waiting_days,
            "input_warnings": list(nodes[key].current_missing),
            "latest_start": None,
            "latest_finish": None,
            "total_float_minutes": None,
            "working_float_minutes": None,
            "critical": None,
        }
    complete = all(item["finish"] is not None for item in result.values())
    project_finish = max(item["finish"] for item in result.values()) if complete else None
    if complete:
        assert project_finish is not None
        for key in reversed(order):
            earliest = result[key]["start"]

            def feasible(point: datetime, key: str = key) -> bool:
                begin, end = finish(key, point)
                if end is None or end > project_finish:
                    return False
                for edge in outgoing[key]:
                    left = lag(edge, begin if edge.relation[0] == "s" else end)
                    right = result[edge.successor][
                        "latest_start" if edge.relation[1] == "s" else "latest_finish"
                    ]
                    if left > right:
                        return False
                return True

            lo, hi = 0, max(0, int((project_finish - earliest).total_seconds() // 60))
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if feasible(earliest + timedelta(minutes=mid)):
                    lo = mid
                else:
                    hi = mid - 1
            latest, end = finish(key, earliest + timedelta(minutes=lo))
            slack = int((latest - earliest).total_seconds() // 60)
            result[key].update(
                latest_start=latest,
                latest_finish=end,
                total_float_minutes=slack,
                working_float_minutes=engine(key).working_minutes(earliest, latest),
                critical=slack == 0,
            )
    return {
        "algorithm_version": ALGORITHM_VERSION,
        "precision": "minute_ceiling",
        "waiting_policy": "elapsed_24_hour_days",
        "working_lag_calendar": "successor",
        "capacity_status": "not_checked",
        "complete": complete,
        "project_finish": project_finish.isoformat() if project_finish else None,
        "calendars": {
            key: {
                **asdict(value.evidence),
                "calendar_id": str(value.evidence.calendar_id),
                "definition": calendars[key].model_dump(mode="json"),
            }
            for key, value in engines.items()
        },
        "nodes": [
            {
                "node_key": key,
                **{
                    name: value.isoformat() if isinstance(value, datetime) else value
                    for name, value in result[key].items()
                },
                "allocation": allocations[key].model_dump(mode="json"),
            }
            for key in order
        ],
    }


def schedule_plan(
    plan: PlanCandidate,
    start: datetime,
    calendars: dict[str, CalendarDefinition],
    allocations: dict[str, NodeAllocation],
) -> dict[str, Any]:
    with localcontext() as calculation_context:
        calculation_context.prec = 48
        return _schedule_plan(plan, start, calendars, allocations)
