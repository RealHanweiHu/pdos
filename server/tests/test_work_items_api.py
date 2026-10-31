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

from app.auth.passwords import PasswordService
from app.auth.roles import Role
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


def bearer_headers(client: TestClient, *, username: str = "owner") -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def seed_project(
    database_url: str,
    *,
    tenant_id: UUID,
    owner_id: UUID,
    label: str = "WORK",
) -> dict[str, UUID]:
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
                    "code": f"WORK-ITEM-{label}",
                    "name": f"Work item workflow {label}",
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
                    "code": f"PRJ-{label}",
                    "name": f"Work item project {label}",
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


def seed_member(
    database_url: str,
    *,
    tenant_id: UUID,
    project_id: UUID,
    added_by_user_id: UUID,
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
                    "display_name": username.replace("_", " ").title(),
                    "role": role,
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
                    "added_by_user_id": added_by_user_id,
                },
            )
    finally:
        engine.dispose()
    return user_id


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


def test_issue_and_risk_lifecycles_are_explicit_and_audited(
    client: TestClient,
    isolated_work_item_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    owner_id = UUID(setup["user"]["id"])
    scope = seed_project(isolated_work_item_database, tenant_id=tenant_id, owner_id=owner_id)
    headers = bearer_headers(client)
    project_id = scope["project_id"]

    issue_response = client.post(
        f"/api/projects/{project_id}/issues",
        headers=headers,
        json={
            "stage_id": str(scope["concept_id"]),
            "title": "Pump overheats during endurance test",
            "description": "Housing exceeds the temperature limit.",
            "severity": "critical",
            "target_date": "2026-09-15",
        },
    )
    assert issue_response.status_code == 201
    issue = issue_response.json()
    assert issue["status"] == "open"
    assert issue["reported_by_user_id"] == str(owner_id)
    issue_patch = client.patch(
        f"/api/projects/{project_id}/issues/{issue['id']}",
        headers=headers,
        json={"root_cause": "Insufficient thermal path"},
    )
    assert issue_patch.status_code == 200
    assert issue_patch.json()["root_cause"] == "Insufficient thermal path"
    issue_transition = f"/api/projects/{project_id}/issues/{issue['id']}/transitions"
    skipped_issue_state = client.post(
        issue_transition,
        headers=headers,
        json={"to_status": "action"},
    )
    assert skipped_issue_state.status_code == 409
    assert skipped_issue_state.json()["detail"]["code"] == "ISSUE_INVALID_TRANSITION"
    for next_status in ("analysis", "action", "verification", "closed"):
        response = client.post(
            issue_transition,
            headers=headers,
            json={"to_status": next_status},
        )
        assert response.status_code == 200
        assert response.json()["status"] == next_status
    assert response.json()["closed_at"] is not None
    assert (
        client.patch(
            f"/api/projects/{project_id}/issues/{issue['id']}",
            headers=headers,
            json={"resolution": "Change heat sink material"},
        ).status_code
        == 409
    )

    risk_response = client.post(
        f"/api/projects/{project_id}/risks",
        headers=headers,
        json={
            "title": "Motor supplier capacity shortfall",
            "likelihood": 4,
            "impact": 5,
            "mitigation_plan": "Qualify a second source.",
        },
    )
    assert risk_response.status_code == 201
    risk = risk_response.json()
    assert risk["status"] == "open"
    assert risk["score"] == 20
    risk_patch = client.patch(
        f"/api/projects/{project_id}/risks/{risk['id']}",
        headers=headers,
        json={"contingency_plan": "Reserve expedited freight capacity."},
    )
    assert risk_patch.status_code == 200
    assert risk_patch.json()["contingency_plan"] == "Reserve expedited freight capacity."
    risk_transition = f"/api/projects/{project_id}/risks/{risk['id']}/transitions"
    assert (
        client.post(
            risk_transition,
            headers=headers,
            json={"to_status": "closed"},
        ).status_code
        == 409
    )
    for next_status in ("mitigating", "watching", "mitigating", "closed"):
        response = client.post(
            risk_transition,
            headers=headers,
            json={"to_status": next_status},
        )
        assert response.status_code == 200
        assert response.json()["status"] == next_status
        assert response.json()["score"] == 20
    assert response.json()["closed_at"] is not None

    assert (
        len(client.get(f"/api/projects/{project_id}/issues", headers=headers).json()["items"]) == 1
    )
    assert (
        len(client.get(f"/api/projects/{project_id}/risks", headers=headers).json()["items"]) == 1
    )

    engine = create_engine(psycopg_database_url(isolated_work_item_database))
    try:
        with engine.connect() as connection:
            issue_created = connection.execute(
                select(tables.events.c.payload).where(tables.events.c.event_type == "ISSUE_CREATED")
            ).scalar_one()
            assert issue_created == {"issue_id": issue["id"], "severity": "critical"}
            work_item_events = connection.scalar(
                select(func.count())
                .select_from(tables.events)
                .where(
                    tables.events.c.event_type.in_(
                        {
                            "ISSUE_CREATED",
                            "ISSUE_UPDATED",
                            "ISSUE_STATUS_CHANGED",
                            "RISK_CREATED",
                            "RISK_UPDATED",
                            "RISK_STATUS_CHANGED",
                        }
                    )
                )
            )
            work_item_audits = connection.scalar(
                select(func.count())
                .select_from(tables.audit_log)
                .where(
                    tables.audit_log.c.action.in_(
                        {
                            "issue.create",
                            "issue.update",
                            "issue.transition",
                            "risk.create",
                            "risk.update",
                            "risk.transition",
                        }
                    )
                )
            )
            assert work_item_events == work_item_audits
    finally:
        engine.dispose()


def test_work_items_fail_closed_for_roles_scope_and_failed_transactions(
    client: TestClient,
    isolated_work_item_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    owner_id = UUID(setup["user"]["id"])
    scope = seed_project(
        isolated_work_item_database,
        tenant_id=tenant_id,
        owner_id=owner_id,
        label="PRIMARY",
    )
    other_scope = seed_project(
        isolated_work_item_database,
        tenant_id=tenant_id,
        owner_id=owner_id,
        label="OTHER",
    )
    engineer_id = seed_member(
        isolated_work_item_database,
        tenant_id=tenant_id,
        project_id=scope["project_id"],
        added_by_user_id=owner_id,
        username="engineer",
        role=Role.ENGINEER,
    )
    supplier_id = seed_member(
        isolated_work_item_database,
        tenant_id=tenant_id,
        project_id=scope["project_id"],
        added_by_user_id=owner_id,
        username="supplier",
        role=Role.SUPPLIER,
    )
    owner_headers = bearer_headers(client)
    engineer_headers = bearer_headers(client, username="engineer")
    supplier_headers = bearer_headers(client, username="supplier")
    project_id = scope["project_id"]

    engineer_task = post_task(
        client,
        engineer_headers,
        project_id,
        {"title": "Engineer-owned task", "assignee_user_id": str(engineer_id)},
    )
    assert engineer_task.status_code == 201
    assert (
        client.get(f"/api/projects/{project_id}/tasks", headers=engineer_headers).status_code == 200
    )
    assert (
        client.get(f"/api/projects/{project_id}/tasks", headers=supplier_headers).status_code == 403
    )
    assert (
        post_task(
            client,
            supplier_headers,
            project_id,
            {"title": "Supplier must not create work"},
        ).status_code
        == 403
    )

    external_assignee = post_task(
        client,
        owner_headers,
        project_id,
        {"title": "Invalid external assignment", "assignee_user_id": str(supplier_id)},
    )
    assert external_assignee.status_code == 404
    assert external_assignee.json()["detail"]["code"] == "TASK_RELATED_OBJECT_NOT_FOUND"

    other_task = post_task(
        client,
        owner_headers,
        other_scope["project_id"],
        {"title": "Other project dependency"},
    ).json()
    engine = create_engine(psycopg_database_url(isolated_work_item_database))
    try:
        with engine.connect() as connection:
            baseline = {
                "tasks": connection.scalar(select(func.count()).select_from(tables.tasks)),
                "issues": connection.scalar(select(func.count()).select_from(tables.issues)),
                "risks": connection.scalar(select(func.count()).select_from(tables.risks)),
                "events": connection.scalar(select(func.count()).select_from(tables.events)),
                "audits": connection.scalar(select(func.count()).select_from(tables.audit_log)),
            }

        cross_project_dependency = post_task(
            client,
            owner_headers,
            project_id,
            {
                "title": "Must roll back completely",
                "dependency_task_ids": [other_task["id"]],
            },
        )
        assert cross_project_dependency.status_code == 404
        assert cross_project_dependency.json()["detail"]["code"] == "TASK_RELATED_OBJECT_NOT_FOUND"

        cross_workflow_stage = client.post(
            f"/api/projects/{project_id}/issues",
            headers=owner_headers,
            json={
                "title": "Wrong workflow stage",
                "stage_id": str(other_scope["concept_id"]),
            },
        )
        assert cross_workflow_stage.status_code == 404
        assert cross_workflow_stage.json()["detail"]["code"] == "ISSUE_RELATED_OBJECT_NOT_FOUND"

        external_risk_owner = client.post(
            f"/api/projects/{project_id}/risks",
            headers=owner_headers,
            json={"title": "External owner", "owner_user_id": str(supplier_id)},
        )
        assert external_risk_owner.status_code == 404
        assert external_risk_owner.json()["detail"]["code"] == "RISK_RELATED_OBJECT_NOT_FOUND"

        assert (
            client.get(f"/api/projects/{uuid4()}/issues", headers=owner_headers).status_code == 403
        )
        with engine.connect() as connection:
            assert (
                connection.scalar(select(func.count()).select_from(tables.tasks))
                == baseline["tasks"]
            )
            assert (
                connection.scalar(select(func.count()).select_from(tables.issues))
                == baseline["issues"]
            )
            assert (
                connection.scalar(select(func.count()).select_from(tables.risks))
                == baseline["risks"]
            )
            assert (
                connection.scalar(select(func.count()).select_from(tables.events))
                == baseline["events"]
            )
            assert (
                connection.scalar(select(func.count()).select_from(tables.audit_log))
                == baseline["audits"]
            )
    finally:
        engine.dispose()


def test_project_members_list_supports_assignee_picking_without_leaking_scope(
    client: TestClient,
    isolated_work_item_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    owner_id = UUID(setup["user"]["id"])
    scope = seed_project(
        isolated_work_item_database,
        tenant_id=tenant_id,
        owner_id=owner_id,
        label="MEMBERS",
    )
    other_scope = seed_project(
        isolated_work_item_database,
        tenant_id=tenant_id,
        owner_id=owner_id,
        label="MEMBERS-OTHER",
    )
    project_id = scope["project_id"]
    engineer_id = seed_member(
        isolated_work_item_database,
        tenant_id=tenant_id,
        project_id=project_id,
        added_by_user_id=owner_id,
        username="engineer",
        role=Role.ENGINEER,
    )
    supplier_id = seed_member(
        isolated_work_item_database,
        tenant_id=tenant_id,
        project_id=project_id,
        added_by_user_id=owner_id,
        username="supplier",
        role=Role.SUPPLIER,
    )
    seed_member(
        isolated_work_item_database,
        tenant_id=tenant_id,
        project_id=other_scope["project_id"],
        added_by_user_id=owner_id,
        username="outsider",
        role=Role.ENGINEER,
    )
    members_url = f"/api/projects/{project_id}/members"

    response = client.get(members_url, headers=bearer_headers(client, username="engineer"))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    items = response.json()["items"]
    assert [item["display_name"] for item in items] == ["Engineer", "Initial Owner", "Supplier"]
    by_user = {item["user_id"]: item for item in items}
    assert set(by_user) == {str(owner_id), str(engineer_id), str(supplier_id)}
    assert by_user[str(owner_id)]["assignable"] is True
    assert by_user[str(engineer_id)]["assignable"] is True
    assert by_user[str(engineer_id)]["role"] == "engineer"
    assert by_user[str(supplier_id)]["assignable"] is False
    assert all(item["is_active"] is True for item in items)
    assert set(items[0]) == {"user_id", "display_name", "role", "is_active", "assignable"}

    assert client.get(members_url, headers=bearer_headers(client)).status_code == 200
    assert (
        client.get(members_url, headers=bearer_headers(client, username="supplier")).status_code
        == 403
    )
    assert (
        client.get(members_url, headers=bearer_headers(client, username="outsider")).status_code
        == 403
    )
    assert client.get(members_url).status_code == 401
