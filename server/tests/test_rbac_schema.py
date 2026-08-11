from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError

from app.auth.roles import Role
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url

SERVER_ROOT = Path(__file__).resolve().parents[1]
BACKFILL_TENANT_ID = uuid4()
BACKFILL_OWNER_ID = uuid4()
BACKFILL_ENGINEER_ID = uuid4()


@pytest.fixture(scope="module")
def rbac_database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    config = Config(str(SERVER_ROOT / "alembic.ini"))

    try:
        command.downgrade(config, "0001_initial_entities")
        engine = create_engine(psycopg_database_url(test_url))
        try:
            inspector = inspect(engine)
            assert "role" not in {
                column["name"] for column in inspector.get_columns("users", schema="cehub_core")
            }
            assert "project_members" not in inspector.get_table_names(schema="cehub_project")
            created_at = datetime.now(UTC).replace(microsecond=0)
            with engine.begin() as connection:
                connection.execute(
                    tables.tenants.insert(),
                    {
                        "id": BACKFILL_TENANT_ID,
                        "slug": "rbac-backfill",
                        "name": "RBAC Backfill",
                    },
                )
                connection.execute(
                    tables.users.insert(),
                    [
                        {
                            "id": BACKFILL_OWNER_ID,
                            "tenant_id": BACKFILL_TENANT_ID,
                            "username": "first-user",
                            "display_name": "First User",
                            "created_at": created_at,
                        },
                        {
                            "id": BACKFILL_ENGINEER_ID,
                            "tenant_id": BACKFILL_TENANT_ID,
                            "username": "second-user",
                            "display_name": "Second User",
                            "created_at": created_at + timedelta(seconds=1),
                        },
                    ],
                )
        finally:
            engine.dispose()

        command.upgrade(config, "head")
        yield test_url
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url


def test_rbac_migration_adds_role_and_project_membership(rbac_database_url: str) -> None:
    engine = create_engine(psycopg_database_url(rbac_database_url))
    try:
        inspector = inspect(engine)
        user_columns = {
            column["name"]: column for column in inspector.get_columns("users", schema="cehub_core")
        }
        member_columns = {
            column["name"]
            for column in inspector.get_columns("project_members", schema="cehub_project")
        }

        assert user_columns["role"]["nullable"] is False
        assert member_columns == {
            "id",
            "tenant_id",
            "project_id",
            "user_id",
            "added_by_user_id",
            "created_at",
        }
        with engine.connect() as connection:
            rows = connection.execute(
                tables.users.select()
                .with_only_columns(tables.users.c.id, tables.users.c.role)
                .where(tables.users.c.tenant_id == BACKFILL_TENANT_ID)
            )
            backfilled_roles: dict[UUID, str] = {user_id: role for user_id, role in rows.tuples()}
        assert backfilled_roles == {
            BACKFILL_OWNER_ID: Role.OWNER,
            BACKFILL_ENGINEER_ID: Role.ENGINEER,
        }
    finally:
        engine.dispose()


def test_database_rejects_invalid_roles_and_cross_tenant_memberships(
    rbac_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(rbac_database_url))
    tenant_a = uuid4()
    tenant_b = uuid4()
    owner_a = uuid4()
    engineer_a = uuid4()
    engineer_b = uuid4()
    workflow_a = uuid4()
    project_a = uuid4()

    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                [
                    {"id": tenant_a, "slug": f"tenant-{tenant_a}", "name": "Tenant A"},
                    {"id": tenant_b, "slug": f"tenant-{tenant_b}", "name": "Tenant B"},
                ],
            )
            connection.execute(
                tables.users.insert(),
                [
                    {
                        "id": owner_a,
                        "tenant_id": tenant_a,
                        "username": "owner",
                        "display_name": "Owner A",
                        "role": Role.OWNER,
                    },
                    {
                        "id": engineer_a,
                        "tenant_id": tenant_a,
                        "username": "engineer",
                        "display_name": "Engineer A",
                        "role": Role.ENGINEER,
                    },
                    {
                        "id": engineer_b,
                        "tenant_id": tenant_b,
                        "username": "engineer",
                        "display_name": "Engineer B",
                        "role": Role.ENGINEER,
                    },
                ],
            )
            connection.execute(
                tables.workflows.insert(),
                {
                    "id": workflow_a,
                    "tenant_id": tenant_a,
                    "code": "npd",
                    "name": "NPD",
                    "version": 1,
                },
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": project_a,
                    "tenant_id": tenant_a,
                    "workflow_id": workflow_a,
                    "code": "PDOS-001",
                    "name": "PDOS",
                },
            )
            connection.execute(
                tables.project_members.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_a,
                    "project_id": project_a,
                    "user_id": engineer_a,
                    "added_by_user_id": owner_a,
                },
            )

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.project_members.insert(),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_a,
                        "project_id": project_a,
                        "user_id": engineer_b,
                        "added_by_user_id": owner_a,
                    },
                )

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.project_members.insert(),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_a,
                        "project_id": project_a,
                        "user_id": engineer_a,
                        "added_by_user_id": owner_a,
                    },
                )

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.users.insert(),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_a,
                        "username": "invalid-role",
                        "display_name": "Invalid Role",
                        "role": "superuser",
                    },
                )
    finally:
        engine.dispose()
