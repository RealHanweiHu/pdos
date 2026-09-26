"""My Work cross-project aggregation API tests (vNext V1-A2)."""

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
from sqlalchemy import Table, create_engine, select

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
def isolated_my_work_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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


def bearer_headers(
    client: TestClient, *, username: str, tenant_slug: str = "beepump"
) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": tenant_slug, "username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class Seeder:
    def __init__(self, database_url: str, tenant_id: UUID, owner_id: UUID) -> None:
        self.engine = create_engine(psycopg_database_url(database_url))
        self.tenant_id = tenant_id
        self.owner_id = owner_id

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

    def project(self, code: str, *, member_ids: tuple[UUID, ...] = ()) -> dict[str, UUID]:
        workflow_id = self._insert(
            tables.workflows, {"code": f"WF-{code}", "name": f"Workflow {code}"}
        )
        stage_id = self._insert(
            tables.stages,
            {"workflow_id": workflow_id, "code": "concept", "name": "Concept", "sequence": 1},
        )
        project_id = self._insert(
            tables.projects,
            {
                "workflow_id": workflow_id,
                "current_stage_id": stage_id,
                "owner_user_id": self.owner_id,
                "code": code,
                "name": f"Project {code}",
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
        return {"project_id": project_id, "workflow_id": workflow_id, "stage_id": stage_id}

    def task(
        self,
        project_id: UUID,
        *,
        assignee: UUID | None,
        title: str,
        status: str = "todo",
        due: date | None = None,
    ) -> UUID:
        return self._insert(
            tables.tasks,
            {
                "project_id": project_id,
                "assignee_user_id": assignee,
                "title": title,
                "status": status,
                "due_date": due,
                "completed_at": NOW if status == "done" else None,
            },
        )

    def issue(
        self,
        project_id: UUID,
        *,
        owner: UUID | None,
        title: str,
        status: str = "open",
        target: date | None = None,
    ) -> UUID:
        return self._insert(
            tables.issues,
            {
                "project_id": project_id,
                "owner_user_id": owner,
                "reported_by_user_id": self.owner_id,
                "title": title,
                "status": status,
                "target_date": target,
                "closed_at": NOW if status == "closed" else None,
            },
        )

    def risk(
        self,
        project_id: UUID,
        *,
        owner: UUID,
        title: str,
        status: str = "open",
        draft_state: str = "confirmed",
    ) -> UUID:
        return self._insert(
            tables.risks,
            {
                "project_id": project_id,
                "owner_user_id": owner,
                "title": title,
                "status": status,
                "draft_state": draft_state,
                "origin_key": f"candidate:{uuid4()}" if draft_state != "confirmed" else None,
                "closed_at": NOW if status == "closed" else None,
            },
        )

    def capa(self, project_id: UUID, *, owner: UUID, due: date) -> UUID:
        complaint_id = self._insert(
            tables.complaints,
            {
                "project_id": project_id,
                "reported_by_user_id": self.owner_id,
                "owner_user_id": self.owner_id,
                "code": f"CMP-{uuid4().hex[:8]}",
                "title": "Field failure",
                "description": "Pump stops under load",
                "source": "customer",
                "severity": "high",
                "occurred_at": NOW,
                "reported_at": NOW,
            },
        )
        ncr_id = self._insert(
            tables.nonconformance_reports,
            {
                "project_id": project_id,
                "complaint_id": complaint_id,
                "owner_user_id": self.owner_id,
                "created_by_user_id": self.owner_id,
                "code": f"NCR-{uuid4().hex[:8]}",
                "nonconformity": "Motor overheating",
                "requirement_reference": "SPEC-42",
                "severity": "high",
                "target_date": due,
            },
        )
        return self._insert(
            tables.capa_actions,
            {
                "project_id": project_id,
                "ncr_id": ncr_id,
                "owner_user_id": owner,
                "created_by_user_id": self.owner_id,
                "action_type": "corrective",
                "description": "Replace thermal pad supplier",
                "due_date": due,
            },
        )

    def gate_with_pending_round(self, project_id: UUID, stage_id: UUID, *, code: str) -> UUID:
        gate_id = self._insert(
            tables.gates,
            {
                "project_id": project_id,
                "stage_id": stage_id,
                "code": code,
                "name": f"Gate {code}",
                "status": "reviewing",
                "review_due_at": NOW,
            },
        )
        round_id = self._insert(
            tables.gate_signoff_rounds,
            {
                "project_id": project_id,
                "gate_id": gate_id,
                "round_number": 1,
                "policy_version": "signoff-policy-v1",
                "requirements": {
                    "product": "required",
                    "engineering": "required",
                    "quality": "required",
                },
                "opened_by_user_id": self.owner_id,
            },
        )
        for slot in ("product", "engineering", "quality"):
            self._insert(
                tables.gate_signoffs,
                {
                    "project_id": project_id,
                    "gate_id": gate_id,
                    "round_id": round_id,
                    "slot": slot,
                    "requirement": "required",
                },
            )
        return gate_id

    def finding(self, project_id: UUID, *, title: str) -> UUID:
        subscription_id = self._insert(
            tables.agent_subscriptions,
            {"project_id": project_id, "agent_key": "project_intelligence"},
        )
        run_id = self._insert(
            tables.agent_runs,
            {
                "project_id": project_id,
                "subscription_id": subscription_id,
                "agent_key": "project_intelligence",
                "status": "succeeded",
                "window_started_at": NOW,
                "window_ended_at": NOW,
                "first_event_row_id": 1,
                "last_event_row_id": 1,
                "event_count": 1,
                "event_row_ids": [1],
                "started_at": NOW,
                "completed_at": NOW,
            },
        )
        invocation_id = self._insert(
            tables.model_invocations,
            {
                "project_id": project_id,
                "run_id": run_id,
                "agent_key": "project_intelligence",
                "prompt_version": "v1",
                "provider": "minimax",
                "model": "fake-model",
                "protocol": "openai-compatible",
                "status": "succeeded",
            },
        )
        return self._insert(
            tables.findings,
            {
                "project_id": project_id,
                "run_id": run_id,
                "model_invocation_id": invocation_id,
                "agent_key": "project_intelligence",
                "finding_type": "risk_suggestion",
                "origin_key": f"origin-{uuid4().hex[:12]}",
                "title": title,
                "summary": "Evidence supports registering a risk.",
                "proposed_payload": {"title": title},
                "evidence_event_ids": [1],
                "confidence_basis_points": 8000,
                "preflight_version": "finding-preflight-v2",
            },
        )


def bootstrap(client: TestClient, database_url: str) -> Seeder:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    return Seeder(
        database_url,
        tenant_id=UUID(setup["tenant"]["id"]),
        owner_id=UUID(setup["user"]["id"]),
    )


def get_my_work(
    client: TestClient, headers: dict[str, str], *, limit: int | None = None
) -> httpx2.Response:
    suffix = f"?limit={limit}" if limit is not None else ""
    return client.get(f"/api/me/work{suffix}", headers=headers)


def test_aggregates_only_own_items_across_projects_sorted_by_due(
    client: TestClient, isolated_my_work_database: str
) -> None:
    seeder = bootstrap(client, isolated_my_work_database)
    try:
        engineer = seeder.user("engineer", "engineer")
        colleague = seeder.user("colleague", "engineer")
        alpha = seeder.project("ALPHA", member_ids=(engineer, colleague))
        beta = seeder.project("BETA", member_ids=(engineer,))

        seeder.task(alpha["project_id"], assignee=engineer, title="Later", due=date(2026, 9, 10))
        seeder.task(beta["project_id"], assignee=engineer, title="Sooner", due=date(2026, 9, 1))
        seeder.task(alpha["project_id"], assignee=engineer, title="No due date", due=None)
        seeder.task(alpha["project_id"], assignee=engineer, title="Done", status="done")
        seeder.task(alpha["project_id"], assignee=colleague, title="Not mine")
        seeder.issue(beta["project_id"], owner=engineer, title="Thermal drift")
        seeder.issue(alpha["project_id"], owner=engineer, title="Closed issue", status="closed")
        seeder.issue(alpha["project_id"], owner=None, title="Unassigned")
        seeder.risk(alpha["project_id"], owner=engineer, title="Supplier slip")
        seeder.finding(beta["project_id"], title="Register delivery risk")

        body = get_my_work(client, bearer_headers(client, username="engineer")).json()

        assert [task["title"] for task in body["tasks"]] == ["Sooner", "Later", "No due date"]
        assert {task["project"]["code"] for task in body["tasks"]} == {"ALPHA", "BETA"}
        assert [issue["title"] for issue in body["issues"]] == ["Thermal drift"]
        assert [risk["title"] for risk in body["risks"]] == ["Supplier slip"]
        assert body["capa_actions"] == []
        assert [item["title"] for item in body["findings"]] == ["Register delivery risk"]
        assert body["counts"] == {
            "tasks": 3,
            "issues": 1,
            "risks": 1,
            "capa_actions": 0,
            "gate_signoffs": 0,
            "findings": 1,
            "risk_followup_actions": 0,
            "id_design_actions": 0,
            "cross_schedule_approvals": 0,
            "change_execution_confirmations": 0,
            "cost_freeze_approvals": 0,
            "task_takeover_actions": 0,
        }
    finally:
        seeder.dispose()


def test_membership_boundary_hides_assigned_items_in_non_member_projects(
    client: TestClient, isolated_my_work_database: str
) -> None:
    seeder = bootstrap(client, isolated_my_work_database)
    try:
        engineer = seeder.user("engineer", "engineer")
        member_scope = seeder.project("MEMBER", member_ids=(engineer,))
        outsider_scope = seeder.project("OUTSIDE")
        seeder.task(member_scope["project_id"], assignee=engineer, title="Visible")
        seeder.task(outsider_scope["project_id"], assignee=engineer, title="Hidden")
        seeder.finding(outsider_scope["project_id"], title="Hidden finding")

        body = get_my_work(client, bearer_headers(client, username="engineer")).json()
        assert [task["title"] for task in body["tasks"]] == ["Visible"]
        assert body["findings"] == []

        seeder.task(outsider_scope["project_id"], assignee=seeder.owner_id, title="Owner task")
        owner_body = get_my_work(client, bearer_headers(client, username="owner")).json()
        assert [task["title"] for task in owner_body["tasks"]] == ["Owner task"]
    finally:
        seeder.dispose()


def test_risk_candidates_enter_my_work_only_while_confirmed(
    client: TestClient, isolated_my_work_database: str
) -> None:
    seeder = bootstrap(client, isolated_my_work_database)
    try:
        engineer = seeder.user("engineer", "engineer")
        project_id = seeder.project("RISKS", member_ids=(engineer,))["project_id"]
        confirmed_ids = {
            str(seeder.risk(project_id, owner=engineer, title=status, status=status))
            for status in ("open", "mitigating", "watching")
        }
        seeder.risk(project_id, owner=engineer, title="Closed", status="closed")
        draft_id = seeder.risk(
            project_id, owner=engineer, title="Awaiting confirmation", draft_state="draft"
        )
        seeder.risk(project_id, owner=engineer, title="Source recovered", draft_state="cleared")
        headers = bearer_headers(client, username="engineer")

        def assert_visible(expected_ids: set[str]) -> None:
            response = get_my_work(client, headers)
            assert response.status_code == 200
            body = response.json()
            assert {risk["id"] for risk in body["risks"]} == expected_ids
            assert body["counts"]["risks"] == len(expected_ids)
            limited = get_my_work(client, headers, limit=2)
            assert limited.status_code == 200
            assert len(limited.json()["risks"]) == 2
            assert {risk["id"] for risk in limited.json()["risks"]} <= expected_ids
            assert limited.json()["counts"]["risks"] == len(expected_ids)

        def assert_candidate_state(expected: str) -> None:
            with seeder.engine.connect() as connection:
                assert (
                    connection.scalar(
                        select(tables.risks.c.draft_state).where(
                            tables.risks.c.tenant_id == seeder.tenant_id,
                            tables.risks.c.project_id == project_id,
                            tables.risks.c.id == draft_id,
                        )
                    )
                    == expected
                )

        assert_candidate_state("draft")
        assert_visible(confirmed_ids)

        candidate_url = f"/api/projects/{project_id}/risks/{draft_id}"
        confirmed = client.post(f"{candidate_url}/confirm", headers=headers)
        assert confirmed.status_code == 200
        assert_candidate_state("confirmed")
        assert_visible(confirmed_ids | {str(draft_id)})

        unconfirmed = client.post(f"{candidate_url}/unconfirm", headers=headers)
        assert unconfirmed.status_code == 200
        assert_candidate_state("draft")
        assert_visible(confirmed_ids)
    finally:
        seeder.dispose()


def test_cross_tenant_isolation(client: TestClient, isolated_my_work_database: str) -> None:
    seeder = bootstrap(client, isolated_my_work_database)
    try:
        engineer = seeder.user("engineer", "engineer")
        scope = seeder.project("HOME", member_ids=(engineer,))
        seeder.task(scope["project_id"], assignee=engineer, title="Mine")

        other_tenant_id = uuid4()
        with seeder.engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": other_tenant_id, "slug": "rival", "name": "Rival Tenant"},
            )
        rival = Seeder(isolated_my_work_database, other_tenant_id, uuid4())
        rival_owner = rival.user("owner", "owner")
        rival.owner_id = rival_owner
        rival_engineer = rival.user("engineer", "engineer")
        rival_scope = rival.project("RIVAL", member_ids=(rival_engineer,))
        rival.task(rival_scope["project_id"], assignee=rival_engineer, title="Rival task")
        rival.dispose()

        body = get_my_work(client, bearer_headers(client, username="engineer")).json()
        assert [task["title"] for task in body["tasks"]] == ["Mine"]
        assert body["counts"]["tasks"] == 1
    finally:
        seeder.dispose()


def test_gate_signoff_slots_follow_role_and_capa_follows_owner(
    client: TestClient, isolated_my_work_database: str
) -> None:
    seeder = bootstrap(client, isolated_my_work_database)
    try:
        engineer = seeder.user("engineer", "engineer")
        quality = seeder.user("quality", "quality")
        scope = seeder.project("GATE", member_ids=(engineer, quality))
        seeder.gate_with_pending_round(scope["project_id"], scope["stage_id"], code="dvt-exit")
        seeder.capa(scope["project_id"], owner=quality, due=date(2026, 9, 5))

        engineer_body = get_my_work(client, bearer_headers(client, username="engineer")).json()
        assert [item["slot"] for item in engineer_body["gate_signoffs"]] == ["engineering"]
        assert engineer_body["capa_actions"] == []

        quality_body = get_my_work(client, bearer_headers(client, username="quality")).json()
        assert [item["slot"] for item in quality_body["gate_signoffs"]] == ["quality"]
        assert [item["action_type"] for item in quality_body["capa_actions"]] == ["corrective"]
        assert quality_body["capa_actions"][0]["due_date"] == "2026-09-05"

        owner_body = get_my_work(client, bearer_headers(client, username="owner")).json()
        assert sorted(item["slot"] for item in owner_body["gate_signoffs"]) == [
            "engineering",
            "product",
            "quality",
        ]
    finally:
        seeder.dispose()


def test_external_roles_are_denied(client: TestClient, isolated_my_work_database: str) -> None:
    seeder = bootstrap(client, isolated_my_work_database)
    try:
        seeder.user("vendor", "supplier")
        seeder.user("client", "customer")
        for username in ("vendor", "client"):
            response = get_my_work(client, bearer_headers(client, username=username))
            assert response.status_code == 403
            assert response.json()["detail"]["code"] == "MY_WORK_FORBIDDEN"
    finally:
        seeder.dispose()


def test_limit_caps_items_while_counts_stay_full(
    client: TestClient, isolated_my_work_database: str
) -> None:
    seeder = bootstrap(client, isolated_my_work_database)
    try:
        engineer = seeder.user("engineer", "engineer")
        scope = seeder.project("LIMIT", member_ids=(engineer,))
        for day in (1, 2, 3):
            seeder.task(
                scope["project_id"],
                assignee=engineer,
                title=f"Task {day}",
                due=date(2026, 9, day),
            )

        body = get_my_work(client, bearer_headers(client, username="engineer"), limit=2).json()
        assert [task["title"] for task in body["tasks"]] == ["Task 1", "Task 2"]
        assert body["counts"]["tasks"] == 3

        assert (
            get_my_work(client, bearer_headers(client, username="engineer"), limit=500).status_code
            == 422
        )
    finally:
        seeder.dispose()
