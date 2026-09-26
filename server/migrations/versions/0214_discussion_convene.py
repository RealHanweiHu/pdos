"""Trace Agent-requested child discussions to original model choices and budgets."""

import sqlalchemy as sa
from alembic import op

revision = "0214_discussion_convene"
down_revision = "0213_discussion_research_tools"
branch_labels = None
depends_on = None

OLD_OBSERVATION = """


CREATE OR REPLACE FUNCTION cehub_ai.require_application_tool_observation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; a cehub_ai.application_authorizations%ROWTYPE;
 i cehub_ai.agent_tool_intents%ROWTYPE; d cehub_ai.agent_tool_dispatches%ROWTYPE;
 token uuid:=nullif(current_setting('pdos.application_lease_id',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;
 SELECT * INTO a FROM cehub_ai.application_authorizations WHERE id=NEW.authorization_id;
 SELECT * INTO i FROM cehub_ai.agent_tool_intents WHERE id=NEW.tool_intent_id;
 SELECT * INTO d FROM cehub_ai.agent_tool_dispatches WHERE intent_id=NEW.tool_intent_id;
 IF (((r.agent_key='engineering_intelligence'
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
END $body$;


"""

OBSERVATION = """


CREATE OR REPLACE FUNCTION cehub_ai.require_application_tool_observation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $body$
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
END $body$;


"""

GUARDS = """

CREATE FUNCTION cehub_ai.guard_discussion_origin() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.origin_run_id IS NULL THEN RETURN NEW; END IF;
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.agent_runs p
 JOIN cehub_ai.agent_runs child ON child.tenant_id=p.tenant_id AND child.id=NEW.run_id
 JOIN cehub_ai.application_result_checkpoints cp ON cp.tenant_id=p.tenant_id AND cp.run_id=p.id
 JOIN cehub_ai.application_context_observations o ON o.tenant_id=cp.tenant_id
 AND o.id=cp.observation_id
 JOIN cehub_ai.budget_run_links pl ON pl.tenant_id=p.tenant_id AND pl.run_id=p.id
 JOIN cehub_ai.budget_run_links cl ON cl.tenant_id=child.tenant_id AND cl.run_id=child.id
 JOIN cehub_ai.agent_tool_intents i ON i.tenant_id=p.tenant_id AND i.run_id=p.id
 JOIN cehub_ai.application_tool_observations observation ON observation.tenant_id=i.tenant_id
 AND observation.run_id=i.run_id AND observation.tool_intent_id=i.id
 WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.origin_run_id AND p.status='running'
 AND cp.id=NEW.origin_checkpoint_id AND p.project_id=NEW.project_id
 AND child.project_id=p.project_id AND child.requested_by_user_id=p.requested_by_user_id
 AND pl.lineage_id=cl.lineage_id
 AND p.run_context->>'discussion_convene_version'='discussion-convene-v1'
 AND o.output_body->>'phase'='discussion_convene'
 AND o.output_body->>'digest'=NEW.source->>'digest'
 AND o.output_body->>'ecr_id'=NEW.ecr_id::text
 AND cp.body->'output'->>'action'='convene'
 AND cp.body->'output'->>'question'=NEW.config->'request'->>'question'
 AND NEW.config->'request'->>'participation_mode'='selected'
 AND NEW.config->'request'->>'rounds'='2'
 AND NEW.config->'request'->>'research_steps'='0'
 AND i.tool_key='discussion.convene' AND i.input_body->>'checkpoint_id'=cp.id::text
 AND observation.output_body->>'run_id'=NEW.run_id::text
 AND (SELECT jsonb_agg(seat->>'key' ORDER BY seat->>'key')
      FROM jsonb_array_elements(cp.body->'output'->'seats') seat)=
     (SELECT jsonb_agg(seat->>'key' ORDER BY seat->>'key')
      FROM jsonb_array_elements(NEW.config->'seats') seat)) THEN
 RAISE EXCEPTION 'Discussion origin requires original model choice scope and shared budget'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER guard_discussion_origin AFTER INSERT ON cehub_ai.debate_run_bindings
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_discussion_origin();
REVOKE ALL ON FUNCTION cehub_ai.guard_discussion_origin() FROM PUBLIC;
CREATE FUNCTION cehub_ai.guard_convene_intent() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.tool_key<>'discussion.convene' THEN RETURN NEW; END IF;
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.agent_runs r
 JOIN cehub_ai.application_result_checkpoints cp ON cp.tenant_id=r.tenant_id AND cp.run_id=r.id
 JOIN cehub_ai.application_context_observations o ON o.tenant_id=cp.tenant_id
 AND o.id=cp.observation_id
 WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.run_id AND r.status='running'
 AND r.run_context->>'discussion_convene_version'='discussion-convene-v1'
 AND NEW.input_body->>'version'='discussion-convene.v1'
 AND cp.id::text=NEW.input_body->>'checkpoint_id'
 AND cp.body->'output'->>'action'='convene'
 AND o.output_body->>'phase'='discussion_convene') THEN
 RAISE EXCEPTION 'Convene requires original successful model choice' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_convene_intent BEFORE INSERT ON cehub_ai.agent_tool_intents
FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_convene_intent();
REVOKE ALL ON FUNCTION cehub_ai.guard_convene_intent() FROM PUBLIC;

"""


