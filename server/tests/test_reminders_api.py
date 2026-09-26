"""Reminder policy, idempotent firing, and notification center tests (vNext V1-A7)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Table, create_engine, func, select

from app.auth.passwords import PasswordService
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.domain.reminders import ReminderService, ScanOutcome
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
DUE = date(2026, 9, 10)
BEFORE_DUE = "2026-09-07T12:00:00Z"
AFTER_DUE = "2026-09-13T12:00:00Z"


@pytest.fixture(autouse=True)
def isolated_reminder_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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
        workflow_id = self._insert(tables.workflows, {"code": "WF-REM", "name": "Workflow"})
        project_id = self._insert(
            tables.projects,
            {
                "workflow_id": workflow_id,
                "owner_user_id": self.owner_id,
                "code": "PRJ-REM",
                "name": "Reminder project",
                "status": "active",
            },
        )
        for member_id in (self.owner_id, *member_ids):
            self._insert(
                tables.project_members,
                {
                    "project_id": project_id,
                    "user_id": member_id,
                    "added_by_user_id": self.owner_id,
                },
            )
        return project_id

    def task(self, project_id: UUID, *, assignee: UUID, due: date | None, title: str) -> UUID:
        return self._insert(
            tables.tasks,
            {
                "project_id": project_id,
                "assignee_user_id": assignee,
                "title": title,
                "status": "todo",
                "due_date": due,
            },
        )

    def issue(
        self,
        project_id: UUID,
        *,
        owner: UUID,
        verifier: UUID | None,
        status: str,
        title: str,
        updated_at: datetime | None = None,
    ) -> UUID:
        values: dict[str, Any] = {
            "project_id": project_id,
            "owner_user_id": owner,
            "verifier_user_id": verifier,
            "reported_by_user_id": self.owner_id,
            "title": title,
            "status": status,
            "severity": "medium",
        }
        if updated_at is not None:
            values["updated_at"] = updated_at
        return self._insert(tables.issues, values)

    def complete_task(self, task_id: UUID) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                tables.tasks.update()
                .where(tables.tasks.c.id == task_id)
                .values(status="done", completed_at=datetime(2026, 9, 8, tzinfo=UTC))
            )


def scan(
    client: TestClient, headers: dict[str, str], project_id: UUID, as_of: str
) -> httpx2.Response:
    return client.post(f"/api/projects/{project_id}/reminders/scan?as_of={as_of}", headers=headers)


def notifications(client: TestClient, headers: dict[str, str]) -> httpx2.Response:
    return client.get("/api/me/notifications", headers=headers)


def test_due_ladder_fires_idempotently_and_escalates_to_project_owner(
    client: TestClient, isolated_reminder_database: str
) -> None:
    scope = Scope(client, isolated_reminder_database)
    try:
        engineer = scope.user("engineer", "engineer")
        project_id = scope.project(member_ids=(engineer,))
        scope.task(project_id, assignee=engineer, due=DUE, title="Verify motor sample")
        headers = bearer_headers(client)

        first = scan(client, headers, project_id, BEFORE_DUE).json()
        assert first == {"scheduled": 7, "cancelled": 0, "fired": 2}

        second = scan(client, headers, project_id, BEFORE_DUE).json()
        assert second == {"scheduled": 0, "cancelled": 0, "fired": 0}

        engineer_view = notifications(client, bearer_headers(client, username="engineer")).json()
        assert engineer_view["unread_count"] == 2
        titles = [item["title"] for item in engineer_view["items"]]
        assert any("待接单" in title for title in titles)
        assert any("3 天后到期" in title for title in titles)

        third = scan(client, headers, project_id, AFTER_DUE).json()
        assert third == {"scheduled": 0, "cancelled": 0, "fired": 5}

        engineer_view = notifications(client, bearer_headers(client, username="engineer")).json()
        assert engineer_view["unread_count"] == 6
        digest = {entry["policy_key"]: entry["count"] for entry in engineer_view["digest"]}
        assert digest["task_due_overdue3"] == 1

        owner_view = notifications(client, headers).json()
        assert owner_view["unread_count"] == 1
        assert owner_view["items"][0]["policy_key"] == "task_due_escalation"
        assert owner_view["items"][0]["escalation_level"] == 1
    finally:
        scope.dispose()


def test_recovered_sources_cancel_outstanding_reminders(
    client: TestClient, isolated_reminder_database: str
) -> None:
    scope = Scope(client, isolated_reminder_database)
    try:
        engineer = scope.user("engineer", "engineer")
        project_id = scope.project(member_ids=(engineer,))
        task_id = scope.task(
            project_id, assignee=engineer, due=date(2026, 9, 20), title="Order tooling"
        )
        headers = bearer_headers(client)

        first = scan(client, headers, project_id, BEFORE_DUE).json()
        assert first["scheduled"] == 7
        assert first["fired"] == 1  # 接单提醒立即触发，其余在未来

        scope.complete_task(task_id)
        second = scan(client, headers, project_id, BEFORE_DUE).json()
        assert second["cancelled"] == 6
        assert second["fired"] == 0

        engineer_view = notifications(client, bearer_headers(client, username="engineer")).json()
        assert engineer_view["unread_count"] == 1  # 已触发的接单提醒保留为历史
    finally:
        scope.dispose()


def test_verify_and_stalled_policies_target_the_right_people(
    client: TestClient, isolated_reminder_database: str
) -> None:
    scope = Scope(client, isolated_reminder_database)
    try:
        engineer = scope.user("engineer", "engineer")
        quality = scope.user("quality", "quality")
        project_id = scope.project(member_ids=(engineer, quality))
        scope.issue(
            project_id,
            owner=engineer,
            verifier=quality,
            status="verification",
            title="Thermal drift",
        )
        as_of = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
        scope.issue(
            project_id,
            owner=engineer,
            verifier=quality,
            status="analysis",
            title="Slow leak",
            updated_at=as_of - timedelta(days=8),
        )
        headers = bearer_headers(client)

        result = scan(client, headers, project_id, BEFORE_DUE).json()
        assert result["fired"] == 2

        quality_view = notifications(client, bearer_headers(client, username="quality")).json()
        assert [item["policy_key"] for item in quality_view["items"]] == ["issue_verify"]

        engineer_view = notifications(client, bearer_headers(client, username="engineer")).json()
        assert [item["policy_key"] for item in engineer_view["items"]] == ["issue_stalled"]
    finally:
        scope.dispose()


def test_acknowledge_is_recipient_scoped(
    client: TestClient, isolated_reminder_database: str
) -> None:
    scope = Scope(client, isolated_reminder_database)
    try:
        engineer = scope.user("engineer", "engineer")
        quality = scope.user("quality", "quality")
        scope.user("vendor", "supplier")
        project_id = scope.project(member_ids=(engineer, quality))
        scope.task(project_id, assignee=engineer, due=None, title="Ack me")
        headers = bearer_headers(client)
        assert scan(client, headers, project_id, BEFORE_DUE).json()["fired"] == 1

        engineer_headers = bearer_headers(client, username="engineer")
        reminder_id = notifications(client, engineer_headers).json()["items"][0]["id"]

        stolen = client.post(
            f"/api/me/notifications/{reminder_id}/ack",
            headers=bearer_headers(client, username="quality"),
        )
        assert stolen.status_code == 404

        acked = client.post(f"/api/me/notifications/{reminder_id}/ack", headers=engineer_headers)
        assert acked.status_code == 200
        assert acked.json()["status"] == "acknowledged"
        assert notifications(client, engineer_headers).json()["unread_count"] == 0

        again = client.post(f"/api/me/notifications/{reminder_id}/ack", headers=engineer_headers)
        assert again.status_code == 200

        denied = notifications(client, bearer_headers(client, username="vendor"))
        assert denied.status_code == 403
    finally:
        scope.dispose()


def test_cancelled_unfired_version_can_resume_without_replaying_fired_history(
    client: TestClient, isolated_reminder_database: str
) -> None:
    scope = Scope(client, isolated_reminder_database)
    try:
        engineer = scope.user("engineer", "engineer")
        project_id = scope.project(member_ids=(engineer,))
        task_id = scope.task(project_id, assignee=engineer, due=DUE, title="Resume tooling")
        headers = bearer_headers(client)
        assert scan(client, headers, project_id, BEFORE_DUE).json()["fired"] == 2
        scope.complete_task(task_id)
        assert scan(client, headers, project_id, BEFORE_DUE).json()["cancelled"] == 5

        with scope.engine.begin() as connection:
            connection.execute(
                tables.tasks.update()
                .where(tables.tasks.c.id == task_id)
                .values(status="todo", completed_at=None)
            )
        resumed = scan(client, headers, project_id, AFTER_DUE).json()
        assert resumed == {"scheduled": 5, "cancelled": 0, "fired": 5}
        with scope.engine.connect() as connection:
            events_before = connection.execute(
                select(func.count()).select_from(tables.events)
            ).scalar_one()
            audits_before = connection.execute(
                select(func.count()).select_from(tables.audit_log)
            ).scalar_one()
            assert (
                connection.execute(select(func.count()).select_from(tables.reminders)).scalar_one()
                == 7
            )
            assert (
                connection.execute(
                    select(func.count()).where(tables.audit_log.c.action == "reminder.reschedule")
                ).scalar_one()
                == 5
            )
        assert scan(client, headers, project_id, AFTER_DUE).json() == {
            "scheduled": 0,
            "cancelled": 0,
            "fired": 0,
        }
        with scope.engine.connect() as connection:
            assert (
                connection.execute(select(func.count()).select_from(tables.events)).scalar_one()
                == events_before
            )
            assert (
                connection.execute(select(func.count()).select_from(tables.audit_log)).scalar_one()
                == audits_before
            )
        engineer_view = notifications(client, bearer_headers(client, username="engineer")).json()
        assert engineer_view["unread_count"] == 6
    finally:
        scope.dispose()


@pytest.mark.parametrize("change", ["deadline", "recipient"])
def test_source_version_change_cancels_stale_schedule_before_firing(
    client: TestClient, isolated_reminder_database: str, change: str
) -> None:
    scope = Scope(client, isolated_reminder_database)
    try:
        engineer = scope.user("engineer", "engineer")
        quality = scope.user("quality", "quality")
        project_id = scope.project(member_ids=(engineer, quality))
        task_id = scope.task(project_id, assignee=engineer, due=DUE, title="Replanned task")
        headers = bearer_headers(client)
        assert scan(client, headers, project_id, BEFORE_DUE).json()["fired"] == 2
        with scope.engine.begin() as connection:
            connection.execute(
                tables.tasks.update()
                .where(tables.tasks.c.id == task_id)
                .values(
                    **(
                        {"due_date": date(2026, 9, 20)}
                        if change == "deadline"
                        else {"assignee_user_id": quality}
                    )
                )
            )
        result = scan(client, headers, project_id, AFTER_DUE).json()
        assert result["cancelled"] == (5 if change == "deadline" else 4)
        engineer_view = notifications(client, bearer_headers(client, username="engineer")).json()
        assert engineer_view["unread_count"] == 2  # Fired history survives both source changes.
        if change == "deadline":
            assert result["fired"] == 0
            assert notifications(client, headers).json()["unread_count"] == 0
        else:
            assert result["fired"] == 7  # New recipient gets six policies; owner gets escalation.
            assert (
                notifications(client, bearer_headers(client, username="quality")).json()[
                    "unread_count"
                ]
                == 6
            )
        assert scan(client, headers, project_id, AFTER_DUE).json()["fired"] == 0
    finally:
        scope.dispose()


def test_existing_legacy_instances_are_reused_until_the_source_version_changes(
    client: TestClient, isolated_reminder_database: str
) -> None:
    scope = Scope(client, isolated_reminder_database)
    try:
        engineer = scope.user("engineer", "engineer")
        project_id = scope.project(member_ids=(engineer,))
        task_id = scope.task(project_id, assignee=engineer, due=DUE, title="Existing reminder")
        headers = bearer_headers(client)
        scan(client, headers, project_id, BEFORE_DUE)
        with scope.engine.begin() as connection:
            rows = connection.execute(select(tables.reminders)).all()
            for row in rows:
                legacy_key = (
                    f"task_accept:{task_id}"
                    if row.policy_key == "task_accept"
                    else f"task_due:{task_id}:{row.policy_key.removeprefix('task_due_')}"
                )
                connection.execute(
                    tables.reminders.update()
                    .where(tables.reminders.c.id == row.id)
                    .values(dedupe_key=legacy_key)
                )
        assert scan(client, headers, project_id, BEFORE_DUE).json() == {
            "scheduled": 0,
            "cancelled": 0,
            "fired": 0,
        }
        with scope.engine.begin() as connection:
            connection.execute(
                tables.tasks.update()
                .where(tables.tasks.c.id == task_id)
                .values(due_date=date(2026, 9, 20))
            )
        assert scan(client, headers, project_id, AFTER_DUE).json() == {
            "scheduled": 6,
            "cancelled": 5,
            "fired": 0,
        }
        with scope.engine.begin() as connection:
            connection.execute(
                tables.tasks.update().where(tables.tasks.c.id == task_id).values(due_date=DUE)
            )
        assert scan(client, headers, project_id, AFTER_DUE).json() == {
            "scheduled": 5,
            "cancelled": 6,
            "fired": 5,
        }
        engineer_view = notifications(client, bearer_headers(client, username="engineer")).json()
        assert engineer_view["unread_count"] == 6
    finally:
        scope.dispose()


def test_new_inactivity_period_has_one_new_stalled_reminder(
    client: TestClient, isolated_reminder_database: str
) -> None:
    scope = Scope(client, isolated_reminder_database)
    try:
        engineer = scope.user("engineer", "engineer")
        project_id = scope.project(member_ids=(engineer,))
        as_of = datetime(2026, 9, 7, 12, tzinfo=UTC)
        issue_id = scope.issue(
            project_id,
            owner=engineer,
            verifier=None,
            status="analysis",
            title="Repeated stall",
            updated_at=as_of - timedelta(days=8),
        )
        headers = bearer_headers(client)
        assert scan(client, headers, project_id, BEFORE_DUE).json()["fired"] == 1
        with scope.engine.begin() as connection:
            connection.execute(
                tables.issues.update()
                .where(tables.issues.c.id == issue_id)
                .values(updated_at=as_of)
            )
        assert scan(client, headers, project_id, AFTER_DUE).json()["fired"] == 0
        later = "2026-09-15T12:00:00Z"
        assert scan(client, headers, project_id, later).json()["fired"] == 1
        assert scan(client, headers, project_id, later).json()["fired"] == 0
        assert (
            notifications(client, bearer_headers(client, username="engineer")).json()[
                "unread_count"
            ]
            == 2
        )
    finally:
        scope.dispose()


@pytest.mark.parametrize("disabled_scope", ["tenant", "project"])
def test_automatic_scan_rechecks_scope_and_records_system_actor(
    client: TestClient, isolated_reminder_database: str, disabled_scope: str
) -> None:
    scope = Scope(client, isolated_reminder_database)
    try:
        project_id = scope.project(member_ids=())
        scope.task(project_id, assignee=scope.owner_id, due=DUE, title="System reminder")
        service = ReminderService(scope.engine)
        as_of = datetime(2026, 9, 7, 12, tzinfo=UTC)
        first = service.scan(
            tenant_id=scope.tenant_id,
            actor_user_id=None,
            project_id=project_id,
            as_of=as_of,
            automatic=True,
        )
        assert first.fired == 2
        with scope.engine.begin() as connection:
            assert set(
                connection.execute(
                    select(tables.audit_log.c.actor_user_id).where(
                        tables.audit_log.c.entity == "reminder"
                    )
                ).scalars()
            ) == {None}
            if disabled_scope == "tenant":
                connection.execute(
                    tables.tenants.update()
                    .where(tables.tenants.c.id == scope.tenant_id)
                    .values(status="suspended")
                )
            else:
                connection.execute(
                    tables.projects.update()
                    .where(tables.projects.c.id == project_id)
                    .values(status="archived")
                )
        assert service.scan(
            tenant_id=scope.tenant_id,
            actor_user_id=None,
            project_id=project_id,
            as_of=as_of + timedelta(days=8),
            automatic=True,
        ) == ScanOutcome(scheduled=0, cancelled=0, fired=0)
    finally:
        scope.dispose()
