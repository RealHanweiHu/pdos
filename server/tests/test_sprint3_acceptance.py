from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
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
def isolated_sprint3_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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


def _login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _seed_acceptance_project(
    database_url: str,
    *,
    tenant_id: UUID,
    owner_id: UUID,
) -> dict[str, UUID]:
    ids = {
        name: uuid4()
        for name in (
            "requirement",
            "case",
            "workflow",
            "evt",
            "dvt",
            "pvt",
            "mp",
            "project",
            "evt_gate",
            "dvt_gate",
            "pvt_gate",
            "mp_gate",
            "prototype_bom",
            "ebom",
            "ebom_item",
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
                    "display_name": "Project Manager",
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
                    "code": "REQ-S3-EXIT",
                    "title": "Sprint 3 integrated acceptance",
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
                    "code": "CASE-S3-EXIT",
                    "title": "Sprint 3 integrated acceptance",
                    "status": "converted",
                },
            )
            connection.execute(
                tables.workflows.insert(),
                {
                    "id": ids["workflow"],
                    "tenant_id": tenant_id,
                    "code": "npd-sprint3-exit",
                    "name": "NPD Sprint 3 Exit",
                },
            )
            connection.execute(
                tables.stages.insert(),
                [
                    {
                        "id": ids[phase],
                        "tenant_id": tenant_id,
                        "workflow_id": ids["workflow"],
                        "code": phase,
                        "name": phase.upper(),
                        "sequence": sequence,
                    }
                    for sequence, phase in enumerate(("evt", "dvt", "pvt", "mp"), 1)
                ],
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": ids["project"],
                    "tenant_id": tenant_id,
                    "development_case_id": ids["case"],
                    "workflow_id": ids["workflow"],
                    "current_stage_id": ids["evt"],
                    "owner_user_id": owner_id,
                    "code": "PRJ-S3-EXIT",
                    "name": "Sprint 3 integrated acceptance",
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
                [
                    {
                        "id": ids[f"{phase}_gate"],
                        "tenant_id": tenant_id,
                        "project_id": ids["project"],
                        "stage_id": ids[phase],
                        "code": phase,
                        "name": f"{phase.upper()} Gate",
                    }
                    for phase in ("evt", "dvt", "pvt", "mp")
                ],
            )
            connection.execute(
                tables.development_boms.insert(),
                [
                    {
                        "id": ids["prototype_bom"],
                        "tenant_id": tenant_id,
                        "project_id": ids["project"],
                        "created_by_user_id": owner_id,
                        "bom_type": "prototype",
                        "code": "PBOM-S3",
                        "name": "Sprint 3 Prototype BOM",
                    },
                    {
                        "id": ids["ebom"],
                        "tenant_id": tenant_id,
                        "project_id": ids["project"],
                        "created_by_user_id": owner_id,
                        "bom_type": "ebom",
                        "code": "EBOM-S3",
                        "name": "Sprint 3 Released EBOM",
                    },
                ],
            )
            connection.execute(
                tables.development_bom_items.insert(),
                {
                    "id": ids["ebom_item"],
                    "tenant_id": tenant_id,
                    "project_id": ids["project"],
                    "bom_id": ids["ebom"],
                    "line_number": 10,
                    "part_number": "S3-P-100",
                    "description": "Integrated acceptance part",
                    "quantity": 1,
                    "unit": "ea",
                    "attributes": {"revision": "A"},
                },
            )
    finally:
        engine.dispose()
    return ids


