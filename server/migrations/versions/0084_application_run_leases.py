"""Application Owner leases, dispatch/publication fences and deterministic expiry."""

from collections.abc import Sequence

from alembic import op

revision: str = "0084_application_run_leases"
down_revision: str | Sequence[str] | None = "0083_domain_context_adapters"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = r"""
CREATE TABLE cehub_ai.application_run_leases (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	run_id UUID NOT NULL, 
	authorization_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	issued_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	renewed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	ended_at TIMESTAMP WITH TIME ZONE, 
	stop_reason VARCHAR(64), 
	CONSTRAINT pk_application_run_leases PRIMARY KEY (id), 
	CONSTRAINT uq_application_lease_scope UNIQUE (tenant_id, run_id, id), 
	CONSTRAINT uq_application_lease_run UNIQUE (tenant_id, run_id), 
	CONSTRAINT fk_application_run_leases_tenant_id_application_authorizations
        FOREIGN KEY(tenant_id, run_id, authorization_id)
        REFERENCES cehub_ai.application_authorizations (tenant_id, run_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_application_run_leases_lifecycle
        CHECK (renewed_at>=issued_at AND expires_at>renewed_at
        AND ((ended_at IS NULL AND stop_reason IS NULL) OR
        (ended_at IS NOT NULL AND ended_at>=issued_at AND stop_reason IS NOT NULL
        AND btrim(stop_reason)<>'')))
)

"""

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
    SELECT * INTO prior FROM cehub_ai.budget_activity_spans
      WHERE tenant_id=wanted_tenant AND run_id=wanted_run AND stopped_at IS NULL;
    IF FOUND THEN
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
REVOKE ALL ON FUNCTION cehub_ai.sync_run_activity(uuid,uuid) FROM PUBLIC;"""

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
REVOKE ALL ON FUNCTION cehub_ai.sync_run_activity(uuid,uuid) FROM PUBLIC;"""

