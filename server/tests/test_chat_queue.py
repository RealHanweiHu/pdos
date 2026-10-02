"""Real queue API and application worker, using a synthetic model transport."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import RowMapping, Table, select, text

from app.ai.application_gateway import configured_application_gateway
from app.ai.chat_queue import ChatQueue
from app.ai.chat_runs import ChatRequestConflictError, ChatRunStore
from app.ai.gateway import GatewayInvocation, GatewayResult, StructuredModelGateway
from app.auth.repository import AuthRepository
from app.db.engine import get_engine
from app.db.schema import tables
from tests.test_ai_api import api_context as api_context
from tests.test_ai_api import isolated_ai_api_database as isolated_ai_api_database
from tests.test_ai_api import seed_project_and_users, setup_owner
from tests.test_application_run_budget_api import factory
from tests.test_chat_requests import ApiContext
from tests.test_model_budget_controller import evidence

QueuedChat = tuple[TestClient, dict[str, str], dict[str, str], dict[str, str], list[httpx2.Request]]


@pytest.fixture
def queued_chat(
    api_context: ApiContext,
    isolated_ai_api_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> QueuedChat:
    client, _, _ = api_context
    tenant, _, headers = setup_owner(client)
    project, _ = seed_project_and_users(isolated_ai_api_database, tenant_id=tenant)
    original = StructuredModelGateway.invoke_structured
    environment, calls, _ = factory(
        get_engine(),
        tmp_path,
        monkeypatch,
        request=request,
        output={
            "disposition": "answered",
            "claims": [
                {"text": "Project facts are available.", "citation_ids": [f"project:{project}"]}
            ],
        },
    )
    # Queuing deliberately creates a stopped creation span before the execution span.
    monkeypatch.setattr(StructuredModelGateway, "invoke_structured", original)
    body = dict(project_id=str(project), question="Project status?", request_id=str(uuid4()))
    return client, headers, body, environment, calls


def rows(table: Table) -> list[RowMapping]:
    with get_engine().connect() as c:
        return list(c.execute(select(table)).mappings())


def enqueue(q: QueuedChat) -> dict[str, object]:
    client, headers, body, _, calls = q
    response = client.post("/api/ai/chat/requests", headers=headers, json=body)
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "queued" and response.json()["started_at"] is None
    assert not calls and not rows(tables.application_run_leases)
    assert all(x["stopped_at"] is not None for x in rows(tables.budget_activity_spans))
    return evidence(response.json())


def test_submit_worker_and_poll_preserve_request_budget_and_citations(
    queued_chat: QueuedChat,
) -> None:
    q = queued_chat
    client, headers, body, environment, calls = q
    receipt = enqueue(q)
    budgets, authority = rows(tables.budget_lineages), rows(tables.application_authorizations)
    url = f"/api/ai/chat/requests/{receipt['run_id']}"
    assert client.get(url, headers=headers).json() == receipt
    with configured_application_gateway(get_engine(), environment) as gateway:
        queue = ChatQueue(get_engine(), gateway=gateway)
        assert queue.run_next()
        assert not queue.run_next()
    result = client.get(url, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "succeeded", result.text
    assert result.json()["result"]["answer"] == "Project facts are available."
    assert result.json()["result"]["citations"][0]["entity_id"] == body["project_id"]
    assert len(calls) == 1 and rows(tables.budget_lineages) == budgets
    assert rows(tables.application_authorizations) == authority
    assert len(rows(tables.application_run_leases)) == 1
    assert client.post("/api/ai/chat/requests", headers=headers, json=body).json() == result.json()
    with get_engine().begin() as c:
        c.execute(
            tables.projects.update()
            .where(tables.projects.c.id == UUID(body["project_id"]))
            .values(name="Changed since answer")
        )
    assert (
        client.get(url, headers=headers).json()["result"]["error_code"] == "CHAT_EVIDENCE_CHANGED"
    )
    assert len(calls) == 1


def test_duplicate_cancel_and_content_conflict_do_not_execute(queued_chat: QueuedChat) -> None:
    client, headers, body, environment, calls = queued_chat
    first = enqueue(queued_chat)
    assert client.post("/api/ai/chat/requests", headers=headers, json=body).json() == first
    conflict = client.post(
        "/api/ai/chat/requests", headers=headers, json={**body, "question": "different content"}
    )
    assert conflict.status_code == 409
    cancel = f"/api/ai/chat/requests/{first['run_id']}/cancel"
    stopped = client.post(cancel, headers=headers)
    assert stopped.status_code == 200 and stopped.json()["status"] == "cancelled", stopped.text
    assert client.post(cancel, headers=headers).json() == stopped.json()
    with configured_application_gateway(get_engine(), environment) as gateway:
        assert not ChatQueue(get_engine(), gateway=gateway).run_next()
    assert not calls and len(rows(tables.agent_runs)) == 1


def test_changed_login_stops_queued_request_without_new_authority(queued_chat: QueuedChat) -> None:
    enqueue(queued_chat)
    _, _, _, environment, calls = queued_chat
    actor = rows(tables.agent_runs)[0]["requested_by_user_id"]
    original = rows(tables.application_authorizations)
    with get_engine().begin() as c:
        c.execute(
            tables.users.update()
            .where(tables.users.c.id == actor)
            .values(auth_version=tables.users.c.auth_version + 1)
        )
    with configured_application_gateway(get_engine(), environment) as gateway:
        queue = ChatQueue(get_engine(), gateway=gateway)
        assert queue.run_next() and not queue.run_next()
    assert rows(tables.agent_runs)[0]["error_code"] == "APPLICATION_AUTHORIZATION_CHANGED"
    assert rows(tables.application_authorizations) == original
    assert not calls and not rows(tables.application_run_leases)


def test_two_workers_only_one_claims_first_execution(queued_chat: QueuedChat) -> None:
    enqueue(queued_chat)
    _, _, body, environment, calls = queued_chat
    original = rows(tables.agent_runs)[0]
    context = AuthRepository(get_engine()).find_user_context(original["requested_by_user_id"])
    assert context is not None
    barrier = Barrier(2)

    def claim() -> bool:
        with configured_application_gateway(get_engine(), environment) as gateway:
            barrier.wait(timeout=10)
            try:
                _, created = ChatRunStore(get_engine(), gateway=gateway).start(
                    tenant_id=context.tenant.id,
                    actor_user_id=context.user.id,
                    auth_version=context.user.auth_version,
                    project_id=UUID(body["project_id"]),
                    request_id=body["request_id"],
                    question=body["question"],
                )
                return created
            except ChatRequestConflictError:
                return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: claim(), range(2))) == [False, True]
    assert len(rows(tables.application_run_leases)) == 1 and not calls


def test_queue_requires_budgeted_factory(
    api_context: ApiContext, isolated_ai_api_database: str
) -> None:
    client, _, _ = api_context
    tenant, _, headers = setup_owner(client)
    project, _ = seed_project_and_users(isolated_ai_api_database, tenant_id=tenant)
    response = client.post(
        "/api/ai/chat/requests",
        headers=headers,
        json=dict(project_id=str(project), question="Status?"),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "APPLICATION_QUEUE_BUDGET_REQUIRED"
    assert not rows(tables.agent_runs)


def test_worker_recovers_persisted_result_after_previous_owner_exit(
    queued_chat: QueuedChat, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_application_leases import expire

    receipt = enqueue(queued_chat)
    client, headers, _, environment, calls = queued_chat
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
            raise RuntimeError("synthetic owner exit after saved result")
        return result

    monkeypatch.setattr(StructuredModelGateway, "invoke_structured", stop_after_result)
    with configured_application_gateway(get_engine(), environment) as first:
        assert ChatQueue(get_engine(), gateway=first).run_next()
    assert rows(tables.agent_runs)[0]["error_code"] == "APPLICATION_RUN_LEASE_EXPIRED"
    with configured_application_gateway(get_engine(), environment) as second:
        queue = ChatQueue(get_engine(), gateway=second)
        assert queue.run_next() and not queue.run_next()
    response = client.get(f"/api/ai/chat/requests/{receipt['run_id']}", headers=headers)
    assert response.json()["status"] == "succeeded", response.text
    assert len(calls) == 1 and len(rows(tables.application_run_leases)) == 2
