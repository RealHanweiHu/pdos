"""Preserve per-plan test baseline and stable case identity."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0057_test_template_snapshot"
down_revision: str | Sequence[str] | None = "0056_meeting_recurrence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "test_plans",
        sa.Column("template_snapshot", postgresql.JSONB(), nullable=True),
        schema="cehub_quality",
    )
    op.create_check_constraint(
        op.f("ck_test_plans_template_snapshot_object"),
        "test_plans",
        "template_snapshot IS NULL OR jsonb_typeof(template_snapshot) = 'object'",
        schema="cehub_quality",
    )
    op.add_column(
        "test_cases",
        sa.Column("template_item_key", sa.String(128), nullable=True),
        schema="cehub_quality",
    )
    op.create_unique_constraint(
        "uq_test_cases_tenant_plan_template_item",
        "test_cases",
        ["tenant_id", "plan_id", "template_item_key"],
        schema="cehub_quality",
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM cehub_quality.test_plans "
                "WHERE template_snapshot IS NOT NULL) "
                "OR EXISTS (SELECT 1 FROM cehub_quality.test_cases "
                "WHERE template_item_key IS NOT NULL)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("refusing downgrade: test template snapshots or case bindings exist")
    op.drop_constraint(
        "uq_test_cases_tenant_plan_template_item",
        "test_cases",
        type_="unique",
        schema="cehub_quality",
    )
    op.drop_column("test_cases", "template_item_key", schema="cehub_quality")
    op.drop_constraint(
        op.f("ck_test_plans_template_snapshot_object"),
        "test_plans",
        type_="check",
        schema="cehub_quality",
    )
    op.drop_column("test_plans", "template_snapshot", schema="cehub_quality")
