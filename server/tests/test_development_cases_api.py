from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app.auth.passwords import PasswordService
from app.auth.roles import Role
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.main import app
from app.settings import get_settings
from tests.db_cleanup import clear_test_tenants

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
def isolated_case_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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
            clear_test_tenants(connection)
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


def bearer_headers(client: TestClient, *, username: str = "owner") -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_approved_requirement(
    client: TestClient,
    headers: dict[str, str],
    code: str,
) -> dict[str, Any]:
    created = client.post(
        "/api/requirements",
        headers=headers,
        json={"code": code, "title": f"Requirement {code}"},
    )
    assert created.status_code == 201
    approved = client.patch(
        f"/api/requirements/{created.json()['id']}",
        headers=headers,
        json={"status": "approved"},
    )
    assert approved.status_code == 200
    return cast(dict[str, Any], approved.json())


def convert_requirement(
    client: TestClient,
    headers: dict[str, str],
    requirement_id: str,
    *,
    code: str = "CASE-001",
) -> httpx2.Response:
    return client.post(
        f"/api/requirements/{requirement_id}/convert-to-case",
        headers=headers,
        json={
            "code": code,
            "title": "Seal leakage development case",
            "summary": "Evaluate the next pump platform.",
            "business_case": {"market_impact": "high", "target_sop": "2027-Q2"},
            "rationale": "Approved customer demand merits formal evaluation.",
        },
    )


def seed_user(database_url: str, *, tenant_id: UUID, username: str, role: Role) -> None:
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.users.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "username": username,
                    "display_name": username.title(),
                    "role": role,
                    "password_hash": PasswordService().hash(PASSWORD),
                },
            )
    finally:
        engine.dispose()


def test_formal_conversion_is_atomic_and_records_decision_events_and_audit(
    client: TestClient,
    isolated_case_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    owner_id = setup["user"]["id"]
    headers = bearer_headers(client)
    requirement = create_approved_requirement(client, headers, "REQ-001")

    converted = convert_requirement(client, headers, requirement["id"])
    assert converted.status_code == 201
    assert converted.headers["cache-control"] == "no-store"
    body = converted.json()
    development_case = body["development_case"]
    decision = body["decision"]
    assert development_case == {
        "id": development_case["id"],
        "requirement_id": requirement["id"],
        "code": "CASE-001",
        "title": "Seal leakage development case",
        "summary": "Evaluate the next pump platform.",
        "status": "draft",
        "business_case": {"market_impact": "high", "target_sop": "2027-Q2"},
        "created_by_user_id": owner_id,
        "created_at": development_case["created_at"],
        "updated_at": development_case["updated_at"],
    }
    assert decision["requirement_id"] == requirement["id"]
    assert decision["development_case_id"] == development_case["id"]
    assert decision["decision_kind"] == "requirement_to_development_case"
    assert decision["outcome"] == "converted"
    assert decision["rationale"] == "Approved customer demand merits formal evaluation."

    detail = client.get(f"/api/development-cases/{development_case['id']}", headers=headers)
    listed = client.get("/api/development-cases", headers=headers)
    assert detail.status_code == listed.status_code == 200
    assert detail.json() == development_case
    assert listed.json() == {"items": [development_case]}

    engine = create_engine(psycopg_database_url(isolated_case_database))
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(
                    select(tables.requirements.c.status).where(
                        tables.requirements.c.id == UUID(requirement["id"])
                    )
                ).scalar_one()
                == "converted"
            )
            event_rows = list(
                connection.execute(
                    select(tables.events.c.event_type, tables.events.c.entity)
                    .where(
                        tables.events.c.event_type.in_(
                            {
                                "DEVELOPMENT_CASE_CREATED",
                                "REQUIREMENT_CONVERTED",
                                "DECISION_RECORDED",
                            }
                        )
                    )
                    .order_by(tables.events.c.id)
                ).mappings()
            )
            audit_rows = list(
                connection.execute(
                    select(tables.audit_log.c.action).where(
                        tables.audit_log.c.action.in_(
                            {
                                "development_case.create",
                                "requirement.convert_to_case",
                                "decision.record",
                            }
                        )
                    )
                ).scalars()
            )
    finally:
        engine.dispose()
    assert event_rows == [
        {"event_type": "DEVELOPMENT_CASE_CREATED", "entity": "development_case"},
        {"event_type": "REQUIREMENT_CONVERTED", "entity": "requirement"},
        {"event_type": "DECISION_RECORDED", "entity": "decision"},
    ]
    assert set(audit_rows) == {
        "development_case.create",
        "requirement.convert_to_case",
        "decision.record",
    }


