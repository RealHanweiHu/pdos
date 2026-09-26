"""Add separately confirmed external booking scope to recurring meeting policies."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0276_recurring_conferences"
down_revision = "0275_tencent_meeting"
branch_labels = None
depends_on = None

SCOPE = (
    "(conference_provider IS NULL AND conference_identity IS NULL) OR "
    "(conference_provider IS NOT NULL AND conference_provider IN ('dingtalk','tencent_meeting') "
    "AND conference_identity IS NOT NULL AND jsonb_typeof(conference_identity)='object')"
)


def upgrade() -> None:
    op.add_column(
        "meeting_generation_policies",
        sa.Column("conference_provider", sa.String(24)),
        schema="cehub_project",
    )
    op.add_column(
        "meeting_generation_policies",
        sa.Column("conference_identity", postgresql.JSONB()),
        schema="cehub_project",
    )
    op.create_check_constraint(
        op.f("ck_meeting_generation_policies_conference_identity"),
        "meeting_generation_policies",
        SCOPE,
        schema="cehub_project",
    )
    # 0273's guard compares the complete row minus operational fields. These new
    # authorization fields therefore require a new policy version as well.


def downgrade() -> None:
    c = op.get_bind()
    if c.execute(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM cehub_project.meeting_generation_policies "
            "WHERE conference_provider IS NOT NULL) OR EXISTS("
            "SELECT 1 FROM cehub_project.meeting_conference_requests "
            "WHERE snapshot ? 'standing_authority')"
        )
    ).scalar_one():
        raise RuntimeError("Recurring external authorizations and receipts must be retained")
    op.drop_constraint(
        op.f("ck_meeting_generation_policies_conference_identity"),
        "meeting_generation_policies",
        schema="cehub_project",
        type_="check",
    )
    op.drop_column("meeting_generation_policies", "conference_identity", schema="cehub_project")
    op.drop_column("meeting_generation_policies", "conference_provider", schema="cehub_project")
