from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select

from app.auth.passwords import PasswordService
from app.auth.roles import Role
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
def isolated_project_members_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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
        cached_engine = get_engine()
        cached_engine.dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@dataclass(frozen=True)
class Staff:
    tenant_id: UUID
    owner_id: UUID
    project_id: UUID
    other_project_id: UUID
    users: dict[str, UUID]


# username -> (display name, role, active, member of the project)
PEOPLE = {
    "manager": ("项目经理甲", Role.PROJECT_MANAGER, True, True),
    "manager2": ("项目经理乙", Role.PROJECT_MANAGER, True, False),
    "engineer": ("工程师甲", Role.ENGINEER, True, True),
    "engineer2": ("工程师乙", Role.ENGINEER, True, False),
    "quality": ("品质甲", Role.QUALITY, True, True),
    "supplier": ("供应商甲", Role.SUPPLIER, True, True),
    "retired": ("已停用工程师", Role.ENGINEER, False, False),
}


def seed(client: TestClient, database_url: str) -> Staff:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD)
    assert setup.status_code == 201
    tenant_id = UUID(setup.json()["tenant"]["id"])
    owner_id = UUID(setup.json()["user"]["id"])
    users = {name: uuid4() for name in (*PEOPLE, "outsider")}
    project_id, other_project_id, other_tenant_id = uuid4(), uuid4(), uuid4()
    password_hash = PasswordService().hash(PASSWORD)
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": other_tenant_id, "slug": "other-tenant", "name": "Other Tenant"},
            )
            connection.execute(
                tables.users.insert(),
                [
                    {
                        "id": users[name],
                        "tenant_id": tenant_id,
                        "username": name,
                        "display_name": display_name,
                        "role": role,
                        "is_active": active,
                        "password_hash": password_hash,
                    }
                    for name, (display_name, role, active, _member) in PEOPLE.items()
                ]
                + [
                    {
                        "id": users["outsider"],
                        "tenant_id": other_tenant_id,
                        "username": "outsider",
                        "display_name": "外租户经理",
                        "role": Role.PROJECT_MANAGER,
                        "is_active": True,
                        "password_hash": password_hash,
                    }
                ],
            )
            for tenant, project, code, project_owner in (
                (tenant_id, project_id, "PDOS-001", users["manager"]),
                (other_tenant_id, other_project_id, "OTHER-001", users["outsider"]),
            ):
                workflow = uuid4()
                connection.execute(
                    tables.workflows.insert(),
                    {
                        "id": workflow,
                        "tenant_id": tenant,
                        "code": "npd",
                        "name": "NPD",
                        "version": 1,
                    },
                )
                connection.execute(
                    tables.projects.insert(),
                    {
                        "id": project,
                        "tenant_id": tenant,
                        "workflow_id": workflow,
                        "owner_user_id": project_owner,
                        "code": code,
                        "name": code,
                    },
                )
            connection.execute(
                tables.project_members.insert(),
                [
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "user_id": users[name],
                        "added_by_user_id": owner_id,
                    }
                    for name, (*_rest, member) in PEOPLE.items()
                    if member
                ],
            )
    finally:
        engine.dispose()
    return Staff(tenant_id, owner_id, project_id, other_project_id, users)


def login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def add(
    client: TestClient, staff: Staff, headers: dict[str, str], user_id: UUID, request_id: UUID
) -> tuple[int, Any]:
    response = client.post(
        f"/api/projects/{staff.project_id}/members",
        headers=headers,
        json={"request_id": str(request_id), "user_id": str(user_id)},
    )
    return response.status_code, response.json()


def remove(
    client: TestClient, staff: Staff, headers: dict[str, str], user_id: UUID, request_id: UUID
) -> tuple[int, Any]:
    response = client.post(
        f"/api/projects/{staff.project_id}/members/{user_id}/remove",
        headers=headers,
        json={"request_id": str(request_id)},
    )
    return response.status_code, response.json()


