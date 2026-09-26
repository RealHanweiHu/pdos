"""Freeze separately authorized recurring meeting notification scope."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0278_recurring_notifications"
down_revision = "0277_meeting_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meeting_generation_policies",
        sa.Column("notification_scope", postgresql.JSONB()),
        schema="cehub_project",
    )
    op.create_check_constraint(
        op.f("ck_meeting_generation_policies_notification_scope"),
        "meeting_generation_policies",
        "notification_scope IS NULL OR jsonb_typeof(notification_scope)='object'",
        schema="cehub_project",
    )
    # The original guard compares all authorization fields, including this one,
    # and requires a new version. Existing policies retain NULL (manual notices).


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""
        SELECT EXISTS (SELECT 1 FROM cehub_project.meeting_generation_policies
          WHERE notification_scope IS NOT NULL)
        OR EXISTS (SELECT 1 FROM cehub_project.meeting_conference_requests
          WHERE snapshot->'standing_authority'->'policy' ? 'notification_scope')
        OR EXISTS (SELECT 1 FROM cehub_project.meeting_notification_batches
          WHERE snapshot ? 'standing_authority')
    """)
        )
        .scalar_one()
    ):
        raise RuntimeError(
            "Recurring notification authority and original receipts must be retained"
        )
    op.drop_constraint(
        op.f("ck_meeting_generation_policies_notification_scope"),
        "meeting_generation_policies",
        schema="cehub_project",
        type_="check",
    )
    op.drop_column("meeting_generation_policies", "notification_scope", schema="cehub_project")
