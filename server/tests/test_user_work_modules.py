"""Module administration persists and projects the current server configuration."""

from importlib import import_module
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.db.schema import tables
from app.db.url import psycopg_database_url
from tests.migration_fixtures import rollback_migration_operations
from tests.test_user_admin_api import _create_user, _login_headers, _owner_headers
from tests.test_user_admin_api import client as client
from tests.test_user_admin_api import isolated_user_admin_database as isolated_user_admin_database


def test_admin_assignment_and_revocation_reach_existing_sessions_with_audit(
    client: TestClient,
    isolated_user_admin_database: str,
) -> None:
    owner = _owner_headers(client)
    _create_user(client, owner, username="module-admin", role="admin")
    person = _create_user(client, owner, username="multi-duty", role="engineer")
    session = _login_headers(client, username="multi-duty", password="temporary passphrase 2026")
    admin = _login_headers(client, username="module-admin", password="temporary passphrase 2026")
    path = f"/api/admin/users/{person['id']}"
    configured = client.patch(
        path,
        headers=admin,
        json={"work_modules": ["quality", "introduction", "product", "quality", "supply"]},
    )
    assert configured.status_code == 200, configured.text
    modules = ["product", "quality", "introduction", "supply"]
    assert configured.json()["role"] == "engineer"
    assert configured.json()["work_modules"] == modules
    assert client.get("/api/auth/me", headers=session).json()["user"]["work_modules"] == modules
    listing = client.get("/api/admin/users", headers=admin).json()["items"]
    assert next(user for user in listing if user["id"] == person["id"])["work_modules"] == modules

    engine = create_engine(psycopg_database_url(isolated_user_admin_database))
    try:
        with engine.connect() as c:
            audit = (
                c.execute(
                    select(tables.audit_log).where(tables.audit_log.c.action == "user.update")
                )
                .mappings()
                .one()
            )
            assert audit["actor_user_id"] == UUID(
                client.get("/api/auth/me", headers=admin).json()["user"]["id"]
            )
            assert audit["before_snapshot"] == {"work_modules": []}
            assert audit["after_snapshot"] == {"work_modules": modules}
        noop = client.patch(path, headers=admin, json={"work_modules": modules[::-1]})
        assert noop.status_code == 200
        with engine.connect() as c:
            assert (
                len(
                    c.execute(
                        select(tables.audit_log).where(tables.audit_log.c.action == "user.update")
                    ).all()
                )
                == 1
            )
    finally:
        engine.dispose()
    assert client.get("/api/admin/users", headers=session).status_code == 403
    assert (
        client.post(
            "/api/product-work/spaces",
            headers=session,
            json={
                "request_id": str(uuid4()),
                "code": "MODULE-DENIED",
                "title": "合成反例",
                "user_groups": ["TEST"],
                "regions": ["TEST"],
                "use_scenarios": ["TEST"],
                "research_questions": ["TEST"],
            },
        ).status_code
        == 403
    )
    revoked = client.patch(path, headers=admin, json={"work_modules": []})
    assert revoked.status_code == 200 and revoked.json()["work_modules"] == []
    assert client.get("/api/auth/me", headers=session).json()["user"]["work_modules"] == []


def test_only_managers_configure_modules_and_tenant_and_privileged_guards_remain(
    client: TestClient,
    isolated_user_admin_database: str,
) -> None:
    owner = _owner_headers(client)
    owner_id = client.get("/api/auth/me", headers=owner).json()["user"]["id"]
    _create_user(client, owner, username="module-admin", role="admin")
    person = _create_user(client, owner, username="multi-duty", role="quality")
    session = _login_headers(client, username="multi-duty", password="temporary passphrase 2026")
    admin = _login_headers(client, username="module-admin", password="temporary passphrase 2026")
    assert (
        client.patch(
            f"/api/admin/users/{person['id']}",
            headers=session,
            json={"work_modules": ["portfolio"]},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/admin/users/{owner_id}", headers=admin, json={"work_modules": ["product"]}
        ).status_code
        == 403
    )
    engine = create_engine(psycopg_database_url(isolated_user_admin_database))
    other_person = uuid4()
    try:
        with engine.begin() as c:
            other = uuid4()
            c.execute(tables.tenants.insert().values(id=other, slug=str(other), name="合成外租户"))
            c.execute(
                tables.users.insert().values(
                    id=other_person,
                    tenant_id=other,
                    username="other",
                    display_name="外租户",
                    role="engineer",
                )
            )
        assert (
            client.patch(
                f"/api/admin/users/{other_person}",
                headers=owner,
                json={"work_modules": ["product"]},
            ).status_code
            == 404
        )
        with engine.connect() as c:
            assert (
                c.execute(
                    select(tables.users.c.work_modules).where(tables.users.c.id == other_person)
                ).scalar_one()
                == []
            )
    finally:
        engine.dispose()


