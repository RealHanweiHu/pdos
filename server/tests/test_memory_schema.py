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
from sqlalchemy import create_engine, inspect, text

from app.db.namespaces import SCHEMAS
from app.db.schema import metadata, tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url

SERVER_ROOT = Path(__file__).resolve().parents[1]
MEMORY_TABLES = {"memories", "memory_embeddings"}


@pytest.fixture(scope="module")
def memory_database_url() -> Iterator[str]:
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


def test_metadata_freezes_verified_memory_and_embedding_boundaries() -> None:
    assert {
        table.name for table in metadata.tables.values() if table.schema == "cehub_memory"
    } >= MEMORY_TABLES
    assert not tables.memories.c.project_id.nullable
    assert not tables.memories.c.content_sha256.nullable
    assert not tables.memories.c.tags.nullable
    assert not tables.memories.c.source_refs.nullable
    assert not tables.memory_embeddings.c.embedding.nullable
    assert not tables.memory_embeddings.c.provider.nullable
    assert not tables.memory_embeddings.c.model.nullable
    assert not tables.memory_embeddings.c.dimensions.nullable


def test_memory_migration_matches_metadata_pgvector_and_single_head(
    memory_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(memory_database_url))
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names(schema="cehub_memory")) >= MEMORY_TABLES
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
                ).scalar_one()
                == 1
            )
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
    command.downgrade(config, "0021_quality_capa")
    command.upgrade(config, "head")
    assert ScriptDirectory.from_config(config).get_heads() == ["0025_context_builder_v2"]
