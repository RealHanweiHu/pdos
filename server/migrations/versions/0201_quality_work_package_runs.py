"""Quality preparation shares application authorization, lease and tool history."""

import sqlalchemy as sa
from alembic import op

revision = "0201_quality_work_package_runs"
down_revision = "0200_quality_work_package_application"
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
 IF (r.agent_key='engineering_intelligence'
  AND r.run_context->>'impact_toolset_version'='application-engineering-tools.v1'
  AND a.body->>'purpose'='change_work_package'
  AND a.body->>'toolset_version'='application-engineering-tools.v1'
  AND i.tool_key IN ('engineering.trace_impact','change.prepare_work_package')
  AND i.input_body->>'source_digest'=r.run_context->'impact_source'->>'digest'
  AND i.input_body->>'ecr_id'=r.run_context->>'impact_ecr_id'
  AND d.tenant_id=NEW.tenant_id AND d.run_id=NEW.run_id AND d.lease_token=token
  AND NEW.metadata->>'id'=NEW.id::text
  AND NEW.metadata->>'run_id'=NEW.run_id::text
  AND NEW.metadata->>'tenant_id'=NEW.tenant_id::text
  AND NEW.metadata->>'tool_call_id'=i.id::text
  AND NEW.metadata->>'allowed_purpose'='change_work_package'
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
ORIGIN = """

CREATE FUNCTION cehub_ai.guard_quality_work_package_origin() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
IF TG_OP='UPDATE' AND OLD.finding_type='capa_work_package' AND
(NEW.finding_type<>OLD.finding_type OR NEW.proposed_payload IS DISTINCT FROM OLD.proposed_payload
OR NEW.run_id<>OLD.run_id OR NEW.model_invocation_id IS DISTINCT FROM OLD.model_invocation_id)
THEN RAISE EXCEPTION 'Quality candidate origin is immutable' USING ERRCODE='23514'; END IF;
IF NEW.finding_type<>'capa_work_package' THEN RETURN NEW; END IF;
IF NEW.evidence_event_ids<>'[]'::jsonb OR NOT EXISTS(
SELECT 1 FROM cehub_ai.agent_runs r JOIN cehub_ai.model_invocations i
ON i.tenant_id=r.tenant_id AND i.project_id=r.project_id AND i.run_id=r.id
WHERE r.tenant_id=NEW.tenant_id AND r.project_id=NEW.project_id AND r.id=NEW.run_id
AND r.agent_key='quality_intelligence' AND r.context_version='quality-work-package-request-v1'
AND i.id=NEW.model_invocation_id AND i.agent_key=r.agent_key AND i.status='succeeded'
AND i.prompt_version=r.run_context->>'quality_prompt_version'
AND NEW.proposed_payload->>'ncr_id'=r.run_context->'quality_source'->>'ncr_id'
AND NEW.proposed_payload->>'source_digest'=r.run_context->'quality_source'->>'digest'
AND NEW.proposed_payload->'assessment'->>'phase'=r.run_context->'quality_source'->>'phase'
) THEN RAISE EXCEPTION 'Quality candidate must bind actual model run and sources'
USING ERRCODE='23514'; END IF;
IF NEW.accepted_payload IS NOT NULL AND EXISTS(SELECT 1 FROM
unnest(ARRAY['ncr_id','source_digest','assessment']) k
WHERE NEW.accepted_payload->k IS DISTINCT FROM NEW.proposed_payload->k)
THEN RAISE EXCEPTION 'Review must retain source and original assessment'
USING ERRCODE='23514'; END IF;
RETURN NEW;
END $$
"""


def upgrade() -> None:
    op.execute(sa.text(OBSERVATION))
    op.execute(sa.text(ORIGIN))
    op.execute(
        "CREATE TRIGGER guard_quality_work_package_origin BEFORE INSERT OR UPDATE "
        "ON cehub_ai.findings FOR EACH ROW EXECUTE FUNCTION "
        "cehub_ai.guard_quality_work_package_origin()"
    )
    op.execute("REVOKE ALL ON FUNCTION cehub_ai.guard_quality_work_package_origin() FROM PUBLIC")


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_ai.agent_runs "
                "WHERE context_version='quality-work-package-request-v1') OR EXISTS(SELECT 1 "
                "FROM cehub_ai.findings WHERE finding_type='capa_work_package') OR EXISTS(SELECT 1 "
                "FROM cehub_ai.agent_tool_intents WHERE tool_key='quality.prepare_capa')"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Refusing to discard quality preparation history")
    op.execute("DROP TRIGGER guard_quality_work_package_origin ON cehub_ai.findings")
    op.execute("DROP FUNCTION cehub_ai.guard_quality_work_package_origin()")
    op.execute(sa.text(OLD_OBSERVATION))
