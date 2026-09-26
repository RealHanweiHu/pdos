"""AI Review candidates use one tenant/member-scoped read across projects."""

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
from fastapi.testclient import TestClient
from sqlalchemy import Engine, Table, create_engine, event

from app.api.auth import current_context, get_auth_service
from app.auth.passwords import PasswordService
from app.auth.repository import AuthContext, TenantRecord, UserRecord
from app.auth.roles import Role
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.domain.risk_candidates import RiskCandidateService
from app.main import app
from app.settings import get_settings
from tests.db_cleanup import clear_test_tenants

SERVER_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)
ENDPOINT = "/api/ai/risk-candidates"


def identity(*, role: Role | str, tenant_id: UUID | None = None) -> AuthContext:
    tenant_id = tenant_id or uuid4()
    user_id = uuid4()
    return AuthContext(
        tenant=TenantRecord(id=tenant_id, slug="review", name="Review", status="active"),
        user=UserRecord(
            id=user_id,
            tenant_id=tenant_id,
            username=f"user-{user_id.hex}",
            display_name="Reviewer",
            role=cast(Role, role),
            email=None,
            password_hash=None,
            auth_version=1,
            is_active=True,
        ),
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_engine] = lambda: MagicMock(spec=Engine)
    app.dependency_overrides[get_auth_service] = lambda: MagicMock()
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_registered_endpoint_requires_a_session(client: TestClient) -> None:
    response = client.get(ENDPOINT)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "role", [Role.OWNER, Role.ADMIN, Role.PROJECT_MANAGER, Role.ENGINEER, Role.QUALITY]
)
def test_scope_comes_from_session_and_response_cannot_be_cached(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, role: Role
) -> None:
    context = identity(role=role)
    app.dependency_overrides[current_context] = lambda: context
    load = MagicMock(return_value=[])
    monkeypatch.setattr(RiskCandidateService, "list_visible_candidates", load)
    response = client.get(
        ENDPOINT,
        params={"tenant_id": str(uuid4()), "user_id": str(uuid4()), "role": "owner"},
    )
    assert response.status_code == 200
    assert response.json() == {"items": []}
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"
    load.assert_called_once_with(
        tenant_id=context.tenant.id,
        member_user_id=None if role in (Role.OWNER, Role.ADMIN) else context.user.id,
    )


@pytest.mark.parametrize("role", [Role.SUPPLIER, Role.CUSTOMER, "unknown-role"])
def test_external_and_unknown_roles_cannot_query_candidates(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, role: Role | str
) -> None:
    context = identity(role=role)
    app.dependency_overrides[current_context] = lambda: context
    load = MagicMock()
    monkeypatch.setattr(RiskCandidateService, "list_visible_candidates", load)
    response = client.get(ENDPOINT)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "REVIEW_CANDIDATES_FORBIDDEN"
    load.assert_not_called()


class Scope:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.owner = identity(role=Role.OWNER)
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": self.owner.tenant.id, "slug": str(self.owner.tenant.id), "name": "Tenant"},
            )
        self.add_user(self.owner)

    def insert(self, table: Table, values: dict[str, Any]) -> UUID:
        row_id: UUID = values.setdefault("id", uuid4())
        values.setdefault("tenant_id", self.owner.tenant.id)
        with self.engine.begin() as connection:
            connection.execute(table.insert(), values)
        return row_id

    def add_user(self, context: AuthContext) -> None:
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
        self.add_user(context)
        return context

    def project(self, code: str, *, member_id: UUID | None = None) -> UUID:
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
                "owner_user_id": self.owner.user.id,
                "code": code,
                "name": code,
            },
        )
        if member_id is not None:
            self.insert(
                tables.project_members,
                {
                    "project_id": project_id,
                    "user_id": member_id,
                    "added_by_user_id": self.owner.user.id,
                },
            )
        return project_id

    def candidate(self, project_id: UUID, **values: Any) -> UUID:
        return self.insert(
            tables.risks,
            {
                "project_id": project_id,
                "title": "Review candidate",
                "draft_state": "draft",
                "origin_key": f"task_overdue:{uuid4()}",
                "rule_key": "task_overdue",
                "created_at": NOW,
                "updated_at": NOW,
                **values,
            },
        )


