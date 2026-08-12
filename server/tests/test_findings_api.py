from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
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


@pytest.fixture(autouse=True)
def isolated_findings_api_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    test_url = configured_test_database_url()
    monkeypatch.setenv("DATABASE_URL", test_url)
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("JWT_ISSUER", "pdos-test")
    monkeypatch.setenv("JWT_AUDIENCE", "pdos-test-client")
    get_settings.cache_clear()
    get_engine.cache_clear()
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


def login_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "findings-api", "username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def seed_api_finding(database_url: str) -> dict[str, UUID | int]:
    tenant_id = uuid4()
    owner_id = uuid4()
    engineer_id = uuid4()
    customer_id = uuid4()
    workflow_id = uuid4()
    project_id = uuid4()
    subscription_id = uuid4()
    run_id = uuid4()
    invocation_id = uuid4()
    finding_id = uuid4()
    now = datetime.now(UTC)
    password_hash = PasswordService().hash(PASSWORD)
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": tenant_id, "slug": "findings-api", "name": "Findings API"},
            )
            connection.execute(
                tables.users.insert(),
                [
                    {
                        "id": owner_id,
                        "tenant_id": tenant_id,
                        "username": "owner",
                        "display_name": "Owner",
                        "role": Role.OWNER.value,
                        "password_hash": password_hash,
                    },
                    {
                        "id": engineer_id,
                        "tenant_id": tenant_id,
                        "username": "engineer",
                        "display_name": "Engineer",
                        "role": Role.ENGINEER.value,
                        "password_hash": password_hash,
                    },
                    {
                        "id": customer_id,
                        "tenant_id": tenant_id,
                        "username": "customer",
                        "display_name": "Customer",
                        "role": Role.CUSTOMER.value,
                        "password_hash": password_hash,
                    },
                ],
            )
            connection.execute(
                tables.workflows.insert(),
                {"id": workflow_id, "tenant_id": tenant_id, "code": "npd", "name": "NPD"},
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": project_id,
                    "tenant_id": tenant_id,
                    "workflow_id": workflow_id,
                    "owner_user_id": owner_id,
                    "code": "PRJ-AI",
                    "name": "AI Review",
                    "status": "active",
                },
            )
            for user_id in (owner_id, engineer_id, customer_id):
                connection.execute(
                    tables.project_members.insert(),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "user_id": user_id,
                        "added_by_user_id": owner_id,
                    },
                )
            event_id = int(
                connection.execute(
                    tables.events.insert()
                    .values(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        event_id=f"issue:{uuid4()}",
                        event_type="ISSUE_CREATED",
                        schema_version=1,
                        source="findings_api_test",
                        entity="issue",
                        entity_id=uuid4(),
                        payload={},
                        timestamp=now - timedelta(minutes=20),
                    )
                    .returning(tables.events.c.id)
                ).scalar_one()
            )
            connection.execute(
                tables.agent_subscriptions.insert(),
                {
                    "id": subscription_id,
                    "tenant_id": tenant_id,
                    "agent_key": "project_intelligence",
                },
            )
            connection.execute(
                tables.agent_runs.insert(),
                {
                    "id": run_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "subscription_id": subscription_id,
                    "agent_key": "project_intelligence",
                    "status": "succeeded",
                    "window_started_at": now - timedelta(minutes=30),
                    "window_ended_at": now - timedelta(minutes=15),
                    "first_event_row_id": event_id,
                    "last_event_row_id": event_id,
                    "event_count": 1,
                    "event_row_ids": [event_id],
                    "started_at": now - timedelta(minutes=14),
                    "completed_at": now - timedelta(minutes=13),
                },
            )
            connection.execute(
                tables.model_invocations.insert(),
                {
                    "id": invocation_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "run_id": run_id,
                    "agent_key": "project_intelligence",
                    "prompt_version": "v1",
                    "provider": "minimax",
                    "model": "MiniMax-M2.7",
                    "protocol": "openai-compatible",
                    "status": "succeeded",
                    "structured_attempts": 1,
                },
            )
            connection.execute(
                tables.findings.insert(),
                {
                    "id": finding_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "run_id": run_id,
                    "model_invocation_id": invocation_id,
                    "agent_key": "project_intelligence",
                    "finding_type": "risk_suggestion",
                    "origin_key": "api-risk",
                    "title": "Review API risk",
                    "summary": "A scoped risk candidate.",
                    "proposed_payload": {
                        "title": "API risk",
                        "likelihood": 3,
                        "impact": 4,
                    },
                    "evidence_event_ids": [event_id],
                    "confidence_basis_points": 8000,
                    "preflight_version": "finding-preflight-v1",
                    "created_at": now,
                    "updated_at": now,
                },
            )
            connection.execute(
                tables.finding_actions.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "finding_id": finding_id,
                    "action": "created",
                    "to_status": "pending_review",
                    "detail": {},
                    "created_at": now,
                },
            )
    finally:
        engine.dispose()
    return {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "finding_id": finding_id,
        "event_id": event_id,
    }


