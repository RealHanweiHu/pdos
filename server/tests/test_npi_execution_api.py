from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select

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
def isolated_npi_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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


def login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def seed_evt_project(
    database_url: str,
    tenant_id: UUID,
    owner_id: UUID,
    *,
    phase: str = "evt",
) -> tuple[UUID, UUID, UUID]:
    workflow_id, stage_id, project_id = uuid4(), uuid4(), uuid4()
    requirement_id, case_id, gate_id, bom_id = uuid4(), uuid4(), uuid4(), uuid4()
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.requirements.insert(),
                {
                    "id": requirement_id,
                    "tenant_id": tenant_id,
                    "created_by_user_id": owner_id,
                    "code": "REQ-NPI",
                    "title": "NPI",
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
                    "code": "CASE-NPI",
                    "title": "NPI",
                    "status": "converted",
                },
            )
            connection.execute(
                tables.workflows.insert(),
                {"id": workflow_id, "tenant_id": tenant_id, "code": "npd-npi", "name": "NPD NPI"},
            )
            connection.execute(
                tables.stages.insert(),
                {
                    "id": stage_id,
                    "tenant_id": tenant_id,
                    "workflow_id": workflow_id,
                    "code": phase,
                    "name": phase.upper(),
                    "sequence": 1,
                },
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": project_id,
                    "tenant_id": tenant_id,
                    "development_case_id": case_id,
                    "workflow_id": workflow_id,
                    "current_stage_id": stage_id,
                    "owner_user_id": owner_id,
                    "code": "PRJ-NPI",
                    "name": "NPI project",
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
                    "stage_id": stage_id,
                    "code": phase,
                    "name": f"{phase.upper()} Gate",
                },
            )
            connection.execute(
                tables.development_boms.insert(),
                {
                    "id": bom_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "created_by_user_id": owner_id,
                    "bom_type": "prototype",
                    "code": "PBOM-1",
                    "name": "Prototype BOM",
                },
            )
    finally:
        engine.dispose()
    return project_id, stage_id, bom_id


