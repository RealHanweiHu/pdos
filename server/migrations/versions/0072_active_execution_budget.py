"""Persistent cumulative execution time for budget lineages and model admission."""

from collections.abc import Sequence

from alembic import op

revision: str = "0072_active_execution_budget"
down_revision: str | Sequence[str] | None = "0071_agent_lease_expiry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = r"""
CREATE TABLE cehub_ai.budget_activity_coverage (
    tenant_id uuid NOT NULL, lineage_id uuid NOT NULL, started_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, lineage_id),
    FOREIGN KEY (tenant_id, lineage_id) REFERENCES cehub_ai.budget_lineages(tenant_id,id)
      ON DELETE RESTRICT
);
CREATE TABLE cehub_ai.budget_activity_spans (
    id uuid PRIMARY KEY, tenant_id uuid NOT NULL, lineage_id uuid NOT NULL,
    run_id uuid NOT NULL, lease_token uuid, started_at timestamptz NOT NULL,
    stopped_at timestamptz, lease_expires_at timestamptz,
    FOREIGN KEY (tenant_id, lineage_id, run_id)
      REFERENCES cehub_ai.budget_run_links(tenant_id,lineage_id,run_id) ON DELETE RESTRICT,
    CONSTRAINT ck_budget_activity_spans_activity_span_stop_order
      CHECK (stopped_at IS NULL OR stopped_at >= started_at)
);
CREATE UNIQUE INDEX uq_activity_open_run ON cehub_ai.budget_activity_spans(tenant_id,run_id)
    WHERE stopped_at IS NULL;
CREATE INDEX ix_activity_lineage ON cehub_ai.budget_activity_spans(tenant_id,lineage_id);
REVOKE ALL ON cehub_ai.budget_activity_coverage, cehub_ai.budget_activity_spans FROM PUBLIC;

CREATE FUNCTION cehub_ai.protect_activity_history() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $body$
BEGIN
    IF pg_trigger_depth() < 2 OR TG_OP='DELETE' THEN
        RAISE EXCEPTION 'activity history is maintained only by run lifecycle triggers'
          USING ERRCODE='42501';
    END IF;
    RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.protect_activity_history() FROM PUBLIC;
CREATE TRIGGER protect_activity_history BEFORE INSERT OR UPDATE OR DELETE
    ON cehub_ai.budget_activity_spans FOR EACH ROW
    EXECUTE FUNCTION cehub_ai.protect_activity_history();
CREATE TRIGGER protect_activity_coverage BEFORE INSERT OR UPDATE OR DELETE
    ON cehub_ai.budget_activity_coverage FOR EACH ROW
    EXECUTE FUNCTION cehub_ai.protect_activity_history();

CREATE FUNCTION cehub_ai.start_activity_coverage() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
BEGIN
    INSERT INTO cehub_ai.budget_activity_coverage VALUES(NEW.tenant_id,NEW.id,clock_timestamp());
    RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.start_activity_coverage() FROM PUBLIC;
CREATE TRIGGER start_activity_coverage AFTER INSERT ON cehub_ai.budget_lineages
    FOR EACH ROW EXECUTE FUNCTION cehub_ai.start_activity_coverage();

CREATE FUNCTION cehub_ai.sync_run_activity(wanted_tenant uuid, wanted_run uuid) RETURNS void
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
REVOKE ALL ON FUNCTION cehub_ai.sync_run_activity(uuid,uuid) FROM PUBLIC;

CREATE FUNCTION cehub_ai.track_run_activity() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
BEGIN
    IF TG_TABLE_NAME='budget_run_links' THEN
        PERFORM cehub_ai.sync_run_activity(NEW.tenant_id,NEW.run_id);
    ELSE
        PERFORM cehub_ai.sync_run_activity(NEW.tenant_id,NEW.id);
    END IF;
    RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.track_run_activity() FROM PUBLIC;
CREATE TRIGGER track_link_activity AFTER INSERT ON cehub_ai.budget_run_links
    FOR EACH ROW EXECUTE FUNCTION cehub_ai.track_run_activity();
CREATE TRIGGER track_run_activity AFTER UPDATE OF status,run_context ON cehub_ai.agent_runs
    FOR EACH ROW EXECUTE FUNCTION cehub_ai.track_run_activity();

CREATE FUNCTION cehub_ai.check_run_active_budget(wanted_tenant uuid,wanted_run uuid)
RETURNS void LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $body$
DECLARE lid uuid; allowance numeric; used numeric; deadline timestamptz;
    observed_at timestamptz := clock_timestamp();
BEGIN
    SELECT l.id,(l.profile->>'active_seconds')::numeric,l.absolute_deadline
      INTO lid,allowance,deadline
      FROM cehub_ai.budget_lineages l JOIN cehub_ai.budget_run_links r
        ON r.tenant_id=l.tenant_id AND r.lineage_id=l.id
      WHERE r.tenant_id=wanted_tenant AND r.run_id=wanted_run;
    IF lid IS NULL THEN
        RAISE EXCEPTION 'BUDGET_RUN_UNBOUND' USING ERRCODE='22023';
    END IF;
    IF observed_at >= deadline THEN
        RAISE EXCEPTION 'BUDGET_LINEAGE_EXPIRED' USING ERRCODE='22023';
    END IF;
    IF NOT EXISTS(SELECT 1 FROM cehub_ai.budget_activity_coverage
        WHERE tenant_id=wanted_tenant AND lineage_id=lid) THEN
        RAISE EXCEPTION 'BUDGET_ACTIVE_HISTORY_UNAVAILABLE' USING ERRCODE='22023';
    END IF;
    IF allowance IS NULL OR allowance <= 0 THEN
        RAISE EXCEPTION 'BUDGET_ACTIVE_PROFILE_INVALID' USING ERRCODE='22023';
    END IF;
    SELECT coalesce(sum(greatest(0,extract(epoch FROM
        (least(observed_at,stopped_at,lease_expires_at)-started_at)))),0) INTO used
      FROM cehub_ai.budget_activity_spans WHERE tenant_id=wanted_tenant AND lineage_id=lid;
    IF used >= allowance THEN
        RAISE EXCEPTION 'BUDGET_ACTIVE_TIME_EXHAUSTED' USING ERRCODE='22023';
    END IF;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.check_run_active_budget(uuid,uuid) FROM PUBLIC;

