"""Keep notice discussions and their follow-up analysis on fixed sources and original budgets."""

from alembic import op

revision = "0321_notice_discussions"
down_revision = "0320_change_notice_runs"
branch_labels = None
depends_on = None

OLD_NOTICE = """
CREATE OR REPLACE FUNCTION cehub_ai.guard_change_notice_run() RETURNS trigger
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
"""

OLD_INPUT = """
CREATE OR REPLACE FUNCTION cehub_ai.guard_change_discussion_input() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE child cehub_ai.agent_runs; parent cehub_ai.agent_runs; analysis cehub_ai.agent_runs;
 b cehub_ai.debate_run_bindings; a cehub_ai.application_authorizations;
 pa cehub_ai.application_authorizations; actual_turns jsonb;
BEGIN
 SELECT * INTO analysis FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND
id=NEW.run_id;
 SELECT * INTO parent FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND
id=NEW.origin_run_id;
 SELECT * INTO child FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND
id=NEW.discussion_run_id FOR UPDATE;
 SELECT * INTO b FROM cehub_ai.debate_run_bindings WHERE tenant_id=NEW.tenant_id AND
run_id=NEW.discussion_run_id;
 SELECT * INTO a FROM cehub_ai.application_authorizations WHERE tenant_id=NEW.tenant_id AND
run_id=NEW.run_id;
 SELECT * INTO pa FROM cehub_ai.application_authorizations WHERE tenant_id=NEW.tenant_id AND
run_id=NEW.origin_run_id;
 IF (b.origin_run_id=parent.id AND parent.status='succeeded' AND child.status='succeeded'
 AND analysis.context_version='change-work-package-request-v1'
 AND analysis.agent_key=parent.agent_key AND analysis.agent_key='engineering_intelligence'
 AND parent.context_version=analysis.context_version
 AND analysis.project_id=parent.project_id AND child.project_id=parent.project_id
 AND analysis.requested_by_user_id=parent.requested_by_user_id
 AND child.requested_by_user_id=parent.requested_by_user_id
 AND parent.run_context->>'discussion_followup_version'='discussion-followup.v1'
 AND parent.run_context->'impact_allow_discussion'='true'::jsonb
 AND analysis.run_context->>'discussion_followup_queue'='discussion-followup.v1'
 AND analysis.run_context->>'impact_prompt_version'='change-work-package-v4'
 AND analysis.run_context->'impact_allow_discussion'='false'::jsonb
 AND analysis.run_context->'impact_source'->'discussion_input'->>'id'=NEW.id::text
 AND analysis.run_context->'impact_source'->'discussion_input'->>'origin_run_id'=parent.id::text
 AND
analysis.run_context->'impact_source'->'discussion_input'->>'discussion_run_id'=child.id::text
 AND analysis.run_context->'impact_source'->'discussion_input'->>'digest'=NEW.brief_digest
 AND analysis.run_context->'impact_source'->'discussion_input'->'body'=NEW.body
 AND
(analysis.run_context->'impact_source')-'discussion_input'=parent.run_context->'impact_source'
 AND b.source->>'digest'=parent.run_context->'impact_source'->>'digest'
 AND a.lineage_id=pa.lineage_id AND a.principal_id=pa.principal_id
 AND a.pins=pa.pins AND a.expires_at<=pa.expires_at
 AND a.body->>'policy_version'=pa.body->>'policy_version'
 AND a.body->>'purpose'='change_work_package'
 AND EXISTS(SELECT 1 FROM cehub_ai.budget_run_links l
 WHERE l.tenant_id=NEW.tenant_id AND l.run_id=child.id AND l.lineage_id=a.lineage_id)
 AND NEW.body->>'run_id'=child.id::text AND NEW.body->>'source_digest'=b.source->>'digest'
 AND NEW.body->>'run_status'='succeeded' AND NEW.body->>'status'='completed'
 AND NEW.body->'complete'='true'::jsonb
 AND NEW.body->'recovery_requested'='false'::jsonb
 ) IS NOT TRUE THEN
 RAISE EXCEPTION 'Discussion follow-up must inherit actual origin, version and authority'
 USING ERRCODE='23514'; END IF;
 SELECT coalesce(jsonb_agg(t.id::text ORDER BY t.sequence),'[]'::jsonb) INTO actual_turns
 FROM cehub_ai.debate_turns t WHERE t.tenant_id=NEW.tenant_id AND t.session_id=b.session_id;
 IF NEW.body->'turn_ids' IS DISTINCT FROM actual_turns OR NOT EXISTS(
 SELECT 1 FROM cehub_ai.debate_turn_receipts tr WHERE tr.tenant_id=NEW.tenant_id AND
tr.run_id=child.id)
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.body->'positions') p WHERE NOT EXISTS(
 SELECT 1 FROM cehub_ai.debate_turn_receipts tr
 WHERE tr.tenant_id=NEW.tenant_id AND tr.run_id=child.id
 AND tr.turn_id::text=p->>'turn_id' AND tr.checkpoint_id::text=p->>'checkpoint_id'
 AND tr.output->'statements'->(p->>'statement_index')::integer=p->'statement')) THEN
 RAISE EXCEPTION 'Discussion follow-up must retain actual turns and checkpoints'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""

NOTICE = """
CREATE OR REPLACE FUNCTION cehub_ai.guard_change_notice_run() RETURNS trigger
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
   NEW.run_context->>'impact_prompt_version' IS DISTINCT FROM
     CASE WHEN NEW.run_context->'impact_source' ? 'discussion_input'
       THEN 'change-work-package-v6' ELSE 'change-work-package-v5' END
   OR NEW.run_context#>>'{impact_source,source_actor_id}' IS DISTINCT FROM
      NEW.requested_by_user_id::text
   OR NEW.run_context#>>'{impact_source,project_id}' IS DISTINCT FROM NEW.project_id::text
 ) THEN RAISE EXCEPTION 'notice analysis requires its fixed actor, project and prompt'; END IF;
 SELECT * INTO m FROM cehub_ai.conversation_messages
 WHERE tenant_id=NEW.tenant_id AND operation_request_id=NEW.request_id
 AND action='change_work_package';
 IF FOUND AND notice IS DISTINCT FROM m.include_supplier_notices THEN
  RAISE EXCEPTION 'notice analysis must match its saved conversation choice';
 END IF;
 RETURN NEW;