def test_validation_creation_and_external_role_transition_are_atomic(client: TestClient) -> None:
    owner = _owner_headers(client)
    created = client.post(
        "/api/admin/users",
        headers=owner,
        json={
            "username": "multi-duty",
            "display_name": "兼职人员",
            "role": "engineer",
            "password": "temporary passphrase 2026",
            "work_modules": ["project", "quality"],
        },
    )
    assert created.status_code == 201, created.text
    path = f"/api/admin/users/{created.json()['id']}"
    session = _login_headers(client, username="multi-duty", password="temporary passphrase 2026")
    assert client.get("/api/auth/me", headers=session).json()["user"]["work_modules"] == [
        "project",
        "quality",
    ]
    for invalid in (["administration"], ["owner"], ["unknown"], None, "quality", [None]):
        rejected = client.patch(path, headers=owner, json={"work_modules": invalid})
        assert rejected.status_code == 422, rejected.text
    assert client.patch(path, headers=owner, json={"role": "customer"}).status_code == 422
    me = client.get("/api/auth/me", headers=session).json()["user"]
    assert me["role"] == "engineer" and me["work_modules"] == ["project", "quality"]
    changed = client.patch(path, headers=owner, json={"role": "customer", "work_modules": []})
    assert changed.status_code == 200, changed.text
    assert (
        client.patch(path, headers=owner, json={"work_modules": ["engineering"]}).status_code == 422
    )
    assert client.get("/api/auth/me", headers=session).json()["user"]["work_modules"] == []


def test_migration_round_trip_and_guard_preserve_assigned_modules(
    isolated_user_admin_database: str,
) -> None:
    migration = import_module("migrations.versions.0419_user_work_modules")
    engine = create_engine(psycopg_database_url(isolated_user_admin_database))
    try:
        with rollback_migration_operations(engine) as c:
            migration.downgrade()
            assert "work_modules" not in {
                column["name"] for column in inspect(c).get_columns("users", schema="cehub_core")
            }
            tenant, user = uuid4(), uuid4()
            c.execute(tables.tenants.insert().values(id=tenant, slug=str(tenant), name="合成迁移"))
            c.execute(
                text(
                    "INSERT INTO cehub_core.users(id,tenant_id,username,display_name,role) "
                    "VALUES(:user,:tenant,'original','原成员','engineer')"
                ),
                {
                    "user": user,
                    "tenant": tenant,
                },
            )
            migration.upgrade()
            assert (
                c.execute(
                    select(tables.users.c.work_modules).where(tables.users.c.id == user)
                ).scalar_one()
                == []
            )
            c.execute(
                tables.users.update()
                .where(tables.users.c.id == user)
                .values(work_modules=["quality"])
            )
            with pytest.raises(RuntimeError, match="Cannot downgrade 0419"):
                migration.downgrade()
            assert c.execute(
                select(tables.users.c.work_modules).where(tables.users.c.id == user)
            ).scalar_one() == ["quality"]
            for values in (["administration"], [None]):
                with pytest.raises(IntegrityError), c.begin_nested():
                    c.execute(
                        tables.users.update()
                        .where(tables.users.c.id == user)
                        .values(work_modules=values)
                    )
            with pytest.raises(IntegrityError), c.begin_nested():
                c.execute(
                    tables.users.update().where(tables.users.c.id == user).values(role="supplier")
                )
    finally:
        engine.dispose()
