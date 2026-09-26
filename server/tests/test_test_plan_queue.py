"""Queued conversations, durable questions and original-budget follow-up."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import text

from app.ai.application_gateway import configured_application_gateway
from app.ai.gateway import GatewayInvocation, GatewayResult, StructuredModelGateway
from app.ai.test_plan_queue import TestPlanQueue
from app.db.engine import get_engine
from app.db.schema import tables
from tests.test_ai_test_plan_changes import MESSAGE, READY
from tests.test_ai_test_plan_changes import scenario as scenario
from tests.test_application_leases import expire
from tests.test_application_run_budget_api import PlanScenario, factory
from tests.test_application_waits import rows
from tests.test_model_budget_controller import evidence
from tests.test_test_report_import_api import isolated_import_database as isolated_import_database

QueuedPlan = tuple[
    TestClient,
    dict[str, str],
    str,
    dict[str, str],
    list[httpx2.Request],
    dict[str, object],
    dict[str, object],
]


@pytest.fixture
def queued_plan(
    scenario: PlanScenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> QueuedPlan:
    output: dict[str, object] = {
        **deepcopy(READY),
        "questions": ["请补充判定条件。"],
        "changes": [
            {
                **{k: v for k, v in item.items() if k != "references"},
                "reference_ids": [r["reference_id"] for r in item["references"]],
            }
            for item in deepcopy(READY["changes"])
        ],
    }
    original = StructuredModelGateway.invoke_structured
    env, calls, _ = factory(get_engine(), tmp_path, monkeypatch, output=output)
    monkeypatch.setattr(StructuredModelGateway, "invoke_structured", original)
    client, _, _, headers, path, plan = scenario
    url = f"{path}/test-plans/{plan['id']}/suggestion-requests"
    return client, headers, url, env, calls, output, plan


def submit(q: QueuedPlan, *, previous: str | None = None) -> dict[str, object]:
    client, headers, url, _, _, _, _ = q
    body = dict(message=MESSAGE, request_id=str(uuid4()), previous_finding_id=previous)
    response = client.post(url, headers=headers, json=body)
    assert response.status_code == 202 and response.json()["status"] == "queued", response.text
    assert client.post(url, headers=headers, json=body).json() == response.json()
    return evidence(response.json())


def work(env: dict[str, str]) -> None:
    with configured_application_gateway(get_engine(), env) as gateway:
        assert TestPlanQueue(get_engine(), gateway=gateway).run_next()
        assert not TestPlanQueue(get_engine(), gateway=gateway).run_next()


def test_wait_and_follow_up_queue_share_budget_and_do_not_hold_idle_lease(
    queued_plan: QueuedPlan,
) -> None:
    q = queued_plan
    client, headers, url, env, calls, output, _ = q
    first = submit(q)
    assert not calls and not rows(tables.application_run_leases)
    work(env)
    result = client.get(f"{url}/{first['run_id']}", headers=headers)
    assert result.json()["status"] == "waiting_input", result.text
    budget = rows(tables.budget_lineages)
    assert all(r["ended_at"] is not None for r in rows(tables.application_run_leases))
    output["questions"] = []
    child = submit(q, previous=result.json()["finding_id"])
    wait = rows(tables.application_input_waits)[0]
    assert wait["resolution"] == "input_received"
    assert str(wait["continuation_run_id"]) == child["run_id"]
    assert len(calls) == 1 and len(rows(tables.application_run_leases)) == 1
    work(env)
    completed = client.get(f"{url}/{child['run_id']}", headers=headers)
    assert completed.json()["status"] == "succeeded", completed.text
    assert completed.json()["finding_id"] != result.json()["finding_id"]
    assert len(calls) == 2 and rows(tables.budget_lineages) == budget
    assert len({r["lineage_id"] for r in rows(tables.budget_run_links)}) == 1
    assert all(r["applied_at"] is None for r in rows(tables.findings))


def test_plan_changed_while_queued_stops_without_model(queued_plan: QueuedPlan) -> None:
    first = submit(queued_plan)
    client, headers, url, env, calls, _, plan = queued_plan
    plan_id = plan["id"]
    assert isinstance(plan_id, str)
    with get_engine().begin() as c:
        c.execute(
            tables.test_plans.update()
            .where(tables.test_plans.c.id == UUID(plan_id))
            .values(title="Updated before execution")
        )
    work(env)
    result = client.get(f"{url}/{first['run_id']}", headers=headers)
    assert result.json()["status"] == "failed", result.text
    assert result.json()["error_code"] == "TEST_PLAN_QUEUED_INPUT_CHANGED"
    assert not calls and not rows(tables.application_run_leases)


def test_queue_cancel_never_generates_finding(queued_plan: QueuedPlan) -> None:
    first = submit(queued_plan)
    client, headers, url, env, calls, _, _ = queued_plan
    response = client.post(f"/api/ai/runs/{first['run_id']}/cancel", headers=headers)
    assert response.status_code == 200, response.text
    with configured_application_gateway(get_engine(), env) as gateway:
        assert not TestPlanQueue(get_engine(), gateway=gateway).run_next()
    assert client.get(f"{url}/{first['run_id']}", headers=headers).json()["status"] == "cancelled"
    assert not calls and not rows(tables.findings)


def test_queue_recovers_saved_model_result(
    queued_plan: QueuedPlan, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = submit(queued_plan)
    client, headers, url, env, calls, _, _ = queued_plan
    original = StructuredModelGateway.invoke_structured
    interrupted = False

    def stop_after_result[OutputT: BaseModel](
        gateway: StructuredModelGateway, invocation: GatewayInvocation, output_type: type[OutputT]
    ) -> GatewayResult[OutputT]:
        nonlocal interrupted
        result = original(gateway, invocation, output_type)
        if not interrupted:
            interrupted = True
            assert invocation.run_id is not None
            expire(get_engine(), invocation.run_id)
            with get_engine().begin() as c:
                c.execute(text("SELECT cehub_ai.expire_application_runs(100)"))
            raise RuntimeError("synthetic owner exit after saved plan result")
        return result

    monkeypatch.setattr(StructuredModelGateway, "invoke_structured", stop_after_result)
    with configured_application_gateway(get_engine(), env) as gateway:
        assert TestPlanQueue(get_engine(), gateway=gateway).run_next()
    assert rows(tables.agent_runs)[0]["error_code"] == "APPLICATION_RUN_LEASE_EXPIRED"
    work(env)
    result = client.get(f"{url}/{first['run_id']}", headers=headers)
    assert result.json()["status"] == "waiting_input", result.text
    assert len(calls) == 1 and len(rows(tables.findings)) == 1