FUNCTIONS = r"""
CREATE FUNCTION cehub_ai.application_lease_is_current(wanted_run uuid,wanted_token uuid)
RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
 SELECT EXISTS(SELECT 1 FROM cehub_ai.application_run_leases l
  JOIN cehub_ai.agent_runs r ON r.tenant_id=l.tenant_id AND r.id=l.run_id
  WHERE l.run_id=wanted_run AND l.id=wanted_token AND l.ended_at IS NULL
   AND l.expires_at>clock_timestamp() AND r.status='running'
   AND cehub_ai.application_authorization_is_current(wanted_run));
$body$;
REVOKE ALL ON FUNCTION cehub_ai.application_lease_is_current(uuid,uuid) FROM PUBLIC;

CREATE FUNCTION cehub_ai.protect_application_lease() RETURNS trigger
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
CREATE TRIGGER protect_application_lease BEFORE UPDATE OR DELETE ON cehub_ai.application_run_leases
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_application_lease();

CREATE FUNCTION cehub_ai.track_application_lease() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
BEGIN
 PERFORM cehub_ai.sync_run_activity(NEW.tenant_id,NEW.run_id);
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.track_application_lease() FROM PUBLIC;
CREATE TRIGGER track_application_lease AFTER INSERT OR UPDATE OF expires_at
 ON cehub_ai.application_run_leases FOR EACH ROW
 EXECUTE FUNCTION cehub_ai.track_application_lease();

CREATE FUNCTION cehub_ai.require_application_lease_dispatch() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE lease_id uuid;
BEGIN
 IF NEW.call_kind='model' AND NEW.reservation_status='reserved' AND NEW.dispatched_at IS NOT NULL
  AND EXISTS(SELECT 1 FROM cehub_ai.application_authorizations WHERE run_id=NEW.run_id) THEN
  SELECT owner_lease_id INTO lease_id FROM cehub_ai.application_context_manifests
   WHERE tenant_id=NEW.tenant_id AND run_id=NEW.run_id AND attempt_id=NEW.attempt_id;
  -- Missing Manifest is rejected by the existing dedicated Manifest guard.
  IF FOUND AND NOT cehub_ai.application_lease_is_current(NEW.run_id,lease_id) THEN
   RAISE EXCEPTION 'BUDGET_APPLICATION_LEASE_LOST' USING ERRCODE='22023';
  END IF;
 END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.require_application_lease_dispatch() FROM PUBLIC;
CREATE TRIGGER require_application_lease_dispatch BEFORE INSERT ON cehub_ai.budget_journal
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.require_application_lease_dispatch();

CREATE FUNCTION cehub_ai.require_application_publication_lease() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE rid uuid;
BEGIN
 IF TG_TABLE_NAME='findings' THEN rid:=NEW.run_id;
 ELSE
  IF NEW.status<>'succeeded' OR OLD.status=NEW.status THEN RETURN NEW; END IF;
  rid:=NEW.id;
 END IF;
 IF EXISTS(SELECT 1 FROM cehub_ai.application_authorizations WHERE run_id=rid)
  AND NOT cehub_ai.application_lease_is_current(rid,
   nullif(current_setting('pdos.application_lease_id',true),'')::uuid) THEN
  RAISE EXCEPTION 'APPLICATION_RUN_LEASE_LOST' USING ERRCODE='22023';
 END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.require_application_publication_lease() FROM PUBLIC;
CREATE TRIGGER require_application_publication_lease BEFORE INSERT ON cehub_ai.findings
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.require_application_publication_lease();
CREATE TRIGGER require_application_success_lease BEFORE UPDATE OF status ON cehub_ai.agent_runs
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.require_application_publication_lease();

CREATE FUNCTION cehub_ai.finish_application_lease() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
BEGIN
 IF NEW.status IN ('succeeded','degraded','failed') THEN
  UPDATE cehub_ai.application_run_leases SET ended_at=clock_timestamp(),
   stop_reason=coalesce(NEW.error_code,'completed')
   WHERE tenant_id=NEW.tenant_id AND run_id=NEW.id AND ended_at IS NULL;
 END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.finish_application_lease() FROM PUBLIC;
CREATE TRIGGER finish_application_lease AFTER UPDATE OF status ON cehub_ai.agent_runs
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.finish_application_lease();

CREATE FUNCTION cehub_ai.expire_application_runs(wanted_limit integer DEFAULT 100)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r record; amount integer:=0; reason text;
BEGIN
 IF wanted_limit NOT BETWEEN 1 AND 1000 THEN RAISE EXCEPTION 'invalid expiry limit'; END IF;
 FOR r IN SELECT a.id,a.tenant_id FROM cehub_ai.agent_runs a
  JOIN cehub_ai.application_run_leases l ON l.tenant_id=a.tenant_id AND l.run_id=a.id
  WHERE a.status='running' AND l.ended_at IS NULL AND l.expires_at<=clock_timestamp()
  ORDER BY l.expires_at,a.id LIMIT wanted_limit FOR UPDATE OF a SKIP LOCKED LOOP
  PERFORM 1 FROM cehub_ai.application_run_leases WHERE run_id=r.id
   AND ended_at IS NULL AND expires_at<=clock_timestamp() FOR UPDATE;
  IF NOT FOUND THEN CONTINUE; END IF;
  reason:='APPLICATION_RUN_LEASE_EXPIRED';
  IF EXISTS(SELECT 1 FROM cehub_ai.budget_journal j WHERE j.run_id=r.id
    AND j.dispatched_at IS NOT NULL AND j.reservation_status IN ('reserved','unknown')
    AND NOT EXISTS(SELECT 1 FROM cehub_ai.budget_journal j2
      WHERE j2.tenant_id=j.tenant_id AND j2.attempt_id=j.attempt_id 
      AND j2.revision>j.revision)) THEN
   reason:='APPLICATION_CALL_RECEIPT_UNKNOWN';
  END IF;
  UPDATE cehub_ai.agent_runs SET status='degraded',error_code=reason,
   completed_at=clock_timestamp(),updated_at=clock_timestamp() WHERE id=r.id;
  amount:=amount+1;
 END LOOP;
 RETURN amount;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.expire_application_runs(integer) FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(TABLE)
    op.execute("REVOKE ALL ON cehub_ai.application_run_leases FROM PUBLIC")
    op.execute("ALTER TABLE cehub_ai.application_context_manifests ADD COLUMN owner_lease_id uuid")
    op.execute("""ALTER TABLE cehub_ai.application_context_manifests
        ADD CONSTRAINT fk_application_manifest_owner_lease
        FOREIGN KEY (tenant_id,run_id,owner_lease_id)
        REFERENCES cehub_ai.application_run_leases(tenant_id,run_id,id) ON DELETE RESTRICT""")
    op.execute(NEW_SYNC)
    op.execute(FUNCTIONS)
    op.execute(
        """DO $b$ BEGIN
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_worker') THEN
        GRANT EXECUTE ON FUNCTION cehub_ai.expire_application_runs(integer) TO pdos_worker;
        END IF; END $b$;"""
    )


def downgrade() -> None:
    op.execute(
        """DO $b$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.application_run_leases) THEN
        RAISE EXCEPTION 'cannot remove persistent application lease history';
        END IF; END $b$;"""
    )
    for table, trigger in [
        ("agent_runs", "finish_application_lease"),
        ("agent_runs", "require_application_success_lease"),
        ("findings", "require_application_publication_lease"),
        ("budget_journal", "require_application_lease_dispatch"),
        ("application_run_leases", "track_application_lease"),
        ("application_run_leases", "protect_application_lease"),
    ]:
        op.execute(f"DROP TRIGGER {trigger} ON cehub_ai.{table}")
    for signature in [
        "expire_application_runs(integer)",
        "finish_application_lease()",
        "require_application_publication_lease()",
        "require_application_lease_dispatch()",
        "track_application_lease()",
        "protect_application_lease()",
        "application_lease_is_current(uuid,uuid)",
    ]:
        op.execute(f"DROP FUNCTION cehub_ai.{signature}")
    op.execute(OLD_SYNC)
    op.execute("ALTER TABLE cehub_ai.application_context_manifests DROP COLUMN owner_lease_id")
    op.execute("DROP TABLE cehub_ai.application_run_leases")
