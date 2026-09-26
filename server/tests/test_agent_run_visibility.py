"""Agent run visibility endpoint tests (vNext V1-A9)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Table, create_engine, text

from app.auth.passwords import PasswordService
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.main import app
from app.settings import get_settings
from tests.db_cleanup import clear_test_tenants

SERVER_ROOT = Path(__file__).resolve().parents[1]
TEST_JWT_SECRET = "test-only-jwt-secret-that-is-at-least-32-bytes"
PASSWORD = "correct horse battery staple"
SETUP_PAYLOAD = {
    "tenant_slug": "beepump",
    "tenant_name": "Beehive Technology",
    "username": "owner",
    "password": PASSWORD,
    "display_name": "Initial Owner",
}
NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolated_run_visibility_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    test_url = configured_test_database_url()
    monkeypatch.setenv("DATABASE_URL", test_url)
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("JWT_ISSUER", "pdos-test")
    monkeypatch.setenv("JWT_AUDIENCE", "pdos-test-client")
    get_settings.cache_clear()
    get_engine.cache_clear()
    os.environ["DATABASE_URL"] = test_url
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            clear_test_tenants(connection)
        yield test_url
    finally:
        engine.dispose()
        get_engine().dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def bearer_headers(client: TestClient, *, username: str = "owner") -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def seed(client: TestClient, database_url: str) -> tuple[UUID, UUID]:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    owner_id = UUID(setup["user"]["id"])
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:

            def insert(table: Table, values: dict[str, Any]) -> UUID:
                values.setdefault("id", uuid4())
                values.setdefault("tenant_id", tenant_id)
                connection.execute(table.insert(), values)
                return cast(UUID, values["id"])

            engineer_id = insert(
                tables.users,
                {
                    "username": "engineer",
                    "display_name": "Engineer",
                    "role": "engineer",
                    "password_hash": PasswordService().hash(PASSWORD),
                    "is_active": True,
                },
            )
            workflow_id = insert(tables.workflows, {"code": "WF-RUN", "name": "Workflow"})
            project_id = insert(
                tables.projects,
                {
                    "workflow_id": workflow_id,
                    "owner_user_id": owner_id,
                    "code": "PRJ-RUN",
                    "name": "Run project",
                    "status": "active",
                },
            )
            insert(
                tables.project_members,
                {"project_id": project_id, "user_id": engineer_id, "added_by_user_id": owner_id},
            )
            subscription_id = insert(
                tables.agent_subscriptions,
                {"project_id": project_id, "agent_key": "project_intelligence"},
            )

            def run(status: str, created_at: datetime, **extra: Any) -> UUID:
                return insert(
                    tables.agent_runs,
                    {
                        "project_id": project_id,
                        "subscription_id": subscription_id,
                        "agent_key": "project_intelligence",
                        "status": status,
                        "window_started_at": created_at,
                        "window_ended_at": created_at,
                        "first_event_row_id": 1,
                        "last_event_row_id": 1,
                        "event_count": 1,
                        "event_row_ids": [1],
                        "created_at": created_at,
                        **extra,
                    },
                )

            run("queued", datetime(2026, 8, 25, 11, 0, tzinfo=UTC))
            run_id = run(
                "succeeded",
                datetime(2026, 8, 25, 12, 0, tzinfo=UTC),
                started_at=NOW,
                completed_at=NOW,
            )
            invocation_id = insert(
                tables.model_invocations,
                {
                    "project_id": project_id,
                    "run_id": run_id,
                    "agent_key": "project_intelligence",
                    "prompt_version": "v1",
                    "provider": "minimax",
                    "model": "fake-model",
                    "protocol": "openai-compatible",
                    "status": "succeeded",
                },
            )
            insert(
                tables.findings,
                {
                    "project_id": project_id,
                    "run_id": run_id,
                    "model_invocation_id": invocation_id,
                    "agent_key": "project_intelligence",
                    "finding_type": "risk_suggestion",
                    "origin_key": f"origin-{uuid4().hex[:12]}",
                    "title": "Pending suggestion",
                    "summary": "Evidence supports a risk.",
                    "proposed_payload": {"title": "Pending suggestion"},
                    "evidence_event_ids": [1],
                    "confidence_basis_points": 8000,
                    "preflight_version": "finding-preflight-v2",
                },
            )
    finally:
        engine.dispose()
    return tenant_id, project_id


def test_run_visibility_lists_recent_runs_and_pending_findings(
    client: TestClient, isolated_run_visibility_database: str
) -> None:
    _, project_id = seed(client, isolated_run_visibility_database)
    headers = bearer_headers(client, username="engineer")

    response = client.get(f"/api/ai/projects/{project_id}/runs", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert [item["status"] for item in body["items"]] == ["succeeded", "queued"]
    assert body["items"][0]["event_count"] == 1
    assert body["pending_review_findings"] == 1


def test_run_visibility_is_membership_scoped(
    client: TestClient, isolated_run_visibility_database: str
) -> None:
    _, project_id = seed(client, isolated_run_visibility_database)
    outsider_engine = create_engine(psycopg_database_url(isolated_run_visibility_database))
    try:
        with outsider_engine.begin() as connection:
            tenant_id = connection.execute(text("SELECT id FROM cehub_core.tenants")).scalar_one()
            connection.execute(
                tables.users.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "username": "outsider",
                    "display_name": "Outsider",
                    "role": "engineer",
                    "password_hash": PasswordService().hash(PASSWORD),
                    "is_active": True,
                },
            )
    finally:
        outsider_engine.dispose()

    response = client.get(
        f"/api/ai/projects/{project_id}/runs",
        headers=bearer_headers(client, username="outsider"),
    )
    assert response.status_code in (403, 404)
