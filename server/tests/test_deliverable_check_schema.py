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
from app.domain.deliverable_checks import EXPECTED_CHECK_ITEM_COUNT, load_manifest

SERVER_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def deliverable_database_url() -> Iterator[str]:
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


def test_manifest_is_consumed_directly_as_687_unique_versioned_items() -> None:
    manifest = load_manifest()

    assert manifest["schema_version"] == 3
    assert manifest["template_versions"] == ["2026-07-v2", "2026-07-v3"]
    assert len(manifest["items"]) == EXPECTED_CHECK_ITEM_COUNT
    assert len({item["check_item_key"] for item in manifest["items"]}) == 687
    assert sum(len(item["bindings"]) for item in manifest["items"]) == 720
    assert sum(not item["bindings"] for item in manifest["items"]) == 99
    assert (
        sum(binding["isGate"] for item in manifest["items"] for binding in item["bindings"]) == 131
    )


def test_schema_freezes_tenant_project_stage_and_completion_boundaries() -> None:
    assert not tables.deliverable_check_templates.c.tenant_id.nullable
    assert not tables.project_check_items.c.stage_id.nullable
    assert not tables.project_check_items.c.is_gate.nullable
    assert {value.name for value in tables.project_check_items.foreign_key_constraints} >= {
        "fk_project_check_items_tenant_workflow_project",
        "fk_project_check_items_tenant_workflow_stage",
        "fk_project_check_items_tenant_template",
    }


def test_deliverable_migration_matches_metadata_and_single_head(
    deliverable_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(deliverable_database_url))
    try:
        assert {
            "deliverable_check_templates",
            "project_check_items",
        } <= set(inspect(engine).get_table_names(schema="cehub_project"))
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
