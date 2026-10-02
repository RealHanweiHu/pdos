"""HTTP binding and error boundaries with no database or provider execution."""

from collections.abc import Iterator
from contextlib import nullcontext
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.ai.budget_ledger import BudgetLedgerError
from app.ai.issue_event_proposal import IssueEventProposalError
from app.ai.issue_event_runs import IssueEventRuns
from app.ai.rollout_guard import CapabilityUnavailableError
from app.api import ai_issue_event_runs as api
from app.api.auth import current_context
from app.db.engine import get_engine
from app.domain.knowledge_push import KnowledgeAccessError


@pytest.fixture
def boundary(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Any, Any, Any]]:
    app = FastAPI()
    app.include_router(api.router)
    context, engine, gateway = MagicMock(), MagicMock(spec=Engine), MagicMock()
    app.dependency_overrides[current_context] = lambda: context
    app.dependency_overrides[get_engine] = lambda: engine
    # A gateway context may be entered, but no call is ever permitted.
    gateway.invoke_structured.side_effect = AssertionError("provider must not be called")
    monkeypatch.setattr(api, "configured_application_gateway", lambda _: nullcontext(gateway))
    monkeypatch.setattr(api, "require_live_key", lambda _: None)
    with TestClient(app) as client:
        yield client, context, engine, gateway


def path(project: Any) -> str:
    return f"/api/projects/{project}/ai-issue-event-runs"


def test_preparation_and_fixed_history_bind_session_and_project(
    boundary: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, context, engine, _ = boundary
    project, run, before = uuid4(), uuid4(), uuid4()
    prepare = MagicMock(return_value={"digest": "a" * 64})
    listing = MagicMock(return_value={"items": [], "next_before_id": None})
    monkeypatch.setattr(api, "prepare", prepare)
    monkeypatch.setattr(IssueEventRuns, "list_results", listing)
    result = client.get(path(project) + "/preparation?event_row_id=27")
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    prepare.assert_called_once_with(engine, context, project, 27)
    result = client.get(
        path(project),
        params={"event_row_id": "27", "before_id": str(before), "run_id": str(run)},
    )
    assert result.status_code == 200
    listing.assert_called_once_with(
        engine,
        context=context,
        project_id=project,
        event_row_id=27,
        before_id=before,
        run_id=run,
        attention=False,
    )


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "nope", "9007199254740992"])
def test_invalid_event_query_never_reaches_reader(
    boundary: Any, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    client, _, _, _ = boundary
    reader = MagicMock(side_effect=AssertionError("invalid input reached reader"))
    monkeypatch.setattr(api, "prepare", reader)
    monkeypatch.setattr(IssueEventRuns, "list_results", reader)
    for suffix in ("", "/preparation"):
        response = client.get(path(uuid4()) + suffix, params={"event_row_id": value})
        assert response.status_code == 422
    reader.assert_not_called()


def test_create_only_forwards_typed_source_binding(
    boundary: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, context, engine, gateway = boundary
    project, request_id = uuid4(), uuid4()
    service = MagicMock()
    service.create.return_value = {"status": "succeeded", "finding_id": str(uuid4())}
    factory = MagicMock(return_value=service)
    monkeypatch.setattr(api, "IssueEventRuns", factory)
    body = {"request_id": str(request_id), "event_row_id": 27, "expected_digest": "a" * 64}
    response = client.post(path(project), json=body)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    factory.assert_called_once_with(engine, gateway=gateway)
    args = service.create.call_args.kwargs
    assert args["context"] is context and args["project_id"] == project
    assert args["request"].model_dump(mode="json") == body
    gateway.invoke_structured.assert_not_called()


@pytest.mark.parametrize(
    "error,status,code",
    [
        (IssueEventProposalError("source_changed", "原来源已有变化"), 409, "source_changed"),
        (CapabilityUnavailableError("CAPABILITY_SHADOW"), 409, "CAPABILITY_SHADOW"),
        (KnowledgeAccessError("not readable"), 403, "OBJECT_PERMISSION_DENIED"),
        (LookupError("wrong project"), 404, "ISSUE_EVENT_SOURCE_NOT_FOUND"),
        (
            BudgetLedgerError("APPLICATION_AUTHORIZATION_DENIED"),
            403,
            "APPLICATION_AUTHORIZATION_DENIED",
        ),
        (BudgetLedgerError("BUDGET_EXHAUSTED"), 409, "BUDGET_EXHAUSTED"),
    ],
)
def test_business_errors_are_structured_and_not_cached(
    boundary: Any, monkeypatch: pytest.MonkeyPatch, error: Exception, status: int, code: str
) -> None:
    client, _, _, _ = boundary
    monkeypatch.setattr(api, "prepare", MagicMock(side_effect=error))
    response = client.get(path(uuid4()) + "/preparation?event_row_id=27")
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert response.headers["cache-control"] == "no-store"


def test_unexpected_failure_is_not_disguised_as_business_conflict() -> None:
    failure = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="database unavailable"):
        api._failure(failure)


@pytest.mark.parametrize(
    "change",
    [
        {"event_row_id": 0},
        {"event_row_id": -1},
        {"expected_digest": "short"},
        {"expected_digest": "z" * 64},
        {"request_id": "not-a-uuid"},
    ],
)
def test_invalid_generation_request_never_reaches_gateway(
    boundary: Any, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any]
) -> None:
    client, _, _, _ = boundary
    factory = MagicMock(side_effect=AssertionError("invalid request reached gateway"))
    monkeypatch.setattr(api, "configured_application_gateway", factory)
    body = {"request_id": str(uuid4()), "event_row_id": 27, "expected_digest": "a" * 64}
    response = client.post(path(uuid4()), json={**body, **change})
    assert response.status_code == 422
    factory.assert_not_called()


def test_gateway_setup_failure_uses_business_error_mapping(
    boundary: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _, _ = boundary
    monkeypatch.setattr(
        api,
        "configured_application_gateway",
        MagicMock(side_effect=BudgetLedgerError("APPLICATION_QUEUE_BUDGET_REQUIRED")),
    )
    response = client.post(
        path(uuid4()),
        json={"request_id": str(uuid4()), "event_row_id": 27, "expected_digest": "a" * 64},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "APPLICATION_QUEUE_BUDGET_REQUIRED"
    assert response.headers["cache-control"] == "no-store"
