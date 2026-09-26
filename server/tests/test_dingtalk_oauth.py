from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update

from app.api.dingtalk import get_dingtalk_http_client
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.integrations.dingtalk_client import ME_URL, TOKEN_URL
from app.main import app
from app.settings import get_settings
from tests.db_cleanup import clear_test_tenants

SERVER_ROOT = Path(__file__).resolve().parents[1]
JWT_SECRET = "dingtalk-oauth-test-jwt-secret-is-at-least-32-bytes"
CLIENT_ID = "ding-test-client"
CLIENT_SECRET = "ding-test-client-secret"
CORP_ID = "ding-test-corp"
OPEN_ID = "ding-test-open-id"
SETUP = {
    "tenant_slug": "beepump",
    "tenant_name": "Beehive Technology",
    "username": "owner",
    "password": "correct horse battery staple",
    "display_name": "Initial Owner",
}


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    test_url = configured_test_database_url()
    monkeypatch.setenv("DATABASE_URL", test_url)
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("JWT_ISSUER", "pdos-test")
    monkeypatch.setenv("JWT_AUDIENCE", "pdos-test-client")
    monkeypatch.setenv("PDOS_DINGTALK_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("PDOS_DINGTALK_CLIENT_SECRET", CLIENT_SECRET)
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
        cached_engine = get_engine()
        cached_engine.dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()
        app.dependency_overrides.clear()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _setup(client: TestClient, database_url: str) -> tuple[UUID, UUID, str]:
    setup = client.post("/api/setup", json=SETUP)
    assert setup.status_code == 201
    tenant_id = UUID(setup.json()["tenant"]["id"])
    user_id = UUID(setup.json()["user"]["id"])
    login = client.post(
        "/api/auth/login",
        json={
            "tenant_slug": SETUP["tenant_slug"],
            "username": SETUP["username"],
            "password": SETUP["password"],
        },
    )
    assert login.status_code == 200
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.dingtalk_tenant_bindings.insert().values(
                    tenant_id=tenant_id,
                    corp_id=CORP_ID,
                    client_id=CLIENT_ID,
                    oauth_redirect_uri=(
                        "https://pdos.example/api/integrations/dingtalk/oauth/callback"
                    ),
                    callback_route_key="test-event-callback",
                    card_callback_route_key="test-card-callback",
                    status="active",
                    configured_by_user_id=user_id,
                )
            )
    finally:
        engine.dispose()
    return tenant_id, user_id, login.json()["access_token"]


def _state_from(response: httpx2.Response) -> str:
    assert response.status_code == 200
    url = response.json()["authorization_url"]
    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "login.dingtalk.com"
    query = parse_qs(parsed.query)
    assert query["client_id"] == [CLIENT_ID]
    assert query["scope"] == ["openid corpid"]
    assert query["prompt"] == ["consent"]
    state = query["state"][0]
    assert isinstance(state, str)
    return state


def _fake_http_client(*, corp_id: str = CORP_ID, open_id: str = OPEN_ID) -> httpx2.Client:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if str(request.url) == TOKEN_URL:
            body = json.loads(request.content)
            assert body == {
                "clientId": CLIENT_ID,
                "clientSecret": CLIENT_SECRET,
                "code": "valid-code",
                "grantType": "authorization_code",
            }
            return httpx2.Response(
                200,
                json={
                    "accessToken": "ephemeral-user-token",
                    "corpId": corp_id,
                    "expireIn": 7200,
                },
            )
        if str(request.url) == ME_URL:
            assert request.headers["x-acs-dingtalk-access-token"] == "ephemeral-user-token"
            return httpx2.Response(
                200,
                json={
                    "openId": open_id,
                    "userId": "staff-user-id",
                    "unionId": "optional-union-id",
                    "nick": "ignored",
                },
            )
        raise AssertionError(f"unexpected DingTalk request: {request.method} {request.url}")

    return httpx2.Client(
        transport=httpx2.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    )


