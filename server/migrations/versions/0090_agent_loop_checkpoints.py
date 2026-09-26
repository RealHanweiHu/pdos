"""Resume completed read-loop steps without repeating their model or tool calls."""

from collections.abc import Sequence
from importlib import import_module

from alembic import op

revision: str = "0090_agent_loop_checkpoints"
down_revision: str | Sequence[str] | None = "0089_application_waiting_input"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PREVIOUS = import_module("migrations.versions.0079_event_authorization")
SCHEMA = """CREATE TABLE cehub_ai.agent_loop_checkpoints (
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL,run_id uuid NOT NULL,next_step integer NOT NULL,
 model_invocation_id uuid NOT NULL,trace_ids uuid[] NOT NULL,body jsonb NOT NULL,
 body_sha256 varchar(64) NOT NULL,created_at timestamptz NOT NULL,
 CONSTRAINT uq_loop_checkpoint_step UNIQUE(tenant_id,run_id,next_step),
 CONSTRAINT uq_loop_checkpoint_scope UNIQUE(tenant_id,run_id,id),
 FOREIGN KEY(tenant_id,run_id) REFERENCES cehub_ai.agent_runs(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,run_id,model_invocation_id)
  REFERENCES cehub_ai.model_invocations(tenant_id,run_id,id) ON DELETE RESTRICT,
 CONSTRAINT ck_agent_loop_checkpoints_body CHECK(next_step BETWEEN 1 AND 99
  AND jsonb_typeof(body)='object' AND length(body_sha256)=64 AND cardinality(trace_ids)>0)
);
REVOKE ALL ON cehub_ai.agent_loop_checkpoints FROM PUBLIC;
CREATE TRIGGER protect_loop_checkpoint BEFORE UPDATE OR DELETE ON cehub_ai.agent_loop_checkpoints
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
ALTER TABLE cehub_ai.agent_run_recoveries ADD COLUMN loop_checkpoint_id uuid,
 ADD CONSTRAINT fk_recovery_loop_checkpoint FOREIGN KEY(tenant_id,run_id,loop_checkpoint_id)
 REFERENCES cehub_ai.agent_loop_checkpoints(tenant_id,run_id,id) ON DELETE RESTRICT;
"""
PORTS = r"""
CREATE OR REPLACE FUNCTION cehub_ai.save_agent_loop_checkpoint(body_text text) RETURNS uuid
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; payload jsonb; step integer; invocation uuid;
 old cehub_ai.agent_loop_checkpoints%ROWTYPE; cid uuid:=gen_random_uuid(); traces uuid[];
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid FOR UPDATE;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent loop checkpoint lease is invalid' USING ERRCODE='42501'; END IF;
 IF r.loop_binding IS NULL OR body_text IS NULL OR octet_length(body_text)>262144 THEN
  RAISE EXCEPTION 'AGENT_LOOP_CHECKPOINT_INVALID' USING ERRCODE='22023'; END IF;
 payload:=body_text::jsonb; step:=(payload->>'next_step')::integer;
 invocation:=(payload->>'model_invocation_id')::uuid;
 IF payload->>'version' IS DISTINCT FROM 'agent-loop-checkpoint.v1'
  OR payload#>>'{context,run_id}' IS DISTINCT FROM r.id::text
  OR payload#>>'{context,tenant_id}' IS DISTINCT FROM r.tenant_id::text
  OR payload#>>'{context,project_id}' IS DISTINCT FROM r.project_id::text
  OR payload#>>'{context,agent_key}' IS DISTINCT FROM r.agent_key
  OR (step BETWEEN 1 AND 99) IS NOT TRUE
  OR (payload->>'runtime_digest' ~ '^[a-f0-9]{64}$') IS NOT TRUE
  OR NOT EXISTS(SELECT 1 FROM cehub_ai.model_invocations m WHERE m.id=invocation
    AND m.tenant_id=r.tenant_id AND m.run_id=r.id AND m.status='succeeded') THEN
  RAISE EXCEPTION 'AGENT_LOOP_CHECKPOINT_INVALID' USING ERRCODE='22023'; END IF;
 PERFORM cehub_ai.check_run_active_budget(r.tenant_id,r.id);
 PERFORM cehub_ai.verify_agent_manifest_sources();
 IF EXISTS(SELECT 1 FROM (
  SELECT DISTINCT ON(e.session_id) e.state FROM cehub_ai.model_call_events e
   JOIN cehub_ai.model_call_sessions s ON s.id=e.session_id
   WHERE s.tenant_id=r.tenant_id AND s.run_id=r.id ORDER BY e.session_id,e.revision DESC
  ) latest WHERE state IN ('open','unknown')) OR EXISTS(SELECT 1 FROM (
  SELECT DISTINCT ON(j.attempt_id) j.held_tokens FROM cehub_ai.budget_journal j
   WHERE j.tenant_id=r.tenant_id AND j.run_id=r.id ORDER BY j.attempt_id,j.revision DESC
  ) latest WHERE held_tokens>0) OR EXISTS(SELECT 1 FROM cehub_ai.agent_tool_dispatches d
   WHERE d.tenant_id=r.tenant_id AND d.run_id=r.id AND NOT EXISTS(
    SELECT 1 FROM cehub_ai.agent_tool_observations o WHERE o.tenant_id=d.tenant_id
     AND o.run_id=d.run_id AND o.tool_intent_id=d.intent_id)) THEN
  RAISE EXCEPTION 'AGENT_LOOP_CHECKPOINT_RECEIPT_UNKNOWN' USING ERRCODE='22023'; END IF;
 SELECT * INTO old FROM cehub_ai.agent_loop_checkpoints
  WHERE tenant_id=r.tenant_id AND run_id=r.id AND next_step=step;
 IF FOUND THEN
  IF old.body IS DISTINCT FROM payload THEN
   RAISE EXCEPTION 'AGENT_LOOP_CHECKPOINT_CONFLICT' USING ERRCODE='22023'; END IF;
  RETURN old.id;
 END IF;
 IF step<>(SELECT coalesce(max(next_step),0)+1 FROM cehub_ai.agent_loop_checkpoints
   WHERE tenant_id=r.tenant_id AND run_id=r.id) THEN
  RAISE EXCEPTION 'AGENT_LOOP_CHECKPOINT_SEQUENCE' USING ERRCODE='22023'; END IF;
 SELECT array_agg(id ORDER BY id) INTO traces FROM cehub_ai.model_invocations
  WHERE tenant_id=r.tenant_id AND run_id=r.id;
 INSERT INTO cehub_ai.agent_loop_checkpoints VALUES(cid,r.tenant_id,r.id,step,invocation,traces,
  payload,encode(sha256(convert_to(payload::text,'UTF8')),'hex'),clock_timestamp());
 RETURN cid;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.save_agent_loop_checkpoint(text) FROM PUBLIC;
CREATE OR REPLACE FUNCTION cehub_ai.load_agent_loop_checkpoint() RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; cp cehub_ai.agent_loop_checkpoints%ROWTYPE;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent loop checkpoint lease is invalid' USING ERRCODE='42501'; END IF;
 IF r.run_context->>'_resume_loop_checkpoint_id' IS NULL THEN RETURN NULL; END IF;
 PERFORM cehub_ai.check_run_active_budget(r.tenant_id,r.id);
 SELECT * INTO cp FROM cehub_ai.agent_loop_checkpoints WHERE tenant_id=r.tenant_id AND run_id=r.id
  AND id=(r.run_context->>'_resume_loop_checkpoint_id')::uuid;
 IF NOT FOUND OR cp.body_sha256 IS DISTINCT FROM
  encode(sha256(convert_to(cp.body::text,'UTF8')),'hex') OR EXISTS(
   SELECT 1 FROM cehub_ai.model_invocations m WHERE m.tenant_id=r.tenant_id AND m.run_id=r.id
    AND NOT m.id=ANY(cp.trace_ids)) THEN
  RAISE EXCEPTION 'AGENT_LOOP_CHECKPOINT_INCOMPLETE' USING ERRCODE='22023'; END IF;
 RETURN cp.body;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.load_agent_loop_checkpoint() FROM PUBLIC;
"""
RECOVER = (
    PREVIOUS.RECOVER.replace(
        "receipt uuid; result_action text;",
        "step_cp cehub_ai.agent_loop_checkpoints%ROWTYPE; receipt uuid; result_action text;",
    )
    .replace(
        "SELECT f.id INTO receipt FROM cehub_ai.findings f",
        """SELECT * INTO step_cp FROM cehub_ai.agent_loop_checkpoints c
          WHERE c.tenant_id=r.tenant_id AND c.run_id=r.id ORDER BY next_step DESC LIMIT 1;
        SELECT f.id INTO receipt FROM cehub_ai.findings f""",
    )
    .replace(
        "ELSIF checkpoint.id IS NULL THEN",
        """ELSIF checkpoint.id IS NULL AND step_cp.id IS NOT NULL AND EXISTS(
            SELECT 1 FROM cehub_ai.model_invocations m WHERE m.tenant_id=r.tenant_id
             AND m.run_id=r.id AND NOT m.id=ANY(step_cp.trace_ids)) THEN
            stop_reason := 'AGENT_LOOP_CHECKPOINT_INCOMPLETE';
        ELSIF checkpoint.id IS NULL AND step_cp.id IS NULL THEN""",
    )
    .replace(
        "INSERT INTO cehub_ai.agent_run_recoveries VALUES(",
        """INSERT INTO cehub_ai.agent_run_recoveries
        (id,tenant_id,run_id,checkpoint_id,finding_id,action,reason,expired_lease_token,created_at,
         loop_checkpoint_id) VALUES(""",
    )
    .replace(
        "checkpoint.id,receipt,result_action,stop_reason,expired_token,observed_at);",
        "checkpoint.id,receipt,result_action,stop_reason,expired_token,observed_at,step_cp.id);",
    )
    .replace(
        "jsonb_build_object('_resume_checkpoint_id',checkpoint.id)",
        "jsonb_build_object('_resume_checkpoint_id',checkpoint.id,'_resume_loop_checkpoint_id',"
        "CASE WHEN checkpoint.id IS NULL THEN step_cp.id ELSE NULL END)",
    )
)


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute(PORTS)
    op.execute(RECOVER)
    op.execute("""DO $body$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_agent') THEN
      GRANT EXECUTE ON FUNCTION cehub_ai.save_agent_loop_checkpoint(text),
       cehub_ai.load_agent_loop_checkpoint() TO pdos_agent; END IF; END $body$;""")


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.agent_loop_checkpoints) THEN
      RAISE EXCEPTION 'cannot remove persistent loop checkpoints'; END IF; END $body$;""")
    op.execute(PREVIOUS.RECOVER)
    # The runtime-role teardown can already have removed these restricted ports.
    op.execute("""DROP FUNCTION IF EXISTS cehub_ai.load_agent_loop_checkpoint();
      DROP FUNCTION IF EXISTS cehub_ai.save_agent_loop_checkpoint(text);
      ALTER TABLE cehub_ai.agent_run_recoveries DROP COLUMN loop_checkpoint_id;
      DROP TABLE cehub_ai.agent_loop_checkpoints;""")
