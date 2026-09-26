"""Durable event pause/resume through real HTTP and restricted checkpoint execution."""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.ai import runtime_factory
from app.ai.run_store import ClaimedAgentRun
from app.db.schema import tables
from app.worker.dispatcher import AgentDispatcher
from tests.test_agent_database_security import (
    secured_agent_database_url as secured_agent_database_url,
)
from tests.test_agent_tool_loop import LoopSetup
from tests.test_agent_tool_loop import loop_setup as loop_setup
from tests.test_event_budget_adoption import EventScope, scope_id
from tests.test_event_budget_adoption import event_scope as event_scope
from tests.test_event_control import client_for
from tests.test_model_budget_controller import rows


def control(client: TestClient, run: UUID, action: str) -> dict[str, object]:
    response = client.post(f"/api/ai/runs/{run}/{action}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict) and all(isinstance(key, str) for key in body)
    return body


def current(client: TestClient, ids: dict[str, UUID | int]) -> dict[str, object]:
    response = client.get(f"/api/ai/projects/{ids['project_a']}/runs")
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert isinstance(item, dict) and all(isinstance(key, str) for key in item)
    return item


def test_pause_queue_can_resume_or_cancel_without_resetting_budget(
    loop_setup: LoopSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, _, _, ids, env, calls, _ = loop_setup
    run = rows(owner, tables.agent_runs)[0]
    run_id = run["id"]
    assert isinstance(run_id, UUID)
    budgets = rows(owner, tables.budget_lineages)
    with client_for(owner, ids, monkeypatch, role="project_manager") as client:
        assert current(client, ids)["can_pause"]
        assert control(client, run_id, "pause")["changed"]
        assert not control(client, run_id, "pause")["changed"]
        assert current(client, ids)["status"] == "paused" and current(client, ids)["can_resume"]
        with runtime_factory.configured_agent_runtime(env) as runtime:
            assert runtime.executor.execute_next().status == "idle"
        assert not calls
        assert control(client, run_id, "resume")["changed"]
        assert current(client, ids)["status"] == "queued"
        assert rows(owner, tables.budget_lineages) == budgets
        control(client, run_id, "pause")
        assert control(client, run_id, "cancel")["changed"]
        assert current(client, ids)["status"] == "cancelled"
        assert all(r["resolved_at"] is not None for r in rows(owner, tables.event_run_pauses))


@pytest.mark.parametrize("boundary", ["step", "result"])
def test_running_pause_preserves_checkpoint_and_new_process_continues(
    loop_setup: LoopSetup, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    owner, _, _, ids, env, calls, _ = loop_setup
    run = rows(owner, tables.agent_runs)[0]
    run_id = run["id"]
    assert isinstance(run_id, UUID)
    budgets = rows(owner, tables.budget_lineages)
    with client_for(owner, ids, monkeypatch) as client:
        with runtime_factory.configured_agent_runtime(env) as runtime:
            if boundary == "step":
                observations = runtime.executor._observations
                assert observations is not None
                original_observation = observations._call

                def request_pause_after_step(sql: str, **values: object) -> object:
                    result: object = original_observation(sql, **values)
                    if "save_agent_loop_checkpoint" in sql:
                        control(client, run_id, "pause")
                        assert current(client, ids)["status"] == "pausing"
                    return result

                monkeypatch.setattr(observations, "_call", request_pause_after_step)
            else:
                checkpoints = runtime.executor._checkpoints
                assert checkpoints is not None
                original_checkpoint = checkpoints.save

                def request_pause_after_result(claim: ClaimedAgentRun, body: str) -> UUID:
                    result = original_checkpoint(claim, body)
                    control(client, run_id, "pause")
                    return result

                monkeypatch.setattr(checkpoints, "save", request_pause_after_result)
            result = runtime.executor.execute_next()
        assert result.status == "paused", result
        assert current(client, ids)["status"] == "paused"
        detail = client.get(f"/api/ai/projects/{ids['project_a']}/runs/{run['id']}").json()
        assert detail["phase"] == "paused"
        journal = rows(owner, tables.budget_journal)
        assert all(r["stopped_at"] is not None for r in rows(owner, tables.budget_activity_spans))
        with runtime_factory.configured_agent_runtime(env) as runtime:
            assert runtime.executor.execute_next().status == "idle"
        assert rows(owner, tables.budget_journal) == journal
        assert control(client, run_id, "resume")["changed"]
        with runtime_factory.configured_agent_runtime(env) as runtime:
            result = runtime.executor.execute_next()
        assert result.status == "succeeded", result
        assert len(calls) == 2 and len(rows(owner, tables.findings)) == 1
        assert rows(owner, tables.budget_lineages) == budgets
        assert rows(owner, tables.event_run_pauses)[0]["resolution"] == "resumed"


def test_resume_rechecks_subscription_and_pause_requires_edit_scope(
    loop_setup: LoopSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, _, _, ids, _, _, _ = loop_setup
    run = rows(owner, tables.agent_runs)[0]
    run_id = run["id"]
    assert isinstance(run_id, UUID)
    with client_for(owner, ids, monkeypatch, role="engineer") as client:
        assert not current(client, ids)["can_pause"]
        assert client.post(f"/api/ai/runs/{run['id']}/pause").status_code == 403
    with client_for(owner, ids, monkeypatch) as client:
        control(client, run_id, "pause")
        with owner.begin() as c:
            c.execute(
                tables.agent_subscriptions.update()
                .where(tables.agent_subscriptions.c.id == run["subscription_id"])
                .values(status="paused", paused_reason="Synthetic subscription pause")
            )
        response = client.post(f"/api/ai/runs/{run['id']}/resume")
        assert response.status_code == 409, response.text
        assert rows(owner, tables.event_run_pauses)[0]["resolved_at"] is None
        assert not current(client, ids)["can_pause"]


def test_debounce_pause_is_not_claimed_after_sealing(
    event_scope: EventScope, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, worker, agent, ids = event_scope
    dispatcher = AgentDispatcher(worker, budget_profile_key="short")
    dispatcher.dispatch_tenant(tenant_id=scope_id(ids, "tenant_a"))
    run = rows(owner, tables.agent_runs)[0]
    run_id = run["id"]
    assert isinstance(run_id, UUID)
    with client_for(owner, ids, monkeypatch) as client:
        control(client, run_id, "pause")
        dispatcher.seal_due_runs()
        with agent.begin() as c:
            assert (
                c.execute(text("SELECT * FROM cehub_ai.claim_agent_run(clock_timestamp())")).first()
                is None
            )
        assert current(client, ids)["status"] == "paused"
        control(client, run_id, "resume")
        assert current(client, ids)["status"] == "queued"
