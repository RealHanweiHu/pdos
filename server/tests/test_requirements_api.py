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
def isolated_requirement_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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


def bearer_headers(client: TestClient, *, username: str = "owner") -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={
            "tenant_slug": "beepump",
            "username": username,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def seed_customer(database_url: str, *, tenant_id: UUID) -> UUID:
    customer_id = uuid4()
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.customers.insert(),
                {
                    "id": customer_id,
                    "tenant_id": tenant_id,
                    "code": "ACME",
                    "name": "Acme Pumps",
                    "description": "Strategic customer",
                },
            )
    finally:
        engine.dispose()
    return customer_id


def seed_user(
    database_url: str,
    *,
    tenant_id: UUID,
    username: str,
    role: Role,
) -> UUID:
    user_id = uuid4()
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.users.insert(),
                {
                    "id": user_id,
                    "tenant_id": tenant_id,
                    "username": username,
                    "display_name": username.replace("_", " ").title(),
                    "role": role,
                    "password_hash": PasswordService().hash(PASSWORD),
                },
            )
    finally:
        engine.dispose()
    return user_id


def seed_other_tenant_requirement(database_url: str) -> tuple[UUID, UUID]:
    tenant_id = uuid4()
    customer_id = uuid4()
    requirement_id = uuid4()
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": tenant_id, "slug": f"other-{tenant_id}", "name": "Other Tenant"},
            )
            connection.execute(
                tables.customers.insert(),
                {
                    "id": customer_id,
                    "tenant_id": tenant_id,
                    "code": "OTHER",
                    "name": "Other Customer",
                },
            )
            connection.execute(
                tables.requirements.insert(),
                {
                    "id": requirement_id,
                    "tenant_id": tenant_id,
                    "customer_id": customer_id,
                    "code": "OTHER-REQ",
                    "title": "Other tenant requirement",
                },
            )
    finally:
        engine.dispose()
    return customer_id, requirement_id


