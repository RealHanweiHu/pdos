"""Lease-bound model result checkpoints and deterministic expired-run supervision."""

from collections.abc import Sequence

from alembic import op

revision: str = "0073_agent_result_checkpoints"
down_revision: str | Sequence[str] | None = "0072_active_execution_budget"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = r"""
CREATE TABLE cehub_ai.agent_result_checkpoints (
    id uuid PRIMARY KEY, tenant_id uuid NOT NULL, run_id uuid NOT NULL,
    model_invocation_id uuid NOT NULL, body jsonb NOT NULL, body_sha256 varchar(64) NOT NULL,
    created_at timestamptz NOT NULL,
    CONSTRAINT uq_agent_checkpoint_run UNIQUE(tenant_id,run_id),
    FOREIGN KEY(tenant_id,run_id) REFERENCES cehub_ai.agent_runs(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY(model_invocation_id) REFERENCES cehub_ai.model_invocations(id) ON DELETE RESTRICT,
    CONSTRAINT ck_agent_result_checkpoints_body_shape CHECK
      (jsonb_typeof(body)='object' AND length(body_sha256)=64)
);
CREATE TABLE cehub_ai.agent_run_recoveries (
    id uuid PRIMARY KEY, tenant_id uuid NOT NULL, run_id uuid NOT NULL,
    checkpoint_id uuid REFERENCES cehub_ai.agent_result_checkpoints(id) ON DELETE RESTRICT,
    finding_id uuid REFERENCES cehub_ai.findings(id) ON DELETE RESTRICT,
    action varchar(32) NOT NULL, reason varchar(64), expired_lease_token uuid NOT NULL,
    created_at timestamptz NOT NULL,
    FOREIGN KEY(tenant_id,run_id) REFERENCES cehub_ai.agent_runs(tenant_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_agent_recovery_lease UNIQUE(tenant_id,run_id,expired_lease_token),
    CONSTRAINT ck_agent_run_recoveries_action_allowed CHECK
      (action IN ('resume_queued','receipt_completed','stopped'))
);
REVOKE ALL ON cehub_ai.agent_result_checkpoints,cehub_ai.agent_run_recoveries FROM PUBLIC;
CREATE FUNCTION cehub_ai.protect_checkpoint_history() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $body$
BEGIN
    RAISE EXCEPTION 'checkpoint and recovery history is append-only' USING ERRCODE='42501';
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.protect_checkpoint_history() FROM PUBLIC;
CREATE TRIGGER protect_checkpoint_history BEFORE UPDATE OR DELETE
  ON cehub_ai.agent_result_checkpoints
  FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
CREATE TRIGGER protect_recovery_history BEFORE UPDATE OR DELETE ON cehub_ai.agent_run_recoveries
  FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
"""

