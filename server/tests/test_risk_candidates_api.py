"""Rule-based risk candidate tests (vNext V1-A6)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Table, create_engine

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
YESTERDAY = date(2026, 8, 24)


@pytest.fixture(autouse=True)
def isolated_candidate_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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
        self.workflow_id: UUID | None = None
        self.stage_id: UUID | None = None

    def dispose(self) -> None:
        self.engine.dispose()

    def _insert(self, table: Table, values: dict[str, Any]) -> UUID:
        row_id: UUID = values.setdefault("id", uuid4())
        values.setdefault("tenant_id", self.tenant_id)
        with self.engine.begin() as connection:
            connection.execute(table.insert(), values)
        return row_id

    def project(self) -> UUID:
        self.workflow_id = self._insert(tables.workflows, {"code": "WF-RC", "name": "Workflow"})
        self.stage_id = self._insert(
            tables.stages,
            {"workflow_id": self.workflow_id, "code": "evt", "name": "EVT", "sequence": 1},
        )
        project_id = self._insert(
            tables.projects,
            {
                "workflow_id": self.workflow_id,
                "owner_user_id": self.owner_id,
                "code": "PRJ-RC",
                "name": "Candidate project",
                "status": "active",
            },
        )
        self._insert(
            tables.project_members,
            {"project_id": project_id, "user_id": self.owner_id, "added_by_user_id": self.owner_id},
        )
        return project_id

    def overdue_task(self, project_id: UUID, *, title: str, priority: str = "high") -> UUID:
        return self._insert(
            tables.tasks,
            {
                "project_id": project_id,
                "title": title,
                "status": "in_progress",
                "priority": priority,
                "due_date": YESTERDAY,
            },
        )

    def overdue_issue(self, project_id: UUID, *, title: str) -> UUID:
        return self._insert(
            tables.issues,
            {
                "project_id": project_id,
                "reported_by_user_id": self.owner_id,
                "title": title,
                "status": "open",
                "severity": "critical",
                "target_date": YESTERDAY,
            },
        )

    def failed_test_case(self, project_id: UUID, *, title: str) -> UUID:
        plan_id = self._insert(
            tables.test_plans,
            {
                "project_id": project_id,
                "workflow_id": self.workflow_id,
                "stage_id": self.stage_id,
                "created_by_user_id": self.owner_id,
                "phase": "evt",
                "title": "EVT plan",
                "sample_size": 3,
                "status": "active",
            },
        )
        return self._insert(
            tables.test_cases,
            {
                "project_id": project_id,
                "plan_id": plan_id,
                "created_by_user_id": self.owner_id,
                "title": title,
                "category": "performance",
                "acceptance_criteria": "Meets spec",
                "severity": "critical",
                "status": "failed",
                "executed_by_user_id": self.owner_id,
                "executed_at": NOW,
            },
        )

    def complete_task(self, task_id: UUID) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                tables.tasks.update()
                .where(tables.tasks.c.id == task_id)
                .values(status="done", completed_at=NOW)
            )


def scan(client: TestClient, headers: dict[str, str], project_id: UUID) -> httpx2.Response:
    return client.post(f"/api/projects/{project_id}/risk-candidates/scan", headers=headers)


def candidates(client: TestClient, headers: dict[str, str], project_id: UUID) -> httpx2.Response:
    return client.get(f"/api/projects/{project_id}/risk-candidates", headers=headers)


def risks(client: TestClient, headers: dict[str, str], project_id: UUID) -> httpx2.Response:
    return client.get(f"/api/projects/{project_id}/risks", headers=headers)


def test_scan_generates_deterministic_candidates_and_hides_them_from_risk_list(
    client: TestClient, isolated_candidate_database: str
) -> None:
    scope = Scope(client, isolated_candidate_database)
    try:
        project_id = scope.project()
        scope.overdue_task(project_id, title="Freeze BOM", priority="critical")
        scope.overdue_issue(project_id, title="Thermal drift")
        scope.failed_test_case(project_id, title="Endurance 500h")
        headers = bearer_headers(client)

        result = scan(client, headers, project_id).json()
        assert result["created"] == 3
        assert result["cleared"] == 0
        rules = sorted(item["title"].split("：")[0] for item in result["items"])
        assert rules == ["任务逾期", "测试失败", "问题逾期"]
        by_rule = {item["title"].split("：")[0]: item for item in result["items"]}
        assert by_rule["任务逾期"]["impact"] == 5
        assert by_rule["测试失败"]["likelihood"] == 4

        listed = candidates(client, headers, project_id).json()["items"]
        assert len(listed) == 3
        assert risks(client, headers, project_id).json()["items"] == []
    finally:
        scope.dispose()


def test_rescan_is_idempotent_and_clears_recovered_sources(
    client: TestClient, isolated_candidate_database: str
) -> None:
    scope = Scope(client, isolated_candidate_database)
    try:
        project_id = scope.project()
        task_id = scope.overdue_task(project_id, title="Order tooling")
        headers = bearer_headers(client)

        first = scan(client, headers, project_id).json()
        assert first["created"] == 1
        candidate_id = first["items"][0]["id"]

        second = scan(client, headers, project_id).json()
        assert second["created"] == 0
        assert second["reactivated"] == 0
        assert [item["id"] for item in second["items"]] == [candidate_id]

        scope.complete_task(task_id)
        third = scan(client, headers, project_id).json()
        assert third["cleared"] == 1
        assert third["items"] == []

        with scope.engine.begin() as connection:
            connection.execute(
                tables.tasks.update()
                .where(tables.tasks.c.id == task_id)
                .values(status="in_progress", completed_at=None)
            )
        fourth = scan(client, headers, project_id).json()
        assert fourth["created"] == 0
        assert fourth["reactivated"] == 1
        assert [item["id"] for item in fourth["items"]] == [candidate_id]
    finally:
        scope.dispose()


def test_confirm_promotes_candidate_and_guards_unconfirmed_edits(
    client: TestClient, isolated_candidate_database: str
) -> None:
    scope = Scope(client, isolated_candidate_database)
    try:
        project_id = scope.project()
        scope.overdue_issue(project_id, title="Leak recurrence")
        headers = bearer_headers(client)

        result = scan(client, headers, project_id).json()
        candidate_id = result["items"][0]["id"]

        premature = client.post(
            f"/api/projects/{project_id}/risks/{candidate_id}/transitions",
            headers=headers,
            json={"to_status": "mitigating"},
        )
        assert premature.status_code == 409
        assert premature.json()["detail"]["code"] == "RISK_NOT_CONFIRMED"

        confirmed = client.post(
            f"/api/projects/{project_id}/risks/{candidate_id}/confirm", headers=headers
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "open"

        listed = risks(client, headers, project_id).json()["items"]
        assert [item["id"] for item in listed] == [candidate_id]
        assert candidates(client, headers, project_id).json()["items"] == []

        again = client.post(
            f"/api/projects/{project_id}/risks/{candidate_id}/confirm", headers=headers
        )
        assert again.status_code == 409

        rescan = scan(client, headers, project_id).json()
        assert rescan["created"] == 0
        assert rescan["reactivated"] == 0
    finally:
        scope.dispose()
