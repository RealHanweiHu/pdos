from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text, update

from app.auth.tokens import TokenCodec
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.main import app
from app.settings import get_settings

SERVER_ROOT = Path(__file__).resolve().parents[1]
TEST_JWT_SECRET = "test-only-jwt-secret-that-is-at-least-32-bytes"
SETUP_PAYLOAD = {
    "tenant_slug": "beepump",
    "tenant_name": "Beehive Technology",
    "username": "owner",
    "password": "correct horse battery staple",
    "display_name": "Initial Owner",
}


@pytest.fixture(autouse=True)
def isolated_auth_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    test_url = configured_test_database_url()
    monkeypatch.setenv("DATABASE_URL", test_url)
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
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


def test_setup_login_and_current_user_follow_the_real_http_path(
    client: TestClient,
    isolated_auth_database: str,
) -> None:
    status_response = client.get("/api/setup/status")
    assert status_response.status_code == 200
    assert status_response.json() == {"needs_setup": True}

    setup_response = client.post("/api/setup", json=SETUP_PAYLOAD)
    assert setup_response.status_code == 201
    setup_body = setup_response.json()
    assert setup_body["tenant"]["slug"] == "beepump"
    assert setup_body["user"]["username"] == "owner"
    assert "password" not in str(setup_body).lower()

    second_setup = client.post("/api/setup", json=SETUP_PAYLOAD)
    assert second_setup.status_code == 403
    assert second_setup.json()["detail"]["code"] == "SETUP_ALREADY_COMPLETED"
    assert client.get("/api/setup/status").json() == {"needs_setup": False}

    engine = create_engine(psycopg_database_url(isolated_auth_database))
    try:
        with engine.connect() as connection:
            stored_hash = connection.execute(select(tables.users.c.password_hash)).scalar_one()
            assert stored_hash.startswith("$argon2id$")
            assert SETUP_PAYLOAD["password"] not in stored_hash
    finally:
        engine.dispose()

    login_response = client.post(
        "/api/auth/login",
        json={
            "tenant_slug": "beepump",
            "username": "owner",
            "password": SETUP_PAYLOAD["password"],
        },
    )
    assert login_response.status_code == 200
    token_body = login_response.json()
    assert token_body["token_type"] == "bearer"
    assert token_body["expires_in"] == 1800

    me_response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token_body['access_token']}"},
    )
    assert me_response.status_code == 200
    assert me_response.json()["tenant"]["slug"] == "beepump"
    assert me_response.json()["user"]["username"] == "owner"
    assert "password_hash" not in me_response.text

    engine = create_engine(psycopg_database_url(isolated_auth_database))
    try:
        with engine.connect() as connection:
            event_rows = connection.execute(
                select(
                    tables.events.c.event_type,
                    tables.events.c.payload,
                ).order_by(tables.events.c.id)
            ).mappings()
            audit_rows = connection.execute(
                select(
                    tables.audit_log.c.action,
                    tables.audit_log.c.before_snapshot,
                    tables.audit_log.c.after_snapshot,
                    tables.audit_log.c.context,
                ).order_by(tables.audit_log.c.id)
            ).mappings()
            recorded = {"events": list(event_rows), "audits": list(audit_rows)}
    finally:
        engine.dispose()

    assert [row["event_type"] for row in recorded["events"]] == [
        "TENANT_BOOTSTRAPPED",
        "USER_SIGNED_IN",
    ]
    assert [row["action"] for row in recorded["audits"]] == [
        "tenant.bootstrap",
        "user.sign_in",
    ]
    serialized_records = str(recorded).lower()
    assert SETUP_PAYLOAD["password"] not in serialized_records
    assert "password_hash" not in serialized_records
    assert token_body["access_token"] not in serialized_records


def test_unknown_user_and_wrong_password_are_indistinguishable(client: TestClient) -> None:
    assert client.post("/api/setup", json=SETUP_PAYLOAD).status_code == 201

    wrong_password = client.post(
        "/api/auth/login",
        json={
            "tenant_slug": "beepump",
            "username": "owner",
            "password": "definitely the wrong password",
        },
    )
    unknown_user = client.post(
        "/api/auth/login",
        json={
            "tenant_slug": "beepump",
            "username": "not-a-user",
            "password": "definitely the wrong password",
        },
    )

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()
    assert wrong_password.json()["detail"]["code"] == "INVALID_CREDENTIALS"


