"""User cancellation through real APIs, with original lease and wait lifecycles."""

from uuid import UUID

import pytest

from app.ai.application_gateway import configured_application_gateway
from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError
from app.ai.chat_queue import ChatQueue
from app.ai.chat_runs import ChatRunStore
from app.auth.repository import AuthRepository
from app.db.engine import get_engine
from app.db.schema import tables
from tests.test_ai_api import api_context as api_context
from tests.test_ai_api import isolated_ai_api_database as isolated_ai_api_database
from tests.test_ai_test_plan_changes import scenario as scenario
from tests.test_ai_test_plan_changes import suggest
from tests.test_application_waits import WaitingPlan
from tests.test_application_waits import waiting_plan as waiting_plan
from tests.test_chat_queue import QueuedChat, enqueue, rows
from tests.test_chat_queue import queued_chat as queued_chat
from tests.test_test_report_import_api import isolated_import_database as isolated_import_database


def test_cancel_queued_run_is_visible_idempotent_and_never_dispatches(
    queued_chat: QueuedChat,
) -> None:
    receipt = enqueue(queued_chat)
    client, headers, body, environment, calls = queued_chat
    url = f"/api/ai/runs/{receipt['run_id']}/cancel"
    response = client.post(url, headers=headers, json={})
    assert response.status_code == 200, response.text
    assert response.json()["changed"] and response.json()["cancelled_run_ids"] == [
        receipt["run_id"]
    ]
    assert client.post(url, headers=headers, json={}).json()["changed"] is False
    assert len(rows(tables.application_cancellations)) == 1
    view = client.get(f"/api/ai/projects/{body['project_id']}/runs", headers=headers)
    assert view.status_code == 200, view.text
    assert view.json()["items"][0]["status"] == "cancelled"
    assert view.json()["items"][0]["can_cancel"] is False
    with configured_application_gateway(get_engine(), environment) as gateway:
        assert not ChatQueue(get_engine(), gateway=gateway).run_next()
    assert not calls and not rows(tables.model_invocations)


def test_cancel_running_run_releases_lease_and_stops_original_budget(
    queued_chat: QueuedChat,
) -> None:
    receipt = enqueue(queued_chat)
    client, headers, body, environment, calls = queued_chat
    run = rows(tables.agent_runs)[0]
    context = AuthRepository(get_engine()).find_user_context(run["requested_by_user_id"])
    assert context is not None
    with configured_application_gateway(get_engine(), environment) as gateway:
        _, created = ChatRunStore(get_engine(), gateway=gateway).start(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            auth_version=context.user.auth_version,
            project_id=UUID(body["project_id"]),
            request_id=body["request_id"],
            question=body["question"],
        )
        assert created
        response = client.post(f"/api/ai/runs/{receipt['run_id']}/cancel", headers=headers)
        assert response.status_code == 200, response.text
        with pytest.raises(BudgetLedgerError, match="BUDGET_LINEAGE_CANCELLED"):
            BudgetLedger(get_engine()).require_active(tenant_id=run["tenant_id"], run_id=run["id"])
    assert all(row["ended_at"] is not None for row in rows(tables.application_run_leases))
    assert all(row["stopped_at"] is not None for row in rows(tables.budget_activity_spans))
    assert not calls


def test_cancel_wait_ends_handoff_and_blocks_new_linked_request(waiting_plan: WaitingPlan) -> None:
    scenario, output, calls, _, finding, _, _ = waiting_plan
    client, _, project, headers, _, _ = scenario
    run = rows(tables.agent_runs)[0]
    url = f"/api/ai/runs/{run['id']}/cancel"
    before = rows(tables.budget_journal)
    response = client.post(url, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["changed"] is True
    wait = rows(tables.application_input_waits)[0]
    assert wait["resolution"] == "cancelled" and wait["resolved_at"] is not None
    assert wait["continuation_run_id"] is None
    output["questions"] = []
    follow = suggest(scenario, previous_finding_id=finding["id"])
    assert follow.status_code == 409, follow.text
    assert len(rows(tables.agent_runs)) == 1 and len(calls) == 1
    assert rows(tables.budget_journal) == before
    assert client.post(url, headers=headers).json()["changed"] is False
