from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
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
def isolated_quality_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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


def seed_project_and_engineer(
    database_url: str,
    tenant_id: UUID,
    owner_id: UUID,
    *,
    suffix: str = "QA",
    engineer_username: str = "engineer",
) -> tuple[UUID, UUID]:
    workflow_id, stage_id, project_id, engineer_id = uuid4(), uuid4(), uuid4(), uuid4()
    requirement_id, case_id = uuid4(), uuid4()
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.requirements.insert(),
                {
                    "id": requirement_id,
                    "tenant_id": tenant_id,
                    "created_by_user_id": owner_id,
                    "code": f"REQ-{suffix}",
                    "title": "Quality",
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
                    "code": f"CASE-{suffix}",
                    "title": "Quality",
                    "status": "converted",
                },
            )
            connection.execute(
                tables.workflows.insert(),
                {
                    "id": workflow_id,
                    "tenant_id": tenant_id,
                    "code": f"qa-{suffix.lower()}",
                    "name": f"QA {suffix}",
                },
            )
            connection.execute(
                tables.stages.insert(),
                {
                    "id": stage_id,
                    "tenant_id": tenant_id,
                    "workflow_id": workflow_id,
                    "code": "mp",
                    "name": "MP",
                    "sequence": 1,
                },
            )
            connection.execute(
                tables.users.insert(),
                {
                    "id": engineer_id,
                    "tenant_id": tenant_id,
                    "username": engineer_username,
                    "display_name": "Quality Engineer",
                    "role": Role.ENGINEER.value,
                    "password_hash": PasswordService().hash(PASSWORD),
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
                    "code": f"PRJ-{suffix}",
                    "name": "Quality project",
                    "status": "active",
                },
            )
            connection.execute(
                tables.project_members.insert(),
                [
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "user_id": owner_id,
                        "added_by_user_id": owner_id,
                    },
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "user_id": engineer_id,
                        "added_by_user_id": owner_id,
                    },
                ],
            )
    finally:
        engine.dispose()
    return project_id, engineer_id


def seed_document(
    database_url: str,
    tenant_id: UUID,
    project_id: UUID,
    uploaded_by_user_id: UUID,
    *,
    filename: str,
) -> UUID:
    document_id = uuid4()
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.documents.insert(),
                {
                    "id": document_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "uploaded_by_user_id": uploaded_by_user_id,
                    "object_key": f"quality/{document_id}/{filename}",
                    "filename": filename,
                    "media_type": "application/pdf",
                    "classification": "internal",
                    "size_bytes": 128,
                    "sha256": "a" * 64,
                    "extraction_status": "extracted",
                    "fragment_count": 1,
                },
            )
    finally:
        engine.dispose()
    return document_id


def seed_project_user(
    database_url: str,
    tenant_id: UUID,
    project_id: UUID,
    added_by_user_id: UUID,
    *,
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
                    "role": role.value,
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
                    "added_by_user_id": added_by_user_id,
                },
            )
    finally:
        engine.dispose()
    return user_id


def create_complaint(
    client: TestClient,
    project_id: UUID,
    owner_user_id: UUID,
    *,
    username: str = "engineer",
) -> dict[str, object]:
    response = client.post(
        f"/api/projects/{project_id}/quality/complaints",
        headers=login(client, username),
        json={
            "title": "Field connector intermittent",
            "description": "Connector opens after thermal cycling.",
            "source": "field",
            "severity": "high",
            "occurred_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
            "owner_user_id": str(owner_user_id),
            "customer_reference": "FIELD-2026-08",
            "affected_scope": "Lot C4s",
        },
    )
    assert response.status_code == 201
    return response.json()


