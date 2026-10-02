"""Pure feedback rules; synthetic inputs are not real business evidence."""

from copy import deepcopy
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest

from app.domain.resource_priorities import PREFIX
from app.domain.schedule_forecast_engine import calculate_forecast
from app.domain.schedule_network import project_sources, qualify_estimates, timing_state
from app.domain.schedule_resource_feedback import reservation_conditions
from tests.test_schedule_forecast_engine import START, inputs, nodes


def condition(**patch: Any) -> dict[str, Any]:
    return {
        "reservation_id": "r",
        "resource_id": "bench",
        "resource_name": "bench",
        "window_start": (START + timedelta(days=7)).isoformat(),
        "window_end": (START + timedelta(days=8)).isoformat(),
        "policy_status": "active",
        "policy_valid_from": (START - timedelta(days=1)).isoformat(),
        "policy_valid_until": (START + timedelta(days=30)).isoformat(),
        "blockers": [],
        **patch,
    }


def test_actual_reservation_moves_forecast_even_when_estimate_has_earlier_not_before() -> None:
    plan, calendar, allocations, tasks = inputs()
    tasks["A"]["resource_conditions"] = [condition()]
    frozen = deepcopy((tasks, allocations))
    result = calculate_forecast(
        plan,
        START,
        {"site": calendar},
        allocations,
        tasks,
        {
            "A": {
                "remaining_hours": "0",
                "remaining_waiting_days": 1,
                "not_before": START.isoformat(),
                "basis": "named estimate",
            },
        },
    )
    assert nodes(result)["A"]["start"] == (START + timedelta(days=7)).isoformat()
    assert nodes(result)["B"]["start"] == (START + timedelta(days=8)).isoformat()
    assert result["capacity_status"] == "not_rechecked"
    assert (tasks, allocations) == frozen


@pytest.mark.parametrize(
    "patch",
    [
        {"blockers": ["预约容量版本已变化"]},
        {"policy_status": "suspended"},
        {"policy_valid_until": START.isoformat()},
        {"window_end": START.isoformat()},
    ],
)
def test_invalid_reservation_inputs_do_not_invent_finish(patch: dict[str, Any]) -> None:
    plan, calendar, allocations, tasks = inputs()
    tasks["A"]["resource_conditions"] = [condition(**patch)]
    result = calculate_forecast(plan, START, {"site": calendar}, allocations, tasks, {})
    assert nodes(result)["A"]["finish"] is None
    assert nodes(result)["B"]["finish"] is None
    assert nodes(result)["D"]["finish"] is not None
    assert result["project_finish"] is None


@pytest.mark.parametrize("expired", [False, True])
def test_in_progress_long_test_uses_actual_source_expected_end_without_fabricating_effort(
    expired: bool,
) -> None:
    plan, calendar, allocations, tasks = inputs()
    expected = START + timedelta(days=-1 if expired else 5)
    tasks["A"].update(
        node_kind="test_run",
        source_status="in_progress",
        status="in_progress",
        actual_start=(START - timedelta(days=2)).isoformat(),
        expected_completion_at=expected.isoformat(),
    )
    result = calculate_forecast(plan, START, {"site": calendar}, allocations, tasks, {})
    row = nodes(result)["A"]
    assert row["finish"] == (None if expired else expected.isoformat())
    assert row["actual_finish"] is None and row["remaining_work_minutes"] is None
    assert row["origin"] == "business_expected_completion"
    assert not result["complete"] if expired else result["complete"]


def test_ended_long_test_preserves_actual_even_if_expected_time_or_policy_is_stale() -> None:
    plan, calendar, allocations, tasks = inputs()
    finished = START - timedelta(hours=1)
    tasks["A"].update(
        node_kind="test_run",
        source_status="passed",
        status="done",
        actual_start=(START - timedelta(days=2)).isoformat(),
        actual_finish=finished.isoformat(),
        expected_completion_at=START.isoformat(),
        resource_conditions=[condition(policy_status="suspended")],
    )
    row = nodes(calculate_forecast(plan, START, {"site": calendar}, allocations, tasks, {}))["A"]
    assert row["finish"] == finished.isoformat() and row["origin"] == "actual"
    assert row["unknown_reasons"] == []


