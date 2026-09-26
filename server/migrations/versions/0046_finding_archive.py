"""finding TTL archive/restore states for review-fatigue governance (vNext V1-A10)

Revision ID: 0046_finding_archive
Revises: 0045_candidate_dismissal
Create Date: 2026-08-26 21:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046_finding_archive"
down_revision: str | Sequence[str] | None = "0045_candidate_dismissal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AI_SCHEMA = "cehub_ai"

_STATUS_OLD = "status IN ('pending_review', 'accepted', 'rejected', 'applied')"
_STATUS_NEW = "status IN ('pending_review', 'accepted', 'rejected', 'applied', 'archived')"

_REVIEW_BASE = (
    "(status = 'pending_review' AND reviewed_by_user_id IS NULL "
    "AND reviewed_at IS NULL AND accepted_payload IS NULL) OR "
    "(status = 'accepted' AND reviewed_by_user_id IS NOT NULL "
    "AND reviewed_at IS NOT NULL AND accepted_payload IS NOT NULL) OR "
    "(status = 'rejected' AND reviewed_by_user_id IS NOT NULL "
    "AND reviewed_at IS NOT NULL AND accepted_payload IS NULL) OR "
    "(status = 'applied' AND reviewed_by_user_id IS NOT NULL "
    "AND reviewed_at IS NOT NULL AND accepted_payload IS NOT NULL)"
)
_REVIEW_ARCHIVED = (
    " OR (status = 'archived' AND reviewed_by_user_id IS NULL "
    "AND reviewed_at IS NULL AND accepted_payload IS NULL)"
)

_ACTION_OLD = "action IN ('created', 'accepted', 'rejected', 'applied')"
_ACTION_NEW = "action IN ('created', 'accepted', 'rejected', 'applied', 'archived', 'restored')"

_TRANSITION_BASE = (
    "(action = 'created' AND actor_user_id IS NULL AND from_status IS NULL "
    "AND to_status = 'pending_review') OR "
    "(action IN ('accepted', 'rejected') AND actor_user_id IS NOT NULL "
    "AND from_status = 'pending_review' AND to_status = action) OR "
    "(action = 'applied' AND actor_user_id IS NOT NULL "
    "AND from_status = 'accepted' AND to_status = 'applied')"
)
_TRANSITION_ARCHIVED = (
    " OR (action = 'archived' AND actor_user_id IS NOT NULL "
    "AND from_status = 'pending_review' AND to_status = 'archived') OR "
    "(action = 'restored' AND actor_user_id IS NOT NULL "
    "AND from_status = 'archived' AND to_status = 'pending_review')"
)


def _swap(table: str, name: str, expression: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, schema=AI_SCHEMA, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, expression, schema=AI_SCHEMA)


def upgrade() -> None:
    _swap("findings", "status_allowed", _STATUS_NEW)
    _swap("findings", "review_lifecycle_consistent", _REVIEW_BASE + _REVIEW_ARCHIVED)
    _swap("finding_actions", "action_allowed", _ACTION_NEW)
    _swap(
        "finding_actions",
        "transition_consistent",
        _TRANSITION_BASE + _TRANSITION_ARCHIVED,
    )


def downgrade() -> None:
    connection = op.get_bind()
    archived_rows = connection.execute(
        sa.text(f"SELECT count(*) FROM {AI_SCHEMA}.findings WHERE status = 'archived'")
    ).scalar_one()
    archive_actions = connection.execute(
        sa.text(
            f"SELECT count(*) FROM {AI_SCHEMA}.finding_actions "
            "WHERE action IN ('archived', 'restored')"
        )
    ).scalar_one()
    if archived_rows or archive_actions:
        raise RuntimeError(
            "refusing downgrade while archived findings or archive/restore action history exist"
        )
    _swap("finding_actions", "transition_consistent", _TRANSITION_BASE)
    _swap("finding_actions", "action_allowed", _ACTION_OLD)
    _swap("findings", "review_lifecycle_consistent", _REVIEW_BASE)
    _swap("findings", "status_allowed", _STATUS_OLD)
