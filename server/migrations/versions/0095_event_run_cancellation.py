"""Project event cancellation shares durable lineage control with user requests."""

from collections.abc import Sequence
from importlib import import_module

from alembic import op

revision: str = "0095_event_run_cancellation"
down_revision: str | Sequence[str] | None = "0094_report_import_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
PREVIOUS = import_module("migrations.versions.0093_test_plan_queue")
LIFECYCLE = PREVIOUS.LIFECYCLE.replace(
    "error_code IN ('BUDGET_LINEAGE_EXPIRED','AGENT_AUTHORIZATION_CHANGED')",
    """error_code IN ('BUDGET_LINEAGE_EXPIRED','AGENT_AUTHORIZATION_CHANGED') OR
     (error_code='EVENT_RUN_CANCELLED' AND request_id IS NULL
      AND requested_by_user_id IS NULL AND subscription_id IS NOT NULL)""",
)
FUNCTION = r"""
CREATE FUNCTION cehub_ai.cancel_event_run(wanted_tenant uuid,wanted_run uuid,
 wanted_actor uuid,wanted_auth_version integer) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; lid uuid; affected uuid[]; receipt uuid;
 observed_at timestamptz; prior cehub_ai.application_cancellations%ROWTYPE;
BEGIN
 PERFORM 1 FROM cehub_core.tenants WHERE id=wanted_tenant AND status='active' FOR UPDATE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'APPLICATION_CONTROL_ACCESS_DENIED' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('pdos-budget:'||wanted_tenant::text,0));
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=wanted_tenant AND id=wanted_run
  AND subscription_id IS NOT NULL AND request_id IS NULL AND requested_by_user_id IS NULL;
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM cehub_core.users WHERE tenant_id=wanted_tenant
  AND id=wanted_actor AND is_active AND auth_version=wanted_auth_version
  AND role IN ('owner','admin','project_manager')) THEN
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
  AND a.status IN ('debouncing','queued','running','waiting_input');
 IF affected IS NULL THEN
  RETURN jsonb_build_object('run_id',wanted_run,'cancellation_id',NULL,
   'lineage_id',lid,'cancelled_run_ids','[]'::jsonb,'changed',false);
 END IF;
 -- A project event stop cannot also cancel another project or personal conversation.
 IF EXISTS(SELECT 1 FROM cehub_ai.agent_runs a WHERE id=ANY(affected)
  AND (a.project_id<>r.project_id OR a.request_id IS NOT NULL
   OR a.requested_by_user_id IS NOT NULL OR a.subscription_id IS NULL)) THEN
  RAISE EXCEPTION 'APPLICATION_CONTROL_ACCESS_DENIED' USING ERRCODE='42501'; END IF;
 observed_at:=clock_timestamp(); receipt:=gen_random_uuid();
 INSERT INTO cehub_ai.application_cancellations VALUES(receipt,wanted_tenant,wanted_run,lid,
  wanted_actor,observed_at);
 UPDATE cehub_ai.agent_runs SET status='failed',error_code='EVENT_RUN_CANCELLED',
  completed_at=observed_at,updated_at=observed_at WHERE tenant_id=wanted_tenant
  AND id=ANY(affected) AND status IN ('debouncing','queued','running','waiting_input');
 RETURN jsonb_build_object('run_id',wanted_run,'cancellation_id',receipt,'lineage_id',lid,
  'cancelled_run_ids',to_jsonb(affected),'changed',true);
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.cancel_event_run(uuid,uuid,uuid,integer) FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(LIFECYCLE)
    op.execute(FUNCTION)


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.agent_runs
     WHERE error_code='EVENT_RUN_CANCELLED') THEN
      RAISE EXCEPTION 'cannot remove event cancellation history'; END IF; END $body$;""")
    op.execute("DROP FUNCTION cehub_ai.cancel_event_run(uuid,uuid,uuid,integer)")
    op.execute(PREVIOUS.LIFECYCLE)