def test_conversion_and_case_errors_are_tenant_safe_and_transactional(
    client: TestClient,
    isolated_case_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    headers = bearer_headers(client)
    draft = client.post(
        "/api/requirements",
        headers=headers,
        json={"code": "REQ-DRAFT", "title": "Draft requirement"},
    ).json()
    not_approved = convert_requirement(client, headers, draft["id"], code="CASE-DRAFT")
    assert not_approved.status_code == 409
    assert not_approved.json()["detail"]["code"] == "REQUIREMENT_NOT_APPROVED"

    approved = create_approved_requirement(client, headers, "REQ-APPROVED")
    first = convert_requirement(client, headers, approved["id"], code="CASE-FIRST")
    assert first.status_code == 201
    duplicate = convert_requirement(client, headers, approved["id"], code="CASE-SECOND")
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "REQUIREMENT_ALREADY_CONVERTED"

    other_tenant_id = uuid4()
    other_requirement_id = uuid4()
    other_case_id = uuid4()
    engine = create_engine(psycopg_database_url(isolated_case_database))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": other_tenant_id, "slug": "other", "name": "Other"},
            )
            connection.execute(
                tables.requirements.insert(),
                {
                    "id": other_requirement_id,
                    "tenant_id": other_tenant_id,
                    "code": "OTHER-REQ",
                    "title": "Other requirement",
                    "status": "approved",
                },
            )
            connection.execute(
                tables.development_cases.insert(),
                {
                    "id": other_case_id,
                    "tenant_id": other_tenant_id,
                    "requirement_id": other_requirement_id,
                    "code": "OTHER-CASE",
                    "title": "Other case",
                },
            )
    finally:
        engine.dispose()

    unknown_id = uuid4()
    cross = convert_requirement(client, headers, str(other_requirement_id), code="CASE-CROSS")
    unknown = convert_requirement(client, headers, str(unknown_id), code="CASE-UNKNOWN")
    assert cross.status_code == unknown.status_code == 404
    assert cross.json() == unknown.json()
    assert cross.json()["detail"]["code"] == "REQUIREMENT_NOT_FOUND"

    cross_case_get = client.get(f"/api/development-cases/{other_case_id}", headers=headers)
    unknown_case_get = client.get(f"/api/development-cases/{unknown_id}", headers=headers)
    cross_case_patch = client.patch(
        f"/api/development-cases/{other_case_id}",
        headers=headers,
        json={"title": "Attempted overwrite"},
    )
    cross_case_transition = client.post(
        f"/api/development-cases/{other_case_id}/transitions",
        headers=headers,
        json={"to_status": "evaluating"},
    )
    assert (
        cross_case_get.status_code
        == unknown_case_get.status_code
        == cross_case_patch.status_code
        == cross_case_transition.status_code
        == 404
    )
    assert cross_case_get.json() == unknown_case_get.json() == cross_case_patch.json()
    assert cross_case_get.json()["detail"]["code"] == "DEVELOPMENT_CASE_NOT_FOUND"

    invalid_transition = client.post(
        f"/api/development-cases/{first.json()['development_case']['id']}/transitions",
        headers=headers,
        json={"to_status": "approved"},
    )
    assert invalid_transition.status_code == 409
    assert invalid_transition.json()["detail"]["code"] == "CASE_INVALID_TRANSITION"

    engine = create_engine(psycopg_database_url(isolated_case_database))
    try:
        with engine.connect() as connection:
            assert set(
                connection.execute(
                    select(tables.development_cases.c.code).where(
                        tables.development_cases.c.tenant_id == tenant_id
                    )
                ).scalars()
            ) == {"CASE-FIRST"}
    finally:
        engine.dispose()