def test_findings_http_keeps_accept_and_apply_separate(
    client: TestClient,
    isolated_findings_api_database: str,
) -> None:
    ids = seed_api_finding(isolated_findings_api_database)
    headers = login_headers(client, "engineer")
    inbox = client.get(
        f"/api/ai/findings?project_id={ids['project_id']}&status=pending_review",
        headers=headers,
    )
    assert inbox.status_code == 200
    assert inbox.headers["cache-control"] == "no-store"
    assert [item["id"] for item in inbox.json()["items"]] == [str(ids["finding_id"])]
    assert inbox.json()["items"][0]["evidence"] == [
        {
            "event_row_id": ids["event_id"],
            "label": f"事件 #{ids['event_id']}",
            "href": (
                f"/projects?project={ids['project_id']}&tab=timeline&event_id={ids['event_id']}"
            ),
        }
    ]
    tenant_inbox = client.get(
        "/api/ai/findings?status=pending_review",
        headers=headers,
    )
    assert tenant_inbox.status_code == 200
    assert [item["id"] for item in tenant_inbox.json()["items"]] == [str(ids["finding_id"])]

    accepted = client.post(
        f"/api/ai/findings/{ids['finding_id']}/review",
        headers=headers,
        json={
            "decision": "accepted",
            "edited_payload": {
                "title": "Edited API risk",
                "likelihood": 4,
                "impact": 5,
            },
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    assert accepted.json()["applied_entity_id"] is None

    applied = client.post(
        f"/api/ai/findings/{ids['finding_id']}/apply",
        headers=headers,
    )
    assert applied.status_code == 200
    assert applied.json()["finding"]["status"] == "applied"
    assert not applied.json()["idempotent_replay"]
    replay = client.post(
        f"/api/ai/findings/{ids['finding_id']}/apply",
        headers=headers,
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"]
    assert replay.json()["risk_id"] == applied.json()["risk_id"]


def test_external_role_cannot_view_review_or_apply_findings(
    client: TestClient,
    isolated_findings_api_database: str,
) -> None:
    ids = seed_api_finding(isolated_findings_api_database)
    headers = login_headers(client, "customer")
    assert (
        client.get(f"/api/ai/findings?project_id={ids['project_id']}", headers=headers).status_code
        == 403
    )
    assert client.get("/api/ai/findings", headers=headers).status_code == 403
    assert (
        client.post(
            f"/api/ai/findings/{ids['finding_id']}/review",
            headers=headers,
            json={"decision": "accepted"},
        ).status_code
        == 403
    )
    assert (
        client.post(f"/api/ai/findings/{ids['finding_id']}/apply", headers=headers).status_code
        == 403
    )


def test_reject_requires_a_human_reason(
    client: TestClient,
    isolated_findings_api_database: str,
) -> None:
    ids = seed_api_finding(isolated_findings_api_database)
    headers = login_headers(client, "engineer")

    missing = client.post(
        f"/api/ai/findings/{ids['finding_id']}/review",
        headers=headers,
        json={"decision": "rejected"},
    )
    rejected = client.post(
        f"/api/ai/findings/{ids['finding_id']}/review",
        headers=headers,
        json={"decision": "rejected", "comment": "证据不足"},
    )

    assert missing.status_code == 422
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["review_comment"] == "证据不足"
