"""Source-bound public search receipts in ordinary XiaoPai conversations."""

from alembic import op

revision = "0423_xiaopai_conversation_search"
down_revision = "0422_research_index_documents"
branch_labels = None
depends_on = None

PRIOR = r"""
CREATE OR REPLACE FUNCTION cehub_ai.require_application_tool_observation()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog'
AS $function$
DECLARE r cehub_ai.agent_runs%ROWTYPE; a cehub_ai.application_authorizations%ROWTYPE;
 i cehub_ai.agent_tool_intents%ROWTYPE; d cehub_ai.agent_tool_dispatches%ROWTYPE;
 token uuid:=nullif(current_setting('pdos.application_lease_id',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;
 SELECT * INTO a FROM cehub_ai.application_authorizations WHERE id=NEW.authorization_id;
 SELECT * INTO i FROM cehub_ai.agent_tool_intents WHERE id=NEW.tool_intent_id;
 SELECT * INTO d FROM cehub_ai.agent_tool_dispatches WHERE intent_id=NEW.tool_intent_id;
 IF (((r.agent_key='engineering_intelligence'
  AND i.tool_key='discussion.convene'
  AND a.body->>'purpose'='change_work_package'
  AND r.run_context->>'discussion_convene_version'='discussion-convene-v1'
  AND i.input_body->>'version'='discussion-convene.v1'
  AND NEW.metadata->>'allowed_purpose'=a.body->>'purpose'
  AND EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings child
   WHERE child.tenant_id=r.tenant_id AND child.origin_run_id=r.id
   AND child.origin_checkpoint_id::text=i.input_body->>'checkpoint_id'
   AND child.run_id::text=NEW.output_body->>'run_id'
   AND child.session_id::text=NEW.output_body->>'session_id')) OR
  (r.agent_key='engineering_intelligence'
  AND NEW.metadata->>'allowed_purpose'='change_discussion'
  AND a.body->>'purpose'='change_discussion'
  AND a.body->>'toolset_version'='discussion-research-tools.v1'
  AND r.run_context->>'discussion_toolset_version'='discussion-research-tools.v1'
  AND i.tool_key IN ('research.search_public','research.capture_snapshot')
  AND i.input_body->>'version'='discussion-research-tools.v1'
  AND i.input_body->>'source_digest'=r.run_context->>'discussion_source_digest') OR
  (r.agent_key='engineering_intelligence'
  AND r.run_context->>'impact_toolset_version'='application-engineering-tools.v1'
  AND a.body->>'purpose'='change_work_package'
  AND a.body->>'toolset_version'='application-engineering-tools.v1'
  AND i.tool_key IN ('engineering.trace_impact','change.prepare_work_package')
  AND i.input_body->>'source_digest'=r.run_context->'impact_source'->>'digest'
  AND i.input_body->>'ecr_id'=r.run_context->>'impact_ecr_id'
  AND NEW.metadata->>'allowed_purpose'='change_work_package') OR
  (r.agent_key='quality_intelligence'
  AND r.context_version='quality-work-package-request-v1'
  AND r.run_context->>'quality_toolset_version'='application-quality-tools.v1'
  AND a.body->>'purpose'='quality_work_package'
  AND a.body->>'toolset_version'='application-quality-tools.v1'
  AND i.tool_key='quality.prepare_capa'
  AND i.input_body->>'source_digest'=r.run_context->'quality_source'->>'digest'
  AND i.input_body->>'ncr_id'=r.run_context->>'quality_ncr_id'
  AND NEW.metadata->>'allowed_purpose'='quality_work_package'))
  AND d.tenant_id=NEW.tenant_id AND d.run_id=NEW.run_id AND d.lease_token=token
  AND NEW.metadata->>'id'=NEW.id::text
  AND NEW.metadata->>'run_id'=NEW.run_id::text
  AND NEW.metadata->>'tenant_id'=NEW.tenant_id::text
  AND NEW.metadata->>'tool_call_id'=i.id::text
  AND cehub_ai.application_lease_is_current(r.id,token)) IS NOT TRUE THEN
  RAISE EXCEPTION 'APPLICATION_TOOL_OBSERVATION_INVALID' USING ERRCODE='22023';
 END IF;
 RETURN NEW;
END $function$;
"""