def test_case_state_machine_and_role_matrix(
    client: TestClient,
    isolated_case_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    for username, role in (
        ("manager", Role.PROJECT_MANAGER),
        ("engineer", Role.ENGINEER),
        ("quality", Role.QUALITY),
        ("supplier", Role.SUPPLIER),
    ):
        seed_user(isolated_case_database, tenant_id=tenant_id, username=username, role=role)
    owner_headers = bearer_headers(client)
    pm_headers = bearer_headers(client, username="manager")
    engineer_headers = bearer_headers(client, username="engineer")
    quality_headers = bearer_headers(client, username="quality")
    supplier_headers = bearer_headers(client, username="supplier")

    requirement = create_approved_requirement(client, owner_headers, "REQ-STATE")
    case = convert_requirement(client, pm_headers, requirement["id"], code="CASE-STATE").json()[
        "development_case"
    ]
    case_url = f"/api/development-cases/{case['id']}"
    assert client.get(case_url, headers=engineer_headers).status_code == 200
    assert client.get(case_url, headers=quality_headers).status_code == 200
    assert client.get(case_url, headers=supplier_headers).status_code == 403
    assert (
        client.patch(case_url, headers=engineer_headers, json={"title": "Denied"}).status_code
        == 403
    )

    edited = client.patch(
        case_url,
        headers=pm_headers,
        json={"title": "Edited case", "business_case": {"npv": 125000}},
    )
    assert edited.status_code == 200
    assert edited.json()["title"] == "Edited case"

    evaluating = client.post(
        f"{case_url}/transitions", headers=pm_headers, json={"to_status": "evaluating"}
    )
    approved = client.post(
        f"{case_url}/transitions", headers=pm_headers, json={"to_status": "approved"}
    )
    assert evaluating.status_code == approved.status_code == 200
    assert approved.json()["status"] == "approved"
    needs_project = client.post(
        f"{case_url}/transitions", headers=pm_headers, json={"to_status": "converted"}
    )
    assert needs_project.status_code == 409
    assert needs_project.json()["detail"]["code"] == "CASE_PROJECT_REQUIRED"

    engine = create_engine(psycopg_database_url(isolated_case_database))
    try:
        with engine.begin() as connection:
            workflow_id = uuid4()
            connection.execute(
                tables.workflows.insert(),
                {
                    "id": workflow_id,
                    "tenant_id": tenant_id,
                    "code": "NPD",
                    "name": "NPD",
                },
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "development_case_id": UUID(case["id"]),
                    "workflow_id": workflow_id,
                    "code": "PRJ-STATE",
                    "name": "State machine project",
                },
            )
    finally:
        engine.dispose()
    converted = client.post(
        f"{case_url}/transitions", headers=pm_headers, json={"to_status": "converted"}
    )
    assert converted.status_code == 200
    assert converted.json()["status"] == "converted"
    assert client.patch(case_url, headers=pm_headers, json={"title": "Too late"}).status_code == 409

    rejected_requirement = create_approved_requirement(client, owner_headers, "REQ-REJECT")
    rejected_case = convert_requirement(
        client,
        pm_headers,
        rejected_requirement["id"],
        code="CASE-REJECT",
    ).json()["development_case"]
    rejected_url = f"/api/development-cases/{rejected_case['id']}"
    assert (
        client.post(
            f"{rejected_url}/transitions",
            headers=pm_headers,
            json={"to_status": "evaluating"},
        ).status_code
        == 200
    )
    rejected = client.post(
        f"{rejected_url}/transitions",
        headers=pm_headers,
        json={"to_status": "rejected"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert (
        client.patch(rejected_url, headers=pm_headers, json={"title": "Too late"}).status_code
        == 409
    )
    assert (
        client.post(
            f"{rejected_url}/transitions",
            headers=pm_headers,
            json={"to_status": "approved"},
        ).status_code
        == 409
    )

    denied_requirement = create_approved_requirement(client, owner_headers, "REQ-DENIED")
    for denied_headers in (engineer_headers, quality_headers, supplier_headers):
        assert (
            convert_requirement(
                client,
                denied_headers,
                denied_requirement["id"],
                code=f"CASE-DENIED-{len(denied_headers)}",
            ).status_code
            == 403
        )


def test_conversion_rolls_back_every_business_write_when_event_recording_fails(
    monkeypatch: pytest.MonkeyPatch,
    isolated_case_database: str,
) -> None:
    case_id = uuid4()
    decision_id = uuid4()
    with TestClient(app, raise_server_exceptions=False) as error_client:
        setup = error_client.post("/api/setup", json=SETUP_PAYLOAD).json()
        tenant_id = UUID(setup["tenant"]["id"])
        headers = bearer_headers(error_client)
        requirement = create_approved_requirement(error_client, headers, "REQ-ROLLBACK")

        engine = create_engine(psycopg_database_url(isolated_case_database))
        try:
            with engine.begin() as connection:
                connection.execute(
                    tables.events.insert(),
                    {
                        "tenant_id": tenant_id,
                        "event_id": f"development-case:{case_id}:created",
                        "event_type": "DEVELOPMENT_CASE_CREATED",
                        "schema_version": 1,
                        "source": "development_case_service",
                        "entity": "development_case",
                        "entity_id": case_id,
                        "payload": {
                            "case_code": "COLLISION",
                            "requirement_id": requirement["id"],
                            "status": "draft",
                        },
                    },
                )
        finally:
            engine.dispose()

        generated_ids = iter((case_id, decision_id))
        monkeypatch.setattr(
            "app.domain.development_cases.uuid4",
            lambda: next(generated_ids),
        )
        failed = convert_requirement(
            error_client,
            headers,
            requirement["id"],
            code="CASE-ROLLBACK",
        )
        assert failed.status_code == 500

    engine = create_engine(psycopg_database_url(isolated_case_database))
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(
                    select(tables.requirements.c.status).where(
                        tables.requirements.c.id == UUID(requirement["id"])
                    )
                ).scalar_one()
                == "approved"
            )
            assert (
                connection.execute(
                    select(tables.development_cases.c.id).where(
                        tables.development_cases.c.tenant_id == tenant_id
                    )
                ).all()
                == []
            )
            assert (
                connection.execute(
                    select(tables.decisions.c.id).where(tables.decisions.c.tenant_id == tenant_id)
                ).all()
                == []
            )
            assert (
                connection.execute(
                    select(tables.audit_log.c.id).where(
                        tables.audit_log.c.tenant_id == tenant_id,
                        tables.audit_log.c.entity.in_({"development_case", "decision"}),
                    )
                ).all()
                == []
            )
    finally:
        engine.dispose()
