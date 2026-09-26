from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Barrier, Event
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError

from app.auth.passwords import PasswordService
from app.auth.roles import Role
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.domain.gates import (
    GateCondition,
    GateConditionsRequiredError,
    GateInvalidStateError,
    GateReadinessRecord,
    GateRoundNotOpenError,
    GateService,
    GateSignoffStatus,
    GateSlot,
)
from app.domain.issues import IssueService, IssueUpdate
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
def isolated_gate_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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
                    "added_by_user_id": owner_id,
                },
            )
    finally:
        engine.dispose()
    return user_id


def seed_project(
    database_url: str,
    *,
    tenant_id: UUID,
    owner_id: UUID,
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    workflow_id = uuid4()
    project_id = uuid4()
    concept_stage_id = uuid4()
    evt_stage_id = uuid4()
    concept_gate_id = uuid4()
    evt_gate_id = uuid4()
    requirement_id = uuid4()
    case_id = uuid4()
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.requirements.insert(),
                {
                    "id": requirement_id,
                    "tenant_id": tenant_id,
                    "created_by_user_id": owner_id,
                    "code": "REQ-GATE",
                    "title": "Gate test requirement",
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
                    "code": "CASE-GATE",
                    "title": "Gate test case",
                    "status": "converted",
                },
            )
            connection.execute(
                tables.workflows.insert(),
                {
                    "id": workflow_id,
                    "tenant_id": tenant_id,
                    "code": "npd-gate-test",
                    "name": "NPD Gate Test",
                },
            )
            connection.execute(
                tables.stages.insert(),
                [
                    {
                        "id": concept_stage_id,
                        "tenant_id": tenant_id,
                        "workflow_id": workflow_id,
                        "code": "concept",
                        "name": "Concept",
                        "sequence": 1,
                    },
                    {
                        "id": evt_stage_id,
                        "tenant_id": tenant_id,
                        "workflow_id": workflow_id,
                        "code": "evt",
                        "name": "EVT",
                        "sequence": 2,
                    },
                ],
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": project_id,
                    "tenant_id": tenant_id,
                    "development_case_id": case_id,
                    "workflow_id": workflow_id,
                    "current_stage_id": concept_stage_id,
                    "owner_user_id": owner_id,
                    "code": "PRJ-GATE",
                    "name": "Gate test project",
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
                [
                    {
                        "id": concept_gate_id,
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "stage_id": concept_stage_id,
                        "code": "concept",
                        "name": "Concept Gate",
                    },
                    {
                        "id": evt_gate_id,
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "stage_id": evt_stage_id,
                        "code": "evt",
                        "name": "EVT Gate",
                    },
                ],
            )
    finally:
        engine.dispose()
    return project_id, concept_stage_id, evt_stage_id, concept_gate_id, evt_gate_id


