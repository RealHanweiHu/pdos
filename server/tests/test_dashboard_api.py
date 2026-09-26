"""Dashboard risk ranking, complete summaries, and bounded query regressions."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, Table, create_engine, event

from app.api.auth import current_context, get_auth_service
from app.api.dashboard import router
from app.auth.repository import AuthContext, TenantRecord, UserRecord
from app.auth.roles import Role
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.domain.dashboard import (
    DashboardProjectRiskSummary,
    DashboardRisk,
    DashboardRiskProject,
    DashboardRiskService,
    DashboardRiskSnapshot,
)
from app.main import app
from app.settings import get_settings
from tests.db_cleanup import clear_test_tenants

SERVER_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)


def identity(*, role: Role | str, tenant_id: UUID | None = None) -> AuthContext:
    tenant_id = tenant_id or uuid4()
    user_id = uuid4()
    return AuthContext(
        tenant=TenantRecord(id=tenant_id, slug="dashboard", name="Dashboard", status="active"),
        user=UserRecord(
            id=user_id,
            tenant_id=tenant_id,
            username=f"user-{user_id.hex}",
            display_name="Dashboard user",
            role=cast(Role, role),
            email=None,
            password_hash=None,
            auth_version=1,
            is_active=True,
        ),
    )


@pytest.fixture
def contract_app() -> FastAPI:
    boundary = FastAPI()
    boundary.include_router(router)
    boundary.dependency_overrides[get_engine] = lambda: MagicMock(spec=Engine)
    boundary.dependency_overrides[get_auth_service] = lambda: MagicMock()
    return boundary


@pytest.mark.parametrize(
    "role", [Role.OWNER, Role.ADMIN, Role.PROJECT_MANAGER, Role.ENGINEER, Role.QUALITY]
)
def test_contract_binds_scope_to_session_and_disables_caching(
    contract_app: FastAPI, monkeypatch: pytest.MonkeyPatch, role: Role
) -> None:
    context = identity(role=role)
    contract_app.dependency_overrides[current_context] = lambda: context
    project_id, risk_id = uuid4(), uuid4()
    load = MagicMock(
        return_value=DashboardRiskSnapshot(
            items=(
                DashboardRisk(
                    id=risk_id,
                    project_id=project_id,
                    title="Delivery slip",
                    status="watching",
                    likelihood=4,
                    impact=5,
                    score=20,
                    updated_at=NOW,
                    project=DashboardRiskProject(id=project_id, code="P-1", name="Pump"),
                ),
            ),
            total=1,
            projects=(
                DashboardProjectRiskSummary(project_id=project_id, open_risk_count=1, max_score=20),
            ),
        )
    )
    monkeypatch.setattr(DashboardRiskService, "load", load)
    with TestClient(contract_app) as client:
        response = client.get(
            "/api/dashboard/risks",
            params={"tenant_id": str(uuid4()), "user_id": str(uuid4()), "role": "owner"},
        )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"
    load.assert_called_once_with(tenant_id=context.tenant.id, user_id=context.user.id, role=role)
    assert response.json() == {
        "items": [
            {
                "id": str(risk_id),
                "project_id": str(project_id),
                "title": "Delivery slip",
                "status": "watching",
                "likelihood": 4,
                "impact": 5,
                "score": 20,
                "updated_at": "2026-09-08T12:00:00Z",
                "project": {"id": str(project_id), "code": "P-1", "name": "Pump"},
            }
        ],
        "total": 1,
        "projects": [{"project_id": str(project_id), "open_risk_count": 1, "max_score": 20}],
    }
    operation = contract_app.openapi()["paths"]["/api/dashboard/risks"]["get"]
    assert not any(item["in"] == "query" for item in operation.get("parameters", []))


@pytest.mark.parametrize("role", [Role.SUPPLIER, Role.CUSTOMER, "unrecognized-role"])
def test_contract_denies_external_and_unknown_roles_without_loading_data(
    contract_app: FastAPI, monkeypatch: pytest.MonkeyPatch, role: Role | str
) -> None:
    context = identity(role=role)
    contract_app.dependency_overrides[current_context] = lambda: context
    load = MagicMock()
    monkeypatch.setattr(DashboardRiskService, "load", load)
    with TestClient(contract_app) as client:
        response = client.get("/api/dashboard/risks")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "DASHBOARD_RISKS_FORBIDDEN"
    load.assert_not_called()


def test_contract_requires_a_session(
    contract_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    load = MagicMock()
    monkeypatch.setattr(DashboardRiskService, "load", load)
    with TestClient(contract_app) as client:
        response = client.get("/api/dashboard/risks")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    load.assert_not_called()


class DashboardSeeder:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.owner = identity(role=Role.OWNER)
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": self.owner.tenant.id, "slug": str(self.owner.tenant.id), "name": "Tenant"},
            )
        self._user(self.owner)

    def insert(self, table: Table, values: dict[str, Any]) -> UUID:
        row_id: UUID = values.setdefault("id", uuid4())
        values.setdefault("tenant_id", self.owner.tenant.id)
        with self.engine.begin() as connection:
            connection.execute(table.insert(), values)
        return row_id

    def _user(self, context: AuthContext) -> None:
        self.insert(
            tables.users,
            {
                "id": context.user.id,
                "username": context.user.username,
                "display_name": context.user.display_name,
                "role": context.user.role,
            },
        )

    def user(self, role: Role) -> AuthContext:
        context = identity(role=role, tenant_id=self.owner.tenant.id)
        self._user(context)
        return context

    def project(
        self,
        code: str,
        *,
        members: tuple[UUID, ...] = (),
        owner_id: UUID | None = None,
    ) -> UUID:
        workflow_id = self.insert(tables.workflows, {"code": f"WF-{code}", "name": code})
        stage_id = self.insert(
            tables.stages,
            {"workflow_id": workflow_id, "code": "concept", "name": "Concept", "sequence": 1},
        )
        project_id = self.insert(
            tables.projects,
            {
                "workflow_id": workflow_id,
                "current_stage_id": stage_id,
                "owner_user_id": owner_id or self.owner.user.id,
                "code": code,
                "name": f"Project {code}",
                "status": "active",
            },
        )
        for member_id in members:
            self.insert(
                tables.project_members,
                {
                    "project_id": project_id,
                    "user_id": member_id,
                    "added_by_user_id": self.owner.user.id,
                },
            )
        return project_id

    def risk(self, project_id: UUID, **values: Any) -> UUID:
        row = {"project_id": project_id, "title": "Risk", "updated_at": NOW, **values}
        if row.get("status") == "closed":
            row["closed_at"] = NOW
        if row.get("draft_state", "confirmed") != "confirmed":
            row["origin_key"] = f"candidate-{uuid4()}"
        return self.insert(tables.risks, row)


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[DashboardSeeder]:
    # Explicit fixture: contract tests never migrate, connect to, or truncate a database.
    test_url = configured_test_database_url()
    monkeypatch.setenv("DATABASE_URL", test_url)
    get_settings.cache_clear()
    get_engine.cache_clear()
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            clear_test_tenants(connection)
        yield DashboardSeeder(engine)
    finally:
        engine.dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()


@pytest.fixture
def database_client(database: DashboardSeeder) -> Iterator[TestClient]:
    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_engine] = lambda: database.engine
    app.dependency_overrides[current_context] = lambda: database.owner
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


def test_database_top_eight_sorting_preserves_complete_project_counts_and_zero_risks(
    database: DashboardSeeder, database_client: TestClient
) -> None:
    alpha = database.project("ALPHA")
    beta = database.project("BETA")
    zero = database.project("ZERO")
    excluded = database.project("EXCLUDED")
    older = database.risk(
        alpha, id=UUID(int=3), likelihood=5, impact=5, updated_at=NOW - timedelta(days=1)
    )
    tie_lower = database.risk(alpha, id=UUID(int=1), likelihood=5, impact=5)
    tie_higher = database.risk(alpha, id=UUID(int=2), likelihood=5, impact=5, status="watching")
    medium = [
        database.risk(alpha, id=UUID(int=100 + index), likelihood=3, impact=4, status="mitigating")
        for index in range(8)
    ]
    database.risk(beta, likelihood=2, impact=2)
    for project_id in (alpha, excluded):
        database.risk(project_id, likelihood=5, impact=5, status="closed")
        database.risk(project_id, likelihood=5, impact=5, draft_state="draft")
        database.risk(project_id, likelihood=5, impact=5, draft_state="cleared")

    response = database_client.get("/api/dashboard/risks")
    assert response.status_code == 200
    body = response.json()
    assert [row["id"] for row in body["items"]] == [
        str(item) for item in (tie_higher, tie_lower, older, *reversed(medium[-5:]))
    ]
    assert body["total"] == 12
    summaries = {row["project_id"]: row for row in body["projects"]}
    assert summaries == {
        str(alpha): {"project_id": str(alpha), "open_risk_count": 11, "max_score": 25},
        str(beta): {"project_id": str(beta), "open_risk_count": 1, "max_score": 4},
        str(zero): {"project_id": str(zero), "open_risk_count": 0, "max_score": 0},
        str(excluded): {"project_id": str(excluded), "open_risk_count": 0, "max_score": 0},
    }
    assert all(
        row["project"] == {"id": str(alpha), "code": "ALPHA", "name": "Project ALPHA"}
        for row in body["items"]
    )
    assert all(row["score"] == row["likelihood"] * row["impact"] for row in body["items"])


@pytest.mark.parametrize("role", [Role.PROJECT_MANAGER, Role.ENGINEER, Role.QUALITY])
def test_database_membership_and_tenant_scope_match_project_list(
    database: DashboardSeeder, database_client: TestClient, role: Role
) -> None:
    user = database.user(role)
    visible = database.project("VISIBLE", members=(user.user.id,))
    zero = database.project("ZERO", members=(user.user.id,))
    hidden = database.project("HIDDEN", owner_id=user.user.id)
    visible_risk = database.risk(visible)
    database.risk(hidden, owner_user_id=user.user.id, likelihood=5, impact=5)
    rival = DashboardSeeder(database.engine)
    rival_project = rival.project("RIVAL")
    rival.risk(rival_project, likelihood=5, impact=5)
    app.dependency_overrides[current_context] = lambda: user

    response = database_client.get("/api/dashboard/risks")
    assert response.status_code == 200
    body = response.json()
    assert [row["id"] for row in body["items"]] == [str(visible_risk)]
    assert body["total"] == 1
    assert {row["project_id"] for row in body["projects"]} == {str(visible), str(zero)}
    projects_response = database_client.get("/api/projects")
    assert projects_response.status_code == 200
    assert {row["id"] for row in projects_response.json()["items"]} == {
        row["project_id"] for row in body["projects"]
    }


@pytest.mark.parametrize("role", [Role.OWNER, Role.ADMIN])
def test_database_owner_and_admin_see_tenant_projects_without_membership(
    database: DashboardSeeder, database_client: TestClient, role: Role
) -> None:
    user = database.owner if role == Role.OWNER else database.user(role)
    visible = database.project("VISIBLE")
    zero = database.project("ZERO")
    risk_id = database.risk(visible)
    rival = DashboardSeeder(database.engine)
    rival.risk(rival.project("RIVAL"), likelihood=5, impact=5)
    app.dependency_overrides[current_context] = lambda: user

    response = database_client.get("/api/dashboard/risks")
    assert response.status_code == 200
    body = response.json()
    assert [row["id"] for row in body["items"]] == [str(risk_id)]
    assert body["total"] == 1
    assert {row["project_id"] for row in body["projects"]} == {str(visible), str(zero)}


def test_database_nonmember_has_empty_dashboard(
    database: DashboardSeeder, database_client: TestClient
) -> None:
    user = database.user(Role.ENGINEER)
    database.risk(database.project("HIDDEN"))
    app.dependency_overrides[current_context] = lambda: user
    response = database_client.get("/api/dashboard/risks")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "projects": []}


def test_database_ranking_and_counts_share_snapshot_during_concurrent_insert(
    database: DashboardSeeder, database_client: TestClient
) -> None:
    project_id = database.project("CONCURRENT")
    original_id = database.risk(project_id)
    inserted_ids: list[UUID] = []

    def insert_between_selects(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        if inserted_ids:
            return
        # Mark before opening a second connection so its INSERT event cannot recurse.
        inserted_ids.append(uuid4())
        database.risk(project_id, id=inserted_ids[0], likelihood=5, impact=5)

    event.listen(database.engine, "after_cursor_execute", insert_between_selects)
    try:
        response = database_client.get("/api/dashboard/risks")
    finally:
        event.remove(database.engine, "after_cursor_execute", insert_between_selects)
    assert response.status_code == 200
    body = response.json()
    assert [row["id"] for row in body["items"]] == [str(original_id)]
    assert body["total"] == 1
    assert body["projects"] == [
        {"project_id": str(project_id), "open_risk_count": 1, "max_score": 1}
    ]
    refreshed = database_client.get("/api/dashboard/risks")
    assert refreshed.status_code == 200
    assert refreshed.json()["total"] == 2
    assert refreshed.json()["items"][0]["id"] == str(inserted_ids[0])


@pytest.mark.parametrize("project_count", [0, 1, 25])
def test_database_uses_two_selects_independent_of_project_count(
    database: DashboardSeeder, database_client: TestClient, project_count: int
) -> None:
    for index in range(project_count):
        database.risk(database.project(f"P-{index}"))
    statements: list[str] = []

    def count_statement(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(database.engine, "before_cursor_execute", count_statement)
    try:
        response = database_client.get("/api/dashboard/risks")
    finally:
        event.remove(database.engine, "before_cursor_execute", count_statement)
    assert response.status_code == 200
    assert response.json()["total"] == project_count
    assert len(response.json()["items"]) == min(project_count, 8)
    assert len(response.json()["projects"]) == project_count
    assert len(statements) == 2, statements
    assert all(statement.lstrip().startswith(("SELECT", "WITH")) for statement in statements)
