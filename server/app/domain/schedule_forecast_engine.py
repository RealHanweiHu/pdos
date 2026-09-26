"""Forward schedule forecasts preserve actual anchors and explicit remaining-work uncertainty."""

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal, localcontext
from types import SimpleNamespace
from typing import Any

from app.contracts.common_objects import PlanCandidate, PlanDependency
from app.domain.plan_scheduling import NodeAllocation
from app.domain.working_time import CalendarDefinition, WorkingTime, ceil_minute, minute_quantity

ALGORITHM_VERSION = "project_forecast.actual_remaining.v6"
MATERIAL_ALGORITHM_VERSION = "project_forecast.actual_remaining.material.v7"
TOOLING_ALGORITHM_VERSION = "project_forecast.actual_remaining.tooling.v8"

ResourcePlacer = Callable[
    [str, WorkingTime, datetime, int, int, datetime | None],
    tuple[datetime | None, datetime | None, list[str]],
]


def calculate_forecast(
    plan: PlanCandidate,
    as_of: datetime,
    calendars: dict[str, CalendarDefinition],
    allocations: dict[str, NodeAllocation],
    tasks: dict[str, dict[str, Any]],
    estimates: dict[str, dict[str, Any]],
    external_dependencies: list[dict[str, Any]] | None = None,
    resource_placer: ResourcePlacer | None = None,
) -> dict[str, Any]:
    with localcontext() as arithmetic:
        arithmetic.prec = 48
        return _calculate(
            plan,
            as_of,
            calendars,
            allocations,
            tasks,
            estimates,
            external_dependencies,
            resource_placer,
        )


