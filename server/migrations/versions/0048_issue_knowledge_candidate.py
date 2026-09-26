"""issue closure knowledge candidate (vNext V1-B7)

Revision ID: 0048_issue_knowledge_candidate
Revises: 0047_organization_model
Create Date: 2026-08-27 21:12:45.180769
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0048_issue_knowledge_candidate"
down_revision: str | Sequence[str] | None = "0047_organization_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MEMORY_SCHEMA = "cehub_memory"

# Autogenerate compares check constraints by name only, so the widened
# expression has to be swapped explicitly.
_SOURCE_EXCLUSIVE_OLD = "source_finding_id IS NULL OR source_ncr_id IS NULL"
_SOURCE_EXCLUSIVE_NEW = (
    "(CASE WHEN source_finding_id IS NULL THEN 0 ELSE 1 END) "
    "+ (CASE WHEN source_ncr_id IS NULL THEN 0 ELSE 1 END) "
    "+ (CASE WHEN source_issue_id IS NULL THEN 0 ELSE 1 END) <= 1"
)


def _swap_source_check(expression: str) -> None:
    op.drop_constraint(
        op.f("ck_memories_source_mutually_exclusive"),
        "memories",
        schema=MEMORY_SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_memories_source_mutually_exclusive"),
        "memories",
        expression,
        schema=MEMORY_SCHEMA,
    )


def upgrade() -> None:
    op.add_column(
        "memories", sa.Column("source_issue_id", sa.Uuid(), nullable=True), schema=MEMORY_SCHEMA
    )
    op.create_unique_constraint(
        "uq_memories_tenant_issue",
        "memories",
        ["tenant_id", "source_issue_id"],
        schema=MEMORY_SCHEMA,
    )
    op.create_foreign_key(
        "fk_memories_tenant_project_issue",
        "memories",
        "issues",
        ["tenant_id", "project_id", "source_issue_id"],
        ["tenant_id", "project_id", "id"],
        source_schema=MEMORY_SCHEMA,
        referent_schema="cehub_project",
        ondelete="RESTRICT",
    )
    _swap_source_check(_SOURCE_EXCLUSIVE_NEW)


def downgrade() -> None:
    connection = op.get_bind()
    issue_sourced = connection.execute(
        sa.text(f"SELECT count(*) FROM {MEMORY_SCHEMA}.memories WHERE source_issue_id IS NOT NULL")
    ).scalar_one()
    if issue_sourced:
        raise RuntimeError(
            "refusing downgrade while Issue-sourced knowledge candidates exist; "
            "the source link would be silently lost"
        )
    _swap_source_check(_SOURCE_EXCLUSIVE_OLD)
    op.drop_constraint(
        "fk_memories_tenant_project_issue", "memories", schema=MEMORY_SCHEMA, type_="foreignkey"
    )
    op.drop_constraint("uq_memories_tenant_issue", "memories", schema=MEMORY_SCHEMA, type_="unique")
    op.drop_column("memories", "source_issue_id", schema=MEMORY_SCHEMA)
