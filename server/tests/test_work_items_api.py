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
from sqlalchemy import create_engine, func, select, text

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
def isolated_work_item_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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


def bearer_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": "owner", "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def seed_project(database_url: str, *, tenant_id: UUID, owner_id: UUID) -> dict[str, UUID]:
    workflow_id = uuid4()
    concept_id = uuid4()
    planning_id = uuid4()
    project_id = uuid4()
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.workflows.insert(),
                {
                    "id": workflow_id,
                    "tenant_id": tenant_id,
                    "code": "WORK-ITEM-WF",
                    "name": "Work item workflow",
                },
            )
            connection.execute(
                tables.stages.insert(),
                [
                    {
                        "id": concept_id,
                        "tenant_id": tenant_id,
                        "workflow_id": workflow_id,
                        "code": "concept",
                        "name": "Concept",
                        "sequence": 1,
                    },
                    {
                        "id": planning_id,
                        "tenant_id": tenant_id,
                        "workflow_id": workflow_id,
                        "code": "planning",
                        "name": "Planning",
                        "sequence": 2,
                    },
                ],
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": project_id,
                    "tenant_id": tenant_id,
                    "workflow_id": workflow_id,
                    "current_stage_id": concept_id,
                    "owner_user_id": owner_id,
                    "code": "PRJ-WORK",
                    "name": "Work item project",
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
    finally:
        engine.dispose()
    return {
        "project_id": project_id,
        "workflow_id": workflow_id,
        "concept_id": concept_id,
        "planning_id": planning_id,
    }


def post_task(
    client: TestClient,
    headers: dict[str, str],
    project_id: UUID,
    payload: dict[str, Any],
) -> Any:
    return client.post(f"/api/projects/{project_id}/tasks", headers=headers, json=payload)


def test_task_dependencies_wait_without_becoming_blocked(
    client: TestClient,
    isolated_work_item_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    owner_id = UUID(setup["user"]["id"])
    scope = seed_project(isolated_work_item_database, tenant_id=tenant_id, owner_id=owner_id)
    headers = bearer_headers(client)
    project_id = scope["project_id"]

    foundation_response = post_task(
        client,
        headers,
        project_id,
        {
            "title": "Freeze product requirements",
            "stage_id": str(scope["concept_id"]),
            "priority": "high",
        },
    )
    assert foundation_response.status_code == 201
    foundation = foundation_response.json()

    dependent_response = post_task(
        client,
        headers,
        project_id,
        {
            "title": "Start detailed design",
            "stage_id": str(scope["planning_id"]),
            "dependency_task_ids": [foundation["id"]],
        },
    )
    assert dependent_response.status_code == 201
    dependent = dependent_response.json()
    assert dependent["status"] == "todo"
    assert dependent["readiness"] == "waiting"
    assert dependent["unresolved_dependency_ids"] == [foundation["id"]]

    dependent_transition = f"/api/projects/{project_id}/tasks/{dependent['id']}/transitions"
    waiting = client.post(
        dependent_transition,
        headers=headers,
        json={"to_status": "in_progress"},
    )
    assert waiting.status_code == 409
    assert waiting.json()["detail"]["code"] == "TASK_DEPENDENCIES_INCOMPLETE"
    unchanged = client.get(
        f"/api/projects/{project_id}/tasks/{dependent['id']}", headers=headers
    ).json()
    assert unchanged["status"] == "todo"
    assert unchanged["readiness"] == "waiting"

    foundation_transition = f"/api/projects/{project_id}/tasks/{foundation['id']}/transitions"
    assert (
        client.post(
            foundation_transition,
            headers=headers,
            json={"to_status": "in_progress"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            foundation_transition,
            headers=headers,
            json={"to_status": "done"},
        ).status_code
        == 200
    )
    ready = client.get(
        f"/api/projects/{project_id}/tasks/{dependent['id']}", headers=headers
    ).json()
    assert ready["status"] == "todo"
    assert ready["readiness"] == "ready"
    assert ready["unresolved_dependency_ids"] == []

    assert (
        client.post(
            dependent_transition,
            headers=headers,
            json={"to_status": "in_progress"},
        ).status_code
        == 200
    )
    blocked_without_reason = client.post(
        dependent_transition,
        headers=headers,
        json={"to_status": "blocked"},
    )
    assert blocked_without_reason.status_code == 422
    blocked = client.post(
        dependent_transition,
        headers=headers,
        json={"to_status": "blocked", "blocked_reason": "Motor sample is delayed"},
    )
    assert blocked.status_code == 200
    assert blocked.json()["readiness"] == "blocked"
    assert blocked.json()["blocked_reason"] == "Motor sample is delayed"
    unblocked = client.post(
        dependent_transition,
        headers=headers,
        json={"to_status": "todo"},
    )
    assert unblocked.status_code == 200
    assert unblocked.json()["blocked_reason"] is None

    cycle_seed = post_task(
        client,
        headers,
        project_id,
        {"title": "Cycle seed", "dependency_task_ids": [dependent["id"]]},
    ).json()
    cycle = client.patch(
        f"/api/projects/{project_id}/tasks/{dependent['id']}",
        headers=headers,
        json={"dependency_task_ids": [cycle_seed["id"]]},
    )
    assert cycle.status_code == 409
    assert cycle.json()["detail"]["code"] == "TASK_DEPENDENCY_CYCLE"

    listed = client.get(f"/api/projects/{project_id}/tasks", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 3

    engine = create_engine(psycopg_database_url(isolated_work_item_database))
    try:
        with engine.connect() as connection:
            assert connection.scalar(
                select(func.count())
                .select_from(tables.events)
                .where(
                    tables.events.c.event_type.in_(
                        {"TASK_CREATED", "TASK_UPDATED", "TASK_STATUS_CHANGED"}
                    )
                )
            ) == connection.scalar(
                select(func.count())
                .select_from(tables.audit_log)
                .where(
                    tables.audit_log.c.action.in_({"task.create", "task.update", "task.transition"})
                )
            )
    finally:
        engine.dispose()