def triage_complaint(
    client: TestClient,
    project_id: UUID,
    complaint_id: object,
    owner_user_id: UUID,
) -> dict[str, object]:
    response = client.post(
        f"/api/projects/{project_id}/quality/complaints/{complaint_id}/triage",
        headers=login(client, "quality"),
        json={
            "nonconformity": "Connector contact resistance exceeds limit.",
            "requirement_reference": "SPEC-ELEC-04 section 8.2",
            "severity": "high",
            "owner_user_id": str(owner_user_id),
            "target_date": (date.today() + timedelta(days=10)).isoformat(),
            "affected_quantity": 24,
            "affected_scope": "Lot C4s",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_engineer_creates_and_lists_complaint_with_same_transaction_event_audit(
    client: TestClient,
    isolated_quality_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id, owner_id = UUID(setup["tenant"]["id"]), UUID(setup["user"]["id"])
    project_id, engineer_id = seed_project_and_engineer(
        isolated_quality_database,
        tenant_id,
        owner_id,
    )

    complaint = create_complaint(client, project_id, engineer_id)
    assert complaint["code"].startswith("CMP-")
    assert complaint["status"] == "open"
    assert complaint["reported_by_user_id"] == str(engineer_id)
    assert complaint["owner_user_id"] == str(engineer_id)

    listed = client.get(
        f"/api/projects/{project_id}/quality/complaints",
        headers=login(client, "engineer"),
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [complaint["id"]]

    engine = create_engine(psycopg_database_url(isolated_quality_database))
    try:
        with engine.connect() as connection:
            event = connection.execute(
                select(tables.events).where(
                    tables.events.c.tenant_id == tenant_id,
                    tables.events.c.entity_id == UUID(complaint["id"]),
                )
            ).mappings().one()
            audit = connection.execute(
                select(tables.audit_log).where(
                    tables.audit_log.c.tenant_id == tenant_id,
                    tables.audit_log.c.entity_id == UUID(complaint["id"]),
                )
            ).mappings().one()
    finally:
        engine.dispose()
    assert event["event_type"] == "COMPLAINT_CREATED"
    assert event["source"] == "quality_service"
    assert event["payload"] == {"complaint_id": complaint["id"], "severity": "high"}
    assert audit["event_id"] == event["event_id"]
    assert audit["action"] == "quality.complaint.create"


def test_quality_triage_atomically_creates_ncr_and_advances_complaint(
    client: TestClient,
    isolated_quality_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id, owner_id = UUID(setup["tenant"]["id"]), UUID(setup["user"]["id"])
    project_id, engineer_id = seed_project_and_engineer(
        isolated_quality_database,
        tenant_id,
        owner_id,
    )
    quality_id = seed_project_user(
        isolated_quality_database,
        tenant_id,
        project_id,
        owner_id,
        username="quality",
        role=Role.QUALITY,
    )
    complaint = create_complaint(client, project_id, engineer_id)

    triaged = client.post(
        f"/api/projects/{project_id}/quality/complaints/{complaint['id']}/triage",
        headers=login(client, "quality"),
        json={
            "nonconformity": "Connector contact resistance exceeds limit.",
            "requirement_reference": "SPEC-ELEC-04 section 8.2",
            "severity": "high",
            "owner_user_id": str(quality_id),
            "target_date": (date.today() + timedelta(days=10)).isoformat(),
            "affected_quantity": 24,
            "affected_scope": "Lot C4s",
        },
    )

    assert triaged.status_code == 201
    payload = triaged.json()
    assert payload["complaint"]["status"] == "triaged"
    assert payload["ncr"]["complaint_id"] == complaint["id"]
    assert payload["ncr"]["status"] == "open"
    assert payload["ncr"]["code"].startswith("NCR-")

    engine = create_engine(psycopg_database_url(isolated_quality_database))
    try:
        with engine.connect() as connection:
            complaint_events = connection.execute(
                select(tables.events.c.event_type).where(
                    tables.events.c.tenant_id == tenant_id,
                    tables.events.c.entity_id == UUID(str(complaint["id"])),
                )
            ).scalars().all()
            ncr_events = connection.execute(
                select(tables.events.c.event_type).where(
                    tables.events.c.tenant_id == tenant_id,
                    tables.events.c.entity_id == UUID(payload["ncr"]["id"]),
                )
            ).scalars().all()
    finally:
        engine.dispose()
    assert complaint_events == ["COMPLAINT_CREATED", "COMPLAINT_STATUS_CHANGED"]
    assert ncr_events == ["NCR_CREATED"]


def test_ncr_root_cause_four_eyes_actions_and_verification_hard_gates(
    client: TestClient,
    isolated_quality_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id, owner_id = UUID(setup["tenant"]["id"]), UUID(setup["user"]["id"])
    project_id, engineer_id = seed_project_and_engineer(
        isolated_quality_database,
        tenant_id,
        owner_id,
    )
    quality_id = seed_project_user(
        isolated_quality_database,
        tenant_id,
        project_id,
        owner_id,
        username="quality",
        role=Role.QUALITY,
    )
    seed_project_user(
        isolated_quality_database,
        tenant_id,
        project_id,
        owner_id,
        username="reviewer",
        role=Role.QUALITY,
    )
    complaint = create_complaint(client, project_id, engineer_id)
    triaged = triage_complaint(client, project_id, complaint["id"], engineer_id)
    ncr_id = triaged["ncr"]["id"]
    quality_headers, engineer_headers = login(client, "quality"), login(client, "engineer")
    reviewer_headers = login(client, "reviewer")

    containment = client.post(
        f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/transitions",
        headers=quality_headers,
        json={"to_status": "containment"},
    )
    assert containment.status_code == 200
    root_cause_stage = client.post(
        f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/transitions",
        headers=quality_headers,
        json={
            "to_status": "root_cause",
            "containment_action": "Quarantine lot C4s and inspect all 24 units.",
        },
    )
    assert root_cause_stage.status_code == 200
    assert root_cause_stage.json()["containment_completed_at"] is not None

    quality_analysis = client.post(
        f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/root-causes",
        headers=quality_headers,
        json={
            "method": "fishbone",
            "analysis": "Quality-owned exploratory analysis.",
            "root_cause": "Pending independent confirmation.",
            "evidence_refs": [],
        },
    )
    assert quality_analysis.status_code == 201
    quality_self_approval = client.post(
        f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/root-causes/"
        f"{quality_analysis.json()['id']}/approve",
        headers=quality_headers,
    )
    assert quality_self_approval.status_code == 409
    assert quality_self_approval.json()["detail"]["code"] == "ROOT_CAUSE_FOUR_EYES_REQUIRED"

    analysis = client.post(
        f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/root-causes",
        headers=engineer_headers,
        json={
            "method": "5why",
            "analysis": "Contact force declined after five thermal cycles.",
            "root_cause": "Terminal crimp height tolerance was too wide.",
            "evidence_refs": [
                {"kind": "event", "reference": f"complaint:{complaint['id']}:created"}
            ],
        },
    )
    assert analysis.status_code == 201
    analysis_id = analysis.json()["id"]
    self_approval = client.post(
        f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/root-causes/{analysis_id}/approve",
        headers=engineer_headers,
    )
    assert self_approval.status_code == 403
    approved = client.post(
        f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/root-causes/{analysis_id}/approve",
        headers=quality_headers,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    action_stage = client.post(
        f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/transitions",
        headers=quality_headers,
        json={"to_status": "action"},
    )
    assert action_stage.status_code == 200

    action_ids: dict[str, str] = {}
    action_headers: dict[str, dict[str, str]] = {}
    for action_type in ("corrective", "preventive"):
        assigned_user_id = quality_id if action_type == "preventive" else engineer_id
        assigned_headers = quality_headers if action_type == "preventive" else engineer_headers
        action = client.post(
            f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/actions",
            headers=assigned_headers,
            json={
                "action_type": action_type,
                "description": f"{action_type.title()} crimp control action",
                "owner_user_id": str(assigned_user_id),
                "due_date": (date.today() + timedelta(days=7)).isoformat(),
            },
        )
        assert action.status_code == 201
        action_ids[action_type] = action.json()["id"]
        action_headers[action_type] = assigned_headers
        started = client.post(
            f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/actions/{action.json()['id']}/transitions",
            headers=assigned_headers,
            json={"to_status": "in_progress"},
        )
        assert started.status_code == 200

    evidence = [{"kind": "event", "reference": f"complaint:{complaint['id']}:created"}]
    corrective = client.post(
        f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/actions/{action_ids['corrective']}/transitions",
        headers=engineer_headers,
        json={
            "to_status": "completed",
            "completion_summary": "Crimp specification and inspection fixture updated.",
            "evidence_refs": evidence,
        },
    )
    assert corrective.status_code == 200
    blocked = client.post(
        f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/transitions",
        headers=quality_headers,
        json={
            "to_status": "verification",
            "effectiveness_criteria": "Zero opens across 24 thermal-cycle samples.",
            "observation_due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "CAPA_ACTION_GATE_NOT_READY"

    preventive = client.post(
        f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/actions/{action_ids['preventive']}/transitions",
        headers=action_headers["preventive"],
        json={
            "to_status": "completed",
            "completion_summary": "Supplier control plan now monitors crimp capability.",
            "evidence_refs": evidence,
        },
    )
    assert preventive.status_code == 200
    due_at = datetime.fromisoformat(preventive.json()["completed_at"]) + timedelta(microseconds=1)
    verification = client.post(
        f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/transitions",
        headers=quality_headers,
        json={
            "to_status": "verification",
            "effectiveness_criteria": "Zero opens across 24 thermal-cycle samples.",
            "observation_due_at": due_at.isoformat(),
        },
    )
    assert verification.status_code == 200
    assert verification.json()["status"] == "verification"
    assert verification.json()["effectiveness_criteria"].startswith("Zero opens")

    reviewer_conflict = client.post(
        f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/effectiveness-reviews",
        headers=quality_headers,
        json={
            "actual_result": "One intermittent open remained after observation.",
            "result": "ineffective",
            "evidence_refs": evidence,
        },
    )
    assert reviewer_conflict.status_code == 409
    assert reviewer_conflict.json()["detail"]["code"] == "EFFECTIVENESS_FOUR_EYES_REQUIRED"
    ineffective = client.post(
        f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/effectiveness-reviews",
        headers=reviewer_headers,
        json={
            "actual_result": "One intermittent open remained after observation.",
            "result": "ineffective",
            "evidence_refs": evidence,
        },
    )
    assert ineffective.status_code == 201
    assert ineffective.json()["review"]["review_number"] == 1
    assert ineffective.json()["ncr"]["status"] == "action"

    repeat_without_new_action = client.post(
        f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/transitions",
        headers=reviewer_headers,
        json={
            "to_status": "verification",
            "effectiveness_criteria": "Zero opens across 48 thermal-cycle samples.",
            "observation_due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert repeat_without_new_action.status_code == 409
    assert repeat_without_new_action.json()["detail"]["code"] == "CAPA_NEW_ACTION_REQUIRED"

    follow_up = client.post(
        f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/actions",
        headers=engineer_headers,
        json={
            "action_type": "corrective",
            "description": "Tighten crimp tolerance and add force traceability.",
            "owner_user_id": str(engineer_id),
            "due_date": (date.today() + timedelta(days=7)).isoformat(),
        },
    )
    assert follow_up.status_code == 201
    follow_up_id = follow_up.json()["id"]
    assert client.post(
        f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/actions/{follow_up_id}/transitions",
        headers=engineer_headers,
        json={"to_status": "in_progress"},
    ).status_code == 200
    follow_up_done = client.post(
        f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/actions/{follow_up_id}/transitions",
        headers=engineer_headers,
        json={
            "to_status": "completed",
            "completion_summary": "Tolerance tightened and force traces retained.",
            "evidence_refs": evidence,
        },
    )
    assert follow_up_done.status_code == 200
    second_due = datetime.fromisoformat(follow_up_done.json()["completed_at"]) + timedelta(
        microseconds=1
    )
    assert client.post(
        f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/transitions",
        headers=reviewer_headers,
        json={
            "to_status": "verification",
            "effectiveness_criteria": "Zero opens across 48 thermal-cycle samples.",
            "observation_due_at": second_due.isoformat(),
        },
    ).status_code == 200
    effective = client.post(
        f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/effectiveness-reviews",
        headers=reviewer_headers,
        json={
            "actual_result": "All 48 samples passed thermal cycling.",
            "result": "effective",
            "evidence_refs": evidence,
        },
    )
    assert effective.status_code == 201
    assert effective.json()["review"]["review_number"] == 2
    assert effective.json()["ncr"]["status"] == "verification"

    closed_ncr = client.post(
        f"/api/projects/{project_id}/quality/ncrs/{ncr_id}/transitions",
        headers=reviewer_headers,
        json={"to_status": "closed"},
    )
    assert closed_ncr.status_code == 200
    assert closed_ncr.json()["closed_by_user_id"] is not None

    for next_status, summary in (
        ("investigating", None),
        ("resolved", "CAPA verified; customer lot disposition completed."),
    ):
        response = client.post(
            f"/api/projects/{project_id}/quality/complaints/{complaint['id']}/transitions",
            headers=reviewer_headers,
            json={"to_status": next_status, "resolution_summary": summary},
        )
        assert response.status_code == 200
    owner_cannot_close = client.post(
        f"/api/projects/{project_id}/quality/complaints/{complaint['id']}/transitions",
        headers=login(client, "owner"),
        json={"to_status": "closed"},
    )
    assert owner_cannot_close.status_code == 403
    closed_complaint = client.post(
        f"/api/projects/{project_id}/quality/complaints/{complaint['id']}/transitions",
        headers=reviewer_headers,
        json={"to_status": "closed"},
    )
    assert closed_complaint.status_code == 200
    assert closed_complaint.json()["status"] == "closed"
    assert closed_complaint.json()["closed_by_user_id"] is not None

    engine = create_engine(psycopg_database_url(isolated_quality_database))
    try:
        with engine.connect() as connection:
            event_ids = set(
                connection.execute(
                    select(tables.events.c.event_id).where(
                        tables.events.c.tenant_id == tenant_id,
                        tables.events.c.project_id == project_id,
                        tables.events.c.source == "quality_service",
                    )
                ).scalars()
            )
            audit_ids = set(
                connection.execute(
                    select(tables.audit_log.c.event_id).where(
                        tables.audit_log.c.tenant_id == tenant_id,
                        tables.audit_log.c.project_id == project_id,
                        tables.audit_log.c.action.startswith("quality."),
                    )
                ).scalars()
            )
    finally:
        engine.dispose()
    assert len(event_ids) >= 20
    assert audit_ids == event_ids


def test_quality_surface_denies_external_roles_and_pm_cannot_triage(
    client: TestClient,
    isolated_quality_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id, owner_id = UUID(setup["tenant"]["id"]), UUID(setup["user"]["id"])
    project_id, engineer_id = seed_project_and_engineer(
        isolated_quality_database,
        tenant_id,
        owner_id,
    )
    seed_project_user(
        isolated_quality_database,
        tenant_id,
        project_id,
        owner_id,
        username="project-manager",
        role=Role.PROJECT_MANAGER,
    )
    for username, role in (("supplier", Role.SUPPLIER), ("customer", Role.CUSTOMER)):
        seed_project_user(
            isolated_quality_database,
            tenant_id,
            project_id,
            owner_id,
            username=username,
            role=role,
        )

    complaint = create_complaint(client, project_id, engineer_id, username="project-manager")
    assert client.get(
        f"/api/projects/{project_id}/quality/complaints",
        headers=login(client, "project-manager"),
    ).status_code == 200
    triage_payload = {
        "nonconformity": "Out of specification",
        "requirement_reference": "SPEC-01",
        "severity": "medium",
        "owner_user_id": str(engineer_id),
        "target_date": (date.today() + timedelta(days=5)).isoformat(),
    }
    assert client.post(
        f"/api/projects/{project_id}/quality/complaints/{complaint['id']}/triage",
        headers=login(client, "project-manager"),
        json=triage_payload,
    ).status_code == 403
    for username in ("supplier", "customer"):
        headers = login(client, username)
        assert client.get(
            f"/api/projects/{project_id}/quality/complaints", headers=headers
        ).status_code == 403
        assert client.post(
            f"/api/projects/{project_id}/quality/complaints",
            headers=headers,
            json={
                "title": "External injection",
                "description": "Must be denied",
                "source": "customer",
                "severity": "low",
                "occurred_at": datetime.now(UTC).isoformat(),
                "owner_user_id": str(engineer_id),
            },
        ).status_code == 403


def test_complaint_document_references_are_project_bound(
    client: TestClient,
    isolated_quality_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id, owner_id = UUID(setup["tenant"]["id"]), UUID(setup["user"]["id"])
    project_id, engineer_id = seed_project_and_engineer(
        isolated_quality_database,
        tenant_id,
        owner_id,
    )
    other_project_id, _ = seed_project_and_engineer(
        isolated_quality_database,
        tenant_id,
        owner_id,
        suffix="OTHER",
        engineer_username="engineer-other",
    )
    local_document_id = seed_document(
        isolated_quality_database,
        tenant_id,
        project_id,
        owner_id,
        filename="local.pdf",
    )
    foreign_document_id = seed_document(
        isolated_quality_database,
        tenant_id,
        other_project_id,
        owner_id,
        filename="foreign.pdf",
    )
    body = {
        "title": "Document scoped complaint",
        "description": "Evidence scope must fail closed.",
        "source": "internal",
        "severity": "medium",
        "occurred_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        "owner_user_id": str(engineer_id),
    }
    rejected = client.post(
        f"/api/projects/{project_id}/quality/complaints",
        headers=login(client, "engineer"),
        json={**body, "document_refs": [str(foreign_document_id)]},
    )
    assert rejected.status_code == 404
    assert rejected.json()["detail"]["code"] == "QUALITY_RELATED_OBJECT_NOT_FOUND"
    accepted = client.post(
        f"/api/projects/{project_id}/quality/complaints",
        headers=login(client, "engineer"),
        json={**body, "document_refs": [str(local_document_id)]},
    )
    assert accepted.status_code == 201
    assert accepted.json()["document_refs"] == [str(local_document_id)]