@pytest.fixture
def database(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[Scope]:
    test_url = configured_test_database_url()
    monkeypatch.setenv("DATABASE_URL", test_url)
    get_settings.cache_clear()
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            clear_test_tenants(connection)
        scope = Scope(engine)
        app.dependency_overrides[get_engine] = lambda: engine
        app.dependency_overrides[current_context] = lambda: scope.owner
        yield scope
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_candidates_are_draft_only_stably_ordered_and_reuse_project_response(
    database: Scope, client: TestClient
) -> None:
    first_project = database.project("FIRST")
    second_project = database.project("SECOND")
    later = database.candidate(first_project, id=UUID(int=2), likelihood=4, impact=5)
    earlier_id = database.candidate(second_project, id=UUID(int=1))
    oldest = database.candidate(first_project, created_at=NOW - timedelta(days=1))
    database.candidate(first_project, draft_state="confirmed")
    database.candidate(second_project, draft_state="cleared")
    response = client.get(ENDPOINT)
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["id"] for item in items] == [str(oldest), str(earlier_id), str(later)]
    project_items = client.get(f"/api/projects/{first_project}/risk-candidates").json()["items"]
    assert [item for item in items if item["project_id"] == str(first_project)] == project_items
    assert items[-1]["score"] == 20


@pytest.mark.parametrize(
    "role", [Role.OWNER, Role.ADMIN, Role.PROJECT_MANAGER, Role.ENGINEER, Role.QUALITY]
)
def test_candidates_match_project_list_and_review_inbox_visibility(
    database: Scope, client: TestClient, role: Role
) -> None:
    user = database.owner if role == Role.OWNER else database.user(role)
    direct = database.project("DIRECT", member_id=user.user.id)
    owned = database.project("OWNED")
    with database.engine.begin() as connection:
        connection.execute(
            tables.projects.update()
            .where(tables.projects.c.id == owned)
            .values(owner_user_id=user.user.id)
        )
    direct_id = database.candidate(direct)
    owned_id = database.candidate(owned, owner_user_id=user.user.id)
    rival = Scope(database.engine)
    rival.candidate(rival.project("OTHER-TENANT"))
    app.dependency_overrides[current_context] = lambda: user
    response = client.get(ENDPOINT)
    assert response.status_code == 200
    candidates = response.json()["items"]
    expected = (
        {str(direct_id), str(owned_id)} if role in (Role.OWNER, Role.ADMIN) else {str(direct_id)}
    )
    assert {item["id"] for item in candidates} == expected
    projects = client.get("/api/projects")
    assert projects.status_code == 200
    assert {item["project_id"] for item in candidates} == {
        item["id"] for item in projects.json()["items"]
    }
    inbox = client.get("/api/ai/review-inbox")
    assert inbox.status_code == 200
    assert {
        item["id"]
        for group in inbox.json()["groups"]
        for item in group["items"]
        if item["kind"] == "risk_candidate"
    } == expected


def test_internal_nonmember_gets_an_empty_list(database: Scope, client: TestClient) -> None:
    user = database.user(Role.ENGINEER)
    database.candidate(database.project("HIDDEN"))
    app.dependency_overrides[current_context] = lambda: user
    response = client.get(ENDPOINT)
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_real_authenticated_sessions_keep_tenant_scopes_separate(
    database: Scope, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-only-jwt-secret-that-is-at-least-32-bytes")
    get_settings.cache_clear()
    rival = Scope(database.engine)
    first_id = database.candidate(database.project("FIRST-TENANT"))
    rival_id = rival.candidate(rival.project("SECOND-TENANT"))
    password = "test-only-review-candidates-password"
    password_hash = PasswordService().hash(password)
    with database.engine.begin() as connection:
        connection.execute(
            tables.users.update()
            .where(tables.users.c.id.in_((database.owner.user.id, rival.owner.user.id)))
            .values(password_hash=password_hash)
        )
    app.dependency_overrides.pop(current_context)
    app.dependency_overrides.pop(get_auth_service)
    for scope, candidate_id in ((database, first_id), (rival, rival_id)):
        login = client.post(
            "/api/auth/login",
            json={
                "tenant_slug": str(scope.owner.tenant.id),
                "username": scope.owner.user.username,
                "password": password,
            },
        )
        assert login.status_code == 200
        response = client.get(
            ENDPOINT,
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
            params={"tenant_id": str(uuid4())},
        )
        assert response.status_code == 200
        assert [item["id"] for item in response.json()["items"]] == [str(candidate_id)]


@pytest.mark.parametrize("project_count", [0, 1, 25])
@pytest.mark.parametrize("role", [Role.OWNER, Role.ENGINEER])
def test_all_projects_require_exactly_one_read(
    database: Scope, client: TestClient, project_count: int, role: Role
) -> None:
    user = database.owner if role == Role.OWNER else database.user(role)
    for index in range(project_count):
        database.candidate(database.project(f"P-{index}", member_id=user.user.id))
    app.dependency_overrides[current_context] = lambda: user
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
        response = client.get(ENDPOINT)
    finally:
        event.remove(database.engine, "before_cursor_execute", count_statement)
    assert response.status_code == 200
    assert len(response.json()["items"]) == project_count
    assert len(statements) == 1, statements
    assert statements[0].lstrip().startswith("SELECT"), statements