def ledger(database_url: str, project_id: UUID) -> dict[str, int]:
    """Member event and audit row counts for one Project, keyed by type/action."""
    engine = create_engine(psycopg_database_url(database_url))
    counts: dict[str, int] = {}
    try:
        with engine.connect() as connection:
            for key, table, pattern in (
                (tables.events.c.event_type, tables.events, "PROJECT_MEMBER_%"),
                (tables.audit_log.c.action, tables.audit_log, "project.member.%"),
            ):
                for name, count in connection.execute(
                    select(key, func.count())
                    .where(table.c.project_id == project_id, key.like(pattern))
                    .group_by(key)
                ):
                    counts[name] = count
    finally:
        engine.dispose()
    return counts


def set_user(database_url: str, user_id: UUID, **values: object) -> None:
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.users.update().where(tables.users.c.id == user_id).values(**values)
            )
    finally:
        engine.dispose()


def test_roster_names_members_and_only_managers_see_candidates(
    client: TestClient, isolated_project_members_database: str
) -> None:
    staff = seed(client, isolated_project_members_database)

    manager = client.get(
        f"/api/projects/{staff.project_id}/members", headers=login(client, "manager")
    )
    assert manager.status_code == 200
    assert manager.headers["cache-control"] == "no-store"
    body = manager.json()
    assert body["can_manage"] is True
    assert body["owner_user_id"] == str(staff.users["manager"])
    by_name = {item["username"]: item for item in body["items"]}
    assert set(by_name) == {"manager", "engineer", "quality", "supplier"}
    assert by_name["engineer"]["display_name"] == "工程师甲"
    assert by_name["engineer"]["added_by_display_name"] == "Initial Owner"
    assert by_name["manager"]["is_owner"] is True
    assert by_name["manager"]["removal_blocker"] == "项目负责人不能移出项目"
    assert by_name["engineer"]["removal_blocker"] is None
    # Only active internal non-members are offered; externals and the inactive never are.
    assert {user["username"] for user in body["available_users"]} == {
        "owner",
        "manager2",
        "engineer2",
    }

    engineer = client.get(
        f"/api/projects/{staff.project_id}/members", headers=login(client, "engineer")
    )
    assert engineer.status_code == 200
    assert engineer.json()["can_manage"] is False
    assert engineer.json()["available_users"] == []

    denied = [
        client.get(f"/api/projects/{staff.project_id}/members", headers=login(client, "supplier")),
        client.get(f"/api/projects/{staff.project_id}/members", headers=login(client, "engineer2")),
        client.get(
            f"/api/projects/{staff.other_project_id}/members", headers=login(client, "owner")
        ),
    ]
    assert {response.status_code for response in denied} == {403}
    assert {response.json()["detail"]["code"] for response in denied} == {
        "OBJECT_PERMISSION_DENIED"
    }
    assert client.get(f"/api/projects/{staff.project_id}/members").status_code == 401


@pytest.mark.parametrize("username", ["engineer", "quality", "supplier", "manager2", "engineer2"])
def test_only_project_managers_on_the_project_and_tenant_admins_may_staff(
    client: TestClient, isolated_project_members_database: str, username: str
) -> None:
    staff = seed(client, isolated_project_members_database)
    headers = login(client, username)

    status, body = add(client, staff, headers, staff.users["engineer2"], uuid4())
    assert status == 403
    assert body["detail"]["code"] == "OBJECT_PERMISSION_DENIED"
    status, body = remove(client, staff, headers, staff.users["engineer"], uuid4())
    assert status == 403
    assert ledger(isolated_project_members_database, staff.project_id) == {}


def test_tenant_owner_staffs_without_membership_but_never_across_tenants(
    client: TestClient, isolated_project_members_database: str
) -> None:
    staff = seed(client, isolated_project_members_database)
    owner = login(client, "owner")

    status, body = add(client, staff, owner, staff.users["manager2"], uuid4())
    assert status == 201
    assert str(staff.users["manager2"]) in {item["user_id"] for item in body["items"]}

    cross_project = client.post(
        f"/api/projects/{staff.other_project_id}/members",
        headers=owner,
        json={"request_id": str(uuid4()), "user_id": str(staff.users["engineer2"])},
    )
    assert cross_project.status_code == 403

    # Absent, other-tenant, inactive and external people all get one answer.
    for candidate in (uuid4(), staff.users["outsider"], staff.users["retired"]):
        status, body = add(client, staff, owner, candidate, uuid4())
        assert (status, body["detail"]["code"]) == (409, "PROJECT_MEMBER_CANDIDATE_INVALID")
    # An external party seeded as a member can be removed, but never re-added as staff.
    status, body = remove(client, staff, owner, staff.users["supplier"], uuid4())
    assert status == 200
    status, body = add(client, staff, owner, staff.users["supplier"], uuid4())
    assert (status, body["detail"]["code"]) == (409, "PROJECT_MEMBER_CANDIDATE_INVALID")