def test_requirement_http_flow_records_customer_events_and_audit(
    client: TestClient,
    isolated_requirement_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD)
    assert setup.status_code == 201
    tenant_id = UUID(setup.json()["tenant"]["id"])
    owner_id = UUID(setup.json()["user"]["id"])
    customer_id = seed_customer(isolated_requirement_database, tenant_id=tenant_id)
    headers = bearer_headers(client)

    customers = client.get("/api/customers", headers=headers)
    assert customers.status_code == 200
    assert customers.headers["cache-control"] == "no-store"
    assert customers.json() == {
        "items": [
            {
                "id": str(customer_id),
                "code": "ACME",
                "name": "Acme Pumps",
                "status": "active",
            }
        ]
    }

    created = client.post(
        "/api/requirements",
        headers=headers,
        json={
            "code": "REQ-001",
            "title": "Reduce seal leakage",
            "description": "Target the next pump platform.",
            "source": "customer_interview",
            "priority": "high",
            "acceptance_criteria": ["Leakage below 1 ml/h", "DVT report attached"],
            "customer_id": str(customer_id),
        },
    )
    assert created.status_code == 201
    assert created.headers["cache-control"] == "no-store"
    requirement = created.json()
    requirement_id = UUID(requirement["id"])
    assert requirement == {
        "id": str(requirement_id),
        "code": "REQ-001",
        "title": "Reduce seal leakage",
        "description": "Target the next pump platform.",
        "source": "customer_interview",
        "status": "draft",
        "priority": "high",
        "acceptance_criteria": ["Leakage below 1 ml/h", "DVT report attached"],
        "customer": {
            "id": str(customer_id),
            "code": "ACME",
            "name": "Acme Pumps",
            "status": "active",
        },
        "created_by_user_id": str(owner_id),
        "created_at": requirement["created_at"],
        "updated_at": requirement["updated_at"],
    }

    detail = client.get(f"/api/requirements/{requirement_id}", headers=headers)
    listed = client.get("/api/requirements", headers=headers)
    assert detail.status_code == listed.status_code == 200
    assert detail.json() == requirement
    assert listed.json() == {"items": [requirement]}

    updated = client.patch(
        f"/api/requirements/{requirement_id}",
        headers=headers,
        json={
            "title": "Reduce mechanical seal leakage",
            "priority": "critical",
            "acceptance_criteria": ["Leakage below 0.5 ml/h"],
            "customer_id": None,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Reduce mechanical seal leakage"
    assert updated.json()["priority"] == "critical"
    assert updated.json()["acceptance_criteria"] == ["Leakage below 0.5 ml/h"]
    assert updated.json()["customer"] is None
    assert updated.json()["updated_at"] >= requirement["updated_at"]

    engine = create_engine(psycopg_database_url(isolated_requirement_database))
    try:
        with engine.connect() as connection:
            events = list(
                connection.execute(
                    select(
                        tables.events.c.event_type,
                        tables.events.c.entity,
                        tables.events.c.entity_id,
                        tables.events.c.project_id,
                        tables.events.c.payload,
                    )
                    .where(tables.events.c.entity == "requirement")
                    .order_by(tables.events.c.id)
                ).mappings()
            )
            audits = list(
                connection.execute(
                    select(
                        tables.audit_log.c.action,
                        tables.audit_log.c.before_snapshot,
                        tables.audit_log.c.after_snapshot,
                    )
                    .where(tables.audit_log.c.entity == "requirement")
                    .order_by(tables.audit_log.c.id)
                ).mappings()
            )
    finally:
        engine.dispose()

    assert [event["event_type"] for event in events] == [
        "REQUIREMENT_CREATED",
        "REQUIREMENT_UPDATED",
    ]
    assert all(event["entity_id"] == requirement_id for event in events)
    assert all(event["project_id"] is None for event in events)
    assert events[0]["payload"] == {
        "requirement_code": "REQ-001",
        "status": "draft",
        "priority": "high",
    }
    assert events[1]["payload"] == {
        "changed_fields": ["acceptance_criteria", "customer_id", "priority", "title"],
        "status": "draft",
        "priority": "critical",
    }
    assert [audit["action"] for audit in audits] == [
        "requirement.create",
        "requirement.update",
    ]
    assert audits[0]["before_snapshot"] is None
    assert audits[0]["after_snapshot"]["customer_id"] == str(customer_id)
    assert audits[1]["before_snapshot"]["title"] == "Reduce seal leakage"
    assert audits[1]["after_snapshot"]["customer_id"] is None


def test_requirement_errors_are_tenant_safe_and_transactional(
    client: TestClient,
    isolated_requirement_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    headers = bearer_headers(client)
    local_customer_id = seed_customer(isolated_requirement_database, tenant_id=tenant_id)
    other_customer_id, other_requirement_id = seed_other_tenant_requirement(
        isolated_requirement_database
    )

    created = client.post(
        "/api/requirements",
        headers=headers,
        json={
            "code": "REQ-LOCAL",
            "title": "Local requirement",
            "customer_id": str(local_customer_id),
        },
    )
    assert created.status_code == 201
    local_requirement_id = created.json()["id"]

    unknown_id = uuid4()
    cross_get = client.get(f"/api/requirements/{other_requirement_id}", headers=headers)
    unknown_get = client.get(f"/api/requirements/{unknown_id}", headers=headers)
    cross_patch = client.patch(
        f"/api/requirements/{other_requirement_id}",
        headers=headers,
        json={"title": "Attempted overwrite"},
    )
    assert cross_get.status_code == unknown_get.status_code == cross_patch.status_code == 404
    assert cross_get.json() == unknown_get.json() == cross_patch.json()
    assert cross_get.json()["detail"]["code"] == "REQUIREMENT_NOT_FOUND"

    engine = create_engine(psycopg_database_url(isolated_requirement_database))
    try:
        with engine.connect() as connection:
            before_event_count = connection.execute(
                select(tables.events.c.id).where(tables.events.c.entity == "requirement")
            ).all()
            before_audit_count = connection.execute(
                select(tables.audit_log.c.id).where(tables.audit_log.c.entity == "requirement")
            ).all()
    finally:
        engine.dispose()

    cross_customer = client.post(
        "/api/requirements",
        headers=headers,
        json={
            "code": "REQ-CROSS",
            "title": "Cross-tenant customer must fail",
            "customer_id": str(other_customer_id),
        },
    )
    duplicate = client.post(
        "/api/requirements",
        headers=headers,
        json={"code": "REQ-LOCAL", "title": "Duplicate code"},
    )
    assert cross_customer.status_code == 404
    assert cross_customer.json()["detail"]["code"] == "CUSTOMER_NOT_FOUND"
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "REQUIREMENT_CODE_CONFLICT"

    assert (
        client.patch(
            f"/api/requirements/{local_requirement_id}", headers=headers, json={}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/requirements/{local_requirement_id}",
            headers=headers,
            json={"status": "converted"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/requirements",
            headers=headers,
            json={
                "code": "REQ-BLANK",
                "title": "Invalid criteria",
                "acceptance_criteria": ["   "],
            },
        ).status_code
        == 422
    )

    engine = create_engine(psycopg_database_url(isolated_requirement_database))
    try:
        with engine.connect() as connection:
            after_event_count = connection.execute(
                select(tables.events.c.id).where(tables.events.c.entity == "requirement")
            ).all()
            after_audit_count = connection.execute(
                select(tables.audit_log.c.id).where(tables.audit_log.c.entity == "requirement")
            ).all()
            persisted_codes = set(
                connection.execute(
                    select(tables.requirements.c.code).where(
                        tables.requirements.c.tenant_id == tenant_id
                    )
                ).scalars()
            )
    finally:
        engine.dispose()

    assert after_event_count == before_event_count
    assert after_audit_count == before_audit_count
    assert persisted_codes == {"REQ-LOCAL"}


def test_requirement_permissions_and_latest_updated_order(
    client: TestClient,
    isolated_requirement_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    seed_user(
        isolated_requirement_database,
        tenant_id=tenant_id,
        username="engineer",
        role=Role.ENGINEER,
    )
    seed_user(
        isolated_requirement_database,
        tenant_id=tenant_id,
        username="external_customer",
        role=Role.CUSTOMER,
    )
    owner_headers = bearer_headers(client)
    engineer_headers = bearer_headers(client, username="engineer")
    external_headers = bearer_headers(client, username="external_customer")

    first = client.post(
        "/api/requirements",
        headers=owner_headers,
        json={"code": "REQ-001", "title": "First"},
    ).json()
    second = client.post(
        "/api/requirements",
        headers=owner_headers,
        json={"code": "REQ-002", "title": "Second"},
    ).json()
    updated_first = client.patch(
        f"/api/requirements/{first['id']}",
        headers=owner_headers,
        json={"title": "First, updated"},
    )
    assert updated_first.status_code == 200

    listed = client.get("/api/requirements", headers=owner_headers)
    assert [item["id"] for item in listed.json()["items"]] == [first["id"], second["id"]]

    assert client.get("/api/requirements", headers=engineer_headers).status_code == 200
    assert (
        client.post(
            "/api/requirements",
            headers=engineer_headers,
            json={"code": "DENIED", "title": "Denied"},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/requirements/{first['id']}",
            headers=engineer_headers,
            json={"title": "Denied"},
        ).status_code
        == 403
    )

    external_list = client.get("/api/requirements", headers=external_headers)
    external_customers = client.get("/api/customers", headers=external_headers)
    assert external_list.status_code == external_customers.status_code == 403
    assert external_list.json()["detail"]["code"] == "OBJECT_PERMISSION_DENIED"
    assert client.get("/api/requirements").status_code == 401


def test_requirement_insert_rolls_back_when_event_write_fails(
    monkeypatch: pytest.MonkeyPatch,
    isolated_requirement_database: str,
) -> None:
    fixed_requirement_id = uuid4()
    with TestClient(app, raise_server_exceptions=False) as error_client:
        setup = error_client.post("/api/setup", json=SETUP_PAYLOAD).json()
        tenant_id = UUID(setup["tenant"]["id"])
        headers = bearer_headers(error_client)

        engine = create_engine(psycopg_database_url(isolated_requirement_database))
        try:
            with engine.begin() as connection:
                connection.execute(
                    tables.events.insert(),
                    {
                        "tenant_id": tenant_id,
                        "event_id": f"requirement:{fixed_requirement_id}:created",
                        "event_type": "REQUIREMENT_CREATED",
                        "schema_version": 1,
                        "source": "requirement_service",
                        "entity": "requirement",
                        "entity_id": fixed_requirement_id,
                        "payload": {
                            "requirement_code": "COLLISION",
                            "status": "draft",
                            "priority": "medium",
                        },
                    },
                )
        finally:
            engine.dispose()

        monkeypatch.setattr("app.domain.requirements.uuid4", lambda: fixed_requirement_id)
        failed = error_client.post(
            "/api/requirements",
            headers=headers,
            json={"code": "REQ-ROLLBACK", "title": "Must roll back"},
        )
        assert failed.status_code == 500

    engine = create_engine(psycopg_database_url(isolated_requirement_database))
    try:
        with engine.connect() as connection:
            requirement_count = connection.execute(
                select(tables.requirements.c.id).where(
                    tables.requirements.c.tenant_id == tenant_id,
                    tables.requirements.c.code == "REQ-ROLLBACK",
                )
            ).all()
            audit_count = connection.execute(
                select(tables.audit_log.c.id).where(
                    tables.audit_log.c.tenant_id == tenant_id,
                    tables.audit_log.c.entity == "requirement",
                )
            ).all()
    finally:
        engine.dispose()

    assert requirement_count == []
    assert audit_count == []