END $$;
"""

INPUT = """
CREATE OR REPLACE FUNCTION cehub_ai.guard_change_discussion_input() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE child cehub_ai.agent_runs; parent cehub_ai.agent_runs; analysis cehub_ai.agent_runs;
 b cehub_ai.debate_run_bindings; a cehub_ai.application_authorizations;
 pa cehub_ai.application_authorizations; actual_turns jsonb;
BEGIN
 SELECT * INTO analysis FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND
id=NEW.run_id;
 SELECT * INTO parent FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND
id=NEW.origin_run_id;
 SELECT * INTO child FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND
id=NEW.discussion_run_id FOR UPDATE;
 SELECT * INTO b FROM cehub_ai.debate_run_bindings WHERE tenant_id=NEW.tenant_id AND
run_id=NEW.discussion_run_id;
 SELECT * INTO a FROM cehub_ai.application_authorizations WHERE tenant_id=NEW.tenant_id AND
run_id=NEW.run_id;
 SELECT * INTO pa FROM cehub_ai.application_authorizations WHERE tenant_id=NEW.tenant_id AND
run_id=NEW.origin_run_id;
 IF (b.origin_run_id=parent.id AND parent.status='succeeded' AND child.status='succeeded'
 AND analysis.context_version='change-work-package-request-v1'
 AND analysis.agent_key=parent.agent_key AND analysis.agent_key='engineering_intelligence'
 AND parent.context_version=analysis.context_version
 AND analysis.project_id=parent.project_id AND child.project_id=parent.project_id
 AND analysis.requested_by_user_id=parent.requested_by_user_id
 AND child.requested_by_user_id=parent.requested_by_user_id
 AND parent.run_context->>'discussion_followup_version'='discussion-followup.v1'
 AND parent.run_context->'impact_allow_discussion'='true'::jsonb
 AND analysis.run_context->>'discussion_followup_queue'='discussion-followup.v1'
 AND analysis.run_context->>'impact_prompt_version'=
 CASE WHEN coalesce((parent.run_context->>'impact_include_supplier_notices')::boolean,false)
 THEN 'change-work-package-v6' ELSE 'change-work-package-v4' END
 AND coalesce((analysis.run_context->>'impact_include_supplier_notices')::boolean,false)=
 coalesce((parent.run_context->>'impact_include_supplier_notices')::boolean,false)
 AND analysis.run_context->'impact_allow_discussion'='false'::jsonb
 AND analysis.run_context->'impact_source'->'discussion_input'->>'id'=NEW.id::text
 AND analysis.run_context->'impact_source'->'discussion_input'->>'origin_run_id'=parent.id::text
 AND
analysis.run_context->'impact_source'->'discussion_input'->>'discussion_run_id'=child.id::text
 AND analysis.run_context->'impact_source'->'discussion_input'->>'digest'=NEW.brief_digest
 AND analysis.run_context->'impact_source'->'discussion_input'->'body'=NEW.body
 AND
(analysis.run_context->'impact_source')-'discussion_input'=parent.run_context->'impact_source'
 AND b.source->>'digest'=parent.run_context->'impact_source'->>'digest'
 AND a.lineage_id=pa.lineage_id AND a.principal_id=pa.principal_id
 AND a.pins=pa.pins AND a.expires_at<=pa.expires_at
 AND a.body->>'policy_version'=pa.body->>'policy_version'
 AND a.body->>'purpose'='change_work_package'
 AND EXISTS(SELECT 1 FROM cehub_ai.budget_run_links l
 WHERE l.tenant_id=NEW.tenant_id AND l.run_id=child.id AND l.lineage_id=a.lineage_id)
 AND NEW.body->>'run_id'=child.id::text AND NEW.body->>'source_digest'=b.source->>'digest'
 AND NEW.body->>'run_status'='succeeded' AND NEW.body->>'status'='completed'
 AND NEW.body->'complete'='true'::jsonb
 AND NEW.body->'recovery_requested'='false'::jsonb
 ) IS NOT TRUE THEN
 RAISE EXCEPTION 'Discussion follow-up must inherit actual origin, version and authority'
 USING ERRCODE='23514'; END IF;
 SELECT coalesce(jsonb_agg(t.id::text ORDER BY t.sequence),'[]'::jsonb) INTO actual_turns
 FROM cehub_ai.debate_turns t WHERE t.tenant_id=NEW.tenant_id AND t.session_id=b.session_id;
 IF NEW.body->'turn_ids' IS DISTINCT FROM actual_turns OR NOT EXISTS(
 SELECT 1 FROM cehub_ai.debate_turn_receipts tr WHERE tr.tenant_id=NEW.tenant_id AND
tr.run_id=child.id)
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.body->'positions') p WHERE NOT EXISTS(
 SELECT 1 FROM cehub_ai.debate_turn_receipts tr
 WHERE tr.tenant_id=NEW.tenant_id AND tr.run_id=child.id
 AND tr.turn_id::text=p->>'turn_id' AND tr.checkpoint_id::text=p->>'checkpoint_id'
 AND tr.output->'statements'->(p->>'statement_index')::integer=p->'statement')) THEN
 RAISE EXCEPTION 'Discussion follow-up must retain actual turns and checkpoints'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""

