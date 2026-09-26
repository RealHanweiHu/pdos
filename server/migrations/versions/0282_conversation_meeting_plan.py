"""Connect private project conversation requests to existing meeting planning runs."""

import sqlalchemy as sa
from alembic import op

revision = "0282_conversation_meeting_plan"
down_revision = "0281_meeting_planning_review"
branch_labels = None
depends_on = None

CHANGES = [
    (
        "ck_conversation_messages_action_allowed",
        (
            "action IN ('note','project_query','meeting_reading','minutes','ac"
            "tions','decisions','business','change_work_package','quality_work"
            "_package')"
        ),
        (
            "action IN ('note','project_query','meeting_reading','minutes','ac"
            "tions','decisions','business','change_work_package','quality_work"
            "_package','meeting_planning')"
        ),
    ),
    (
        "ck_conversation_messages_action_source",
        (
            "(action IN ('note','project_query') AND transcript_id IS NULL AND"
            " expected_digest IS NULL AND expected_minutes_version IS NULL) OR"
            " (action NOT IN ('note','project_query','change_work_package','qu"
            "ality_work_package') AND transcript_id IS NOT NULL AND expected_d"
            "igest IS NOT NULL AND expected_digest ~ '^[0-9a-f]{64}$' AND ((ac"
            "tion='minutes' AND expected_minutes_version IS NOT NULL AND expec"
            "ted_minutes_version>=0) OR (action<>'minutes' AND expected_minute"
            "s_version IS NULL))) OR (action IN ('change_work_package','qualit"
            "y_work_package') AND transcript_id IS NULL AND expected_minutes_v"
            "ersion IS NULL AND expected_digest IS NOT NULL AND expected_diges"
            "t ~ '^[0-9a-f]{64}$')"
        ),
        (
            "(action IN ('note','project_query') AND transcript_id IS NULL AND"
            " expected_digest IS NULL AND expected_minutes_version IS NULL) OR"
            " (action NOT IN ('note','project_query','change_work_package','qu"
            "ality_work_package','meeting_planning') AND transcript_id IS NOT "
            "NULL AND expected_digest IS NOT NULL AND expected_digest ~ '^[0-9"
            "a-f]{64}$' AND ((action='minutes' AND expected_minutes_version IS"
            " NOT NULL AND expected_minutes_version>=0) OR (action<>'minutes' "
            "AND expected_minutes_version IS NULL))) OR (action IN ('change_wo"
            "rk_package','quality_work_package','meeting_planning') AND transc"
            "ript_id IS NULL AND expected_minutes_version IS NULL AND expected"
            "_digest IS NOT NULL AND expected_digest ~ '^[0-9a-f]{64}$')"
        ),
    ),
]
SOURCE = (
    "((action='meeting_planning' AND meeting_planning_brief_id IS NOT "
    "NULL) OR (action<>'meeting_planning' AND meeting_planning_brief_i"
    "d IS NULL)) IS TRUE"
)
GUARD = (
    "\nCREATE FUNCTION cehub_ai.guard_conversation_meeting_planning_mes"
    "sage() RETURNS trigger\nLANGUAGE plpgsql AS $$\nDECLARE b cehub_pro"
    "ject.meeting_planning_briefs; conv cehub_ai.conversations;\nBEGIN\n"
    " IF NEW.action<>'meeting_planning' THEN RETURN NEW; END IF;\n SELE"
    "CT * INTO conv FROM cehub_ai.conversations WHERE tenant_id=NEW.te"
    "nant_id\n  AND project_id=NEW.project_id AND id=NEW.conversation_i"
    "d;\n SELECT * INTO b FROM cehub_project.meeting_planning_briefs WH"
    "ERE tenant_id=NEW.tenant_id\n  AND project_id=NEW.project_id AND i"
    "d=NEW.meeting_planning_brief_id;\n IF conv.id IS NULL OR conv.meet"
    "ing_id IS NOT NULL OR conv.archived_at IS NOT NULL\n  OR conv.crea"
    "ted_by_user_id IS DISTINCT FROM NEW.author_user_id\n  OR b.id IS N"
    "ULL OR b.created_by_user_id IS DISTINCT FROM NEW.author_user_id\n "
    " OR b.source_digest IS DISTINCT FROM NEW.expected_digest\n  OR NEW"
    ".dispatch_input IS DISTINCT FROM NEW.body\n  OR NEW.body IS DISTIN"
    "CT FROM\n    '按已核对的会议要求起草：《'||(b.source_snapshot->>'title')||'》（版本"
    " '||b.version::text||'）。'\n THEN RAISE EXCEPTION 'Conversation mee"
    "ting request requires its private fixed briefing'; END IF;\n RETUR"
    "N NEW;\nEND $$;\nREVOKE ALL ON FUNCTION cehub_ai.guard_conversation"
    "_meeting_planning_message() FROM PUBLIC;\nCREATE TRIGGER guard_con"
    "versation_meeting_planning_message BEFORE INSERT\n ON cehub_ai.con"
    "versation_messages FOR EACH ROW\n EXECUTE FUNCTION cehub_ai.guard_"
    "conversation_meeting_planning_message();\nCREATE FUNCTION cehub_ai"
    ".guard_conversation_meeting_planning_run() RETURNS trigger\nLANGUA"
    "GE plpgsql AS $$\nDECLARE m cehub_ai.conversation_messages;\nBEGIN\n"
    " SELECT * INTO m FROM cehub_ai.conversation_messages WHERE tenant"
    "_id=NEW.tenant_id\n  AND operation_request_id=NEW.request_id;\n IF "
    "m.id IS NULL THEN RETURN NEW; END IF;\n IF m.action<>'meeting_plan"
    "ning' AND NEW.context_version<>'meeting-planning-request-v1'\n THE"
    "N RETURN NEW; END IF;\n IF m.action<>'meeting_planning' OR NEW.con"
    "text_version<>'meeting-planning-request-v1'\n  OR m.project_id IS "
    "DISTINCT FROM NEW.project_id\n  OR m.author_user_id IS DISTINCT FR"
    "OM NEW.requested_by_user_id\n  OR NEW.run_context->>'meeting_plann"
    "ing_brief_id' IS DISTINCT FROM m.meeting_planning_brief_id::text\n"
    "  OR NEW.run_context->>'meeting_planning_source_digest' IS DISTIN"
    "CT FROM m.expected_digest\n THEN RAISE EXCEPTION 'Conversation mee"
    "ting run must use the exact saved request'; END IF;\n RETURN NEW;\n"
    "END $$;\nREVOKE ALL ON FUNCTION cehub_ai.guard_conversation_meetin"
    "g_planning_run() FROM PUBLIC;\nCREATE TRIGGER guard_conversation_m"
    "eeting_planning_run BEFORE INSERT OR UPDATE\n ON cehub_ai.agent_ru"
    "ns FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_conversation_meet"
    "ing_planning_run();\n"
)


