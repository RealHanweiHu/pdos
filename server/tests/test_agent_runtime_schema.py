from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Table,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.schema import Constraint

from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url

SERVER_ROOT = Path(__file__).resolve().parents[1]


def constraint_names(table: Table, constraint_type: type[Constraint]) -> set[str]:
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, constraint_type) and isinstance(constraint.name, str)
    }


def index_names(table: Table) -> set[str]:
    return {
        index.name
        for index in table.indexes
        if isinstance(index, Index) and isinstance(index.name, str)
    }


def test_agent_runtime_metadata_freezes_control_and_execution_records() -> None:
    assert set(tables.agent_dispatcher_cursors.c.keys()) == {
        "id",
        "tenant_id",
        "consumer_key",
        "last_event_row_id",
        "created_at",
        "updated_at",
    }
    assert "uq_agent_dispatcher_cursors_tenant_consumer" in constraint_names(
        tables.agent_dispatcher_cursors, UniqueConstraint
    )
    assert "ck_agent_dispatcher_cursors_last_event_nonnegative" in constraint_names(
        tables.agent_dispatcher_cursors, CheckConstraint
    )

    assert set(tables.agent_subscriptions.c.keys()) == {
        "id",
        "tenant_id",
        "agent_key",
        "status",
        "consecutive_failure_count",
        "failure_threshold",
        "paused_reason",
        "created_at",
        "updated_at",
    }
    assert {
        "ck_agent_subscriptions_agent_key_allowed",
        "ck_agent_subscriptions_status_allowed",
        "ck_agent_subscriptions_failure_count_nonnegative",
        "ck_agent_subscriptions_failure_threshold_range",
        "ck_agent_subscriptions_pause_reason_consistent",
    } <= constraint_names(tables.agent_subscriptions, CheckConstraint)
    assert "uq_agent_subscriptions_tenant_agent" in constraint_names(
        tables.agent_subscriptions, UniqueConstraint
    )

    assert set(tables.agent_runs.c.keys()) == {
        "id",
        "tenant_id",
        "project_id",
        "subscription_id",
        "agent_key",
        "status",
        "window_started_at",
        "window_ended_at",
        "first_event_row_id",
        "last_event_row_id",
        "event_count",
        "event_row_ids",
        "context_version",
        "run_context",
        "started_at",
        "completed_at",
        "error_code",
        "created_at",
        "updated_at",
    }
    assert {
        "ck_agent_runs_agent_key_allowed",
        "ck_agent_runs_status_allowed",
        "ck_agent_runs_window_order",
        "ck_agent_runs_event_bounds_consistent",
        "ck_agent_runs_event_ids_array",
        "ck_agent_runs_context_object",
        "ck_agent_runs_lifecycle_consistent",
        "ck_agent_runs_error_consistent",
    } <= constraint_names(tables.agent_runs, CheckConstraint)
    assert {
        "fk_agent_runs_tenant_project",
        "fk_agent_runs_tenant_subscription_agent",
    } <= constraint_names(tables.agent_runs, ForeignKeyConstraint)
    assert "uq_agent_runs_tenant_project_agent_window" in constraint_names(
        tables.agent_runs, UniqueConstraint
    )
    assert {
        "ix_agent_runs_tenant_status_created",
        "ix_agent_runs_tenant_project_created",
        "ix_agent_runs_tenant_agent_created",
    } <= index_names(tables.agent_runs)
    assert "fk_model_invocations_tenant_run" in constraint_names(
        tables.model_invocations, ForeignKeyConstraint
    )
    assert str(tables.agent_runs.c.context_version.server_default.arg) == "'run-context-v2'"


@pytest.fixture
def agent_runtime_database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.downgrade(config, "0009_invocation_cache_tokens")
    command.upgrade(config, "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE cehub_core.tenants CASCADE"))
        yield test_url
    finally:
        engine.dispose()
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url


def seed_project(database_url: str) -> tuple[UUID, UUID, UUID]:
    tenant_id = uuid4()
    workflow_id = uuid4()
    project_id = uuid4()
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": tenant_id, "slug": f"agent-{tenant_id}", "name": "Agent Tenant"},
            )
            connection.execute(
                tables.workflows.insert(),
                {
                    "id": workflow_id,
                    "tenant_id": tenant_id,
                    "code": "agent-runtime",
                    "name": "Agent Runtime",
                },
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": project_id,
                    "tenant_id": tenant_id,
                    "workflow_id": workflow_id,
                    "code": "PRJ-AGENT",
                    "name": "Agent Project",
                },
            )
    finally:
        engine.dispose()
    return tenant_id, workflow_id, project_id


