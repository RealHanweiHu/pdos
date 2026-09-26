"""Versioned event scheduling and trigger-to-outcome deadline fences."""

from collections.abc import Sequence

from alembic import op

revision: str = "0075_event_trigger_scheduling"
down_revision: str | Sequence[str] | None = "0074_checkpoint_scope_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = r"""
ALTER TABLE cehub_ai.agent_runs
 ADD COLUMN dispatch_key varchar(128),
 ADD COLUMN dispatch_policy varchar(32),
 ADD COLUMN dispatch_deadline timestamptz,
 DROP CONSTRAINT ck_agent_runs_lifecycle_consistent,
 ADD CONSTRAINT ck_agent_runs_lifecycle_consistent CHECK (
  (status IN ('debouncing','queued') AND started_at IS NULL AND completed_at IS NULL) OR
  (status='running' AND started_at IS NOT NULL AND completed_at IS NULL) OR
  (status IN ('succeeded','degraded','failed') AND started_at IS NOT NULL
    AND completed_at IS NOT NULL) OR
  (status='failed' AND started_at IS NULL AND completed_at IS NOT NULL
    AND dispatch_policy='milestone.v1' AND dispatch_deadline IS NOT NULL
    AND error_code='AGENT_TRIGGER_DEADLINE_EXCEEDED') IS TRUE),
 DROP CONSTRAINT uq_agent_runs_tenant_project_agent_window,
 ADD CONSTRAINT uq_agent_runs_tenant_project_agent_window UNIQUE NULLS NOT DISTINCT
   (tenant_id,project_id,agent_key,window_started_at,dispatch_key),
 ADD CONSTRAINT ck_agent_runs_dispatch_shape CHECK (
   (dispatch_policy IS NULL AND dispatch_key IS NULL AND dispatch_deadline IS NULL) OR
   (dispatch_policy IS NOT NULL AND dispatch_key IS NOT NULL AND
    ((dispatch_policy='milestone.v1' AND dispatch_deadline IS NOT NULL) OR
     (dispatch_policy='frequent_edit.v1' AND dispatch_deadline IS NULL))));
CREATE FUNCTION cehub_ai.protect_dispatch_policy() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $body$
DECLARE e cehub_event.events%ROWTYPE;
BEGIN
 IF TG_OP='UPDATE' THEN
  IF ROW(NEW.dispatch_key,NEW.dispatch_policy,NEW.dispatch_deadline) IS DISTINCT FROM
     ROW(OLD.dispatch_key,OLD.dispatch_policy,OLD.dispatch_deadline) THEN
   RAISE EXCEPTION 'dispatch policy is immutable' USING ERRCODE='42501';
  END IF;
  IF OLD.dispatch_policy IS NOT NULL AND ROW(
      NEW.tenant_id,NEW.project_id,NEW.agent_key,NEW.subscription_id,
      NEW.first_event_row_id,NEW.window_started_at,NEW.window_ended_at
    ) IS DISTINCT FROM ROW(
      OLD.tenant_id,OLD.project_id,OLD.agent_key,OLD.subscription_id,
      OLD.first_event_row_id,OLD.window_started_at,OLD.window_ended_at
    ) THEN
   RAISE EXCEPTION 'dispatch source is immutable' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
 END IF;
 IF NEW.dispatch_policy IS NULL THEN RETURN NEW; END IF;
 SELECT * INTO e FROM cehub_event.events WHERE id=NEW.first_event_row_id;
 IF NOT FOUND OR e.tenant_id<>NEW.tenant_id OR e.project_id IS DISTINCT FROM NEW.project_id
    OR NEW.request_id IS NOT NULL OR NEW.subscription_id IS NULL THEN
  RAISE EXCEPTION 'invalid dispatch source' USING ERRCODE='22023';
 END IF;
 IF NEW.dispatch_policy='milestone.v1' THEN
  IF e.event_type NOT IN ('PROJECT_STAGE_CHANGED','GATE_APPROVED','TEST_FAILED','ISSUE_CREATED',
    'ISSUE_STATUS_CHANGED','SUPPLIER_DELAY_REPORTED','COMPLAINT_CREATED','NCR_CREATED',
    'CHANGE_RECORD_CHANGED') OR NEW.dispatch_key IS DISTINCT FROM 'event:' || e.id::text
    OR NEW.dispatch_deadline IS DISTINCT FROM e.timestamp + interval '180 seconds'
    OR NEW.window_started_at IS DISTINCT FROM e.timestamp
    OR NEW.window_ended_at IS DISTINCT FROM e.timestamp THEN
   RAISE EXCEPTION 'invalid milestone policy' USING ERRCODE='22023';
  END IF;
 ELSIF NEW.dispatch_policy='frequent_edit.v1' THEN
  IF e.event_type NOT IN
    ('DEVELOPMENT_BOM_CREATED','DEVELOPMENT_BOM_ITEM_ADDED','DOCUMENT_UPLOADED')
    OR NEW.window_ended_at - NEW.window_started_at <> interval '900 seconds'
    OR e.timestamp < NEW.window_started_at OR e.timestamp >= NEW.window_ended_at THEN
   RAISE EXCEPTION 'invalid frequent edit policy' USING ERRCODE='22023';
  END IF;
 END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.protect_dispatch_policy() FROM PUBLIC;
