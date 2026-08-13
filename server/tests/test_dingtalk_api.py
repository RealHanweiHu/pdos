from __future__ import annotations

import os
from collections.abc import Iterator
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
JWT_SECRET = "dingtalk-api-test-jwt-secret-is-at-least-32-bytes"
PASSWORD = "correct horse battery staple"
CLIENT_ID = "dingtalk-api-client"
SETUP = {
    "tenant_slug": "beepump",
    "tenant_name": "Beehive Technology",
    "username": "owner",
    "password": PASSWORD,
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
    monkeypatch.setenv("PDOS_DINGTALK_DELIVERY_ENABLED", "false")
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
        app.dependency_overrides.clear()


def _headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _seed(database_url: str, tenant_id: UUID, owner_id: UUID) -> dict[str, UUID]:
    ids = {
        "manager": uuid4(),
        "engineer": uuid4(),
        "supplier": uuid4(),
        "workflow": uuid4(),
        "stage": uuid4(),
        "project": uuid4(),
    }
    password_hash = PasswordService().hash(PASSWORD)
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.users.insert(),
                [
                    {
                        "id": ids[username],
                        "tenant_id": tenant_id,
                        "username": username,
                        "display_name": username.title(),
                        "role": role.value,
                        "password_hash": password_hash,
                    }
                    for username, role in (
                        ("manager", Role.PROJECT_MANAGER),
                        ("engineer", Role.ENGINEER),
                        ("supplier", Role.SUPPLIER),
                    )
                ],
            )
            connection.execute(
                tables.workflows.insert().values(
                    id=ids["workflow"],
                    tenant_id=tenant_id,
                    code="dingtalk-api",
                    name="DingTalk API",
                )
            )
            connection.execute(
                tables.stages.insert().values(
                    id=ids["stage"],
                    tenant_id=tenant_id,
                    workflow_id=ids["workflow"],
                    code="concept",
                    name="Concept",
                    sequence=1,
                )
            )
            connection.execute(
                tables.projects.insert().values(
                    id=ids["project"],
                    tenant_id=tenant_id,
                    workflow_id=ids["workflow"],
                    current_stage_id=ids["stage"],
                    owner_user_id=owner_id,
                    code="P-DING",
                    name="DingTalk Pilot",
                    status="active",
                )
            )
            connection.execute(
                tables.project_members.insert(),
                [
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": ids["project"],
                        "user_id": user_id,
                        "added_by_user_id": owner_id,
                    }
                    for user_id in (owner_id, ids["manager"], ids["engineer"], ids["supplier"])
                ],
            )
    finally:
        engine.dispose()
    return ids


def test_config_project_status_and_manual_outbox_are_tenant_and_role_bound(
    isolated_database: str,
) -> None:
    with TestClient(app) as client:
        setup = client.post("/api/setup", json=SETUP)
        assert setup.status_code == 201
        tenant_id = UUID(setup.json()["tenant"]["id"])
        owner_id = UUID(setup.json()["user"]["id"])
        ids = _seed(isolated_database, tenant_id, owner_id)
        owner = _headers(client, "owner")
        manager = _headers(client, "manager")
        engineer = _headers(client, "engineer")
        supplier = _headers(client, "supplier")

        configured = client.put(
            "/api/integrations/dingtalk/config",
            headers=owner,
            json={
                "corp_id": "ding-api-corp",
                "client_id": CLIENT_ID,
                "agent_id": "12345",
                "robot_code": "robot-code",
                "oauth_redirect_uri": "https://pdos.example/dingtalk/oauth/callback",
                "callback_route_key": "event-callback-route",
                "approval_process_code": "gate-approval",
                "card_template_id": "gate-card",
                "card_callback_route_key": "card-callback-route",
                "status": "active",
            },
        )
        assert configured.status_code == 200
        assert configured.json()["corp_id"] == "ding-api-corp"

        channel = client.put(
            f"/api/integrations/dingtalk/projects/{ids['project']}/channel",
            headers=manager,
            json={
                "open_conversation_id": "open-conversation-api",
                "display_name": "Pilot Group",
            },
        )
        assert channel.status_code == 200
        assert (
            client.put(
                f"/api/integrations/dingtalk/projects/{ids['project']}/channel",
                headers=engineer,
                json={
                    "open_conversation_id": "forbidden",
                    "display_name": "Forbidden",
                },
            ).status_code
            == 403
        )

        queued = client.post(
            f"/api/integrations/dingtalk/projects/{ids['project']}/notifications",
            headers=manager,
            json={
                "title": "Gate review",
                "text": "Review in PDOS",
                "idempotency_key": "api-group-manual-0001",
            },
        )
        assert queued.status_code == 200
        assert queued.json()["status"] == "manual"
        outbox_id = queued.json()["id"]

        project_status = client.get(
            f"/api/integrations/dingtalk/projects/{ids['project']}/status",
            headers=engineer,
        )
        assert project_status.status_code == 200
        assert project_status.json()["channel_configured"] is True
        assert project_status.json()["delivery_enabled"] is False
        assert project_status.json()["outbox"][0]["id"] == outbox_id
        assert (
            client.get(
                f"/api/integrations/dingtalk/projects/{ids['project']}/status",
                headers=supplier,
            ).status_code
            == 403
        )

        owner_outbox = client.get("/api/integrations/dingtalk/outbox", headers=owner)
        assert owner_outbox.status_code == 200
        assert owner_outbox.json()["items"][0]["id"] == outbox_id
        assert client.get("/api/integrations/dingtalk/outbox", headers=manager).status_code == 403
        disabled_replay = client.post(
            f"/api/integrations/dingtalk/outbox/{outbox_id}/replay",
            headers=owner,
            json={"confirmation": "REPLAY_CONFIRMED"},
        )
        assert disabled_replay.status_code == 503
        assert disabled_replay.json()["detail"]["code"] == "DINGTALK_DELIVERY_DISABLED"

        owner_status = client.get("/api/integrations/dingtalk/status", headers=owner)
        assert owner_status.status_code == 200
        assert owner_status.json() == {
            "configured": True,
            "binding_status": "active",
            "corp_id": "ding-api-corp",
            "linked": False,
            "delivery_enabled": False,
        }

    engine = create_engine(psycopg_database_url(isolated_database))
    try:
        with engine.connect() as connection:
            actions = set(
                connection.execute(
                    select(tables.audit_log.c.action).where(
                        tables.audit_log.c.tenant_id == tenant_id
                    )
                ).scalars()
            )
    finally:
        engine.dispose()
    assert {
        "dingtalk.integration.configure",
        "dingtalk.project_channel.configure",
        "dingtalk.outbox.enqueue",
    }.issubset(actions)
