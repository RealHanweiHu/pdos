from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

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
def isolated_product_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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


def seed_project(database_url: str, *, tenant_id: UUID, owner_id: UUID) -> UUID:
    workflow_id = uuid4()
    project_id = uuid4()
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.workflows.insert(),
                {
                    "id": workflow_id,
                    "tenant_id": tenant_id,
                    "code": "npd-product",
                    "name": "NPD Product",
                },
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": project_id,
                    "tenant_id": tenant_id,
                    "workflow_id": workflow_id,
                    "owner_user_id": owner_id,
                    "code": "PRJ-PRODUCT",
                    "name": "Portable pump",
                },
            )
            connection.execute(
                tables.project_members.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "user_id": owner_id,
                    "added_by_user_id": owner_id,
                },
            )
    finally:
        engine.dispose()
    return project_id


def seed_user(
    database_url: str,
    *,
    tenant_id: UUID,
    project_id: UUID,
    owner_id: UUID,
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
                    "display_name": username.title(),
                    "role": role,
                    "password_hash": PasswordService().hash(PASSWORD),
                },
            )
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
    finally:
        engine.dispose()
    return user_id


def test_specification_and_three_bom_types_are_project_scoped_and_audited(
    client: TestClient,
    isolated_product_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    owner_id = UUID(setup["user"]["id"])
    project_id = seed_project(
        isolated_product_database,
        tenant_id=tenant_id,
        owner_id=owner_id,
    )
    headers = bearer_headers(client)
    base_url = f"/api/projects/{project_id}/product-engineering"

    specification_response = client.post(
        f"{base_url}/specifications",
        headers=headers,
        json={
            "code": "SPEC-C4S",
            "title": "C4s performance specification",
            "version": 1,
            "content": {"rated_pressure_kpa": 1034, "mass_g_max": 520},
        },
    )
    assert specification_response.status_code == 201
    assert specification_response.headers["cache-control"] == "no-store"
    specification = specification_response.json()
    assert specification["project_id"] == str(project_id)
    assert specification["content"]["rated_pressure_kpa"] == 1034
    assert client.get(f"{base_url}/specifications", headers=headers).json() == {
        "items": [specification]
    }

    boms: dict[str, dict[str, object]] = {}
    for bom_type in ("ebom", "prototype", "cost"):
        response = client.post(
            f"{base_url}/boms",
            headers=headers,
            json={
                "specification_id": specification["id"],
                "bom_type": bom_type,
                "code": f"C4S-{bom_type.upper()}",
                "name": f"C4s {bom_type} BOM",
                "version": 1,
            },
        )
        assert response.status_code == 201
        boms[bom_type] = response.json()

    item_response = client.post(
        f"{base_url}/boms/{boms['cost']['id']}/items",
        headers=headers,
        json={
            "line_number": 10,
            "part_number": "C4S-HOUSING",
            "description": "Pump housing",
            "quantity": "1.000000",
            "unit": "ea",
            "material_reference": "ERP-MAT-1001",
            "attributes": {"material": "PA66-GF30"},
            "cost": {"currency": "CNY", "unit_cost": "12.3400", "cost_category": "material"},
        },
    )
    assert item_response.status_code == 201
    item = item_response.json()
    assert item["cost"] == {
        "currency": "CNY",
        "unit_cost": "12.3400",
        "cost_category": "material",
    }

    reference_response = client.post(
        f"{base_url}/erp-references",
        headers=headers,
        json={
            "bom_id": boms["ebom"]["id"],
            "reference_type": "routing",
            "source_system": "erp",
            "external_id": "ROUTING-9001",
        },
    )
    assert reference_response.status_code == 201
    assert reference_response.json()["reference_type"] == "routing"

    listed_boms = client.get(f"{base_url}/boms", headers=headers)
    assert listed_boms.status_code == 200
    assert {bom["bom_type"] for bom in listed_boms.json()["items"]} == {
        "ebom",
        "prototype",
        "cost",
    }
    cost_bom = next(bom for bom in listed_boms.json()["items"] if bom["bom_type"] == "cost")
    assert cost_bom["items"] == [item]
    assert client.get(f"{base_url}/erp-references", headers=headers).json() == {
        "items": [reference_response.json()]
    }

    engine = create_engine(psycopg_database_url(isolated_product_database))
    try:
        with engine.connect() as connection:
            event_types = set(
                connection.execute(
                    select(tables.events.c.event_type).where(
                        tables.events.c.project_id == project_id
                    )
                ).scalars()
            )
            audit_actions = set(
                connection.execute(
                    select(tables.audit_log.c.action).where(
                        tables.audit_log.c.project_id == project_id
                    )
                ).scalars()
            )
    finally:
        engine.dispose()
    assert {
        "SPECIFICATION_CREATED",
        "DEVELOPMENT_BOM_CREATED",
        "DEVELOPMENT_BOM_ITEM_ADDED",
        "ERP_BOM_REFERENCE_ADDED",
    } <= event_types
    assert {
        "specification.create",
        "development_bom.create",
        "development_bom_item.add",
        "erp_bom_reference.add",
    } <= audit_actions


def test_product_engineering_rejects_erp_truth_cross_tenant_and_external_roles(
    client: TestClient,
    isolated_product_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    owner_id = UUID(setup["user"]["id"])
    project_id = seed_project(
        isolated_product_database,
        tenant_id=tenant_id,
        owner_id=owner_id,
    )
    engineer_id = seed_user(
        isolated_product_database,
        tenant_id=tenant_id,
        project_id=project_id,
        owner_id=owner_id,
        username="engineer",
        role=Role.ENGINEER,
    )
    seed_user(
        isolated_product_database,
        tenant_id=tenant_id,
        project_id=project_id,
        owner_id=owner_id,
        username="supplier",
        role=Role.SUPPLIER,
    )
    owner_headers = bearer_headers(client)
    engineer_headers = bearer_headers(client, username="engineer")
    supplier_headers = bearer_headers(client, username="supplier")
    base_url = f"/api/projects/{project_id}/product-engineering"

    assert client.get(f"{base_url}/boms", headers=engineer_headers).status_code == 200
    assert (
        client.post(
            f"{base_url}/specifications",
            headers=engineer_headers,
            json={"code": "SPEC-ENG", "title": "Engineer specification", "version": 1},
        ).status_code
        == 201
    )
    assert client.get(f"{base_url}/boms", headers=supplier_headers).status_code == 403
    assert (
        client.post(
            f"{base_url}/boms",
            headers=owner_headers,
            json={
                "bom_type": "mbom",
                "code": "INVALID-MBOM",
                "name": "ERP truth must not be created here",
                "version": 1,
            },
        ).status_code
        == 422
    )

    other_tenant_id = uuid4()
    other_owner_id = uuid4()
    other_workflow_id = uuid4()
    other_project_id = uuid4()
    other_specification_id = uuid4()
    engine = create_engine(psycopg_database_url(isolated_product_database))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": other_tenant_id, "slug": "other-product", "name": "Other Product"},
            )
            connection.execute(
                tables.users.insert(),
                {
                    "id": other_owner_id,
                    "tenant_id": other_tenant_id,
                    "username": "other-owner",
                    "display_name": "Other Owner",
                    "role": "owner",
                },
            )
            connection.execute(
                tables.workflows.insert(),
                {
                    "id": other_workflow_id,
                    "tenant_id": other_tenant_id,
                    "code": "other-npd",
                    "name": "Other NPD",
                },
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": other_project_id,
                    "tenant_id": other_tenant_id,
                    "workflow_id": other_workflow_id,
                    "code": "OTHER-PRJ",
                    "name": "Other project",
                },
            )
            connection.execute(
                tables.specifications.insert(),
                {
                    "id": other_specification_id,
                    "tenant_id": other_tenant_id,
                    "project_id": other_project_id,
                    "created_by_user_id": other_owner_id,
                    "code": "OTHER-SPEC",
                    "title": "Other specification",
                    "version": 1,
                },
            )
    finally:
        engine.dispose()

    unknown = client.post(
        f"{base_url}/boms",
        headers=owner_headers,
        json={
            "specification_id": str(uuid4()),
            "bom_type": "ebom",
            "code": "UNKNOWN-SPEC",
            "name": "Unknown specification",
            "version": 1,
        },
    )
    cross_tenant = client.post(
        f"{base_url}/boms",
        headers=owner_headers,
        json={
            "specification_id": str(other_specification_id),
            "bom_type": "ebom",
            "code": "CROSS-SPEC",
            "name": "Cross-tenant specification",
            "version": 1,
        },
    )
    assert unknown.status_code == 404
    assert cross_tenant.status_code == 404
    assert unknown.json() == cross_tenant.json()
    assert engineer_id
