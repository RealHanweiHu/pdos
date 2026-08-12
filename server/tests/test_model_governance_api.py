from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text

from app.ai.golden_suite import load_golden_suite
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
    "tenant_slug": "model-governance",
    "tenant_name": "Model Governance",
    "username": "owner",
    "password": PASSWORD,
    "display_name": "Initial Owner",
}


@pytest.fixture(autouse=True)
def isolated_model_governance_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[str]:
    test_url = configured_test_database_url()
    qualification_path = tmp_path / "model-qualifications.json"
    trusted_suite = load_golden_suite(SERVER_ROOT / "golden" / "model-gateway-v1.json")
    qualification_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "suite_version": trusted_suite.suite.suite_version,
                "suite_digest": trusted_suite.digest,
                "models": [
                    {"provider": "minimax", "model": "MiniMax-M2.7", "status": "passed"},
                    {"provider": "openai", "model": "gpt-5.1", "status": "failed"},
                ],
            }
        )
    )
    monkeypatch.setenv("DATABASE_URL", test_url)
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("JWT_ISSUER", "pdos-test")
    monkeypatch.setenv("JWT_AUDIENCE", "pdos-test-client")
    monkeypatch.setenv("PDOS_LLM_PROVIDER", "minimax")
    monkeypatch.setenv("PDOS_LLM_API_KEY", "test-only-minimax-secret")
    monkeypatch.setenv("PDOS_LLM_MODEL", "MiniMax-M2.7")
    monkeypatch.setenv("PDOS_LLM_OPENAI_API_KEY", "test-only-openai-secret")
    monkeypatch.setenv("PDOS_LLM_OPENAI_MODEL", "gpt-5.1")
    monkeypatch.setenv("PDOS_LLM_GOLDEN_QUALIFICATIONS_PATH", str(qualification_path))
    monkeypatch.setenv("PDOS_AI_DAILY_TOKEN_BUDGET", "2000000")
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


def bearer_headers(client: TestClient, *, tenant_slug: str, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": tenant_slug, "username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def seed_roles_and_other_tenant(database_url: str, *, tenant_id: UUID) -> UUID:
    other_tenant_id = uuid4()
    password_hash = PasswordService().hash(PASSWORD)
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.users.insert(),
                [
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "username": "admin",
                        "display_name": "Administrator",
                        "role": Role.ADMIN,
                        "password_hash": password_hash,
                    },
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "username": "manager",
                        "display_name": "Project Manager",
                        "role": Role.PROJECT_MANAGER,
                        "password_hash": password_hash,
                    },
                ],
            )
            connection.execute(
                tables.tenants.insert(),
                {"id": other_tenant_id, "slug": "other-models", "name": "Other Models"},
            )
            connection.execute(
                tables.model_invocations.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": other_tenant_id,
                    "agent_key": "other_agent",
                    "prompt_version": "other-v1",
                    "provider": "minimax",
                    "model": "MiniMax-M2.7",
                    "protocol": "openai-compatible",
                    "status": "succeeded",
                    "input_tokens": 8000,
                    "output_tokens": 1000,
                    "total_tokens": 9000,
                    "structured_attempts": 1,
                },
            )
    finally:
        engine.dispose()
    return other_tenant_id


def test_model_governance_is_qualified_secret_free_tenant_bound_and_audited(
    client: TestClient,
    isolated_model_governance_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    seed_roles_and_other_tenant(isolated_model_governance_database, tenant_id=tenant_id)
    owner_headers = bearer_headers(client, tenant_slug="model-governance", username="owner")
    admin_headers = bearer_headers(client, tenant_slug="model-governance", username="admin")
    manager_headers = bearer_headers(client, tenant_slug="model-governance", username="manager")

    initial = client.get("/api/ai/governance/model", headers=owner_headers)
    assert initial.status_code == 200
    assert initial.headers["cache-control"] == "no-store"
    assert initial.json() == {
        "eligible_models": [
            {
                "provider": "minimax",
                "model": "MiniMax-M2.7",
                "protocol": "openai-compatible",
            }
        ],
        "selection": {
            "provider": "minimax",
            "model": "MiniMax-M2.7",
            "available": True,
        },
        "budget": {
            "daily_token_budget": 2000000,
            "used_tokens_today": 0,
            "remaining_tokens_today": 2000000,
            "exhausted": False,
        },
    }
    serialized = json.dumps(initial.json()).lower()
    assert "secret" not in serialized
    assert "api_key" not in serialized
    assert "base_url" not in serialized

    updated = client.patch(
        "/api/ai/governance/model",
        headers=admin_headers,
        json={
            "provider": "minimax",
            "model": "MiniMax-M2.7",
            "daily_token_budget": 1000,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["budget"]["daily_token_budget"] == 1000

    engine = create_engine(psycopg_database_url(isolated_model_governance_database))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.model_invocations.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "agent_key": "project_intelligence",
                    "prompt_version": "project-intelligence-v1",
                    "provider": "minimax",
                    "model": "MiniMax-M2.7",
                    "protocol": "openai-compatible",
                    "status": "succeeded",
                    "input_tokens": 200,
                    "output_tokens": 50,
                    "total_tokens": 250,
                    "structured_attempts": 1,
                },
            )
    finally:
        engine.dispose()

    persisted = client.get("/api/ai/governance/model", headers=owner_headers)
    assert persisted.status_code == 200
    assert persisted.json()["budget"] == {
        "daily_token_budget": 1000,
        "used_tokens_today": 250,
        "remaining_tokens_today": 750,
        "exhausted": False,
    }

    unqualified = client.patch(
        "/api/ai/governance/model",
        headers=owner_headers,
        json={"provider": "openai", "model": "gpt-5.1", "daily_token_budget": 1000},
    )
    assert unqualified.status_code == 422
    assert unqualified.json()["detail"]["code"] == "MODEL_NOT_ELIGIBLE"

    assert (
        client.patch(
            "/api/ai/governance/model",
            headers=manager_headers,
            json={
                "provider": "minimax",
                "model": "MiniMax-M2.7",
                "daily_token_budget": 1000,
            },
        ).status_code
        == 403
    )
    assert client.get("/api/ai/governance/model", headers=manager_headers).status_code == 403
    assert client.get("/api/ai/governance/model").status_code == 401
    assert (
        client.patch(
            "/api/ai/governance/model",
            headers=owner_headers,
            json={
                "provider": "minimax",
                "model": "MiniMax-M2.7",
                "daily_token_budget": 1000,
                "api_key": "exfiltrate",
            },
        ).status_code
        == 422
    )

    engine = create_engine(psycopg_database_url(isolated_model_governance_database))
    try:
        with engine.connect() as connection:
            events = (
                connection.execute(
                    select(tables.events.c.payload).where(
                        tables.events.c.tenant_id == tenant_id,
                        tables.events.c.event_type == "TENANT_MODEL_SETTINGS_UPDATED",
                    )
                )
                .mappings()
                .all()
            )
            audits = (
                connection.execute(
                    select(tables.audit_log.c.after_snapshot).where(
                        tables.audit_log.c.tenant_id == tenant_id,
                        tables.audit_log.c.action == "tenant_model_settings.update",
                    )
                )
                .mappings()
                .all()
            )
        assert [dict(row) for row in events] == [
            {
                "payload": {
                    "provider": "minimax",
                    "model": "MiniMax-M2.7",
                    "daily_token_budget": 1000,
                }
            }
        ]
        assert len(audits) == 1
        assert "api_key" not in json.dumps([dict(row) for row in audits]).lower()
    finally:
        engine.dispose()