def _calculate(
    plan: PlanCandidate,
    as_of: datetime,
    calendars: dict[str, CalendarDefinition],
    allocations: dict[str, NodeAllocation],
    tasks: dict[str, dict[str, Any]],
    estimates: dict[str, dict[str, Any]],
    external_dependencies: list[dict[str, Any]] | None = None,
    resource_placer: ResourcePlacer | None = None,
) -> dict[str, Any]:
    nodes = {node.node_key: node for node in plan.nodes}
    if set(nodes) != set(tasks) or set(nodes) != set(allocations) or set(estimates) - set(nodes):
        raise ValueError("预测输入须对应全部实际计划节点")
    external_dependencies = external_dependencies or []
    node_keys = {task.get("node_id"): key for key, task in tasks.items()}
    if any(edge["successor_node_id"] not in node_keys for edge in external_dependencies):
        raise ValueError("已应用跨项目依赖的后序节点不能从计划中直接移除")
    engines = {key: WorkingTime(value) for key, value in calendars.items()}
    incoming: dict[str, list[PlanDependency]] = {key: [] for key in nodes}
    outgoing: dict[str, list[PlanDependency]] = {key: [] for key in nodes}
    for edge in plan.dependencies:
        incoming[edge.successor].append(edge)
        outgoing[edge.predecessor].append(edge)
    pending = {key: len(incoming[key]) for key in nodes}
    queue = sorted(key for key, value in pending.items() if value == 0)
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
        raise ValueError("预测执行依赖存在循环")
    results: dict[str, dict[str, Any]] = {}
    residuals: dict[str, dict[str, Any]] = {}
    now = ceil_minute(as_of)

    def instant(value: Any) -> datetime | None:
        return datetime.fromisoformat(value) if isinstance(value, str) else value

    def lagged(edge: Any, anchor: datetime) -> datetime:
        if edge.lag_unit == "calendar_days":
            minutes = int((abs(edge.lag) * 1440).to_integral_value(rounding=ROUND_CEILING))
            return ceil_minute(anchor) + timedelta(minutes=minutes if edge.lag >= 0 else -minutes)
        return engines[allocations[edge.successor].calendar_key].advance(
            anchor, minute_quantity(edge.lag) * (1 if edge.lag >= 0 else -1)
        )

    for key in order:
        task = tasks[key]
        node = nodes[key]
        allocation = allocations[key]
        engine = engines[allocation.calendar_key]
        actual_start = instant(task.get("actual_start"))
        actual_finish = instant(task.get("actual_finish"))
        estimate = estimates.get(key)
        unknown = list(task.get("input_unknown", ()))
        warnings = list(task.get("input_warnings", ()))
        start_bounds: list[datetime] = []
        finish_bounds: list[datetime] = []
        for edge in incoming[key]:
            point = "start" if edge.relation[0] == "s" else "finish"
            anchor = results[edge.predecessor][point]
            if anchor is None:
                unknown.append(f"前置{edge.predecessor}的{point}时间未知")
                continue
            bound = lagged(edge, anchor)
            (start_bounds if edge.relation[1] == "s" else finish_bounds).append(bound)
            actual_target = actual_start if edge.relation[1] == "s" else actual_finish
            if actual_target is not None and actual_target < bound:
                warnings.append(
                    f"实际记录早于{edge.predecessor}的{edge.relation.upper()}约束；保留事实并提示差异"
                )
        for external in external_dependencies:
            if node_keys[external["successor_node_id"]] != key:
                continue
            anchor = instant(external["anchor"])
            if external["anchor_kind"] == "forecast" and anchor and anchor < as_of:
                anchor = None
            if anchor is None or not external["is_current"]:
                unknown.append(
                    external["unknown_reason"] or "跨项目前置预测已过时，须更新实际或预测依据"
                )
                continue
            external_edge = SimpleNamespace(
                successor=key,
                relation=external["relation"],
                lag=Decimal(external["lag"]),
                lag_unit=external["lag_unit"],
            )
            bound = lagged(external_edge, anchor)
            (start_bounds if external["target_point"] == "start" else finish_bounds).append(bound)
            actual_target = actual_start if external["target_point"] == "start" else actual_finish
            if actual_target is not None and actual_target < bound:
                warnings.append("实际记录早于跨项目依赖约束；保留事实并提示差异")
        material_bounds: list[datetime] = []
        for condition in task.get("material_conditions", []):
            if condition["status"] == "ready":
                continue
            anchor = instant(condition.get("ready_at"))
            note = f"物料异常 {condition['exception_id']}："
            historical = actual_finish is not None or (
                condition["target_point"] == "start" and actual_start is not None
            )
            if condition["status"] != "estimate" or anchor is None or anchor < as_of:
                message = note + "供给尚待核对或预计日期已失效"
                (warnings if historical else unknown).append(message)
            elif historical:
                warnings.append(note + "保留实际时间，原物料预测条件仅供核对")
            else:
                material_bounds.append(ceil_minute(anchor))
                warnings.append(note + "采用具名预计可用时间；未形成正式供应承诺")
        for condition in task.get("tooling_conditions", []):
            point = condition["target_point"]
            actual_target = actual_start if point == "start" else actual_finish
            historical = actual_target is not None
            anchor = instant(
                condition.get("available_at")
                if condition["status"] == "ready"
                else condition.get("ready_at")
            )
            note = f"工装 {condition['title']}："
            if condition["status"] == "ready" and anchor is not None:
                if actual_target is not None and actual_target < anchor:
                    warnings.append(note + "实际节点时间早于已核对的工装可用时间；保留事实")
                elif not historical:
                    (start_bounds if point == "start" else finish_bounds).append(
                        ceil_minute(anchor)
                    )
            elif condition["status"] == "estimate" and anchor is not None and anchor >= as_of:
                if not historical:
                    (start_bounds if point == "start" else finish_bounds).append(
                        ceil_minute(anchor)
                    )
                warnings.append(note + "采用具名预计日期，实际办理仍须可用证据")
            else:
                (warnings if historical else unknown).append(
                    note + "实际可用待核对或预计日期已失效"
                )
        origin = "explicit_remaining" if estimate else "approved_initial_estimate"
        if actual_finish is not None:
            start = actual_start
            finish = actual_finish
            origin = "actual"
            unknown = []
        else:
            if task["status"] == "skipped":
                unknown.append("节点已跳过，尚无获批计划变更或实际完成记录")
            if actual_start is not None and estimate is None:
                unknown.append("已开工节点需要明确剩余工时和剩余等待")
            if task["status"] == "blocked" and (estimate is None or not estimate.get("not_before")):
                unknown.append("受阻节点需要明确预计恢复时间")
            hours = (
                estimate.get("remaining_hours")
                if estimate
                else (None if actual_start else node.effort_hours)
            )
            waiting = (
                estimate.get("remaining_waiting_days")
                if estimate
                else (None if actual_start else node.waiting_days)
            )
            if hours is None:
                unknown.append("剩余工时未知")
            if waiting is None:
                unknown.append("剩余等待未知")
            if task.get("node_kind") == "milestone" and (
                hours is None or Decimal(hours) != 0 or waiting != 0
            ):
                unknown.append("里程碑是零时长检查点，实际工作和等待须放在前置业务节点")
            release = instant(estimate.get("not_before")) if estimate else allocation.not_before
            earliest = max(
                now, release or now, *material_bounds, *(start_bounds if not actual_start else [])
            )
            start = actual_start
            finish = None
            if not unknown:
                assert hours is not None and waiting is not None
                duration = minute_quantity(Decimal(hours) / allocation.parallel_units)
                work_start = engine.snap(earliest) if duration else earliest
                finish = engine.advance(work_start, duration) + timedelta(days=waiting)
                start = actual_start or work_start
                if finish_bounds and finish < max(finish_bounds):
                    target = max(finish_bounds)
                    if actual_start:
                        finish = target
                    else:
                        # Move only forecast work; actual starts never move to fit a plan.
                        low = 0
                        high = max(0, int((target - work_start).total_seconds() // 60) + 1)
                        while low < high:
                            mid = (low + high) // 2
                            candidate_start = work_start + timedelta(minutes=mid)
                            candidate_finish = engine.advance(
                                engine.snap(candidate_start) if duration else candidate_start,
                                duration,
                            ) + timedelta(days=waiting)
                            if candidate_finish >= target:
                                high = mid
                            else:
                                low = mid + 1
                        start = (
                            engine.snap(work_start + timedelta(minutes=low))
                            if duration
                            else work_start + timedelta(minutes=low)
                        )
                        finish = engine.advance(start, duration) + timedelta(days=waiting)
                residuals[key] = {
                    "work_start": work_start if actual_start else start,
                    "duration": duration,
                    "waiting": waiting,
                    "finish_floor": max(finish_bounds) if finish_bounds else None,
                }
            elif not actual_start:
                start = None
        if resource_placer is not None and key in residuals:
            profile = residuals[key]
            placed, placed_finish, reasons = resource_placer(
                key,
                engine,
                profile["work_start"],
                profile["duration"],
                profile["waiting"],
                profile["finish_floor"],
            )
            if placed is None or placed_finish is None:
                unknown.extend(reasons)
                start, finish = actual_start, None
                residuals.pop(key)
            else:
                profile["work_start"] = placed
                start, finish = actual_start or placed, placed_finish
        residual = residuals.get(key)
        results[key] = {
            "remaining_work_start": residual["work_start"] if residual else None,
            "remaining_work_minutes": residual["duration"]
            if residual
            else 0
            if actual_finish
            else None,
            "allocation": allocation.model_dump(mode="json"),
            "start": start,
            "finish": finish,
            "actual_start": actual_start,
            "actual_finish": actual_finish,
            "origin": origin,
            "unknown_reasons": list(dict.fromkeys(unknown)),
            "warnings": warnings,
            "estimate": estimate,
            "status": task["status"],
            **(
                {"tooling_conditions": task["tooling_conditions"]}
                if task.get("tooling_conditions")
                else {}
            ),
            **(
                {"material_conditions": task["material_conditions"]}
                if task.get("material_conditions")
                else {}
            ),
        }
    complete = all(row["finish"] is not None for row in results.values())
    float_status = (
        "unknown_schedule"
        if not complete
        else "actual_constraint_conflict"
        if any(row["warnings"] for row in results.values())
        else "calculated"
    )
    for row in results.values():
        row.update(
            latest_start=None,
            latest_finish=None,
            total_float_minutes=None,
            working_float_minutes=None,
            remaining_work_float_minutes=None,
            float_dimension=None,
            critical=None,
        )
    deadline = max(row["finish"] for row in results.values()) if complete else None
    if resource_placer is not None:
        float_status = "resource_constrained_not_calculated"
    if float_status == "calculated":
        assert deadline is not None
        for key in reversed(order):
            row = results[key]
            if row["actual_finish"] is not None:
                row.update(
                    latest_start=row["actual_start"],
                    latest_finish=row["actual_finish"],
                    float_dimension="actual_fixed",
                )
                continue
            profile = residuals[key]
            engine = engines[allocations[key].calendar_key]
            earliest_work = profile["work_start"]

            def shifted(
                minutes: int,
                earliest_work: datetime = earliest_work,
                profile: dict[str, Any] = profile,
                engine: WorkingTime = engine,
                row: dict[str, Any] = row,
            ) -> tuple[datetime, datetime, datetime]:
                work = earliest_work + timedelta(minutes=minutes)
                if profile["duration"]:
                    work = engine.snap(work)
                predicted_finish = engine.advance(work, profile["duration"]) + timedelta(
                    days=profile["waiting"]
                )
                if profile["finish_floor"]:
                    predicted_finish = max(predicted_finish, profile["finish_floor"])
                return row["actual_start"] or work, predicted_finish, work

            def feasible(minutes: int, key: str = key) -> bool:
                candidate_start, candidate_finish, _ = shifted(minutes)
                if candidate_finish > deadline:
                    return False
                for edge in outgoing[key]:
                    successor = results[edge.successor]
                    target = successor[
                        "latest_start" if edge.relation[1] == "s" else "latest_finish"
                    ]
                    if (
                        target is None
                        or lagged(
                            edge, candidate_start if edge.relation[0] == "s" else candidate_finish
                        )
                        > target
                    ):
                        return False
                return True

            if not feasible(0):
                float_status = "actual_constraint_conflict"
                break
            low = 0
            high = max(0, int((deadline - earliest_work).total_seconds() // 60))
            while low < high:
                middle = (low + high + 1) // 2
                if feasible(middle):
                    low = middle
                else:
                    high = middle - 1
            latest_start, latest_finish, latest_work = shifted(low)
            dimension = "remaining_finish" if row["actual_start"] else "start"
            slack = int(
                (
                    (latest_finish - row["finish"])
                    if row["actual_start"]
                    else (latest_start - row["start"])
                ).total_seconds()
                // 60
            )
            row.update(
                latest_start=latest_start,
                latest_finish=latest_finish,
                total_float_minutes=slack,
                working_float_minutes=engine.working_minutes(earliest_work, latest_work),
                remaining_work_float_minutes=int(
                    (latest_work - earliest_work).total_seconds() // 60
                ),
                float_dimension=dimension,
                critical=slack == 0,
            )
    if float_status != "calculated":
        for row in results.values():
            row.update(
                latest_start=None,
                latest_finish=None,
                total_float_minutes=None,
                working_float_minutes=None,
                remaining_work_float_minutes=None,
                float_dimension=None,
                critical=None,
            )
    critical_edges = []
    if float_status == "calculated":
        for edge in plan.dependencies:
            predecessor = results[edge.predecessor]
            successor = results[edge.successor]
            left = predecessor["start" if edge.relation[0] == "s" else "finish"]
            right = successor["start" if edge.relation[1] == "s" else "finish"]
            if predecessor["critical"] and successor["critical"]:
                margin = (right - lagged(edge, left)).total_seconds()
                if 0 <= margin < 60:
                    critical_edges.append(
                        {**edge.model_dump(mode="json"), "constraint_margin_seconds": margin}
                    )
    return {
        "float_status": float_status,
        "float_reference": "current_project_forecast_finish",
        "external_dependencies": external_dependencies,
        "critical_node_keys": [key for key in order if results[key]["critical"]],
        "critical_edges": critical_edges,
        "algorithm_version": TOOLING_ALGORITHM_VERSION
        if any(task.get("tooling_conditions") for task in tasks.values())
        else MATERIAL_ALGORITHM_VERSION
        if any(task.get("material_conditions") for task in tasks.values())
        else ALGORITHM_VERSION,
        "as_of": as_of.isoformat(),
        "complete": complete,
        "project_finish": max(row["finish"] for row in results.values()).isoformat()
        if complete
        else None,
        "capacity_status": "not_rechecked",
        "calendars": {
            key: {
                **asdict(engine.evidence),
                "calendar_id": str(engine.evidence.calendar_id),
                "definition": calendars[key].model_dump(mode="json"),
            }
            for key, engine in engines.items()
        },
        "nodes": [
            {
                "node_key": key,
                **{
                    name: value.isoformat() if isinstance(value, datetime) else value
                    for name, value in results[key].items()
                },
            }
            for key in order
        ],
    }