def test_member_commands_are_idempotent_audited_and_change_project_reach(
    client: TestClient, isolated_project_members_database: str
) -> None:
    staff = seed(client, isolated_project_members_database)
    manager = login(client, "manager")
    newcomer = staff.users["engineer2"]
    newcomer_headers = login(client, "engineer2")
    access = f"/api/projects/{staff.project_id}/access"
    assert client.get(access, headers=newcomer_headers).status_code == 403

    request_id = uuid4()
    status, body = add(client, staff, manager, newcomer, request_id)
    assert status == 201
    assert body["receipt"] == {"operation": "add", "user_id": str(newcomer), "replayed": False}
    added = next(item for item in body["items"] if item["user_id"] == str(newcomer))
    assert added["display_name"] == "工程师乙"
    assert added["added_by_display_name"] == "项目经理甲"
    assert "engineer2" not in {user["username"] for user in body["available_users"]}
    assert client.get(access, headers=newcomer_headers).status_code == 200

    status, body = add(client, staff, manager, newcomer, request_id)
    assert status == 201
    assert body["receipt"]["replayed"] is True
    status, body = add(client, staff, manager, staff.users["manager2"], request_id)
    assert (status, body["detail"]["code"]) == (409, "REQUEST_ID_REUSED")
    status, body = remove(client, staff, manager, newcomer, request_id)
    assert (status, body["detail"]["code"]) == (409, "REQUEST_ID_REUSED")
    status, body = add(client, staff, manager, newcomer, uuid4())
    assert (status, body["detail"]["code"]) == (409, "PROJECT_MEMBER_EXISTS")
    assert ledger(isolated_project_members_database, staff.project_id) == {
        "PROJECT_MEMBER_ADDED": 1,
        "project.member.add": 1,
    }

    removal_id = uuid4()
    status, body = remove(client, staff, manager, newcomer, removal_id)
    assert status == 200
    assert body["receipt"] == {"operation": "remove", "user_id": str(newcomer), "replayed": False}
    assert str(newcomer) not in {item["user_id"] for item in body["items"]}
    status, body = remove(client, staff, manager, newcomer, removal_id)
    assert (status, body["receipt"]["replayed"]) == (200, True)
    status, body = remove(client, staff, manager, newcomer, uuid4())
    assert (status, body["detail"]["code"]) == (404, "PROJECT_MEMBER_NOT_FOUND")
    assert client.get(access, headers=newcomer_headers).status_code == 403

    assert ledger(isolated_project_members_database, staff.project_id) == {
        "PROJECT_MEMBER_ADDED": 1,
        "PROJECT_MEMBER_REMOVED": 1,
        "project.member.add": 1,
        "project.member.remove": 1,
    }
    engine = create_engine(psycopg_database_url(isolated_project_members_database))
    try:
        with engine.connect() as connection:
            audit = (
                connection.execute(
                    select(tables.audit_log).where(
                        tables.audit_log.c.project_id == staff.project_id,
                        tables.audit_log.c.action == "project.member.remove",
                    )
                )
                .mappings()
                .one()
            )
    finally:
        engine.dispose()
    assert audit["actor_user_id"] == staff.users["manager"]
    assert audit["before_snapshot"]["display_name"] == "工程师乙"
    assert audit["after_snapshot"] is None
    assert audit["context"] == {"request_id": str(removal_id)}