def test_database_enforces_debounce_scope_lifecycle_and_invocation_link(
    agent_runtime_database_url: str,
) -> None:
    tenant_id, _, project_id = seed_project(agent_runtime_database_url)
    subscription_id = uuid4()
    run_id = uuid4()
    window_start = datetime(2026, 8, 11, 20, tzinfo=UTC)
    engine = create_engine(psycopg_database_url(agent_runtime_database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.agent_dispatcher_cursors.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "consumer_key": "agent_dispatcher_v1",
                    "last_event_row_id": 0,
                },
            )
            connection.execute(
                tables.agent_subscriptions.insert(),
                {
                    "id": subscription_id,
                    "tenant_id": tenant_id,
                    "agent_key": "project_intelligence",
                },
            )
            connection.execute(
                tables.agent_runs.insert(),
                {
                    "id": run_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "subscription_id": subscription_id,
                    "agent_key": "project_intelligence",
                    "status": "debouncing",
                    "window_started_at": window_start,
                    "window_ended_at": window_start + timedelta(minutes=15),
                    "first_event_row_id": 10,
                    "last_event_row_id": 12,
                    "event_count": 3,
                    "event_row_ids": [10, 11, 12],
                },
            )
            connection.execute(
                tables.model_invocations.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "run_id": run_id,
                    "agent_key": "project_intelligence",
                    "prompt_version": "project-intelligence-v1",
                    "provider": "minimax",
                    "model": "MiniMax-M2.7",
                    "protocol": "openai-compatible",
                    "status": "succeeded",
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "total_tokens": 12,
                    "structured_attempts": 1,
                },
            )

            invalid_runs = (
                {"agent_key": "knowledge_lite"},
                {"window_ended_at": window_start - timedelta(seconds=1)},
                {"first_event_row_id": 13},
                {"event_count": 2},
                {"event_row_ids": {"not": "an array"}},
                {"status": "succeeded", "completed_at": None},
                {"status": "failed", "completed_at": window_start, "error_code": None},
            )
            valid = {
                "id": uuid4(),
                "tenant_id": tenant_id,
                "project_id": project_id,
                "subscription_id": subscription_id,
                "agent_key": "project_intelligence",
                "status": "debouncing",
                "window_started_at": window_start + timedelta(minutes=30),
                "window_ended_at": window_start + timedelta(minutes=45),
                "first_event_row_id": 20,
                "last_event_row_id": 20,
                "event_count": 1,
                "event_row_ids": [20],
            }
            for overrides in invalid_runs:
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(
                        tables.agent_runs.insert(),
                        {**valid, **overrides, "id": uuid4()},
                    )

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.agent_runs.insert(),
                    {**valid, "id": uuid4(), "window_started_at": window_start},
                )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.model_invocations.insert(),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "run_id": uuid4(),
                        "agent_key": "project_intelligence",
                        "prompt_version": "v1",
                        "provider": "minimax",
                        "model": "MiniMax-M2.7",
                        "protocol": "openai-compatible",
                        "status": "succeeded",
                        "structured_attempts": 1,
                    },
                )
    finally:
        engine.dispose()


def test_agent_runtime_migration_round_trip(agent_runtime_database_url: str) -> None:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    engine = create_engine(psycopg_database_url(agent_runtime_database_url))
    try:
        command.downgrade(config, "0009_invocation_cache_tokens")
        assert set(inspect(engine).get_table_names(schema="cehub_ai")) == {
            "model_invocations",
            "tenant_model_settings",
        }
        command.upgrade(config, "head")
        assert set(inspect(engine).get_table_names(schema="cehub_ai")) == {
            "agent_dispatcher_cursors",
            "agent_runs",
            "agent_subscriptions",
            "finding_actions",
            "finding_quality_controls",
            "findings",
            "model_invocations",
            "tenant_model_settings",
        }
    finally:
        command.upgrade(config, "head")
        engine.dispose()