CREATE FUNCTION cehub_ai.check_finding_active_budget() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
BEGIN
    IF EXISTS(SELECT 1 FROM cehub_ai.budget_run_links
              WHERE tenant_id=NEW.tenant_id AND run_id=NEW.run_id) THEN
        PERFORM cehub_ai.check_run_active_budget(NEW.tenant_id,NEW.run_id);
    END IF;
    RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.check_finding_active_budget() FROM PUBLIC;
CREATE TRIGGER check_finding_active_budget BEFORE INSERT ON cehub_ai.findings
    FOR EACH ROW EXECUTE FUNCTION cehub_ai.check_finding_active_budget();
"""

AGENT_CHECK = r"""CREATE OR REPLACE FUNCTION cehub_ai.agent_check_active_budget()
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE scoped_run cehub_ai.agent_runs%ROWTYPE;
BEGIN
    SELECT * INTO scoped_run FROM cehub_ai.agent_runs
      WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid;
    IF NOT FOUND OR NOT cehub_ai.agent_scope_allows(scoped_run.tenant_id,scoped_run.project_id) THEN
        RAISE EXCEPTION 'Agent run lease is invalid' USING ERRCODE='42501';
    END IF;
    PERFORM cehub_ai.check_run_active_budget(scoped_run.tenant_id,scoped_run.id);
    RETURN '{}'::jsonb;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.agent_check_active_budget() FROM PUBLIC;
"""

# Immutable before/after admission bodies are appended below, independently of DBA files.
FUNCTIONS: list[tuple[str, str]] = [
    (
        r"""
