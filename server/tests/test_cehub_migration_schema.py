from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app.db.namespaces import SCHEMAS
from app.db.schema import metadata, tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url

SERVER_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def migration_database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    try:
        command.downgrade(config, "0019_deliverable_checks")
        engine = create_engine(psycopg_database_url(test_url))
        try:
            assert "migration_runs" not in inspect(engine).get_table_names(schema="cehub_audit")
            assert "external_file_references" not in inspect(engine).get_table_names(
                schema="cehub_project"
            )
        finally:
            engine.dispose()
        command.upgrade(config, "head")
        yield test_url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def test_migration_metadata_freezes_audited_external_reference_boundaries() -> None:
    assert not tables.migration_runs.c.tenant_id.nullable
    assert not tables.migration_mappings.c.tenant_id.nullable
    assert not tables.gate_history_records.c.project_id.nullable
    assert not tables.external_file_references.c.project_id.nullable
    assert tables.external_file_references.c.object_key.nullable is False
    assert "content" not in tables.external_file_references.c


def test_migration_0020_matches_metadata_and_single_head(
    migration_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(migration_database_url))
    try:
        assert {"migration_runs", "migration_mappings"} <= set(
            inspect(engine).get_table_names(schema="cehub_audit")
        )
        assert {"gate_history_records", "external_file_references"} <= set(
            inspect(engine).get_table_names(schema="cehub_project")
        )
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={
                    "compare_server_default": True,
                    "compare_type": True,
                    "include_schemas": True,
                    "include_name": lambda name, type_, parent_names: (
                        name in SCHEMAS
                        if type_ == "schema"
                        else parent_names.get("schema_name") in SCHEMAS
                        if type_ == "table"
                        else True
                    ),
                },
            )
            assert compare_metadata(context, metadata) == []
    finally:
        engine.dispose()
    assert ScriptDirectory.from_config(Config(str(SERVER_ROOT / "alembic.ini"))).get_heads() == [
        "0022_memory_search"
    ]
