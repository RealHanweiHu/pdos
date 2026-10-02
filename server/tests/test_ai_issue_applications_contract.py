"""Confirmation HTTP contracts with mocked services; no DB, model, or business writes."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.ai.rollout_guard import CapabilityUnavailableError
from app.api import ai_issue_applications as api
from app.api.auth import current_context
from app.db.engine import get_engine
from app.domain.ai_issue_applications import IssueApplicationError
from app.domain.ai_write_policy import WritePolicyError
from app.domain.knowledge_push import KnowledgeAccessError


@pytest.fixture
def boundary(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Any, ...]]:
    app = FastAPI()
    app.include_router(api.router)
    context, engine, service, scope = MagicMock(), MagicMock(spec=Engine), MagicMock(), MagicMock()
    app.dependency_overrides[current_context] = lambda: context
    app.dependency_overrides[get_engine] = lambda: engine
    monkeypatch.setattr(api, "IssueApplicationService", MagicMock(return_value=service))
    monkeypatch.setattr(api, "ScopeService", MagicMock(return_value=scope))
    service.get.return_value = {"can_apply": False}
    service.apply.return_value = {"reused": False}
    scope.get.return_value = {"scope": {"revision": 0, "enabled": False}}
    scope.change.return_value = {"revision": 1, "reused": False}
    with TestClient(app) as client:
        yield client, context, engine, service, scope


def base(project: Any) -> str:
    return f"/api/projects/{project}/ai-issue-applications"


def test_static_scope_routes_precede_run_uuid_and_bind_actor(boundary: Any) -> None:
    client, context, _, service, scope = boundary
    project = uuid4()
    response = client.get(base(project) + "/scope")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    scope.get.assert_called_once_with(context, project)
    body = {
        "request_id": str(uuid4()),
        "expected_revision": 0,
        "enabled": True,
        "reason": "项目试运行",
    }
    response = client.post(base(project) + "/scope", json=body)
    assert response.status_code == 200
    args = scope.change.call_args.args
    assert args[:2] == (context, project)
    assert args[2].model_dump(mode="json") == body
    service.get.assert_not_called()
    service.apply.assert_not_called()


def test_confirmation_uses_typed_fixed_result_and_current_session(boundary: Any) -> None:
    client, context, _, service, _ = boundary
    project, run = uuid4(), uuid4()
    response = client.get(base(project) + f"/{run}")
    assert response.status_code == 200 and response.json()["can_apply"] is False
    service.get.assert_called_once_with(context, project, run)
    body = {"request_id": str(uuid4()), "result_id": str(uuid4()), "expected_digest": "a" * 64}
    response = client.post(base(project) + f"/{run}", json=body)
    assert response.status_code == 200
    args = service.apply.call_args.args
    assert args[:3] == (context, project, run)
    assert args[3].model_dump(mode="json") == body
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "extra",
    [
        {"origin": "ai"},
        {"principal_id": str(uuid4())},
        {"qualification_current": True},
        {"proposal": {"title": "client override"}},
    ],
)
def test_client_cannot_supply_writer_qualification_or_result(
    boundary: Any, extra: dict[str, Any]
) -> None:
    client, _, _, service, _ = boundary
    response = client.post(
        base(uuid4()) + f"/{uuid4()}",
        json={
            "request_id": str(uuid4()),
            "result_id": str(uuid4()),
            "expected_digest": "a" * 64,
            **extra,
        },
    )
    assert response.status_code == 422
    service.apply.assert_not_called()


@pytest.mark.parametrize(
    "error,status,code",
    [
        (IssueApplicationError("SOURCE_CHANGED", "来源已有变化"), 409, "SOURCE_CHANGED"),
        (
            WritePolicyError("AI_ISSUE_SCOPE_REQUIRED", "范围尚未授权"),
            409,
            "AI_ISSUE_SCOPE_REQUIRED",
        ),
        (CapabilityUnavailableError("CAPABILITY_SHADOW"), 409, "CAPABILITY_SHADOW"),
        (KnowledgeAccessError("已撤权"), 403, "OBJECT_PERMISSION_DENIED"),
        (LookupError("missing"), 404, "ISSUE_APPLICATION_NOT_FOUND"),
    ],
)
def test_apply_business_failures_are_structured_and_not_cached(
    boundary: Any, error: Exception, status: int, code: str
) -> None:
    client, _, _, service, _ = boundary
    service.apply.side_effect = error
    response = client.post(
        base(uuid4()) + f"/{uuid4()}",
        json={"request_id": str(uuid4()), "result_id": str(uuid4()), "expected_digest": "a" * 64},
    )
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert response.headers["cache-control"] == "no-store"


def test_scope_body_cannot_target_other_operations(boundary: Any) -> None:
    client, _, _, _, scope = boundary
    response = client.post(
        base(uuid4()) + "/scope",
        json={
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "enabled": True,
            "reason": "scope",
            "operation_key": "meeting.minutes.draft",
        },
    )
    assert response.status_code == 422
    scope.change.assert_not_called()