def test_owner_last_manager_and_archived_projects_are_protected(
    client: TestClient, isolated_project_members_database: str
) -> None:
    staff = seed(client, isolated_project_members_database)
    owner = login(client, "owner")

    status, body = remove(client, staff, owner, staff.users["manager"], uuid4())
    assert (status, body["detail"]["code"]) == (409, "PROJECT_OWNER_MEMBER")

    status, _ = add(client, staff, owner, staff.users["manager2"], uuid4())
    assert status == 201
    # With the owner no longer active, manager2 is the only manager left.
    set_user(isolated_project_members_database, staff.users["manager"], is_active=False)
    roster = client.get(f"/api/projects/{staff.project_id}/members", headers=owner).json()
    blockers = {item["username"]: item["removal_blocker"] for item in roster["items"]}
    assert blockers["manager2"] == "项目须至少保留一名在岗的项目经理成员"
    before = ledger(isolated_project_members_database, staff.project_id)
    status, body = remove(client, staff, owner, staff.users["manager2"], uuid4())
    assert (status, body["detail"]["code"]) == (409, "PROJECT_LAST_MANAGER")
    assert ledger(isolated_project_members_database, staff.project_id) == before

    # Non-managers can still leave, and a second manager releases the first.
    status, _ = remove(client, staff, owner, staff.users["engineer"], uuid4())
    assert status == 200
    set_user(isolated_project_members_database, staff.users["engineer2"], role=Role.PROJECT_MANAGER)
    status, _ = add(client, staff, owner, staff.users["engineer2"], uuid4())
    assert status == 201
    status, _ = remove(client, staff, login(client, "manager2"), staff.users["manager2"], uuid4())
    assert status == 200

    engine = create_engine(psycopg_database_url(isolated_project_members_database))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.projects.update()
                .where(tables.projects.c.id == staff.project_id)
                .values(status="archived")
            )
    finally:
        engine.dispose()
    status, body = add(client, staff, owner, staff.users["manager2"], uuid4())
    assert (status, body["detail"]["code"]) == (409, "PROJECT_TERMINAL")
    status, body = remove(client, staff, owner, staff.users["quality"], uuid4())
    assert (status, body["detail"]["code"]) == (409, "PROJECT_TERMINAL")


def test_authority_is_rechecked_after_waiting_for_project_lock(
    client: TestClient, isolated_project_members_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import Connection
    from sqlalchemy.engine import RowMapping

    from app.domain import project_members

    staff = seed(client, isolated_project_members_database)
    headers = login(client, "manager")
    original_lock = project_members._lock_project

    def lock_after_revocation(connection: Connection, tenant: UUID, project: UUID) -> RowMapping:
        row = original_lock(connection, tenant, project)
        # Simulate a membership removed after HTTP authorization but before the
        # command obtains its lock. The command must not trust that old check.
        connection.execute(
            tables.project_members.delete().where(
                tables.project_members.c.tenant_id == tenant,
                tables.project_members.c.project_id == project,
                tables.project_members.c.user_id == staff.users["manager"],
            )
        )
        return row

    monkeypatch.setattr(project_members, "_lock_project", lock_after_revocation)
    status, body = add(client, staff, headers, staff.users["engineer2"], uuid4())
    assert (status, body["detail"]["code"]) == (403, "OBJECT_PERMISSION_DENIED")
    assert ledger(isolated_project_members_database, staff.project_id) == {}


def test_self_removal_returns_only_receipt_when_access_is_lost(
    client: TestClient, isolated_project_members_database: str
) -> None:
    staff = seed(client, isolated_project_members_database)
    owner = login(client, "owner")
    assert add(client, staff, owner, staff.users["manager2"], uuid4())[0] == 201
    manager2 = login(client, "manager2")
    status, body = remove(client, staff, manager2, staff.users["manager2"], uuid4())
    assert status == 200
    assert body["access_lost"] is True
    assert body["can_manage"] is False
    assert body["owner_user_id"] is None
    assert body["items"] == body["available_users"] == []
    assert body["receipt"]["operation"] == "remove"
    assert (
        client.get(f"/api/projects/{staff.project_id}/members", headers=manager2).status_code == 403
    )

    # Tenant authority survives removal of direct membership.
    assert add(client, staff, owner, staff.owner_id, uuid4())[0] == 201
    status, body = remove(client, staff, owner, staff.owner_id, uuid4())
    assert status == 200
    assert body["access_lost"] is False
    assert body["can_manage"] is True
    assert body["items"]