def test_explicit_link_then_password_free_login_uses_one_time_state_and_no_token_storage(
    isolated_database: str,
) -> None:
    fake = _fake_http_client()
    app.dependency_overrides[get_dingtalk_http_client] = lambda: fake
    with TestClient(app) as client:
        tenant_id, user_id, local_token = _setup(client, isolated_database)
        link_state = _state_from(
            client.post(
                "/api/integrations/dingtalk/oauth/link/start",
                json={"return_path": "/settings/integrations"},
                headers=_bearer(local_token),
            )
        )
        linked = client.post(
            "/api/integrations/dingtalk/oauth/callback",
            json={"auth_code": "valid-code", "state": link_state},
        )
        assert linked.status_code == 200
        assert linked.json()["mode"] == "link"
        assert linked.json()["linked"] is True
        assert linked.json()["return_path"] == "/settings/integrations"
        assert client.get(
            "/api/auth/me",
            headers=_bearer(linked.json()["access_token"]),
        ).json()["user"]["id"] == str(user_id)

        replay = client.post(
            "/api/integrations/dingtalk/oauth/callback",
            json={"auth_code": "valid-code", "state": link_state},
        )
        assert replay.status_code == 401
        assert replay.json()["detail"]["code"] == "DINGTALK_STATE_INVALID"

        login_state = _state_from(
            client.post(
                "/api/integrations/dingtalk/oauth/login/start",
                json={"tenant_slug": "beepump", "return_path": "/projects"},
            )
        )
        password_free = client.post(
            "/api/integrations/dingtalk/oauth/callback",
            json={"auth_code": "valid-code", "state": login_state},
        )
        assert password_free.status_code == 200
        assert password_free.json()["mode"] == "login"
        assert password_free.json()["linked"] is False
        assert client.get(
            "/api/auth/me",
            headers=_bearer(password_free.json()["access_token"]),
        ).json()["tenant"]["id"] == str(tenant_id)

    engine = create_engine(psycopg_database_url(isolated_database))
    try:
        with engine.connect() as connection:
            binding = connection.execute(select(tables.dingtalk_user_bindings)).mappings().one()
            events = list(
                connection.execute(
                    select(tables.events.c.event_type, tables.events.c.payload).where(
                        tables.events.c.event_type.in_(
                            ["DINGTALK_IDENTITY_LINKED", "USER_SIGNED_IN"]
                        )
                    )
                ).mappings()
            )
            stored = str(
                {
                    "binding": dict(binding),
                    "events": [dict(event) for event in events],
                }
            )
    finally:
        engine.dispose()
        fake.close()

    assert binding["user_id"] == user_id
    assert binding["open_id"] == OPEN_ID
    assert binding["staff_id"] == "staff-user-id"
    assert "ephemeral-user-token" not in stored
    assert "valid-code" not in stored
    methods = [
        event["payload"]["authentication_method"]
        for event in events
        if event["event_type"] == "USER_SIGNED_IN"
    ]
    assert methods.count("dingtalk_oauth") == 2


def test_unlinked_login_corp_mismatch_and_state_replay_fail_closed(
    isolated_database: str,
) -> None:
    with TestClient(app) as client:
        _setup(client, isolated_database)

        unlinked_fake = _fake_http_client(open_id="not-linked")
        app.dependency_overrides[get_dingtalk_http_client] = lambda: unlinked_fake
        unlinked_state = _state_from(
            client.post(
                "/api/integrations/dingtalk/oauth/login/start",
                json={"tenant_slug": "beepump"},
            )
        )
        unlinked = client.post(
            "/api/integrations/dingtalk/oauth/callback",
            json={"auth_code": "valid-code", "state": unlinked_state},
        )
        assert unlinked.status_code == 401
        assert unlinked.json()["detail"]["code"] == "DINGTALK_IDENTITY_NOT_LINKED"
        unlinked_fake.close()

        mismatch_fake = _fake_http_client(corp_id="different-corp")
        app.dependency_overrides[get_dingtalk_http_client] = lambda: mismatch_fake
        mismatch_state = _state_from(
            client.post(
                "/api/integrations/dingtalk/oauth/login/start",
                json={"tenant_slug": "beepump"},
            )
        )
        mismatch = client.post(
            "/api/integrations/dingtalk/oauth/callback",
            json={"auth_code": "valid-code", "state": mismatch_state},
        )
        assert mismatch.status_code == 401
        assert mismatch.json()["detail"]["code"] == "DINGTALK_CORP_MISMATCH"
        mismatch_replay = client.post(
            "/api/integrations/dingtalk/oauth/callback",
            json={"auth_code": "valid-code", "state": mismatch_state},
        )
        assert mismatch_replay.status_code == 401
        assert mismatch_replay.json()["detail"]["code"] == "DINGTALK_STATE_INVALID"
        mismatch_fake.close()


def test_inactive_user_link_and_external_role_link_are_denied(
    isolated_database: str,
) -> None:
    fake = _fake_http_client()
    app.dependency_overrides[get_dingtalk_http_client] = lambda: fake
    with TestClient(app) as client:
        tenant_id, user_id, local_token = _setup(client, isolated_database)
        link_state = _state_from(
            client.post(
                "/api/integrations/dingtalk/oauth/link/start",
                json={},
                headers=_bearer(local_token),
            )
        )
        engine = create_engine(psycopg_database_url(isolated_database))
        try:
            with engine.begin() as connection:
                connection.execute(
                    update(tables.users)
                    .where(tables.users.c.tenant_id == tenant_id, tables.users.c.id == user_id)
                    .values(is_active=False)
                )
        finally:
            engine.dispose()
        inactive = client.post(
            "/api/integrations/dingtalk/oauth/callback",
            json={"auth_code": "valid-code", "state": link_state},
        )
        assert inactive.status_code == 401
        assert inactive.json()["detail"]["code"] == "DINGTALK_IDENTITY_NOT_LINKED"

    fake.close()


def test_return_paths_and_payloads_are_bounded() -> None:
    with TestClient(app) as client:
        for invalid_path in ["https://evil.example", "//evil.example", "/ok\\bad"]:
            response = client.post(
                "/api/integrations/dingtalk/oauth/login/start",
                json={"tenant_slug": "beepump", "return_path": invalid_path},
            )
            assert response.status_code == 422
        unknown = client.post(
            "/api/integrations/dingtalk/oauth/login/start",
            json={"tenant_slug": "beepump", "unexpected": "rejected"},
        )
        assert unknown.status_code == 422
