"""add dispatcher control plane and Agent run records

Revision ID: 0010_agent_runtime
Revises: 0009_invocation_cache_tokens
Create Date: 2026-08-11 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_agent_runtime"
down_revision: str | Sequence[str] | None = "0009_invocation_cache_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AI_SCHEMA = "cehub_ai"
CORE_SCHEMA = "cehub_core"
PROJECT_SCHEMA = "cehub_project"


def upgrade() -> None:
    op.create_table(
        "agent_dispatcher_cursors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("consumer_key", sa.String(length=64), nullable=False),
        sa.Column(
            "last_event_row_id",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(consumer_key) <> ''",
            name=op.f("ck_agent_dispatcher_cursors_consumer_key_nonblank"),
        ),
        sa.CheckConstraint(
            "last_event_row_id >= 0",
            name=op.f("ck_agent_dispatcher_cursors_last_event_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{CORE_SCHEMA}.tenants.id"],
            name=op.f("fk_agent_dispatcher_cursors_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_dispatcher_cursors")),
        sa.UniqueConstraint(
            "tenant_id",
            "consumer_key",
            name="uq_agent_dispatcher_cursors_tenant_consumer",
        ),
        schema=AI_SCHEMA,
    )

    op.create_table(
        "agent_subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("agent_key", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "consecutive_failure_count",
            sa.SmallInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "failure_threshold",
            sa.SmallInteger(),
            server_default=sa.text("3"),
            nullable=False,
        ),
        sa.Column("paused_reason", sa.String(length=256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "agent_key IN ('project_intelligence', 'knowledge_lite')",
            name=op.f("ck_agent_subscriptions_agent_key_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'paused')",
            name=op.f("ck_agent_subscriptions_status_allowed"),
        ),
        sa.CheckConstraint(
            "consecutive_failure_count >= 0",
            name=op.f("ck_agent_subscriptions_failure_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "failure_threshold BETWEEN 1 AND 20",
            name=op.f("ck_agent_subscriptions_failure_threshold_range"),
        ),
        sa.CheckConstraint(
            "(status = 'active' AND paused_reason IS NULL) OR "
            "(status = 'paused' AND paused_reason IS NOT NULL AND btrim(paused_reason) <> '')",
            name=op.f("ck_agent_subscriptions_pause_reason_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{CORE_SCHEMA}.tenants.id"],
            name=op.f("fk_agent_subscriptions_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_subscriptions")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_agent_subscriptions_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            "agent_key",
            name="uq_agent_subscriptions_tenant_id_agent",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "agent_key",
            name="uq_agent_subscriptions_tenant_agent",
        ),
        schema=AI_SCHEMA,
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.Column("agent_key", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'debouncing'"),
            nullable=False,
        ),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_event_row_id", sa.BigInteger(), nullable=False),
        sa.Column("last_event_row_id", sa.BigInteger(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("event_row_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "context_version",
            sa.String(length=64),
            server_default=sa.text("'run-context-v1'"),
            nullable=False,
        ),
        sa.Column(
            "run_context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "agent_key IN ('project_intelligence', 'knowledge_lite')",
            name=op.f("ck_agent_runs_agent_key_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('debouncing', 'queued', 'running', 'succeeded', 'degraded', 'failed')",
            name=op.f("ck_agent_runs_status_allowed"),
        ),
        sa.CheckConstraint(
            "window_started_at <= window_ended_at",
            name=op.f("ck_agent_runs_window_order"),
        ),
        sa.CheckConstraint(
            "CASE WHEN jsonb_typeof(event_row_ids) = 'array' THEN "
            "event_count > 0 AND first_event_row_id > 0 "
            "AND last_event_row_id >= first_event_row_id "
            "AND jsonb_array_length(event_row_ids) = event_count "
            "AND (event_row_ids->>0)::bigint = first_event_row_id "
            "AND (event_row_ids->>(event_count - 1))::bigint = last_event_row_id "
            "ELSE false END",
            name=op.f("ck_agent_runs_event_bounds_consistent"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(event_row_ids) = 'array'",
            name=op.f("ck_agent_runs_event_ids_array"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(run_context) = 'object'",
            name=op.f("ck_agent_runs_context_object"),
        ),
        sa.CheckConstraint(
            "btrim(context_version) <> ''",
            name=op.f("ck_agent_runs_context_version_nonblank"),
        ),
        sa.CheckConstraint(
            "(status IN ('debouncing', 'queued') AND started_at IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL) OR "
            "(status IN ('succeeded', 'degraded', 'failed') "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL)",
            name=op.f("ck_agent_runs_lifecycle_consistent"),
        ),
        sa.CheckConstraint(
            "(status IN ('degraded', 'failed') AND error_code IS NOT NULL "
            "AND btrim(error_code) <> '') OR "
            "(status NOT IN ('degraded', 'failed') AND error_code IS NULL)",
            name=op.f("ck_agent_runs_error_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{CORE_SCHEMA}.tenants.id"],
            name=op.f("fk_agent_runs_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
            name="fk_agent_runs_tenant_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "subscription_id", "agent_key"],
            [
                f"{AI_SCHEMA}.agent_subscriptions.tenant_id",
                f"{AI_SCHEMA}.agent_subscriptions.id",
                f"{AI_SCHEMA}.agent_subscriptions.agent_key",
            ],
            name="fk_agent_runs_tenant_subscription_agent",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_agent_runs_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "agent_key",
            "window_started_at",
            name="uq_agent_runs_tenant_project_agent_window",
        ),
        schema=AI_SCHEMA,
    )
    op.create_index(
        "ix_agent_runs_tenant_status_created",
        "agent_runs",
        ["tenant_id", "status", "created_at", "id"],
        unique=False,
        schema=AI_SCHEMA,
    )
    op.create_index(
        "ix_agent_runs_tenant_project_created",
        "agent_runs",
        ["tenant_id", "project_id", "created_at", "id"],
        unique=False,
        schema=AI_SCHEMA,
    )
    op.create_index(
        "ix_agent_runs_tenant_agent_created",
        "agent_runs",
        ["tenant_id", "agent_key", "created_at", "id"],
        unique=False,
        schema=AI_SCHEMA,
    )
    # Pre-S2-2 gateway calls may carry a run-shaped correlation UUID without an
    # Agent run row. They remain valid historical traces but cannot satisfy the
    # new tenant-safe run foreign key. The append-only trigger is disabled only
    # inside this transactional migration; any failure rolls the trigger state
    # back with the data change.
    op.execute(
        sa.text(
            "ALTER TABLE cehub_ai.model_invocations DISABLE TRIGGER model_invocations_immutable"
        )
    )
    op.execute(sa.text("UPDATE cehub_ai.model_invocations SET run_id = NULL"))
    op.execute(
        sa.text("ALTER TABLE cehub_ai.model_invocations ENABLE TRIGGER model_invocations_immutable")
    )
    op.create_foreign_key(
        "fk_model_invocations_tenant_run",
        "model_invocations",
        "agent_runs",
        ["tenant_id", "run_id"],
        ["tenant_id", "id"],
        source_schema=AI_SCHEMA,
        referent_schema=AI_SCHEMA,
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_model_invocations_tenant_run",
        "model_invocations",
        type_="foreignkey",
        schema=AI_SCHEMA,
    )
    op.drop_index(
        "ix_agent_runs_tenant_agent_created",
        table_name="agent_runs",
        schema=AI_SCHEMA,
    )
    op.drop_index(
        "ix_agent_runs_tenant_project_created",
        table_name="agent_runs",
        schema=AI_SCHEMA,
    )
    op.drop_index(
        "ix_agent_runs_tenant_status_created",
        table_name="agent_runs",
        schema=AI_SCHEMA,
    )
    op.drop_table("agent_runs", schema=AI_SCHEMA)
    op.drop_table("agent_subscriptions", schema=AI_SCHEMA)
    op.drop_table("agent_dispatcher_cursors", schema=AI_SCHEMA)
