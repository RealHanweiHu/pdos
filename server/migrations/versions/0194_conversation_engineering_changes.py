"""Bind private conversation requests to original engineering change sources.
Revision ID: 0194_conversation_engineering_changes
Revises: 0193_change_work_package_application
"""

import sqlalchemy as sa
from alembic import op

revision = "0194_conversation_engineering_changes"
down_revision = "0193_change_work_package_application"
branch_labels = None
depends_on = None

CHANGES = [
    (
        "ck_conversation_messages_action_allowed",
        "action IN "
        "('note','project_query','meeting_reading','minutes','actions','decisions','business')",
        "action IN "
        "('note','project_query','meeting_reading','minutes','actions','decisions','business','change_work_package')",
    ),
    (
        "ck_conversation_messages_action_source",
        "(action IN ('note','project_query') AND transcript_id IS NULL AND expected_digest IS "
        "NULL AND expected_minutes_version IS NULL) OR (action NOT IN ('note','project_query') "
        "AND transcript_id IS NOT NULL AND expected_digest IS NOT NULL AND expected_digest ~ "
        "'^[0-9a-f]{64}$' AND ((action='minutes' AND expected_minutes_version IS NOT NULL AND "
        "expected_minutes_version>=0) OR (action<>'minutes' AND expected_minutes_version IS "
        "NULL)))",
        "(action IN ('note','project_query') AND transcript_id IS NULL AND expected_digest IS "
        "NULL AND expected_minutes_version IS NULL) OR (action NOT IN "
        "('note','project_query','change_work_package') AND transcript_id IS NOT NULL AND "
        "expected_digest IS NOT NULL AND expected_digest ~ '^[0-9a-f]{64}$' AND "
        "((action='minutes' AND expected_minutes_version IS NOT NULL AND "
        "expected_minutes_version>=0) OR (action<>'minutes' AND expected_minutes_version IS "
        "NULL))) OR (action='change_work_package' AND transcript_id IS NULL AND "
        "expected_minutes_version IS NULL AND expected_digest IS NOT NULL AND expected_digest "
        "~ '^[0-9a-f]{64}$')",
    ),
]
SOURCE_SHAPE = (
    "((action='change_work_package' AND ecr_id IS NOT NULL AND impact_depth BETWEEN 1 AND "
    "5) OR (action<>'change_work_package' AND ecr_id IS NULL AND impact_depth IS NULL)) IS "
    "TRUE"
)


def upgrade() -> None:
    op.add_column(
        "conversation_messages", sa.Column("ecr_id", sa.Uuid(), nullable=True), schema="cehub_ai"
    )
    op.add_column(
        "conversation_messages",
        sa.Column("impact_depth", sa.Integer(), nullable=True),
        schema="cehub_ai",
    )
    op.create_foreign_key(
        "fk_conversation_message_ecr",
        "conversation_messages",
        "engineering_change_requests",
        ["tenant_id", "project_id", "ecr_id"],
        ["tenant_id", "project_id", "id"],
        source_schema="cehub_ai",
        referent_schema="cehub_product",
        ondelete="RESTRICT",
    )
    for name, _, updated in CHANGES:
        op.drop_constraint(op.f(name), "conversation_messages", schema="cehub_ai")
        op.create_check_constraint(op.f(name), "conversation_messages", updated, schema="cehub_ai")
    op.create_check_constraint(
        op.f("ck_conversation_messages_change_source"),
        "conversation_messages",
        SOURCE_SHAPE,
        schema="cehub_ai",
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_ai.conversation_messages "
                "WHERE action='change_work_package')"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Refusing to discard engineering conversation requests")
    op.drop_constraint(
        op.f("ck_conversation_messages_change_source"), "conversation_messages", schema="cehub_ai"
    )
    for name, original, _ in CHANGES:
        op.drop_constraint(op.f(name), "conversation_messages", schema="cehub_ai")
        op.create_check_constraint(op.f(name), "conversation_messages", original, schema="cehub_ai")
    op.drop_constraint("fk_conversation_message_ecr", "conversation_messages", schema="cehub_ai")
    op.drop_column("conversation_messages", "impact_depth", schema="cehub_ai")
    op.drop_column("conversation_messages", "ecr_id", schema="cehub_ai")