def test_remaining_estimates_survive_other_nodes_and_resource_changes_but_not_own_progress() -> (
    None
):
    basis: dict[str, Any] = {
        "baseline_id": "b",
        "baseline_version": 1,
        "plan": {"nodes": []},
        "allocations": {},
        "calendars": {},
        "tasks": [
            {"node_key": "A", "status": "todo"},
            {"node_key": "B", "status": "todo"},
        ],
    }
    original = {
        "basis": deepcopy(basis),
        "estimates": {"A": {"basis": "named"}, "B": {"basis": "named"}},
    }
    basis["tasks"][1]["status"] = "in_progress"
    basis["tasks"][0]["resource_conditions"] = [condition()]
    assert qualify_estimates(original, basis) == {"A": {"basis": "named"}}
    basis["test_expectation_validity"] = {"test-node": False}
    assert qualify_estimates(original, basis) == {"A": {"basis": "named"}}
    basis["tasks"][0]["actual_start_event"] = 55
    assert qualify_estimates(original, basis) == {}
    assert qualify_estimates({**original, "estimates": {}}, original["basis"]) == {}


def test_appointment_drift_and_release_are_explicit_inputs() -> None:
    row = {
        "id": "r",
        "node_id": "n",
        "resource_id": "bench",
        "capacity_version_id": "c",
        "version": 2,
        "state": "reserved",
        "window_start": START.isoformat(),
        "window_end": (START + timedelta(days=1)).isoformat(),
        "contract": {"priority_policy_version": PREFIX + "p"},
    }
    values = reservation_conditions(
        [row],
        {"bench": {"name": "bench"}},
        {"bench": {"id": "new"}},
        {
            "bench": {
                "id": "p",
                "status": "active",
                "current": False,
                "valid_from": START.isoformat(),
                "valid_until": START.isoformat(),
            }
        },
        node_id="n",
    )
    assert values[0]["blockers"] == ["预约容量版本已变化", "预约优先级已暂停或过期"]
    assert reservation_conditions([{**row, "state": "released"}], {}, {}, {}, node_id="n")[0][
        "blockers"
    ]


@pytest.mark.parametrize("source", ["resource", "expired_resource", "long_test", "material"])
def test_cross_project_timing_uses_current_source_constraints_without_exposing_details(
    source: str,
) -> None:
    plan, calendar, allocations, tasks = inputs()
    ids = {key: "n:" + tasks[key]["node_id"].replace("-", "") for key in "AB"}
    upstream = {**tasks["A"], "node_kind": "task"}
    expected = START + timedelta(days=5)
    if source in ("resource", "expired_resource"):
        upstream["resource_conditions"] = [
            condition(
                resource_name="Private partner bench",
                blockers=["Private policy evidence"] if source == "expired_resource" else [],
            )
        ]
        expected = START + timedelta(days=8)
    elif source == "long_test":
        upstream.update(
            node_kind="test_run",
            status="in_progress",
            source_status="in_progress",
            actual_start=(START - timedelta(days=2)).isoformat(),
            expected_completion_at=expected.isoformat(),
        )
    else:
        upstream["material_conditions"] = [
            {
                "exception_id": "Private partner supplier",
                "target_point": "start",
                "status": "estimate",
                "ready_at": (START + timedelta(days=4)).isoformat(),
            }
        ]
    network: dict[str, Any] = {
        "root_keys": {ids["B"]: "B"},
        "nodes": {
            ids[key]: {**node.model_dump(mode="json"), "node_key": ids[key]}
            for node in plan.nodes
            if (key := node.node_key) in ids
        },
        "states": {
            ids["A"]: timing_state(upstream, ids["A"]),
            ids["B"]: timing_state({**tasks["B"], "node_kind": "task"}, ids["B"]),
        },
        "allocations": {
            ids[key]: {
                **allocations[key].model_dump(mode="json"),
                "calendar_version_id": "site",
            }
            for key in "AB"
        },
        "calendars": {"site": calendar.model_dump(mode="json")},
        "estimates": {},
        "edges": [
            {
                "predecessor": ids["A"],
                "successor": ids["B"],
                "relation": "fs",
                "lag": "0",
                "lag_unit": "calendar_days",
            }
        ],
        "shared": [
            {
                "application_id": str(uuid4()),
                "predecessor_node_id": tasks["A"]["node_id"],
                "is_current": True,
                "source_point": "finish",
            }
        ],
    }
    result = project_sources(network, {"plan": plan.model_dump(mode="json")}, START, {})
    assert result[0]["anchor"] == (None if source == "expired_resource" else expected.isoformat())
    assert "Private" not in str(network) and "Private" not in str(result)
