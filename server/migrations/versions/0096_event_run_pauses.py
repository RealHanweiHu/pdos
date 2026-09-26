"""Durable cooperative pauses at event runtime checkpoints."""

from collections.abc import Sequence
from importlib import import_module

from alembic import op

revision: str = "0096_event_run_pauses"
down_revision: str | Sequence[str] | None = "0095_event_run_cancellation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
PREVIOUS = import_module("migrations.versions.0079_event_authorization")
CLAIM = PREVIOUS.CLAIM.replace(
    "AND candidate.subscription_id IS NOT NULL",
    """AND candidate.subscription_id IS NOT NULL
      AND NOT EXISTS(SELECT 1 FROM cehub_ai.event_run_pauses p
       WHERE p.run_id=candidate.id AND p.resolved_at IS NULL)""",
)
SCHEMA = r"""
CREATE TABLE cehub_ai.event_run_pauses (
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL,run_id uuid NOT NULL,actor_user_id uuid NOT NULL,
 created_at timestamptz NOT NULL,honored_at timestamptz,resolved_at timestamptz,
 resolution varchar(24),resolved_by_user_id uuid,
 FOREIGN KEY(tenant_id,run_id) REFERENCES cehub_ai.agent_runs(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,actor_user_id) REFERENCES cehub_core.users(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,resolved_by_user_id) REFERENCES cehub_core.users(tenant_id,id)
  ON DELETE RESTRICT,
 CONSTRAINT ck_event_run_pauses_resolution CHECK(
  (honored_at IS NULL OR honored_at>=created_at) AND
  ((resolved_at IS NULL AND resolution IS NULL AND resolved_by_user_id IS NULL) OR
   (resolved_at IS NOT NULL AND resolved_at>=created_at AND
    ((resolution='resumed' AND resolved_by_user_id IS NOT NULL) OR
     (resolution='run_finished' AND resolved_by_user_id IS NULL)))))
);
CREATE UNIQUE INDEX uq_event_run_pause_open ON cehub_ai.event_run_pauses(tenant_id,run_id)
 WHERE resolved_at IS NULL;
REVOKE ALL ON cehub_ai.event_run_pauses FROM PUBLIC;
CREATE FUNCTION cehub_ai.protect_event_pause() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $body$
BEGIN
 IF TG_OP='DELETE' OR (NEW.id,NEW.tenant_id,NEW.run_id,NEW.actor_user_id,NEW.created_at)
  IS DISTINCT FROM (OLD.id,OLD.tenant_id,OLD.run_id,OLD.actor_user_id,OLD.created_at)
  OR (OLD.honored_at IS NOT NULL AND NEW.honored_at IS DISTINCT FROM OLD.honored_at)
  OR (OLD.resolved_at IS NOT NULL AND
   (NEW.resolved_at,NEW.resolution,NEW.resolved_by_user_id) IS DISTINCT FROM
   (OLD.resolved_at,OLD.resolution,OLD.resolved_by_user_id)) THEN
  RAISE EXCEPTION 'event pause history is immutable'; END IF;
 RETURN NEW;
END $body$;
CREATE TRIGGER protect_event_pause BEFORE UPDATE OR DELETE ON cehub_ai.event_run_pauses
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_event_pause();
CREATE FUNCTION cehub_ai.finish_event_pause() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
BEGIN
 IF NEW.status IN ('succeeded','degraded','failed') THEN
  UPDATE cehub_ai.event_run_pauses SET resolved_at=clock_timestamp(),resolution='run_finished'
   WHERE tenant_id=NEW.tenant_id AND run_id=NEW.id AND resolved_at IS NULL;
 ELSIF NEW.status IN ('queued','debouncing') THEN
  UPDATE cehub_ai.event_run_pauses SET honored_at=clock_timestamp()
   WHERE tenant_id=NEW.tenant_id AND run_id=NEW.id AND resolved_at IS NULL AND honored_at IS NULL;
 END IF;
 RETURN NEW;
END $body$;
CREATE TRIGGER finish_event_pause AFTER UPDATE OF status ON cehub_ai.agent_runs
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.finish_event_pause();
REVOKE ALL ON FUNCTION cehub_ai.protect_event_pause(),cehub_ai.finish_event_pause() FROM PUBLIC;
"""
CONTROL = r"""
CREATE FUNCTION cehub_ai.control_event_pause(wanted_tenant uuid,wanted_run uuid,
 wanted_actor uuid,wanted_version integer,resume boolean) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE;p cehub_ai.event_run_pauses%ROWTYPE;
 stamp timestamptz;pid uuid;
BEGIN
 PERFORM 1 FROM cehub_core.tenants WHERE id=wanted_tenant AND status='active' FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'APPLICATION_CONTROL_ACCESS_DENIED'
  USING ERRCODE='42501'; END IF;
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=wanted_tenant AND id=wanted_run
  AND request_id IS NULL AND requested_by_user_id IS NULL AND subscription_id IS NOT NULL
  FOR UPDATE;
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM cehub_core.users WHERE tenant_id=wanted_tenant
  AND id=wanted_actor AND is_active AND auth_version=wanted_version
  AND role IN ('owner','admin','project_manager')) THEN
  RAISE EXCEPTION 'APPLICATION_CONTROL_ACCESS_DENIED' USING ERRCODE='42501'; END IF;
 SELECT * INTO p FROM cehub_ai.event_run_pauses WHERE tenant_id=wanted_tenant
  AND run_id=wanted_run AND resolved_at IS NULL FOR UPDATE;
 IF r.status NOT IN ('debouncing','queued','running') OR (resume AND p.id IS NULL) THEN
  RETURN jsonb_build_object('run_id',wanted_run,'changed',false,'pause_id',NULL);
 END IF;
 IF resume THEN
  PERFORM cehub_ai.check_run_active_budget(wanted_tenant,wanted_run);
  IF r.dispatch_deadline<=clock_timestamp() OR NOT EXISTS(SELECT 1
   FROM cehub_ai.agent_subscriptions WHERE id=r.subscription_id AND status='active')
   OR (EXISTS(SELECT 1 FROM cehub_ai.agent_authorizations WHERE run_id=r.id)
    AND NOT cehub_ai.event_authorization_is_current(r.id)) THEN
   RAISE EXCEPTION 'EVENT_PAUSE_AUTHORIZATION_EXPIRED' USING ERRCODE='22023'; END IF;
  UPDATE cehub_ai.event_run_pauses SET resolved_at=clock_timestamp(),resolution='resumed',
   resolved_by_user_id=wanted_actor WHERE id=p.id;
  RETURN jsonb_build_object('run_id',wanted_run,'changed',true,'pause_id',p.id);
 END IF;
 IF p.id IS NOT NULL THEN
  RETURN jsonb_build_object('run_id',wanted_run,'changed',false,'pause_id',p.id);
 END IF;
 PERFORM cehub_ai.check_run_active_budget(wanted_tenant,wanted_run);
 stamp:=clock_timestamp();pid:=gen_random_uuid();
 INSERT INTO cehub_ai.event_run_pauses VALUES(pid,wanted_tenant,wanted_run,wanted_actor,
  stamp,CASE WHEN r.status IN ('debouncing','queued') THEN stamp END,NULL,NULL,NULL);
 RETURN jsonb_build_object('run_id',wanted_run,'changed',true,'pause_id',pid);
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.control_event_pause(uuid,uuid,uuid,integer,boolean) FROM PUBLIC;
"""
HONOR = r"""
CREATE FUNCTION cehub_ai.honor_event_pause() RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE;p cehub_ai.event_run_pauses%ROWTYPE;
 cp uuid;step_cp cehub_ai.agent_loop_checkpoints%ROWTYPE;stamp timestamptz;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid FOR UPDATE;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent pause lease is invalid' USING ERRCODE='42501'; END IF;
 SELECT * INTO p FROM cehub_ai.event_run_pauses WHERE tenant_id=r.tenant_id
  AND run_id=r.id AND resolved_at IS NULL FOR UPDATE;
 IF NOT FOUND THEN RETURN false; END IF;
 IF EXISTS(SELECT 1 FROM (SELECT DISTINCT ON(attempt_id) held_tokens
  FROM cehub_ai.budget_journal WHERE tenant_id=r.tenant_id AND run_id=r.id
  ORDER BY attempt_id,revision DESC) j WHERE held_tokens>0) OR EXISTS(
   SELECT 1 FROM cehub_ai.agent_tool_dispatches d WHERE d.run_id=r.id AND NOT EXISTS(
    SELECT 1 FROM cehub_ai.agent_tool_observations o WHERE o.tool_intent_id=d.intent_id)) THEN
  RETURN false; END IF;
 SELECT id INTO cp FROM cehub_ai.agent_result_checkpoints
  WHERE tenant_id=r.tenant_id AND run_id=r.id;
 SELECT * INTO step_cp FROM cehub_ai.agent_loop_checkpoints WHERE tenant_id=r.tenant_id
  AND run_id=r.id ORDER BY next_step DESC LIMIT 1;
 IF cp IS NULL AND step_cp.id IS NOT NULL AND EXISTS(SELECT 1 FROM cehub_ai.model_invocations
  WHERE tenant_id=r.tenant_id AND run_id=r.id AND NOT id=ANY(step_cp.trace_ids)) THEN
  RETURN false; END IF;
 IF cp IS NULL AND step_cp.id IS NULL AND (EXISTS(SELECT 1 FROM cehub_ai.model_invocations
  WHERE tenant_id=r.tenant_id AND run_id=r.id) OR EXISTS(
   SELECT 1 FROM cehub_ai.agent_tool_dispatches
   WHERE tenant_id=r.tenant_id AND run_id=r.id)) THEN RETURN false; END IF;
 PERFORM cehub_ai.check_run_active_budget(r.tenant_id,r.id);
 stamp:=clock_timestamp();
 UPDATE cehub_ai.event_run_pauses SET honored_at=stamp WHERE id=p.id;
 UPDATE cehub_ai.agent_runs SET status='queued',started_at=NULL,completed_at=NULL,
  run_context=(run_context-'_lease_token'-'_lease_expires_at'-'_lease_renewed_at')
   ||jsonb_build_object('_resume_checkpoint_id',cp,'_resume_loop_checkpoint_id',
     CASE WHEN cp IS NULL THEN step_cp.id ELSE NULL END),updated_at=stamp WHERE id=r.id;
 RETURN true;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.honor_event_pause() FROM PUBLIC;
"""


def upgrade() -> None:
    for sql in (SCHEMA, CONTROL, HONOR, CLAIM):
        op.execute(sql)
    op.execute("""DO $body$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_agent') THEN
     GRANT EXECUTE ON FUNCTION cehub_ai.honor_event_pause() TO pdos_agent;
     END IF; END $body$;""")


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.event_run_pauses) THEN
     RAISE EXCEPTION 'cannot remove event pause history'; END IF; END $body$;""")
    op.execute(PREVIOUS.CLAIM)
    op.execute("""DROP TRIGGER finish_event_pause ON cehub_ai.agent_runs;
     DROP FUNCTION cehub_ai.finish_event_pause();
     DROP FUNCTION cehub_ai.control_event_pause(uuid,uuid,uuid,integer,boolean);
     DROP FUNCTION cehub_ai.honor_event_pause();
     DROP TABLE cehub_ai.event_run_pauses;
     DROP FUNCTION cehub_ai.protect_event_pause();""")
