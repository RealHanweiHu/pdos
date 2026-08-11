from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
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
from app.domain.workflow_templates import NPD_WORKFLOW_TEMPLATE
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
def isolated_project_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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


def seed_user(database_url: str, *, tenant_id: UUID, username: str, role: Role) -> UUID:
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
                    "display_name": username.title(),
                    "role": role,
                    "password_hash": PasswordService().hash(PASSWORD),
                },
            )
    finally:
        engine.dispose()
    return user_id


def approved_case(
    client: TestClient,
    headers: dict[str, str],
    *,
    suffix: str,
) -> dict[str, Any]:
    requirement = client.post(
        "/api/requirements",
        headers=headers,
        json={"code": f"REQ-{suffix}", "title": f"Requirement {suffix}"},
    ).json()
    assert (
        client.patch(
            f"/api/requirements/{requirement['id']}",
            headers=headers,
            json={"status": "approved"},
        ).status_code
        == 200
    )
    converted = client.post(
        f"/api/requirements/{requirement['id']}/convert-to-case",
        headers=headers,
        json={
            "code": f"CASE-{suffix}",
            "title": f"Case {suffix}",
            "rationale": "Approved for project evaluation.",
        },
    )
    assert converted.status_code == 201
    case = cast(dict[str, Any], converted.json()["development_case"])
    case_url = f"/api/development-cases/{case['id']}/transitions"
    assert (
        client.post(case_url, headers=headers, json={"to_status": "evaluating"}).status_code == 200
    )
    approved = client.post(case_url, headers=headers, json={"to_status": "approved"})
    assert approved.status_code == 200
    return cast(dict[str, Any], approved.json())


def create_project(
    client: TestClient,
    headers: dict[str, str],
    case_id: str,
    *,
    code: str,
) -> Any:
    return client.post(
        "/api/projects",
        headers=headers,
        json={
            "development_case_id": case_id,
            "code": code,
            "name": f"Project {code}",
            "description": "NPD workflow instantiation test.",
            "start_date": "2026-08-15",
            "target_date": "2027-03-31",
        },
    )


def test_npd_template_is_versioned_and_exact() -> None:
    assert NPD_WORKFLOW_TEMPLATE.code == "npd"
    assert NPD_WORKFLOW_TEMPLATE.version == 1
    assert [(stage.code, stage.name, stage.sequence) for stage in NPD_WORKFLOW_TEMPLATE.stages] == [
        ("concept", "概念阶段", 1),
        ("planning", "规划阶段", 2),
        ("design", "设计阶段", 3),
        ("evt", "EVT 工程验证", 4),
        ("dvt", "DVT 设计验证", 5),
        ("pvt", "PVT 试产验证", 6),
        ("mp", "量产稳定与移交", 7),
    ]


