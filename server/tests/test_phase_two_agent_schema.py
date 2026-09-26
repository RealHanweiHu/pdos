from __future__ import annotations

import os
from collections.abc import Iterator
from importlib import import_module
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from tests.db_cleanup import clear_test_tenants
from tests.migration_fixtures import (
    migrate_test_database_in_steps,
    rollback_migration_operations,
)

SERVER_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def phase_two_database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            clear_test_tenants(connection)
        yield test_url
    finally:
        command.upgrade(config, "head")
        engine.dispose()
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url


def test_database_accepts_only_frozen_phase_two_agent_and_finding_pairs(
    phase_two_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(phase_two_database_url))
    tenant_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": tenant_id, "slug": f"phase-two-{tenant_id}", "name": "Phase Two"},
            )
            for agent_key in ("engineering_intelligence", "quality_intelligence"):
                connection.execute(
                    tables.agent_subscriptions.insert(),
                    {"id": uuid4(), "tenant_id": tenant_id, "agent_key": agent_key},
                )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.agent_subscriptions.insert(),
                    {"id": uuid4(), "tenant_id": tenant_id, "agent_key": "reviewer_agent"},
                )

            valid_controls = (
                ("engineering_intelligence", "bom_impact_suggestion"),
                ("engineering_intelligence", "change_impact_suggestion"),
                ("quality_intelligence", "quality_cluster_alert"),
                ("quality_intelligence", "capa_suggestion"),
            )
            for agent_key, finding_type in valid_controls:
                connection.execute(
                    tables.finding_quality_controls.insert(),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "agent_key": agent_key,
                        "finding_type": finding_type,
                    },
                )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.finding_quality_controls.insert(),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "agent_key": "quality_intelligence",
                        "finding_type": "bom_impact_suggestion",
                    },
                )
    finally:
        engine.dispose()


def test_phase_two_migration_round_trip_and_lossy_downgrade_guard(
    phase_two_database_url: str,
) -> None:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    engine = create_engine(psycopg_database_url(phase_two_database_url))
    tenant_id = uuid4()
    try:
        try:
            migrate_test_database_in_steps(config, engine, "0023_memory_finding_apply")
        finally:
            migrate_test_database_in_steps(config, engine, "head")
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": tenant_id, "slug": f"guard-{tenant_id}", "name": "Guard"},
            )
            connection.execute(
                tables.agent_subscriptions.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "agent_key": "quality_intelligence",
                },
            )
        with (
            pytest.raises(DBAPIError, match="Cannot downgrade 0024"),
            rollback_migration_operations(engine),
        ):
            import_module("migrations.versions.0024_phase_two_agents").downgrade()
    finally:
        with engine.begin() as connection:
            clear_test_tenants(connection)
        command.upgrade(config, "head")
        engine.dispose()