CREATE OR REPLACE FUNCTION cehub_ai.reserve_run_budget(
    wanted_tenant uuid, wanted_run uuid, wanted_attempt uuid, wanted_kind text,
    wanted_input bigint, wanted_output bigint, caller_daily_limit bigint, binding jsonb
) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog AS $body$
DECLARE
    event_time timestamptz;
    day_start timestamptz;
    lineage cehub_ai.budget_lineages%ROWTYPE;
    prior cehub_ai.budget_journal%ROWTYPE;
    profile jsonb;
    field text;
    tokens bigint;
    own_used numeric;
    tenant_used numeric;
    own_busy boolean;
    occupied bigint;
    parallel_limit bigint;
    calls_used bigint;
    trace_tokens bigint;
    unresolved uuid[];
    current_daily_limit bigint;
    new_row cehub_ai.budget_journal%ROWTYPE;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('pdos-budget:' || wanted_tenant::text, 0));
    IF wanted_kind IS NULL OR wanted_kind NOT IN ('model','tool')
       OR wanted_input IS NULL OR wanted_output IS NULL
       OR wanted_input < 0 OR wanted_output < 0 OR wanted_input + wanted_output <= 0
       OR caller_daily_limit IS NULL OR caller_daily_limit <= 0 OR wanted_attempt IS NULL THEN
        RAISE EXCEPTION 'BUDGET_RESERVATION_INVALID' USING ERRCODE = '22023';
    END IF;
    PERFORM 1 FROM cehub_ai.agent_runs WHERE tenant_id = wanted_tenant AND id = wanted_run
      FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'BUDGET_RUN_SCOPE_INVALID' USING ERRCODE = '22023';
    END IF;
    SELECT l.* INTO lineage FROM cehub_ai.budget_lineages l
    JOIN cehub_ai.budget_run_links r ON r.tenant_id = l.tenant_id AND r.lineage_id = l.id
    WHERE r.tenant_id = wanted_tenant AND r.run_id = wanted_run;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'BUDGET_RUN_UNBOUND' USING ERRCODE = '22023';
    END IF;
    IF binding IS NOT NULL THEN
        IF wanted_kind <> 'model' OR jsonb_typeof(binding) IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'BUDGET_REQUEST_BINDING_INVALID' USING ERRCODE = '22023';
        END IF;
        IF (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(binding) key)
          IS DISTINCT FROM ARRAY['meter_version','model','model_call_id','output_limit',
            'output_parameter','protocol','provider','qualification_ref','qualified_output_limit',
            'qualified_window','request_digest','structured_attempt'] THEN
            RAISE EXCEPTION 'BUDGET_REQUEST_BINDING_INVALID' USING ERRCODE = '22023';
        END IF;
        FOREACH field IN ARRAY ARRAY['output_limit','qualified_output_limit',
            'qualified_window','structured_attempt'] LOOP
            IF jsonb_typeof(binding->field) IS DISTINCT FROM 'number'
               OR (binding->>field) !~ '^[1-9][0-9]{0,17}$' THEN
                RAISE EXCEPTION 'BUDGET_REQUEST_BINDING_INVALID' USING ERRCODE = '22023';
            END IF;
        END LOOP;
        FOREACH field IN ARRAY ARRAY['meter_version','model','model_call_id','output_parameter',
            'protocol','provider','qualification_ref','request_digest'] LOOP
            IF jsonb_typeof(binding->field) IS DISTINCT FROM 'string'
               OR btrim(binding->>field) = '' THEN
                RAISE EXCEPTION 'BUDGET_REQUEST_BINDING_INVALID' USING ERRCODE = '22023';
            END IF;
        END LOOP;
        IF binding->>'request_digest' !~ '^[a-f0-9]{64}$'
           OR binding->>'model_call_id' !~
             '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
           OR (binding->>'output_limit')::bigint <> wanted_output
           OR (binding->>'output_limit')::bigint > (binding->>'qualified_output_limit')::bigint
           OR (binding->>'structured_attempt')::bigint > 3
           OR binding->>'protocol' NOT IN ('openai-compatible','anthropic-native')
           OR binding->>'output_parameter' NOT IN ('max_tokens','max_completion_tokens')
           OR (binding->>'protocol' = 'anthropic-native'
               AND binding->>'output_parameter' <> 'max_tokens') THEN
            RAISE EXCEPTION 'BUDGET_REQUEST_BINDING_INVALID' USING ERRCODE = '22023';
        END IF;
    END IF;
    SELECT * INTO prior FROM cehub_ai.budget_journal
      WHERE tenant_id = wanted_tenant AND attempt_id = wanted_attempt
      ORDER BY revision DESC LIMIT 1;
    IF FOUND THEN
        IF prior.run_id IS DISTINCT FROM wanted_run OR prior.lineage_id <> lineage.id
           OR prior.call_kind <> wanted_kind OR prior.input_tokens <> wanted_input
           OR prior.output_tokens <> wanted_output OR prior.request_binding IS DISTINCT FROM binding
        THEN RAISE EXCEPTION 'BUDGET_ATTEMPT_CONFLICT' USING ERRCODE = '22023'; END IF;
        RETURN jsonb_build_object('row',to_jsonb(prior),'changed',false,'dispatch_granted',false);
    END IF;
    IF (SELECT mode FROM cehub_ai.model_call_mode_events WHERE tenant_id = wanted_tenant
        ORDER BY revision DESC LIMIT 1) = 'draining' THEN
        RAISE EXCEPTION 'BUDGET_ADMISSION_DRAINING' USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM cehub_ai.agent_runs
        WHERE id = wanted_run AND tenant_id = wanted_tenant AND status = 'running') THEN
        RAISE EXCEPTION 'BUDGET_RUN_NOT_RUNNING' USING ERRCODE = '22023';
    END IF;
    IF cehub_ai.model_calls_in_flight(wanted_tenant,'legacy') THEN
        RAISE EXCEPTION 'BUDGET_LEGACY_CALL_IN_FLIGHT' USING ERRCODE = '22023';
    END IF;
    SELECT daily_token_budget INTO current_daily_limit FROM cehub_ai.tenant_model_settings
      WHERE tenant_id = wanted_tenant FOR SHARE;
    event_time := clock_timestamp();
    IF event_time >= lineage.absolute_deadline THEN
        RAISE EXCEPTION 'BUDGET_LINEAGE_EXPIRED' USING ERRCODE = '22023';
    END IF;
    profile := lineage.profile;
    FOREACH field IN ARRAY ARRAY['input_token_limit','output_token_reserve',
        'lineage_token_limit','model_call_limit','tool_call_limit','tenant_parallel_lineages'] LOOP
        IF jsonb_typeof(profile->field) IS DISTINCT FROM 'number'
           OR (profile->>field) !~ '^[1-9][0-9]{0,17}$' THEN
            RAISE EXCEPTION 'BUDGET_PROFILE_INVALID' USING ERRCODE = '22023';
        END IF;
    END LOOP;
    IF profile->>'monetary_limit_microusd' IS NOT NULL THEN
        RAISE EXCEPTION 'BUDGET_MONETARY_ENFORCEMENT_UNAVAILABLE' USING ERRCODE = '22023';
    END IF;
    IF wanted_input > (profile->>'input_token_limit')::bigint
       OR wanted_output > (profile->>'output_token_reserve')::bigint THEN
        RAISE EXCEPTION 'BUDGET_CALL_TOKEN_LIMIT' USING ERRCODE = '22023';
    END IF;
    tokens := wanted_input + wanted_output;
    day_start := date_trunc('day',event_time AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    WITH latest AS (
        SELECT DISTINCT ON (attempt_id) * FROM cehub_ai.budget_journal
        WHERE tenant_id = wanted_tenant ORDER BY attempt_id, revision DESC
    ), occupied_lineages AS (
        SELECT DISTINCT lineage_id FROM latest WHERE reservation_status IN ('reserved','unknown')
    )
    SELECT coalesce(sum(coalesce(nullif(held_tokens,0),charged_tokens,0))
            FILTER (WHERE lineage_id = lineage.id),0),
        coalesce(sum(coalesce(nullif(held_tokens,0),charged_tokens,0))
            FILTER (WHERE held_tokens > 0 OR created_at >= day_start),0),
        coalesce(bool_or(lineage_id = lineage.id
            AND reservation_status IN ('reserved','unknown')),false),
        count(*) FILTER (WHERE lineage_id = lineage.id AND call_kind = wanted_kind
            AND reservation_status <> 'cancelled_before_dispatch'),
        (SELECT count(*) FROM occupied_lineages),
        least((profile->>'tenant_parallel_lineages')::bigint, coalesce((
            SELECT min((l.profile->>'tenant_parallel_lineages')::bigint)
            FROM cehub_ai.budget_lineages l JOIN occupied_lineages o ON o.lineage_id = l.id
            WHERE l.tenant_id = wanted_tenant
        ),(profile->>'tenant_parallel_lineages')::bigint))
    INTO own_used, tenant_used, own_busy, calls_used, occupied, parallel_limit FROM latest;
    IF own_busy THEN
        RAISE EXCEPTION 'BUDGET_LINEAGE_CALL_BUSY' USING ERRCODE = '22023';
    END IF;
    IF occupied >= parallel_limit THEN
        RAISE EXCEPTION 'BUDGET_TENANT_CALL_BUSY' USING ERRCODE = '22023';
    END IF;
    IF calls_used >= (profile->>(wanted_kind || '_call_limit'))::bigint THEN
        RAISE EXCEPTION 'BUDGET_CALL_COUNT_EXHAUSTED' USING ERRCODE = '22023';
    END IF;
    IF own_used + tokens > (profile->>'lineage_token_limit')::bigint THEN
        RAISE EXCEPTION 'BUDGET_LINEAGE_TOKENS_EXHAUSTED' USING ERRCODE = '22023';
    END IF;
    SELECT u.additional_tokens, u.unresolved_invocation_ids INTO trace_tokens, unresolved
      FROM cehub_ai.unbound_model_usage(wanted_tenant,event_time) u;
    IF cardinality(unresolved) > 0 THEN
        RAISE EXCEPTION 'BUDGET_LEGACY_USAGE_UNRESOLVED' USING ERRCODE = '22023';
    END IF;
    IF tenant_used + trace_tokens + tokens > least(caller_daily_limit,
        coalesce(current_daily_limit, caller_daily_limit)) THEN
        RAISE EXCEPTION 'BUDGET_TENANT_TOKENS_EXHAUSTED' USING ERRCODE = '22023';
    END IF;
    INSERT INTO cehub_ai.budget_journal (
        id,tenant_id,lineage_id,run_id,attempt_id,revision,call_kind,input_tokens,output_tokens,
        policy_version,reservation_status,reserved_tokens,held_tokens,price_status,
        request_binding,created_at
    ) VALUES (gen_random_uuid(),wanted_tenant,lineage.id,wanted_run,wanted_attempt,1,
        wanted_kind,wanted_input,wanted_output,profile->>'version','reserved',tokens,tokens,
        'unknown',binding,event_time) RETURNING * INTO new_row;
    RETURN jsonb_build_object('row',to_jsonb(new_row),'changed',true,'dispatch_granted',false);
END
$body$;
REVOKE ALL ON FUNCTION cehub_ai.reserve_run_budget(
    uuid,uuid,uuid,text,bigint,bigint,bigint,jsonb) FROM PUBLIC;
""",
        r"""
CREATE OR REPLACE FUNCTION cehub_ai.reserve_run_budget(
    wanted_tenant uuid, wanted_run uuid, wanted_attempt uuid, wanted_kind text,
    wanted_input bigint, wanted_output bigint, caller_daily_limit bigint, binding jsonb
) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog AS $body$
DECLARE
    event_time timestamptz;
    day_start timestamptz;
    lineage cehub_ai.budget_lineages%ROWTYPE;
    prior cehub_ai.budget_journal%ROWTYPE;
    profile jsonb;
    field text;
    tokens bigint;
    own_used numeric;
    tenant_used numeric;
    own_busy boolean;
    occupied bigint;
    parallel_limit bigint;
    calls_used bigint;
    trace_tokens bigint;
    unresolved uuid[];
    current_daily_limit bigint;
    new_row cehub_ai.budget_journal%ROWTYPE;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('pdos-budget:' || wanted_tenant::text, 0));
    IF wanted_kind IS NULL OR wanted_kind NOT IN ('model','tool')
       OR wanted_input IS NULL OR wanted_output IS NULL
       OR wanted_input < 0 OR wanted_output < 0 OR wanted_input + wanted_output <= 0
       OR caller_daily_limit IS NULL OR caller_daily_limit <= 0 OR wanted_attempt IS NULL THEN
        RAISE EXCEPTION 'BUDGET_RESERVATION_INVALID' USING ERRCODE = '22023';
    END IF;
    PERFORM 1 FROM cehub_ai.agent_runs WHERE tenant_id = wanted_tenant AND id = wanted_run
      FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'BUDGET_RUN_SCOPE_INVALID' USING ERRCODE = '22023';
    END IF;
    SELECT l.* INTO lineage FROM cehub_ai.budget_lineages l
    JOIN cehub_ai.budget_run_links r ON r.tenant_id = l.tenant_id AND r.lineage_id = l.id
    WHERE r.tenant_id = wanted_tenant AND r.run_id = wanted_run;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'BUDGET_RUN_UNBOUND' USING ERRCODE = '22023';
    END IF;
    IF binding IS NOT NULL THEN
        IF wanted_kind <> 'model' OR jsonb_typeof(binding) IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'BUDGET_REQUEST_BINDING_INVALID' USING ERRCODE = '22023';
        END IF;
        IF (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(binding) key)
          IS DISTINCT FROM ARRAY['meter_version','model','model_call_id','output_limit',
            'output_parameter','protocol','provider','qualification_ref','qualified_output_limit',
            'qualified_window','request_digest','structured_attempt'] THEN
            RAISE EXCEPTION 'BUDGET_REQUEST_BINDING_INVALID' USING ERRCODE = '22023';
        END IF;
        FOREACH field IN ARRAY ARRAY['output_limit','qualified_output_limit',
            'qualified_window','structured_attempt'] LOOP
            IF jsonb_typeof(binding->field) IS DISTINCT FROM 'number'
               OR (binding->>field) !~ '^[1-9][0-9]{0,17}$' THEN
                RAISE EXCEPTION 'BUDGET_REQUEST_BINDING_INVALID' USING ERRCODE = '22023';
            END IF;
        END LOOP;
        FOREACH field IN ARRAY ARRAY['meter_version','model','model_call_id','output_parameter',
            'protocol','provider','qualification_ref','request_digest'] LOOP
            IF jsonb_typeof(binding->field) IS DISTINCT FROM 'string'
               OR btrim(binding->>field) = '' THEN
                RAISE EXCEPTION 'BUDGET_REQUEST_BINDING_INVALID' USING ERRCODE = '22023';
            END IF;
        END LOOP;
        IF binding->>'request_digest' !~ '^[a-f0-9]{64}$'
           OR binding->>'model_call_id' !~
             '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
           OR (binding->>'output_limit')::bigint <> wanted_output
           OR (binding->>'output_limit')::bigint > (binding->>'qualified_output_limit')::bigint
           OR (binding->>'structured_attempt')::bigint > 3
           OR binding->>'protocol' NOT IN ('openai-compatible','anthropic-native')
           OR binding->>'output_parameter' NOT IN ('max_tokens','max_completion_tokens')
           OR (binding->>'protocol' = 'anthropic-native'
               AND binding->>'output_parameter' <> 'max_tokens') THEN
            RAISE EXCEPTION 'BUDGET_REQUEST_BINDING_INVALID' USING ERRCODE = '22023';
        END IF;
    END IF;
    SELECT * INTO prior FROM cehub_ai.budget_journal
      WHERE tenant_id = wanted_tenant AND attempt_id = wanted_attempt
      ORDER BY revision DESC LIMIT 1;
    IF FOUND THEN
        IF prior.run_id IS DISTINCT FROM wanted_run OR prior.lineage_id <> lineage.id
           OR prior.call_kind <> wanted_kind OR prior.input_tokens <> wanted_input
           OR prior.output_tokens <> wanted_output OR prior.request_binding IS DISTINCT FROM binding
        THEN RAISE EXCEPTION 'BUDGET_ATTEMPT_CONFLICT' USING ERRCODE = '22023'; END IF;
        RETURN jsonb_build_object('row',to_jsonb(prior),'changed',false,'dispatch_granted',false);
    END IF;
    IF (SELECT mode FROM cehub_ai.model_call_mode_events WHERE tenant_id = wanted_tenant
        ORDER BY revision DESC LIMIT 1) = 'draining' THEN
        RAISE EXCEPTION 'BUDGET_ADMISSION_DRAINING' USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM cehub_ai.agent_runs
        WHERE id = wanted_run AND tenant_id = wanted_tenant AND status = 'running') THEN
        RAISE EXCEPTION 'BUDGET_RUN_NOT_RUNNING' USING ERRCODE = '22023';
    END IF;
    IF cehub_ai.model_calls_in_flight(wanted_tenant,'legacy') THEN
        RAISE EXCEPTION 'BUDGET_LEGACY_CALL_IN_FLIGHT' USING ERRCODE = '22023';
    END IF;
    SELECT daily_token_budget INTO current_daily_limit FROM cehub_ai.tenant_model_settings
      WHERE tenant_id = wanted_tenant FOR SHARE;
    event_time := clock_timestamp();
    IF event_time >= lineage.absolute_deadline THEN
        RAISE EXCEPTION 'BUDGET_LINEAGE_EXPIRED' USING ERRCODE = '22023';
    END IF;
    PERFORM cehub_ai.check_run_active_budget(wanted_tenant,wanted_run);
    profile := lineage.profile;
    FOREACH field IN ARRAY ARRAY['input_token_limit','output_token_reserve',
        'lineage_token_limit','model_call_limit','tool_call_limit','tenant_parallel_lineages'] LOOP
        IF jsonb_typeof(profile->field) IS DISTINCT FROM 'number'
           OR (profile->>field) !~ '^[1-9][0-9]{0,17}$' THEN
            RAISE EXCEPTION 'BUDGET_PROFILE_INVALID' USING ERRCODE = '22023';
        END IF;
    END LOOP;
    IF profile->>'monetary_limit_microusd' IS NOT NULL THEN
        RAISE EXCEPTION 'BUDGET_MONETARY_ENFORCEMENT_UNAVAILABLE' USING ERRCODE = '22023';
    END IF;
    IF wanted_input > (profile->>'input_token_limit')::bigint
       OR wanted_output > (profile->>'output_token_reserve')::bigint THEN
        RAISE EXCEPTION 'BUDGET_CALL_TOKEN_LIMIT' USING ERRCODE = '22023';
    END IF;
    tokens := wanted_input + wanted_output;
    day_start := date_trunc('day',event_time AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    WITH latest AS (
        SELECT DISTINCT ON (attempt_id) * FROM cehub_ai.budget_journal
        WHERE tenant_id = wanted_tenant ORDER BY attempt_id, revision DESC
    ), occupied_lineages AS (
        SELECT DISTINCT lineage_id FROM latest WHERE reservation_status IN ('reserved','unknown')
    )
    SELECT coalesce(sum(coalesce(nullif(held_tokens,0),charged_tokens,0))
            FILTER (WHERE lineage_id = lineage.id),0),
        coalesce(sum(coalesce(nullif(held_tokens,0),charged_tokens,0))
            FILTER (WHERE held_tokens > 0 OR created_at >= day_start),0),
        coalesce(bool_or(lineage_id = lineage.id
            AND reservation_status IN ('reserved','unknown')),false),
        count(*) FILTER (WHERE lineage_id = lineage.id AND call_kind = wanted_kind
            AND reservation_status <> 'cancelled_before_dispatch'),
        (SELECT count(*) FROM occupied_lineages),
        least((profile->>'tenant_parallel_lineages')::bigint, coalesce((
            SELECT min((l.profile->>'tenant_parallel_lineages')::bigint)
            FROM cehub_ai.budget_lineages l JOIN occupied_lineages o ON o.lineage_id = l.id
            WHERE l.tenant_id = wanted_tenant
        ),(profile->>'tenant_parallel_lineages')::bigint))
    INTO own_used, tenant_used, own_busy, calls_used, occupied, parallel_limit FROM latest;
    IF own_busy THEN
        RAISE EXCEPTION 'BUDGET_LINEAGE_CALL_BUSY' USING ERRCODE = '22023';
    END IF;
    IF occupied >= parallel_limit THEN
        RAISE EXCEPTION 'BUDGET_TENANT_CALL_BUSY' USING ERRCODE = '22023';
    END IF;
    IF calls_used >= (profile->>(wanted_kind || '_call_limit'))::bigint THEN
        RAISE EXCEPTION 'BUDGET_CALL_COUNT_EXHAUSTED' USING ERRCODE = '22023';
    END IF;
    IF own_used + tokens > (profile->>'lineage_token_limit')::bigint THEN
        RAISE EXCEPTION 'BUDGET_LINEAGE_TOKENS_EXHAUSTED' USING ERRCODE = '22023';
    END IF;
    SELECT u.additional_tokens, u.unresolved_invocation_ids INTO trace_tokens, unresolved
      FROM cehub_ai.unbound_model_usage(wanted_tenant,event_time) u;
    IF cardinality(unresolved) > 0 THEN
        RAISE EXCEPTION 'BUDGET_LEGACY_USAGE_UNRESOLVED' USING ERRCODE = '22023';
    END IF;
    IF tenant_used + trace_tokens + tokens > least(caller_daily_limit,
        coalesce(current_daily_limit, caller_daily_limit)) THEN
        RAISE EXCEPTION 'BUDGET_TENANT_TOKENS_EXHAUSTED' USING ERRCODE = '22023';
    END IF;
    INSERT INTO cehub_ai.budget_journal (
        id,tenant_id,lineage_id,run_id,attempt_id,revision,call_kind,input_tokens,output_tokens,
        policy_version,reservation_status,reserved_tokens,held_tokens,price_status,
        request_binding,created_at
    ) VALUES (gen_random_uuid(),wanted_tenant,lineage.id,wanted_run,wanted_attempt,1,
        wanted_kind,wanted_input,wanted_output,profile->>'version','reserved',tokens,tokens,
        'unknown',binding,event_time) RETURNING * INTO new_row;
    RETURN jsonb_build_object('row',to_jsonb(new_row),'changed',true,'dispatch_granted',false);
END
$body$;
REVOKE ALL ON FUNCTION cehub_ai.reserve_run_budget(
    uuid,uuid,uuid,text,bigint,bigint,bigint,jsonb) FROM PUBLIC;
""",
    ),
    (
        r"""
CREATE OR REPLACE FUNCTION cehub_ai.transition_bound_model_budget(
    wanted_tenant uuid, wanted_run uuid, wanted_attempt uuid,
    wanted_action text, evidence_body text
) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog AS $body$
DECLARE
    prior cehub_ai.budget_journal%ROWTYPE;
    next_row cehub_ai.budget_journal%ROWTYPE;
    event_time timestamptz;
    evidence jsonb;
    evidence_ref text;
    field text;
    total bigint;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('pdos-budget:' || wanted_tenant::text, 0));
    event_time := clock_timestamp();
    IF wanted_action IS NULL OR wanted_action NOT IN ('dispatch', 'unknown', 'cancel', 'settle')
       OR (wanted_action <> 'settle' AND evidence_body IS NOT NULL) THEN
        RAISE EXCEPTION 'BUDGET_TRANSITION_INVALID' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO prior FROM cehub_ai.budget_journal
      WHERE tenant_id = wanted_tenant AND attempt_id = wanted_attempt
        AND run_id = wanted_run ORDER BY revision DESC LIMIT 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'BUDGET_ATTEMPT_NOT_FOUND' USING ERRCODE = '22023';
    END IF;
    IF prior.call_kind <> 'model' OR prior.request_binding IS NULL THEN
        RAISE EXCEPTION 'BUDGET_REQUEST_BINDING_REQUIRED' USING ERRCODE = '22023';
    END IF;
    next_row := prior;
    IF wanted_action = 'dispatch' THEN
        IF prior.dispatched_at IS NOT NULL THEN
            RETURN jsonb_build_object('row', to_jsonb(prior), 'changed', false,
                                      'dispatch_granted', false);
        END IF;
        IF prior.reservation_status <> 'reserved' THEN
            RAISE EXCEPTION 'BUDGET_TRANSITION_INVALID' USING ERRCODE = '22023';
        END IF;
        PERFORM 1 FROM cehub_ai.agent_runs
          WHERE tenant_id = wanted_tenant AND id = wanted_run AND status = 'running'
          FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'BUDGET_RUN_NOT_RUNNING' USING ERRCODE = '22023';
        END IF;
        -- Waiting for the run row must not preserve an earlier valid deadline.
        event_time := clock_timestamp();
        PERFORM 1 FROM cehub_ai.budget_lineages
          WHERE tenant_id = wanted_tenant AND id = prior.lineage_id
            AND absolute_deadline > event_time;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'BUDGET_LINEAGE_EXPIRED' USING ERRCODE = '22023';
        END IF;
        next_row.dispatched_at := event_time;
    ELSIF wanted_action = 'unknown' THEN
        IF prior.reservation_status = 'unknown' THEN
            RETURN jsonb_build_object('row', to_jsonb(prior), 'changed', false,
                                      'dispatch_granted', false);
        END IF;
        IF prior.reservation_status <> 'reserved' OR prior.dispatched_at IS NULL THEN
            RAISE EXCEPTION 'BUDGET_TRANSITION_INVALID' USING ERRCODE = '22023';
        END IF;
        next_row.reservation_status := 'unknown';
    ELSIF wanted_action = 'cancel' THEN
        IF prior.reservation_status = 'cancelled_before_dispatch' THEN
            RETURN jsonb_build_object('row', to_jsonb(prior), 'changed', false,
                                      'dispatch_granted', false);
        END IF;
        IF prior.reservation_status <> 'reserved' OR prior.dispatched_at IS NOT NULL THEN
            RAISE EXCEPTION 'BUDGET_TRANSITION_INVALID' USING ERRCODE = '22023';
        END IF;
        next_row.reservation_status := 'cancelled_before_dispatch';
        next_row.held_tokens := 0;
        next_row.charged_tokens := 0;
    ELSE
        IF evidence_body IS NULL OR octet_length(evidence_body) > 64000 THEN
            RAISE EXCEPTION 'BUDGET_SETTLEMENT_EVIDENCE_REQUIRED' USING ERRCODE = '22023';
        END IF;
        BEGIN
            evidence := evidence_body::jsonb;
        EXCEPTION WHEN invalid_text_representation THEN
            RAISE EXCEPTION 'BUDGET_SETTLEMENT_EVIDENCE_CONFLICT' USING ERRCODE = '22023';
        END;
        IF jsonb_typeof(evidence) IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'BUDGET_SETTLEMENT_EVIDENCE_CONFLICT' USING ERRCODE = '22023';
        END IF;
        IF (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(evidence) key)
            IS DISTINCT FROM ARRAY['cache_creation_tokens','cache_read_tokens','error_code',
                 'input_tokens','model_version','output_tokens','request_digest','request_id']
            OR evidence->>'request_digest' IS DISTINCT FROM prior.request_binding->>'request_digest'
        THEN
            RAISE EXCEPTION 'BUDGET_SETTLEMENT_EVIDENCE_CONFLICT' USING ERRCODE = '22023';
        END IF;
        FOREACH field IN ARRAY ARRAY['input_tokens','output_tokens',
            'cache_read_tokens','cache_creation_tokens'] LOOP
            IF jsonb_typeof(evidence->field) IS DISTINCT FROM 'number'
               OR (evidence->>field) !~ '^[0-9]{1,18}$' THEN
                RAISE EXCEPTION 'BUDGET_SETTLEMENT_EVIDENCE_CONFLICT' USING ERRCODE = '22023';
            END IF;
        END LOOP;
        FOREACH field IN ARRAY ARRAY['request_id','model_version','error_code'] LOOP
            IF jsonb_typeof(evidence->field) NOT IN ('string', 'null') THEN
                RAISE EXCEPTION 'BUDGET_SETTLEMENT_EVIDENCE_CONFLICT' USING ERRCODE = '22023';
            END IF;
        END LOOP;
        IF (evidence->>'cache_read_tokens')::bigint + (evidence->>'cache_creation_tokens')::bigint
            > (evidence->>'input_tokens')::bigint THEN
            RAISE EXCEPTION 'BUDGET_SETTLEMENT_EVIDENCE_CONFLICT' USING ERRCODE = '22023';
        END IF;
        total := (evidence->>'input_tokens')::bigint + (evidence->>'output_tokens')::bigint;
        evidence_ref := 'provider-usage.v1:sha256:' ||
            encode(sha256(convert_to(evidence_body, 'UTF8')), 'hex');
        IF prior.reservation_status = 'settled' THEN
            IF prior.usage_evidence IS DISTINCT FROM evidence THEN
                RAISE EXCEPTION 'BUDGET_SETTLEMENT_CONFLICT' USING ERRCODE = '22023';
            END IF;
            RETURN jsonb_build_object('row', to_jsonb(prior), 'changed', false,
                                      'dispatch_granted', false);
        END IF;
        IF prior.dispatched_at IS NULL
           OR prior.reservation_status NOT IN ('reserved', 'unknown') THEN
            RAISE EXCEPTION 'BUDGET_TRANSITION_INVALID' USING ERRCODE = '22023';
        END IF;
        next_row.reservation_status := 'settled';
        next_row.charged_tokens := total;
        next_row.held_tokens := 0;
        next_row.reconciliation_ref := evidence_ref;
        next_row.provider_request_id := evidence->>'request_id';
        next_row.usage_evidence := evidence;
    END IF;
    next_row.id := gen_random_uuid();
    next_row.revision := prior.revision + 1;
    next_row.created_at := event_time;
    INSERT INTO cehub_ai.budget_journal SELECT next_row.*;
    RETURN jsonb_build_object('row', to_jsonb(next_row), 'changed', true,
                              'dispatch_granted', wanted_action = 'dispatch');
