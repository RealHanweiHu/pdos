"""candidate dismissal marker for free-zone one-click ignore (vNext V1-C1, D32)

Revision ID: 0045_candidate_dismissal
Revises: 0044_apply_target_whitelist
Create Date: 2026-08-26 20:05:15.013372
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045_candidate_dismissal"
down_revision: str | Sequence[str] | None = "0044_apply_target_whitelist"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROJECT_SCHEMA = "cehub_project"


def upgrade() -> None:
    op.add_column(
        "risks",
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_risks_dismissed_only_when_cleared"),
        "risks",
        "dismissed_at IS NULL OR draft_state = 'cleared'",
        schema=PROJECT_SCHEMA,
    )


def downgrade() -> None:
    connection = op.get_bind()
    dismissed_rows = connection.execute(
        sa.text(f"SELECT count(*) FROM {PROJECT_SCHEMA}.risks WHERE dismissed_at IS NOT NULL")
    ).scalar_one()
    if dismissed_rows:
        raise RuntimeError(
            "refusing downgrade while dismissed risk candidates exist; "
            "clear dismissed_at explicitly first"
        )
    op.drop_constraint(
        op.f("ck_risks_dismissed_only_when_cleared"),
        "risks",
        schema=PROJECT_SCHEMA,
        type_="check",
    )
    op.drop_column("risks", "dismissed_at", schema=PROJECT_SCHEMA)
