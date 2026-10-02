"""The follow-up forecast must preserve buffers and isolate unrelated work."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

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


def test_delay_uses_calendar_and_buffer_without_shifting_unrelated_tasks() -> None:
    tenant, owner = uuid4(), uuid4()
    start = datetime(2026, 10, 2, 9, tzinfo=UTC)  # Friday; Monday is a holiday.
    plan = PlanCandidate(
        id=uuid4(),
        tenant_id=tenant,
        scope=ScopeRef(kind="tenant", ref_id=tenant),
        version=1,
        owner_user_id=owner,
        template_version="pai-check.v1",
        nodes=tuple(
            PlanNode(
                node_key=k,
                title=k,
                discipline="ME",
                owner_user_id=owner,
                receiver_user_id=owner,
                expected_output="checked",
                completion_criteria="evidence",
                effort_hours=Decimal(8),
                estimate_basis="approved estimate",
            )
            for k in ("A", "B", "C")
        ),
        dependencies=(
            PlanDependency(
                predecessor="A",
                successor="B",
                relation="fs",
                lag=Decimal(0),
                lag_unit="working_hours",
            ),
        ),
    )
    calendar = CalendarDefinition(
        calendar=WorkCalendar(
            id=uuid4(),
            tenant_id=tenant,
            version=1,
            timezone="UTC",
            working_weekdays=(0, 1, 2, 3, 4),
            holidays=(date(2026, 10, 5),),
            hours_per_workday=Decimal(8),
        ),
        intervals=(WorkInterval(start_minute=540, end_minute=1020),),
    )
    allocations = {
        k: NodeAllocation(
            calendar_key="work",
            parallel_units=Decimal(1),
            allocation_basis="approved",
            not_before=datetime(2026, 10, 7, 9, tzinfo=UTC) if k == "B" else None,
        )
        for k in ("A", "B", "C")
    }
    tasks = {
        k: {
            "node_id": str(uuid4()),
            "status": "in_progress" if k == "A" else "todo",
            "actual_start": start.isoformat() if k == "A" else None,
            "actual_finish": None,
        }
        for k in ("A", "B", "C")
    }

    def calculate(hours: str | None):
        return calculate_forecast(
            plan,
            start,
            {"work": calendar},
            allocations,
            tasks,
            {
                "A": {
                    "remaining_hours": hours,
                    "remaining_waiting_days": 0,
                    "not_before": None,
                    "basis": "owner estimate",
                }
            },
        )

    buffered = calculate("16")
    nodes = {n["node_key"]: n for n in buffered["nodes"]}
    assert buffered["complete"]
    assert nodes["A"]["finish"] == "2026-10-06T17:00:00+00:00"
    assert nodes["B"]["start"] == "2026-10-07T09:00:00+00:00"
    delayed = calculate("24")
    later = {n["node_key"]: n for n in delayed["nodes"]}
    assert later["B"]["start"] == "2026-10-08T09:00:00+00:00"
    assert later["C"]["start"] == nodes["C"]["start"]
    assert later["C"]["finish"] == nodes["C"]["finish"]
    unknown = calculate(None)
    assert not unknown["complete"]
    assert next(n for n in unknown["nodes"] if n["node_key"] == "B")["finish"] is None
