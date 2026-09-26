"""Bind discussion follow-up candidates to actual turns and original budgets."""

import sqlalchemy as sa
from alembic import op

revision = "0215_discussion_followup"
down_revision = "0214_discussion_convene"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_ai.change_discussion_inputs (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    run_id UUID NOT NULL,
    origin_run_id UUID NOT NULL,
    discussion_run_id UUID NOT NULL,
    brief_digest VARCHAR(64) NOT NULL,
    body JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_change_discussion_inputs PRIMARY KEY (id),
    CONSTRAINT uq_change_discussion_input_run UNIQUE (tenant_id, run_id),
    CONSTRAINT uq_change_discussion_input_origin UNIQUE (tenant_id, origin_run_id),
    CONSTRAINT uq_change_discussion_input_source UNIQUE (tenant_id, discussion_run_id),
    CONSTRAINT fk_change_discussion_input_run FOREIGN KEY(tenant_id, run_id)
REFERENCES cehub_ai.agent_runs (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_change_discussion_input_origin FOREIGN KEY(tenant_id,
origin_run_id) REFERENCES cehub_ai.agent_runs (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_change_discussion_inputs_tenant_id_debate_run_bindings FOREIGN KEY(tenant_id,
discussion_run_id) REFERENCES cehub_ai.debate_run_bindings (tenant_id, run_id) ON DELETE
RESTRICT,
    CONSTRAINT ck_change_discussion_inputs_shape CHECK (run_id<>origin_run_id AND
run_id<>discussion_run_id AND origin_run_id<>discussion_run_id AND brief_digest ~
'^[a-f0-9]{64}$' AND jsonb_typeof(body)='object' AND body->>'complete'='true')
)

;

CREATE TRIGGER protect_change_discussion_inputs BEFORE UPDATE OR DELETE ON
cehub_ai.change_discussion_inputs FOR EACH ROW EXECUTE FUNCTION
cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_ai.change_discussion_inputs FROM PUBLIC;

CREATE FUNCTION cehub_ai.guard_change_discussion_input() RETURNS trigger
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
CREATE CONSTRAINT TRIGGER guard_change_discussion_input AFTER INSERT ON
cehub_ai.change_discussion_inputs DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_change_discussion_input();
REVOKE ALL ON FUNCTION cehub_ai.guard_change_discussion_input() FROM PUBLIC;

CREATE FUNCTION cehub_ai.guard_discussion_followup_run() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='UPDATE' AND (
 NEW.run_context->'discussion_followup_version' IS DISTINCT FROM
OLD.run_context->'discussion_followup_version'
 OR NEW.run_context->'discussion_followup_queue' IS DISTINCT FROM
OLD.run_context->'discussion_followup_queue'
 OR NEW.run_context->'impact_source'->'discussion_input' IS DISTINCT FROM
OLD.run_context->'impact_source'->'discussion_input'
 OR ((OLD.run_context ? 'discussion_followup_queue' OR
 OLD.run_context ? 'discussion_followup_version') AND EXISTS(SELECT 1 FROM
unnest(ARRAY['impact_source','impact_prompt_version','impact_toolset_version','impact_schema_digest',
'impact_allow_discussion','impact_depth','impact_ecr_id','impact_expected_digest','impact_user_instruction'])
k
 WHERE NEW.run_context->k IS DISTINCT FROM OLD.run_context->k))) THEN
 RAISE EXCEPTION 'Discussion follow-up input and version are immutable' USING ERRCODE='23514';
END IF;
 IF NEW.run_context ? 'discussion_followup_queue' AND NOT EXISTS(
 SELECT 1 FROM cehub_ai.change_discussion_inputs i WHERE i.tenant_id=NEW.tenant_id AND
i.run_id=NEW.id
 AND NEW.run_context->'impact_source'->'discussion_input'->>'id'=i.id::text) THEN
 RAISE EXCEPTION 'Discussion follow-up requires its fixed input' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER guard_discussion_followup_run AFTER INSERT OR UPDATE ON
cehub_ai.agent_runs DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_discussion_followup_run();
REVOKE ALL ON FUNCTION cehub_ai.guard_discussion_followup_run() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(sa.text(DDL))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_ai.change_discussion_inputs) "
                "OR EXISTS(SELECT 1 FROM cehub_ai.agent_runs "
                "WHERE run_context ? 'discussion_followup_version')"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Refusing to discard discussion follow-up inputs or authorized requests")
    op.execute("DROP TRIGGER guard_discussion_followup_run ON cehub_ai.agent_runs")
    op.execute("DROP FUNCTION cehub_ai.guard_discussion_followup_run()")
    op.execute("DROP TABLE cehub_ai.change_discussion_inputs")
    op.execute("DROP FUNCTION cehub_ai.guard_change_discussion_input()")
