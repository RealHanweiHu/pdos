"""Actual model-selected public research under original discussion authority."""

import sqlalchemy as sa
from alembic import op

revision = "0213_discussion_research_tools"
down_revision = "0212_discussion_research"
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

OLD_KNOWN = """
CREATE OR REPLACE FUNCTION cehub_ai.discussion_resume_history_known(t uuid,rid uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT NOT EXISTS(SELECT 1 FROM cehub_ai.model_call_sessions s WHERE s.tenant_id=t AND
s.run_id=rid
  AND NOT EXISTS(SELECT 1 FROM cehub_ai.model_call_events e
   WHERE e.tenant_id=t AND e.session_id=s.id AND e.state='closed'))
 AND NOT EXISTS(SELECT 1 FROM (
  SELECT DISTINCT ON(j.attempt_id) j.reservation_status FROM cehub_ai.budget_journal j
  JOIN cehub_ai.budget_run_links b ON b.tenant_id=j.tenant_id AND b.lineage_id=j.lineage_id
  WHERE b.tenant_id=t AND b.run_id=rid ORDER BY j.attempt_id,j.revision DESC
 ) latest WHERE latest.reservation_status IN ('reserved','unknown'))
 AND NOT EXISTS(SELECT 1 FROM cehub_ai.budget_journal j WHERE j.tenant_id=t AND j.run_id=rid
  AND NOT EXISTS(SELECT 1 FROM cehub_ai.application_result_checkpoints cp
   WHERE cp.tenant_id=t AND cp.run_id=rid AND
cp.model_call_id::text=j.request_binding->>'model_call_id'));
$$;

"""

KNOWN = """
CREATE OR REPLACE FUNCTION cehub_ai.discussion_resume_history_known(t uuid,rid uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT NOT EXISTS(SELECT 1 FROM cehub_ai.agent_tool_dispatches d
 WHERE d.tenant_id=t AND d.run_id=rid AND NOT EXISTS(
 SELECT 1 FROM cehub_ai.application_tool_observations o WHERE o.tenant_id=t AND o.run_id=rid
 AND o.tool_intent_id=d.intent_id)) AND NOT EXISTS(
 SELECT 1 FROM cehub_ai.model_call_sessions s WHERE s.tenant_id=t AND
s.run_id=rid
  AND NOT EXISTS(SELECT 1 FROM cehub_ai.model_call_events e
   WHERE e.tenant_id=t AND e.session_id=s.id AND e.state='closed'))
 AND NOT EXISTS(SELECT 1 FROM (
  SELECT DISTINCT ON(j.attempt_id) j.reservation_status FROM cehub_ai.budget_journal j
  JOIN cehub_ai.budget_run_links b ON b.tenant_id=j.tenant_id AND b.lineage_id=j.lineage_id
  WHERE b.tenant_id=t AND b.run_id=rid ORDER BY j.attempt_id,j.revision DESC
 ) latest WHERE latest.reservation_status IN ('reserved','unknown'))
 AND NOT EXISTS(SELECT 1 FROM cehub_ai.budget_journal j WHERE j.tenant_id=t AND j.run_id=rid
  AND NOT EXISTS(SELECT 1 FROM cehub_ai.application_result_checkpoints cp
   WHERE cp.tenant_id=t AND cp.run_id=rid AND
cp.model_call_id::text=j.request_binding->>'model_call_id'));
$$;

"""

OLD_SOURCE = """


CREATE OR REPLACE FUNCTION cehub_ai.guard_discussion_research() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings b
 JOIN cehub_ai.agent_runs r ON r.tenant_id=b.tenant_id AND r.id=b.run_id
 JOIN cehub_ai.debate_turns t ON t.tenant_id=b.tenant_id AND t.session_id=b.session_id
 JOIN cehub_evidence.evidence_snapshots s ON s.tenant_id=b.tenant_id AND s.id=NEW.snapshot_id
 JOIN cehub_evidence.research_sources rs ON rs.tenant_id=s.tenant_id AND rs.id=s.source_id
 JOIN cehub_evidence.evidence_contents ec
 ON ec.tenant_id=s.tenant_id AND ec.content_digest=s.content_digest
 WHERE b.tenant_id=NEW.tenant_id AND b.run_id=NEW.run_id AND b.session_id=NEW.session_id
 AND r.status IN ('queued','running') AND t.id=NEW.turn_id AND t.speaker_kind='human'
 AND t.author_user_id=NEW.actor_user_id AND rs.status='active'
 AND rs.source_type IN ('web','api') AND s.url IS NOT NULL AND s.taint='untrusted_external'
 AND NEW.request->>'snapshot_id'=s.id::text
 AND NEW.request->>'request_id'=NEW.request_id::text
 AND NEW.request->>'expected_digest'=NEW.reference->>'digest'
 AND NEW.reference->>'category'='public_research_snapshot'
 AND NEW.reference->'fields'->>'id'=s.id::text
 AND NEW.reference->'fields'->>'content_digest'=s.content_digest
 AND NEW.reference->'fields'->>'source_id'=s.source_id::text
 AND NEW.reference->'fields'->>'url'=s.url
 AND NEW.reference->'fields'->>'taint'=s.taint
 AND (NEW.request->>'offset')::integer BETWEEN 0 AND 2000000
 AND (NEW.request->>'length')::integer BETWEEN 1 AND 6000
 AND NEW.reference->'fields'->>'excerpt'=substring(ec.body
 FROM (NEW.request->>'offset')::integer+1 FOR (NEW.request->>'length')::integer)) THEN
 RAISE EXCEPTION 'research input requires actual public snapshot and named addition'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

"""