OLD_BINDING = """

CREATE OR REPLACE FUNCTION cehub_ai.guard_debate_binding() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.agent_runs r JOIN cehub_ai.debate_sessions s
 ON s.tenant_id=r.tenant_id AND s.id=NEW.session_id
 WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.run_id AND r.project_id=NEW.project_id
 AND s.project_id=NEW.project_id AND s.topic_entity=NEW.topic_kind
 AND ((NEW.topic_kind='engineering_change_request' AND s.topic_entity_id=NEW.ecr_id)
 OR (NEW.topic_kind='project' AND s.topic_entity_id=NEW.project_id AND NEW.ecr_id IS NULL
 AND NEW.source->>'source_kind'='project_discussion'
 AND NEW.source->>'topic_id'=NEW.project_id::text
 AND NEW.source->>'actor_id'=r.requested_by_user_id::text)) AND ((s.initiated_by='user' AND
s.initiated_by_user_id=r.requested_by_user_id
 AND NOT (NEW.config ? 'initiation')) OR (s.initiated_by='agent'
 AND s.initiated_by_user_id IS NULL AND s.initiator_ref=r.id::text
 AND NEW.config->'request'->>'participation_mode'='agent_choose'
 AND r.run_context->>'discussion_initiation_version'='discussion-initiation-v1'
 AND jsonb_typeof(NEW.config->'initiation')='object'))
 AND r.context_version='change-discussion-request-v1'
 AND r.run_context->>'debate_session_id'=NEW.session_id::text
 AND r.run_context->>'discussion_source_digest'=NEW.source->>'digest') THEN
 RAISE EXCEPTION 'discussion binding does not match original run and topic'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

"""

BINDING = """

CREATE OR REPLACE FUNCTION cehub_ai.guard_debate_binding() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.agent_runs r JOIN cehub_ai.debate_sessions s
 ON s.tenant_id=r.tenant_id AND s.id=NEW.session_id
 WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.run_id AND r.project_id=NEW.project_id
 AND s.project_id=NEW.project_id AND s.topic_entity=NEW.topic_kind
 AND ((NEW.topic_kind='engineering_change_request' AND s.topic_entity_id=NEW.ecr_id)
 OR (NEW.topic_kind='project' AND s.topic_entity_id=NEW.project_id AND NEW.ecr_id IS NULL
 AND NEW.source->>'source_kind'='project_discussion'
 AND NEW.source->>'topic_id'=NEW.project_id::text
 AND NEW.source->>'actor_id'=r.requested_by_user_id::text)) AND ((s.initiated_by='user' AND
s.initiated_by_user_id=r.requested_by_user_id
 AND NOT (NEW.config ? 'initiation')) OR (s.initiated_by='agent'
 AND s.initiated_by_user_id IS NULL AND s.initiator_ref=r.id::text
 AND NEW.config->'request'->>'participation_mode'='agent_choose'
 AND r.run_context->>'discussion_initiation_version'='discussion-initiation-v1'
 AND jsonb_typeof(NEW.config->'initiation')='object') OR
 (s.initiated_by='agent' AND s.initiated_by_user_id IS NULL
 AND NEW.origin_run_id IS NOT NULL AND s.initiator_ref=NEW.origin_run_id::text
 AND NEW.config->'request'->>'participation_mode'='selected'))
 AND r.context_version='change-discussion-request-v1'
 AND r.run_context->>'debate_session_id'=NEW.session_id::text
 AND r.run_context->>'discussion_source_digest'=NEW.source->>'digest') THEN
 RAISE EXCEPTION 'discussion binding does not match original run and topic'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

"""


def upgrade() -> None:
    op.add_column("debate_run_bindings", sa.Column("origin_run_id", sa.Uuid()), schema="cehub_ai")
    op.add_column(
        "debate_run_bindings", sa.Column("origin_checkpoint_id", sa.Uuid()), schema="cehub_ai"
    )
    op.create_unique_constraint(
        "uq_debate_origin",
        "debate_run_bindings",
        ["tenant_id", "origin_run_id", "origin_checkpoint_id"],
        schema="cehub_ai",
    )
    op.create_foreign_key(
        "fk_debate_origin_checkpoint",
        "debate_run_bindings",
        "application_result_checkpoints",
        ["tenant_id", "origin_run_id", "origin_checkpoint_id"],
        ["tenant_id", "run_id", "id"],
        source_schema="cehub_ai",
        referent_schema="cehub_ai",
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_debate_run_bindings_origin_shape"),
        "debate_run_bindings",
        "(origin_run_id IS NULL AND origin_checkpoint_id IS NULL) OR "
        "(origin_run_id IS NOT NULL AND origin_checkpoint_id IS NOT NULL "
        "AND origin_run_id<>run_id AND parent_run_id IS NULL)",
        schema="cehub_ai",
    )
    op.execute(sa.text(BINDING))
    op.execute(sa.text(OBSERVATION))
    op.execute(sa.text(GUARDS))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""SELECT EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings
      WHERE origin_run_id IS NOT NULL) OR EXISTS(SELECT 1 FROM cehub_ai.agent_runs
      WHERE run_context ? 'discussion_convene_version')""")
        )
        .scalar()
    ):
        raise RuntimeError("Refusing to discard original discussion request history")
    op.execute(sa.text(OLD_BINDING))
    op.execute(sa.text(OLD_OBSERVATION))
    op.execute("DROP TRIGGER guard_discussion_origin ON cehub_ai.debate_run_bindings")
    op.execute("DROP FUNCTION cehub_ai.guard_discussion_origin()")
    op.execute("DROP TRIGGER guard_convene_intent ON cehub_ai.agent_tool_intents")
    op.execute("DROP FUNCTION cehub_ai.guard_convene_intent()")
    for name in (
        "ck_debate_run_bindings_origin_shape",
        "fk_debate_origin_checkpoint",
        "uq_debate_origin",
    ):
        op.drop_constraint(op.f(name), "debate_run_bindings", schema="cehub_ai")
    op.drop_column("debate_run_bindings", "origin_checkpoint_id", schema="cehub_ai")
    op.drop_column("debate_run_bindings", "origin_run_id", schema="cehub_ai")
