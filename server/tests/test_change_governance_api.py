from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text

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
def isolated_change_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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
        get_engine().dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def seed_project(database_url: str, tenant_id: UUID, owner_id: UUID) -> dict[str, UUID]:
    ids = {
        name: uuid4()
        for name in (
            "requirement",
            "case",
            "workflow",
            "pvt",
            "project",
            "gate",
            "ebom",
            "prototype",
            "item",
            "manager",
        )
    }
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.users.insert(),
                {
                    "id": ids["manager"],
                    "tenant_id": tenant_id,
                    "username": "manager",
                    "display_name": "Manager",
                    "role": Role.PROJECT_MANAGER.value,
                    "password_hash": PasswordService().hash(PASSWORD),
                },
            )
            connection.execute(
                tables.requirements.insert(),
                {
                    "id": ids["requirement"],
                    "tenant_id": tenant_id,
                    "created_by_user_id": owner_id,
                    "code": "REQ-CHANGE",
                    "title": "Change",
                    "status": "converted",
                },
            )
            connection.execute(
                tables.development_cases.insert(),
                {
                    "id": ids["case"],
                    "tenant_id": tenant_id,
                    "requirement_id": ids["requirement"],
                    "created_by_user_id": owner_id,
                    "code": "CASE-CHANGE",
                    "title": "Change",
                    "status": "converted",
                },
            )
            connection.execute(
                tables.workflows.insert(),
                {
                    "id": ids["workflow"],
                    "tenant_id": tenant_id,
                    "code": "npd-change",
                    "name": "NPD Change",
                },
            )
            connection.execute(
                tables.stages.insert(),
                {
                    "id": ids["pvt"],
                    "tenant_id": tenant_id,
                    "workflow_id": ids["workflow"],
                    "code": "pvt",
                    "name": "PVT",
                    "sequence": 1,
                },
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": ids["project"],
                    "tenant_id": tenant_id,
                    "development_case_id": ids["case"],
                    "workflow_id": ids["workflow"],
                    "current_stage_id": ids["pvt"],
                    "owner_user_id": owner_id,
                    "code": "PRJ-CHANGE",
                    "name": "Change project",
                    "status": "active",
                },
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
                    for user_id in (owner_id, ids["manager"])
                ],
            )
            connection.execute(
                tables.gates.insert(),
                {
                    "id": ids["gate"],
                    "tenant_id": tenant_id,
                    "project_id": ids["project"],
                    "stage_id": ids["pvt"],
                    "code": "pvt",
                    "name": "PVT Gate",
                },
            )
            connection.execute(
                tables.development_boms.insert(),
                [
                    {
                        "id": ids["ebom"],
                        "tenant_id": tenant_id,
                        "project_id": ids["project"],
                        "created_by_user_id": owner_id,
                        "bom_type": "ebom",
                        "code": "EBOM-1",
                        "name": "Released EBOM",
                    },
                    {
                        "id": ids["prototype"],
                        "tenant_id": tenant_id,
                        "project_id": ids["project"],
                        "created_by_user_id": owner_id,
                        "bom_type": "prototype",
                        "code": "PBOM-1",
                        "name": "Prototype BOM",
                    },
                ],
            )
            connection.execute(
                tables.development_bom_items.insert(),
                {
                    "id": ids["item"],
                    "tenant_id": tenant_id,
                    "project_id": ids["project"],
                    "bom_id": ids["ebom"],
                    "line_number": 10,
                    "part_number": "P-100",
                    "description": "Housing",
                    "quantity": 2,
                    "unit": "ea",
                    "attributes": {"finish": "black"},
                },
            )
    finally:
        engine.dispose()
    return ids


