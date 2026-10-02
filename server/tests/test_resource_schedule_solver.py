"""Real interval solver with synthetic source capture; no database is opened."""

from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import Connection

from app.contracts.common_objects import WorkCalendar
from app.domain import resource_schedule_solver as module
from app.domain.product_workspace import _plain
from app.domain.resource_capacity import CapacityCheckDraft, Demand
from app.domain.working_time import CalendarDefinition, WorkingTime, WorkInterval
from tests.test_resource_reallocations import context

NOW = datetime(2026, 10, 1, 9, tzinfo=UTC)


def solver(
    monkeypatch: pytest.MonkeyPatch,
    *,
    state: str = "active",
    occupied: list[dict[str, Any]] | None = None,
    units: Decimal = Decimal(1),
    horizon: int = 10,
) -> tuple[module.ResourceSolver, WorkingTime]:
    caller, resource, capacity = context(), uuid4(), uuid4()
    definition = CalendarDefinition(
        calendar=WorkCalendar(
            id=uuid4(),
            tenant_id=caller.tenant.id,
            version=1,
            timezone="UTC",
            working_weekdays=tuple(range(7)),
            holidays=(),
            hours_per_workday=Decimal(8),
        ),
        intervals=(WorkInterval(start_minute=540, end_minute=1020),),
    )
    engine = WorkingTime(definition)
    profile = {
        "id": capacity,
        "resource_id": resource,
        "resource_name": "shared bench",
        "parallel_units": Decimal(1),
        "window_start": NOW,
        "window_end": NOW + timedelta(days=30),
        "is_current": True,
        "person_active": True,
        "calendar_definition": definition.model_dump(mode="json"),
        "calendar_evidence": _plain(asdict(engine.evidence)),
    }
    bookings = [{**item, "resource_id": str(resource)} for item in (occupied or [])]
    monkeypatch.setattr(
        module,
        "capacity_sources",
        lambda *args, **kwargs: (
            {capacity: profile},
            bookings,
            set(),
        ),
    )
    policy = (
        None
        if state == "missing"
        else {
            "id": uuid4(),
            "version": 1,
            "status": "suspended" if state == "suspended" else "active",
            "valid_from": NOW + timedelta(days=1) if state == "future" else NOW - timedelta(days=1),
            "valid_until": NOW if state == "expired" else NOW + timedelta(days=30),
            "body": {"default_rank": 1, "ranks": []},
        }
    )
    monkeypatch.setattr(module, "latest", lambda *args: policy)
    connection = MagicMock(spec=Connection)
    connection.execute.return_value.scalar_one.return_value = NOW
    connection.execute.return_value.mappings.return_value = []
    draft = CapacityCheckDraft(
        request_id=uuid4(),
        demands={
            "A": (
                Demand(
                    capacity_version_id=capacity,
                    units=units,
                    contributes_effort=True,
                    occupancy_policy="working_only",
                    basis="synthetic capacity requirement",
                ),
            )
        },
    )
    scenario = {
        "id": uuid4(),
        "result_digest": "a" * 64,
        "result": {
            "nodes": [
                {
                    "node_id": str(uuid4()),
                    "node_key": "A",
                    "actual_finish": None,
                    "allocation": {"calendar_key": "site", "parallel_units": str(units)},
                }
            ]
        },
    }
    return module.ResourceSolver(
        connection,
        caller,
        uuid4(),
        scenario,
        draft,
        NOW,
        horizon,
    ), engine


@pytest.mark.parametrize("policy_state", ["missing", "suspended", "future", "expired"])
def test_invalid_priority_refuses_dates_without_calling_a_model(
    monkeypatch: pytest.MonkeyPatch,
    policy_state: str,
) -> None:
    target, calendar = solver(monkeypatch, state=policy_state)
    start, finish, reasons = target.place("A", calendar, NOW, 480, 0, None)
    assert start is finish is None
    assert reasons and "优先级" in reasons[0]
    assert target.attempts == 0 and target.evidence()["optimality_proven"] is False


def test_two_projects_share_bench_by_queueing_without_moving_confirmed_booking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    occupied = [
        {"start": NOW.isoformat(), "end": (NOW + timedelta(hours=8)).isoformat(), "units": "1"}
    ]
    target, calendar = solver(monkeypatch, occupied=occupied)
    original = deepcopy(target.original)
    start, finish, reasons = target.place("A", calendar, NOW, 480, 0, None)
    assert reasons == []
    assert start == NOW + timedelta(days=1)
    assert finish == NOW + timedelta(days=1, hours=8)
    assert target.original == original
    assert target.decisions[0]["delays"][0]["demand_units"] == "2"
    assert target.decisions[0]["delays"][0]["available_units"] == "1"


def test_same_node_existing_coverage_is_not_counted_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    occupied = [
        {
            "start": NOW.isoformat(),
            "end": (NOW + timedelta(hours=8)).isoformat(),
            "units": "1",
            "covered_node_key": "A",
        }
    ]
    target, calendar = solver(monkeypatch, occupied=occupied)
    assert target.place("A", calendar, NOW, 480, 0, None) == (
        NOW,
        NOW + timedelta(hours=8),
        [],
    )
    assert sum(Decimal(row["units"]) for row in target.occupied) == Decimal(1)


def test_released_booking_restores_window_but_unresolvable_horizon_has_no_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    occupied = [
        {"start": NOW.isoformat(), "end": (NOW + timedelta(days=20)).isoformat(), "units": "1"}
    ]
    blocked, calendar = solver(monkeypatch, occupied=occupied, horizon=3)
    start, finish, reasons = blocked.place("A", calendar, NOW, 480, 0, None)
    assert start is finish is None and reasons
    assert "范围" in reasons[0]
    assert blocked.evidence()["optimality_proven"] is False
    restored, calendar = solver(monkeypatch, horizon=3)
    assert restored.place("A", calendar, NOW, 480, 0, None) == (
        NOW,
        NOW + timedelta(hours=8),
        [],
    )


def test_units_above_declared_capacity_refuses_solution_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, calendar = solver(monkeypatch, units=Decimal(2))
    start, finish, reasons = target.place("A", calendar, NOW, 480, 0, None)
    assert start is finish is None and "最大容量" in reasons[0]
    assert target.attempts == 0
