"""Test-plan questions persist, release resources and resume through real application APIs."""

from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

import httpx2
import pytest
from sqlalchemy import RowMapping, Table, select, text

from app.db.engine import get_engine
from app.db.schema import tables
from tests.test_ai_test_plan_changes import READY, get_finding, suggest
from tests.test_ai_test_plan_changes import scenario as scenario
from tests.test_application_run_budget_api import PlanScenario, factory
from tests.test_test_report_import_api import isolated_import_database as isolated_import_database

WaitingPlan = tuple[
    PlanScenario,
    dict[str, object],
    list[httpx2.Request],
    list[dict[str, object]],
    dict[str, object],
    str,
    dict[str, str],
]


def rows(table: Table) -> list[RowMapping]:
    with get_engine().connect() as c:
        return list(c.execute(select(table)).mappings())


@pytest.fixture
def waiting_plan(
    scenario: PlanScenario,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> WaitingPlan:
    output: dict[str, object] = {
        **deepcopy(READY),
        "questions": ["请确认本次测试的判定条件。"],
        "changes": [
            {
                **{k: v for k, v in item.items() if k != "references"},
                "reference_ids": [r["reference_id"] for r in item["references"]],
            }
            for item in deepcopy(READY["changes"])
        ],
    }
    environment, calls, snapshots = factory(
        get_engine(), tmp_path, monkeypatch, request=request, output=output
    )
    request_id = str(uuid4())
    finding = get_finding(scenario, suggest(scenario, request_id=request_id))
    return scenario, output, calls, snapshots, finding, request_id, environment


def test_wait_is_durable_queryable_and_releases_execution(waiting_plan: WaitingPlan) -> None:
    scenario, _, calls, _, finding, request_id, _ = waiting_plan
    client, _, _, headers, _, plan = scenario
    run = rows(tables.agent_runs)[0]
    wait = rows(tables.application_input_waits)[0]
    assert run["status"] == "waiting_input" and run["completed_at"] is None
    finding_id = finding["id"]
    assert isinstance(finding_id, str)
    assert wait["finding_id"] == UUID(finding_id) and wait["resolved_at"] is None
    assert wait["checkpoint_id"] == rows(tables.application_result_checkpoints)[0]["id"]
    assert rows(tables.application_run_leases)[0]["stop_reason"] == "waiting_input"
    assert all(r["ended_at"] is not None for r in rows(tables.application_run_leases))
    assert all(r["stopped_at"] is not None for r in rows(tables.budget_activity_spans))
    response = client.get(f"/api/ai/projects/{plan['project_id']}/runs", headers=headers)
    assert response.status_code == 200, response.text
    displayed = next(r for r in response.json()["items"] if r["id"] == str(run["id"]))
    assert displayed["input_wait"]["questions"] == wait["body"]["questions"]
    assert displayed["status"] == "waiting_input"
    assert suggest(scenario, request_id=request_id).json()["finding_id"] == finding["id"]
    assert len(calls) == 1 and len(rows(tables.application_input_waits)) == 1


def test_input_continues_with_original_lineage_and_closes_wait(waiting_plan: WaitingPlan) -> None:
    scenario, output, calls, _, finding, _, _ = waiting_plan
    original_budget = rows(tables.budget_lineages)
    parent = rows(tables.agent_runs)[0]["id"]
    output["questions"] = []
    next_finding = get_finding(scenario, suggest(scenario, previous_finding_id=finding["id"]))
    wait = rows(tables.application_input_waits)[0]
    assert wait["resolution"] == "input_received" and wait["resolved_at"] is not None
    by_id = {r["id"]: r for r in rows(tables.agent_runs)}
    assert by_id[parent]["status"] == "succeeded"
    assert by_id[wait["continuation_run_id"]]["status"] == "succeeded"
    assert next_finding["run_id"] == str(wait["continuation_run_id"])
    assert rows(tables.budget_lineages) == original_budget and len(calls) == 2
    assert len({r["lineage_id"] for r in rows(tables.budget_run_links)}) == 1
    assert all(r["ended_at"] is not None for r in rows(tables.application_run_leases))
    assert suggest(scenario, previous_finding_id=finding["id"]).status_code == 409
    assert len(calls) == 2


@pytest.mark.parametrize("decision", ["accepted", "rejected"])
def test_human_review_resolves_wait_without_model_or_business_apply(
    waiting_plan: WaitingPlan, decision: str
) -> None:
    scenario, _, calls, _, finding, _, _ = waiting_plan
    client, _, _, headers, _, _ = scenario
    body: dict[str, object] = {"decision": decision, "comment": "按当前测试要求审阅"}
    if decision == "accepted":
        edited = deepcopy(finding["proposed_payload"])
        assert isinstance(edited, dict)
        edited["questions"] = []
        body["edited_payload"] = edited
    response = client.post(f"/api/ai/findings/{finding['id']}/review", headers=headers, json=body)
    assert response.status_code == 200, response.text
    wait = rows(tables.application_input_waits)[0]
    assert wait["resolution"] == f"finding_{decision}"
    assert wait["continuation_run_id"] is None
    assert rows(tables.agent_runs)[0]["status"] == "succeeded"
    assert rows(tables.findings)[0]["applied_at"] is None and len(calls) == 1


def test_supervisor_expires_wait_without_inventing_execution(waiting_plan: WaitingPlan) -> None:
    scenario, _, calls, _, finding, _, _ = waiting_plan
    # Move only this synthetic test's wait clock into the past. Transactional DDL
    # restores the history trigger before the expiry function is exercised.
    with get_engine().begin() as c:
        c.execute(
            text(
                "ALTER TABLE cehub_ai.application_input_waits "
                "DISABLE TRIGGER protect_application_input_wait"
            )
        )
        c.execute(
            text(
                "UPDATE cehub_ai.application_input_waits "
                "SET created_at=clock_timestamp()-interval '2 seconds', "
                "expires_at=clock_timestamp()-interval '1 second'"
            )
        )
        c.execute(
            text(
                "ALTER TABLE cehub_ai.application_input_waits "
                "ENABLE TRIGGER protect_application_input_wait"
            )
        )
        assert c.execute(text("SELECT cehub_ai.expire_application_runs(100)")).scalar_one() == 1
        assert c.execute(text("SELECT cehub_ai.expire_application_runs(100)")).scalar_one() == 0
    assert rows(tables.application_input_waits)[0]["resolution"] == "expired"
    assert rows(tables.agent_runs)[0]["error_code"] == "APPLICATION_INPUT_WAIT_EXPIRED"
    assert suggest(scenario, previous_finding_id=finding["id"]).status_code == 409
    assert len(calls) == 1 and len(rows(tables.agent_runs)) == 1