def _complete_npi_phase(
    client: TestClient,
    *,
    headers: dict[str, str],
    ids: dict[str, UUID],
    phase: str,
) -> None:
    project_id = ids["project"]
    build = client.post(
        f"/api/projects/{project_id}/npi/builds",
        headers=headers,
        json={
            "stage_id": str(ids[phase]),
            "phase": phase,
            "code": f"{phase.upper()}-S3-001",
            "planned_quantity": 1,
        },
    )
    assert build.status_code == 201, build.text
    sample = client.post(
        f"/api/projects/{project_id}/npi/builds/{build.json()['id']}/samples",
        headers=headers,
        json={
            "serial_number": f"{phase.upper()}-S3-0001",
            "prototype_bom_id": str(ids["prototype_bom"]),
        },
    )
    assert sample.status_code == 201, sample.text
    plan = client.post(
        f"/api/projects/{project_id}/npi/test-plans",
        headers=headers,
        json={
            "stage_id": str(ids[phase]),
            "phase": phase,
            "title": f"{phase.upper()} integrated validation",
            "sample_size": 1,
            "status": "active",
        },
    )
    assert plan.status_code == 201, plan.text
    case = client.post(
        f"/api/projects/{project_id}/npi/test-plans/{plan.json()['id']}/cases",
        headers=headers,
        json={
            "title": f"{phase.upper()} functional test",
            "category": "functional",
            "acceptance_criteria": "All checks pass",
            "severity": "major",
            "sample_ids": [sample.json()["id"]],
        },
    )
    assert case.status_code == 201, case.text
    result = client.post(
        f"/api/projects/{project_id}/npi/test-cases/{case.json()['id']}/result",
        headers=headers,
        json={"status": "passed", "result_notes": "Acceptance passed"},
    )
    assert result.status_code == 200, result.text
    report = client.post(
        f"/api/projects/{project_id}/npi/test-plans/{plan.json()['id']}/reports",
        headers=headers,
        json={
            "report_number": f"TR-{phase.upper()}-S3-001",
            "title": f"{phase.upper()} integrated report",
            "result": "pass",
            "summary": "Acceptance passed",
        },
    )
    assert report.status_code == 201, report.text
    reviewed = client.post(
        f"/api/projects/{project_id}/npi/test-reports/{report.json()['id']}/review",
        headers=headers,
        json={"review_status": "approved", "note": "Acceptance evidence reviewed"},
    )
    assert reviewed.status_code == 200, reviewed.text
    completed = client.patch(
        f"/api/projects/{project_id}/npi/builds/{build.json()['id']}",
        headers=headers,
        json={"status": "completed", "completed_quantity": 1},
    )
    assert completed.status_code == 200, completed.text


