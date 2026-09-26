"""Do not read private conversation messages for event-only worker runs."""

from alembic import op

revision = "0370_conversation_run_guard"
down_revision = "0369_research_workpacks"
branch_labels = None
depends_on = None

OLD_GUARD = r"""
CREATE OR REPLACE FUNCTION cehub_ai.guard_conversation_meeting_planning_run() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE m cehub_ai.conversation_messages;
BEGIN
 SELECT * INTO m FROM cehub_ai.conversation_messages WHERE tenant_id=NEW.tenant_id
  AND operation_request_id=NEW.request_id;
 IF m.id IS NULL THEN RETURN NEW; END IF;
 IF m.action<>'meeting_planning' AND NEW.context_version<>'meeting-planning-request-v1'
 THEN RETURN NEW; END IF;
 IF m.action<>'meeting_planning' OR NEW.context_version<>'meeting-planning-request-v1'
  OR m.project_id IS DISTINCT FROM NEW.project_id
  OR m.author_user_id IS DISTINCT FROM NEW.requested_by_user_id
  OR NEW.run_context->>'meeting_planning_brief_id'
    IS DISTINCT FROM m.meeting_planning_brief_id::text
  OR NEW.run_context->>'meeting_planning_source_digest' IS DISTINCT FROM m.expected_digest
 THEN RAISE EXCEPTION 'Conversation meeting run must use the exact saved request'; END IF;
 RETURN NEW;
END $$;
"""

GUARD = r"""
CREATE OR REPLACE FUNCTION cehub_ai.guard_conversation_meeting_planning_run() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE m cehub_ai.conversation_messages;
BEGIN
 -- Event-driven runs have no private conversation request to validate.
 -- Keep the original exact binding checks for every named request.
 IF NEW.request_id IS NULL THEN RETURN NEW; END IF;
 SELECT * INTO m FROM cehub_ai.conversation_messages WHERE tenant_id=NEW.tenant_id
  AND operation_request_id=NEW.request_id;
 IF m.id IS NULL THEN RETURN NEW; END IF;
 IF m.action<>'meeting_planning' AND NEW.context_version<>'meeting-planning-request-v1'
 THEN RETURN NEW; END IF;
 IF m.action<>'meeting_planning' OR NEW.context_version<>'meeting-planning-request-v1'
  OR m.project_id IS DISTINCT FROM NEW.project_id
  OR m.author_user_id IS DISTINCT FROM NEW.requested_by_user_id
  OR NEW.run_context->>'meeting_planning_brief_id'
    IS DISTINCT FROM m.meeting_planning_brief_id::text
  OR NEW.run_context->>'meeting_planning_source_digest' IS DISTINCT FROM m.expected_digest
 THEN RAISE EXCEPTION 'Conversation meeting run must use the exact saved request'; END IF;
 RETURN NEW;
END $$;
"""


def upgrade() -> None:
    op.execute(GUARD)


def downgrade() -> None:
    op.execute(OLD_GUARD)
