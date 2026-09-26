from __future__ import annotations

import os
from collections.abc import Iterator
from importlib import import_module
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import DBAPIError

from app.db.namespaces import SCHEMAS
from app.db.schema import metadata, tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from tests.db_cleanup import clear_test_tenants
from tests.migration_fixtures import migrate_test_database_in_steps, rollback_migration_operations
from tests.test_migrations import EXPECTED_HEAD

SERVER_ROOT = Path(__file__).resolve().parents[1]
DINGTALK_TABLES = {
    ("cehub_core", "dingtalk_tenant_bindings"),
    ("cehub_core", "dingtalk_user_bindings"),
    ("cehub_core", "dingtalk_oauth_states"),
    ("cehub_project", "dingtalk_project_channels"),
    ("cehub_event", "integration_outbox"),
    ("cehub_event", "integration_receipts"),
    ("cehub_project", "dingtalk_approval_instances"),
    ("cehub_project", "dingtalk_interactive_cards"),
}


@pytest.fixture(scope="module")
def connector_database_url() -> Iterator[str]:
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


def test_metadata_freezes_dingtalk_identity_delivery_and_receipt_boundaries() -> None:
    actual = {(table.schema, table.name) for table in metadata.tables.values()}
    assert actual >= DINGTALK_TABLES
    assert not tables.dingtalk_tenant_bindings.c.tenant_id.nullable
    assert not tables.dingtalk_user_bindings.c.open_id.nullable
    assert not tables.dingtalk_user_bindings.c.staff_id.nullable
    assert not tables.dingtalk_oauth_states.c.state_digest.nullable
    assert not tables.integration_outbox.c.payload.nullable
    assert not tables.integration_receipts.c.payload_digest.nullable
    assert not tables.dingtalk_approval_instances.c.gate_id.nullable
    assert not tables.dingtalk_interactive_cards.c.out_track_id.nullable


def test_dingtalk_migration_matches_metadata_and_keeps_one_head(
    connector_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(connector_database_url))
    try:
        inspector = inspect(engine)
        actual = {
            (schema, table)
            for schema, table in DINGTALK_TABLES
            if table in inspector.get_table_names(schema=schema)
        }
        assert actual == DINGTALK_TABLES
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
        EXPECTED_HEAD
    ]


def test_dingtalk_migration_round_trip_and_lossy_downgrade_guard(
    connector_database_url: str,
) -> None:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    cleanup_engine = create_engine(psycopg_database_url(connector_database_url))
    try:
        with cleanup_engine.begin() as connection:
            clear_test_tenants(connection)
    finally:
        cleanup_engine.dispose()
    round_trip_engine = create_engine(psycopg_database_url(connector_database_url))
    try:
        migrate_test_database_in_steps(config, round_trip_engine, "0025_context_builder_v2")
    finally:
        try:
            migrate_test_database_in_steps(config, round_trip_engine, "head")
        finally:
            round_trip_engine.dispose()

    engine = create_engine(psycopg_database_url(connector_database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert().values(
                    id="00000000-0000-0000-0000-000000000026",
                    slug="dingtalk-downgrade-guard",
                    name="DingTalk downgrade guard",
                )
            )
            connection.execute(
                tables.users.insert().values(
                    id="00000000-0000-0000-0000-000000000126",
                    tenant_id="00000000-0000-0000-0000-000000000026",
                    username="dingtalk-guard-owner",
                    display_name="DingTalk Guard Owner",
                    role="owner",
                )
            )
            connection.execute(
                tables.dingtalk_tenant_bindings.insert().values(
                    tenant_id="00000000-0000-0000-0000-000000000026",
                    corp_id="ding-guard-corp",
                    client_id="ding-guard-client",
                    oauth_redirect_uri="https://pdos.example/dingtalk/callback",
                    callback_route_key="ding-guard-callback",
                    configured_by_user_id="00000000-0000-0000-0000-000000000126",
                )
            )

        with (
            rollback_migration_operations(engine),
            pytest.raises(DBAPIError, match="Cannot downgrade 0026"),
        ):
            import_module(
                "migrations.versions.0026_dingtalk_connector_add_dingtalk_connector"
            ).downgrade()

        with engine.begin() as connection:
            connection.execute(
                tables.dingtalk_tenant_bindings.delete().where(
                    tables.dingtalk_tenant_bindings.c.tenant_id
                    == "00000000-0000-0000-0000-000000000026"
                )
            )
            connection.execute(
                tables.users.delete().where(
                    tables.users.c.tenant_id == "00000000-0000-0000-0000-000000000026"
                )
            )
            connection.execute(
                tables.tenants.delete().where(
                    tables.tenants.c.id == "00000000-0000-0000-0000-000000000026"
                )
            )
    finally:
        engine.dispose()

    round_trip_engine = create_engine(psycopg_database_url(connector_database_url))
    try:
        migrate_test_database_in_steps(config, round_trip_engine, "0025_context_builder_v2")
    finally:
        try:
            migrate_test_database_in_steps(config, round_trip_engine, "head")
        finally:
            round_trip_engine.dispose()
