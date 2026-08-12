from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.auth.passwords import PasswordService
from app.auth.roles import Role
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.main import app
from app.settings import get_settings

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


@pytest.fixture(autouse=True)
def isolated_event_api_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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
            connection.execute(text("TRUNCATE TABLE cehub_core.tenants CASCADE"))
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


def bearer_headers(client: TestClient, *, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def seed_roles_projects_and_events(
    database_url: str,
    *,
    tenant_id: UUID,
    owner_id: UUID,
) -> tuple[UUID, UUID]:
    project_id = uuid4()
    workflow_id = uuid4()
    other_tenant_id = uuid4()
    other_workflow_id = uuid4()
    other_project_id = uuid4()
    password_hash = PasswordService().hash(PASSWORD)
    admin_id = uuid4()
    manager_id = uuid4()
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.users.insert(),
                [
                    {
                        "id": admin_id,
                        "tenant_id": tenant_id,
                        "username": "admin",
                        "display_name": "Administrator",
                        "role": Role.ADMIN,
                        "password_hash": password_hash,
                    },
                    {
                        "id": manager_id,
                        "tenant_id": tenant_id,
                        "username": "manager",
                        "display_name": "Project Manager",
                        "role": Role.PROJECT_MANAGER,
                        "password_hash": password_hash,
                    },
                ],
            )
            connection.execute(
                tables.workflows.insert(),
                {
                    "id": workflow_id,
                    "tenant_id": tenant_id,
                    "code": "event-local",
                    "name": "Local Event Workflow",
                },
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": project_id,
                    "tenant_id": tenant_id,
                    "workflow_id": workflow_id,
                    "code": "PRJ-EVENT-LOCAL",
                    "name": "Local Event Project",
                },
            )
            connection.execute(
                tables.project_members.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "user_id": manager_id,
                    "added_by_user_id": owner_id,
                },
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=owner_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id="project:event-local:created",
                    event_type="PROJECT_CREATED",
                    source="project_service",
                    entity_id=project_id,
                    payload={
                        "project_code": "PRJ-EVENT-LOCAL",
                        "project_name": "Local Event Project",
                    },
                ),
                AuditDraft(
                    action="project.create",
                    after_snapshot={"code": "PRJ-EVENT-LOCAL"},
                ),
            )

            connection.execute(
                tables.tenants.insert(),
                {
                    "id": other_tenant_id,
                    "slug": "other-events",
                    "name": "Other Events",
                },
            )
            connection.execute(
                tables.workflows.insert(),
                {
                    "id": other_workflow_id,
                    "tenant_id": other_tenant_id,
                    "code": "event-other",
                    "name": "Other Event Workflow",
                },
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": other_project_id,
                    "tenant_id": other_tenant_id,
                    "workflow_id": other_workflow_id,
                    "code": "PRJ-EVENT-OTHER",
                    "name": "Other Event Project",
                },
            )
            EventAuditWriter(
                connection,
                tenant_id=other_tenant_id,
                actor_user_id=None,
                project_id=other_project_id,
            ).record(
                EventDraft(
                    event_id="project:event-other:created",
                    event_type="PROJECT_CREATED",
                    source="project_service",
                    entity_id=other_project_id,
                    payload={
                        "project_code": "PRJ-EVENT-OTHER",
                        "project_name": "Other Event Project",
                    },
                ),
                AuditDraft(
                    action="project.create",
                    after_snapshot={"code": "PRJ-EVENT-OTHER"},
                ),
            )
    finally:
        engine.dispose()
    return project_id, other_project_id


