"""Deterministic contract scenarios using synthetic facts and no database."""

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from app.contracts.common_objects import (
    PlanCandidate,
    PlanDependency,
    PlanNode,
    ScopeRef,
    WorkCalendar,
)
from app.domain.plan_scheduling import NodeAllocation
from app.domain.schedule_forecast_engine import calculate_forecast
from app.domain.working_time import CalendarDefinition, WorkInterval

START = datetime(2026, 10, 1, tzinfo=UTC)


def inputs() -> tuple[
    PlanCandidate, CalendarDefinition, dict[str, NodeAllocation], dict[str, dict[str, Any]]
]:
    tenant, owner = uuid4(), uuid4()
    plan = PlanCandidate(
        id=uuid4(),
        tenant_id=tenant,
        scope=ScopeRef(kind="project", ref_id=uuid4()),
        version=1,
        owner_user_id=owner,
        template_version="synthetic.at06.v1",
        nodes=tuple(
            PlanNode(
                node_key=key,
                title=key,
                discipline="ME",
                owner_user_id=owner,
                receiver_user_id=owner,
                expected_output="evidence",
                completion_criteria="accepted",
                effort_hours=Decimal(0),
                waiting_days=1,
                estimate_basis="synthetic contract input",
            )
            for key in "ABCD"
        ),
        dependencies=tuple(
            PlanDependency(
                predecessor="A",
                successor=key,
                relation="fs",
                lag=Decimal(0),
                lag_unit="calendar_days",
            )
            for key in "BC"
        ),
    )
    calendar = CalendarDefinition(
        calendar=WorkCalendar(
            id=uuid4(),
            tenant_id=tenant,
            version=1,
            timezone="UTC",
            working_weekdays=tuple(range(7)),
            holidays=(),
            hours_per_workday=Decimal(24),
        ),
        intervals=(WorkInterval(start_minute=0, end_minute=1440),),
    )
    allocations = {
        key: NodeAllocation(
            calendar_key="site",
            parallel_units=Decimal(1),
            allocation_basis="synthetic",
            not_before=START + timedelta(days=4 if key == "B" else 10) if key in "BC" else None,
        )
        for key in "ABCD"
    }
    tasks = {
        key: {
            "node_id": str(uuid4()),
            "status": "todo",
            "actual_start": None,
            "actual_finish": None,
        }
        for key in "ABCD"
    }
    return plan, calendar, allocations, tasks


def nodes(result: dict[str, Any]) -> dict[str, Any]:
    return {node["node_key"]: node for node in result["nodes"]}


def test_at06_a_six_days_b_three_days_c_absorbs_delay_without_rewriting_inputs() -> None:
    plan, calendar, allocations, tasks = inputs()
    frozen = (plan.model_dump_json(), deepcopy(allocations), deepcopy(tasks))
    baseline = calculate_forecast(plan, START, {"site": calendar}, allocations, tasks, {})
    estimates = {
        "A": {
            "remaining_hours": "0",
            "remaining_waiting_days": 7,
            "not_before": None,
            "basis": "synthetic six-day delay",
        }
    }
    forecast = calculate_forecast(plan, START, {"site": calendar}, allocations, tasks, estimates)
    original, changed = nodes(baseline), nodes(forecast)
    for key, days in (("A", 6), ("B", 3), ("C", 0), ("D", 0)):
        assert datetime.fromisoformat(changed[key]["finish"]) - datetime.fromisoformat(
            original[key]["finish"]
        ) == timedelta(days=days)
    assert forecast == calculate_forecast(
        plan, START, {"site": calendar}, allocations, tasks, estimates
    )
    assert frozen == (plan.model_dump_json(), allocations, tasks)
    assert changed["C"]["total_float_minutes"] == original["C"]["total_float_minutes"]
    assert forecast["capacity_status"] == "not_rechecked"


def test_unknown_predecessor_blocks_only_reachable_work_and_cannot_claim_a_date() -> None:
    plan, calendar, allocations, tasks = inputs()
    forecast = calculate_forecast(
        plan,
        START,
        {"site": calendar},
        allocations,
        tasks,
        {
            "A": {"remaining_hours": None, "remaining_waiting_days": 1, "basis": "unknown"},
        },
    )
    result = nodes(forecast)
    assert not forecast["complete"] and forecast["project_finish"] is None
    for key in "ABC":
        assert result[key]["finish"] is None and result[key]["unknown_reasons"]
    assert result["D"]["finish"] == (START + timedelta(days=1)).isoformat()