def test_change_chain_freezes_handoff_and_requires_pvt_gate(
    client: TestClient, isolated_change_database: str
) -> None:
    setup = client.post(
        "/api/setup",
        json={
            "tenant_slug": "beepump",
            "tenant_name": "Beehive",
            "username": "owner",
            "password": PASSWORD,
            "display_name": "Owner",
        },
    ).json()
    tenant_id, owner_id = UUID(setup["tenant"]["id"]), UUID(setup["user"]["id"])
    ids = seed_project(isolated_change_database, tenant_id, owner_id)
    owner_headers, manager_headers = login(client, "owner"), login(client, "manager")
    base = f"/api/projects/{ids['project']}/changes"

    ecr = client.post(
        f"{base}/ecrs",
        headers=owner_headers,
        json={"code": "ECR-1", "title": "Housing finish", "reason": "Supplier change"},
    )
    assert ecr.status_code == 201
    ecr_id = ecr.json()["id"]
    assert (
        client.post(f"{base}/ecrs/{ecr_id}/start-impact", headers=owner_headers).json()["status"]
        == "impact_analysis"
    )
    impact = client.post(
        f"{base}/ecrs/{ecr_id}/submit-impact",
        headers=owner_headers,
        json={
            "impact_analysis": {"cost": "neutral", "quality": "retest"},
            "affected_bom_ids": [str(ids["ebom"])],
        },
    )
    assert impact.status_code == 200 and impact.json()["status"] == "approval"
    self_approval = client.post(
        f"{base}/ecrs/{ecr_id}/decide", headers=owner_headers, json={"outcome": "approved"}
    )
    assert self_approval.status_code == 409
    assert self_approval.json()["detail"]["code"] == "CHANGE_FOUR_EYES_REQUIRED"
    approved = client.post(
        f"{base}/ecrs/{ecr_id}/decide",
        headers=manager_headers,
        json={"outcome": "approved", "note": "Impact accepted"},
    )
    assert approved.status_code == 200 and approved.json()["status"] == "approved"

    ecn = client.post(
        f"{base}/ecrs/{ecr_id}/ecns",
        headers=owner_headers,
        json={
            "code": "ECN-1",
            "title": "Release black housing",
            "implementation_plan": {"lot": "next"},
        },
    )
    assert ecn.status_code == 201
    ecn_id = ecn.json()["id"]
    assert (
        client.post(f"{base}/ecns/{ecn_id}/submit-effectivity", headers=owner_headers).status_code
        == 200
    )
    wrong_bom = client.post(
        f"{base}/ecns/{ecn_id}/decide-effectivity",
        headers=manager_headers,
        json={
            "outcome": "approved",
            "effectivity": {"from_lot": "L-100"},
            "released_bom_id": str(ids["prototype"]),
            "target_system": "sap",
        },
    )
    assert wrong_bom.status_code == 409
    effectivity = client.post(
        f"{base}/ecns/{ecn_id}/decide-effectivity",
        headers=manager_headers,
        json={
            "outcome": "approved",
            "effectivity": {"from_lot": "L-100"},
            "released_bom_id": str(ids["ebom"]),
            "target_system": "sap",
        },
    )
    assert effectivity.status_code == 200
    handoff = effectivity.json()["handoff"]
    assert handoff["status"] == "pending"
    assert handoff["source_bom_snapshot"]["header"]["bom_type"] == "ebom"
    assert handoff["source_bom_snapshot"]["items"][0]["quantity"] == "2.000000"
    blocked = client.post(f"{base}/handoffs/{handoff['id']}/ready", headers=manager_headers)
    assert (
        blocked.status_code == 409
        and blocked.json()["detail"]["code"] == "HANDOFF_PVT_GATE_REQUIRED"
    )

    engine = create_engine(psycopg_database_url(isolated_change_database))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.gates.update()
                .where(tables.gates.c.id == ids["gate"])
                .values(
                    status="approved",
                    decided_at=datetime.now(UTC),
                    decided_by_user_id=ids["manager"],
                )
            )
    finally:
        engine.dispose()
    ready = client.post(f"{base}/handoffs/{handoff['id']}/ready", headers=manager_headers)
    assert ready.status_code == 200 and ready.json()["status"] == "ready"
    assert (
        client.post(f"{base}/handoffs/{handoff['id']}/queue", headers=manager_headers).status_code
        == 404
    )

    snapshot = client.get(base, headers=owner_headers).json()
    assert snapshot["ecrs"][0]["affected_bom_ids"] == [str(ids["ebom"])]
    assert snapshot["ecns"][0]["status"] == "erp_handoff"
    assert snapshot["handoffs"][0]["status"] == "ready"
    engine = create_engine(psycopg_database_url(isolated_change_database))
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(
                    select(func.count())
                    .select_from(tables.decisions)
                    .where(
                        tables.decisions.c.decision_kind.in_(("ecr_approval", "ecn_effectivity"))
                    )
                ).scalar_one()
                == 2
            )
            event_count = connection.execute(
                select(func.count())
                .select_from(tables.events)
                .where(tables.events.c.event_type == "CHANGE_RECORD_CHANGED")
            ).scalar_one()
            audit_count = connection.execute(
                select(func.count())
                .select_from(tables.audit_log)
                .where(tables.audit_log.c.action.like("change.%"))
            ).scalar_one()
            assert event_count == audit_count == 9
    finally:
        engine.dispose()
