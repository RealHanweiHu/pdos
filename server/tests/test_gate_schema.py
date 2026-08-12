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
GATE_TABLES = {
    "gate_signoff_rounds",
    "gate_signoffs",
    "gate_signoff_additions",
    "gate_grandfather_exemptions",
}


@pytest.fixture(scope="module")
def gate_database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    try:
        command.upgrade(config, "head")
        yield test_url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def test_metadata_freezes_round_signoff_tightening_and_grandfather_tables() -> None:
    assert {
        table.name for table in metadata.tables.values() if table.schema == "cehub_project"
    } >= GATE_TABLES
    assert tables.gate_signoff_rounds.c.requirements.type.python_type is dict
    assert tables.gate_signoff_rounds.c.risk_snapshot.type.python_type is dict
    assert tables.gate_signoff_rounds.c.readiness_snapshot.nullable


def test_migration_has_one_open_round_per_gate_and_matches_metadata(
    gate_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(gate_database_url))
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names(schema="cehub_project")) >= GATE_TABLES
        indexes = inspector.get_indexes("gate_signoff_rounds", schema="cehub_project")
        open_index = next(index for index in indexes if index["name"] == "uq_gate_rounds_one_open")
        assert open_index["unique"]
        assert "status" in str(open_index["dialect_options"]["postgresql_where"])

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


def test_gate_migration_round_trip_preserves_single_head(gate_database_url: str) -> None:
    del gate_database_url
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.downgrade(config, "0015_specification_boms")
    command.upgrade(config, "head")
    assert ScriptDirectory.from_config(config).get_heads() == ["0020_cehub_migration_v1"]
