"""widen finding apply-target whitelist for tiered authorization (vNext V1-C1, D32/D16)

Revision ID: 0044_apply_target_whitelist
Revises: 0043_task_action_contract
Create Date: 2026-08-26 20:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0044_apply_target_whitelist"
down_revision: str | Sequence[str] | None = "0043_task_action_contract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AI_SCHEMA = "cehub_ai"
_PREFIX = (
    "(status <> 'applied' AND applied_by_user_id IS NULL AND applied_at IS NULL "
    "AND applied_entity_type IS NULL AND applied_entity_id IS NULL) OR "
    "(status = 'applied' AND applied_by_user_id IS NOT NULL AND applied_at IS NOT NULL "
)
_SUFFIX = " AND applied_entity_id IS NOT NULL AND reviewed_at < applied_at)"
_OLD = _PREFIX + "AND applied_entity_type IN ('risk', 'memory')" + _SUFFIX
_NEW = (
    _PREFIX + "AND applied_entity_type IN ('risk', 'memory', 'issue', 'task', 'test_run', "
    "'sample_build_configuration', 'knowledge_candidate', 'schedule_change_proposal', "
    "'material_exception')" + _SUFFIX
)


def _swap(expression: str) -> None:
    op.drop_constraint(
        op.f("ck_findings_apply_lifecycle_consistent"),
        "findings",
        schema=AI_SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_findings_apply_lifecycle_consistent"),
        "findings",
        expression,
        schema=AI_SCHEMA,
    )


def upgrade() -> None:
    _swap(_NEW)


def downgrade() -> None:
    import sqlalchemy as sa

    connection = op.get_bind()
    widened_rows = connection.execute(
        sa.text(
            f"SELECT count(*) FROM {AI_SCHEMA}.findings "
            "WHERE applied_entity_type IS NOT NULL "
            "AND applied_entity_type NOT IN ('risk', 'memory')"
        )
    ).scalar_one()
    if widened_rows:
        raise RuntimeError(
            "refusing downgrade while findings applied to widened target types exist"
        )
    _swap(_OLD)
