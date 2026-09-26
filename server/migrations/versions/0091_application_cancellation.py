"""Cancel application run lineages and persist the user's control receipt."""

import re
from collections.abc import Sequence
from importlib import import_module

from alembic import op

revision: str = "0091_application_cancellation"
down_revision: str | Sequence[str] | None = "0090_agent_loop_checkpoints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PREVIOUS = import_module("migrations.versions.0072_active_execution_budget")
matched = re.search(
    r"CREATE FUNCTION cehub_ai.check_run_active_budget\b.*?\$body\$;", PREVIOUS.SCHEMA, re.S
)
assert matched is not None
OLD_ACTIVE = matched.group().replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
ACTIVE = OLD_ACTIVE.replace(
    "    IF observed_at >= deadline THEN",
    """    IF EXISTS(SELECT 1 FROM cehub_ai.application_cancellations
      WHERE tenant_id=wanted_tenant AND lineage_id=lid) THEN
        RAISE EXCEPTION 'BUDGET_LINEAGE_CANCELLED' USING ERRCODE='22023';
    END IF;
    IF observed_at >= deadline THEN""",
)
SCHEMA = """
CREATE TABLE cehub_ai.application_cancellations (
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL,run_id uuid NOT NULL,lineage_id uuid,
 actor_user_id uuid NOT NULL,created_at timestamptz NOT NULL,
 CONSTRAINT uq_application_cancel_run UNIQUE(tenant_id,run_id),
 CONSTRAINT uq_application_cancel_lineage UNIQUE(tenant_id,lineage_id),
 FOREIGN KEY(tenant_id,run_id) REFERENCES cehub_ai.agent_runs(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,lineage_id) REFERENCES cehub_ai.budget_lineages(tenant_id,id)
  ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,actor_user_id) REFERENCES cehub_core.users(tenant_id,id) ON DELETE RESTRICT
);
REVOKE ALL ON cehub_ai.application_cancellations FROM PUBLIC;
CREATE TRIGGER protect_application_cancellation BEFORE UPDATE OR DELETE
 ON cehub_ai.application_cancellations FOR EACH ROW
 EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
ALTER TABLE cehub_ai.application_input_waits
 DROP CONSTRAINT ck_application_input_waits_resolution;
ALTER TABLE cehub_ai.application_input_waits
 ADD CONSTRAINT ck_application_input_waits_resolution
 CHECK(((resolved_at IS NULL AND resolution IS NULL AND continuation_run_id IS NULL) OR
 (resolved_at IS NOT NULL AND resolved_at>=created_at AND
 ((resolution='input_received' AND continuation_run_id IS NOT NULL) OR
 (resolution IN ('finding_accepted','finding_rejected','finding_applied','expired','cancelled')
 AND continuation_run_id IS NULL)))) IS TRUE);
"""
FUNCTIONS = r"""
CREATE FUNCTION cehub_ai.reject_cancelled_lineage_link() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
BEGIN
 PERFORM 1 FROM cehub_ai.budget_lineages WHERE tenant_id=NEW.tenant_id AND id=NEW.lineage_id
  FOR UPDATE;
 IF EXISTS(SELECT 1 FROM cehub_ai.application_cancellations
  WHERE tenant_id=NEW.tenant_id AND lineage_id=NEW.lineage_id) THEN
  RAISE EXCEPTION 'BUDGET_LINEAGE_CANCELLED' USING ERRCODE='22023'; END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.reject_cancelled_lineage_link() FROM PUBLIC;
CREATE TRIGGER reject_cancelled_lineage_link BEFORE INSERT ON cehub_ai.budget_run_links
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.reject_cancelled_lineage_link();

CREATE FUNCTION cehub_ai.cancel_application_request(wanted_tenant uuid,wanted_run uuid,
 wanted_actor uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; lid uuid; affected uuid[]; receipt uuid;
 observed_at timestamptz; prior cehub_ai.application_cancellations%ROWTYPE;
BEGIN
 PERFORM 1 FROM cehub_core.tenants WHERE id=wanted_tenant FOR UPDATE;
 PERFORM pg_advisory_xact_lock(hashtextextended('pdos-budget:'||wanted_tenant::text,0));
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=wanted_tenant AND id=wanted_run
  AND coalesce(requested_by_user_id,(SELECT principal_id
   FROM cehub_ai.application_authorizations WHERE run_id=wanted_run))=wanted_actor;
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM cehub_core.users
  WHERE tenant_id=wanted_tenant AND id=wanted_actor AND is_active) THEN
  RAISE EXCEPTION 'APPLICATION_CONTROL_ACCESS_DENIED' USING ERRCODE='42501'; END IF;
 SELECT lineage_id INTO lid FROM cehub_ai.budget_run_links
  WHERE tenant_id=wanted_tenant AND run_id=wanted_run;
 IF lid IS NOT NULL THEN
  PERFORM 1 FROM cehub_ai.budget_lineages WHERE tenant_id=wanted_tenant AND id=lid FOR UPDATE;
 END IF;
 SELECT * INTO prior FROM cehub_ai.application_cancellations
  WHERE tenant_id=wanted_tenant AND (run_id=wanted_run OR lineage_id=lid);
 IF FOUND THEN
  RETURN jsonb_build_object('run_id',wanted_run,'cancellation_id',prior.id,
   'lineage_id',lid,'cancelled_run_ids','[]'::jsonb,'changed',false);
 END IF;
 PERFORM 1 FROM cehub_ai.agent_runs a WHERE a.tenant_id=wanted_tenant
  AND (a.id=wanted_run OR EXISTS(SELECT 1 FROM cehub_ai.budget_run_links b
   WHERE b.tenant_id=wanted_tenant AND b.lineage_id=lid AND b.run_id=a.id))
  ORDER BY a.id FOR UPDATE;
 SELECT array_agg(a.id ORDER BY a.id) INTO affected FROM cehub_ai.agent_runs a
 WHERE a.tenant_id=wanted_tenant AND
  (a.id=wanted_run OR EXISTS(SELECT 1 FROM cehub_ai.budget_run_links b
   WHERE b.tenant_id=wanted_tenant AND b.lineage_id=lid AND b.run_id=a.id))
  AND (a.status IN ('queued','running','waiting_input') OR
    a.status='degraded' AND a.error_code='APPLICATION_RUN_LEASE_EXPIRED');
 IF affected IS NULL THEN
  RETURN jsonb_build_object('run_id',wanted_run,'cancellation_id',NULL,
   'lineage_id',lid,'cancelled_run_ids','[]'::jsonb,'changed',false);
 END IF;
 IF EXISTS(SELECT 1 FROM cehub_ai.agent_runs a WHERE id=ANY(affected)
   AND coalesce(a.requested_by_user_id,(SELECT principal_id
    FROM cehub_ai.application_authorizations WHERE run_id=a.id))
    IS DISTINCT FROM wanted_actor) THEN
  RAISE EXCEPTION 'APPLICATION_CONTROL_ACCESS_DENIED' USING ERRCODE='42501'; END IF;
 observed_at:=clock_timestamp(); receipt:=gen_random_uuid();
 INSERT INTO cehub_ai.application_cancellations VALUES(receipt,wanted_tenant,wanted_run,lid,
  wanted_actor,observed_at);
 UPDATE cehub_ai.application_input_waits SET resolved_at=observed_at,resolution='cancelled'
  WHERE tenant_id=wanted_tenant AND run_id=ANY(affected) AND resolved_at IS NULL;
 UPDATE cehub_ai.agent_runs SET status='failed',error_code='APPLICATION_REQUEST_CANCELLED',
  completed_at=observed_at,updated_at=observed_at WHERE tenant_id=wanted_tenant
  AND id=ANY(affected) AND (status IN ('queued','running','waiting_input') OR
   status='degraded' AND error_code='APPLICATION_RUN_LEASE_EXPIRED');
 RETURN jsonb_build_object('run_id',wanted_run,'cancellation_id',receipt,'lineage_id',lid,
  'cancelled_run_ids',to_jsonb(affected),'changed',true);
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.cancel_application_request(uuid,uuid,uuid) FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute(FUNCTIONS)
    op.execute(ACTIVE)


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.application_cancellations) THEN
     RAISE EXCEPTION 'cannot remove application cancellation history'; END IF; END $body$;""")
    op.execute(OLD_ACTIVE)
    op.execute("""DROP FUNCTION cehub_ai.cancel_application_request(uuid,uuid,uuid);
     DROP TRIGGER reject_cancelled_lineage_link ON cehub_ai.budget_run_links;
     DROP FUNCTION cehub_ai.reject_cancelled_lineage_link();
     DROP TABLE cehub_ai.application_cancellations;
     ALTER TABLE cehub_ai.application_input_waits
 DROP CONSTRAINT ck_application_input_waits_resolution;
     ALTER TABLE cehub_ai.application_input_waits
 ADD CONSTRAINT ck_application_input_waits_resolution
      CHECK(((resolved_at IS NULL AND resolution IS NULL AND continuation_run_id IS NULL) OR
       (resolved_at IS NOT NULL AND resolved_at>=created_at AND
        ((resolution='input_received' AND continuation_run_id IS NOT NULL) OR
         (resolution IN ('finding_accepted','finding_rejected','finding_applied','expired')
          AND continuation_run_id IS NULL)))) IS TRUE);""")