PORTS = r"""CREATE OR REPLACE FUNCTION cehub_ai.save_agent_result_checkpoint(
    wanted_run uuid,wanted_token uuid,body_text text
) RETURNS uuid LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; payload jsonb; invocation uuid;
    previous cehub_ai.agent_result_checkpoints%ROWTYPE; new_id uuid := gen_random_uuid();
BEGIN
    SELECT * INTO r FROM cehub_ai.agent_runs WHERE id=wanted_run FOR UPDATE;
    IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(wanted_run,wanted_token) THEN
        RAISE EXCEPTION 'Agent run lease is invalid' USING ERRCODE='42501';
    END IF;
    IF body_text IS NULL OR octet_length(body_text)>262144 THEN
        RAISE EXCEPTION 'AGENT_CHECKPOINT_INVALID' USING ERRCODE='22023';
    END IF;
    payload := body_text::jsonb;
    IF jsonb_typeof(payload) IS DISTINCT FROM 'object'
       OR payload->>'version' IS DISTINCT FROM 'agent-result.v1'
       OR payload#>>'{context,run_id}' IS DISTINCT FROM r.id::text
       OR payload#>>'{context,tenant_id}' IS DISTINCT FROM r.tenant_id::text
       OR payload#>>'{context,project_id}' IS DISTINCT FROM r.project_id::text
       OR payload#>>'{context,agent_key}' IS DISTINCT FROM r.agent_key
       OR payload->>'runtime_digest' IS NULL
       OR payload->>'runtime_digest' !~ '^[a-f0-9]{64}$'
       OR (payload#>>'{result,status}' IN ('succeeded','degraded')) IS NOT TRUE THEN
        RAISE EXCEPTION 'AGENT_CHECKPOINT_INVALID' USING ERRCODE='22023';
    END IF;
    invocation := (payload#>>'{result,invocation_id}')::uuid;
    IF invocation IS NULL OR NOT EXISTS(SELECT 1 FROM cehub_ai.model_invocations
       WHERE id=invocation AND tenant_id=r.tenant_id AND run_id=r.id
         AND project_id=r.project_id AND agent_key=r.agent_key
         AND (payload#>>'{result,status}' <> 'succeeded' OR status='succeeded')) THEN
        RAISE EXCEPTION 'AGENT_CHECKPOINT_TRACE_INVALID' USING ERRCODE='22023';
    END IF;
    SELECT * INTO previous FROM cehub_ai.agent_result_checkpoints
      WHERE tenant_id=r.tenant_id AND run_id=r.id;
    IF FOUND THEN
        IF previous.body IS DISTINCT FROM payload THEN
            RAISE EXCEPTION 'AGENT_CHECKPOINT_CONFLICT' USING ERRCODE='22023';
        END IF;
        RETURN previous.id;
    END IF;
    IF NOT cehub_ai.agent_lease_is_current(wanted_run,wanted_token) THEN
        RAISE EXCEPTION 'Agent run lease expired before checkpoint' USING ERRCODE='42501';
    END IF;
    INSERT INTO cehub_ai.agent_result_checkpoints VALUES(new_id,r.tenant_id,r.id,invocation,payload,
        encode(sha256(convert_to(payload::text,'UTF8')),'hex'),clock_timestamp());
    RETURN new_id;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.save_agent_result_checkpoint(uuid,uuid,text) FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.load_agent_result_checkpoint(
    wanted_run uuid,wanted_token uuid
) RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; checkpoint cehub_ai.agent_result_checkpoints%ROWTYPE;
BEGIN
    SELECT * INTO r FROM cehub_ai.agent_runs WHERE id=wanted_run;
    IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(wanted_run,wanted_token) THEN
        RAISE EXCEPTION 'Agent run lease is invalid' USING ERRCODE='42501';
    END IF;
    IF r.run_context->>'_resume_checkpoint_id' IS NULL THEN RETURN NULL; END IF;
    IF NOT EXISTS(SELECT 1 FROM cehub_ai.agent_subscriptions
        WHERE id=r.subscription_id AND tenant_id=r.tenant_id AND status='active') THEN
        RAISE EXCEPTION 'AGENT_RECOVERY_SUBSCRIPTION_PAUSED' USING ERRCODE='22023';
    END IF;
    IF EXISTS(SELECT 1 FROM cehub_ai.budget_run_links
              WHERE tenant_id=r.tenant_id AND run_id=r.id) THEN
        PERFORM cehub_ai.check_run_active_budget(r.tenant_id,r.id);
    END IF;
    SELECT * INTO checkpoint FROM cehub_ai.agent_result_checkpoints
      WHERE tenant_id=r.tenant_id AND run_id=r.id
        AND id=(r.run_context->>'_resume_checkpoint_id')::uuid;
    IF NOT FOUND OR checkpoint.body_sha256 IS DISTINCT FROM
        encode(sha256(convert_to(checkpoint.body::text,'UTF8')),'hex') THEN
        RAISE EXCEPTION 'AGENT_CHECKPOINT_MISSING_OR_CORRUPT' USING ERRCODE='22023';
    END IF;
    RETURN checkpoint.body;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.load_agent_result_checkpoint(uuid,uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.recover_expired_agent_runs(batch_limit integer)
RETURNS TABLE(run_id uuid,action text,reason text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; checkpoint cehub_ai.agent_result_checkpoints%ROWTYPE;
    receipt uuid; result_action text; stop_reason text; attempts bigint; attempt_limit integer;
    expired_token uuid; observed_at timestamptz;
BEGIN
    IF batch_limit IS NULL OR batch_limit<1 OR batch_limit>1000 THEN
        RAISE EXCEPTION 'invalid recovery batch size' USING ERRCODE='22023';
    END IF;
    FOR r IN SELECT * FROM cehub_ai.agent_runs
      WHERE status='running' AND subscription_id IS NOT NULL AND request_id IS NULL
        AND nullif(run_context->>'_lease_expires_at','')::timestamptz <= clock_timestamp()
        AND nullif(run_context->>'_lease_token','') IS NOT NULL
      ORDER BY updated_at,id LIMIT batch_limit FOR UPDATE SKIP LOCKED LOOP
        observed_at := clock_timestamp();
        expired_token := (r.run_context->>'_lease_token')::uuid;
        IF cehub_ai.agent_lease_is_current(r.id,expired_token) THEN CONTINUE; END IF;
        SELECT * INTO checkpoint FROM cehub_ai.agent_result_checkpoints c
          WHERE c.tenant_id=r.tenant_id AND c.run_id=r.id;
        SELECT f.id INTO receipt FROM cehub_ai.findings f
          WHERE f.tenant_id=r.tenant_id AND f.run_id=r.id ORDER BY f.created_at,f.id LIMIT 1;
        result_action := 'stopped'; stop_reason := NULL;
        IF receipt IS NOT NULL THEN
            result_action := 'receipt_completed';
        ELSIF EXISTS(SELECT 1 FROM (
            SELECT DISTINCT ON(e.session_id) e.state FROM cehub_ai.model_call_events e
            JOIN cehub_ai.model_call_sessions s ON s.id=e.session_id
            WHERE s.tenant_id=r.tenant_id AND s.run_id=r.id
            ORDER BY e.session_id,e.revision DESC) latest WHERE state IN ('open','unknown'))
          OR EXISTS(SELECT 1 FROM (
            SELECT DISTINCT ON(j.attempt_id) j.held_tokens FROM cehub_ai.budget_journal j
            WHERE j.tenant_id=r.tenant_id AND j.run_id=r.id
            ORDER BY j.attempt_id,j.revision DESC) latest WHERE held_tokens>0) THEN
            stop_reason := 'AGENT_RECOVERY_RECEIPT_UNKNOWN';
        ELSIF checkpoint.id IS NULL THEN
            stop_reason := 'AGENT_CHECKPOINT_MISSING';
        ELSIF NOT EXISTS(SELECT 1 FROM cehub_ai.agent_subscriptions
            WHERE id=r.subscription_id AND tenant_id=r.tenant_id AND status='active') THEN
            stop_reason := 'AGENT_RECOVERY_SUBSCRIPTION_PAUSED';
        ELSE
            SELECT count(*) INTO attempts FROM cehub_ai.agent_run_recoveries h
              WHERE h.tenant_id=r.tenant_id AND h.run_id=r.id AND h.action='resume_queued';
            SELECT (l.profile->>'transient_attempt_limit')::integer INTO attempt_limit
              FROM cehub_ai.budget_lineages l JOIN cehub_ai.budget_run_links b
                ON b.tenant_id=l.tenant_id AND b.lineage_id=l.id
              WHERE b.tenant_id=r.tenant_id AND b.run_id=r.id;
            IF attempts >= coalesce(attempt_limit,2)-1 THEN
                stop_reason := 'AGENT_RECOVERY_ATTEMPT_LIMIT';
            ELSE
                IF attempt_limit IS NOT NULL THEN
                    BEGIN
                        PERFORM cehub_ai.check_run_active_budget(r.tenant_id,r.id);
                    EXCEPTION WHEN invalid_parameter_value THEN
                        GET STACKED DIAGNOSTICS stop_reason = MESSAGE_TEXT;
                    END;
                END IF;
                IF stop_reason IS NULL THEN result_action := 'resume_queued'; END IF;
            END IF;
        END IF;
        INSERT INTO cehub_ai.agent_run_recoveries VALUES(gen_random_uuid(),r.tenant_id,r.id,
            checkpoint.id,receipt,result_action,stop_reason,expired_token,observed_at);
        IF result_action='resume_queued' THEN
            UPDATE cehub_ai.agent_runs SET status='queued',started_at=NULL,completed_at=NULL,
              error_code=NULL,updated_at=observed_at,
              run_context=(run_context - '_lease_token' - '_lease_expires_at' - '_lease_renewed_at')
                || jsonb_build_object('_resume_checkpoint_id',checkpoint.id)
              WHERE id=r.id;
        ELSE
            UPDATE cehub_ai.agent_runs SET
              status=CASE WHEN result_action='receipt_completed' THEN 'succeeded' ELSE 'failed' END,
              error_code=stop_reason,completed_at=observed_at,updated_at=observed_at WHERE id=r.id;
        END IF;
        RETURN QUERY SELECT r.id,result_action,stop_reason;
    END LOOP;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.recover_expired_agent_runs(integer) FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute(PORTS)
    op.execute("""DO $body$ BEGIN
      IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_agent') THEN
        GRANT EXECUTE ON FUNCTION cehub_ai.save_agent_result_checkpoint(uuid,uuid,text),
            cehub_ai.load_agent_result_checkpoint(uuid,uuid) TO pdos_agent;
      END IF;
      IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_worker') THEN
        GRANT EXECUTE ON FUNCTION cehub_ai.recover_expired_agent_runs(integer) TO pdos_worker;
      END IF;
    END $body$;""")


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN
      IF EXISTS(SELECT 1 FROM cehub_ai.agent_result_checkpoints)
         OR EXISTS(SELECT 1 FROM cehub_ai.agent_run_recoveries) THEN
        RAISE EXCEPTION 'cannot remove persistent checkpoint recovery history';
      END IF;
    END $body$;""")
    op.execute("DROP FUNCTION IF EXISTS cehub_ai.recover_expired_agent_runs(integer)")
    op.execute("DROP FUNCTION IF EXISTS cehub_ai.load_agent_result_checkpoint(uuid,uuid)")
    op.execute("DROP FUNCTION IF EXISTS cehub_ai.save_agent_result_checkpoint(uuid,uuid,text)")
    op.execute("DROP TABLE cehub_ai.agent_run_recoveries")
    op.execute("DROP TABLE cehub_ai.agent_result_checkpoints")
    op.execute("DROP FUNCTION cehub_ai.protect_checkpoint_history()")
