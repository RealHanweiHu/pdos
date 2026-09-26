"""Three-tier authorization boundary tests (vNext V1-C1, D32).

Free zone: rule scans write drafts directly and drafts never leak into truth
lists. Confirm zone: single-action batch confirm plus a reversible unconfirm,
both leaving audit evidence. Hard-gate semantics for findings stay covered by
test_ai_api / test_finding_schema.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Table, create_engine, select

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
YESTERDAY = date(2026, 8, 25)


@pytest.fixture(autouse=True)
def isolated_tier_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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
        workflow_id = self._insert(tables.workflows, {"code": "WF-3T", "name": "Workflow"})
        project_id = self._insert(
            tables.projects,
            {
                "workflow_id": workflow_id,
                "owner_user_id": self.owner_id,
                "code": "PRJ-3T",
                "name": "Tier project",
                "status": "active",
            },
        )
        self._insert(
            tables.project_members,
            {"project_id": project_id, "user_id": self.owner_id, "added_by_user_id": self.owner_id},
        )
        return project_id

    def overdue_task(self, project_id: UUID, *, title: str) -> UUID:
        return self._insert(
            tables.tasks,
            {
                "project_id": project_id,
                "title": title,
                "status": "in_progress",
                "priority": "high",
                "due_date": YESTERDAY,
            },
        )

    def set_task_status(self, task_id: UUID, *, status: str, completed: datetime | None) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                tables.tasks.update()
                .where(tables.tasks.c.id == task_id)
                .values(status=status, completed_at=completed)
            )

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


def scan(client: TestClient, headers: dict[str, str], project_id: UUID) -> httpx2.Response:
    return client.post(f"/api/projects/{project_id}/risk-candidates/scan", headers=headers)


def risk_titles(client: TestClient, headers: dict[str, str], project_id: UUID) -> list[str]:
    response = client.get(f"/api/projects/{project_id}/risks", headers=headers)
    assert response.status_code == 200
    return [item["title"] for item in response.json()["items"]]


def test_batch_confirm_reports_per_item_outcome(
    client: TestClient, isolated_tier_database: str
) -> None:
    scope = Scope(client, isolated_tier_database)
    try:
        headers = bearer_headers(client)
        project_id = scope.project()
        scope.overdue_task(project_id, title="Tooling late")
        scope.overdue_task(project_id, title="Firmware late")
        scanned = scan(client, headers, project_id)
        assert scanned.status_code == 200
        candidate_ids = [item["id"] for item in scanned.json()["items"]]
        assert len(candidate_ids) == 2

        first = client.post(
            f"/api/projects/{project_id}/risks/{candidate_ids[0]}/confirm", headers=headers
        )
        assert first.status_code == 200

        missing_id = str(uuid4())
        response = client.post(
            f"/api/projects/{project_id}/risk-candidates/confirm-batch",
            headers=headers,
            json={"risk_ids": [*candidate_ids, missing_id]},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["confirmed"] == [candidate_ids[1]]
        assert body["already"] == [candidate_ids[0]]
        assert body["not_found"] == [missing_id]
        assert sorted(risk_titles(client, headers, project_id)) == [
            "任务逾期：Firmware late",
            "任务逾期：Tooling late",
        ]
    finally:
        scope.dispose()


def test_unconfirm_returns_candidate_to_draft_with_audit(
    client: TestClient, isolated_tier_database: str
) -> None:
    scope = Scope(client, isolated_tier_database)
    try:
        headers = bearer_headers(client)
        project_id = scope.project()
        scope.overdue_task(project_id, title="Injection mold late")
        scanned = scan(client, headers, project_id)
        candidate_id = scanned.json()["items"][0]["id"]

        confirmed = client.post(
            f"/api/projects/{project_id}/risks/{candidate_id}/confirm", headers=headers
        )
        assert confirmed.status_code == 200
        assert risk_titles(client, headers, project_id) == ["任务逾期：Injection mold late"]

        undone = client.post(
            f"/api/projects/{project_id}/risks/{candidate_id}/unconfirm", headers=headers
        )
        assert undone.status_code == 200
        assert risk_titles(client, headers, project_id) == []
        drafts = client.get(f"/api/projects/{project_id}/risk-candidates", headers=headers)
        assert [item["id"] for item in drafts.json()["items"]] == [candidate_id]

        reconfirmed = client.post(
            f"/api/projects/{project_id}/risks/{candidate_id}/confirm", headers=headers
        )
        assert reconfirmed.status_code == 200
        assert risk_titles(client, headers, project_id) == ["任务逾期：Injection mold late"]

        actions = scope.audit_actions()
        assert actions.count("risk.candidate_confirm") == 2
        assert actions.count("risk.candidate_unconfirm") == 1
    finally:
        scope.dispose()


def test_unconfirm_rejects_manual_risks_and_repeat_undo(
    client: TestClient, isolated_tier_database: str
) -> None:
    scope = Scope(client, isolated_tier_database)
    try:
        headers = bearer_headers(client)
        project_id = scope.project()
        manual = client.post(
            f"/api/projects/{project_id}/risks",
            headers=headers,
            json={"title": "Manual supply risk", "likelihood": 2, "impact": 3},
        )
        assert manual.status_code == 201
        manual_id = manual.json()["id"]
        rejected = client.post(
            f"/api/projects/{project_id}/risks/{manual_id}/unconfirm", headers=headers
        )
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "RISK_NOT_CONFIRMED"

        scope.overdue_task(project_id, title="Pump housing late")
        candidate_id = scan(client, headers, project_id).json()["items"][0]["id"]
        repeat = client.post(
            f"/api/projects/{project_id}/risks/{candidate_id}/unconfirm", headers=headers
        )
        assert repeat.status_code == 409
        assert repeat.json()["detail"]["code"] == "RISK_NOT_CONFIRMED"
    finally:
        scope.dispose()


def test_dismissed_candidate_stays_hidden_until_reoccurrence(
    client: TestClient, isolated_tier_database: str
) -> None:
    scope = Scope(client, isolated_tier_database)
    try:
        headers = bearer_headers(client)
        project_id = scope.project()
        task_id = scope.overdue_task(project_id, title="Motor vendor late")
        candidate_id = scan(client, headers, project_id).json()["items"][0]["id"]

        dismissed = client.post(
            f"/api/projects/{project_id}/risks/{candidate_id}/dismiss", headers=headers
        )
        assert dismissed.status_code == 200
        assert risk_titles(client, headers, project_id) == []
        drafts = client.get(f"/api/projects/{project_id}/risk-candidates", headers=headers)
        assert drafts.json()["items"] == []

        persisting = scan(client, headers, project_id).json()
        assert persisting["reactivated"] == 0
        assert persisting["items"] == []

        from datetime import UTC, datetime

        scope.set_task_status(task_id, status="done", completed=datetime.now(UTC))
        recovered = scan(client, headers, project_id).json()
        assert recovered["items"] == []

        scope.set_task_status(task_id, status="in_progress", completed=None)
        resurfaced = scan(client, headers, project_id).json()
        assert resurfaced["reactivated"] == 1
        assert [item["id"] for item in resurfaced["items"]] == [candidate_id]

        actions = scope.audit_actions()
        assert actions.count("risk.candidate_dismiss") == 1
        assert actions.count("risk.candidate_reactivate") == 1
    finally:
        scope.dispose()


def test_dismiss_rejects_confirmed_and_manual_risks(
    client: TestClient, isolated_tier_database: str
) -> None:
    scope = Scope(client, isolated_tier_database)
    try:
        headers = bearer_headers(client)
        project_id = scope.project()
        scope.overdue_task(project_id, title="Battery cell late")
        candidate_id = scan(client, headers, project_id).json()["items"][0]["id"]
        assert (
            client.post(
                f"/api/projects/{project_id}/risks/{candidate_id}/confirm", headers=headers
            ).status_code
            == 200
        )
        rejected = client.post(
            f"/api/projects/{project_id}/risks/{candidate_id}/dismiss", headers=headers
        )
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "RISK_NOT_CONFIRMED"
    finally:
        scope.dispose()