def test_long_running_test_requires_remaining_estimate_then_keeps_actual_feedback() -> None:
    plan, calendar, allocations, tasks = inputs()
    tasks["A"].update(status="in_progress", node_kind="test_run", actual_start=START.isoformat())
    unknown = calculate_forecast(plan, START, {"site": calendar}, allocations, tasks, {})
    assert nodes(unknown)["A"]["finish"] is None
    estimates = {
        "A": {
            "remaining_hours": "0",
            "remaining_waiting_days": 7,
            "not_before": None,
            "basis": "operator ETA",
        }
    }
    predicted = calculate_forecast(plan, START, {"site": calendar}, allocations, tasks, estimates)
    actual = START + timedelta(days=8)
    tasks["A"].update(status="done", actual_finish=actual.isoformat())
    feedback = calculate_forecast(plan, actual, {"site": calendar}, allocations, tasks, estimates)
    assert nodes(feedback)["A"]["origin"] == "actual"
    assert nodes(feedback)["A"]["finish"] == actual.isoformat()
    assert nodes(feedback)["A"]["start"] == START.isoformat()
    assert nodes(predicted)["A"]["finish"] == (START + timedelta(days=7)).isoformat()


def test_execution_cycle_fails_closed_even_for_unvalidated_legacy_input() -> None:
    plan, calendar, allocations, tasks = inputs()
    plan = plan.model_copy(
        update={
            "dependencies": (
                *plan.dependencies,
                PlanDependency(
                    predecessor="B",
                    successor="A",
                    relation="fs",
                    lag=Decimal(0),
                    lag_unit="working_hours",
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="循环"):
        calculate_forecast(plan, START, {"site": calendar}, allocations, tasks, {})


def test_cross_site_dst_and_certification_window_are_deterministic_constraints() -> None:
    plan, calendar, allocations, tasks = inputs()
    start = datetime(2026, 10, 30, 16, tzinfo=UTC)  # Friday 09:00 in Los Angeles.
    plan = plan.model_copy(
        update={
            "nodes": tuple(
                node.model_copy(
                    update={
                        "effort_hours": Decimal(8),
                        "waiting_days": 0,
                    }
                )
                for node in plan.nodes
            )
        }
    )
    la = calendar.model_copy(
        update={
            "calendar": calendar.calendar.model_copy(
                update={
                    "timezone": "America/Los_Angeles",
                    "working_weekdays": (0, 1, 2, 3, 4),
                    "hours_per_workday": Decimal(8),
                    "holidays": (),
                }
            ),
            "intervals": (WorkInterval(start_minute=540, end_minute=1020),),
        }
    )
    shanghai = la.model_copy(
        update={
            "calendar": la.calendar.model_copy(
                update={
                    "id": uuid4(),
                    "timezone": "Asia/Shanghai",
                    "holidays": (date(2026, 11, 2),),
                }
            )
        }
    )
    allocations = {
        key: value.model_copy(
            update={
                "calendar_key": "la" if key in "AD" else "shanghai",
                "not_before": datetime(2026, 11, 4, 1, tzinfo=UTC) if key == "C" else None,
            }
        )
        for key, value in allocations.items()
    }
    tasks["A"].update(status="in_progress", actual_start=start.isoformat())
    estimates = {
        "A": {"remaining_hours": "16", "remaining_waiting_days": 0, "basis": "two working days"}
    }
    result = nodes(
        calculate_forecast(
            plan,
            start,
            {"la": la, "shanghai": shanghai},
            allocations,
            tasks,
            estimates,
        )
    )
    assert result["A"]["finish"] == "2026-11-03T01:00:00+00:00"
    assert result["B"]["start"] == "2026-11-03T01:00:00+00:00"
    assert result["C"]["start"] == "2026-11-04T01:00:00+00:00"
    assert result["D"]["finish"] == "2026-10-31T00:00:00+00:00"