def upgrade() -> None:
    op.add_column(
        "conversation_messages",
        sa.Column("meeting_planning_brief_id", sa.Uuid()),
        schema="cehub_ai",
    )
    op.create_foreign_key(
        "fk_conversation_meeting_planning_brief",
        "conversation_messages",
        "meeting_planning_briefs",
        ["tenant_id", "project_id", "meeting_planning_brief_id"],
        ["tenant_id", "project_id", "id"],
        source_schema="cehub_ai",
        referent_schema="cehub_project",
        ondelete="RESTRICT",
    )
    for name, _, updated in CHANGES:
        op.drop_constraint(op.f(name), "conversation_messages", schema="cehub_ai")
        op.create_check_constraint(op.f(name), "conversation_messages", updated, schema="cehub_ai")
    op.create_check_constraint(
        op.f("ck_conversation_messages_meeting_planning_source"),
        "conversation_messages",
        SOURCE,
        schema="cehub_ai",
    )
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
    IF EXISTS(SELECT 1 FROM cehub_ai.conversation_messages WHERE action='meeting_planning')
    THEN RAISE EXCEPTION 'Meeting conversation request history must be retained'; END IF;
    END $$;
    DROP TRIGGER guard_conversation_meeting_planning_run ON cehub_ai.agent_runs;
    DROP FUNCTION cehub_ai.guard_conversation_meeting_planning_run();
    DROP TRIGGER guard_conversation_meeting_planning_message ON cehub_ai.conversation_messages;
    DROP FUNCTION cehub_ai.guard_conversation_meeting_planning_message();
    """)
    op.drop_constraint(
        op.f("ck_conversation_messages_meeting_planning_source"),
        "conversation_messages",
        schema="cehub_ai",
    )
    for name, original, _ in CHANGES:
        op.drop_constraint(op.f(name), "conversation_messages", schema="cehub_ai")
        op.create_check_constraint(op.f(name), "conversation_messages", original, schema="cehub_ai")
    op.drop_constraint(
        "fk_conversation_meeting_planning_brief", "conversation_messages", schema="cehub_ai"
    )
    op.drop_column("conversation_messages", "meeting_planning_brief_id", schema="cehub_ai")