SOURCE = """


CREATE OR REPLACE FUNCTION cehub_ai.guard_discussion_research() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings b
 JOIN cehub_ai.agent_runs r ON r.tenant_id=b.tenant_id AND r.id=b.run_id
 JOIN cehub_ai.debate_turns t ON t.tenant_id=b.tenant_id AND t.session_id=b.session_id
 JOIN cehub_evidence.evidence_snapshots s ON s.tenant_id=b.tenant_id AND s.id=NEW.snapshot_id
 LEFT JOIN cehub_evidence.research_sources rs ON rs.tenant_id=s.tenant_id AND rs.id=s.source_id
 JOIN cehub_evidence.evidence_contents ec
 ON ec.tenant_id=s.tenant_id AND ec.content_digest=s.content_digest
 WHERE b.tenant_id=NEW.tenant_id AND b.run_id=NEW.run_id AND b.session_id=NEW.session_id
 AND r.status IN ('queued','running') AND t.id=NEW.turn_id AND t.speaker_kind='human'
 AND t.author_user_id=NEW.actor_user_id AND (s.source_id IS NULL OR
 (rs.status='active' AND rs.source_type IN ('web','api')))
 AND s.url IS NOT NULL AND s.taint='untrusted_external'
 AND NEW.request->>'snapshot_id'=s.id::text
 AND NEW.request->>'request_id'=NEW.request_id::text
 AND NEW.request->>'expected_digest'=NEW.reference->>'digest'
 AND NEW.reference->>'category'='public_research_snapshot'
 AND NEW.reference->'fields'->>'id'=s.id::text
 AND NEW.reference->'fields'->>'content_digest'=s.content_digest
 AND (NEW.reference->'fields'->>'source_id') IS NOT DISTINCT FROM s.source_id::text
 AND NEW.reference->'fields'->>'url'=s.url
 AND NEW.reference->'fields'->>'taint'=s.taint
 AND (NEW.request->>'offset')::integer BETWEEN 0 AND 2000000
 AND (NEW.request->>'length')::integer BETWEEN 1 AND 6000
 AND NEW.reference->'fields'->>'excerpt'=substring(ec.body
 FROM (NEW.request->>'offset')::integer+1 FOR (NEW.request->>'length')::integer)) THEN
 RAISE EXCEPTION 'research input requires actual public snapshot and named addition'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

"""

