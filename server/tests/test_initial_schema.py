from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError

from app.db.schema import metadata, tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url

SERVER_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SCHEMAS = {
    "cehub_core",
    "cehub_project",
    "cehub_product",
    "cehub_quality",
    "cehub_supplier",
    "cehub_cost",
    "cehub_ai",
    "cehub_memory",
    "cehub_event",
    "cehub_audit",
}
EXPECTED_TABLES = {
    ("cehub_core", "tenants"),
    ("cehub_core", "users"),
    ("cehub_core", "customers"),
    ("cehub_project", "requirements"),
    ("cehub_project", "development_cases"),
    ("cehub_project", "projects"),
    ("cehub_project", "workflows"),
    ("cehub_project", "stages"),
    ("cehub_project", "gates"),
    ("cehub_project", "tasks"),
    ("cehub_project", "task_dependencies"),
    ("cehub_project", "issues"),
    ("cehub_project", "risks"),
    ("cehub_project", "decisions"),
    ("cehub_project", "project_members"),
    ("cehub_project", "documents"),
    ("cehub_project", "document_fragments"),
    ("cehub_product", "specifications"),
    ("cehub_product", "development_boms"),
    ("cehub_product", "development_bom_items"),
    ("cehub_product", "erp_bom_references"),
    ("cehub_cost", "cost_bom_items"),
    ("cehub_event", "events"),
    ("cehub_audit", "audit_log"),
    ("cehub_ai", "model_invocations"),
    ("cehub_ai", "tenant_model_settings"),
    ("cehub_ai", "agent_dispatcher_cursors"),
    ("cehub_ai", "agent_subscriptions"),
    ("cehub_ai", "agent_runs"),
    ("cehub_ai", "finding_quality_controls"),
    ("cehub_ai", "findings"),
    ("cehub_ai", "finding_actions"),
}


@pytest.fixture(scope="module")
def migrated_database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    config = Config(str(SERVER_ROOT / "alembic.ini"))

    try:
        command.downgrade(config, "0000_scaffold")
        engine = create_engine(psycopg_database_url(test_url))
        try:
            assert EXPECTED_SCHEMAS.isdisjoint(inspect(engine).get_schema_names())
        finally:
            engine.dispose()

        command.upgrade(config, "head")
        yield test_url
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url


def test_metadata_contains_the_frozen_s0_2_entities_and_s0_4_membership() -> None:
    actual_tables = {(table.schema, table.name) for table in metadata.tables.values()}

    assert actual_tables == EXPECTED_TABLES
    for table in metadata.tables.values():
        if table.name != "tenants":
            assert not table.c.tenant_id.nullable
            assert any(
                foreign_key.target_fullname == "cehub_core.tenants.id"
                for foreign_key in table.c.tenant_id.foreign_keys
            )


def test_migration_round_trip_creates_the_exact_namespaces_and_tables(
    migrated_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(migrated_database_url))
    try:
        inspector = inspect(engine)
        assert set(inspector.get_schema_names()) >= EXPECTED_SCHEMAS
        actual_tables = {
            (schema, table_name)
            for schema in EXPECTED_SCHEMAS
            for table_name in inspector.get_table_names(schema=schema)
        }
        assert actual_tables == EXPECTED_TABLES
    finally:
        engine.dispose()


def test_migrated_database_matches_canonical_metadata(migrated_database_url: str) -> None:
    engine = create_engine(psycopg_database_url(migrated_database_url))

    def include_name(
        name: str | None,
        type_: str,
        parent_names: dict[str, str | None],
    ) -> bool:
        if type_ == "schema":
            return name in EXPECTED_SCHEMAS
        if type_ == "table":
            return parent_names.get("schema_name") in EXPECTED_SCHEMAS
        return True

    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={
                    "compare_server_default": True,
                    "compare_type": True,
                    "include_name": include_name,
                    "include_schemas": True,
                },
            )
            assert compare_metadata(context, metadata) == []
    finally:
        engine.dispose()


def test_database_enforces_tenant_state_and_uniqueness_boundaries(
    migrated_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(migrated_database_url))
    tenant_a = uuid4()
    tenant_b = uuid4()
    workflow_a = uuid4()
    workflow_b = uuid4()
    stage_a = uuid4()
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
                tables.workflows.insert(),
                [
                    {
                        "id": workflow_a,
                        "tenant_id": tenant_a,
                        "code": "npd",
                        "name": "NPD",
                        "version": 1,
                    },
                    {
                        "id": workflow_b,
                        "tenant_id": tenant_b,
                        "code": "npd",
                        "name": "NPD",
                        "version": 1,
                    },
                ],
            )
            connection.execute(
                tables.stages.insert(),
                {
                    "id": stage_a,
                    "tenant_id": tenant_a,
                    "workflow_id": workflow_a,
                    "code": "concept",
                    "name": "Concept",
                    "sequence": 1,
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
                    "status": "draft",
                },
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_b,
                    "workflow_id": workflow_b,
                    "code": "PDOS-001",
                    "name": "Same code in another tenant",
                    "status": "active",
                },
            )
            connection.execute(
                tables.gates.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_a,
                    "project_id": project_a,
                    "stage_id": stage_a,
                    "code": "G0",
                    "name": "Concept Gate",
                    "status": "preparing",
                },
            )
            connection.execute(
                tables.issues.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_a,
                    "project_id": project_a,
                    "title": "Initial issue",
                    "status": "analysis",
                },
            )

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.projects.insert(),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_a,
                        "workflow_id": workflow_b,
                        "code": "CROSS-TENANT",
                        "name": "Invalid cross-tenant workflow",
                        "status": "draft",
                    },
                )

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.projects.insert(),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_a,
                        "workflow_id": workflow_a,
                        "code": "PDOS-001",
                        "name": "Duplicate code",
                        "status": "draft",
                    },
                )

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.projects.insert(),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_a,
                        "workflow_id": workflow_a,
                        "code": "INVALID-STATE",
                        "name": "Invalid state",
                        "status": "unknown",
                    },
                )

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.issues.insert(),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_a,
                        "project_id": project_a,
                        "title": "Invalid issue state",
                        "status": "unknown",
                    },
                )

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.gates.insert(),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_a,
                        "project_id": project_a,
                        "stage_id": stage_a,
                        "code": "INVALID-GATE",
                        "name": "Invalid gate state",
                        "status": "unknown",
                    },
                )

            project_timestamps = connection.execute(
                select(tables.projects.c.created_at, tables.projects.c.updated_at).where(
                    tables.projects.c.id == project_a
                )
            ).one()
            assert project_timestamps.created_at is not None
            assert project_timestamps.updated_at is not None
    finally:
        engine.dispose()
