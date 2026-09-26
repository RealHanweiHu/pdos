"""Issue accountability contract tests (vNext V1-A4)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Table, create_engine, text
from sqlalchemy.exc import IntegrityError

from app.auth.passwords import PasswordService
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
NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolated_issue_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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


def bearer_headers(client: TestClient, *, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class Scope:
    def __init__(self, client: TestClient, database_url: str) -> None:
        setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
        self.tenant_id = UUID(setup["tenant"]["id"])
        self.owner_id = UUID(setup["user"]["id"])
        self.engine = create_engine(psycopg_database_url(database_url))

    def dispose(self) -> None:
        self.engine.dispose()

    def _insert(self, table: Table, values: dict[str, Any]) -> UUID:
        row_id: UUID = values.setdefault("id", uuid4())
        values.setdefault("tenant_id", self.tenant_id)
        with self.engine.begin() as connection:
            connection.execute(table.insert(), values)
        return row_id

    def user(self, username: str, role: str) -> UUID:
        return self._insert(
            tables.users,
            {
                "username": username,
                "display_name": username.title(),
                "role": role,
                "password_hash": PasswordService().hash(PASSWORD),
                "is_active": True,
            },
        )

    def project(self, *, member_ids: tuple[UUID, ...]) -> UUID:
        workflow_id = self._insert(tables.workflows, {"code": "WF-ISSUE", "name": "Workflow"})
        self._insert(
            tables.stages,
            {"workflow_id": workflow_id, "code": "concept", "name": "Concept", "sequence": 1},
        )
        project_id = self._insert(
            tables.projects,
            {
                "workflow_id": workflow_id,
                "owner_user_id": self.owner_id,
                "code": "PRJ-ISSUE",
                "name": "Issue project",
                "status": "active",
            },
        )
        for member_id in member_ids:
            self._insert(
                tables.project_members,
                {
                    "project_id": project_id,
                    "user_id": member_id,
                    "added_by_user_id": self.owner_id,
                },
            )
        return project_id

    def legacy_issue(self, project_id: UUID, *, status: str, severity: str = "medium") -> UUID:
        return self._insert(
            tables.issues,
            {
                "project_id": project_id,
                "owner_user_id": None,
                "reported_by_user_id": self.owner_id,
                "title": "Legacy issue",
                "status": status,
                "severity": severity,
                "closed_at": NOW if status == "closed" else None,
            },
        )


def issue_url(project_id: UUID, issue_id: str | UUID | None = None) -> str:
    base = f"/api/projects/{project_id}/issues"
    return f"{base}/{issue_id}" if issue_id else base


def assign(
    client: TestClient, headers: dict[str, str], project_id: UUID, issue_id: UUID, **fields: object
) -> httpx2.Response:
    return client.patch(issue_url(project_id, issue_id), headers=headers, json=fields)


def transition(
    client: TestClient,
    headers: dict[str, str],
    project_id: UUID,
    issue_id: str | UUID,
    to_status: str,
) -> httpx2.Response:
    return client.post(
        f"{issue_url(project_id, issue_id)}/transitions",
        headers=headers,
        json={"to_status": to_status},
    )


def test_assignment_fields_require_issue_assign_permission(
    client: TestClient, isolated_issue_database: str
) -> None:
    scope = Scope(client, isolated_issue_database)
    try:
        engineer = scope.user("engineer", "engineer")
        quality = scope.user("quality", "quality")
        project_id = scope.project(member_ids=(engineer, quality))
        engineer_headers = bearer_headers(client, username="engineer")

        bare = client.post(
            issue_url(project_id),
            headers=engineer_headers,
            json={"title": "Motor noise", "severity": "medium"},
        )
        assert bare.status_code == 201
        assert bare.json()["issue_type"] == "engineering"

        with_owner = client.post(
            issue_url(project_id),
            headers=engineer_headers,
            json={"title": "Self assigned", "owner_user_id": str(engineer)},
        )
        assert with_owner.status_code == 403

        patch_denied = assign(
            client,
            engineer_headers,
            project_id,
            bare.json()["id"],
            owner_user_id=str(engineer),
        )
        assert patch_denied.status_code == 403

        quality_headers = bearer_headers(client, username="quality")
        patch_ok = assign(
            client,
            quality_headers,
            project_id,
            bare.json()["id"],
            owner_user_id=str(engineer),
            verifier_user_id=str(quality),
            target_date="2026-09-15",
            closure_criteria="Noise below 45 dB across three samples",
        )
        assert patch_ok.status_code == 200
        body = patch_ok.json()
        assert body["verifier_user_id"] == str(quality)
        assert body["closure_criteria"].startswith("Noise below")
    finally:
        scope.dispose()


def test_analysis_requires_full_assignment(
    client: TestClient, isolated_issue_database: str
) -> None:
    scope = Scope(client, isolated_issue_database)
    try:
        engineer = scope.user("engineer", "engineer")
        quality = scope.user("quality", "quality")
        project_id = scope.project(member_ids=(engineer, quality))
        quality_headers = bearer_headers(client, username="quality")
        engineer_headers = bearer_headers(client, username="engineer")

        created = client.post(
            issue_url(project_id),
            headers=quality_headers,
            json={"title": "Thermal drift", "issue_type": "test_failure"},
        )
        issue_id = created.json()["id"]

        blocked = transition(client, engineer_headers, project_id, issue_id, "analysis")
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "ISSUE_ASSIGNMENT_INCOMPLETE"

        assert (
            assign(
                client,
                quality_headers,
                project_id,
                issue_id,
                owner_user_id=str(engineer),
                verifier_user_id=str(quality),
                target_date="2026-09-10",
                closure_criteria="Root cause verified on DVT sample",
            ).status_code
            == 200
        )
        moved = transition(client, engineer_headers, project_id, issue_id, "analysis")
        assert moved.status_code == 200
        assert moved.json()["status"] == "analysis"
    finally:
        scope.dispose()


def test_four_eyes_for_high_severity(client: TestClient, isolated_issue_database: str) -> None:
    scope = Scope(client, isolated_issue_database)
    try:
        engineer = scope.user("engineer", "engineer")
        quality = scope.user("quality", "quality")
        project_id = scope.project(member_ids=(engineer, quality))
        quality_headers = bearer_headers(client, username="quality")

        created = client.post(
            issue_url(project_id),
            headers=quality_headers,
            json={"title": "Battery vent", "severity": "high"},
        )
        issue_id = created.json()["id"]

        same_person = assign(
            client,
            quality_headers,
            project_id,
            issue_id,
            owner_user_id=str(engineer),
            verifier_user_id=str(engineer),
        )
        assert same_person.status_code == 409
        assert same_person.json()["detail"]["code"] == "ISSUE_FOUR_EYES_REQUIRED"

        with pytest.raises(IntegrityError):
            scope.legacy_issue(project_id, status="open", severity="high")
            with scope.engine.begin() as connection:
                connection.execute(
                    tables.issues.update()
                    .where(tables.issues.c.title == "Legacy issue")
                    .values(owner_user_id=engineer, verifier_user_id=engineer)
                )
    finally:
        scope.dispose()


def test_high_issue_closes_only_by_verifier(
    client: TestClient, isolated_issue_database: str
) -> None:
    scope = Scope(client, isolated_issue_database)
    try:
        engineer = scope.user("engineer", "engineer")
        quality = scope.user("quality", "quality")
        project_id = scope.project(member_ids=(engineer, quality))
        quality_headers = bearer_headers(client, username="quality")
        engineer_headers = bearer_headers(client, username="engineer")

        created = client.post(
            issue_url(project_id),
            headers=quality_headers,
            json={
                "title": "Critical leak",
                "severity": "critical",
                "owner_user_id": str(engineer),
                "verifier_user_id": str(quality),
                "closure_criteria": "Leak rate < 0.1 sccm on three units",
                "target_date": "2026-09-20",
            },
        )
        issue_id = created.json()["id"]
        for step in ("analysis", "action", "verification"):
            assert (
                transition(client, engineer_headers, project_id, issue_id, step).status_code == 200
            )

        owner_close = transition(client, engineer_headers, project_id, issue_id, "closed")
        assert owner_close.status_code == 409
        assert owner_close.json()["detail"]["code"] == "ISSUE_CLOSE_REQUIRES_VERIFIER"

        no_evidence = transition(client, quality_headers, project_id, issue_id, "closed")
        assert no_evidence.status_code == 409
        assert no_evidence.json()["detail"]["code"] == "ISSUE_CLOSURE_EVIDENCE_REQUIRED"

        verifier_close = client.post(
            f"{issue_url(project_id, issue_id)}/transitions",
            headers=quality_headers,
            json={
                "to_status": "closed",
                "closure_evidence_ref": "Leak report LR-42, 3/3 units pass",
            },
        )
        assert verifier_close.status_code == 200
        assert verifier_close.json()["status"] == "closed"
        assert verifier_close.json()["closed_at"] is not None
        assert verifier_close.json()["closure_evidence_ref"].startswith("Leak report")
    finally:
        scope.dispose()


def test_submit_verification_only_by_owner_and_reject_only_by_verifier(
    client: TestClient, isolated_issue_database: str
) -> None:
    scope = Scope(client, isolated_issue_database)
    try:
        engineer = scope.user("engineer", "engineer")
        quality = scope.user("quality", "quality")
        project_id = scope.project(member_ids=(engineer, quality))
        quality_headers = bearer_headers(client, username="quality")
        engineer_headers = bearer_headers(client, username="engineer")

        created = client.post(
            issue_url(project_id),
            headers=quality_headers,
            json={
                "title": "Vibration spike",
                "severity": "high",
                "owner_user_id": str(engineer),
                "verifier_user_id": str(quality),
                "closure_criteria": "Vibration under 2g on retest",
                "target_date": "2026-09-12",
            },
        )
        issue_id = created.json()["id"]
        for step in ("analysis", "action"):
            assert (
                transition(client, engineer_headers, project_id, issue_id, step).status_code == 200
            )

        not_owner_submit = transition(client, quality_headers, project_id, issue_id, "verification")
        assert not_owner_submit.status_code == 409
        assert not_owner_submit.json()["detail"]["code"] == "ISSUE_SUBMIT_REQUIRES_OWNER"
        assert (
            transition(client, engineer_headers, project_id, issue_id, "verification").status_code
            == 200
        )

        not_verifier_reject = transition(client, engineer_headers, project_id, issue_id, "action")
        assert not_verifier_reject.status_code == 409
        assert not_verifier_reject.json()["detail"]["code"] == "ISSUE_REJECT_REQUIRES_VERIFIER"

        rejected = client.post(
            f"{issue_url(project_id, issue_id)}/transitions",
            headers=quality_headers,
            json={"to_status": "action", "comment": "Retest missed the 40C corner"},
        )
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "action"
    finally:
        scope.dispose()


def test_reopen_preserves_history_and_increments_count(
    client: TestClient, isolated_issue_database: str
) -> None:
    scope = Scope(client, isolated_issue_database)
    try:
        engineer = scope.user("engineer", "engineer")
        quality = scope.user("quality", "quality")
        project_id = scope.project(member_ids=(engineer, quality))
        quality_headers = bearer_headers(client, username="quality")
        engineer_headers = bearer_headers(client, username="engineer")

        created = client.post(
            issue_url(project_id),
            headers=quality_headers,
            json={
                "title": "Recurring seal failure",
                "severity": "high",
                "owner_user_id": str(engineer),
                "verifier_user_id": str(quality),
                "closure_criteria": "No leak across 500h soak",
                "target_date": "2026-09-30",
            },
        )
        issue_id = created.json()["id"]
        for step in ("analysis", "action", "verification"):
            assert (
                transition(client, engineer_headers, project_id, issue_id, step).status_code == 200
            )
        first_close = client.post(
            f"{issue_url(project_id, issue_id)}/transitions",
            headers=quality_headers,
            json={"to_status": "closed", "closure_evidence_ref": "Soak report SR-7"},
        )
        assert first_close.status_code == 200

        reopened = transition(client, quality_headers, project_id, issue_id, "action")
        assert reopened.status_code == 200
        body = reopened.json()
        assert body["status"] == "action"
        assert body["reopen_count"] == 1
        assert body["closed_at"] is None
        assert body["closure_evidence_ref"] is None

        with scope.engine.connect() as connection:
            snapshots = (
                connection.execute(
                    text(
                        "SELECT before_snapshot->>'closure_evidence_ref' "
                        "FROM cehub_audit.audit_log "
                        "WHERE action = 'issue.transition' AND entity_id = CAST(:issue_id AS uuid) "
                        "ORDER BY id"
                    ),
                    {"issue_id": issue_id},
                )
                .scalars()
                .all()
            )
        assert "Soak report SR-7" in snapshots
    finally:
        scope.dispose()


def test_low_severity_close_by_owner_allowed(
    client: TestClient, isolated_issue_database: str
) -> None:
    scope = Scope(client, isolated_issue_database)
    try:
        engineer = scope.user("engineer", "engineer")
        quality = scope.user("quality", "quality")
        project_id = scope.project(member_ids=(engineer, quality))
        quality_headers = bearer_headers(client, username="quality")
        engineer_headers = bearer_headers(client, username="engineer")

        created = client.post(
            issue_url(project_id),
            headers=quality_headers,
            json={
                "title": "Cosmetic scratch",
                "severity": "low",
                "owner_user_id": str(engineer),
                "verifier_user_id": str(quality),
                "closure_criteria": "Repolished and photographed",
                "target_date": "2026-09-01",
            },
        )
        issue_id = created.json()["id"]
        for step in ("analysis", "action", "verification", "closed"):
            assert (
                transition(client, engineer_headers, project_id, issue_id, step).status_code == 200
            )
    finally:
        scope.dispose()


def test_legacy_rows_stay_compatible(client: TestClient, isolated_issue_database: str) -> None:
    scope = Scope(client, isolated_issue_database)
    try:
        engineer = scope.user("engineer", "engineer")
        project_id = scope.project(member_ids=(engineer,))
        engineer_headers = bearer_headers(client, username="engineer")
        legacy_id = scope.legacy_issue(project_id, status="analysis")

        fetched = client.get(issue_url(project_id, str(legacy_id)), headers=engineer_headers)
        assert fetched.status_code == 200
        body = fetched.json()
        assert body["issue_type"] == "engineering"
        assert body["reopen_count"] == 0
        assert body["verifier_user_id"] is None

        moved = transition(client, engineer_headers, project_id, str(legacy_id), "action")
        assert moved.status_code == 200
    finally:
        scope.dispose()
