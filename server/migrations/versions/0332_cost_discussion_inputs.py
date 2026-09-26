"""Actual discussion receipts and original budget lineage for cost follow-up."""

from alembic import op

revision = "0332_cost_discussion_inputs"
down_revision = "0331_cost_reduction_findings"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_ai.cost_discussion_inputs (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	project_id UUID NOT NULL,
	run_id UUID NOT NULL,
	discussion_run_id UUID NOT NULL,
	source_digest VARCHAR(64) NOT NULL,
	brief_digest VARCHAR(64) NOT NULL,
	body JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_cost_discussion_inputs PRIMARY KEY (id),
	CONSTRAINT uq_cost_discussion_input_run UNIQUE (tenant_id, run_id),
	CONSTRAINT uq_cost_discussion_input_source UNIQUE (tenant_id, discussion_run_id),
        CONSTRAINT fk_cost_discussion_analysis FOREIGN KEY(tenant_id, run_id) REFERENCES
cehub_ai.agent_runs (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_cost_discussion_original FOREIGN KEY(tenant_id, discussion_run_id)
REFERENCES cehub_ai.debate_run_bindings (tenant_id, run_id) ON DELETE RESTRICT,
        CONSTRAINT fk_cost_discussion_project FOREIGN KEY(tenant_id, project_id) REFERENCES
cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_cost_discussion_inputs_shape CHECK (source_digest ~ '^[a-f0-9]{64}$' AND
brief_digest ~ '^[a-f0-9]{64}$' AND jsonb_typeof(body)='object')
)

;
"""

GUARDS = """
CREATE FUNCTION cehub_ai.guard_cost_discussion_input() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE analysis cehub_ai.agent_runs; discussion cehub_ai.agent_runs;
 b cehub_ai.debate_run_bindings; a cehub_ai.application_authorizations;
 pa cehub_ai.application_authorizations; actual_turns jsonb;
BEGIN
 SELECT * INTO analysis FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;
 SELECT * INTO discussion FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id
 AND id=NEW.discussion_run_id FOR UPDATE;
 SELECT * INTO b FROM cehub_ai.debate_run_bindings WHERE tenant_id=NEW.tenant_id
 AND run_id=NEW.discussion_run_id;
 SELECT * INTO a FROM cehub_ai.application_authorizations WHERE tenant_id=NEW.tenant_id
 AND run_id=NEW.run_id;
 SELECT * INTO pa FROM cehub_ai.application_authorizations WHERE tenant_id=NEW.tenant_id
 AND run_id=NEW.discussion_run_id;
 IF (analysis.context_version='cost-reduction-request-v1'
 AND analysis.agent_key='engineering_intelligence' AND discussion.status='succeeded'
 AND analysis.project_id=NEW.project_id AND discussion.project_id=NEW.project_id
 AND b.project_id=NEW.project_id AND b.topic_kind='project'
 AND b.source->>'source_kind'='project_discussion'
 AND analysis.requested_by_user_id=discussion.requested_by_user_id
 AND b.source->>'actor_id'=analysis.requested_by_user_id::text
 AND b.source->'selections' @> jsonb_build_array(jsonb_build_object(
 'kind','cost_gap_observation','id',analysis.run_context->'cost_selection'->>'observation_id'))
 AND analysis.run_context->>'cost_discussion_run_id'=discussion.id::text
 AND analysis.run_context->>'cost_prompt_version'='cost-reduction-v2'
 AND analysis.run_context->'cost_source'->'discussion_input'=NEW.body
 AND NEW.body->>'version'='cost-discussion-input.v1'
 AND NEW.body->>'discussion_run_id'=discussion.id::text
 AND NEW.body->>'session_id'=b.session_id::text
 AND NEW.body->>'actor_id'=analysis.requested_by_user_id::text
 AND NEW.body->>'source_digest'=NEW.source_digest
 AND NEW.source_digest=b.source->>'digest' AND NEW.body->>'digest'=NEW.brief_digest
 AND NEW.body->'body'->>'run_id'=discussion.id::text
 AND NEW.body->'body'->>'source_digest'=NEW.source_digest
 AND NEW.body->'body'->>'run_status'='succeeded'
 AND NEW.body->'body'->>'status'='completed'
 AND NEW.body->'body'->'complete'='true'::jsonb
 AND NEW.body->'body'->'recovery_requested'='false'::jsonb
 AND a.lineage_id=pa.lineage_id AND a.principal_id=pa.principal_id
 AND (a.pins-'action')=(pa.pins-'action') AND a.expires_at<=pa.expires_at
 AND a.body->>'policy_version'=pa.body->>'policy_version'
 AND a.body->>'purpose'='cost_reduction' AND pa.body->>'purpose'='change_discussion'
 ) IS NOT TRUE THEN
 RAISE EXCEPTION 'Cost follow-up requires actual discussion, authority and original budget'
 USING ERRCODE='23514'; END IF;
 SELECT coalesce(jsonb_agg(t.id::text ORDER BY t.sequence),'[]'::jsonb) INTO actual_turns
 FROM cehub_ai.debate_turns t WHERE t.tenant_id=NEW.tenant_id AND t.session_id=b.session_id;
 IF NEW.body->'body'->'turn_ids' IS DISTINCT FROM actual_turns OR NOT EXISTS(
 SELECT 1 FROM cehub_ai.debate_turn_receipts tr WHERE tr.tenant_id=NEW.tenant_id
 AND tr.run_id=discussion.id) OR EXISTS(
 SELECT 1 FROM jsonb_array_elements(NEW.body->'body'->'positions') p WHERE NOT EXISTS(
 SELECT 1 FROM cehub_ai.debate_turn_receipts tr WHERE tr.tenant_id=NEW.tenant_id
 AND tr.run_id=discussion.id AND tr.turn_id::text=p->>'turn_id'
 AND tr.checkpoint_id::text=p->>'checkpoint_id'
 AND tr.output->'statements'->(p->>'statement_index')::integer=p->'statement')) THEN
 RAISE EXCEPTION 'Cost discussion input must retain original turns and actual receipts'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER guard_cost_discussion_input AFTER INSERT ON
cehub_ai.cost_discussion_inputs DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_cost_discussion_input();

CREATE FUNCTION cehub_ai.guard_cost_discussion_run() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='UPDATE' AND OLD.run_context->>'cost_discussion_run_id' IS NOT NULL AND (
 NEW.run_context->>'cost_discussion_run_id' IS DISTINCT FROM
 OLD.run_context->>'cost_discussion_run_id'
 OR NEW.run_context->'cost_source' IS DISTINCT FROM OLD.run_context->'cost_source'
 OR NEW.run_context->>'cost_prompt_version' IS DISTINCT FROM
 OLD.run_context->>'cost_prompt_version') THEN
 RAISE EXCEPTION 'Cost discussion origin is immutable' USING ERRCODE='23514'; END IF;
 IF NEW.run_context->>'cost_discussion_run_id' IS NOT NULL
 OR NEW.run_context->>'cost_prompt_version'='cost-reduction-v2' THEN
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.cost_discussion_inputs i
 WHERE i.tenant_id=NEW.tenant_id AND i.project_id=NEW.project_id AND i.run_id=NEW.id
 AND i.discussion_run_id::text=NEW.run_context->>'cost_discussion_run_id'
 AND i.body=NEW.run_context->'cost_source'->'discussion_input') THEN
 RAISE EXCEPTION 'Cost follow-up must commit with original discussion receipt'
 USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER guard_cost_discussion_run AFTER INSERT OR UPDATE ON cehub_ai.agent_runs
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_cost_discussion_run();
CREATE TRIGGER protect_cost_discussion_inputs BEFORE UPDATE OR DELETE ON
cehub_ai.cost_discussion_inputs FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON FUNCTION cehub_ai.guard_cost_discussion_input() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.guard_cost_discussion_run() FROM PUBLIC;
REVOKE ALL ON cehub_ai.cost_discussion_inputs FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute("""
DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.cost_discussion_inputs) OR EXISTS(
 SELECT 1 FROM cehub_ai.agent_runs WHERE run_context->>'cost_discussion_run_id' IS NOT NULL
 OR run_context->>'cost_prompt_version'='cost-reduction-v2') THEN
 RAISE EXCEPTION 'Cost discussion history requires retention'; END IF; END $$;
DROP TRIGGER guard_cost_discussion_run ON cehub_ai.agent_runs;
DROP FUNCTION cehub_ai.guard_cost_discussion_run();
DROP TABLE cehub_ai.cost_discussion_inputs;
DROP FUNCTION cehub_ai.guard_cost_discussion_input();
""")
