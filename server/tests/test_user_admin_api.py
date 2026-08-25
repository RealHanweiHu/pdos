from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text

from app.auth.passwords import PasswordService
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.main import app
from app.settings import get_settings

SERVER_ROOT = Path(__file__).resolve().parents[1]
SETUP = {
    "tenant_slug": "beepump",
    "tenant_name": "Beehive Technology",
    "username": "owner",
    "password": "correct horse battery staple",
    "display_name": "Initial Owner",
}


@pytest.fixture(autouse=True)
def isolated_user_admin_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    test_url = configured_test_database_url()
    monkeypatch.setenv("DATABASE_URL", test_url)
    monkeypatch.setenv("JWT_SECRET", "test-only-jwt-secret-that-is-at-least-32-bytes")
    monkeypatch.setenv("JWT_ISSUER", "pdos-test")
    monkeypatch.setenv("JWT_AUDIENCE", "pdos-test-client")
    monkeypatch.setenv("JWT_ACCESS_TOKEN_MINUTES", "30")
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


def _login(client: TestClient, *, username: str, password: str) -> str:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": username, "password": password},
    )
    assert response.status_code == 200
    return str(response.json()["access_token"])


def _login_headers(client: TestClient, *, username: str, password: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_login(client, username=username, password=password)}"}


def _owner_headers(client: TestClient) -> dict[str, str]:
    assert client.post("/api/setup", json=SETUP).status_code == 201
    return _login_headers(client, username="owner", password=SETUP["password"])


def _create_user(
    client: TestClient,
    headers: dict[str, str],
    *,
    username: str,
    role: str,
    password: str = "temporary passphrase 2026",
) -> dict[str, object]:
    response = client.post(
        "/api/admin/users",
        headers=headers,
        json={
            "username": username,
            "display_name": username.replace("-", " ").title(),
            "email": f"{username}@example.com",
            "role": role,
            "password": password,
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


def test_owner_creates_and_lists_tenant_users_without_exposing_credentials(
    client: TestClient,
    isolated_user_admin_database: str,
) -> None:
    owner_headers = _owner_headers(client)

    created = _create_user(client, owner_headers, username="quality-lead", role="quality")
    assert created["username"] == "quality-lead"
    assert created["role"] == "quality"
    assert created["is_active"] is True
    assert "password" not in str(created).lower()
    assert _login(client, username="quality-lead", password="temporary passphrase 2026")

    listed = client.get("/api/admin/users", headers=owner_headers)
    assert listed.status_code == 200
    assert [user["username"] for user in listed.json()["items"]] == ["owner", "quality-lead"]
    assert all("password" not in str(user).lower() for user in listed.json()["items"])

    engine = create_engine(psycopg_database_url(isolated_user_admin_database))
    try:
        with engine.connect() as connection:
            evidence = {
                "events": list(
                    connection.execute(
                        select(tables.events.c.event_type, tables.events.c.payload).order_by(
                            tables.events.c.id
                        )
                    ).mappings()
                ),
                "audits": list(
                    connection.execute(
                        select(
                            tables.audit_log.c.action,
                            tables.audit_log.c.before_snapshot,
                            tables.audit_log.c.after_snapshot,
                            tables.audit_log.c.context,
                        ).order_by(tables.audit_log.c.id)
                    ).mappings()
                ),
            }
    finally:
        engine.dispose()
    assert "USER_CREATED" in [row["event_type"] for row in evidence["events"]]
    assert "user.create" in [row["action"] for row in evidence["audits"]]
    serialized = str(evidence).lower()
    assert "temporary passphrase 2026" not in serialized
    assert "password_hash" not in serialized


def test_admin_cannot_manage_privileged_accounts_and_non_admins_have_no_access(
    client: TestClient,
) -> None:
    owner_headers = _owner_headers(client)
    _create_user(client, owner_headers, username="tenant-admin", role="admin")
    engineer = _create_user(client, owner_headers, username="engineer-one", role="engineer")
    admin_headers = _login_headers(
        client,
        username="tenant-admin",
        password="temporary passphrase 2026",
    )

    create_owner = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "username": "forged-owner",
            "display_name": "Forged Owner",
            "role": "owner",
            "password": "temporary passphrase 2026",
        },
    )
    assert create_owner.status_code == 403
    assert create_owner.json()["detail"]["code"] == "PRIVILEGED_ROLE_REQUIRES_OWNER"

    owner_id = client.get("/api/admin/users", headers=owner_headers).json()["items"][0]["id"]
    manage_owner = client.patch(
        f"/api/admin/users/{owner_id}", headers=admin_headers, json={"is_active": False}
    )
    assert manage_owner.status_code == 403
    assert manage_owner.json()["detail"]["code"] == "PRIVILEGED_ACCOUNT_REQUIRES_OWNER"

    engineer_headers = _login_headers(
        client,
        username="engineer-one",
        password="temporary passphrase 2026",
    )
    assert client.get("/api/admin/users", headers=engineer_headers).status_code == 403
    assert (
        client.patch(
            f"/api/admin/users/{engineer['id']}",
            headers=engineer_headers,
            json={"role": "owner"},
        ).status_code
        == 403
    )


