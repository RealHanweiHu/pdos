from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.auth.roles import Role
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from tests.db_cleanup import clear_test_tenants
from tests.migration_fixtures import migrate_test_database_in_steps

SERVER_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def event_audit_database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    config = Config(str(SERVER_ROOT / "alembic.ini"))

    engine = create_engine(psycopg_database_url(test_url))
    try:
        command.upgrade(config, "head")
        with engine.begin() as connection:
            clear_test_tenants(connection)
        try:
            migrate_test_database_in_steps(config, engine, "0002_rbac")
            inspector = inspect(engine)
            assert "events" not in inspector.get_table_names(schema="cehub_event")
            assert "audit_log" not in inspector.get_table_names(schema="cehub_audit")
        finally:
            migrate_test_database_in_steps(config, engine, "head")
        yield test_url
    finally:
        engine.dispose()
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url


def test_migration_creates_frozen_event_and_audit_envelopes(
    event_audit_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(event_audit_database_url))
    try:
        inspector = inspect(engine)
        event_columns = {
            column["name"] for column in inspector.get_columns("events", schema="cehub_event")
        }
        audit_columns = {
            column["name"] for column in inspector.get_columns("audit_log", schema="cehub_audit")
        }

        assert event_columns == {
            "id",
            "tenant_id",
            "project_id",
            "event_id",
            "event_type",
            "schema_version",
            "source",
            "entity",
            "entity_id",
            "payload",
            "timestamp",
        }
        assert audit_columns == {
            "id",
            "tenant_id",
            "project_id",
            "actor_user_id",
            "event_id",
            "action",
            "entity",
            "entity_id",
            "before_snapshot",
            "after_snapshot",
            "context",
            "timestamp",
        }
    finally:
        engine.dispose()


def test_database_enforces_event_idempotency_tenant_scope_and_audit_immutability(
    event_audit_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(event_audit_database_url))
    tenant_a = uuid4()
    tenant_b = uuid4()
    owner_a = uuid4()
    workflow_a = uuid4()
    project_a = uuid4()
    event_entity_id = uuid4()

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
                {
                    "id": owner_a,
                    "tenant_id": tenant_a,
                    "username": "owner",
                    "display_name": "Owner",
                    "role": Role.OWNER,
                },
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
            event_values = {
                "tenant_id": tenant_a,
                "project_id": project_a,
                "event_id": "project:pdos-001:created",
                "event_type": "PROJECT_CREATED",
                "schema_version": 1,
                "source": "project_service",
                "entity": "project",
                "entity_id": event_entity_id,
                "payload": {"project_code": "PDOS-001", "project_name": "PDOS"},
            }
            connection.execute(tables.events.insert(), event_values)
            audit_id = connection.execute(
                tables.audit_log.insert()
                .values(
                    tenant_id=tenant_a,
                    project_id=project_a,
                    actor_user_id=owner_a,
                    event_id=event_values["event_id"],
                    action="project.create",
                    entity="project",
                    entity_id=event_entity_id,
                    after_snapshot={"code": "PDOS-001", "name": "PDOS"},
                    context={"source": "project_service"},
                )
                .returning(tables.audit_log.c.id)
            ).scalar_one()

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(tables.events.insert(), event_values)

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.events.insert(),
                    {
                        **event_values,
                        "event_id": "cross-tenant-project",
                        "tenant_id": tenant_b,
                    },
                )

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.events.insert(),
                    {
                        **event_values,
                        "event_id": "scalar-payload",
                        "payload": "not-an-object",
                    },
                )

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.audit_log.insert(),
                    {
                        "tenant_id": tenant_a,
                        "actor_user_id": owner_a,
                        "event_id": "missing-snapshot",
                        "action": "project.read",
                        "entity": "project",
                        "entity_id": project_a,
                    },
                )

        with engine.begin() as connection, pytest.raises(DBAPIError):
            connection.execute(
                update(tables.audit_log)
                .where(tables.audit_log.c.id == audit_id)
                .values(action="tampered")
            )

        with engine.begin() as connection, pytest.raises(DBAPIError):
            connection.execute(tables.audit_log.delete().where(tables.audit_log.c.id == audit_id))

        with engine.connect() as connection:
            assert (
                connection.execute(
                    select(tables.audit_log.c.action).where(tables.audit_log.c.id == audit_id)
                ).scalar_one()
                == "project.create"
            )
    finally:
        engine.dispose()
