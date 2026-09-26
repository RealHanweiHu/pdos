"""Persist application inference together with its known call receipt."""

from collections.abc import Sequence

from alembic import op

revision: str = "0085_application_results"
down_revision: str | Sequence[str] | None = "0084_application_run_leases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = r"""

CREATE TABLE cehub_ai.application_result_checkpoints (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	run_id UUID NOT NULL,
	model_call_id UUID NOT NULL,
	observation_id UUID NOT NULL,
	manifest_id UUID NOT NULL,
	invocation_id UUID NOT NULL,
	owner_lease_id UUID NOT NULL,
	body JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_application_result_checkpoints PRIMARY KEY (id),
	CONSTRAINT uq_application_result_call UNIQUE (tenant_id, run_id, model_call_id),
        CONSTRAINT fk_application_result_checkpoints_tenant_id_application_6a53 FOREIGN
KEY(tenant_id, run_id, observation_id) REFERENCES cehub_ai.application_context_observations
(tenant_id, run_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_application_result_checkpoints_tenant_id_application_15f2 FOREIGN
KEY(tenant_id, run_id, manifest_id) REFERENCES cehub_ai.application_context_manifests
(tenant_id, run_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_application_result_checkpoints_tenant_id_application_4740 FOREIGN
KEY(tenant_id, run_id, owner_lease_id) REFERENCES cehub_ai.application_run_leases (tenant_id,
run_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_application_result_checkpoints_tenant_id_model_invocations FOREIGN
KEY(tenant_id, invocation_id) REFERENCES cehub_ai.model_invocations (tenant_id, id) ON DELETE
RESTRICT,
        CONSTRAINT ck_application_result_checkpoints_result_body CHECK
((body->>'version'='application-result.v1' AND body->>'status'='succeeded' AND
jsonb_typeof(body->'output')='object' AND jsonb_typeof(body->'removed_context_paths')='array'
AND jsonb_typeof(body->'structured_attempts')='number' AND
(body->>'structured_attempts')::integer BETWEEN 1 AND 3) IS TRUE)
)


"""

RECEIPT = r"""
CREATE FUNCTION cehub_ai.application_result_receipt_valid(
 t uuid,r uuid,call_id uuid,obs uuid,manifest uuid,trace_id uuid,lease uuid)
RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
 SELECT EXISTS (
  SELECT 1 FROM cehub_ai.model_invocations i
  JOIN cehub_ai.application_context_observations o ON o.tenant_id=i.tenant_id
   AND o.run_id=i.run_id AND o.model_call_id=i.budget_call_id
  JOIN cehub_ai.application_context_manifests m ON m.tenant_id=o.tenant_id
   AND m.run_id=o.run_id AND m.observation_id=o.id
  JOIN cehub_ai.budget_journal a ON a.id=m.admission_id
  JOIN cehub_ai.model_call_sessions s ON s.tenant_id=i.tenant_id AND s.id=i.model_call_session_id
  WHERE i.tenant_id=t AND i.run_id=r AND i.id=trace_id AND i.budget_call_id=call_id
   AND i.status='succeeded' AND i.usage_status='known' AND i.structured_attempts>0
   AND o.id=obs AND m.id=manifest AND m.owner_lease_id=lease
   AND s.run_id=r AND s.execution_mode='budgeted'
   AND (a.request_binding->>'structured_attempt')::integer=i.structured_attempts
   AND EXISTS(SELECT 1 FROM cehub_ai.model_call_events e
     WHERE e.tenant_id=t AND e.session_id=s.id AND e.state='closed' AND e.invocation_id=i.id
     AND e.revision=(SELECT max(revision) FROM cehub_ai.model_call_events
       WHERE tenant_id=t AND session_id=s.id))
   AND NOT EXISTS(SELECT 1 FROM generate_series(1,i.structured_attempts) n WHERE NOT EXISTS(
     SELECT 1 FROM cehub_ai.budget_journal j WHERE j.tenant_id=t AND j.run_id=r
      AND j.call_kind='model' AND j.request_binding->>'model_call_id'=call_id::text
      AND (j.request_binding->>'structured_attempt')::integer=n
      AND j.reservation_status='settled' AND j.dispatched_at IS NOT NULL
      AND j.revision=(SELECT max(revision) FROM cehub_ai.budget_journal
        WHERE tenant_id=t AND run_id=r AND attempt_id=j.attempt_id)))
   AND NOT EXISTS(SELECT 1 FROM cehub_ai.budget_journal j WHERE j.tenant_id=t AND j.run_id=r
     AND j.reservation_status IN ('reserved','unknown')
     AND j.revision=(SELECT max(revision) FROM cehub_ai.budget_journal
       WHERE tenant_id=t AND run_id=r AND attempt_id=j.attempt_id))
   AND NOT EXISTS(SELECT 1 FROM cehub_ai.model_call_sessions s2
     JOIN cehub_ai.model_call_events e ON e.tenant_id=s2.tenant_id AND e.session_id=s2.id
     WHERE s2.tenant_id=t AND s2.run_id=r AND e.state<>'closed'
      AND e.revision=(SELECT max(revision) FROM cehub_ai.model_call_events
        WHERE tenant_id=t AND session_id=s2.id))
 );
$body$;
REVOKE ALL ON FUNCTION cehub_ai.application_result_receipt_valid(uuid,uuid,uuid,uuid,uuid,uuid,uuid)
 FROM PUBLIC;
"""

GUARD = r"""
CREATE FUNCTION cehub_ai.require_application_result_receipt() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
BEGIN
 PERFORM 1 FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id FOR UPDATE;
 IF NOT cehub_ai.application_lease_is_current(NEW.run_id,NEW.owner_lease_id)
  OR NEW.owner_lease_id IS DISTINCT FROM
nullif(current_setting('pdos.application_lease_id',true),'')::uuid THEN
  RAISE EXCEPTION 'APPLICATION_RUN_LEASE_LOST' USING ERRCODE='22023';
 END IF;
 PERFORM cehub_ai.check_run_active_budget(NEW.tenant_id,NEW.run_id);
 IF NOT cehub_ai.application_result_receipt_valid(NEW.tenant_id,NEW.run_id,NEW.model_call_id,
   NEW.observation_id,NEW.manifest_id,NEW.invocation_id,NEW.owner_lease_id)
  OR (NEW.body->>'structured_attempts')::integer IS DISTINCT FROM
    (SELECT structured_attempts FROM cehub_ai.model_invocations WHERE id=NEW.invocation_id) THEN
  RAISE EXCEPTION 'APPLICATION_RESULT_RECEIPT_INVALID' USING ERRCODE='22023';
 END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.require_application_result_receipt() FROM PUBLIC;
CREATE TRIGGER require_application_result_receipt BEFORE INSERT
 ON cehub_ai.application_result_checkpoints FOR EACH ROW
 EXECUTE FUNCTION cehub_ai.require_application_result_receipt();
CREATE TRIGGER protect_application_result BEFORE UPDATE OR DELETE
 ON cehub_ai.application_result_checkpoints FOR EACH ROW
 EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_ai.application_result_checkpoints FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute(RECEIPT)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN
     IF EXISTS(SELECT 1 FROM cehub_ai.application_result_checkpoints) THEN
      RAISE EXCEPTION 'cannot remove persistent application result history';
     END IF;
    END $body$;""")
    op.execute("DROP TABLE cehub_ai.application_result_checkpoints")
    op.execute("DROP FUNCTION cehub_ai.require_application_result_receipt()")
    op.execute(
        "DROP FUNCTION cehub_ai.application_result_receipt_valid"
        "(uuid,uuid,uuid,uuid,uuid,uuid,uuid)"
    )
