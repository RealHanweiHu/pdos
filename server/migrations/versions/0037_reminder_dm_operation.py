"""allow reminder_dm outbox operation for personal reminder delivery (vNext V1-A8)

Revision ID: 0037_reminder_dm_operation
Revises: 0036_reminders
Create Date: 2026-08-25 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037_reminder_dm_operation"
down_revision: str | Sequence[str] | None = "0036_reminders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENT_SCHEMA = "cehub_event"
_OLD = (
    "(provider = 'dingtalk' AND operation IN ('group_markdown', "
    "'gate_approval_create', 'interactive_card_create', 'interactive_card_update')) OR "
    "(provider = 'erp' AND operation = 'ebom_handoff')"
)
_NEW = (
    "(provider = 'dingtalk' AND operation IN ('group_markdown', "
    "'gate_approval_create', 'interactive_card_create', 'interactive_card_update', "
    "'reminder_dm')) OR "
    "(provider = 'erp' AND operation = 'ebom_handoff')"
)


def _swap(expression: str) -> None:
    op.drop_constraint(
        op.f("ck_integration_outbox_operation_allowed"),
        "integration_outbox",
        schema=EVENT_SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_integration_outbox_operation_allowed"),
        "integration_outbox",
        expression,
        schema=EVENT_SCHEMA,
    )


def upgrade() -> None:
    _swap(_NEW)


def downgrade() -> None:
    connection = op.get_bind()
    reminder_rows = connection.execute(
        sa.text(
            f"SELECT count(*) FROM {EVENT_SCHEMA}.integration_outbox "
            "WHERE operation = 'reminder_dm'"
        )
    ).scalar_one()
    if reminder_rows:
        raise RuntimeError("refusing lossy downgrade while reminder_dm outbox rows exist")
    _swap(_OLD)