CREATE TRIGGER protect_dispatch_policy BEFORE INSERT OR UPDATE ON cehub_ai.agent_runs
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_dispatch_policy();
"""

EXPIRY = r"""CREATE OR REPLACE FUNCTION cehub_ai.expire_queued_dispatch_runs(batch_limit integer)
RETURNS integer LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE count_expired integer;
BEGIN
 IF batch_limit IS NULL OR batch_limit<1 OR batch_limit>1000 THEN
  RAISE EXCEPTION 'invalid expiry batch size' USING ERRCODE='22023';
 END IF;
 WITH due AS (SELECT id FROM cehub_ai.agent_runs
   WHERE status IN ('debouncing','queued') AND dispatch_deadline <= clock_timestamp()
   ORDER BY dispatch_deadline,id LIMIT batch_limit FOR UPDATE SKIP LOCKED)
 UPDATE cehub_ai.agent_runs r SET status='failed',error_code='AGENT_TRIGGER_DEADLINE_EXCEEDED',
   completed_at=clock_timestamp(),updated_at=clock_timestamp() FROM due WHERE due.id=r.id;
 GET DIAGNOSTICS count_expired=ROW_COUNT;
 RETURN count_expired;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.expire_queued_dispatch_runs(integer) FROM PUBLIC;
"""

HELPERS = r"""CREATE OR REPLACE FUNCTION cehub_ai.agent_lease_is_current(
    wanted_run uuid, wanted_token uuid
) RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog
AS $function$
    SELECT EXISTS (
        SELECT 1 FROM cehub_ai.agent_runs AS run
        WHERE run.id = wanted_run AND run.status = 'running'
          AND run.run_context->>'_lease_token' = wanted_token::text
          AND nullif(run.run_context->>'_lease_expires_at', '')::timestamptz > clock_timestamp()
          AND (run.dispatch_deadline IS NULL OR run.dispatch_deadline > clock_timestamp())
    )
