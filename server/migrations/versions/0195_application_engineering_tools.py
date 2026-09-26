"""Actual application tool observations share the existing cumulative intent ledger."""

import sqlalchemy as sa
from alembic import op

revision = "0195_application_engineering_tools"
down_revision = "0194_conversation_engineering_changes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE cehub_ai.application_tool_observations (
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL,run_id uuid NOT NULL,
 authorization_id uuid NOT NULL,tool_intent_id uuid NOT NULL,
 metadata jsonb NOT NULL,output_body jsonb NOT NULL,created_at timestamptz NOT NULL,
 CONSTRAINT uq_application_tool_observation_scope UNIQUE(tenant_id,run_id,id),
 CONSTRAINT uq_application_tool_observation_intent UNIQUE(tool_intent_id),
 FOREIGN KEY(tenant_id,run_id,authorization_id)
  REFERENCES cehub_ai.application_authorizations(tenant_id,run_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,run_id,tool_intent_id)
  REFERENCES cehub_ai.agent_tool_intents(tenant_id,run_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tool_intent_id)
  REFERENCES cehub_ai.agent_tool_dispatches(intent_id) ON DELETE RESTRICT,
 CONSTRAINT ck_application_tool_observations_shape
  CHECK(jsonb_typeof(metadata)='object' AND jsonb_typeof(output_body)='object')
);
CREATE TRIGGER protect_application_tool_observation BEFORE UPDATE OR DELETE
 ON cehub_ai.application_tool_observations
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_ai.application_tool_observations FROM PUBLIC;

CREATE FUNCTION cehub_ai.require_application_tool_observation() RETURNS trigger
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
REVOKE ALL ON FUNCTION cehub_ai.require_application_tool_observation() FROM PUBLIC;
CREATE TRIGGER require_application_tool_observation BEFORE INSERT
 ON cehub_ai.application_tool_observations
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.require_application_tool_observation();
""")


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_ai.application_tool_observations) OR "
                "EXISTS(SELECT 1 FROM cehub_ai.agent_tool_intents WHERE tool_key IN "
                "('engineering.trace_impact','change.prepare_work_package'))"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Refusing to discard engineering tool history")
    op.execute("DROP TABLE cehub_ai.application_tool_observations")
    op.execute("DROP FUNCTION cehub_ai.require_application_tool_observation()")