def _open_sign_and_approve_gate(
    client: TestClient,
    *,
    headers: dict[str, str],
    ids: dict[str, UUID],
    phase: str,
) -> dict[str, Any]:
    project_id = ids["project"]
    gate_id = ids[f"{phase}_gate"]
    opened = client.post(
        f"/api/projects/{project_id}/gates/{gate_id}/rounds",
        headers=headers,
    )
    assert opened.status_code == 201, opened.text
    round_id = opened.json()["round"]["id"]
    for slot in ("product", "engineering", "quality"):
        signed = client.put(
            f"/api/projects/{project_id}/gates/{gate_id}/rounds/{round_id}/signoffs/{slot}",
            headers=headers,
            json={"status": "approved", "note": f"{phase} {slot} evidence reviewed"},
        )
        assert signed.status_code == 200, signed.text
    approved = client.post(
        f"/api/projects/{project_id}/gates/{gate_id}/decisions",
        headers=headers,
        json={"status": "approved", "rationale": f"{phase.upper()} evidence complete"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["readiness"]["ready"] is True
    return cast(dict[str, Any], approved.json())


def _advance(
    client: TestClient,
    *,
    headers: dict[str, str],
    ids: dict[str, UUID],
    to_phase: str,
) -> None:
    response = client.post(
        f"/api/projects/{ids['project']}/stage-transitions",
        headers=headers,
        json={"to_stage_id": str(ids[to_phase])},
    )
    assert response.status_code == 200, response.text
    assert response.json()["current_stage"]["id"] == str(ids[to_phase])


def test_one_project_completes_evt_dvt_pvt_hard_gates_and_one_ecn(
    client: TestClient,
    isolated_sprint3_database: str,
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
    ids = _seed_acceptance_project(
        isolated_sprint3_database,
        tenant_id=tenant_id,
        owner_id=owner_id,
    )
    owner_headers = _login(client, "owner")
    manager_headers = _login(client, "manager")

    evt_round = client.post(
        f"/api/projects/{ids['project']}/gates/{ids['evt_gate']}/rounds",
        headers=owner_headers,
    )
    assert evt_round.status_code == 201
    for slot in ("product", "engineering", "quality"):
        signed = client.put(
            f"/api/projects/{ids['project']}/gates/{ids['evt_gate']}"
            f"/rounds/{evt_round.json()['round']['id']}/signoffs/{slot}",
            headers=owner_headers,
            json={"status": "approved", "note": "Role evidence complete"},
        )
        assert signed.status_code == 200
    blocked_evt = client.post(
        f"/api/projects/{ids['project']}/gates/{ids['evt_gate']}/decisions",
        headers=owner_headers,
        json={"status": "approved", "rationale": "Attempt before NPI evidence"},
    )
    assert blocked_evt.status_code == 409
    assert blocked_evt.json()["detail"]["code"] == "GATE_NOT_READY"
    assert "build:evt:completed_missing" in blocked_evt.json()["detail"]["blocker_keys"]

    _complete_npi_phase(client, headers=owner_headers, ids=ids, phase="evt")
    approved_evt = client.post(
        f"/api/projects/{ids['project']}/gates/{ids['evt_gate']}/decisions",
        headers=owner_headers,
        json={"status": "approved", "rationale": "EVT evidence complete"},
    )
    assert approved_evt.status_code == 200, approved_evt.text
    _advance(client, headers=owner_headers, ids=ids, to_phase="dvt")

    _complete_npi_phase(client, headers=owner_headers, ids=ids, phase="dvt")
    _open_sign_and_approve_gate(client, headers=owner_headers, ids=ids, phase="dvt")
    _advance(client, headers=owner_headers, ids=ids, to_phase="pvt")

    changes = f"/api/projects/{ids['project']}/changes"
    ecr = client.post(
        f"{changes}/ecrs",
        headers=owner_headers,
        json={"code": "ECR-S3-1", "title": "Release update", "reason": "NPI learning"},
    )
    assert ecr.status_code == 201, ecr.text
    ecr_id = ecr.json()["id"]
    assert (
        client.post(f"{changes}/ecrs/{ecr_id}/start-impact", headers=owner_headers).status_code
        == 200
    )
    impact = client.post(
        f"{changes}/ecrs/{ecr_id}/submit-impact",
        headers=owner_headers,
        json={
            "impact_analysis": {"quality": "verified in PVT"},
            "affected_bom_ids": [str(ids["ebom"])],
        },
    )
    assert impact.status_code == 200, impact.text
    ecr_approved = client.post(
        f"{changes}/ecrs/{ecr_id}/decide",
        headers=manager_headers,
        json={"outcome": "approved", "note": "Independent approval"},
    )
    assert ecr_approved.status_code == 200, ecr_approved.text
    ecn = client.post(
        f"{changes}/ecrs/{ecr_id}/ecns",
        headers=owner_headers,
        json={
            "code": "ECN-S3-1",
            "title": "Release NPI update",
            "implementation_plan": {"lot": "next"},
        },
    )
    assert ecn.status_code == 201, ecn.text
    ecn_id = ecn.json()["id"]
    assert (
        client.post(
            f"{changes}/ecns/{ecn_id}/submit-effectivity", headers=owner_headers
        ).status_code
        == 200
    )
    effectivity = client.post(
        f"{changes}/ecns/{ecn_id}/decide-effectivity",
        headers=manager_headers,
        json={
            "outcome": "approved",
            "effectivity": {"from_lot": "PVT-101"},
            "released_bom_id": str(ids["ebom"]),
            "target_system": "sap",
        },
    )
    assert effectivity.status_code == 200, effectivity.text
    handoff_id = effectivity.json()["handoff"]["id"]
    blocked_handoff = client.post(f"{changes}/handoffs/{handoff_id}/ready", headers=manager_headers)
    assert blocked_handoff.status_code == 409
    assert blocked_handoff.json()["detail"]["code"] == "HANDOFF_PVT_GATE_REQUIRED"

    _complete_npi_phase(client, headers=owner_headers, ids=ids, phase="pvt")
    _open_sign_and_approve_gate(client, headers=owner_headers, ids=ids, phase="pvt")
    ready = client.post(f"{changes}/handoffs/{handoff_id}/ready", headers=manager_headers)
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "ready"
    _advance(client, headers=owner_headers, ids=ids, to_phase="mp")

    engine = create_engine(psycopg_database_url(isolated_sprint3_database))
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(
                    select(tables.stages.c.code)
                    .join(tables.projects, tables.projects.c.current_stage_id == tables.stages.c.id)
                    .where(tables.projects.c.id == ids["project"])
                ).scalar_one()
                == "mp"
            )
            assert tuple(
                connection.execute(
                    select(tables.gates.c.code)
                    .where(
                        tables.gates.c.project_id == ids["project"],
                        tables.gates.c.code.in_(("evt", "dvt", "pvt")),
                        tables.gates.c.status == "approved",
                    )
                    .order_by(tables.gates.c.code)
                ).scalars()
            ) == ("dvt", "evt", "pvt")
            assert (
                connection.execute(
                    select(func.count())
                    .select_from(tables.engineering_change_notices)
                    .where(tables.engineering_change_notices.c.project_id == ids["project"])
                ).scalar_one()
                == 1
            )
            assert (
                connection.execute(
                    select(tables.erp_handoffs.c.status).where(
                        tables.erp_handoffs.c.project_id == ids["project"]
                    )
                ).scalar_one()
                == "ready"
            )
            assert (
                connection.execute(
                    select(func.count())
                    .select_from(tables.events)
                    .where(
                        tables.events.c.project_id == ids["project"],
                        tables.events.c.event_type == "GATE_APPROVED",
                    )
                ).scalar_one()
                == 3
            )
    finally:
        engine.dispose()
