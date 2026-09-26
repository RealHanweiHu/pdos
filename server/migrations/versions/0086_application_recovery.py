"""New application holders resume known results under original authority and budget."""

from collections.abc import Sequence

from alembic import op

revision: str = "0086_application_recovery"
down_revision: str | Sequence[str] | None = "0085_application_results"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_SYNC = r"""

CREATE OR REPLACE FUNCTION cehub_ai.sync_run_activity(wanted_tenant uuid, wanted_run uuid)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; lid uuid; token uuid; expiry timestamptz;
    observed_at timestamptz := clock_timestamp(); prior cehub_ai.budget_activity_spans%ROWTYPE;
BEGIN
    -- Called only by triggers while the source run is transactionally owned.
    SELECT * INTO r FROM cehub_ai.agent_runs
      WHERE tenant_id=wanted_tenant AND id=wanted_run FOR UPDATE;
    SELECT l.lineage_id INTO lid FROM cehub_ai.budget_run_links l
      JOIN cehub_ai.budget_activity_coverage c USING(tenant_id,lineage_id)
      WHERE l.tenant_id=wanted_tenant AND l.run_id=wanted_run;
    IF lid IS NULL THEN RETURN; END IF;
    token := nullif(r.run_context->>'_lease_token','')::uuid;
    expiry := nullif(r.run_context->>'_lease_expires_at','')::timestamptz;
    IF EXISTS(SELECT 1 FROM cehub_ai.application_run_leases WHERE run_id=wanted_run) THEN
        SELECT id,expires_at INTO token,expiry FROM cehub_ai.application_run_leases
          WHERE run_id=wanted_run;
    END IF;
    SELECT * INTO prior FROM cehub_ai.budget_activity_spans
      WHERE tenant_id=wanted_tenant AND run_id=wanted_run AND stopped_at IS NULL;
    IF FOUND THEN
        IF prior.lease_token IS NULL AND token IS NOT NULL AND r.status='running'
         AND EXISTS(SELECT 1 FROM cehub_ai.application_run_leases
          WHERE run_id=wanted_run AND id=token AND issued_at>=prior.started_at) THEN
            UPDATE cehub_ai.budget_activity_spans SET lease_token=token,lease_expires_at=expiry
              WHERE id=prior.id;
            RETURN;
        END IF;
        IF r.status <> 'running' OR token IS DISTINCT FROM prior.lease_token THEN
            UPDATE cehub_ai.budget_activity_spans SET stopped_at=greatest(started_at,
                least(observed_at,lease_expires_at)) WHERE id=prior.id;
        ELSE
            UPDATE cehub_ai.budget_activity_spans SET lease_expires_at=expiry WHERE id=prior.id;
            RETURN;
        END IF;
    END IF;
    IF r.status='running' THEN
        INSERT INTO cehub_ai.budget_activity_spans
          (id,tenant_id,lineage_id,run_id,lease_token,started_at,lease_expires_at)
          VALUES(gen_random_uuid(),wanted_tenant,lid,wanted_run,token,observed_at,expiry);
    END IF;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.sync_run_activity(uuid,uuid) FROM PUBLIC;
"""