def test_gate_round_hard_stop_signoffs_and_grandfather_are_end_to_end(
    client: TestClient,
    isolated_gate_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    owner_id = UUID(setup["user"]["id"])
    project_id, _, evt_stage_id, concept_gate_id, evt_gate_id = seed_project(
        isolated_gate_database,
        tenant_id=tenant_id,
        owner_id=owner_id,
    )
    for username, role in (
        ("manager", Role.PROJECT_MANAGER),
        ("engineer", Role.ENGINEER),
        ("quality", Role.QUALITY),
        ("supplier", Role.SUPPLIER),
    ):
        seed_user(
            isolated_gate_database,
            tenant_id=tenant_id,
            project_id=project_id,
            owner_id=owner_id,
            username=username,
            role=role,
        )

    owner = login(client, "owner")
    pm = login(client, "manager")
    engineer = login(client, "engineer")
    quality = login(client, "quality")
    supplier = login(client, "supplier")
    base = f"/api/projects/{project_id}/gates"

    listed = client.get(base, headers=pm)
    assert listed.status_code == 200
    assert [gate["stage"]["code"] for gate in listed.json()["items"]] == ["concept", "evt"]
    assert client.get(base, headers=supplier).status_code == 403

    opened = client.post(f"{base}/{concept_gate_id}/rounds", headers=pm)
    assert opened.status_code == 201
    gate = opened.json()
    assert gate["status"] == "reviewing"
    assert gate["round"]["round_number"] == 1
    assert gate["round"]["policy_version"] == "npd-gate-v1"
    assert gate["readiness"]["blocker_keys"] == [
        "signoff:product",
        "signoff:engineering",
        "signoff:quality",
    ]

    denied = client.put(
        f"{base}/{concept_gate_id}/rounds/{gate['round']['id']}/signoffs/engineering",
        headers=pm,
        json={"status": "approved", "note": "PM cannot sign engineering"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "GATE_SIGNING_DENIED"

    for headers, slot, status_value in (
        (pm, "product", "approved"),
        (engineer, "engineering", "approved"),
        (quality, "quality", "conditional"),
    ):
        signed = client.put(
            f"{base}/{concept_gate_id}/rounds/{gate['round']['id']}/signoffs/{slot}",
            headers=headers,
            json={"status": status_value, "note": f"{slot} evidence reviewed"},
        )
        assert signed.status_code == 200

    stage_blocked = client.post(
        f"/api/projects/{project_id}/stage-transitions",
        headers=pm,
        json={"to_stage_id": str(evt_stage_id)},
    )
    assert stage_blocked.status_code == 409
    assert stage_blocked.json()["detail"]["code"] == "PROJECT_GATE_NOT_APPROVED"

    engine = create_engine(psycopg_database_url(isolated_gate_database))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.issues.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "reported_by_user_id": owner_id,
                    "title": "Safety escape path unresolved",
                    "severity": "critical",
                    "status": "open",
                },
            )
        blocked = client.post(
            f"{base}/{concept_gate_id}/decisions",
            headers=pm,
            json={"status": "approved", "rationale": "Ready for EVT"},
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "GATE_NOT_READY"
        assert any(key.startswith("issue:") for key in blocked.json()["detail"]["blocker_keys"])
        with engine.begin() as connection:
            connection.execute(
                tables.issues.delete().where(tables.issues.c.project_id == project_id)
            )
    finally:
        engine.dispose()

    approved = client.post(
        f"{base}/{concept_gate_id}/decisions",
        headers=pm,
        json={"status": "approved", "rationale": "Evidence and risks reviewed"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["readiness"]["ready"]
    assert approved.json()["round"]["status"] == "completed"

    current_exemption = client.post(
        f"{base}/{concept_gate_id}/grandfather-exemptions",
        headers=owner,
        json={
            "requirement_key": "document:new-template-v2",
            "policy_version": "npd-gate-v2",
            "reason": "Policy became effective after the decision",
        },
    )
    assert current_exemption.status_code == 409

    advanced = client.post(
        f"/api/projects/{project_id}/stage-transitions",
        headers=pm,
        json={"to_stage_id": str(evt_stage_id)},
    )
    assert advanced.status_code == 200
    assert advanced.json()["current_stage"]["id"] == str(evt_stage_id)

    exemption = client.post(
        f"{base}/{concept_gate_id}/grandfather-exemptions",
        headers=owner,
        json={
            "requirement_key": "document:new-template-v2",
            "policy_version": "npd-gate-v2",
            "reason": "Policy became effective after the decision",
        },
    )
    assert exemption.status_code == 201, exemption.text
    assert exemption.json()["requirement_key"] == "document:new-template-v2"
    assert (
        client.post(
            f"{base}/{evt_gate_id}/grandfather-exemptions",
            headers=owner,
            json={
                "requirement_key": "document:new-template-v2",
                "policy_version": "npd-gate-v2",
                "reason": "Future Gate cannot be exempted",
            },
        ).status_code
        == 409
    )

    evt_round = client.post(f"{base}/{evt_gate_id}/rounds", headers=pm).json()["round"]
    promoted = client.post(
        f"{base}/{evt_gate_id}/requirements",
        headers=pm,
        json={
            "slot": "product",
            "requirement": "required",
            "reason": "Customer-facing EVT review requires product approval",
        },
    )
    assert promoted.status_code == 201
    assert promoted.json()["requirement"] == "required"
    reopened = client.post(f"{base}/{evt_gate_id}/rounds", headers=pm)
    assert reopened.status_code == 201
    assert reopened.json()["round"]["round_number"] == 2
    assert reopened.json()["round"]["id"] != evt_round["id"]

    engine = create_engine(psycopg_database_url(isolated_gate_database))
    try:
        with engine.connect() as connection:
            assert connection.execute(
                select(tables.decisions.c.id).where(tables.decisions.c.gate_id == concept_gate_id)
            ).scalar_one()
            assert (
                connection.execute(
                    select(tables.events.c.event_type).where(
                        tables.events.c.entity_id == concept_gate_id,
                        tables.events.c.event_type == "GATE_APPROVED",
                    )
                ).scalar_one()
                == "GATE_APPROVED"
            )
            assert (
                connection.execute(
                    select(tables.audit_log.c.action).where(
                        tables.audit_log.c.entity_id == concept_gate_id,
                        tables.audit_log.c.action == "gate.approve",
                    )
                ).scalar_one()
                == "gate.approve"
            )
            completed_snapshot = connection.execute(
                select(tables.gate_signoff_rounds.c.readiness_snapshot).where(
                    tables.gate_signoff_rounds.c.gate_id == concept_gate_id
                )
            ).scalar_one()
            assert completed_snapshot["ready"] is True
            assert completed_snapshot["evaluated_at"] <= datetime.now(UTC).isoformat()
    finally:
        engine.dispose()


def prepare_ready_gate(
    client: TestClient,
    database_url: str,
) -> tuple[UUID, UUID, UUID, UUID]:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    owner_id = UUID(setup["user"]["id"])
    project_id, _, _, gate_id, _ = seed_project(
        database_url,
        tenant_id=tenant_id,
        owner_id=owner_id,
    )
    engine = create_engine(psycopg_database_url(database_url))
    try:
        service = GateService(engine)
        opened = service.open_round(
            tenant_id=tenant_id,
            project_id=project_id,
            gate_id=gate_id,
            actor_user_id=owner_id,
        )
        assert opened.round is not None
        signoffs: tuple[tuple[GateSlot, GateSignoffStatus], ...] = (
            ("product", "approved"),
            ("engineering", "approved"),
            ("quality", "conditional"),
        )
        for slot, status_value in signoffs:
            service.sign(
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
                round_id=opened.round.id,
                actor_user_id=owner_id,
                actor_role=Role.OWNER,
                slot=slot,
                status=status_value,
                note="Concurrency fixture",
            )
    finally:
        engine.dispose()
    return tenant_id, owner_id, project_id, gate_id


def test_rejected_gate_completes_the_round_and_reopens_as_a_new_review(
    client: TestClient,
    isolated_gate_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    owner_id = UUID(setup["user"]["id"])
    project_id, _, _, gate_id, _ = seed_project(
        isolated_gate_database,
        tenant_id=tenant_id,
        owner_id=owner_id,
    )
    engine = create_engine(psycopg_database_url(isolated_gate_database))
    try:
        service = GateService(engine)
        first = service.open_round(
            tenant_id=tenant_id,
            project_id=project_id,
            gate_id=gate_id,
            actor_user_id=owner_id,
        )
        assert first.round is not None
        rejected = service.decide(
            tenant_id=tenant_id,
            project_id=project_id,
            gate_id=gate_id,
            actor_user_id=owner_id,
            status="rejected",
            rationale="Evidence is incomplete",
        )
        assert rejected.status == "rejected"
        assert rejected.round is not None
        assert rejected.round.status == "completed"
        assert not rejected.readiness.ready

        reopened = service.open_round(
            tenant_id=tenant_id,
            project_id=project_id,
            gate_id=gate_id,
            actor_user_id=owner_id,
        )
        assert reopened.status == "reviewing"
        assert reopened.round is not None
        assert reopened.round.round_number == 2
        with pytest.raises(GateRoundNotOpenError):
            service.sign(
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
                round_id=first.round.id,
                actor_user_id=owner_id,
                actor_role=Role.OWNER,
                slot="product",
                status="approved",
                note="Stale browser write",
            )
    finally:
        engine.dispose()


def test_concurrent_approval_commits_exactly_one_decision(
    client: TestClient,
    isolated_gate_database: str,
) -> None:
    tenant_id, owner_id, project_id, gate_id = prepare_ready_gate(client, isolated_gate_database)
    barrier = Barrier(2)

    def approve() -> str:
        engine = create_engine(psycopg_database_url(isolated_gate_database))
        try:
            barrier.wait(timeout=5)
            GateService(engine).decide(
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
                actor_user_id=owner_id,
                status="approved",
                rationale="Concurrent decision",
            )
            return "approved"
        except GateInvalidStateError:
            return "conflict"
        finally:
            engine.dispose()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(approve) for _ in range(2)]
        results = sorted(future.result(timeout=5) for future in futures)
    assert results == ["approved", "conflict"]

    engine = create_engine(psycopg_database_url(isolated_gate_database))
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(
                    select(func.count())
                    .select_from(tables.decisions)
                    .where(tables.decisions.c.gate_id == gate_id)
                ).scalar_one()
                == 1
            )
            assert (
                connection.execute(
                    select(func.count())
                    .select_from(tables.events)
                    .where(
                        tables.events.c.entity_id == gate_id,
                        tables.events.c.event_type == "GATE_APPROVED",
                    )
                ).scalar_one()
                == 1
            )
    finally:
        engine.dispose()


def test_gate_approval_serializes_with_new_readiness_blockers(
    client: TestClient,
    isolated_gate_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, owner_id, project_id, gate_id = prepare_ready_gate(client, isolated_gate_database)
    readiness_computed = Event()
    release_approval = Event()
    original = GateService._readiness
    issue_id = uuid4()
    engine = create_engine(psycopg_database_url(isolated_gate_database))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.issues.insert(),
                {
                    "id": issue_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "reported_by_user_id": owner_id,
                    "title": "Concurrent severity promotion",
                    "severity": "medium",
                    "status": "open",
                },
            )
    finally:
        engine.dispose()

    def held_readiness(cls: type[GateService], *args: Any, **kwargs: Any) -> GateReadinessRecord:
        del cls
        result = original(*args, **kwargs)
        readiness_computed.set()
        assert release_approval.wait(timeout=5)
        return result

    monkeypatch.setattr(GateService, "_readiness", classmethod(held_readiness))

    def approve() -> None:
        engine = create_engine(psycopg_database_url(isolated_gate_database))
        try:
            GateService(engine).decide(
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
                actor_user_id=owner_id,
                status="approved",
                rationale="Lock project readiness scope",
            )
        finally:
            engine.dispose()

    def promote_blocker() -> None:
        engine = create_engine(psycopg_database_url(isolated_gate_database))
        try:
            IssueService(engine).update(
                tenant_id=tenant_id,
                actor_user_id=owner_id,
                project_id=project_id,
                issue_id=issue_id,
                patch=IssueUpdate(changes={"severity": "critical"}),
            )
        finally:
            engine.dispose()

    with ThreadPoolExecutor(max_workers=2) as pool:
        approval_future = pool.submit(approve)
        assert readiness_computed.wait(timeout=5)
        blocker_future = pool.submit(promote_blocker)
        completed, _ = wait([blocker_future], timeout=0.2)
        was_serialized = blocker_future not in completed
        release_approval.set()
        approval_future.result(timeout=5)
        blocker_future.result(timeout=5)

    assert was_serialized


def _sign_all(
    service: GateService,
    *,
    tenant_id: UUID,
    project_id: UUID,
    gate_id: UUID,
    round_id: UUID,
    owner_id: UUID,
) -> None:
    for slot in ("product", "engineering", "quality"):
        service.sign(
            tenant_id=tenant_id,
            project_id=project_id,
            gate_id=gate_id,
            round_id=round_id,
            actor_user_id=owner_id,
            actor_role=Role.OWNER,
            slot=slot,
            status="approved",
            note=f"{slot} evidence reviewed",
        )


def test_conditional_pass_records_its_strings_as_tracked_gate_actions(
    client: TestClient,
    isolated_gate_database: str,
) -> None:
    """V1-B6: "approved with conditions" must not lose the conditions."""
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    owner_id = UUID(setup["user"]["id"])
    project_id, _, _, gate_id, _ = seed_project(
        isolated_gate_database, tenant_id=tenant_id, owner_id=owner_id
    )
    engine = create_engine(psycopg_database_url(isolated_gate_database))
    try:
        service = GateService(engine)
        opened = service.open_round(
            tenant_id=tenant_id, project_id=project_id, gate_id=gate_id, actor_user_id=owner_id
        )
        assert opened.round is not None
        _sign_all(
            service,
            tenant_id=tenant_id,
            project_id=project_id,
            gate_id=gate_id,
            round_id=opened.round.id,
            owner_id=owner_id,
        )

        decided = service.decide(
            tenant_id=tenant_id,
            project_id=project_id,
            gate_id=gate_id,
            actor_user_id=owner_id,
            status="conditional",
            rationale="Pass with two open items",
            conditions=(
                GateCondition(
                    title="补齐 EMC 预测试报告",
                    owner_user_id=owner_id,
                    due_date=date(2026, 9, 15),
                    closure_evidence="doc://emc-pretest",
                ),
                GateCondition(
                    title="关闭轴承供应商偏差单",
                    owner_user_id=owner_id,
                    due_date=date(2026, 9, 30),
                    closure_evidence="doc://supplier-deviation",
                ),
            ),
        )
        assert decided.status == "conditional"

        with engine.connect() as connection:
            rows = (
                connection.execute(
                    select(tables.tasks).where(
                        tables.tasks.c.tenant_id == tenant_id,
                        tables.tasks.c.kind == "gate_action",
                    )
                )
                .mappings()
                .all()
            )
        assert len(rows) == 2
        # Each condition is a tracked action with an owner, a date, and the
        # evidence that will close it — not a sentence in a rationale.
        assert {row["title"] for row in rows} == {
            "补齐 EMC 预测试报告",
            "关闭轴承供应商偏差单",
        }
        for row in rows:
            assert row["source_entity"] == "gate"
            assert row["source_entity_id"] == gate_id
            assert row["assignee_user_id"] == owner_id
            assert row["due_date"] is not None
            assert row["expected_output"].startswith("doc://")
    finally:
        engine.dispose()


def test_conditions_belong_only_to_a_conditional_pass(
    client: TestClient,
    isolated_gate_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    owner_id = UUID(setup["user"]["id"])
    project_id, _, _, gate_id, _ = seed_project(
        isolated_gate_database, tenant_id=tenant_id, owner_id=owner_id
    )
    engine = create_engine(psycopg_database_url(isolated_gate_database))
    try:
        service = GateService(engine)
        opened = service.open_round(
            tenant_id=tenant_id, project_id=project_id, gate_id=gate_id, actor_user_id=owner_id
        )
        assert opened.round is not None
        _sign_all(
            service,
            tenant_id=tenant_id,
            project_id=project_id,
            gate_id=gate_id,
            round_id=opened.round.id,
            owner_id=owner_id,
        )

        # A conditional pass with no conditions is just an approval in disguise.
        with pytest.raises(GateConditionsRequiredError):
            service.decide(
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
                actor_user_id=owner_id,
                status="conditional",
                rationale="No strings named",
            )
        # A clean pass carrying conditions is equally incoherent.
        with pytest.raises(GateConditionsRequiredError):
            service.decide(
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
                actor_user_id=owner_id,
                status="approved",
                rationale="Clean pass",
                conditions=(
                    GateCondition(
                        title="不该存在的条件",
                        owner_user_id=owner_id,
                        due_date=date(2026, 9, 15),
                        closure_evidence="doc://x",
                    ),
                ),
            )
    finally:
        engine.dispose()


def test_hold_is_a_distinct_outcome_that_reopens(
    client: TestClient,
    isolated_gate_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    owner_id = UUID(setup["user"]["id"])
    project_id, _, _, gate_id, _ = seed_project(
        isolated_gate_database, tenant_id=tenant_id, owner_id=owner_id
    )
    engine = create_engine(psycopg_database_url(isolated_gate_database))
    try:
        service = GateService(engine)
        service.open_round(
            tenant_id=tenant_id, project_id=project_id, gate_id=gate_id, actor_user_id=owner_id
        )
        held = service.decide(
            tenant_id=tenant_id,
            project_id=project_id,
            gate_id=gate_id,
            actor_user_id=owner_id,
            status="hold",
            rationale="Waiting on the customer's spec answer",
        )
        # Hold is not rejection: the work is not wrong, it is waiting.
        assert held.status == "hold"
        assert held.round is not None
        assert held.round.status == "completed"

        reopened = service.open_round(
            tenant_id=tenant_id, project_id=project_id, gate_id=gate_id, actor_user_id=owner_id
        )
        assert reopened.status == "reviewing"
        assert reopened.round is not None
        assert reopened.round.round_number == 2
    finally:
        engine.dispose()


def test_a_gate_deliverable_cannot_be_closed_without_evidence(
    client: TestClient,
    isolated_gate_database: str,
) -> None:
    """The service refuses it; this proves the database does too."""
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    owner_id = UUID(setup["user"]["id"])
    project_id, _, evt_stage_id, _, _ = seed_project(
        isolated_gate_database, tenant_id=tenant_id, owner_id=owner_id
    )
    engine = create_engine(psycopg_database_url(isolated_gate_database))
    try:
        with engine.begin() as connection:
            workflow_id = connection.execute(
                select(tables.projects.c.workflow_id).where(tables.projects.c.id == project_id)
            ).scalar_one()
        template_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                tables.deliverable_check_templates.insert(),
                {
                    "id": template_id,
                    "tenant_id": tenant_id,
                    "asset_schema_version": "1",
                    "template_versions": ["v1"],
                    "check_item_key": "evt/gate-doc",
                    "deliverable_name": "EMC 报告",
                    "requirement": "必须附报告",
                    "source": "seed",
                    "bindings": [],
                    "content_hash": "a" * 64,
                    "imported_at": datetime.now(UTC),
                },
            )
        base_item = {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "workflow_id": workflow_id,
            "stage_id": evt_stage_id,
            "template_id": template_id,
            "created_by_user_id": owner_id,
            "binding_key": "evt/gate-doc",
            "phase_id": "p1",
            "phase_code": "evt",
            "phase_name": "EVT",
            "task_id": "t1",
            "task_name": "Gate deliverable",
            "deliverable_name": "EMC 报告",
            "requirement": "必须附报告",
            "is_gate": True,
            "status": "completed",
            "completed_by_user_id": owner_id,
            "completed_at": datetime.now(UTC),
        }
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(tables.project_check_items.insert(), {"id": uuid4(), **base_item})
        with engine.begin() as connection:
            connection.execute(
                tables.project_check_items.insert(),
                {"id": uuid4(), **base_item, "evidence_reference": "doc://emc-report"},
            )
    finally:
        engine.dispose()


def test_build_purpose_enumerates_certification_sampling(
    client: TestClient,
    isolated_gate_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    owner_id = UUID(setup["user"]["id"])
    project_id, _, evt_stage_id, _, _ = seed_project(
        isolated_gate_database, tenant_id=tenant_id, owner_id=owner_id
    )
    engine = create_engine(psycopg_database_url(isolated_gate_database))
    try:
        with engine.begin() as connection:
            workflow_id = connection.execute(
                select(tables.projects.c.workflow_id).where(tables.projects.c.id == project_id)
            ).scalar_one()
        batch = {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "workflow_id": workflow_id,
            "stage_id": evt_stage_id,
            "created_by_user_id": owner_id,
            "phase": "evt",
            "planned_quantity": 3,
            "status": "planned",
        }
        with engine.begin() as connection:
            connection.execute(
                tables.build_batches.insert(),
                {
                    "id": uuid4(),
                    **batch,
                    "code": "BATCH-CERT",
                    "purpose": "certification_sample",
                },
            )
            default_id = uuid4()
            connection.execute(
                tables.build_batches.insert(),
                {"id": default_id, **batch, "code": "BATCH-DEFAULT"},
            )
            assert (
                connection.execute(
                    select(tables.build_batches.c.purpose).where(
                        tables.build_batches.c.id == default_id
                    )
                ).scalar_one()
                == "engineering_build"
            )
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                tables.build_batches.insert(),
                {"id": uuid4(), **batch, "code": "BATCH-BAD", "purpose": "whatever"},
            )
    finally:
        engine.dispose()
