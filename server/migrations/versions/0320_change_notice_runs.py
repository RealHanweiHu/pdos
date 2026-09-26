"""Bind the notice analysis request mode to its original source and prompt versions."""

import sqlalchemy as sa
from alembic import op

revision = "0320_change_notice_runs"
down_revision = "0319_supplier_notice_impact"
branch_labels = None
depends_on = None

DDL = """
CREATE FUNCTION cehub_ai.guard_change_notice_run() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE notice boolean; m cehub_ai.conversation_messages;
BEGIN
 IF NEW.context_version IS DISTINCT FROM 'change-work-package-request-v1' THEN RETURN NEW; END IF;
 notice:=coalesce((NEW.run_context->>'impact_include_supplier_notices')::boolean,false);
 IF TG_OP='UPDATE' AND notice IS DISTINCT FROM
   coalesce((OLD.run_context->>'impact_include_supplier_notices')::boolean,false) THEN
  RAISE EXCEPTION 'notice analysis request mode is immutable';
 END IF;
 IF notice IS DISTINCT FROM
    coalesce(NEW.run_context#>>'{impact_source,context_version}'='change-work-package-context-v4',false)
 THEN RAISE EXCEPTION 'notice analysis mode must match the fixed source version'; END IF;
 IF notice AND (
   NEW.run_context->>'impact_prompt_version' IS DISTINCT FROM 'change-work-package-v5'
   OR NEW.run_context#>>'{impact_source,source_actor_id}' IS DISTINCT FROM
      NEW.requested_by_user_id::text
   OR NEW.run_context#>>'{impact_source,project_id}' IS DISTINCT FROM NEW.project_id::text
   OR coalesce((NEW.run_context->>'impact_allow_discussion')::boolean,false)
 ) THEN RAISE EXCEPTION 'notice analysis requires its fixed actor, project and prompt'; END IF;
 SELECT * INTO m FROM cehub_ai.conversation_messages
 WHERE tenant_id=NEW.tenant_id AND operation_request_id=NEW.request_id
 AND action='change_work_package';
 IF FOUND AND notice IS DISTINCT FROM m.include_supplier_notices THEN
  RAISE EXCEPTION 'notice analysis must match its saved conversation choice';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER change_notice_run_guard BEFORE INSERT OR UPDATE ON cehub_ai.agent_runs
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_change_notice_run();
REVOKE ALL ON FUNCTION cehub_ai.guard_change_notice_run() FROM PUBLIC;
"""


def upgrade() -> None:
    op.add_column(
        "conversation_messages",
        sa.Column(
            "include_supplier_notices", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        schema="cehub_ai",
    )
    op.create_check_constraint(
        op.f("ck_conversation_messages_notice_source"),
        "conversation_messages",
        "NOT include_supplier_notices OR (action='change_work_package' AND NOT allow_discussion)",
        schema="cehub_ai",
    )
    op.execute(DDL)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM cehub_ai.agent_runs
         WHERE run_context#>>'{impact_source,context_version}'
            ='change-work-package-context-v4') OR EXISTS (
          SELECT 1 FROM cehub_ai.conversation_messages WHERE include_supplier_notices
        ) THEN
        RAISE EXCEPTION 'retain fixed notice run contract';
      END IF;
    END $$;
    DROP TRIGGER change_notice_run_guard ON cehub_ai.agent_runs;
    DROP FUNCTION cehub_ai.guard_change_notice_run();
    """)
    op.drop_constraint(
        op.f("ck_conversation_messages_notice_source"), "conversation_messages", schema="cehub_ai"
    )
    op.drop_column("conversation_messages", "include_supplier_notices", schema="cehub_ai")