def test_user_can_change_own_password_and_revoke_the_current_session(
    client: TestClient,
    isolated_auth_database: str,
) -> None:
    assert client.post("/api/setup", json=SETUP_PAYLOAD).status_code == 201
    login = client.post(
        "/api/auth/login",
        json={
            "tenant_slug": "beepump",
            "username": "owner",
            "password": SETUP_PAYLOAD["password"],
        },
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    rejected = client.post(
        "/api/auth/change-password",
        headers=headers,
        json={
            "current_password": "wrong current password",
            "new_password": "rotated production passphrase",
        },
    )
    assert rejected.status_code == 400
    assert rejected.json()["detail"]["code"] == "INVALID_CURRENT_PASSWORD"

    changed = client.post(
        "/api/auth/change-password",
        headers=headers,
        json={
            "current_password": SETUP_PAYLOAD["password"],
            "new_password": "rotated production passphrase",
        },
    )
    assert changed.status_code == 200
    assert changed.json() == {"changed": True}
    assert "password" not in changed.text.lower()

    revoked = client.get("/api/auth/me", headers=headers)
    assert revoked.status_code == 401
    assert revoked.json()["detail"]["code"] == "INVALID_ACCESS_TOKEN"
    assert (
        client.post(
            "/api/auth/login",
            json={
                "tenant_slug": "beepump",
                "username": "owner",
                "password": SETUP_PAYLOAD["password"],
            },
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login",
            json={
                "tenant_slug": "beepump",
                "username": "owner",
                "password": "rotated production passphrase",
            },
        ).status_code
        == 200
    )

    engine = create_engine(psycopg_database_url(isolated_auth_database))
    try:
        with engine.connect() as connection:
            event = connection.execute(
                select(tables.events.c.payload).where(
                    tables.events.c.event_type == "USER_PASSWORD_CHANGED"
                )
            ).scalar_one()
            audit = (
                connection.execute(
                    select(
                        tables.audit_log.c.before_snapshot,
                        tables.audit_log.c.after_snapshot,
                        tables.audit_log.c.context,
                    ).where(tables.audit_log.c.action == "user.password_change")
                )
                .mappings()
                .one()
            )
    finally:
        engine.dispose()
    assert event == {"credential_version": 2}
    serialized = str({"event": event, "audit": audit}).lower()
    assert SETUP_PAYLOAD["password"] not in serialized
    assert "rotated production passphrase" not in serialized
    assert "password_hash" not in serialized
    assert "argon2" not in serialized


def test_concurrent_setup_requests_have_exactly_one_winner() -> None:
    def run_setup() -> int:
        with TestClient(app) as thread_client:
            return thread_client.post("/api/setup", json=SETUP_PAYLOAD).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(executor.map(lambda _: run_setup(), range(2)))

    assert statuses == [201, 403]


def test_tokens_fail_closed_when_missing_invalid_or_outside_the_tenant_context(
    client: TestClient,
    isolated_auth_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    user_id = UUID(setup["user"]["id"])
    tenant_id = UUID(setup["tenant"]["id"])

    missing = client.get("/api/auth/me")
    invalid = client.get("/api/auth/me", headers={"Authorization": "Bearer invalid-token"})
    assert missing.status_code == invalid.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert invalid.json()["detail"]["code"] == "INVALID_ACCESS_TOKEN"

    codec = TokenCodec(get_settings())
    wrong_tenant_token = codec.issue(user_id=user_id, tenant_id=uuid4()).token
    wrong_tenant = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {wrong_tenant_token}"},
    )
    assert wrong_tenant.status_code == 403
    assert wrong_tenant.json()["detail"]["code"] == "TENANT_CONTEXT_DENIED"

    valid_token = codec.issue(user_id=user_id, tenant_id=tenant_id).token
    engine = create_engine(psycopg_database_url(isolated_auth_database))
    try:
        with engine.begin() as connection:
            connection.execute(
                update(tables.tenants)
                .where(tables.tenants.c.id == tenant_id)
                .values(status="suspended")
            )
    finally:
        engine.dispose()

    suspended = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert suspended.status_code == 403
    assert suspended.json()["detail"]["code"] == "TENANT_CONTEXT_DENIED"


def test_auth_input_is_bounded_and_rejects_unknown_fields(client: TestClient) -> None:
    too_short = client.post(
        "/api/setup",
        json={**SETUP_PAYLOAD, "password": "short"},
    )
    unknown_field = client.post(
        "/api/setup",
        json={**SETUP_PAYLOAD, "unexpected": "not accepted"},
    )

    assert too_short.status_code == 422
    assert unknown_field.status_code == 422
