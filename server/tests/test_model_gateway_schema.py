from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
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
from tests.db_cleanup import clear_test_tenants
from tests.migration_fixtures import migrate_test_database_in_steps

SERVER_ROOT = Path(__file__).resolve().parents[1]


def constraint_names(table: Table, constraint_type: type[Constraint]) -> set[str]:
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, constraint_type) and isinstance(constraint.name, str)
    }


def check_constraint_sql(table: Table, name: str) -> str:
    return next(
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name == name
    )


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
    settings_provider_sql = check_constraint_sql(
        tables.tenant_model_settings,
        "ck_tenant_model_settings_provider_allowed",
    )
    assert "'openrouter'" in settings_provider_sql
    assert "'opencode_go'" in settings_provider_sql

    assert set(tables.model_invocations.c.keys()) == {
        "id",
        "tenant_id",
        "project_id",
        "run_id",
        "request_id",
        "budget_call_id",
        "model_call_session_id",
        "context_receipt_id",
        "usage_status",
        "input_meter_version",
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
        "cache_read_tokens",
        "cache_creation_tokens",
        "latency_ms",
        "normalized_cost_microusd",
        "cost_status",
        "rate_card_snapshot",
        "structured_attempts",
        "error_code",
        "created_at",
    }
    assert {
        "ck_model_invocations_provider_allowed",
        "ck_model_invocations_protocol_allowed",
        "ck_model_invocations_status_allowed",
        "ck_model_invocations_token_totals_consistent",
        "ck_model_invocations_cache_tokens_nonnegative",
        "ck_model_invocations_error_consistent",
        "ck_model_invocations_structured_attempts_range",
    } <= constraint_names(tables.model_invocations, CheckConstraint)
    assert "fk_model_invocations_tenant_project" in constraint_names(
        tables.model_invocations, ForeignKeyConstraint
    )
    invocation_provider_sql = check_constraint_sql(
        tables.model_invocations,
        "ck_model_invocations_provider_allowed",
    )
    assert "'openrouter'" in invocation_provider_sql
    assert "'opencode_go'" in invocation_provider_sql
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
            clear_test_tenants(connection)
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


def test_database_persists_openrouter_and_opencode_go_audit_identities(
    model_gateway_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(model_gateway_database_url))
    tenant_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": tenant_id, "slug": "aggregators", "name": "Aggregators"},
            )
            connection.execute(
                tables.tenant_model_settings.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "provider": "openrouter",
                    "model": "openai/gpt-5.2",
                    "daily_token_budget": 2_000_000,
                },
            )
            invocation = valid_invocation(tenant_id)
            invocation.update(
                {
                    "provider": "opencode_go",
                    "model": "deepseek-v4-flash",
                }
            )
            connection.execute(tables.model_invocations.insert(), invocation)

        with engine.connect() as connection:
            assert (
                connection.execute(
                    select(tables.tenant_model_settings.c.provider).where(
                        tables.tenant_model_settings.c.tenant_id == tenant_id
                    )
                ).scalar_one()
                == "openrouter"
            )
            assert (
                connection.execute(
                    select(tables.model_invocations.c.provider).where(
                        tables.model_invocations.c.tenant_id == tenant_id
                    )
                ).scalar_one()
                == "opencode_go"
            )
    finally:
        engine.dispose()


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
        migrate_test_database_in_steps(config, engine, "0007_work_item_lifecycle")
        assert inspect(engine).get_table_names(schema="cehub_ai") == []
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT to_regprocedure('cehub_ai.claim_agent_run(timestamptz)')")
                )
                is None
            )
        migrate_test_database_in_steps(config, engine, "0009_invocation_cache_tokens")
        assert set(inspect(engine).get_table_names(schema="cehub_ai")) == {
            "model_invocations",
            "tenant_model_settings",
        }
    finally:
        try:
            migrate_test_database_in_steps(config, engine, "head")
        finally:
            engine.dispose()