def seed_supplier(database_url: str, tenant_id: UUID, project_id: UUID, owner_id: UUID) -> None:
    engine = create_engine(psycopg_database_url(database_url))
    try:
        user_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                tables.users.insert(),
                {
                    "id": user_id,
                    "tenant_id": tenant_id,
                    "username": "supplier",
                    "display_name": "Supplier",
                    "role": Role.SUPPLIER.value,
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


def test_evt_build_sample_test_signoff_and_certification_are_end_to_end(
    client: TestClient,
    isolated_npi_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id, owner_id = UUID(setup["tenant"]["id"]), UUID(setup["user"]["id"])
    project_id, stage_id, bom_id = seed_evt_project(isolated_npi_database, tenant_id, owner_id)
    seed_supplier(isolated_npi_database, tenant_id, project_id, owner_id)
    owner_headers, supplier_headers = login(client, "owner"), login(client, "supplier")

    build = client.post(
        f"/api/projects/{project_id}/npi/builds",
        headers=owner_headers,
        json={"stage_id": str(stage_id), "phase": "evt", "code": "EVT-001", "planned_quantity": 2},
    )
    assert build.status_code == 201
    build_id = build.json()["id"]
    assert (
        client.post(
            f"/api/projects/{project_id}/npi/builds",
            headers=supplier_headers,
            json={
                "stage_id": str(stage_id),
                "phase": "evt",
                "code": "INJECTED",
                "planned_quantity": 1,
            },
        ).status_code
        == 403
    )
    first = client.post(
        f"/api/projects/{project_id}/npi/builds/{build_id}/samples",
        headers=owner_headers,
        json={"serial_number": "EVT-0001", "prototype_bom_id": str(bom_id)},
    )
    assert first.status_code == 201
    second = client.post(
        f"/api/projects/{project_id}/npi/builds/{build_id}/samples",
        headers=owner_headers,
        json={
            "serial_number": "EVT-0002",
            "parent_sample_id": first.json()["id"],
            "prototype_bom_id": str(bom_id),
        },
    )
    assert second.status_code == 201
    assert (
        client.post(
            f"/api/projects/{project_id}/npi/builds/{build_id}/samples",
            headers=owner_headers,
            json={"serial_number": "EVT-0003", "prototype_bom_id": str(bom_id)},
        ).status_code
        == 409
    )

    signoff = client.post(
        f"/api/projects/{project_id}/npi/sample-signoffs",
        headers=owner_headers,
        json={
            "phase": "evt",
            "title": "Supplier sample",
            "signoff_type": "evt_sample",
            "audience": "supplier",
            "sample_ids": [first.json()["id"]],
        },
    )
    assert signoff.status_code == 201
    external_snapshot = client.get(
        f"/api/projects/{project_id}/npi", headers=supplier_headers
    ).json()
    assert external_snapshot["sample_signoffs"][0]["audience"] == "supplier"
    assert external_snapshot["sample_signoffs"][0]["sample_ids"] == [first.json()["id"]]
    assert external_snapshot["samples"] == []
    responded = client.post(
        f"/api/projects/{project_id}/npi/sample-signoffs/{signoff.json()['id']}/respond",
        headers=supplier_headers,
        json={"status": "approved", "note": "checked"},
    )
    assert responded.status_code == 200

    plan = client.post(
        f"/api/projects/{project_id}/npi/test-plans",
        headers=owner_headers,
        json={
            "stage_id": str(stage_id),
            "phase": "evt",
            "title": "EVT validation",
            "sample_size": 2,
            "status": "active",
        },
    )
    assert plan.status_code == 201
    case = client.post(
        f"/api/projects/{project_id}/npi/test-plans/{plan.json()['id']}/cases",
        headers=owner_headers,
        json={
            "title": "Drop test",
            "category": "reliability",
            "acceptance_criteria": "No functional damage",
            "severity": "critical",
            "sample_ids": [first.json()["id"], second.json()["id"]],
        },
    )
    assert case.status_code == 201
    failed = client.post(
        f"/api/projects/{project_id}/npi/test-cases/{case.json()['id']}/result",
        headers=owner_headers,
        json={"status": "failed", "result_notes": "Housing cracked"},
    )
    assert failed.status_code == 200

    report = client.post(
        f"/api/projects/{project_id}/npi/test-plans/{plan.json()['id']}/reports",
        headers=owner_headers,
        json={
            "report_number": "TR-EVT-001",
            "title": "EVT report",
            "result": "pass",
            "summary": "Retest passed",
        },
    )
    assert report.status_code == 201
    assert (
        client.post(
            f"/api/projects/{project_id}/npi/test-reports/{report.json()['id']}/review",
            headers=owner_headers,
            json={"review_status": "approved", "note": "QA approved"},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/projects/{project_id}/npi/builds/{build_id}",
            headers=owner_headers,
            json={"status": "completed", "completed_quantity": 2},
        ).status_code
        == 200
    )

    gate = client.get(f"/api/projects/{project_id}/gates", headers=owner_headers).json()["items"][0]
    assert any(key.startswith("test_case:") for key in gate["readiness"]["blocker_keys"])
    assert (
        client.post(
            f"/api/projects/{project_id}/npi/test-cases/{case.json()['id']}/result",
            headers=owner_headers,
            json={"status": "passed", "result_notes": "Retest passed"},
        ).status_code
        == 200
    )
    gate_after_retest = client.get(
        f"/api/projects/{project_id}/gates", headers=owner_headers
    ).json()["items"][0]
    assert gate_after_retest["readiness"]["blocker_keys"] == ["round:not_open"]

    expiry = date.today() + timedelta(days=30)
    certificate = client.post(
        f"/api/projects/{project_id}/npi/certifications",
        headers=owner_headers,
        json={
            "certificate_type": "product_safety",
            "certificate_number": "CERT-1",
            "issuing_body": "Lab",
            "target_markets": ["US"],
            "status": "valid",
            "is_required": True,
            "valid_from": str(date.today()),
            "valid_until": str(expiry),
        },
    )
    assert certificate.status_code == 201
    first_scan = client.post(
        f"/api/projects/{project_id}/npi/certifications/scan",
        headers=owner_headers,
        json={"as_of": str(date.today())},
    )
    second_scan = client.post(
        f"/api/projects/{project_id}/npi/certifications/scan",
        headers=owner_headers,
        json={"as_of": str(date.today())},
    )
    assert first_scan.json()["alerts_created"] == 1
    assert second_scan.json()["alerts_created"] == 0
    expired_scan = client.post(
        f"/api/projects/{project_id}/npi/certifications/scan",
        headers=owner_headers,
        json={"as_of": str(expiry + timedelta(days=1))},
    )
    assert expired_scan.json() == {"expired_count": 1, "alerts_created": 0}
    repeated_expired_scan = client.post(
        f"/api/projects/{project_id}/npi/certifications/scan",
        headers=owner_headers,
        json={"as_of": str(expiry + timedelta(days=1))},
    )
    assert repeated_expired_scan.json() == {"expired_count": 0, "alerts_created": 0}

    engine = create_engine(psycopg_database_url(isolated_npi_database))
    try:
        with engine.connect() as connection:
            failed_event = connection.execute(
                select(tables.events.c.payload).where(tables.events.c.event_type == "TEST_FAILED")
            ).scalar_one()
            assert failed_event == {
                "test_record_id": case.json()["id"],
                "severity": "critical",
            }
            assert (
                connection.execute(
                    select(func.count()).select_from(tables.certification_expiry_alerts)
                ).scalar_one()
                == 1
            )
            npi_event_count = connection.execute(
                select(func.count())
                .select_from(tables.events)
                .where(tables.events.c.event_type.in_(("NPI_RECORD_CHANGED", "TEST_FAILED")))
            ).scalar_one()
            npi_audit_count = connection.execute(
                select(func.count())
                .select_from(tables.audit_log)
                .where(tables.audit_log.c.action.like("npi.%"))
            ).scalar_one()
            assert npi_event_count == npi_audit_count
    finally:
        engine.dispose()


def test_pvt_gate_blocks_required_expired_certification(
    client: TestClient,
    isolated_npi_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id, owner_id = UUID(setup["tenant"]["id"]), UUID(setup["user"]["id"])
    project_id, _, _ = seed_evt_project(
        isolated_npi_database,
        tenant_id,
        owner_id,
        phase="pvt",
    )
    certification_id = uuid4()
    engine = create_engine(psycopg_database_url(isolated_npi_database))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.certifications.insert(),
                {
                    "id": certification_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "owner_user_id": owner_id,
                    "created_by_user_id": owner_id,
                    "certificate_type": "product_safety",
                    "status": "expired",
                    "is_required": True,
                    "valid_until": date.today() - timedelta(days=1),
                },
            )
    finally:
        engine.dispose()

    gate = client.get(f"/api/projects/{project_id}/gates", headers=login(client, "owner")).json()[
        "items"
    ][0]
    assert f"certification:{certification_id}" in gate["readiness"]["blocker_keys"]
