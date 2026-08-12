from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text

from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.main import app
from app.settings import get_settings

SERVER_ROOT = Path(__file__).resolve().parents[1]
TEST_JWT_SECRET = "test-only-jwt-secret-that-is-at-least-32-bytes"
PASSWORD = "correct horse battery staple"
STAGE_CODES = ("concept", "planning", "design", "evt", "dvt", "pvt", "mp")


@pytest.fixture(autouse=True)
def isolated_deliverable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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


def login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": "owner", "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def seed_npd_project(database_url: str, tenant_id: UUID, owner_id: UUID) -> tuple[UUID, UUID]:
    requirement_id, case_id, workflow_id, project_id = uuid4(), uuid4(), uuid4(), uuid4()
    stage_ids = {code: uuid4() for code in STAGE_CODES}
    gate_id = uuid4()
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.requirements.insert(),
                {
                    "id": requirement_id,
                    "tenant_id": tenant_id,
                    "created_by_user_id": owner_id,
                    "code": "REQ-CHECK",
                    "title": "Deliverable checks",
                    "status": "converted",
                },
            )
            connection.execute(
                tables.development_cases.insert(),
                {
                    "id": case_id,
                    "tenant_id": tenant_id,
                    "requirement_id": requirement_id,
                    "created_by_user_id": owner_id,
                    "code": "CASE-CHECK",
                    "title": "Deliverable checks",
                    "status": "converted",
                },
            )
            connection.execute(
                tables.workflows.insert(),
                {
                    "id": workflow_id,
                    "tenant_id": tenant_id,
                    "code": f"npd-{project_id}",
                    "name": "NPD checks",
                },
            )
            connection.execute(
                tables.stages.insert(),
                [
                    {
                        "id": stage_ids[code],
                        "tenant_id": tenant_id,
                        "workflow_id": workflow_id,
                        "code": code,
                        "name": code.upper(),
                        "sequence": sequence,
                    }
                    for sequence, code in enumerate(STAGE_CODES, start=1)
                ],
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": project_id,
                    "tenant_id": tenant_id,
                    "development_case_id": case_id,
                    "workflow_id": workflow_id,
                    "current_stage_id": stage_ids["concept"],
                    "owner_user_id": owner_id,
                    "code": "PRJ-CHECK",
                    "name": "Deliverable checks",
                    "status": "active",
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
            connection.execute(
                tables.gates.insert(),
                {
                    "id": gate_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "stage_id": stage_ids["concept"],
                    "code": "concept",
                    "name": "Concept Gate",
                },
            )
    finally:
        engine.dispose()
    return project_id, gate_id


def test_manifest_import_project_binding_completion_and_gate_blockers_are_end_to_end(
    client: TestClient,
    isolated_deliverable_database: str,
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
    project_id, _ = seed_npd_project(isolated_deliverable_database, tenant_id, owner_id)
    headers = login(client)
    base = f"/api/projects/{project_id}/deliverable-checks"
    assert client.get(base).status_code == 401
    assert (
        client.get(f"/api/projects/{uuid4()}/deliverable-checks", headers=headers).status_code
        == 403
    )

    prepared = client.post(f"{base}/prepare", headers=headers)
    assert prepared.status_code == 200
    assert prepared.json() == {
        "asset_schema_version": 3,
        "library_count": 687,
        "imported_count": 687,
        "project_type": "npd",
        "created_count": 282,
        "project_item_count": 282,
    }
    repeated = client.post(f"{base}/prepare", headers=headers)
    assert repeated.status_code == 200
    assert repeated.json()["imported_count"] == 0
    assert repeated.json()["created_count"] == 0
    assert repeated.json()["project_item_count"] == 282

    items = client.get(base, headers=headers).json()["items"]
    concept_gate_items = [
        item for item in items if item["phase_id"] == "concept" and item["is_gate"]
    ]
    concept_non_gate = next(
        item for item in items if item["phase_id"] == "concept" and not item["is_gate"]
    )
    assert len(concept_gate_items) == 6
    readiness = client.get(f"/api/projects/{project_id}/gates", headers=headers).json()["items"][0][
        "readiness"
    ]
    assert (
        len([key for key in readiness["blocker_keys"] if key.startswith("deliverable_check:")]) == 6
    )

    gate_item = concept_gate_items[0]
    no_evidence = client.post(
        f"{base}/items/{gate_item['id']}/resolve",
        headers=headers,
        json={"status": "completed"},
    )
    assert no_evidence.status_code == 409
    no_gate_bypass = client.post(
        f"{base}/items/{gate_item['id']}/resolve",
        headers=headers,
        json={"status": "not_applicable", "note": "skip"},
    )
    assert no_gate_bypass.status_code == 409
    completed = client.post(
        f"{base}/items/{gate_item['id']}/resolve",
        headers=headers,
        json={"status": "completed", "evidence_reference": "doc://concept-review"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    waived = client.post(
        f"{base}/items/{concept_non_gate['id']}/resolve",
        headers=headers,
        json={"status": "not_applicable", "note": "Not used by pilot"},
    )
    assert waived.status_code == 200
    readiness_after = client.get(f"/api/projects/{project_id}/gates", headers=headers).json()[
        "items"
    ][0]["readiness"]
    assert (
        len(
            [key for key in readiness_after["blocker_keys"] if key.startswith("deliverable_check:")]
        )
        == 5
    )

    engine = create_engine(psycopg_database_url(isolated_deliverable_database))
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(
                    select(func.count()).select_from(tables.deliverable_check_templates)
                ).scalar_one()
                == 687
            )
            event_count = connection.execute(
                select(func.count())
                .select_from(tables.events)
                .where(tables.events.c.event_type == "DELIVERABLE_CHECK_CHANGED")
            ).scalar_one()
            audit_count = connection.execute(
                select(func.count())
                .select_from(tables.audit_log)
                .where(tables.audit_log.c.action.like("deliverable_check.%"))
            ).scalar_one()
            assert event_count == audit_count == 4
    finally:
        engine.dispose()
