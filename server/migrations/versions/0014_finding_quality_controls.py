"""add finding quality telemetry and output controls

Revision ID: 0014_finding_quality_controls
Revises: 0013_ai_api_documents
Create Date: 2026-08-12 08:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_finding_quality_controls"
down_revision: str | Sequence[str] | None = "0013_ai_api_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AI_SCHEMA = "cehub_ai"
CORE_SCHEMA = "cehub_core"


def upgrade() -> None:
    op.create_table(
        "finding_quality_controls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("agent_key", sa.String(length=64), nullable=False),
        sa.Column("finding_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column(
            "minimum_review_count",
            sa.SmallInteger(),
            server_default=sa.text("5"),
            nullable=False,
        ),
        sa.Column(
            "acceptance_threshold_basis_points",
            sa.SmallInteger(),
            server_default=sa.text("5000"),
            nullable=False,
        ),
        sa.Column("reviewed_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("accepted_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("applied_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("narrowed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("narrowed_reason", sa.String(length=256), nullable=True),
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
            "(agent_key = 'project_intelligence' AND finding_type IN "
            "('risk_suggestion', 'blocker_alert', 'gate_readiness_anomaly')) OR "
            "(agent_key = 'knowledge_lite' AND finding_type = 'knowledge_draft')",
            name=op.f("ck_finding_quality_controls_type_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'narrowed')",
            name=op.f("ck_finding_quality_controls_status_allowed"),
        ),
        sa.CheckConstraint(
            "minimum_review_count BETWEEN 1 AND 1000",
            name=op.f("ck_finding_quality_controls_minimum_reviews_range"),
        ),
        sa.CheckConstraint(
            "acceptance_threshold_basis_points BETWEEN 0 AND 10000",
            name=op.f("ck_finding_quality_controls_threshold_range"),
        ),
        sa.CheckConstraint(
            "reviewed_count >= 0 AND accepted_count BETWEEN 0 AND reviewed_count "
            "AND applied_count BETWEEN 0 AND accepted_count",
            name=op.f("ck_finding_quality_controls_counts_consistent"),
        ),
        sa.CheckConstraint(
            "(status = 'active' AND narrowed_at IS NULL AND narrowed_reason IS NULL) OR "
            "(status = 'narrowed' AND narrowed_at IS NOT NULL "
            "AND narrowed_reason IS NOT NULL AND btrim(narrowed_reason) <> '')",
            name=op.f("ck_finding_quality_controls_narrowing_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{CORE_SCHEMA}.tenants.id"],
            name=op.f("fk_finding_quality_controls_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_finding_quality_controls")),
        sa.UniqueConstraint(
            "tenant_id",
            "agent_key",
            "finding_type",
            name="uq_finding_quality_controls_tenant_agent_type",
        ),
        schema=AI_SCHEMA,
    )
    op.create_index(
        "ix_finding_quality_controls_tenant_status",
        "finding_quality_controls",
        ["tenant_id", "status", "agent_key", "finding_type"],
        unique=False,
        schema=AI_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_finding_quality_controls_tenant_status",
        table_name="finding_quality_controls",
        schema=AI_SCHEMA,
    )
    op.drop_table("finding_quality_controls", schema=AI_SCHEMA)