GUARDS = """

CREATE FUNCTION cehub_ai.guard_discussion_research_tool() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.tool_key NOT IN ('research.search_public','research.capture_snapshot') THEN
 RETURN NEW; END IF;
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings b
 JOIN cehub_ai.agent_runs r ON r.tenant_id=b.tenant_id AND r.id=b.run_id
 JOIN cehub_ai.application_result_checkpoints cp ON cp.tenant_id=b.tenant_id AND cp.run_id=b.run_id
 JOIN cehub_ai.application_context_observations o ON o.tenant_id=cp.tenant_id
 AND o.id=cp.observation_id
 WHERE b.tenant_id=NEW.tenant_id AND b.run_id=NEW.run_id AND r.status='running'
 AND r.run_context->>'discussion_toolset_version'='discussion-research-tools.v1'
 AND NEW.input_body->>'version'='discussion-research-tools.v1'
 AND cp.id::text=NEW.input_body->>'checkpoint_id'
 AND cp.model_call_id::text=NEW.input_body->>'model_call_id'
 AND cp.body->'output'=NEW.input_body->'choice'
 AND b.source->>'digest'=NEW.input_body->>'source_digest'
 AND o.output_body->>'phase'='discussion_research'
 AND o.output_body->'source'->>'digest'=b.source->>'digest'
 AND (o.output_body->>'research_step')::integer BETWEEN 1 AND
 (b.config->'request'->>'research_steps')::integer
 AND (o.output_body->>'round_number')::integer BETWEEN 1 AND
 (b.config->'request'->>'rounds')::integer
 AND EXISTS(SELECT 1 FROM jsonb_array_elements(b.config->'seats') seat
 WHERE seat->>'id'=o.output_body->'projection'->>'id')
 AND (NOT (b.config ? 'initiation') OR EXISTS(
 SELECT 1 FROM cehub_ai.debate_initiations di,
 jsonb_array_elements(di.output->'seats') chosen
 WHERE di.tenant_id=b.tenant_id AND di.run_id=b.run_id AND di.output->>'action'='convene'
 AND chosen->>'key'=o.output_body->'projection'->>'key'))
 AND ((NEW.tool_key='research.search_public' AND NEW.input_body->'choice'->>'action'='search')
 OR (NEW.tool_key='research.capture_snapshot' AND NEW.input_body->'choice'->>'action'='read')))
 THEN RAISE EXCEPTION 'Research requires original scoped model choice'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_discussion_research_tool BEFORE INSERT ON cehub_ai.agent_tool_intents
FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_discussion_research_tool();
REVOKE ALL ON FUNCTION cehub_ai.guard_discussion_research_tool() FROM PUBLIC;

CREATE FUNCTION cehub_ai.guard_discussion_research_result() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE i cehub_ai.agent_tool_intents; ref jsonb;
BEGIN
 SELECT * INTO i FROM cehub_ai.agent_tool_intents WHERE tenant_id=NEW.tenant_id
 AND run_id=NEW.run_id AND id=NEW.tool_intent_id;
 IF i.tool_key NOT IN ('research.search_public','research.capture_snapshot') THEN RETURN NEW;
 END IF;
 ref:=NEW.output_body->'reference';
 IF ref IS NULL OR ref='null'::jsonb THEN RETURN NEW; END IF;
 IF i.tool_key<>'research.capture_snapshot' OR NOT EXISTS(
 SELECT 1 FROM cehub_evidence.evidence_snapshots s JOIN cehub_evidence.evidence_contents ec
 ON ec.tenant_id=s.tenant_id AND ec.content_digest=s.content_digest
 WHERE s.tenant_id=NEW.tenant_id AND s.id::text=ref->'fields'->>'id'
 AND s.content_digest=ref->'fields'->>'content_digest' AND s.taint='untrusted_external'
 AND s.url=ref->'fields'->>'url' AND s.source_id IS NULL
 AND ref->>'category'='public_research_snapshot'
 AND ref->'fields'->>'excerpt'=substring(ec.body
 FROM (i.input_body->'choice'->>'offset')::integer+1
 FOR (i.input_body->'choice'->>'length')::integer)) THEN
 RAISE EXCEPTION 'Research result requires actual captured public excerpt'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_discussion_research_result BEFORE INSERT ON
cehub_ai.application_tool_observations
FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_discussion_research_result();
REVOKE ALL ON FUNCTION cehub_ai.guard_discussion_research_result() FROM PUBLIC;

CREATE FUNCTION cehub_ai.guard_discussion_research_binding() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF coalesce((NEW.config->'request'->>'research_steps')::integer,0)=0 THEN RETURN NEW; END IF;
 IF (NEW.config->'request'->>'research_steps')::integer NOT BETWEEN 1 AND 3
 OR NOT EXISTS(SELECT 1 FROM cehub_ai.agent_runs r WHERE r.tenant_id=NEW.tenant_id
 AND r.id=NEW.run_id AND r.run_context->>'discussion_research_version'='discussion-research-v1'
 AND r.run_context->>'discussion_toolset_version'='discussion-research-tools.v1') THEN
 RAISE EXCEPTION 'Research must use a fixed bounded run version' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_discussion_research_binding BEFORE INSERT ON cehub_ai.debate_run_bindings
FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_discussion_research_binding();
REVOKE ALL ON FUNCTION cehub_ai.guard_discussion_research_binding() FROM PUBLIC;

"""


def upgrade() -> None:
    for sql in (OBSERVATION, KNOWN, SOURCE, GUARDS):
        op.execute(sa.text(sql))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""SELECT EXISTS(SELECT 1 FROM cehub_ai.agent_runs
    WHERE run_context->>'discussion_toolset_version'='discussion-research-tools.v1')""")
        )
        .scalar()
    ):
        raise RuntimeError("Refusing to discard original research tool history")
    for table, name in (
        ("agent_tool_intents", "guard_discussion_research_tool"),
        ("application_tool_observations", "guard_discussion_research_result"),
        ("debate_run_bindings", "guard_discussion_research_binding"),
    ):
        op.execute(f"DROP TRIGGER {name} ON cehub_ai.{table}")
        op.execute(f"DROP FUNCTION cehub_ai.{name}()")
    for sql in (OLD_OBSERVATION, OLD_KNOWN, OLD_SOURCE):
        op.execute(sa.text(sql))
