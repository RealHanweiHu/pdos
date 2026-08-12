from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import (
    CheckConstraint,
    Connection,
    ForeignKeyConstraint,
    Index,
    Table,
    UniqueConstraint,
    create_engine,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.exc import DBAPIError, IntegrityError
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


def test_model_gateway_metadata_freezes_settings_and_invocation_contracts() -> None:
    assert set(tables.tenant_model_settings.c.keys()) == {
        "id",
        "tenant_id",
        "provider",
        "model",
        "daily_token_budget",
        "updated_by_user_id",
        "created_at",
        "updated_at",
    }
    assert {
        "ck_tenant_model_settings_provider_allowed",
        "ck_tenant_model_settings_model_nonblank",
        "ck_tenant_model_settings_daily_budget_range",
    } <= constraint_names(tables.tenant_model_settings, CheckConstraint)
    assert "uq_tenant_model_settings_tenant_id" in constraint_names(
        tables.tenant_model_settings, UniqueConstraint
    )
    assert "fk_tenant_model_settings_tenant_updater" in constraint_names(
        tables.tenant_model_settings, ForeignKeyConstraint
    )

    assert set(tables.model_invocations.c.keys()) == {
        "id",
        "tenant_id",
        "project_id",
        "run_id",
        "request_id",
        "agent_key",
        "agent_tier",
        "prompt_version",
        "provider",
        "model",
        "model_version",
        "protocol",
        "status",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "latency_ms",
        "normalized_cost_microusd",
        "structured_attempts",
        "error_code",
        "created_at",
    }
    assert {
        "ck_model_invocations_provider_allowed",
        "ck_model_invocations_protocol_allowed",
        "ck_model_invocations_status_allowed",
        "ck_model_invocations_token_totals_consistent",
        "ck_model_invocations_error_consistent",
        "ck_model_invocations_structured_attempts_range",
    } <= constraint_names(tables.model_invocations, CheckConstraint)
    assert "fk_model_invocations_tenant_project" in constraint_names(
        tables.model_invocations, ForeignKeyConstraint
    )
    assert {
        "ix_model_invocations_tenant_created",
        "ix_model_invocations_tenant_agent_created",
        "ix_model_invocations_tenant_project_created",
    } <= index_names(tables.model_invocations)


@pytest.fixture
def model_gateway_database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    config = Config(str(SERVER_ROOT / "alembic.ini"))
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


def seed_project(connection: Connection, tenant_id: UUID) -> UUID:
    workflow_id = uuid4()
    project_id = uuid4()
    connection.execute(
        tables.workflows.insert(),
        {
            "id": workflow_id,
            "tenant_id": tenant_id,
            "code": "npd",
            "name": "NPD",
        },
    )
    connection.execute(
        tables.projects.insert(),
        {
            "id": project_id,
            "tenant_id": tenant_id,
            "workflow_id": workflow_id,
            "code": "PRJ-AI",
            "name": "AI Project",
        },
    )
    return project_id


def valid_invocation(tenant_id: UUID, *, project_id: UUID | None = None) -> dict[str, object]:
    return {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "project_id": project_id,
        "agent_key": "project_intelligence",
        "agent_tier": "reasoning",
        "prompt_version": "project-intelligence-v1",
        "provider": "minimax",
        "model": "MiniMax-M2.7",
        "protocol": "openai-compatible",
        "status": "succeeded",
        "input_tokens": 12,
        "output_tokens": 8,
        "total_tokens": 20,
        "latency_ms": 120,
        "normalized_cost_microusd": 15,
        "structured_attempts": 1,
    }


def test_database_enforces_model_gateway_scope_usage_and_immutability(
    model_gateway_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(model_gateway_database_url))
    tenant_a = uuid4()
    tenant_b = uuid4()
    user_a = uuid4()
    invocation_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                [
                    {"id": tenant_a, "slug": "ai-a", "name": "AI A"},
                    {"id": tenant_b, "slug": "ai-b", "name": "AI B"},
                ],
            )
            connection.execute(
                tables.users.insert(),
                {
                    "id": user_a,
                    "tenant_id": tenant_a,
                    "username": "owner",
                    "display_name": "Owner",
                    "role": "owner",
                },
            )
            project_a = seed_project(connection, tenant_a)
            connection.execute(
                tables.tenant_model_settings.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_a,
                    "provider": "minimax",
                    "model": "MiniMax-M2.7",
                    "daily_token_budget": 2_000_000,
                    "updated_by_user_id": user_a,
                },
            )

            for invalid_setting in (
                {"provider": "unknown", "model": "model", "daily_token_budget": 10},
                {"provider": "minimax", "model": "   ", "daily_token_budget": 10},
                {"provider": "minimax", "model": "model", "daily_token_budget": 0},
            ):
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(
                        tables.tenant_model_settings.insert(),
                        {"id": uuid4(), "tenant_id": tenant_b, **invalid_setting},
                    )

            values = valid_invocation(tenant_a, project_id=project_a)
            values["id"] = invocation_id
            connection.execute(tables.model_invocations.insert(), values)

            invalid_invocations = (
                {"total_tokens": 21},
                {"status": "succeeded", "error_code": "unexpected"},
                {"status": "provider_error", "error_code": None},
                {"protocol": "vendor-magic"},
                {"tenant_id": tenant_b, "project_id": project_a},
            )
            for overrides in invalid_invocations:
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(
                        tables.model_invocations.insert(),
                        {**valid_invocation(tenant_a), **overrides, "id": uuid4()},
                    )

        with engine.begin() as connection, pytest.raises(DBAPIError):
            connection.execute(
                update(tables.model_invocations)
                .where(tables.model_invocations.c.id == invocation_id)
                .values(total_tokens=999)
            )
        with engine.begin() as connection, pytest.raises(DBAPIError):
            connection.execute(
                tables.model_invocations.delete().where(
                    tables.model_invocations.c.id == invocation_id
                )
            )
        with engine.connect() as connection:
            assert (
                connection.execute(
                    select(tables.model_invocations.c.total_tokens).where(
                        tables.model_invocations.c.id == invocation_id
                    )
                ).scalar_one()
                == 20
            )
    finally:
        engine.dispose()


def test_model_gateway_migration_round_trip(model_gateway_database_url: str) -> None:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    engine = create_engine(psycopg_database_url(model_gateway_database_url))
    try:
        command.downgrade(config, "0007_work_item_lifecycle")
        assert inspect(engine).get_table_names(schema="cehub_ai") == []
        command.upgrade(config, "head")
        assert set(inspect(engine).get_table_names(schema="cehub_ai")) == {
            "model_invocations",
            "tenant_model_settings",
        }
    finally:
        command.upgrade(config, "head")
        engine.dispose()