END
$body$;
REVOKE ALL ON FUNCTION
    cehub_ai.transition_bound_model_budget(uuid, uuid, uuid, text, text) FROM PUBLIC;
""",
        r"""
CREATE OR REPLACE FUNCTION cehub_ai.transition_bound_model_budget(
    wanted_tenant uuid, wanted_run uuid, wanted_attempt uuid,
    wanted_action text, evidence_body text
) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog AS $body$
DECLARE
    prior cehub_ai.budget_journal%ROWTYPE;
    next_row cehub_ai.budget_journal%ROWTYPE;
    event_time timestamptz;
    evidence jsonb;
    evidence_ref text;
    field text;
    total bigint;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('pdos-budget:' || wanted_tenant::text, 0));
    event_time := clock_timestamp();
    IF wanted_action IS NULL OR wanted_action NOT IN ('dispatch', 'unknown', 'cancel', 'settle')
       OR (wanted_action <> 'settle' AND evidence_body IS NOT NULL) THEN
        RAISE EXCEPTION 'BUDGET_TRANSITION_INVALID' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO prior FROM cehub_ai.budget_journal
      WHERE tenant_id = wanted_tenant AND attempt_id = wanted_attempt
        AND run_id = wanted_run ORDER BY revision DESC LIMIT 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'BUDGET_ATTEMPT_NOT_FOUND' USING ERRCODE = '22023';
    END IF;
    IF prior.call_kind <> 'model' OR prior.request_binding IS NULL THEN
        RAISE EXCEPTION 'BUDGET_REQUEST_BINDING_REQUIRED' USING ERRCODE = '22023';
    END IF;
    next_row := prior;
    IF wanted_action = 'dispatch' THEN
        IF prior.dispatched_at IS NOT NULL THEN
            RETURN jsonb_build_object('row', to_jsonb(prior), 'changed', false,
                                      'dispatch_granted', false);
        END IF;
        IF prior.reservation_status <> 'reserved' THEN
            RAISE EXCEPTION 'BUDGET_TRANSITION_INVALID' USING ERRCODE = '22023';
        END IF;
        PERFORM 1 FROM cehub_ai.agent_runs
          WHERE tenant_id = wanted_tenant AND id = wanted_run AND status = 'running'
          FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'BUDGET_RUN_NOT_RUNNING' USING ERRCODE = '22023';
        END IF;
        -- Waiting for the run row must not preserve an earlier valid deadline.
        event_time := clock_timestamp();
        PERFORM 1 FROM cehub_ai.budget_lineages
          WHERE tenant_id = wanted_tenant AND id = prior.lineage_id
            AND absolute_deadline > event_time;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'BUDGET_LINEAGE_EXPIRED' USING ERRCODE = '22023';
        END IF;
    PERFORM cehub_ai.check_run_active_budget(wanted_tenant,wanted_run);
        next_row.dispatched_at := event_time;
    ELSIF wanted_action = 'unknown' THEN
        IF prior.reservation_status = 'unknown' THEN
            RETURN jsonb_build_object('row', to_jsonb(prior), 'changed', false,
                                      'dispatch_granted', false);
        END IF;
        IF prior.reservation_status <> 'reserved' OR prior.dispatched_at IS NULL THEN
            RAISE EXCEPTION 'BUDGET_TRANSITION_INVALID' USING ERRCODE = '22023';
        END IF;
        next_row.reservation_status := 'unknown';
    ELSIF wanted_action = 'cancel' THEN
        IF prior.reservation_status = 'cancelled_before_dispatch' THEN
            RETURN jsonb_build_object('row', to_jsonb(prior), 'changed', false,
                                      'dispatch_granted', false);
        END IF;
        IF prior.reservation_status <> 'reserved' OR prior.dispatched_at IS NOT NULL THEN
            RAISE EXCEPTION 'BUDGET_TRANSITION_INVALID' USING ERRCODE = '22023';
        END IF;
        next_row.reservation_status := 'cancelled_before_dispatch';
        next_row.held_tokens := 0;
        next_row.charged_tokens := 0;
    ELSE
        IF evidence_body IS NULL OR octet_length(evidence_body) > 64000 THEN
            RAISE EXCEPTION 'BUDGET_SETTLEMENT_EVIDENCE_REQUIRED' USING ERRCODE = '22023';
        END IF;
        BEGIN
            evidence := evidence_body::jsonb;
        EXCEPTION WHEN invalid_text_representation THEN
            RAISE EXCEPTION 'BUDGET_SETTLEMENT_EVIDENCE_CONFLICT' USING ERRCODE = '22023';
        END;
        IF jsonb_typeof(evidence) IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'BUDGET_SETTLEMENT_EVIDENCE_CONFLICT' USING ERRCODE = '22023';
        END IF;
        IF (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(evidence) key)
            IS DISTINCT FROM ARRAY['cache_creation_tokens','cache_read_tokens','error_code',
                 'input_tokens','model_version','output_tokens','request_digest','request_id']
            OR evidence->>'request_digest' IS DISTINCT FROM prior.request_binding->>'request_digest'
        THEN
            RAISE EXCEPTION 'BUDGET_SETTLEMENT_EVIDENCE_CONFLICT' USING ERRCODE = '22023';
        END IF;
        FOREACH field IN ARRAY ARRAY['input_tokens','output_tokens',
            'cache_read_tokens','cache_creation_tokens'] LOOP
            IF jsonb_typeof(evidence->field) IS DISTINCT FROM 'number'
               OR (evidence->>field) !~ '^[0-9]{1,18}$' THEN
                RAISE EXCEPTION 'BUDGET_SETTLEMENT_EVIDENCE_CONFLICT' USING ERRCODE = '22023';
            END IF;
        END LOOP;
        FOREACH field IN ARRAY ARRAY['request_id','model_version','error_code'] LOOP
            IF jsonb_typeof(evidence->field) NOT IN ('string', 'null') THEN
                RAISE EXCEPTION 'BUDGET_SETTLEMENT_EVIDENCE_CONFLICT' USING ERRCODE = '22023';
            END IF;
        END LOOP;
        IF (evidence->>'cache_read_tokens')::bigint + (evidence->>'cache_creation_tokens')::bigint
            > (evidence->>'input_tokens')::bigint THEN
            RAISE EXCEPTION 'BUDGET_SETTLEMENT_EVIDENCE_CONFLICT' USING ERRCODE = '22023';
        END IF;
        total := (evidence->>'input_tokens')::bigint + (evidence->>'output_tokens')::bigint;
        evidence_ref := 'provider-usage.v1:sha256:' ||
            encode(sha256(convert_to(evidence_body, 'UTF8')), 'hex');
        IF prior.reservation_status = 'settled' THEN
            IF prior.usage_evidence IS DISTINCT FROM evidence THEN
                RAISE EXCEPTION 'BUDGET_SETTLEMENT_CONFLICT' USING ERRCODE = '22023';
            END IF;
            RETURN jsonb_build_object('row', to_jsonb(prior), 'changed', false,
                                      'dispatch_granted', false);
        END IF;
        IF prior.dispatched_at IS NULL
           OR prior.reservation_status NOT IN ('reserved', 'unknown') THEN
            RAISE EXCEPTION 'BUDGET_TRANSITION_INVALID' USING ERRCODE = '22023';
        END IF;
        next_row.reservation_status := 'settled';
        next_row.charged_tokens := total;
        next_row.held_tokens := 0;
        next_row.reconciliation_ref := evidence_ref;
        next_row.provider_request_id := evidence->>'request_id';
        next_row.usage_evidence := evidence;
    END IF;
    next_row.id := gen_random_uuid();
    next_row.revision := prior.revision + 1;
    next_row.created_at := event_time;
    INSERT INTO cehub_ai.budget_journal SELECT next_row.*;
    RETURN jsonb_build_object('row', to_jsonb(next_row), 'changed', true,
                              'dispatch_granted', wanted_action = 'dispatch');
