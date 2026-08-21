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
CHANGE_TABLES = {
    "engineering_change_requests",
    "ecr_affected_boms",
    "engineering_change_notices",
    "erp_handoffs",
}


@pytest.fixture(scope="module")
def change_database_url() -> Iterator[str]:
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


def test_metadata_freezes_ecr_ecn_and_handoff_boundaries() -> None:
    assert {
        table.name for table in metadata.tables.values() if table.schema == "cehub_product"
    } >= CHANGE_TABLES
    assert tables.engineering_change_requests.c.impact_analysis.nullable
    assert not tables.erp_handoffs.c.source_bom_snapshot.nullable
    assert not tables.integration_outbox.c.payload.nullable
    assert tables.integration_outbox.c.erp_handoff_id.nullable
    assert tables.integration_outbox.c.payload_digest.nullable


def test_change_migration_matches_metadata_and_single_head(change_database_url: str) -> None:
    engine = create_engine(psycopg_database_url(change_database_url))
    try:
        assert set(inspect(engine).get_table_names(schema="cehub_product")) >= CHANGE_TABLES
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
        "0031_user_account_management"
    ]
