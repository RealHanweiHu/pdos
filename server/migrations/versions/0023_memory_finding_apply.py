"""allow accepted knowledge findings to apply into memory drafts

Revision ID: 0023_memory_finding_apply
Revises: 0022_memory_search
Create Date: 2026-08-12 22:40:00.000000
"""

from collections.abc import Sequence

from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "0023_memory_finding_apply"
down_revision: str | Sequence[str] | None = "0022_memory_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_findings_apply_lifecycle_consistent"),
        "findings",
        schema="cehub_ai",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_findings_apply_lifecycle_consistent"),
        "findings",
        "(status <> 'applied' AND applied_by_user_id IS NULL AND applied_at IS NULL "
        "AND applied_entity_type IS NULL AND applied_entity_id IS NULL) OR "
        "(status = 'applied' AND applied_by_user_id IS NOT NULL AND applied_at IS NOT NULL "
        "AND applied_entity_type IN ('risk', 'memory') AND applied_entity_id IS NOT NULL "
        "AND reviewed_at < applied_at)",
        schema="cehub_ai",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_findings_apply_lifecycle_consistent"),
        "findings",
        schema="cehub_ai",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_findings_apply_lifecycle_consistent"),
        "findings",
        "(status <> 'applied' AND applied_by_user_id IS NULL AND applied_at IS NULL "
        "AND applied_entity_type IS NULL AND applied_entity_id IS NULL) OR "
        "(status = 'applied' AND applied_by_user_id IS NOT NULL AND applied_at IS NOT NULL "
        "AND applied_entity_type = 'risk' AND applied_entity_id IS NOT NULL "
        "AND reviewed_at < applied_at)",
        schema="cehub_ai",
    )