$function$;
REVOKE ALL ON FUNCTION cehub_ai.agent_lease_is_current(uuid, uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.renew_agent_run_lease(
    wanted_run uuid, wanted_token uuid
) RETURNS timestamptz LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog
AS $function$
DECLARE scoped_run cehub_ai.agent_runs%ROWTYPE; renewed_at timestamptz; expires_at timestamptz;
BEGIN
    SELECT * INTO scoped_run FROM cehub_ai.agent_runs WHERE id = wanted_run FOR UPDATE;
    -- Recheck after waiting for the row lock; an expired token cannot renew itself.
    IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(wanted_run, wanted_token) THEN
        RAISE EXCEPTION 'Agent run lease is invalid or expired' USING ERRCODE = '42501';
    END IF;
    renewed_at := clock_timestamp();
    expires_at := least(renewed_at + interval '60 seconds', scoped_run.dispatch_deadline);
    UPDATE cehub_ai.agent_runs SET run_context = run_context || jsonb_build_object(
        '_lease_expires_at', expires_at, '_lease_renewed_at', renewed_at
    ) WHERE id = wanted_run;
    RETURN expires_at;
END
$function$;
REVOKE ALL ON FUNCTION cehub_ai.renew_agent_run_lease(uuid, uuid) FROM PUBLIC;
"""

CLAIM = r"""CREATE OR REPLACE FUNCTION cehub_ai.claim_agent_run(
    claimed_at timestamptz
) RETURNS TABLE (
    id uuid,
    tenant_id uuid,
    project_id uuid,
    subscription_id uuid,
    agent_key varchar,
    status varchar,
    window_started_at timestamptz,
    window_ended_at timestamptz,
    first_event_row_id bigint,
    last_event_row_id bigint,
    event_count integer,
    event_row_ids jsonb,
    lease_token uuid
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    claimed_run cehub_ai.agent_runs%ROWTYPE;
    generated_lease uuid := gen_random_uuid();
BEGIN
    PERFORM cehub_ai.expire_queued_dispatch_runs(1000);
    SELECT * INTO claimed_run
    FROM cehub_ai.agent_runs AS candidate
    WHERE candidate.status = 'queued' AND candidate.request_id IS NULL
      AND candidate.subscription_id IS NOT NULL
      AND (candidate.dispatch_deadline IS NULL OR candidate.dispatch_deadline > clock_timestamp())
    ORDER BY CASE candidate.dispatch_policy WHEN 'milestone.v1' THEN 0 ELSE 1 END,
      candidate.dispatch_deadline NULLS LAST, candidate.created_at, candidate.id
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    claimed_at := clock_timestamp();
    UPDATE cehub_ai.agent_runs AS target
    SET status = 'running',
        started_at = claimed_at,
        run_context = target.run_context || jsonb_build_object(
            '_lease_token', generated_lease::text,
            '_lease_expires_at',
            least(claimed_at + interval '60 seconds', claimed_run.dispatch_deadline),
            '_lease_renewed_at', claimed_at
        ),
        updated_at = claimed_at
    WHERE target.id = claimed_run.id
    RETURNING * INTO claimed_run;

    RETURN QUERY SELECT
        claimed_run.id,
        claimed_run.tenant_id,
        claimed_run.project_id,
        claimed_run.subscription_id,
        claimed_run.agent_key,
        claimed_run.status,
        claimed_run.window_started_at,
        claimed_run.window_ended_at,
        claimed_run.first_event_row_id,
        claimed_run.last_event_row_id,
        claimed_run.event_count,
        claimed_run.event_row_ids,
        generated_lease;
END
$function$;"""

RECOVER = r"""CREATE OR REPLACE FUNCTION cehub_ai.recover_expired_agent_runs(batch_limit integer)
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
        ELSIF r.dispatch_deadline <= clock_timestamp() THEN
            stop_reason := 'AGENT_TRIGGER_DEADLINE_EXCEEDED';
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

OLD_HELPERS = r"""CREATE OR REPLACE FUNCTION cehub_ai.agent_lease_is_current(
    wanted_run uuid, wanted_token uuid
) RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog
AS $function$
    SELECT EXISTS (
        SELECT 1 FROM cehub_ai.agent_runs AS run
        WHERE run.id = wanted_run AND run.status = 'running'
          AND run.run_context->>'_lease_token' = wanted_token::text
          AND nullif(run.run_context->>'_lease_expires_at', '')::timestamptz > clock_timestamp()
    )
$function$;
REVOKE ALL ON FUNCTION cehub_ai.agent_lease_is_current(uuid, uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.renew_agent_run_lease(
    wanted_run uuid, wanted_token uuid
) RETURNS timestamptz LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog
AS $function$
DECLARE scoped_run cehub_ai.agent_runs%ROWTYPE; renewed_at timestamptz; expires_at timestamptz;
BEGIN
    SELECT * INTO scoped_run FROM cehub_ai.agent_runs WHERE id = wanted_run FOR UPDATE;
    -- Recheck after waiting for the row lock; an expired token cannot renew itself.
    IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(wanted_run, wanted_token) THEN
        RAISE EXCEPTION 'Agent run lease is invalid or expired' USING ERRCODE = '42501';
    END IF;
    renewed_at := clock_timestamp();
    expires_at := renewed_at + interval '60 seconds';
    UPDATE cehub_ai.agent_runs SET run_context = run_context || jsonb_build_object(
        '_lease_expires_at', expires_at, '_lease_renewed_at', renewed_at
    ) WHERE id = wanted_run;
    RETURN expires_at;
END
$function$;
REVOKE ALL ON FUNCTION cehub_ai.renew_agent_run_lease(uuid, uuid) FROM PUBLIC;
"""

OLD_CLAIM = r"""CREATE OR REPLACE FUNCTION cehub_ai.claim_agent_run(
    claimed_at timestamptz
) RETURNS TABLE (
    id uuid,
    tenant_id uuid,
    project_id uuid,
    subscription_id uuid,
    agent_key varchar,
    status varchar,
    window_started_at timestamptz,
    window_ended_at timestamptz,
    first_event_row_id bigint,
    last_event_row_id bigint,
    event_count integer,
    event_row_ids jsonb,
    lease_token uuid
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    claimed_run cehub_ai.agent_runs%ROWTYPE;
    generated_lease uuid := gen_random_uuid();
BEGIN
    SELECT * INTO claimed_run
    FROM cehub_ai.agent_runs AS candidate
    WHERE candidate.status = 'queued'
    ORDER BY candidate.created_at, candidate.id
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    claimed_at := clock_timestamp();
    UPDATE cehub_ai.agent_runs AS target
    SET status = 'running',
        started_at = claimed_at,
        run_context = target.run_context || jsonb_build_object(
            '_lease_token', generated_lease::text,
            '_lease_expires_at', claimed_at + interval '60 seconds',
            '_lease_renewed_at', claimed_at
        ),
        updated_at = claimed_at
    WHERE target.id = claimed_run.id
    RETURNING * INTO claimed_run;

    RETURN QUERY SELECT
        claimed_run.id,
        claimed_run.tenant_id,
        claimed_run.project_id,
        claimed_run.subscription_id,
        claimed_run.agent_key,
        claimed_run.status,
        claimed_run.window_started_at,
        claimed_run.window_ended_at,
        claimed_run.first_event_row_id,
        claimed_run.last_event_row_id,
        claimed_run.event_count,
        claimed_run.event_row_ids,
        generated_lease;
END
$function$;"""

OLD_RECOVER = r"""
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
    for sql in (EXPIRY, HELPERS, CLAIM, RECOVER):
        op.execute(sql)
    op.execute("""DO $body$ BEGIN
      IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_worker') THEN
        GRANT EXECUTE ON FUNCTION cehub_ai.expire_queued_dispatch_runs(integer) TO pdos_worker;
        GRANT INSERT(dispatch_key,dispatch_policy,dispatch_deadline)
          ON cehub_ai.agent_runs TO pdos_worker;
      END IF;
    END $body$;""")


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN
      IF EXISTS(SELECT 1 FROM cehub_ai.agent_runs WHERE dispatch_policy IS NOT NULL) THEN
        RAISE EXCEPTION 'cannot remove persistent dispatch policy history';
      END IF;
    END $body$;""")
    for sql in (OLD_RECOVER, OLD_CLAIM, OLD_HELPERS):
        op.execute(sql)
    op.execute("DROP FUNCTION IF EXISTS cehub_ai.expire_queued_dispatch_runs(integer)")
    op.execute("DROP TRIGGER protect_dispatch_policy ON cehub_ai.agent_runs")
    op.execute("DROP FUNCTION cehub_ai.protect_dispatch_policy()")
    op.execute("""ALTER TABLE cehub_ai.agent_runs
      DROP CONSTRAINT uq_agent_runs_tenant_project_agent_window,
      DROP CONSTRAINT ck_agent_runs_dispatch_shape,
      DROP CONSTRAINT ck_agent_runs_lifecycle_consistent,
      ADD CONSTRAINT ck_agent_runs_lifecycle_consistent CHECK (
        (status IN ('debouncing','queued') AND started_at IS NULL AND completed_at IS NULL) OR
        (status='running' AND started_at IS NOT NULL AND completed_at IS NULL) OR
        (status IN ('succeeded','degraded','failed') AND started_at IS NOT NULL
          AND completed_at IS NOT NULL)),
      DROP COLUMN dispatch_key, DROP COLUMN dispatch_policy, DROP COLUMN dispatch_deadline,
      ADD CONSTRAINT uq_agent_runs_tenant_project_agent_window
        UNIQUE(tenant_id,project_id,agent_key,window_started_at);""")
