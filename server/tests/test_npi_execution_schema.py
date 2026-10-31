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
from sqlalchemy import String, create_engine, inspect

from app.db.namespaces import SCHEMAS
from app.db.schema import metadata, tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url

SERVER_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_TABLES = {"build_batches", "samples"}
QUALITY_TABLES = {
    "sample_signoffs",
    "sample_signoff_samples",
    "test_plans",
    "test_cases",
    "test_case_samples",
    "test_reports",
    "certifications",
    "certification_expiry_alerts",
}


@pytest.fixture(scope="module")
def npi_database_url() -> Iterator[str]:
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


def test_metadata_freezes_build_sample_test_and_certification_tables() -> None:
    assert {
        table.name for table in metadata.tables.values() if table.schema == "cehub_product"
    } >= PRODUCT_TABLES
    assert {
        table.name for table in metadata.tables.values() if table.schema == "cehub_quality"
    } >= QUALITY_TABLES
    assert isinstance(tables.build_batches.c.phase.type, String)
    assert tables.build_batches.c.phase.type.length == 8
    assert not tables.samples.c.serial_number.nullable
    assert tables.certifications.c.is_required.server_default is not None


def test_migration_matches_metadata_and_preserves_single_head(npi_database_url: str) -> None:
    engine = create_engine(psycopg_database_url(npi_database_url))
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names(schema="cehub_product")) >= PRODUCT_TABLES
        assert set(inspector.get_table_names(schema="cehub_quality")) >= QUALITY_TABLES
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

    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.downgrade(config, "0016_gate_signoffs")
    command.upgrade(config, "head")
    assert ScriptDirectory.from_config(config).get_heads() == ["0031_project_planning"]
