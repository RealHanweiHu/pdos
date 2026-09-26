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
from sqlalchemy.schema import DefaultClause

from app.db.namespaces import SCHEMAS
from app.db.schema import metadata, tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from tests.db_cleanup import clear_test_tenants
from tests.migration_fixtures import (
    migrate_test_database_in_steps,
    rollback_migration_operations,
)
from tests.test_migrations import EXPECTED_HEAD

SERVER_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def user_admin_database_url() -> Iterator[str]:
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


def test_user_account_metadata_adds_a_positive_auth_version() -> None:
    assert "auth_version" in tables.users.c
    assert tables.users.c.auth_version.nullable is False
    server_default = tables.users.c.auth_version.server_default
    assert isinstance(server_default, DefaultClause)
    assert str(server_default.arg) == "1"


def test_user_account_migration_matches_metadata_and_is_the_single_head(
    user_admin_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(user_admin_database_url))
    try:
        with engine.connect() as connection:
            columns = {
                column["name"]: column
                for column in inspect(connection).get_columns("users", schema="cehub_core")
            }
            assert columns["auth_version"]["nullable"] is False
            context = MigrationContext.configure(
                connection,
                opts={
                    "compare_type": True,
                    "compare_server_default": True,
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
    assert ScriptDirectory.from_config(config).get_heads() == [EXPECTED_HEAD]


def test_user_account_migration_round_trip_and_revocation_downgrade_guard(
    user_admin_database_url: str,
) -> None:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    engine = create_engine(psycopg_database_url(user_admin_database_url))
    try:
        with engine.begin() as connection:
            clear_test_tenants(connection)
            connection.execute(
                tables.tenants.insert().values(
                    id="00000000-0000-0000-0000-000000000031",
                    slug="user-admin-downgrade-guard",
                    name="User Admin Downgrade Guard",
                )
            )
            connection.execute(
                tables.users.insert().values(
                    id="00000000-0000-0000-0000-000000000131",
                    tenant_id="00000000-0000-0000-0000-000000000031",
                    username="credential-guard-owner",
                    display_name="Credential Guard Owner",
                    role="owner",
                    auth_version=2,
                )
            )

        with (
            pytest.raises(DBAPIError, match="Cannot downgrade 0031"),
            rollback_migration_operations(engine),
        ):
            import_module("migrations.versions.0031_user_account_management").downgrade()

        with engine.begin() as connection:
            clear_test_tenants(connection)
        try:
            migrate_test_database_in_steps(config, engine, "0030_phase_three_agents")
        finally:
            migrate_test_database_in_steps(config, engine, "head")
    finally:
        engine.dispose()