CURRENT = r"""
CREATE OR REPLACE FUNCTION cehub_ai.require_application_tool_observation()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog'
AS $function$
DECLARE r cehub_ai.agent_runs%ROWTYPE; a cehub_ai.application_authorizations%ROWTYPE;
 i cehub_ai.agent_tool_intents%ROWTYPE; d cehub_ai.agent_tool_dispatches%ROWTYPE;
 token uuid:=nullif(current_setting('pdos.application_lease_id',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;
 SELECT * INTO a FROM cehub_ai.application_authorizations WHERE id=NEW.authorization_id;
 SELECT * INTO i FROM cehub_ai.agent_tool_intents WHERE id=NEW.tool_intent_id;
 SELECT * INTO d FROM cehub_ai.agent_tool_dispatches WHERE intent_id=NEW.tool_intent_id;
 IF (((r.agent_key='ai_chat'
  AND r.context_version='xiaopai-conversation-v1'
  AND a.tenant_id=NEW.tenant_id AND a.run_id=NEW.run_id
  AND i.tenant_id=NEW.tenant_id AND i.run_id=NEW.run_id
  AND a.body->>'purpose'='xiaopai_reply'
  AND a.body->>'toolset_version'='xiaopai-public-research-v1'
  AND NEW.metadata->>'allowed_purpose'='xiaopai_reply'
  AND i.tool_key IN ('conversation.search_public','conversation.read_public')
  AND i.input_body->>'version'='xiaopai-public-research-v1'
  AND i.input_body->>'source_digest'=r.run_context->'reply_source'->>'digest'
  AND EXISTS(SELECT 1 FROM cehub_ai.application_result_checkpoints cp
   WHERE cp.tenant_id=r.tenant_id AND cp.run_id=r.id
   AND cp.model_call_id::text=i.input_body->>'model_call_id'
   AND cp.body->'output'->'research'=i.input_body->'choice')) OR
 (r.agent_key='engineering_intelligence'
  AND i.tool_key='discussion.convene'
  AND a.body->>'purpose'='change_work_package'
  AND r.run_context->>'discussion_convene_version'='discussion-convene-v1'
  AND i.input_body->>'version'='discussion-convene.v1'
  AND NEW.metadata->>'allowed_purpose'=a.body->>'purpose'
  AND EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings child
   WHERE child.tenant_id=r.tenant_id AND child.origin_run_id=r.id
   AND child.origin_checkpoint_id::text=i.input_body->>'checkpoint_id'
   AND child.run_id::text=NEW.output_body->>'run_id'
   AND child.session_id::text=NEW.output_body->>'session_id')) OR
  (r.agent_key='engineering_intelligence'
  AND NEW.metadata->>'allowed_purpose'='change_discussion'
  AND a.body->>'purpose'='change_discussion'
  AND a.body->>'toolset_version'='discussion-research-tools.v1'
  AND r.run_context->>'discussion_toolset_version'='discussion-research-tools.v1'
  AND i.tool_key IN ('research.search_public','research.capture_snapshot')
  AND i.input_body->>'version'='discussion-research-tools.v1'
  AND i.input_body->>'source_digest'=r.run_context->>'discussion_source_digest') OR
  (r.agent_key='engineering_intelligence'
  AND r.run_context->>'impact_toolset_version'='application-engineering-tools.v1'
  AND a.body->>'purpose'='change_work_package'
  AND a.body->>'toolset_version'='application-engineering-tools.v1'
  AND i.tool_key IN ('engineering.trace_impact','change.prepare_work_package')
  AND i.input_body->>'source_digest'=r.run_context->'impact_source'->>'digest'
  AND i.input_body->>'ecr_id'=r.run_context->>'impact_ecr_id'
  AND NEW.metadata->>'allowed_purpose'='change_work_package') OR
  (r.agent_key='quality_intelligence'
  AND r.context_version='quality-work-package-request-v1'
  AND r.run_context->>'quality_toolset_version'='application-quality-tools.v1'
  AND a.body->>'purpose'='quality_work_package'
  AND a.body->>'toolset_version'='application-quality-tools.v1'
  AND i.tool_key='quality.prepare_capa'
  AND i.input_body->>'source_digest'=r.run_context->'quality_source'->>'digest'
  AND i.input_body->>'ncr_id'=r.run_context->>'quality_ncr_id'
  AND NEW.metadata->>'allowed_purpose'='quality_work_package'))
  AND d.tenant_id=NEW.tenant_id AND d.run_id=NEW.run_id AND d.lease_token=token
  AND NEW.metadata->>'id'=NEW.id::text
  AND NEW.metadata->>'run_id'=NEW.run_id::text
  AND NEW.metadata->>'tenant_id'=NEW.tenant_id::text
  AND NEW.metadata->>'tool_call_id'=i.id::text
  AND cehub_ai.application_lease_is_current(r.id,token)) IS NOT TRUE THEN
  RAISE EXCEPTION 'APPLICATION_TOOL_OBSERVATION_INVALID' USING ERRCODE='22023';
 END IF;
 RETURN NEW;
END $function$;

CREATE FUNCTION cehub_ai.guard_xiaopai_research_receipt() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF OLD.context_version='xiaopai-conversation-v1' AND OLD.run_context ? 'reply_research'
  AND NEW.run_context->'reply_research' IS DISTINCT FROM OLD.run_context->'reply_research' THEN
  RAISE EXCEPTION 'Conversation research receipt is immutable'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_xiaopai_research_receipt() FROM PUBLIC;
CREATE TRIGGER guard_xiaopai_research_receipt BEFORE UPDATE ON cehub_ai.agent_runs
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_xiaopai_research_receipt();
"""


def upgrade() -> None:
    op.execute(CURRENT)


def downgrade() -> None:
    op.execute("DROP TRIGGER guard_xiaopai_research_receipt ON cehub_ai.agent_runs")
    op.execute("DROP FUNCTION cehub_ai.guard_xiaopai_research_receipt()")
    op.execute(PRIOR)
