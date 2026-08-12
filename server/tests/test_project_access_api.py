from __future__ import annotations

import os
from collections.abc import Iterator
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
def isolated_project_access_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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
        cached_engine = get_engine()
        cached_engine.dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def bearer_headers(
    client: TestClient, *, username: str, password: str = PASSWORD
) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": username, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def seed_project_and_engineer(
    database_url: str,
    *,
    tenant_id: UUID,
) -> tuple[UUID, UUID, UUID]:
    engine = create_engine(psycopg_database_url(database_url))
    workflow_id = uuid4()
    project_id = uuid4()
    other_project_id = uuid4()
    engineer_id = uuid4()
    other_tenant_id = uuid4()
    other_workflow_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.users.insert(),
                {
                    "id": engineer_id,
                    "tenant_id": tenant_id,
                    "username": "engineer",
                    "display_name": "Project Engineer",
                    "role": Role.ENGINEER,
                    "password_hash": PasswordService().hash(PASSWORD),
                },
            )
            connection.execute(
                tables.workflows.insert(),
                {
                    "id": workflow_id,
                    "tenant_id": tenant_id,
                    "code": "npd",
                    "name": "NPD",
                    "version": 1,
                },
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": project_id,
                    "tenant_id": tenant_id,
                    "workflow_id": workflow_id,
                    "code": "PDOS-001",
                    "name": "PDOS",
                },
            )
            connection.execute(
                tables.tenants.insert(),
                {
                    "id": other_tenant_id,
                    "slug": "other-tenant",
                    "name": "Other Tenant",
                },
            )
            connection.execute(
                tables.workflows.insert(),
                {
                    "id": other_workflow_id,
                    "tenant_id": other_tenant_id,
                    "code": "npd",
                    "name": "NPD",
                    "version": 1,
                },
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": other_project_id,
                    "tenant_id": other_tenant_id,
                    "workflow_id": other_workflow_id,
                    "code": "OTHER-001",
                    "name": "Other Project",
                },
            )
    finally:
        engine.dispose()
    return project_id, other_project_id, engineer_id


def test_project_access_http_path_is_tenant_bound_and_membership_gated(
    client: TestClient,
    isolated_project_access_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD)
    assert setup.status_code == 201
    tenant_id = UUID(setup.json()["tenant"]["id"])
    owner_id = UUID(setup.json()["user"]["id"])
    assert setup.json()["user"]["role"] == Role.OWNER

    project_id, other_project_id, engineer_id = seed_project_and_engineer(
        isolated_project_access_database,
        tenant_id=tenant_id,
    )
    owner_headers = bearer_headers(client, username="owner")
    engineer_headers = bearer_headers(client, username="engineer")

    owner_access = client.get(f"/api/projects/{project_id}/access", headers=owner_headers)
    assert owner_access.status_code == 200
    assert owner_access.headers["cache-control"] == "no-store"
    assert owner_access.json()["role"] == Role.OWNER
    assert "tenant.manage" in owner_access.json()["allowed_actions"]

    denied_non_member = client.get(
        f"/api/projects/{project_id}/access",
        headers=engineer_headers,
    )
    denied_cross_tenant = client.get(
        f"/api/projects/{other_project_id}/access",
        headers=owner_headers,
    )
    assert denied_non_member.status_code == denied_cross_tenant.status_code == 403
    assert denied_non_member.json() == denied_cross_tenant.json()
    assert denied_non_member.json()["detail"]["code"] == "OBJECT_PERMISSION_DENIED"
    assert client.get(f"/api/projects/{project_id}/access").status_code == 401

    engine = create_engine(psycopg_database_url(isolated_project_access_database))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.project_members.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "user_id": engineer_id,
                    "added_by_user_id": owner_id,
                },
            )
    finally:
        engine.dispose()

    member_access = client.get(
        f"/api/projects/{project_id}/access",
        headers=engineer_headers,
    )
    assert member_access.status_code == 200
    assert member_access.json()["allowed_actions"] == [
        "ai_chat.use",
        "change.edit",
        "change.view",
        "development_case.view",
        "document.analyze",
        "finding.apply",
        "finding.review",
        "finding.view",
        "gate.sign",
        "gate.view",
        "handoff.view",
        "product_engineering.edit",
        "product_engineering.view",
        "project.view",
        "requirement.view",
        "risk_suggestion.create",
        "work_item.edit",
        "work_item.view",
    ]
