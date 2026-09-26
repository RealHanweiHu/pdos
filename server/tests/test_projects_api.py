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
from sqlalchemy import create_engine, event, func, select

from app.auth.passwords import PasswordService
from app.auth.roles import Role
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.domain.projects import ProjectService
from app.domain.workflow_templates import NPD_WORKFLOW_TEMPLATE
from app.main import app
from app.settings import get_settings
from tests.db_cleanup import clear_test_tenants
from tests.stage_plan_fixtures import seed_formal_task

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


def test_project_list_batches_stages_without_changing_workflow_contents(
    client: TestClient, isolated_project_database: str
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD)
    assert setup.status_code == 201
    headers = bearer_headers(client)
    expected = []
    for index in range(5):
        case = approved_case(client, headers, suffix=f"BATCH-{index}")
        response = create_project(client, headers, case["id"], code=f"BATCH-{index}")
        assert response.status_code == 201
        expected.append(response.json())

    engine = create_engine(psycopg_database_url(isolated_project_database))
    statements: list[str] = []

    def track_query(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    try:
        with engine.connect() as connection:
            tenant_id = connection.execute(select(tables.tenants.c.id)).scalar_one()
        event.listen(engine, "before_cursor_execute", track_query)
        records = ProjectService(engine).list(tenant_id=tenant_id, member_user_id=None)
        assert len(statements) == 2
        assert [record.code for record in records] == [item["code"] for item in reversed(expected)]
        by_id = {item["id"]: item for item in expected}
        for record in records:
            original = by_id[str(record.id)]
            assert [str(stage.id) for stage in record.workflow.stages] == [
                stage["id"] for stage in original["workflow"]["stages"]
            ]
            assert str(record.current_stage.id) == original["current_stage"]["id"]
        statements.clear()
        assert ProjectService(engine).list(tenant_id=tenant_id, member_user_id=uuid4()) == []
        assert len(statements) == 1
    finally:
        event.remove(engine, "before_cursor_execute", track_query)
        engine.dispose()


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
    activity = client.get(f"/api/projects/{project['id']}/activity", headers=headers)
    assert activity.status_code == 200
    assert activity.headers["cache-control"] == "no-store"
    assert "PROJECT_CREATED" in [item["event_type"] for item in activity.json()["items"]]
    assert all("payload" not in item for item in activity.json()["items"])
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


def test_project_list_keeps_imported_history_without_a_development_case_visible(
    client: TestClient,
    isolated_project_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id = UUID(setup["tenant"]["id"])
    owner_id = UUID(setup["user"]["id"])
    workflow_id = uuid4()
    stage_id = uuid4()
    project_id = uuid4()
    with create_engine(psycopg_database_url(isolated_project_database)).begin() as connection:
        connection.execute(
            tables.workflows.insert(),
            {
                "id": workflow_id,
                "tenant_id": tenant_id,
                "code": "npd-imported-history",
                "name": "Imported NPD workflow",
                "version": 1,
                "is_active": True,
            },
        )
        connection.execute(
            tables.stages.insert(),
            {
                "id": stage_id,
                "tenant_id": tenant_id,
                "workflow_id": workflow_id,
                "code": "concept",
                "name": "概念阶段",
                "sequence": 1,
            },
        )
        connection.execute(
            tables.projects.insert(),
            {
                "id": project_id,
                "tenant_id": tenant_id,
                "development_case_id": None,
                "workflow_id": workflow_id,
                "current_stage_id": stage_id,
                "owner_user_id": owner_id,
                "code": "HIST-001",
                "name": "Imported historical project",
                "status": "archived",
            },
        )

    response = client.get("/api/projects", headers=bearer_headers(client))

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    imported = response.json()["items"][0]
    assert imported["id"] == str(project_id)
    assert imported["development_case_id"] is None
    assert imported["code"] == "HIST-001"
    assert imported["name"] == "Imported historical project"
    assert imported["status"] == "archived"


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

    with create_engine(psycopg_database_url(isolated_project_database)).connect() as connection:
        assert (
            connection.execute(
                select(func.count())
                .select_from(tables.gates)
                .where(tables.gates.c.project_id == UUID(project["id"]))
            ).scalar_one()
            == 7
        )

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
    proposed = client.post(transition_url, headers=manager_headers, json={"to_status": "proposed"})
    assert proposed.status_code == 200
    # Case-derived projects now require a recorded plan approval and application.
    unapproved = client.post(
        transition_url, headers=manager_headers, json={"to_status": "approved"}
    )
    assert unapproved.status_code == 409
    fixture_engine = create_engine(psycopg_database_url(isolated_project_database))
    try:
        with fixture_engine.begin() as connection:
            seed_formal_task(connection, tenant_id, UUID(project["id"]), owner_id, engineer_id)
            # The execution approval service, rather than the generic transition
            # endpoint, produces this state; prepare it for stage permission checks.
            connection.execute(
                tables.projects.update()
                .where(tables.projects.c.id == UUID(project["id"]))
                .values(status="approved")
            )
    finally:
        fixture_engine.dispose()
    for state in ("active",):
        response = client.post(transition_url, headers=manager_headers, json={"to_status": state})
        assert response.status_code == 200
        assert response.json()["status"] == state

    stages = project["workflow"]["stages"]
    with create_engine(psycopg_database_url(isolated_project_database)).begin() as connection:
        connection.execute(
            tables.gates.update()
            .where(
                tables.gates.c.project_id == UUID(project["id"]),
                tables.gates.c.stage_id == UUID(stages[0]["id"]),
            )
            .values(status="approved")
        )
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
    with create_engine(psycopg_database_url(isolated_project_database)).begin() as connection:
        connection.execute(
            tables.gates.update()
            .where(
                tables.gates.c.project_id == UUID(project["id"]),
                tables.gates.c.stage_id == UUID(stages[1]["id"]),
            )
            .values(status="approved")
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