NEW_SYNC = r"""

CREATE OR REPLACE FUNCTION cehub_ai.sync_run_activity(wanted_tenant uuid, wanted_run uuid)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; lid uuid; token uuid; expiry timestamptz;
    observed_at timestamptz := clock_timestamp(); prior cehub_ai.budget_activity_spans%ROWTYPE;
BEGIN
    -- Called only by triggers while the source run is transactionally owned.
    SELECT * INTO r FROM cehub_ai.agent_runs
      WHERE tenant_id=wanted_tenant AND id=wanted_run FOR UPDATE;
    SELECT l.lineage_id INTO lid FROM cehub_ai.budget_run_links l
      JOIN cehub_ai.budget_activity_coverage c USING(tenant_id,lineage_id)
      WHERE l.tenant_id=wanted_tenant AND l.run_id=wanted_run;
    IF lid IS NULL THEN RETURN; END IF;
    token := nullif(r.run_context->>'_lease_token','')::uuid;
    expiry := nullif(r.run_context->>'_lease_expires_at','')::timestamptz;
    IF EXISTS(SELECT 1 FROM cehub_ai.application_run_leases WHERE run_id=wanted_run) THEN
        SELECT id,expires_at INTO token,expiry FROM cehub_ai.application_run_leases
          WHERE run_id=wanted_run AND ended_at IS NULL;
    END IF;
    SELECT * INTO prior FROM cehub_ai.budget_activity_spans
      WHERE tenant_id=wanted_tenant AND run_id=wanted_run AND stopped_at IS NULL;
    IF FOUND THEN
        IF prior.lease_token IS NULL AND token IS NOT NULL AND r.status='running'
         AND EXISTS(SELECT 1 FROM cehub_ai.application_run_leases
          WHERE run_id=wanted_run AND id=token AND issued_at>=prior.started_at) THEN
            UPDATE cehub_ai.budget_activity_spans SET lease_token=token,lease_expires_at=expiry
              WHERE id=prior.id;
            RETURN;
        END IF;
        IF r.status <> 'running' OR token IS DISTINCT FROM prior.lease_token THEN
            UPDATE cehub_ai.budget_activity_spans SET stopped_at=greatest(started_at,
                least(observed_at,lease_expires_at)) WHERE id=prior.id;
        ELSE
            UPDATE cehub_ai.budget_activity_spans SET lease_expires_at=expiry WHERE id=prior.id;
            RETURN;
        END IF;
    END IF;
    IF r.status='running' THEN
        INSERT INTO cehub_ai.budget_activity_spans
          (id,tenant_id,lineage_id,run_id,lease_token,started_at,lease_expires_at)
          VALUES(gen_random_uuid(),wanted_tenant,lid,wanted_run,token,observed_at,expiry);
    END IF;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.sync_run_activity(uuid,uuid) FROM PUBLIC;
"""

OLD_PROTECT = r"""
CREATE OR REPLACE FUNCTION cehub_ai.protect_application_lease() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $body$
BEGIN
 IF TG_OP='DELETE' OR (TG_OP='UPDATE' AND (
  (NEW.id,NEW.tenant_id,NEW.run_id,NEW.authorization_id,NEW.owner_id,NEW.issued_at)
   IS DISTINCT FROM
  (OLD.id,OLD.tenant_id,OLD.run_id,OLD.authorization_id,OLD.owner_id,OLD.issued_at)
  OR OLD.ended_at IS NOT NULL OR NEW.renewed_at<OLD.renewed_at)) THEN
  RAISE EXCEPTION 'application lease identity and ended history are immutable';
 END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.protect_application_lease() FROM PUBLIC;

"""

NEW_PROTECT = r"""
CREATE OR REPLACE FUNCTION cehub_ai.protect_application_lease() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $body$
BEGIN
 IF TG_OP='DELETE' OR (TG_OP='UPDATE' AND (
  (NEW.id,NEW.tenant_id,NEW.run_id,NEW.authorization_id,NEW.owner_id,NEW.issued_at,
   NEW.generation,NEW.previous_lease_id,NEW.recovery_checkpoint_id)
   IS DISTINCT FROM
  (OLD.id,OLD.tenant_id,OLD.run_id,OLD.authorization_id,OLD.owner_id,OLD.issued_at,
   OLD.generation,OLD.previous_lease_id,OLD.recovery_checkpoint_id)
  OR OLD.ended_at IS NOT NULL OR NEW.renewed_at<OLD.renewed_at)) THEN
  RAISE EXCEPTION 'application lease identity and ended history are immutable';
 END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.protect_application_lease() FROM PUBLIC;

"""

