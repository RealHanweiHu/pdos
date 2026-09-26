"""Run detail API and cumulative budget snapshots, without disclosure of source bodies."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select

from app.ai import runtime_factory
from app.ai.application_gateway import configured_application_gateway
from app.ai.budget_ledger import BudgetLedger
from app.ai.chat_queue import ChatQueue
from app.ai.run_progress import read_progress
from app.auth.repository import AuthRepository
from app.db.engine import get_engine
from app.db.schema import tables
from tests.test_agent_database_security import (
    secured_agent_database_url as secured_agent_database_url,
)
from tests.test_agent_tool_loop import LoopSetup
from tests.test_agent_tool_loop import loop_setup as loop_setup
from tests.test_ai_api import PASSWORD
from tests.test_ai_api import api_context as api_context
from tests.test_ai_api import isolated_ai_api_database as isolated_ai_api_database
from tests.test_budget_ledger import ledger_db as ledger_db
from tests.test_budget_ledger import profile, reserve, settle
from tests.test_chat_queue import QueuedChat, enqueue, rows
from tests.test_chat_queue import queued_chat as queued_chat
from tests.test_event_budget_adoption import event_scope as event_scope
from tests.test_event_control import client_for


def test_request_api_reports_queue_completion_and_budget_without_private_content(
    queued_chat: QueuedChat,
) -> None:
    q = queued_chat
    receipt = enqueue(q)
    client, headers, body, env, calls = q
    path = f"/api/ai/projects/{body['project_id']}/runs/{receipt['run_id']}"
    pending = client.get(path, headers=headers)
    assert pending.status_code == 200 and "no-store" in pending.headers["cache-control"]
    value = pending.json()
    assert value["phase"] == "queued" and value["budget"]["charged_tokens"] == 0
    with configured_application_gateway(get_engine(), env) as gateway:
        assert ChatQueue(get_engine(), gateway=gateway).run_next()
    result = client.get(path, headers=headers).json()
    assert (
        result["phase"] == "completed"
        and result["observations"] == 1
        and result["saved_results"] == 1
    )
    assert result["model_receipts"] == 1 and len(calls) == 1
    assert result["budget"]["charged_tokens"] == 10 and result["budget"]["held_tokens"] == 0
    assert result["budget"]["active_seconds"] > 0
    assert "question" not in result and "run_context" not in result and "output_body" not in result
    before = rows(tables.budget_journal)
    assert client.get(path, headers=headers).status_code == 200
    assert rows(tables.budget_journal) == before
    other = client.get(path.replace(body["project_id"], str(UUID(int=1))), headers=headers)
    assert other.status_code in {403, 404}


def test_detail_does_not_disclose_another_users_request(queued_chat: QueuedChat) -> None:
    q = queued_chat
    receipt = enqueue(q)
    client, headers, body, _, _ = q
    engine = get_engine()
    with engine.begin() as c:
        user = (
            c.execute(select(tables.users).where(tables.users.c.username == "manager"))
            .mappings()
            .one()
        )
        c.execute(
            tables.project_members.insert().values(
                id=uuid4(),
                tenant_id=user["tenant_id"],
                project_id=UUID(body["project_id"]),
                user_id=user["id"],
                added_by_user_id=user["id"],
            )
        )
    login = client.post(
        "/api/auth/login", json=dict(tenant_slug="beepump", username="manager", password=PASSWORD)
    )
    assert login.status_code == 200, login.text
    response = client.get(
        f"/api/ai/projects/{body['project_id']}/runs/{receipt['run_id']}",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert response.status_code == 403, response.text


def test_budget_sums_latest_revisions_across_related_runs_and_keeps_unknown(
    ledger_db: tuple[Engine, UUID, list[UUID]],
) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    lid = ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile())
    ledger.link_run(tenant_id=tenant, lineage_id=lid, run_id=runs[1])
    first = reserve(ledger, tenant, runs[0])
    settle(ledger, tenant, first.entry.attempt_id, tokens=60)
    second = reserve(ledger, tenant, runs[1])
    ledger.transition(tenant_id=tenant, attempt_id=second.entry.attempt_id, action="dispatch")
    ledger.transition(tenant_id=tenant, attempt_id=second.entry.attempt_id, action="unknown")
    with engine.connect() as c:
        user = (
            c.execute(select(tables.users.c.id).where(tables.users.c.tenant_id == tenant))
            .scalars()
            .first()
        )
        project = c.execute(
            select(tables.agent_runs.c.project_id).where(tables.agent_runs.c.id == runs[0])
        ).scalar_one()
    assert isinstance(user, UUID)
    context = AuthRepository(engine).find_user_context(user)
    assert context is not None
    snapshot = read_progress(engine, context=context, project_id=project, run_id=runs[0])
    assert snapshot.budget is not None
    assert snapshot.budget.charged_tokens == 60 and snapshot.budget.held_tokens == 80
    assert snapshot.budget.remaining_tokens == 60 and snapshot.budget.unresolved_calls == 1
    assert snapshot.budget.model_cost_complete is False
    ledger.transition(
        tenant_id=tenant,
        attempt_id=second.entry.attempt_id,
        action="settle",
        charged_tokens=40,
        reconciliation_ref="synthetic-known-usage",
    )
    after = read_progress(engine, context=context, project_id=project, run_id=runs[0])
    assert after.budget is not None
    assert after.budget.charged_tokens == 100 and after.budget.held_tokens == 0
    assert after.budget.remaining_tokens == 100 and after.budget.model_cost_complete is False
    legacy = read_progress(engine, context=context, project_id=project, run_id=runs[2])
    assert legacy.budget is None


def test_event_details_follow_real_checkpoints_without_reading_observation_bodies(
    loop_setup: LoopSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, _, _, ids, env, _, _ = loop_setup
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.status == "succeeded"
    with client_for(owner, ids, monkeypatch) as client:
        response = client.get(f"/api/ai/projects/{ids['project_a']}/runs/{result.run_id}")
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["saved_tool_steps"] == 1 and detail["saved_results"] == 1
    assert detail["tool_dispatches"] >= 1 and detail["observations"] >= 1
    assert detail["last_tool"] == "get_recent_events"
    assert detail["model_receipts"] == 2
    assert "must remain private" not in response.text