BOUND = """
CREATE FUNCTION cehub_ai.guard_notice_discussion_source() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE notice boolean; r cehub_ai.agent_runs; origin cehub_ai.agent_runs;
BEGIN
 notice:=coalesce((NEW.config#>>'{request,include_supplier_notices}')::boolean,false);
 IF notice IS DISTINCT FROM
  coalesce(NEW.source->>'context_version'='change-work-package-context-v4',false) THEN
  RAISE EXCEPTION 'discussion notice choice must match the fixed source version';
 END IF;
 IF NOT notice THEN RETURN NEW; END IF;
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;
 IF (NEW.ecr_id IS NOT NULL AND NEW.source->>'ecr_id'=NEW.ecr_id::text
  AND NEW.source->>'project_id'=NEW.project_id::text
  AND NEW.source->>'source_actor_id'=r.requested_by_user_id::text
  AND r.project_id=NEW.project_id) IS NOT TRUE THEN
  RAISE EXCEPTION 'notice discussion requires its original actor and ECR';
 END IF;
 IF NEW.origin_run_id IS NOT NULL THEN
  SELECT * INTO origin FROM cehub_ai.agent_runs
   WHERE tenant_id=NEW.tenant_id AND id=NEW.origin_run_id;
  IF (origin.run_context->'impact_source'=NEW.source
   AND origin.run_context->'impact_include_supplier_notices'='true'::jsonb) IS NOT TRUE THEN
   RAISE EXCEPTION 'notice discussion must retain its originating analysis source';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER notice_discussion_source_guard BEFORE INSERT ON cehub_ai.debate_run_bindings
FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_notice_discussion_source();
REVOKE ALL ON FUNCTION cehub_ai.guard_notice_discussion_source() FROM PUBLIC;
"""


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_conversation_messages_notice_source"), "conversation_messages", schema="cehub_ai"
    )
    op.create_check_constraint(
        op.f("ck_conversation_messages_notice_source"),
        "conversation_messages",
        "NOT include_supplier_notices OR action='change_work_package'",
        schema="cehub_ai",
    )
    op.execute(NOTICE)
    op.execute(INPUT)
    op.execute(BOUND)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
     IF EXISTS (SELECT 1 FROM cehub_ai.debate_run_bindings
       WHERE source->>'context_version'='change-work-package-context-v4')
     OR EXISTS (SELECT 1 FROM cehub_ai.agent_runs
       WHERE run_context->'impact_include_supplier_notices'='true'::jsonb
       AND (run_context->'impact_allow_discussion'='true'::jsonb
            OR run_context->'impact_source' ? 'discussion_input'))
     OR EXISTS (SELECT 1 FROM cehub_ai.conversation_messages
       WHERE include_supplier_notices AND allow_discussion) THEN
       RAISE EXCEPTION 'retain original notice discussion and follow-up contracts';
     END IF;
    END $$;
    DROP TRIGGER notice_discussion_source_guard ON cehub_ai.debate_run_bindings;
    DROP FUNCTION cehub_ai.guard_notice_discussion_source();
    """)
    op.execute(OLD_INPUT)
    op.execute(OLD_NOTICE)
    op.drop_constraint(
        op.f("ck_conversation_messages_notice_source"), "conversation_messages", schema="cehub_ai"
    )
    op.create_check_constraint(
        op.f("ck_conversation_messages_notice_source"),
        "conversation_messages",
        "NOT include_supplier_notices OR (action='change_work_package' AND NOT allow_discussion)",
        schema="cehub_ai",
    )