def test_external_event_ingress_is_idempotent_rejects_conflicts_and_internal_types(
    client: TestClient,
    isolated_event_api_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    owner_id = UUID(setup["user"]["id"])
    project_id, _ = seed_roles_projects_and_events(
        isolated_event_api_database,
        tenant_id=tenant_id,
        owner_id=owner_id,
    )
    owner_headers = bearer_headers(client, username="owner")
    manager_headers = bearer_headers(client, username="manager")
    occurred_at = datetime(2026, 8, 12, 3, 0, tzinfo=UTC).isoformat()
    request = {
        "project_id": str(project_id),
        "event_id": "external-test-failed-1",
        "event_type": "TEST_FAILED",
        "entity_id": str(uuid4()),
        "payload": {"test_record_id": "TEST-001", "severity": "high"},
        "occurred_at": occurred_at,
    }

    created = client.post("/api/events", headers=manager_headers, json=request)
    replay = client.post("/api/events", headers=manager_headers, json=request)

    assert created.status_code == 201
    assert created.json()["created"] is True
    assert replay.status_code == 200
    assert replay.json()["created"] is False
    assert replay.json()["event"] == created.json()["event"]

    conflict_request = {**request, "payload": {"test_record_id": "TEST-001", "severity": "low"}}
    conflict = client.post("/api/events", headers=manager_headers, json=conflict_request)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "EVENT_IDEMPOTENCY_CONFLICT"

    internal = client.post(
        "/api/events",
        headers=owner_headers,
        json={
            **request,
            "event_id": "impersonation-attempt",
            "event_type": "PROJECT_CREATED",
            "payload": {"project_code": "FAKE", "project_name": "Fake"},
        },
    )
    assert internal.status_code == 422
    assert internal.json()["detail"]["code"] == "EXTERNAL_EVENT_TYPE_DENIED"

    engine = create_engine(psycopg_database_url(isolated_event_api_database))
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM cehub_event.events "
                        "WHERE event_id = 'external-test-failed-1'"
                    )
                ).scalar_one()
                == 1
            )
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM cehub_audit.audit_log "
                        "WHERE event_id = 'external-test-failed-1'"
                    )
                ).scalar_one()
                == 1
            )
    finally:
        engine.dispose()


def test_event_catalog_and_stream_are_admin_only_tenant_bound_and_cursor_stable(
    client: TestClient,
    isolated_event_api_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    owner_id = UUID(setup["user"]["id"])
    project_id, other_project_id = seed_roles_projects_and_events(
        isolated_event_api_database,
        tenant_id=tenant_id,
        owner_id=owner_id,
    )
    owner_headers = bearer_headers(client, username="owner")
    admin_headers = bearer_headers(client, username="admin")
    manager_headers = bearer_headers(client, username="manager")

    catalog = client.get("/api/events/catalog", headers=owner_headers)
    assert catalog.status_code == 200
    assert catalog.headers["cache-control"] == "no-store"
    definitions = {item["event_type"]: item for item in catalog.json()["items"]}
    assert definitions["PROJECT_CREATED"] == {
        "event_type": "PROJECT_CREATED",
        "version": 1,
        "entity": "project",
        "producer": "project_service",
        "consumers": ["timeline_projection", "agent_dispatcher"],
        "payload_schema": {
            "type": "object",
            "properties": {
                "project_code": {"type": "string"},
                "project_name": {"type": "string"},
            },
            "required": ["project_code", "project_name"],
            "additionalProperties": False,
        },
        "idempotency": "unique(source,event_id); reuse event_id on retry",
        "implemented_in_sprint_1": True,
    }
    assert definitions["GATE_APPROVED"]["implemented_in_sprint_1"] is False

    first = client.get("/api/events?limit=2", headers=admin_headers)
    assert first.status_code == 200
    first_body = first.json()
    assert len(first_body["items"]) == 2
    assert [item["id"] for item in first_body["items"]] == sorted(
        item["id"] for item in first_body["items"]
    )
    assert first_body["has_more"] is True
    assert first_body["next_after_id"] == first_body["items"][-1]["id"]
    assert all(item["consumers"] for item in first_body["items"])

    second = client.get(
        f"/api/events?limit=100&after_id={first_body['next_after_id']}",
        headers=admin_headers,
    )
    second_body = second.json()
    assert second.status_code == 200
    assert not (
        {item["id"] for item in first_body["items"]} & {item["id"] for item in second_body["items"]}
    )
    assert all(item["id"] > first_body["next_after_id"] for item in second_body["items"])
    assert all(item["event_id"] != "project:event-other:created" for item in second_body["items"])

    filtered = client.get(
        f"/api/events?event_type=PROJECT_CREATED&project_id={project_id}",
        headers=owner_headers,
    )
    assert filtered.status_code == 200
    assert [item["event_id"] for item in filtered.json()["items"]] == [
        "project:event-local:created"
    ]

    unknown_project = client.get(f"/api/events?project_id={uuid4()}", headers=owner_headers)
    cross_tenant_project = client.get(
        f"/api/events?project_id={other_project_id}", headers=owner_headers
    )
    assert unknown_project.status_code == cross_tenant_project.status_code == 404
    assert unknown_project.json() == cross_tenant_project.json()
    assert unknown_project.json()["detail"]["code"] == "PROJECT_NOT_FOUND"

    for path in ("/api/events", "/api/events/catalog"):
        assert client.get(path, headers=manager_headers).status_code == 403
        assert client.get(path).status_code == 401
