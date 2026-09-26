"""First-class Decision API tests (vNext V1-B4)."""

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
from sqlalchemy import Table, create_engine, select, text

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


@pytest.fixture(autouse=True)
def isolated_decision_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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

    def project(self, *, code: str, member_ids: tuple[UUID, ...]) -> UUID:
        workflow_id = self._insert(
            tables.workflows, {"code": f"WF-{code}", "name": f"Workflow {code}"}
        )
        project_id = self._insert(
            tables.projects,
            {
                "workflow_id": workflow_id,
                "owner_user_id": self.owner_id,
                "code": code,
                "name": f"Project {code}",
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

    def issue(self, project_id: UUID, *, title: str) -> UUID:
        return self._insert(
            tables.issues,
            {
                "project_id": project_id,
                "reported_by_user_id": self.owner_id,
                "title": title,
                "status": "open",
                "severity": "high",
            },
        )


def decisions_url(project_id: UUID, suffix: str = "") -> str:
    return f"/api/projects/{project_id}/decisions{suffix}"


def decision_basis(scope: Scope) -> dict[str, object]:
    return {
        "context": "合成阶段场景：需要完成一次技术方案落实。",
        "options": ["保持原方案", "采用替代方案"],
        "trade_offs": "比较实施工作与验证成本。",
        "rationale": "根据合成评估选择替代方案。",
        "consequence": "须完成跟进任务并保留实际执行凭据。",
        "evidence_refs": ["synthetic:decision-stage-evidence"],
        "approver_user_id": str(scope.owner_id),
    }


def test_decision_captures_context_options_evidence_and_lands_in_timeline(
    client: TestClient, isolated_decision_database: str
) -> None:
    scope = Scope(client, isolated_decision_database)
    try:
        engineer = scope.user("engineer", "engineer")
        project_id = scope.project(code="PRJ-DEC", member_ids=(engineer,))
        issue_id = scope.issue(project_id, title="Thermal drift")
        headers = bearer_headers(client)

        created = client.post(
            decisions_url(project_id),
            headers=headers,
            json={
                "decision_kind": "technical_choice",
                "title": "改用石墨导热垫",
                "context": "原硅胶垫在 55C 环境下导热不足。",
                "options": ["保持硅胶垫", "石墨导热垫", "增加风扇"],
                "trade_offs": "石墨垫成本 +0.8 元，但免去结构改动。",
                "outcome": "采用石墨导热垫，EVT-2 起生效。",
                "rationale": "三方案中唯一同时满足温升与交期。",
                "consequence": "BOM 单价上升 0.8 元；需要重测温升。",
                "evidence_refs": ["test_run:TR-118", "issue:thermal-drift"],
                "issue_id": str(issue_id),
                "owner_user_id": str(engineer),
                "approver_user_id": str(scope.owner_id),
                "follow_up_pending": True,
                "follow_up_note": "等待 EVT-2 温升重测确认",
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["options"] == ["保持硅胶垫", "石墨导热垫", "增加风扇"]
        assert body["evidence_refs"] == ["test_run:TR-118", "issue:thermal-drift"]
        assert body["follow_up_state"] == "pending"
        assert body["issue_id"] == str(issue_id)

        listed = client.get(decisions_url(project_id), headers=headers).json()["items"]
        assert [item["title"] for item in listed] == ["改用石墨导热垫"]

        with scope.engine.connect() as connection:
            events = (
                connection.execute(
                    text(
                        "SELECT payload->>'decision_kind' FROM cehub_event.events "
                        "WHERE event_type = 'DECISION_RECORDED' "
                        "AND entity_id = CAST(:decision_id AS uuid)"
                    ),
                    {"decision_id": body["id"]},
                )
                .scalars()
                .all()
            )
        assert events == ["technical_choice"]
    finally:
        scope.dispose()


def test_follow_up_completes_once_and_records_note(
    client: TestClient, isolated_decision_database: str
) -> None:
    scope = Scope(client, isolated_decision_database)
    try:
        project_id = scope.project(code="PRJ-FUP", member_ids=())
        headers = bearer_headers(client)
        task = client.post(
            f"/api/projects/{project_id}/tasks",
            headers=headers,
            json={"title": "落实技术选择", "assignee_user_id": str(scope.owner_id)},
        )
        assert task.status_code == 201, task.text
        task_id = UUID(task.json()["id"])
        created = client.post(
            decisions_url(project_id),
            headers=headers,
            json={
                **decision_basis(scope),
                "decision_kind": "technical_choice",
                "title": "采用替代方案",
                "outcome": "具名确认后落实并核对执行结果。",
                "owner_user_id": str(scope.owner_id),
                "follow_up_task_id": str(task_id),
                "follow_up_pending": True,
                "follow_up_note": "等待目标任务完成",
            },
        )
        assert created.status_code == 201, created.text
        decision_id = created.json()["id"]

        missing_receipt = client.post(
            decisions_url(project_id, f"/{decision_id}/follow-up"),
            headers=headers,
            json={"note": "单独备注不能证明完成"},
        )
        assert missing_receipt.status_code == 422
        transition = f"/api/projects/{project_id}/tasks/{task_id}/transitions"
        for command in (
            {"to_status": "in_progress"},
            {"to_status": "done", "completion_evidence_ref": "synthetic:decision-task-result"},
        ):
            changed = client.post(transition, headers=headers, json=command)
            assert changed.status_code == 200, changed.text
        with scope.engine.connect() as connection:
            receipt = connection.execute(
                select(tables.audit_log.c.id).where(
                    tables.audit_log.c.tenant_id == scope.tenant_id,
                    tables.audit_log.c.project_id == project_id,
                    tables.audit_log.c.entity_id == task_id,
                    tables.audit_log.c.action == "task.transition",
                    tables.audit_log.c.after_snapshot["status"].as_string() == "done",
                )
            ).scalar_one()
        done = client.post(
            decisions_url(project_id, f"/{decision_id}/follow-up"),
            headers=headers,
            json={"note": "目标任务已实际完成", "execution_audit_id": receipt},
        )
        assert done.status_code == 200
        assert done.json()["follow_up_state"] == "completed"

        again = client.post(
            decisions_url(project_id, f"/{decision_id}/follow-up"),
            headers=headers,
            json={"note": "重复完成", "execution_audit_id": receipt},
        )
        assert again.status_code == 409
        assert again.json()["detail"]["code"] == "DECISION_FOLLOW_UP_INVALID"
    finally:
        scope.dispose()


def test_scope_and_kind_are_enforced(client: TestClient, isolated_decision_database: str) -> None:
    scope = Scope(client, isolated_decision_database)
    try:
        project_id = scope.project(code="PRJ-A", member_ids=())
        other_project = scope.project(code="PRJ-B", member_ids=())
        foreign_issue = scope.issue(other_project, title="Foreign issue")
        headers = bearer_headers(client)

        cross_scope = client.post(
            decisions_url(project_id),
            headers=headers,
            json={
                **decision_basis(scope),
                "decision_kind": "technical_choice",
                "title": "跨项目引用",
                "outcome": "不应成功",
                "issue_id": str(foreign_issue),
            },
        )
        assert cross_scope.status_code == 404
        assert cross_scope.json()["detail"]["code"] == "DECISION_RELATED_OBJECT_NOT_FOUND"

        system_kind = client.post(
            decisions_url(project_id),
            headers=headers,
            json={
                "decision_kind": "gate_review",
                "title": "越权写系统类决策",
                "outcome": "不应成功",
            },
        )
        assert system_kind.status_code == 422

        legacy_ok = True
        with scope.engine.begin() as connection:
            connection.execute(
                tables.decisions.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": scope.tenant_id,
                    "project_id": project_id,
                    "decided_by_user_id": scope.owner_id,
                    "decision_kind": "gate_review",
                    "title": "Legacy gate decision",
                    "outcome": "approved",
                },
            )
        assert legacy_ok
    finally:
        scope.dispose()