END
$body$;
REVOKE ALL ON FUNCTION
    cehub_ai.transition_bound_model_budget(uuid, uuid, uuid, text, text) FROM PUBLIC;
""",
    ),
]


def upgrade() -> None:
    op.execute(SCHEMA)
    for _, current in FUNCTIONS:
        op.get_bind().exec_driver_sql(current, execution_options={"no_parameters": True})
    op.execute(AGENT_CHECK)
    op.execute("""DO $body$ BEGIN
      IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_agent') THEN
        GRANT EXECUTE ON FUNCTION cehub_ai.agent_check_active_budget() TO pdos_agent;
      END IF;
    END $body$;""")


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN
      IF EXISTS(SELECT 1 FROM cehub_ai.budget_activity_spans) THEN
        RAISE EXCEPTION 'cannot remove active accounting with % or %',
            'running lease history', 'persistent budget history';
      END IF;
    END $body$;""")
    for previous, _ in FUNCTIONS:
        op.get_bind().exec_driver_sql(previous, execution_options={"no_parameters": True})
    op.execute("DROP FUNCTION IF EXISTS cehub_ai.agent_check_active_budget()")
    op.execute("DROP TRIGGER IF EXISTS check_finding_active_budget ON cehub_ai.findings")
    op.execute("DROP FUNCTION IF EXISTS cehub_ai.check_finding_active_budget()")
    op.execute("DROP FUNCTION cehub_ai.check_run_active_budget(uuid,uuid)")
    op.execute("DROP TRIGGER track_run_activity ON cehub_ai.agent_runs")
    op.execute("DROP TRIGGER track_link_activity ON cehub_ai.budget_run_links")
    op.execute("DROP TRIGGER start_activity_coverage ON cehub_ai.budget_lineages")
    op.execute("DROP FUNCTION cehub_ai.track_run_activity()")
    op.execute("DROP FUNCTION cehub_ai.sync_run_activity(uuid,uuid)")
    op.execute("DROP FUNCTION cehub_ai.start_activity_coverage()")
    op.execute("DROP TABLE cehub_ai.budget_activity_spans")
    op.execute("DROP TABLE cehub_ai.budget_activity_coverage")
    op.execute("DROP FUNCTION cehub_ai.protect_activity_history()")