def test_user_updates_are_tenant_bound_and_preserve_an_active_owner(
    client: TestClient,
    isolated_user_admin_database: str,
) -> None:
    owner_headers = _owner_headers(client)
    owner = client.get("/api/admin/users", headers=owner_headers).json()["items"][0]
    engineer = _create_user(client, owner_headers, username="engineer-two", role="engineer")

    self_demote = client.patch(
        f"/api/admin/users/{owner['id']}", headers=owner_headers, json={"role": "admin"}
    )
    assert self_demote.status_code == 409
    assert self_demote.json()["detail"]["code"] == "SELF_ROLE_OR_STATUS_CHANGE_FORBIDDEN"

    duplicate = client.post(
        "/api/admin/users",
        headers=owner_headers,
        json={
            "username": "engineer-two",
            "display_name": "Duplicate",
            "role": "quality",
            "password": "temporary passphrase 2026",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "USERNAME_ALREADY_EXISTS"

    updated = client.patch(
        f"/api/admin/users/{engineer['id']}",
        headers=owner_headers,
        json={"display_name": "Product Engineer", "role": "project_manager"},
    )
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Product Engineer"
    assert updated.json()["role"] == "project_manager"

    engine = create_engine(psycopg_database_url(isolated_user_admin_database))
    try:
        with engine.connect() as connection:
            write_count_before_noop = (
                connection.execute(
                    select(tables.audit_log.c.id).where(tables.audit_log.c.action == "user.update")
                )
                .scalars()
                .all()
            )
    finally:
        engine.dispose()
    noop = client.patch(
        f"/api/admin/users/{engineer['id']}",
        headers=owner_headers,
        json={"display_name": "Product Engineer", "role": "project_manager"},
    )
    assert noop.status_code == 200
    engine = create_engine(psycopg_database_url(isolated_user_admin_database))
    try:
        with engine.connect() as connection:
            write_count_after_noop = (
                connection.execute(
                    select(tables.audit_log.c.id).where(tables.audit_log.c.action == "user.update")
                )
                .scalars()
                .all()
            )
    finally:
        engine.dispose()
    assert write_count_after_noop == write_count_before_noop

    other_tenant_id, other_user_id = uuid4(), uuid4()
    engine = create_engine(psycopg_database_url(isolated_user_admin_database))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": other_tenant_id, "slug": "other", "name": "Other Tenant"},
            )
            connection.execute(
                tables.users.insert(),
                {
                    "id": other_user_id,
                    "tenant_id": other_tenant_id,
                    "username": "other-owner",
                    "display_name": "Other Owner",
                    "role": "owner",
                    "password_hash": PasswordService().hash("other tenant password"),
                },
            )
    finally:
        engine.dispose()

    hidden = client.patch(
        f"/api/admin/users/{other_user_id}",
        headers=owner_headers,
        json={"display_name": "Cross Tenant"},
    )
    assert hidden.status_code == 404
    assert hidden.json()["detail"]["code"] == "USER_NOT_FOUND"


def test_password_reset_revokes_old_password_and_access_token(
    client: TestClient,
    isolated_user_admin_database: str,
) -> None:
    owner_headers = _owner_headers(client)
    user = _create_user(client, owner_headers, username="quality-two", role="quality")
    old_token = _login(client, username="quality-two", password="temporary passphrase 2026")

    reset = client.post(
        f"/api/admin/users/{user['id']}/reset-password",
        headers=owner_headers,
        json={"password": "rotated production passphrase"},
    )
    assert reset.status_code == 200
    assert "password" not in reset.text.lower()

    old_session = client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert old_session.status_code == 401
    assert old_session.json()["detail"]["code"] == "INVALID_ACCESS_TOKEN"
    assert (
        client.post(
            "/api/auth/login",
            json={
                "tenant_slug": "beepump",
                "username": "quality-two",
                "password": "temporary passphrase 2026",
            },
        ).status_code
        == 401
    )
    assert _login(client, username="quality-two", password="rotated production passphrase")

    engine = create_engine(psycopg_database_url(isolated_user_admin_database))
    try:
        with engine.connect() as connection:
            user_row = (
                connection.execute(
                    select(tables.users).where(tables.users.c.id == UUID(str(user["id"])))
                )
                .mappings()
                .one()
            )
            reset_events = list(
                connection.execute(
                    select(tables.events.c.payload).where(
                        tables.events.c.event_type == "USER_PASSWORD_RESET"
                    )
                ).scalars()
            )
    finally:
        engine.dispose()
    assert user_row["auth_version"] == 2
    assert reset_events == [{"credential_version": 2}]
