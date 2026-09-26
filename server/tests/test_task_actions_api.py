"""Task action-source contract tests (vNext V1-B5, D28)."""

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
from sqlalchemy import Engine, Table, create_engine, select, text

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
NOW = datetime(2026, 8, 26, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolated_action_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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


def bearer_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": "owner", "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def seed_project(client: TestClient, database_url: str) -> tuple[Engine, UUID, UUID, UUID, UUID]:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    owner_id = UUID(setup["user"]["id"])
    engine = create_engine(psycopg_database_url(database_url))
    with engine.begin() as connection:

        def insert(table: Table, values: dict[str, Any]) -> UUID:
            values.setdefault("id", uuid4())
            values.setdefault("tenant_id", tenant_id)
            connection.execute(table.insert(), values)
            return cast(UUID, values["id"])

        workflow_id = insert(tables.workflows, {"code": "WF-ACT", "name": "Workflow"})
        project_id = insert(
            tables.projects,
            {
                "workflow_id": workflow_id,
                "owner_user_id": owner_id,
                "code": "PRJ-ACT",
                "name": "Action project",
                "status": "active",
            },
        )
        insert(
            tables.project_members,
            {"project_id": project_id, "user_id": owner_id, "added_by_user_id": owner_id},
        )
        issue_id = insert(
            tables.issues,
            {
                "project_id": project_id,
                "reported_by_user_id": owner_id,
                "title": "Thermal drift",
                "status": "analysis",
                "severity": "high",
            },
        )
    return engine, tenant_id, owner_id, project_id, issue_id


def test_issue_action_requires_source_and_completion_evidence(
    client: TestClient, isolated_action_database: str
) -> None:
    engine, _, _, project_id, issue_id = seed_project(client, isolated_action_database)
    try:
        headers = bearer_headers(client)
        tasks_url = f"/api/projects/{project_id}/tasks"

        orphan = client.post(
            tasks_url,
            headers=headers,
            json={"title": "Orphan action", "kind": "issue_action", "dependency_task_ids": []},
        )
        assert orphan.status_code == 404

        created = client.post(
            tasks_url,
            headers=headers,
            json={
                "title": "Verify thermal fix",
                "kind": "issue_action",
                "source_entity_id": str(issue_id),
                "expected_output": "Retest report attached",
                "dependency_task_ids": [],
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["kind"] == "issue_action"
        assert body["source_entity"] == "issues"
        assert body["source_entity_id"] == str(issue_id)

        task_id = body["id"]
        transitions = f"{tasks_url}/{task_id}/transitions"
        assert (
            client.post(transitions, headers=headers, json={"to_status": "in_progress"}).status_code
            == 200
        )

        no_evidence = client.post(transitions, headers=headers, json={"to_status": "done"})
        assert no_evidence.status_code == 409
        assert no_evidence.json()["detail"]["code"] == "TASK_EVIDENCE_REQUIRED"

        with engine.connect() as connection:
            issue_before = connection.execute(
                select(tables.issues.c.updated_at).where(tables.issues.c.id == issue_id)
            ).scalar_one()

        done = client.post(
            transitions,
            headers=headers,
            json={"to_status": "done", "completion_evidence_ref": "Retest report TR-88"},
        )
        assert done.status_code == 200
        assert done.json()["completion_evidence_ref"] == "Retest report TR-88"

        with engine.connect() as connection:
            issue_after = connection.execute(
                select(tables.issues.c.updated_at).where(tables.issues.c.id == issue_id)
            ).scalar_one()
            audit = connection.execute(
                text(
                    "SELECT count(*) FROM cehub_audit.audit_log "
                    "WHERE action = 'issue_action.completed'"
                )
            ).scalar_one()
        assert issue_after > issue_before
        assert audit == 1
    finally:
        engine.dispose()


def test_plain_tasks_keep_existing_completion_semantics(
    client: TestClient, isolated_action_database: str
) -> None:
    engine, _, _, project_id, _ = seed_project(client, isolated_action_database)
    try:
        headers = bearer_headers(client)
        tasks_url = f"/api/projects/{project_id}/tasks"
        created = client.post(
            tasks_url,
            headers=headers,
            json={"title": "Plain task", "dependency_task_ids": []},
        ).json()
        transitions = f"{tasks_url}/{created['id']}/transitions"
        assert (
            client.post(transitions, headers=headers, json={"to_status": "in_progress"}).status_code
            == 200
        )
        done = client.post(transitions, headers=headers, json={"to_status": "done"})
        assert done.status_code == 200
        assert done.json()["kind"] == "task"
    finally:
        engine.dispose()