def test_project_creation_atomically_instantiates_workflow_stages_and_case_transition(
    client: TestClient,
    isolated_project_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    owner_id = setup["user"]["id"]
    headers = bearer_headers(client)
    case = approved_case(client, headers, suffix="ATOMIC")

    created = create_project(client, headers, case["id"], code="PRJ-001")
    assert created.status_code == 201
    assert created.headers["cache-control"] == "no-store"
    project = created.json()
    assert project["development_case_id"] == case["id"]
    assert project["owner_user_id"] == owner_id
    assert project["code"] == "PRJ-001"
    assert project["status"] == "draft"
    assert project["current_stage"]["code"] == "concept"
    assert project["workflow"]["code"] == f"npd-{project['id']}"
    assert project["workflow"]["version"] == 1
    assert [stage["code"] for stage in project["workflow"]["stages"]] == [
        "concept",
        "planning",
        "design",
        "evt",
        "dvt",
        "pvt",
        "mp",
    ]

    assert client.get(f"/api/projects/{project['id']}", headers=headers).json() == project
    assert client.get("/api/projects", headers=headers).json() == {"items": [project]}
    case_after = client.get(f"/api/development-cases/{case['id']}", headers=headers)
    assert case_after.json()["status"] == "converted"

    engine = create_engine(psycopg_database_url(isolated_project_database))
    try:
        with engine.connect() as connection:
            counts = {
                "workflows": connection.scalar(select(func.count()).select_from(tables.workflows)),
                "stages": connection.scalar(select(func.count()).select_from(tables.stages)),
                "projects": connection.scalar(select(func.count()).select_from(tables.projects)),
                "members": connection.scalar(
                    select(func.count()).select_from(tables.project_members)
                ),
            }
            project_events = list(
                connection.execute(
                    select(tables.events.c.event_type, tables.events.c.project_id)
                    .where(
                        tables.events.c.project_id == UUID(project["id"]),
                        tables.events.c.event_type.in_(
                            {"PROJECT_CREATED", "DEVELOPMENT_CASE_STATUS_CHANGED"}
                        ),
                    )
                    .order_by(tables.events.c.id)
                ).mappings()
            )
            project_audits = set(
                connection.execute(
                    select(tables.audit_log.c.action).where(
                        tables.audit_log.c.action.in_(
                            {"project.create", "development_case.transition"}
                        )
                    )
                ).scalars()
            )
    finally:
        engine.dispose()
    assert counts == {"workflows": 1, "stages": 7, "projects": 1, "members": 1}
    assert [event["event_type"] for event in project_events] == [
        "PROJECT_CREATED",
        "DEVELOPMENT_CASE_STATUS_CHANGED",
    ]
    assert all(event["project_id"] == UUID(project["id"]) for event in project_events)
    assert project_audits == {"project.create", "development_case.transition"}


def test_project_state_stage_and_member_permissions(
    client: TestClient,
    isolated_project_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    owner_id = UUID(setup["user"]["id"])
    manager_id = seed_user(
        isolated_project_database,
        tenant_id=tenant_id,
        username="manager",
        role=Role.PROJECT_MANAGER,
    )
    engineer_id = seed_user(
        isolated_project_database,
        tenant_id=tenant_id,
        username="engineer",
        role=Role.ENGINEER,
    )
    supplier_id = seed_user(
        isolated_project_database,
        tenant_id=tenant_id,
        username="supplier",
        role=Role.SUPPLIER,
    )
    owner_headers = bearer_headers(client)
    manager_headers = bearer_headers(client, username="manager")
    engineer_headers = bearer_headers(client, username="engineer")
    supplier_headers = bearer_headers(client, username="supplier")
    case = approved_case(client, owner_headers, suffix="STATE")
    project = create_project(client, manager_headers, case["id"], code="PRJ-STATE").json()
    project_url = f"/api/projects/{project['id']}"

    assert client.get("/api/projects", headers=owner_headers).json()["items"] == [project]
    assert client.get("/api/projects", headers=manager_headers).json()["items"] == [project]
    assert client.get("/api/projects", headers=engineer_headers).json() == {"items": []}
    with create_engine(psycopg_database_url(isolated_project_database)).begin() as connection:
        connection.execute(
            tables.project_members.insert(),
            [
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": UUID(project["id"]),
                    "user_id": engineer_id,
                    "added_by_user_id": owner_id,
                },
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": UUID(project["id"]),
                    "user_id": supplier_id,
                    "added_by_user_id": owner_id,
                },
            ],
        )
    assert client.get(project_url, headers=engineer_headers).status_code == 200
    assert client.get(project_url, headers=supplier_headers).status_code == 200
    assert (
        client.patch(project_url, headers=engineer_headers, json={"name": "Denied"}).status_code
        == 403
    )

    edited = client.patch(project_url, headers=manager_headers, json={"name": "Updated project"})
    assert edited.status_code == 200
    assert edited.json()["name"] == "Updated project"
    assert manager_id == UUID(edited.json()["owner_user_id"])

    transition_url = f"{project_url}/transitions"
    for state in ("proposed", "approved", "active"):
        response = client.post(transition_url, headers=manager_headers, json={"to_status": state})
        assert response.status_code == 200
        assert response.json()["status"] == state

    stages = project["workflow"]["stages"]
    skipped = client.post(
        f"{project_url}/stage-transitions",
        headers=manager_headers,
        json={"to_stage_id": stages[2]["id"]},
    )
    assert skipped.status_code == 409
    planning = client.post(
        f"{project_url}/stage-transitions",
        headers=manager_headers,
        json={"to_stage_id": stages[1]["id"]},
    )
    assert planning.status_code == 200
    assert planning.json()["current_stage"]["code"] == "planning"

    assert (
        client.post(
            transition_url, headers=manager_headers, json={"to_status": "on_hold"}
        ).status_code
        == 200
    )
    paused_stage = client.post(
        f"{project_url}/stage-transitions",
        headers=manager_headers,
        json={"to_stage_id": stages[2]["id"]},
    )
    assert paused_stage.status_code == 409
    assert (
        client.post(
            transition_url, headers=manager_headers, json={"to_status": "active"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"{project_url}/stage-transitions",
            headers=manager_headers,
            json={"to_stage_id": stages[2]["id"]},
        ).status_code
        == 200
    )
    assert (
        client.post(
            transition_url, headers=manager_headers, json={"to_status": "archived"}
        ).status_code
        == 409
    )


def test_project_errors_are_tenant_safe_and_transactional(
    client: TestClient,
    isolated_project_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    headers = bearer_headers(client)
    case = approved_case(client, headers, suffix="ERROR")
    first = create_project(client, headers, case["id"], code="PRJ-ERROR")
    assert first.status_code == 201
    duplicate = create_project(client, headers, case["id"], code="PRJ-ERROR-2")
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "PROJECT_ALREADY_EXISTS"

    unknown = create_project(client, headers, str(uuid4()), code="PRJ-UNKNOWN")
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "DEVELOPMENT_CASE_NOT_FOUND"

    other_tenant_id = uuid4()
    other_requirement_id = uuid4()
    other_case_id = uuid4()
    engine = create_engine(psycopg_database_url(isolated_project_database))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": other_tenant_id, "slug": "other-project", "name": "Other Project"},
            )
            connection.execute(
                tables.requirements.insert(),
                {
                    "id": other_requirement_id,
                    "tenant_id": other_tenant_id,
                    "code": "OTHER-REQ",
                    "title": "Other requirement",
                    "status": "converted",
                },
            )
            connection.execute(
                tables.development_cases.insert(),
                {
                    "id": other_case_id,
                    "tenant_id": other_tenant_id,
                    "requirement_id": other_requirement_id,
                    "code": "OTHER-CASE",
                    "title": "Other case",
                    "status": "approved",
                },
            )
    finally:
        engine.dispose()
    cross = create_project(client, headers, str(other_case_id), code="PRJ-CROSS")
    assert cross.status_code == 404
    assert cross.json() == unknown.json()

    second_case = approved_case(client, headers, suffix="ROLLBACK")
    conflict = create_project(client, headers, second_case["id"], code="PRJ-ERROR")
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "PROJECT_CODE_CONFLICT"
    engine = create_engine(psycopg_database_url(isolated_project_database))
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(tables.projects)
                    .where(tables.projects.c.tenant_id == tenant_id)
                )
                == 1
            )
            assert (
                connection.scalar(
                    select(tables.development_cases.c.status).where(
                        tables.development_cases.c.id == UUID(second_case["id"])
                    )
                )
                == "approved"
            )
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(tables.workflows)
                    .where(tables.workflows.c.tenant_id == tenant_id)
                )
                == 1
            )
    finally:
        engine.dispose()
