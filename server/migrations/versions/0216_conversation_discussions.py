"""Keep each conversation message's discussion option and resulting run in agreement."""

import sqlalchemy as sa
from alembic import op

revision = "0216_conversation_discussions"
down_revision = "0215_discussion_followup"
branch_labels = None
depends_on = None

GUARD = """
CREATE FUNCTION cehub_ai.guard_conversation_change_run() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE m cehub_ai.conversation_messages;
BEGIN
 IF NEW.context_version IS DISTINCT FROM 'change-work-package-request-v1'
 OR NEW.request_id IS NULL OR NEW.requested_by_user_id IS NULL THEN RETURN NEW; END IF;
 SELECT * INTO m FROM cehub_ai.conversation_messages
 WHERE tenant_id=NEW.tenant_id AND operation_request_id=NEW.request_id
 AND action='change_work_package';
 IF NOT FOUND THEN RETURN NEW; END IF;
 IF (NEW.project_id=m.project_id AND NEW.requested_by_user_id=m.author_user_id
 AND NEW.agent_key='engineering_intelligence'
 AND NEW.context_version='change-work-package-request-v1'
 AND NEW.run_context->>'impact_ecr_id'=m.ecr_id::text
 AND NEW.run_context->>'impact_depth'=m.impact_depth::text
 AND NEW.run_context->>'impact_expected_digest'=m.expected_digest
 AND NEW.run_context->>'impact_user_instruction'=m.dispatch_input
 AND coalesce((NEW.run_context->>'impact_allow_discussion')::boolean,false)=m.allow_discussion
 ) IS NOT TRUE THEN
 RAISE EXCEPTION 'Conversation engineering run must retain its saved input and discussion option'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_conversation_change_run() FROM PUBLIC;
CREATE TRIGGER guard_conversation_change_run BEFORE INSERT OR UPDATE ON cehub_ai.agent_runs
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_conversation_change_run();
"""


def upgrade() -> None:
    op.add_column(
        "conversation_messages",
        sa.Column("allow_discussion", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="cehub_ai",
    )
    op.create_check_constraint(
        op.f("ck_conversation_messages_discussion_source"),
        "conversation_messages",
        "NOT allow_discussion OR action='change_work_package'",
        schema="cehub_ai",
    )
    op.execute(sa.text(GUARD))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_ai.conversation_messages WHERE allow_discussion)"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Refusing to discard saved conversation discussion choices")
    op.execute("DROP TRIGGER guard_conversation_change_run ON cehub_ai.agent_runs")
    op.execute("DROP FUNCTION cehub_ai.guard_conversation_change_run()")
    op.drop_constraint(
        op.f("ck_conversation_messages_discussion_source"),
        "conversation_messages",
        schema="cehub_ai",
    )
    op.drop_column("conversation_messages", "allow_discussion", schema="cehub_ai")
