"""Project event stops via HTTP and a real restricted executor."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from app.ai import runtime_factory
from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError
from app.api.auth import current_context
from app.auth.repository import AuthRepository
from app.db.engine import get_engine
from app.db.schema import tables
from app.main import app
from app.settings import get_settings
from app.worker.dispatcher import AgentDispatcher
from tests.test_agent_database_security import (
    secured_agent_database_url as secured_agent_database_url,
)
from tests.test_agent_dispatcher import append_event
from tests.test_agent_tool_loop import LoopSetup
from tests.test_agent_tool_loop import loop_setup as loop_setup
from tests.test_event_budget_adoption import EventScope, scope_id
from tests.test_event_budget_adoption import event_scope as event_scope
from tests.test_model_budget_controller import rows


@contextmanager
def client_for(
    owner: Engine,
    ids: dict[str, UUID | int],
    monkeypatch: pytest.MonkeyPatch,
    *,
    role: str = "owner",
    member: bool = True,
) -> Iterator[TestClient]:
    user = uuid4()
    with owner.begin() as c:
        c.execute(
            tables.users.insert().values(
                id=user,
                tenant_id=scope_id(ids, "tenant_a"),
                username=str(user),
                display_name="Run controller",
                role=role,
            )
        )
        if member:
            c.execute(
                tables.project_members.insert().values(
                    id=uuid4(),
                    tenant_id=scope_id(ids, "tenant_a"),
                    project_id=scope_id(ids, "project_a"),
                    user_id=user,
                    added_by_user_id=user,
                )
            )
    context = AuthRepository(owner).find_user_context(user)
    monkeypatch.setenv("JWT_SECRET", "test-only-event-control-secret-at-least-32-bytes")
    get_settings.cache_clear()
    app.dependency_overrides[get_engine] = lambda: owner
    app.dependency_overrides[current_context] = lambda: context
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def cancel(client: TestClient, run: UUID) -> dict[str, object]:
    result = client.post(f"/api/ai/runs/{run}/cancel")
    assert result.status_code == 200, result.text
    body = result.json()
    assert isinstance(body, dict) and all(isinstance(key, str) for key in body)
    return body


@pytest.mark.parametrize("sealed", [False, True])
def test_project_manager_stops_pending_event_without_disabling_future_events(
    event_scope: EventScope, monkeypatch: pytest.MonkeyPatch, sealed: bool
) -> None:
    owner, worker, _, ids = event_scope
    dispatcher = AgentDispatcher(worker, budget_profile_key="short")
    dispatcher.dispatch_tenant(tenant_id=scope_id(ids, "tenant_a"))
    if sealed:
        dispatcher.seal_due_runs()
    run = rows(owner, tables.agent_runs)[0]
    run_id = run["id"]
    assert isinstance(run_id, UUID)
    with client_for(owner, ids, monkeypatch, role="project_manager") as client:
        view = client.get(f"/api/ai/projects/{ids['project_a']}/runs")
        assert view.status_code == 200 and view.json()["items"][0]["can_cancel"], view.text
        assert cancel(client, run_id)["changed"]
        assert not cancel(client, run_id)["changed"]
        view = client.get(f"/api/ai/projects/{ids['project_a']}/runs").json()["items"][0]
        assert view["status"] == "cancelled" and not view["can_cancel"]
    stopped = rows(owner, tables.agent_runs)[0]
    assert stopped["started_at"] is None and stopped["event_row_ids"] == run["event_row_ids"]
    with pytest.raises(BudgetLedgerError, match="BUDGET_LINEAGE_CANCELLED"):
        BudgetLedger(owner).require_active(tenant_id=scope_id(ids, "tenant_a"), run_id=run_id)
    with owner.begin() as c:
        append_event(
            c,
            tenant_id=scope_id(ids, "tenant_a"),
            project_id=scope_id(ids, "project_a"),
            event_type="ISSUE_CREATED",
            occurred_at=datetime.now(UTC),
        )
    assert dispatcher.dispatch_tenant(tenant_id=scope_id(ids, "tenant_a")).created_run_count == 1
    assert len(rows(owner, tables.application_cancellations)) == 1
    assert not rows(owner, tables.model_invocations)


def test_running_event_stops_after_checkpoint_and_preserves_charges(
    loop_setup: LoopSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, worker, _, ids, env, calls, _ = loop_setup
    run = rows(owner, tables.agent_runs)[0]
    run_id = run["id"]
    assert isinstance(run_id, UUID)
    with client_for(owner, ids, monkeypatch) as client:
        with runtime_factory.configured_agent_runtime(env) as runtime:
            observations = runtime.executor._observations
            assert observations is not None
            original = observations._call
            journal: list[dict[str, object]] = []

            def stop(sql: str, **values: object) -> object:
                result: object = original(sql, **values)
                if "save_agent_loop_checkpoint" in sql:
                    journal.extend(rows(owner, tables.budget_journal))
                    assert cancel(client, run_id)["changed"]
                return result

            monkeypatch.setattr(observations, "_call", stop)
            result = runtime.executor.execute_next()
        assert result.status != "succeeded"
        assert len(calls) == 1 and not rows(owner, tables.findings)
        assert rows(owner, tables.budget_journal) == journal
        assert all(s["stopped_at"] is not None for s in rows(owner, tables.budget_activity_spans))
        assert AgentDispatcher(worker).dispatch_once().recovered_run_count == 0
        with runtime_factory.configured_agent_runtime(env) as runtime:
            assert runtime.executor.execute_next().status == "idle"
        assert rows(owner, tables.agent_runs)[0]["error_code"] == "EVENT_RUN_CANCELLED"


def test_completed_event_keeps_finding_and_completion(
    loop_setup: LoopSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, _, _, ids, env, calls, _ = loop_setup
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.status == "succeeded"
    assert result.run_id is not None
    before = rows(owner, tables.findings)
    with client_for(owner, ids, monkeypatch) as client:
        assert not cancel(client, result.run_id)["changed"]
    assert rows(owner, tables.findings) == before and len(before) == 1
    assert not rows(owner, tables.application_cancellations)
    assert len(calls) == 2


@pytest.mark.parametrize("role,member", [("engineer", True), ("project_manager", False)])
def test_event_control_requires_project_edit_access(
    event_scope: EventScope, monkeypatch: pytest.MonkeyPatch, role: str, member: bool
) -> None:
    owner, worker, _, ids = event_scope
    AgentDispatcher(worker, budget_profile_key="short").dispatch_tenant(
        tenant_id=scope_id(ids, "tenant_a")
    )
    run = rows(owner, tables.agent_runs)[0]
    run_id = run["id"]
    assert isinstance(run_id, UUID)
    with client_for(owner, ids, monkeypatch, role=role, member=member) as client:
        denied = client.post(f"/api/ai/runs/{run['id']}/cancel")
        assert denied.status_code == 403, denied.text
    assert not rows(owner, tables.application_cancellations)
    with owner.connect() as c:
        assert c.execute(select(tables.agent_runs.c.status)).scalar_one() == "debouncing"
