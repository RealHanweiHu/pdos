"""Organization, delegation, and handover HTTP tests (vNext V1-A11, G5/G6)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Row, Table, create_engine, select
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
ORG = "/api/admin/organization"


@pytest.fixture(autouse=True)
def isolated_organization_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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


class Scope:
    def __init__(self, client: TestClient, database_url: str) -> None:
        setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
        self.tenant_id = UUID(setup["tenant"]["id"])
        self.owner_id = UUID(setup["user"]["id"])
        self.engine = create_engine(psycopg_database_url(database_url))
        self.password_hash = PasswordService().hash(PASSWORD)

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
                "password_hash": self.password_hash,
            },
        )

    def project(self, *, owner_user_id: UUID, member_ids: tuple[UUID, ...] = ()) -> UUID:
        workflow_id = self._insert(tables.workflows, {"code": "WF-ORG", "name": "Workflow"})
        project_id = self._insert(
            tables.projects,
            {
                "workflow_id": workflow_id,
                "owner_user_id": owner_user_id,
                "code": f"PRJ-{uuid4().hex[:6]}",
                "name": "Org project",
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

    def issue(
        self,
        project_id: UUID,
        *,
        owner: UUID | None,
        verifier: UUID | None,
        status: str = "open",
    ) -> UUID:
        values: dict[str, Any] = {
            "project_id": project_id,
            "reported_by_user_id": self.owner_id,
            "owner_user_id": owner,
            "verifier_user_id": verifier,
            "title": "Impeller vibration",
            "status": status,
            "severity": "high",
        }
        if status == "closed":
            values["closed_at"] = datetime.now(UTC)
        return self._insert(tables.issues, values)

    def task(self, project_id: UUID, *, assignee: UUID, status: str = "todo") -> UUID:
        values = {
            "project_id": project_id,
            "assignee_user_id": assignee,
            "title": "Check seal torque",
            "status": status,
        }
        if status == "done":
            values["completed_at"] = datetime.now(UTC)
        return self._insert(tables.tasks, values)

    def audit_actions(self) -> list[str]:
        with self.engine.connect() as connection:
            return [
                row.action
                for row in connection.execute(
                    select(tables.audit_log.c.action).where(
                        tables.audit_log.c.tenant_id == self.tenant_id
                    )
                )
            ]

    def event_types(self) -> list[str]:
        with self.engine.connect() as connection:
            return [
                row.event_type
                for row in connection.execute(
                    select(tables.events.c.event_type).where(
                        tables.events.c.tenant_id == self.tenant_id
                    )
                )
            ]

    def row(self, table: Table, row_id: UUID) -> Row[Any]:
        with self.engine.connect() as connection:
            return connection.execute(
                select(table).where(table.c.tenant_id == self.tenant_id, table.c.id == row_id)
            ).one()


def window(*, start_offset_hours: int = -1, end_offset_hours: int = 48) -> dict[str, str]:
    now = datetime.now(UTC)
    return {
        "starts_at": (now + timedelta(hours=start_offset_hours)).isoformat(),
        "ends_at": (now + timedelta(hours=end_offset_hours)).isoformat(),
    }


def test_departments_and_reporting_lines_build_the_escalation_chain(
    client: TestClient, isolated_organization_database: str
) -> None:
    scope = Scope(client, isolated_organization_database)
    try:
        headers = bearer_headers(client)
        hardware = client.post(f"{ORG}/departments", headers=headers, json={"name": "硬件部"})
        assert hardware.status_code == 201
        hardware_id = hardware.json()["id"]
        structure = client.post(
            f"{ORG}/departments",
            headers=headers,
            json={"name": "结构组", "parent_department_id": hardware_id},
        )
        assert structure.status_code == 201
        assert structure.json()["parent_department_id"] == hardware_id

        director = scope.user("director", "project_manager")
        lead = scope.user("lead", "project_manager")
        engineer = scope.user("engineer", "engineer")
        for user_id, manager_id in ((lead, director), (engineer, lead)):
            placed = client.put(
                f"{ORG}/users/{user_id}/placement",
                headers=headers,
                json={"department_id": hardware_id, "manager_user_id": str(manager_id)},
            )
            assert placed.status_code == 204

        chain = client.get(f"{ORG}/users/{engineer}/escalation-chain", headers=headers)
        assert chain.status_code == 200
        assert chain.json()["manager_user_ids"] == [str(lead), str(director)]

        # A cycle (director reporting to the engineer below them) is refused.
        cyclic = client.put(
            f"{ORG}/users/{director}/placement",
            headers=headers,
            json={"manager_user_id": str(engineer)},
        )
        assert cyclic.status_code == 409
        assert cyclic.json()["detail"]["code"] == "REPORTING_CYCLE"

        listed = client.get(f"{ORG}/departments", headers=headers)
        assert [item["name"] for item in listed.json()["items"]] == ["硬件部", "结构组"]
    finally:
        scope.dispose()


def test_delegate_borrows_project_reach_only_inside_the_window(
    client: TestClient, isolated_organization_database: str
) -> None:
    scope = Scope(client, isolated_organization_database)
    try:
        headers = bearer_headers(client)
        principal = scope.user("principal", "engineer")
        delegate = scope.user("delegate", "engineer")
        project_id = scope.project(owner_user_id=scope.owner_id, member_ids=(principal,))
        delegate_headers = bearer_headers(client, username="delegate")

        # Before any delegation the stand-in cannot reach the project.
        denied = client.get(f"/api/projects/{project_id}/issues", headers=delegate_headers)
        assert denied.status_code == 403

        granted = client.post(
            f"{ORG}/delegations",
            headers=headers,
            json={
                "principal_user_id": str(principal),
                "delegate_user_id": str(delegate),
                "reason": "年假代班",
                **window(),
            },
        )
        assert granted.status_code == 201
        delegation_id = granted.json()["id"]

        allowed = client.get(f"/api/projects/{project_id}/issues", headers=delegate_headers)
        assert allowed.status_code == 200

        revoked = client.post(f"{ORG}/delegations/{delegation_id}/revoke", headers=headers)
        assert revoked.status_code == 200
        assert revoked.json()["revoked_at"] is not None
        assert (
            client.get(f"/api/projects/{project_id}/issues", headers=delegate_headers).status_code
            == 403
        )

        # Revoking twice is a conflict-free 404, not a silent success.
        assert (
            client.post(f"{ORG}/delegations/{delegation_id}/revoke", headers=headers).status_code
            == 404
        )

        actions = scope.audit_actions()
        assert "user.delegation_grant" in actions
        assert "user.delegation_revoke" in actions
        types = scope.event_types()
        assert "USER_DELEGATION_GRANTED" in types
        assert "USER_DELEGATION_REVOKED" in types
    finally:
        scope.dispose()


def test_expired_and_future_delegations_grant_nothing(
    client: TestClient, isolated_organization_database: str
) -> None:
    scope = Scope(client, isolated_organization_database)
    try:
        headers = bearer_headers(client)
        principal = scope.user("principal", "engineer")
        delegate = scope.user("delegate", "engineer")
        project_id = scope.project(owner_user_id=scope.owner_id, member_ids=(principal,))
        delegate_headers = bearer_headers(client, username="delegate")

        future = client.post(
            f"{ORG}/delegations",
            headers=headers,
            json={
                "principal_user_id": str(principal),
                "delegate_user_id": str(delegate),
                "reason": "下周出差",
                **window(start_offset_hours=48, end_offset_hours=96),
            },
        )
        assert future.status_code == 201
        assert (
            client.get(f"/api/projects/{project_id}/issues", headers=delegate_headers).status_code
            == 403
        ), "a delegation that has not started must not grant reach"

        already_over = client.post(
            f"{ORG}/delegations",
            headers=headers,
            json={
                "principal_user_id": str(principal),
                "delegate_user_id": str(delegate),
                "reason": "上周年假",
                **window(start_offset_hours=-96, end_offset_hours=-48),
            },
        )
        assert already_over.status_code == 422
        assert already_over.json()["detail"]["code"] == "DELEGATION_WINDOW_INVALID"

        self_delegation = client.post(
            f"{ORG}/delegations",
            headers=headers,
            json={
                "principal_user_id": str(principal),
                "delegate_user_id": str(principal),
                "reason": "自我代理",
                **window(),
            },
        )
        assert self_delegation.status_code == 422
    finally:
        scope.dispose()


def test_delegation_never_lets_one_person_satisfy_four_eyes(
    client: TestClient, isolated_organization_database: str
) -> None:
    """A delegate acts under their own identity, so四眼 still needs two humans."""
    scope = Scope(client, isolated_organization_database)
    try:
        headers = bearer_headers(client)
        owner_engineer = scope.user("owner_engineer", "engineer")
        delegate = scope.user("delegate", "engineer")
        project_id = scope.project(
            owner_user_id=scope.owner_id, member_ids=(owner_engineer, delegate)
        )
        client.post(
            f"{ORG}/delegations",
            headers=headers,
            json={
                "principal_user_id": str(owner_engineer),
                "delegate_user_id": str(delegate),
                "reason": "病假代班",
                **window(),
            },
        )
        # The delegate is both owner and verifier of the same issue: the
        # four-eyes CHECK must refuse it regardless of the delegation.
        with pytest.raises(IntegrityError):
            scope.issue(project_id, owner=delegate, verifier=delegate)
    finally:
        scope.dispose()


def test_handover_moves_open_work_only_and_leaves_one_audited_event(
    client: TestClient, isolated_organization_database: str
) -> None:
    scope = Scope(client, isolated_organization_database)
    try:
        headers = bearer_headers(client)
        leaver = scope.user("leaver", "engineer")
        successor = scope.user("successor", "engineer")
        reviewer = scope.user("reviewer", "quality")
        report = scope.user("report", "engineer")
        project_id = scope.project(
            owner_user_id=scope.owner_id, member_ids=(leaver, successor, reviewer)
        )

        open_issue = scope.issue(project_id, owner=leaver, verifier=reviewer)
        closed_issue = scope.issue(project_id, owner=leaver, verifier=reviewer, status="closed")
        verify_issue = scope.issue(project_id, owner=reviewer, verifier=leaver)
        open_task = scope.task(project_id, assignee=leaver)
        done_task = scope.task(project_id, assignee=leaver, status="done")
        client.put(
            f"{ORG}/users/{report}/placement",
            headers=headers,
            json={"manager_user_id": str(leaver)},
        )
        client.post(
            f"{ORG}/delegations",
            headers=headers,
            json={
                "principal_user_id": str(leaver),
                "delegate_user_id": str(successor),
                "reason": "交接前代班",
                **window(),
            },
        )

        preview = client.post(
            f"{ORG}/handover/preview",
            headers=headers,
            json={"from_user_id": str(leaver), "to_user_id": str(successor)},
        )
        assert preview.status_code == 200
        result = client.post(
            f"{ORG}/handover",
            headers=headers,
            json={
                "from_user_id": str(leaver),
                "to_user_id": str(successor),
                "expected_digest": preview.json()["basis_digest"],
            },
        )
        assert result.status_code == 200
        counts = result.json()["transferred_counts"]
        assert counts["issue_owner"] == 1
        assert counts["issue_verifier"] == 1
        assert counts["task_assignee"] == 1
        assert counts["direct_reports"] == 1
        assert counts["delegations_revoked"] == 1
        assert result.json()["deactivated"] is True

        assert scope.row(tables.issues, open_issue).owner_user_id == successor
        assert scope.row(tables.issues, verify_issue).verifier_user_id == successor
        assert scope.row(tables.tasks, open_task).assignee_user_id == successor
        # History keeps its original owner so the audit trail stays truthful.
        assert scope.row(tables.issues, closed_issue).owner_user_id == leaver
        assert scope.row(tables.tasks, done_task).assignee_user_id == leaver
        assert scope.row(tables.users, report).manager_user_id == successor
        assert scope.row(tables.users, leaver).is_active is False

        replay = client.post(
            f"{ORG}/handover",
            headers=headers,
            json={
                "from_user_id": str(leaver),
                "to_user_id": str(successor),
                "expected_digest": preview.json()["basis_digest"],
            },
        )
        assert replay.status_code == 200
        assert replay.json() == result.json()
        assert scope.event_types().count("USER_RESPONSIBILITY_TRANSFERRED") == 1
        assert "user.responsibility_handover" in scope.audit_actions()

        self_handover = client.post(
            f"{ORG}/handover",
            headers=headers,
            json={
                "from_user_id": str(successor),
                "to_user_id": str(successor),
                "expected_digest": preview.json()["basis_digest"],
            },
        )
        assert self_handover.status_code == 422
        assert self_handover.json()["detail"]["code"] == "HANDOVER_TARGET_INVALID"
    finally:
        scope.dispose()


def test_organization_surface_is_admin_only(
    client: TestClient, isolated_organization_database: str
) -> None:
    scope = Scope(client, isolated_organization_database)
    try:
        scope.user("engineer", "engineer")
        engineer_headers = bearer_headers(client, username="engineer")
        for method, path, payload in (
            ("get", f"{ORG}/departments", None),
            ("post", f"{ORG}/departments", {"name": "结构组"}),
            ("get", f"{ORG}/delegations", None),
            (
                "post",
                f"{ORG}/handover",
                {
                    "from_user_id": str(uuid4()),
                    "to_user_id": str(uuid4()),
                    "expected_digest": "0" * 64,
                },
            ),
        ):
            response = getattr(client, method)(
                path, headers=engineer_headers, **({"json": payload} if payload else {})
            )
            assert response.status_code == 403, path
            assert response.json()["detail"]["code"] == "USER_MANAGEMENT_FORBIDDEN"
        assert client.get(f"{ORG}/departments").status_code == 401
    finally:
        scope.dispose()
