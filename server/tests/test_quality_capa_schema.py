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
QUALITY_CAPA_TABLES = {
    "complaints",
    "nonconformance_reports",
    "root_cause_analyses",
    "capa_actions",
    "effectiveness_reviews",
}


@pytest.fixture(scope="module")
def capa_database_url() -> Iterator[str]:
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


def test_metadata_freezes_the_quality_owner_approved_capa_tables() -> None:
    assert {
        table.name for table in metadata.tables.values() if table.schema == "cehub_quality"
    } >= QUALITY_CAPA_TABLES
    assert not tables.complaints.c.project_id.nullable
    assert tables.complaints.c.status.server_default is not None
    assert tables.complaints.c.document_refs.nullable is False
    assert tables.nonconformance_reports.c.target_date.nullable is False
    assert tables.nonconformance_reports.c.effectiveness_criteria.nullable
    assert tables.nonconformance_reports.c.observation_due_at.nullable
    assert tables.root_cause_analyses.c.version.nullable is False
    assert tables.capa_actions.c.evidence_refs.nullable is False
    assert tables.effectiveness_reviews.c.evidence_refs.nullable is False


def test_quality_capa_migration_matches_metadata_and_keeps_one_head(
    capa_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(capa_database_url))
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names(schema="cehub_quality")) >= QUALITY_CAPA_TABLES
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
    command.downgrade(config, "0020_cehub_migration_v1")
    command.upgrade(config, "head")
    assert ScriptDirectory.from_config(config).get_heads() == ["0024_phase_two_agents"]
