"""Exercise the actual preview router with overridden in-memory dependencies."""

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.api import plan_scenarios as api
from app.api.auth import current_context
from app.db.engine import get_engine
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError
from tests.test_resource_reallocations import context


def client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, MagicMock]:
    service = MagicMock()
    monkeypatch.setattr(api, "ResourceReallocationService", lambda engine: service)
    app = FastAPI()
    app.include_router(api.router)
    caller = context()
    app.dependency_overrides[current_context] = lambda: caller
    app.dependency_overrides[get_engine] = lambda: MagicMock(spec=Engine)
    return TestClient(app), service


def draft() -> dict[str, Any]:
    return {
        "request_id": str(uuid4()),
        "title": "synthetic",
        "reason": "synthetic",
        "items": [
            {
                "reservation_id": str(uuid4()),
                "expected_digest": "b" * 64,
                "impact": "synthetic",
                "target": {
                    "request_id": str(uuid4()),
                    "node_id": str(uuid4()),
                    "capacity_version_id": str(uuid4()),
                    "window_start": "2026-10-01T09:00Z",
                    "window_end": "2026-10-01T17:00Z",
                    "parallel_units": "1",
                    "occupancy_policy": "working_only",
                    "basis": "synthetic",
                },
            }
            for _ in range(2)
        ],
    }


def test_original_draft_and_saved_review_keep_distinct_dispatch_and_no_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http, service = client(monkeypatch)
    service.preview.return_value = {
        "preview_digest": "a" * 64,
        "snapshot": {"capacity_clear": True},
    }
    service.review.return_value = {"sources_current": False, "blockers": ["policy drift"]}
    url = f"/api/projects/{uuid4()}/execution/resource-reallocation-preview"
    result = http.post(url, json=draft())
    assert result.status_code == 200 and result.json()["preview_digest"] == "a" * 64
    assert result.headers["cache-control"] == "no-store"
    service.preview.assert_called_once()
    service.review.assert_not_called()
    review = {"allocation_id": str(uuid4()), "expected_digest": "b" * 64}
    result = http.post(url, json=review)
    assert result.status_code == 200 and result.json()["sources_current"] is False
    service.review.assert_called_once()
    assert str(service.review.call_args.args[2].allocation_id) == review["allocation_id"]
    assert result.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "failure,code",
    [
        (ProductWorkAccessError("no access"), 403),
        (ProductWorkError("wrong digest"), 409),
    ],
)
def test_saved_review_preserves_permission_and_version_errors(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    code: int,
) -> None:
    http, service = client(monkeypatch)
    service.review.side_effect = failure
    result = http.post(
        f"/api/projects/{uuid4()}/execution/resource-reallocation-preview",
        json={
            "allocation_id": str(uuid4()),
            "expected_digest": "b" * 64,
        },
    )
    assert result.status_code == code
    assert result.json()["detail"]["message"] == str(failure)


def test_review_cannot_smuggle_replacement_inputs_into_saved_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http, service = client(monkeypatch)
    body = {**draft(), "allocation_id": str(uuid4()), "expected_digest": "b" * 64}
    result = http.post(
        f"/api/projects/{uuid4()}/execution/resource-reallocation-preview", json=body
    )
    assert result.status_code == 422
    service.review.assert_not_called()
    service.preview.assert_not_called()
