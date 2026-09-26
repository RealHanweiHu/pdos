"""rule-based risk candidates: draft state, origin key, source refs (vNext V1-A6)

Revision ID: 0035_risk_candidates
Revises: 0034_issue_accountability
Create Date: 2026-08-25 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035_risk_candidates"
down_revision: str | Sequence[str] | None = "0034_issue_accountability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROJECT_SCHEMA = "cehub_project"


def upgrade() -> None:
    op.add_column(
        "risks",
        sa.Column(
            "draft_state",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'confirmed'"),
        ),
        schema=PROJECT_SCHEMA,
    )
    op.add_column(
        "risks",
        sa.Column("origin_key", sa.String(length=128), nullable=True),
        schema=PROJECT_SCHEMA,
    )
    op.add_column(
        "risks", sa.Column("rule_key", sa.String(length=64), nullable=True), schema=PROJECT_SCHEMA
    )
    op.add_column(
        "risks",
        sa.Column("source_entity", sa.String(length=64), nullable=True),
        schema=PROJECT_SCHEMA,
    )
    op.add_column(
        "risks", sa.Column("source_entity_id", sa.Uuid(), nullable=True), schema=PROJECT_SCHEMA
    )
    op.create_check_constraint(
        op.f("ck_risks_draft_state_allowed"),
        "risks",
        "draft_state IN ('draft', 'confirmed', 'cleared')",
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_risks_manual_risks_confirmed"),
        "risks",
        "origin_key IS NOT NULL OR draft_state = 'confirmed'",
        schema=PROJECT_SCHEMA,
    )
    op.create_index(
        "uq_risks_tenant_origin_key",
        "risks",
        ["tenant_id", "origin_key"],
        unique=True,
        schema=PROJECT_SCHEMA,
        postgresql_where=sa.text("origin_key IS NOT NULL"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    candidate_rows = connection.execute(
        sa.text(
            f"SELECT count(*) FROM {PROJECT_SCHEMA}.risks "
            "WHERE origin_key IS NOT NULL OR draft_state <> 'confirmed'"
        )
    ).scalar_one()
    if candidate_rows:
        raise RuntimeError("refusing lossy downgrade while rule-based risk candidates exist")

    op.drop_index(
        "uq_risks_tenant_origin_key",
        table_name="risks",
        schema=PROJECT_SCHEMA,
        postgresql_where=sa.text("origin_key IS NOT NULL"),
    )
    op.drop_constraint(
        op.f("ck_risks_manual_risks_confirmed"), "risks", schema=PROJECT_SCHEMA, type_="check"
    )
    op.drop_constraint(
        op.f("ck_risks_draft_state_allowed"), "risks", schema=PROJECT_SCHEMA, type_="check"
    )
    op.drop_column("risks", "source_entity_id", schema=PROJECT_SCHEMA)
    op.drop_column("risks", "source_entity", schema=PROJECT_SCHEMA)
    op.drop_column("risks", "rule_key", schema=PROJECT_SCHEMA)
    op.drop_column("risks", "origin_key", schema=PROJECT_SCHEMA)
    op.drop_column("risks", "draft_state", schema=PROJECT_SCHEMA)
