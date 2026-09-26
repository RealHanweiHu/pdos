"""Structured test run tests (vNext V1-B3)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import RowMapping, Table, create_engine, select

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
def isolated_test_run_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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


def bearer_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": "owner", "password": PASSWORD},
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

    def project(self) -> UUID:
        workflow_id = self._insert(tables.workflows, {"code": "WF-RUN", "name": "Workflow"})
        self.workflow_id = workflow_id
        self.stage_id = self._insert(
            tables.stages,
            {"workflow_id": workflow_id, "code": "evt", "name": "EVT", "sequence": 1},
        )
        project_id = self._insert(
            tables.projects,
            {
                "workflow_id": workflow_id,
                "owner_user_id": self.owner_id,
                "code": "PRJ-RUN",
                "name": "Run project",
                "status": "active",
            },
        )
        self._insert(
            tables.project_members,
            {"project_id": project_id, "user_id": self.owner_id, "added_by_user_id": self.owner_id},
        )
        return project_id

    def test_case(self, project_id: UUID, *, severity: str = "major") -> UUID:
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
                "title": "Endurance 500h",
                "category": "reliability",
                "acceptance_criteria": "No leak across soak",
                "severity": severity,
                "status": "planned",
            },
        )

    def case_row(self, case_id: UUID) -> RowMapping:
        with self.engine.connect() as connection:
            return (
                connection.execute(
                    select(tables.test_cases).where(tables.test_cases.c.id == case_id)
                )
                .mappings()
                .one()
            )

    def issue_row(self, issue_id: UUID) -> RowMapping | None:
        with self.engine.connect() as connection:
            return (
                connection.execute(select(tables.issues).where(tables.issues.c.id == issue_id))
                .mappings()
                .one_or_none()
            )


def runs_url(project_id: UUID, case_id: UUID) -> str:
    return f"/api/projects/{project_id}/npi/test-cases/{case_id}/runs"


def test_terminal_run_records_metrics_and_syncs_case(
    client: TestClient, isolated_test_run_database: str
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        project_id = scope.project()
        case_id = scope.test_case(project_id)
        headers = bearer_headers(client)

        created = client.post(
            runs_url(project_id, case_id),
            headers=headers,
            json={
                "status": "passed",
                "conditions": {"ambient_c": 40, "duty_cycle": "50%"},
                "metrics": [
                    {
                        "name": "leak_rate",
                        "value": 0.05,
                        "unit": "sccm",
                        "target": 0.1,
                        "verdict": "pass",
                    }
                ],
                "equipment": "Leak tester LT-3",
                "environment": "40C chamber",
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["run_number"] == 1
        assert body["status"] == "passed"
        assert body["executed_at"] is not None
        assert body["metrics"][0]["name"] == "leak_rate"

        case = scope.case_row(case_id)
        assert case["status"] == "passed"
        assert case["executed_by_user_id"] == scope.owner_id
    finally:
        scope.dispose()


def test_failed_run_auto_creates_and_reuses_test_failure_issue(
    client: TestClient, isolated_test_run_database: str
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        project_id = scope.project()
        case_id = scope.test_case(project_id, severity="critical")
        headers = bearer_headers(client)

        first = client.post(
            runs_url(project_id, case_id),
            headers=headers,
            json={"status": "failed", "result_notes": "Leak at 320h"},
        )
        assert first.status_code == 201
        issue_id = first.json()["related_issue_id"]
        assert issue_id is not None
        issue = scope.issue_row(UUID(issue_id))
        assert issue is not None
        assert issue["issue_type"] == "test_failure"
        assert issue["severity"] == "critical"
        assert issue["status"] == "open"

        second = client.post(
            runs_url(project_id, case_id),
            headers=headers,
            json={"status": "failed", "result_notes": "Leak again at 350h"},
        )
        assert second.status_code == 201
        assert second.json()["run_number"] == 2
        assert second.json()["related_issue_id"] == issue_id
    finally:
        scope.dispose()


def test_long_running_test_stays_in_progress_until_completed(
    client: TestClient, isolated_test_run_database: str
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        project_id = scope.project()
        case_id = scope.test_case(project_id)
        headers = bearer_headers(client)

        started = client.post(
            runs_url(project_id, case_id),
            headers=headers,
            json={
                "status": "in_progress",
                "expected_completion_at": "2026-09-15T08:00:00Z",
            },
        )
        assert started.status_code == 201
        run = started.json()
        assert run["executed_at"] is None
        assert run["expected_completion_at"].startswith("2026-09-15")
        assert scope.case_row(case_id)["status"] == "planned"

        completed = client.post(
            f"{runs_url(project_id, case_id)}/{run['id']}/complete",
            headers=headers,
            json={
                "status": "passed",
                "metrics": [{"name": "soak_hours", "value": 500, "unit": "h"}],
            },
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "passed"
        assert scope.case_row(case_id)["status"] == "passed"

        again = client.post(
            f"{runs_url(project_id, case_id)}/{run['id']}/complete",
            headers=headers,
            json={"status": "failed"},
        )
        assert again.status_code == 409
        assert again.json()["detail"]["code"] == "TEST_RUN_INVALID_STATE"

        listed = client.get(runs_url(project_id, case_id), headers=headers)
        assert [item["run_number"] for item in listed.json()["items"]] == [1]
    finally:
        scope.dispose()
