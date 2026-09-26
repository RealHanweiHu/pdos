"""Bind private quality requests to scoped NCR and fixed original evidence."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0202_conversation_quality_work"
down_revision = "0201_quality_work_package_runs"
branch_labels = None
depends_on = None

CHANGES = [
    (
        "ck_conversation_messages_action_allowed",
        """
action IN
('note','project_query','meeting_reading','minutes','actions','decisions','business',
'change_work_package')
""",
        """
action IN
('note','project_query','meeting_reading','minutes','actions','decisions','business',
'change_work_package','quality_work_package')
""",
    ),
    (
        "ck_conversation_messages_action_source",
        """
(action IN ('note','project_query') AND transcript_id IS NULL AND expected_digest IS NULL AND
expected_minutes_version IS NULL) OR (action NOT IN
('note','project_query','change_work_package') AND transcript_id IS NOT NULL AND
expected_digest IS NOT NULL AND expected_digest ~ '^[0-9a-f]{64}$' AND ((action='minutes' AND
expected_minutes_version IS NOT NULL AND expected_minutes_version>=0) OR (action<>'minutes' AND
expected_minutes_version IS NULL))) OR (action='change_work_package' AND transcript_id IS NULL
AND expected_minutes_version IS NULL AND expected_digest IS NOT NULL AND expected_digest ~
'^[0-9a-f]{64}$')
""",
        """
(action IN ('note','project_query') AND transcript_id IS NULL AND expected_digest IS NULL AND
expected_minutes_version IS NULL) OR (action NOT IN
('note','project_query','change_work_package','quality_work_package') AND transcript_id IS NOT
NULL AND expected_digest IS NOT NULL AND expected_digest ~ '^[0-9a-f]{64}$' AND
((action='minutes' AND expected_minutes_version IS NOT NULL AND expected_minutes_version>=0) OR
(action<>'minutes' AND expected_minutes_version IS NULL))) OR (action IN
('change_work_package','quality_work_package') AND transcript_id IS NULL AND
expected_minutes_version IS NULL AND expected_digest IS NOT NULL AND expected_digest ~
'^[0-9a-f]{64}$')
""",
    ),
]
SOURCE = """
((action='quality_work_package' AND ncr_id IS NOT NULL AND quality_selections IS NOT NULL AND
jsonb_typeof(quality_selections)='array' AND jsonb_array_length(quality_selections)<=50) OR
(action<>'quality_work_package' AND ncr_id IS NULL AND quality_selections IS NULL)) IS TRUE
"""


def upgrade() -> None:
    op.add_column(
        "conversation_messages", sa.Column("ncr_id", sa.Uuid(), nullable=True), schema="cehub_ai"
    )
    op.add_column(
        "conversation_messages",
        sa.Column("quality_selections", JSONB(none_as_null=True), nullable=True),
        schema="cehub_ai",
    )
    op.create_foreign_key(
        "fk_conversation_message_ncr",
        "conversation_messages",
        "nonconformance_reports",
        ["tenant_id", "project_id", "ncr_id"],
        ["tenant_id", "project_id", "id"],
        source_schema="cehub_ai",
        referent_schema="cehub_quality",
        ondelete="RESTRICT",
    )
    for name, _, updated in CHANGES:
        op.drop_constraint(op.f(name), "conversation_messages", schema="cehub_ai")
        op.create_check_constraint(op.f(name), "conversation_messages", updated, schema="cehub_ai")
    op.create_check_constraint(
        op.f("ck_conversation_messages_quality_source"),
        "conversation_messages",
        SOURCE,
        schema="cehub_ai",
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_ai.conversation_messages "
                "WHERE action='quality_work_package')"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Refusing to discard quality conversation requests")
    op.drop_constraint(
        op.f("ck_conversation_messages_quality_source"), "conversation_messages", schema="cehub_ai"
    )
    for name, original, _ in CHANGES:
        op.drop_constraint(op.f(name), "conversation_messages", schema="cehub_ai")
        op.create_check_constraint(op.f(name), "conversation_messages", original, schema="cehub_ai")
    op.drop_constraint("fk_conversation_message_ncr", "conversation_messages", schema="cehub_ai")
    op.drop_column("conversation_messages", "quality_selections", schema="cehub_ai")
    op.drop_column("conversation_messages", "ncr_id", schema="cehub_ai")
