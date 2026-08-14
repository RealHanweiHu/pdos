"""add tenant model governance and immutable invocation trace

Revision ID: 0008_model_gateway
Revises: 0007_work_item_lifecycle
Create Date: 2026-08-11 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "0008_model_gateway"
down_revision: str | Sequence[str] | None = "0007_work_item_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AI_SCHEMA = "cehub_ai"
CORE_SCHEMA = "cehub_core"
PROJECT_SCHEMA = "cehub_project"


def upgrade() -> None:
    op.create_table(
        "tenant_model_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "provider",
            sa.String(length=32),
            server_default=sa.text("'minimax'"),
            nullable=False,
        ),
        sa.Column(
            "model",
            sa.String(length=128),
            server_default=sa.text("'MiniMax-M2.7'"),
            nullable=False,
        ),
        sa.Column(
            "daily_token_budget",
            sa.BigInteger(),
            server_default=sa.text("2000000"),
            nullable=False,
        ),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
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
            "provider IN ('minimax', 'deepseek', 'glm', 'openai', 'anthropic')",
            name=op.f("ck_tenant_model_settings_provider_allowed"),
        ),
        sa.CheckConstraint(
            "btrim(model) <> ''",
            name=op.f("ck_tenant_model_settings_model_nonblank"),
        ),
        sa.CheckConstraint(
            "daily_token_budget BETWEEN 1 AND 1000000000",
            name=op.f("ck_tenant_model_settings_daily_budget_range"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{CORE_SCHEMA}.tenants.id"],
            name=op.f("fk_tenant_model_settings_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "updated_by_user_id"],
            [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
            name="fk_tenant_model_settings_tenant_updater",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_model_settings")),
        sa.UniqueConstraint(
            "tenant_id",
            name="uq_tenant_model_settings_tenant_id",
        ),
        schema=AI_SCHEMA,
    )

    op.create_table(
        "model_invocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("agent_key", sa.String(length=64), nullable=False),
        sa.Column(
            "agent_tier",
            sa.String(length=32),
            server_default=sa.text("'default'"),
            nullable=False,
        ),
        sa.Column("prompt_version", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=True),
        sa.Column("protocol", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("latency_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "normalized_cost_microusd",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "structured_attempts",
            sa.SmallInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider IN ('minimax', 'deepseek', 'glm', 'openai', 'anthropic')",
            name=op.f("ck_model_invocations_provider_allowed"),
        ),
        sa.CheckConstraint(
            "protocol IN ('openai-compatible', 'anthropic-native')",
            name=op.f("ck_model_invocations_protocol_allowed"),
        ),
        sa.CheckConstraint(
            "agent_tier IN ('default', 'extraction', 'reasoning')",
            name=op.f("ck_model_invocations_agent_tier_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'provider_error', 'schema_error', 'budget_exceeded')",
            name=op.f("ck_model_invocations_status_allowed"),
        ),
        sa.CheckConstraint(
            "btrim(agent_key) <> ''",
            name=op.f("ck_model_invocations_agent_key_nonblank"),
        ),
        sa.CheckConstraint(
            "btrim(prompt_version) <> ''",
            name=op.f("ck_model_invocations_prompt_version_nonblank"),
        ),
        sa.CheckConstraint(
            "btrim(model) <> ''",
            name=op.f("ck_model_invocations_model_nonblank"),
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND total_tokens >= 0 "
            "AND total_tokens = input_tokens + output_tokens",
            name=op.f("ck_model_invocations_token_totals_consistent"),
        ),
        sa.CheckConstraint(
            "latency_ms >= 0",
            name=op.f("ck_model_invocations_latency_nonnegative"),
        ),
        sa.CheckConstraint(
            "normalized_cost_microusd >= 0",
            name=op.f("ck_model_invocations_cost_nonnegative"),
        ),
        sa.CheckConstraint(
            "structured_attempts BETWEEN 0 AND 3",
            name=op.f("ck_model_invocations_structured_attempts_range"),
        ),
        sa.CheckConstraint(
            "(status = 'succeeded' AND error_code IS NULL) OR "
            "(status <> 'succeeded' AND error_code IS NOT NULL AND btrim(error_code) <> '')",
            name=op.f("ck_model_invocations_error_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{CORE_SCHEMA}.tenants.id"],
            name=op.f("fk_model_invocations_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
            name="fk_model_invocations_tenant_project",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_invocations")),
        schema=AI_SCHEMA,
    )
    op.create_index(
        "ix_model_invocations_tenant_created",
        "model_invocations",
        ["tenant_id", "created_at", "id"],
        unique=False,
        schema=AI_SCHEMA,
    )
    op.create_index(
        "ix_model_invocations_tenant_agent_created",
        "model_invocations",
        ["tenant_id", "agent_key", "created_at", "id"],
        unique=False,
        schema=AI_SCHEMA,
    )
    op.create_index(
        "ix_model_invocations_tenant_project_created",
        "model_invocations",
        ["tenant_id", "project_id", "created_at", "id"],
        unique=False,
        schema=AI_SCHEMA,
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION cehub_ai.reject_model_invocation_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'cehub_ai.model_invocations is append-only';
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER model_invocations_immutable
            BEFORE UPDATE OR DELETE ON cehub_ai.model_invocations
            FOR EACH ROW EXECUTE FUNCTION cehub_ai.reject_model_invocation_mutation()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER model_invocations_immutable ON cehub_ai.model_invocations"))
    op.execute(sa.text("DROP FUNCTION cehub_ai.reject_model_invocation_mutation()"))
    op.drop_index(
        "ix_model_invocations_tenant_project_created",
        table_name="model_invocations",
        schema=AI_SCHEMA,
    )
    op.drop_index(
        "ix_model_invocations_tenant_agent_created",
        table_name="model_invocations",
        schema=AI_SCHEMA,
    )
    op.drop_index(
        "ix_model_invocations_tenant_created",
        table_name="model_invocations",
        schema=AI_SCHEMA,
    )
    op.drop_table("model_invocations", schema=AI_SCHEMA)
    op.drop_table("tenant_model_settings", schema=AI_SCHEMA)
