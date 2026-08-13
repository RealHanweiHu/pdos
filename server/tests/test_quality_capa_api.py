from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text

from app.auth.passwords import PasswordService
from app.auth.roles import Role
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
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
def isolated_quality_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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


def login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def seed_project_and_engineer(
    database_url: str,
    tenant_id: UUID,
    owner_id: UUID,
) -> tuple[UUID, UUID]:
    workflow_id, stage_id, project_id, engineer_id = uuid4(), uuid4(), uuid4(), uuid4()
    requirement_id, case_id = uuid4(), uuid4()
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.requirements.insert(),
                {
                    "id": requirement_id,
                    "tenant_id": tenant_id,
                    "created_by_user_id": owner_id,
                    "code": "REQ-QA",
                    "title": "Quality",
                    "status": "converted",
                },
            )
            connection.execute(
                tables.development_cases.insert(),
                {
                    "id": case_id,
                    "tenant_id": tenant_id,
                    "requirement_id": requirement_id,
                    "created_by_user_id": owner_id,
                    "code": "CASE-QA",
                    "title": "Quality",
                    "status": "converted",
                },
            )
            connection.execute(
                tables.workflows.insert(),
                {"id": workflow_id, "tenant_id": tenant_id, "code": "qa", "name": "QA"},
            )
            connection.execute(
                tables.stages.insert(),
                {
                    "id": stage_id,
                    "tenant_id": tenant_id,
                    "workflow_id": workflow_id,
                    "code": "mp",
                    "name": "MP",
                    "sequence": 1,
                },
            )
            connection.execute(
                tables.users.insert(),
                {
                    "id": engineer_id,
                    "tenant_id": tenant_id,
                    "username": "engineer",
                    "display_name": "Quality Engineer",
                    "role": Role.ENGINEER.value,
                    "password_hash": PasswordService().hash(PASSWORD),
                },
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": project_id,
                    "tenant_id": tenant_id,
                    "development_case_id": case_id,
                    "workflow_id": workflow_id,
                    "current_stage_id": stage_id,
                    "owner_user_id": owner_id,
                    "code": "PRJ-QA",
                    "name": "Quality project",
                    "status": "active",
                },
            )
            connection.execute(
                tables.project_members.insert(),
                [
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "user_id": owner_id,
                        "added_by_user_id": owner_id,
                    },
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "user_id": engineer_id,
                        "added_by_user_id": owner_id,
                    },
                ],
            )
    finally:
        engine.dispose()
    return project_id, engineer_id


def test_engineer_creates_and_lists_complaint_with_same_transaction_event_audit(
    client: TestClient,
    isolated_quality_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id, owner_id = UUID(setup["tenant"]["id"]), UUID(setup["user"]["id"])
    project_id, engineer_id = seed_project_and_engineer(
        isolated_quality_database,
        tenant_id,
        owner_id,
    )

    response = client.post(
        f"/api/projects/{project_id}/quality/complaints",
        headers=login(client, "engineer"),
        json={
            "title": "Field connector intermittent",
            "description": "Connector opens after thermal cycling.",
            "source": "field",
            "severity": "high",
            "occurred_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
            "owner_user_id": str(engineer_id),
            "customer_reference": "FIELD-2026-08",
            "affected_scope": "Lot C4s",
        },
    )

    assert response.status_code == 201
    complaint = response.json()
    assert complaint["code"].startswith("CMP-")
    assert complaint["status"] == "open"
    assert complaint["reported_by_user_id"] == str(engineer_id)
    assert complaint["owner_user_id"] == str(engineer_id)

    listed = client.get(
        f"/api/projects/{project_id}/quality/complaints",
        headers=login(client, "engineer"),
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [complaint["id"]]

    engine = create_engine(psycopg_database_url(isolated_quality_database))
    try:
        with engine.connect() as connection:
            event = connection.execute(
                select(tables.events).where(
                    tables.events.c.tenant_id == tenant_id,
                    tables.events.c.entity_id == UUID(complaint["id"]),
                )
            ).mappings().one()
            audit = connection.execute(
                select(tables.audit_log).where(
                    tables.audit_log.c.tenant_id == tenant_id,
                    tables.audit_log.c.entity_id == UUID(complaint["id"]),
                )
            ).mappings().one()
    finally:
        engine.dispose()
    assert event["event_type"] == "COMPLAINT_CREATED"
    assert event["source"] == "quality_service"
    assert event["payload"] == {"complaint_id": complaint["id"], "severity": "high"}
    assert audit["event_id"] == event["event_id"]
    assert audit["action"] == "quality.complaint.create"