def test_cost_migration_preserves_legacy_trace_and_refuses_evidence_loss(
    model_gateway_database_url: str,
) -> None:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    engine = create_engine(psycopg_database_url(model_gateway_database_url))
    tenant_id = uuid4()
    old = valid_invocation(tenant_id)
    try:
        command.downgrade(config, "0058_ai_test_plan_changes")
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {
                    "id": tenant_id,
                    "slug": "cost-history",
                    "name": "Cost history",
                },
            )
            # Explicit columns support the prior schema without the new fields.
            connection.execute(tables.model_invocations.insert(), old)
        command.upgrade(config, "head")
        with engine.connect() as connection:
            row = connection.execute(select(tables.model_invocations)).mappings().one()
            assert row["id"] == old["id"]
            assert row["normalized_cost_microusd"] == 15
            assert row["cost_status"] == "legacy_unverified"
            assert row["rate_card_snapshot"] is None
        # With only old evidence the migration is reversible.
        command.downgrade(config, "0058_ai_test_plan_changes")
        command.upgrade(config, "head")
        new = valid_invocation(tenant_id)
        new.update(normalized_cost_microusd=None, cost_status="unknown")
        with engine.begin() as connection:
            connection.execute(tables.model_invocations.insert(), new)
        with pytest.raises(RuntimeError, match="refusing downgrade: cost evidence"):
            command.downgrade(config, "0058_ai_test_plan_changes")
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == ScriptDirectory.from_config(config).get_current_head()
            )
        with pytest.raises(DBAPIError, match="append-only"), engine.begin() as connection:
            connection.execute(update(tables.model_invocations).values(normalized_cost_microusd=0))
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "changes",
    [
        {"cost_status": "unknown", "normalized_cost_microusd": 0},
        {"cost_status": "priced", "normalized_cost_microusd": 0},
        {"cost_status": "priced", "normalized_cost_microusd": 0, "rate_card_snapshot": {}},
        {"cost_status": "not_invoked", "normalized_cost_microusd": 0},
        {"cost_status": "invented", "normalized_cost_microusd": None},
    ],
)
def test_database_rejects_inconsistent_cost_evidence(
    model_gateway_database_url: str,
    changes: dict[str, object],
) -> None:
    engine = create_engine(psycopg_database_url(model_gateway_database_url))
    tenant_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": tenant_id, "slug": "cost-constraint", "name": "Cost"},
            )
        record = valid_invocation(tenant_id)
        record.update(changes)
        with (
            pytest.raises(IntegrityError, match="cost_evidence_consistent"),
            engine.begin() as connection,
        ):
            connection.execute(tables.model_invocations.insert(), record)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "invalid",
    [
        {"normalized_cost_microusd": None},
        {"input_tokens": 1, "total_tokens": 1},
        {"cache_read_tokens": 1},
        {"cache_creation_tokens": 1},
        {"structured_attempts": 1},
        {"error_code": "PROVIDER_TRANSPORT_ERROR"},
        None,
    ],
)
def test_provider_admission_zero_cost_requires_zero_call_evidence(
    model_gateway_database_url: str, invalid: dict[str, object] | None
) -> None:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    engine = create_engine(psycopg_database_url(model_gateway_database_url))
    tenant_id = uuid4()
    record = valid_invocation(tenant_id)
    record.update(
        status="provider_error",
        error_code="PROVIDER_OUTPUT_LIMIT_UNCONFIGURED",
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        structured_attempts=0,
        normalized_cost_microusd=0,
        cost_status="not_invoked",
    )
    try:
        if invalid is None:
            # Empty upgrade/downgrade roundtrip must also preserve this constraint.
            command.downgrade(config, "0060_budget_reservations")
            command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {
                    "id": tenant_id,
                    "slug": "admission-cost",
                    "name": "Admission cost",
                },
            )
        if invalid is not None:
            record.update(invalid)
            with (
                pytest.raises(IntegrityError, match="cost_evidence_consistent"),
                engine.begin() as connection,
            ):
                connection.execute(tables.model_invocations.insert(), record)
        else:
            with engine.begin() as connection:
                connection.execute(tables.model_invocations.insert(), record)
            with pytest.raises(
                RuntimeError, match="refusing downgrade: provider admission evidence"
            ):
                command.downgrade(config, "0060_budget_reservations")
            with engine.connect() as connection:
                assert (
                    connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                    == ScriptDirectory.from_config(config).get_current_head()
                )
                persisted = connection.execute(select(tables.model_invocations)).mappings().one()
                assert persisted["id"] == record["id"]
                assert persisted["cost_status"] == "not_invoked"
    finally:
        engine.dispose()
