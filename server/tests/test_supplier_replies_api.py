"""In-process HTTP boundaries with explicit mocked services and no database."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import npi_execution as api
from app.api.auth import current_context
from app.db.engine import get_engine
from app.domain.product_workspace import ProductWorkError

PROJECT, SUPPLIER, RECORD, DOCUMENT = (UUID(int=i) for i in range(1, 5))
PATH = f"/api/projects/{PROJECT}/npi/supplier-replies/{SUPPLIER}/{RECORD}"
DRAFT = dict(
    update="first_response",
    at="2020-01-03T00:00:00Z",
    evidence_id=str(DOCUMENT),
    location="内部转发第2页",
    reason="对应原供方事项",
)


def client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, MagicMock]:
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[current_context] = lambda: SimpleNamespace()
    app.dependency_overrides[get_engine] = lambda: MagicMock()
    service = MagicMock()
    monkeypatch.setattr(api, "SupplierReplyService", lambda engine: service)
    return TestClient(app), service


def test_reply_http_preview_and_confirm_bound_path_and_no_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http, service = client(monkeypatch)
    service.preview.return_value = {"digest": "a" * 64}
    service.confirm.return_value = {"version": 2}
    response = http.post(f"{PATH}/preview", json=DRAFT)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert service.preview.call_args.args[1:4] == (PROJECT, SUPPLIER, RECORD)
    response = http.post(
        f"{PATH}/confirm",
        json={
            **DRAFT,
            "request_id": str(DOCUMENT),
            "expected_version": 1,
            "expected_digest": "a" * 64,
            "evidence_checked": True,
        },
    )
    assert response.status_code == 200 and response.json()["version"] == 2
    assert service.confirm.call_args.args[1:4] == (PROJECT, SUPPLIER, RECORD)


def test_reply_http_rejects_scope_overposting_and_missing_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http, service = client(monkeypatch)
    assert (
        http.post(f"{PATH}/preview", json={**DRAFT, "tenant_id": str(PROJECT)}).status_code == 422
    )
    assert (
        http.post(
            f"{PATH}/confirm",
            json={
                **DRAFT,
                "request_id": str(DOCUMENT),
                "expected_version": 1,
                "expected_digest": "a" * 64,
                "evidence_checked": False,
            },
        ).status_code
        == 422
    )
    service.preview.assert_not_called()
    service.confirm.assert_not_called()


def test_reply_http_keeps_version_conflict_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    http, service = client(monkeypatch)
    service.preview.side_effect = ProductWorkError("原事项来源已变化")
    response = http.post(f"{PATH}/preview", json=DRAFT)
    assert response.status_code == 409
    assert response.json()["detail"]["message"] == "原事项来源已变化"