SCHEMA = r"""
ALTER TABLE cehub_ai.application_result_checkpoints
 ADD CONSTRAINT uq_application_result_scope UNIQUE(tenant_id,run_id,id);
ALTER TABLE cehub_ai.application_run_leases
 DROP CONSTRAINT uq_application_lease_run,
 ADD COLUMN generation integer NOT NULL DEFAULT 1,
 ADD COLUMN previous_lease_id uuid,
 ADD COLUMN recovery_checkpoint_id uuid,
 ADD CONSTRAINT uq_application_lease_generation UNIQUE(tenant_id,run_id,generation),
 ADD CONSTRAINT fk_application_lease_previous FOREIGN KEY(tenant_id,run_id,previous_lease_id)
  REFERENCES cehub_ai.application_run_leases(tenant_id,run_id,id) ON DELETE RESTRICT,
 ADD CONSTRAINT fk_application_lease_checkpoint FOREIGN KEY(tenant_id,run_id,recovery_checkpoint_id)
  REFERENCES cehub_ai.application_result_checkpoints(tenant_id,run_id,id) ON DELETE RESTRICT,
 ADD CONSTRAINT ck_application_run_leases_generation CHECK(generation>0 AND
  ((generation=1 AND previous_lease_id IS NULL AND recovery_checkpoint_id IS NULL)
   OR (generation>1 AND previous_lease_id IS NOT NULL AND recovery_checkpoint_id IS NOT NULL)));
CREATE UNIQUE INDEX uq_application_lease_active ON cehub_ai.application_run_leases(tenant_id,run_id)
 WHERE ended_at IS NULL;
"""
CLAIM = r"""
CREATE FUNCTION cehub_ai.claim_application_result_run(t uuid,rid uuid,actor uuid,
 session_version integer,owner uuid,result_id uuid,policy text,profile jsonb)
RETURNS uuid LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; l cehub_ai.application_run_leases%ROWTYPE;
 a cehub_ai.application_authorizations%ROWTYPE; cp cehub_ai.application_result_checkpoints%ROWTYPE;
 token uuid; stamp timestamptz;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('pdos-budget:'||t::text,0));
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=t AND id=rid FOR UPDATE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'APPLICATION_RECOVERY_SCOPE_INVALID' USING ERRCODE='22023'; END IF;
 IF r.status<>'running' AND NOT(r.status='degraded'
   AND r.error_code='APPLICATION_RUN_LEASE_EXPIRED') THEN RETURN NULL; END IF;
 SELECT * INTO l FROM cehub_ai.application_run_leases WHERE tenant_id=t AND run_id=rid
  ORDER BY generation DESC LIMIT 1 FOR UPDATE;
 IF NOT FOUND OR (l.ended_at IS NULL AND l.expires_at>clock_timestamp()) THEN RETURN NULL; END IF;
 IF l.generation>=3 THEN
  RAISE EXCEPTION 'APPLICATION_RECOVERY_LIMIT_REACHED' USING ERRCODE='22023'; END IF;
 SELECT * INTO a FROM cehub_ai.application_authorizations WHERE tenant_id=t AND run_id=rid;
 IF a.principal_id IS DISTINCT FROM actor OR (a.pins->>'auth_version')::integer
  IS DISTINCT FROM session_version OR a.body->>'policy_version' IS DISTINCT FROM policy
  OR NOT EXISTS(SELECT 1 FROM cehub_ai.budget_lineages WHERE tenant_id=t
    AND id=a.lineage_id AND budget_lineages.profile=claim_application_result_run.profile) THEN
  RAISE EXCEPTION 'APPLICATION_RECOVERY_AUTHORIZATION_CHANGED' USING ERRCODE='22023'; END IF;
 SELECT * INTO cp FROM cehub_ai.application_result_checkpoints
  WHERE tenant_id=t AND run_id=rid AND id=result_id;
 IF NOT FOUND OR NOT cehub_ai.application_result_receipt_valid(t,rid,cp.model_call_id,
  cp.observation_id,cp.manifest_id,cp.invocation_id,cp.owner_lease_id) THEN
  RAISE EXCEPTION 'APPLICATION_RECOVERY_RECEIPT_INVALID' USING ERRCODE='22023'; END IF;
 -- Close the former generation before opening a new one. Both operations and
 -- the run transition commit together; original authority and budget are never reissued.
 IF l.ended_at IS NULL THEN
  UPDATE cehub_ai.application_run_leases SET ended_at=clock_timestamp(),
   stop_reason='APPLICATION_RUN_LEASE_EXPIRED' WHERE id=l.id;
 END IF;
 UPDATE cehub_ai.agent_runs SET status='running',error_code=NULL,completed_at=NULL,
  updated_at=clock_timestamp() WHERE tenant_id=t AND id=rid;
 IF NOT cehub_ai.application_authorization_is_current(rid) THEN
  RAISE EXCEPTION 'APPLICATION_RECOVERY_AUTHORIZATION_CHANGED' USING ERRCODE='22023'; END IF;
 PERFORM cehub_ai.check_run_active_budget(t,rid);
 token:=gen_random_uuid(); stamp:=clock_timestamp();
 INSERT INTO cehub_ai.application_run_leases
  (id,tenant_id,run_id,authorization_id,owner_id,generation,previous_lease_id,
   recovery_checkpoint_id,issued_at,renewed_at,expires_at)
 VALUES(token,t,rid,a.id,owner,l.generation+1,l.id,cp.id,stamp,stamp,
  least(stamp+interval '60 seconds',a.expires_at));
 RETURN token;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.claim_application_result_run
 (uuid,uuid,uuid,integer,uuid,uuid,text,jsonb) FROM PUBLIC;
"""
GUARDS = r"""
CREATE FUNCTION cehub_ai.require_application_lease_chain() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $body$
BEGIN
 IF NEW.generation>1 AND NOT EXISTS(SELECT 1 FROM cehub_ai.application_run_leases l
  JOIN cehub_ai.application_result_checkpoints cp ON cp.tenant_id=l.tenant_id AND cp.run_id=l.run_id
  WHERE l.tenant_id=NEW.tenant_id AND l.run_id=NEW.run_id AND l.id=NEW.previous_lease_id
   AND l.generation+1=NEW.generation AND l.ended_at IS NOT NULL
   AND l.ended_at<=NEW.issued_at AND cp.id=NEW.recovery_checkpoint_id
   AND l.authorization_id=NEW.authorization_id) THEN
  RAISE EXCEPTION 'APPLICATION_RECOVERY_CHAIN_INVALID' USING ERRCODE='22023'; END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.require_application_lease_chain() FROM PUBLIC;
CREATE TRIGGER require_application_lease_chain BEFORE INSERT ON cehub_ai.application_run_leases
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.require_application_lease_chain();
CREATE FUNCTION cehub_ai.forbid_application_recovery_dispatch() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
BEGIN
 IF NEW.call_kind='model' AND NEW.dispatched_at IS NOT NULL
  AND NEW.reservation_status='reserved' AND EXISTS(
   SELECT 1 FROM cehub_ai.application_run_leases WHERE tenant_id=NEW.tenant_id AND run_id=NEW.run_id
    AND generation>1 AND ended_at IS NULL) THEN
  RAISE EXCEPTION 'BUDGET_APPLICATION_RECOVERY_MODEL_FORBIDDEN' USING ERRCODE='22023'; END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.forbid_application_recovery_dispatch() FROM PUBLIC;
CREATE TRIGGER forbid_application_recovery_dispatch BEFORE INSERT ON cehub_ai.budget_journal
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.forbid_application_recovery_dispatch();
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute(NEW_SYNC)
    op.execute(NEW_PROTECT)
    op.execute(CLAIM)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute("""DO $b$ BEGIN
     IF EXISTS(SELECT 1 FROM cehub_ai.application_run_leases WHERE generation>1) THEN
      RAISE EXCEPTION 'cannot remove persistent application recovery history'; END IF;
    END $b$;""")
    op.execute("DROP TRIGGER forbid_application_recovery_dispatch ON cehub_ai.budget_journal")
    op.execute("DROP FUNCTION cehub_ai.forbid_application_recovery_dispatch()")
    op.execute("DROP TRIGGER require_application_lease_chain ON cehub_ai.application_run_leases")
    op.execute("DROP FUNCTION cehub_ai.require_application_lease_chain()")
    op.execute(
        "DROP FUNCTION cehub_ai.claim_application_result_run"
        "(uuid,uuid,uuid,integer,uuid,uuid,text,jsonb)"
    )
    op.execute(OLD_PROTECT)
    op.execute(OLD_SYNC)
    op.execute("""ALTER TABLE cehub_ai.application_run_leases
     DROP CONSTRAINT fk_application_lease_checkpoint,
     DROP CONSTRAINT fk_application_lease_previous,
     DROP CONSTRAINT ck_application_run_leases_generation,
     DROP CONSTRAINT uq_application_lease_generation;
     DROP INDEX cehub_ai.uq_application_lease_active;
     ALTER TABLE cehub_ai.application_run_leases DROP COLUMN generation,
      DROP COLUMN previous_lease_id,DROP COLUMN recovery_checkpoint_id,
      ADD CONSTRAINT uq_application_lease_run UNIQUE(tenant_id,run_id);
     ALTER TABLE cehub_ai.application_result_checkpoints
      DROP CONSTRAINT uq_application_result_scope;
    """)
