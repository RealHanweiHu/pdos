"""Risk queue HTTP receipt, new worker and final-result recovery."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import text

from app.ai.application_gateway import configured_application_gateway
from app.ai.gateway import GatewayInvocation, GatewayResult, StructuredModelGateway
from app.ai.risk_queue import RiskQueue
from app.ai.run_store import OwnerAgentRunStore
from app.db.engine import get_engine
from app.db.schema import tables
from tests.test_ai_api import api_context as api_context
from tests.test_ai_api import isolated_ai_api_database as isolated_ai_api_database
from tests.test_ai_api import seed_project_and_users, setup_owner
from tests.test_application_leases import expire
from tests.test_application_run_budget_api import factory
from tests.test_chat_queue import rows
from tests.test_chat_requests import ApiContext

QueuedRisk = tuple[
    TestClient, dict[str, str], dict[str, object], dict[str, str], list[httpx2.Request]
]


@pytest.fixture
def queued_risk(
    api_context: ApiContext,
    isolated_ai_api_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> QueuedRisk:
    client, _, _ = api_context
    tenant, _, headers = setup_owner(client)
    project, event = seed_project_and_users(isolated_ai_api_database, tenant_id=tenant)
    original = StructuredModelGateway.invoke_structured
    environment, calls, _ = factory(
        get_engine(),
        tmp_path,
        monkeypatch,
        output=dict(
            disposition="human_review_candidate",
            candidate_type="risk_suggestion",
            summary="Review the project evidence.",
            proposed_payload=dict(title="Evidence risk", likelihood=3, impact=4),
            evidence_event_ids=[event],
            confidence=0.8,
        ),
    )
    monkeypatch.setattr(StructuredModelGateway, "invoke_structured", original)
    body: dict[str, object] = dict(
        project_id=str(project),
        request_id=str(uuid4()),
        concern="Review this issue",
        evidence_event_ids=[event],
    )
    return client, headers, body, environment, calls


def enqueue(q: QueuedRisk) -> dict[str, object]:
    client, headers, body, _, calls = q
    response = client.post("/api/ai/risk-suggestions/requests", headers=headers, json=body)
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "queued" and not calls
    assert not rows(tables.application_run_leases)
    assert all(s["stopped_at"] is not None for s in rows(tables.budget_activity_spans))
    result_body = response.json()
    assert isinstance(result_body, dict) and all(isinstance(key, str) for key in result_body)
    return result_body


def test_risk_queue_new_worker_publishes_one_pending_finding(queued_risk: QueuedRisk) -> None:
    q = queued_risk
    receipt = enqueue(q)
    client, headers, body, environment, calls = q
    assert (
        client.post("/api/ai/risk-suggestions/requests", headers=headers, json=body).json()
        == receipt
    )
    budget, auth = rows(tables.budget_lineages), rows(tables.application_authorizations)
    assert OwnerAgentRunStore(get_engine()).claim(started_at=datetime.now(UTC)) is None
    with configured_application_gateway(get_engine(), environment) as gateway:
        assert RiskQueue(get_engine(), gateway=gateway).run_next()
        assert not RiskQueue(get_engine(), gateway=gateway).run_next()
    result = client.get(f"/api/ai/risk-suggestions/requests/{receipt['run_id']}", headers=headers)
    assert result.status_code == 200 and result.json()["status"] == "succeeded", result.text
    finding = rows(tables.findings)[0]
    assert str(finding["id"]) == result.json()["finding_id"]
    assert finding["status"] == "pending_review" and finding["applied_at"] is None
    assert len(calls) == 1 and rows(tables.budget_lineages) == budget
    assert rows(tables.application_authorizations) == auth
    assert (
        client.post("/api/ai/risk-suggestions/requests", headers=headers, json=body).json()
        == result.json()
    )


def test_risk_queue_cancel_and_conflicting_request_do_not_call_model(
    queued_risk: QueuedRisk,
) -> None:
    receipt = enqueue(queued_risk)
    client, headers, body, environment, calls = queued_risk
    assert (
        client.post(
            "/api/ai/risk-suggestions/requests",
            headers=headers,
            json={**body, "concern": "Different concern"},
        ).status_code
        == 409
    )
    cancelled = client.post(f"/api/ai/runs/{receipt['run_id']}/cancel", headers=headers)
    assert cancelled.status_code == 200, cancelled.text
    with configured_application_gateway(get_engine(), environment) as gateway:
        assert not RiskQueue(get_engine(), gateway=gateway).run_next()
    result = client.get(f"/api/ai/risk-suggestions/requests/{receipt['run_id']}", headers=headers)
    assert result.json()["status"] == "cancelled" and not calls


def test_risk_worker_recovers_saved_result_without_repeating_model(
    queued_risk: QueuedRisk, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = enqueue(queued_risk)
    client, headers, _, environment, calls = queued_risk
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
            raise RuntimeError("synthetic owner exit after saved risk result")
        return result

    monkeypatch.setattr(StructuredModelGateway, "invoke_structured", stop_after_result)
    with configured_application_gateway(get_engine(), environment) as gateway:
        assert RiskQueue(get_engine(), gateway=gateway).run_next()
    assert rows(tables.agent_runs)[0]["error_code"] == "APPLICATION_RUN_LEASE_EXPIRED"
    with configured_application_gateway(get_engine(), environment) as gateway:
        assert RiskQueue(get_engine(), gateway=gateway).run_next()
        assert not RiskQueue(get_engine(), gateway=gateway).run_next()
    result = client.get(f"/api/ai/risk-suggestions/requests/{receipt['run_id']}", headers=headers)
    assert result.json()["status"] == "succeeded", result.text
    assert len(calls) == 1 and len(rows(tables.findings)) == 1
    assert len(rows(tables.application_run_leases)) == 2
