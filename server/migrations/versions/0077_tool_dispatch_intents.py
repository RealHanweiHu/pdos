"""Durable tool intent, single dispatch and cumulative pre-handler call admission."""

from collections.abc import Sequence

from alembic import op

revision: str = "0077_tool_dispatch_intents"
down_revision: str | Sequence[str] | None = "0076_tool_observation_receipts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = r"""
CREATE TABLE cehub_ai.agent_tool_accounting_epochs (
 id integer PRIMARY KEY,activated_at timestamptz NOT NULL,
 CONSTRAINT ck_agent_tool_accounting_epochs_singleton CHECK(id=1)
);
INSERT INTO cehub_ai.agent_tool_accounting_epochs VALUES(1,clock_timestamp());
CREATE TRIGGER protect_tool_epoch BEFORE UPDATE OR DELETE ON cehub_ai.agent_tool_accounting_epochs
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_ai.agent_tool_accounting_epochs FROM PUBLIC;
CREATE TABLE cehub_ai.agent_tool_intents (
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL,run_id uuid NOT NULL,lineage_id uuid,
 call_key varchar(128) NOT NULL,tool_key varchar(64) NOT NULL,input_body jsonb NOT NULL,
 created_at timestamptz NOT NULL,
 CONSTRAINT uq_tool_intent_scope UNIQUE(tenant_id,run_id,id),
 CONSTRAINT uq_tool_intent_call UNIQUE(tenant_id,run_id,call_key),
 FOREIGN KEY(tenant_id,run_id) REFERENCES cehub_ai.agent_runs(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,lineage_id,run_id)
  REFERENCES cehub_ai.budget_run_links(tenant_id,lineage_id,run_id) ON DELETE RESTRICT,
 CONSTRAINT ck_agent_tool_intents_shape CHECK(btrim(call_key)<>'' AND btrim(tool_key)<>''
  AND jsonb_typeof(input_body)='object')
);
CREATE INDEX ix_tool_intent_lineage ON cehub_ai.agent_tool_intents(tenant_id,lineage_id);
CREATE TABLE cehub_ai.agent_tool_dispatches (
 intent_id uuid PRIMARY KEY,tenant_id uuid NOT NULL,run_id uuid NOT NULL,
 lease_token uuid NOT NULL,created_at timestamptz NOT NULL,
 FOREIGN KEY(tenant_id,run_id,intent_id)
  REFERENCES cehub_ai.agent_tool_intents(tenant_id,run_id,id) ON DELETE RESTRICT
);
ALTER TABLE cehub_ai.agent_tool_observations ADD COLUMN tool_intent_id uuid,
 ADD CONSTRAINT fk_observation_tool_intent FOREIGN KEY(tenant_id,run_id,tool_intent_id)
 REFERENCES cehub_ai.agent_tool_intents(tenant_id,run_id,id) ON DELETE RESTRICT;
CREATE TRIGGER protect_tool_intent BEFORE UPDATE OR DELETE ON cehub_ai.agent_tool_intents
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
CREATE TRIGGER protect_tool_dispatch BEFORE UPDATE OR DELETE ON cehub_ai.agent_tool_dispatches
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_ai.agent_tool_intents,cehub_ai.agent_tool_dispatches FROM PUBLIC;
"""

PORTS = r"""CREATE OR REPLACE FUNCTION cehub_ai.tool_intent_call_count(
 wanted_tenant uuid,wanted_lineage uuid
) RETURNS bigint LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $body$
DECLARE cutoff timestamptz;
BEGIN
 SELECT activated_at INTO cutoff FROM cehub_ai.agent_tool_accounting_epochs WHERE id=1;
 IF cutoff IS NULL OR EXISTS(SELECT 1 FROM cehub_ai.budget_run_links b
   JOIN cehub_ai.agent_runs r ON r.tenant_id=b.tenant_id AND r.id=b.run_id
   WHERE b.tenant_id=wanted_tenant AND b.lineage_id=wanted_lineage AND r.started_at<cutoff)
  OR EXISTS(SELECT 1 FROM cehub_ai.budget_activity_spans
    WHERE tenant_id=wanted_tenant AND lineage_id=wanted_lineage AND started_at<cutoff)
  OR EXISTS(SELECT 1 FROM cehub_ai.agent_tool_observations o
    JOIN cehub_ai.budget_run_links b ON b.tenant_id=o.tenant_id AND b.run_id=o.run_id
    WHERE b.tenant_id=wanted_tenant AND b.lineage_id=wanted_lineage AND o.created_at<cutoff) THEN
  RAISE EXCEPTION 'BUDGET_TOOL_HISTORY_UNAVAILABLE' USING ERRCODE='22023';
 END IF;
 RETURN (SELECT count(*) FROM cehub_ai.agent_tool_intents i
   JOIN cehub_ai.budget_run_links b ON b.tenant_id=i.tenant_id AND b.run_id=i.run_id
   WHERE b.tenant_id=wanted_tenant AND b.lineage_id=wanted_lineage)
  + (SELECT count(*) FROM cehub_ai.agent_tool_observations o
     JOIN cehub_ai.budget_run_links b ON b.tenant_id=o.tenant_id AND b.run_id=o.run_id
     WHERE b.tenant_id=wanted_tenant AND b.lineage_id=wanted_lineage
       AND o.tool_intent_id IS NULL);
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.tool_intent_call_count(uuid,uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.prepare_agent_tool_call(
 wanted_call uuid,wanted_key varchar,wanted_tool varchar,input_text text
) RETURNS uuid LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; old cehub_ai.agent_tool_intents%ROWTYPE;
 lineage cehub_ai.budget_lineages%ROWTYPE; args jsonb; used bigint; allowance bigint;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent tool lease is invalid' USING ERRCODE='42501';
 END IF;
 -- Same order as model admission: tenant budget lock, then the run row.
 PERFORM pg_advisory_xact_lock(hashtextextended('pdos-budget:' || r.tenant_id::text,0));
 PERFORM 1 FROM cehub_ai.agent_runs WHERE id=r.id FOR UPDATE;
 IF NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent tool lease expired' USING ERRCODE='42501';
 END IF;
 IF wanted_call IS NULL OR wanted_key IS NULL OR length(wanted_key) NOT BETWEEN 1 AND 128
  OR btrim(wanted_key)='' OR input_text IS NULL OR octet_length(input_text)>65536 THEN
  RAISE EXCEPTION 'AGENT_TOOL_INTENT_INVALID' USING ERRCODE='22023';
 END IF;
 IF (wanted_tool IN ('get_project_context','get_recent_events','search_memory') OR
  wanted_tool='get_engineering_evidence' AND r.agent_key='engineering_intelligence' OR
  wanted_tool='get_quality_evidence' AND r.agent_key='quality_intelligence' OR
  wanted_tool='get_supplier_delay_evidence' AND r.agent_key='supplier_intelligence' OR
  wanted_tool='get_portfolio_brief' AND r.agent_key='executive_intelligence') IS NOT TRUE THEN
  RAISE EXCEPTION 'AGENT_TOOL_INTENT_TOOL_INVALID' USING ERRCODE='22023';
 END IF;
 args:=input_text::jsonb;
 IF jsonb_typeof(args) IS DISTINCT FROM 'object'
   OR args->>'project_id' IS DISTINCT FROM r.project_id::text THEN
  RAISE EXCEPTION 'AGENT_TOOL_INTENT_SCOPE' USING ERRCODE='22023';
 END IF;
 SELECT * INTO old FROM cehub_ai.agent_tool_intents
  WHERE tenant_id=r.tenant_id AND run_id=r.id AND call_key=wanted_key;
 IF FOUND THEN
  IF old.id IS DISTINCT FROM wanted_call OR old.tool_key IS DISTINCT FROM wanted_tool
    OR old.input_body IS DISTINCT FROM args THEN
   RAISE EXCEPTION 'AGENT_TOOL_INTENT_CONFLICT' USING ERRCODE='22023';
  END IF;
  RETURN old.id;
 END IF;
 IF EXISTS(SELECT 1 FROM cehub_ai.agent_tool_observations
    WHERE tenant_id=r.tenant_id AND run_id=r.id AND call_key=wanted_key) THEN
  RAISE EXCEPTION 'AGENT_TOOL_HISTORICAL_CALL' USING ERRCODE='22023';
 END IF;
 SELECT l.* INTO lineage FROM cehub_ai.budget_lineages l
  JOIN cehub_ai.budget_run_links b ON b.tenant_id=l.tenant_id AND b.lineage_id=l.id
  WHERE b.tenant_id=r.tenant_id AND b.run_id=r.id;
 IF lineage.id IS NOT NULL THEN
  PERFORM cehub_ai.check_run_active_budget(r.tenant_id,r.id);
  allowance:=(lineage.profile->>'tool_call_limit')::bigint;
  IF allowance IS NULL OR allowance<1 THEN
   RAISE EXCEPTION 'BUDGET_TOOL_PROFILE_INVALID' USING ERRCODE='22023';
  END IF;
  SELECT count(*) INTO used FROM (
   SELECT DISTINCT ON(attempt_id) reservation_status FROM cehub_ai.budget_journal
    WHERE tenant_id=r.tenant_id AND lineage_id=lineage.id AND call_kind='tool'
    ORDER BY attempt_id,revision DESC) latest WHERE reservation_status<>'cancelled_before_dispatch';
  used:=used+cehub_ai.tool_intent_call_count(r.tenant_id,lineage.id);
  IF used>=allowance THEN
   RAISE EXCEPTION 'BUDGET_TOOL_CALL_COUNT_EXHAUSTED' USING ERRCODE='22023';
  END IF;
 END IF;
 IF NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent tool lease expired' USING ERRCODE='42501';
 END IF;
 INSERT INTO cehub_ai.agent_tool_intents VALUES(wanted_call,r.tenant_id,r.id,lineage.id,
   wanted_key,wanted_tool,args,clock_timestamp());
 RETURN wanted_call;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.prepare_agent_tool_call(uuid,varchar,varchar,text) FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.dispatch_agent_tool_call(wanted_call uuid)
RETURNS void LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; intent cehub_ai.agent_tool_intents%ROWTYPE;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid FOR UPDATE;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent tool dispatch lease is invalid' USING ERRCODE='42501';
 END IF;
 SELECT * INTO intent FROM cehub_ai.agent_tool_intents
  WHERE id=wanted_call AND tenant_id=r.tenant_id AND run_id=r.id;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'AGENT_TOOL_INTENT_MISSING' USING ERRCODE='22023';
 END IF;
 IF EXISTS(SELECT 1 FROM cehub_ai.agent_tool_dispatches WHERE intent_id=wanted_call) THEN
  RAISE EXCEPTION 'AGENT_TOOL_ALREADY_DISPATCHED' USING ERRCODE='22023';
 END IF;
 IF EXISTS(SELECT 1 FROM cehub_ai.budget_run_links b
    WHERE b.tenant_id=r.tenant_id AND b.run_id=r.id) THEN
  PERFORM cehub_ai.check_run_active_budget(r.tenant_id,r.id);
  PERFORM cehub_ai.tool_intent_call_count(r.tenant_id,b.lineage_id)
    FROM cehub_ai.budget_run_links b WHERE b.tenant_id=r.tenant_id AND b.run_id=r.id;
 END IF;
 IF NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent tool dispatch lease expired' USING ERRCODE='42501';
 END IF;
 INSERT INTO cehub_ai.agent_tool_dispatches VALUES(wanted_call,r.tenant_id,r.id,token,
   clock_timestamp());
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.dispatch_agent_tool_call(uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.require_tool_dispatch_receipt()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE intent cehub_ai.agent_tool_intents%ROWTYPE;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT i.* INTO intent FROM cehub_ai.agent_tool_intents i
  JOIN cehub_ai.agent_tool_dispatches d ON d.intent_id=i.id
  WHERE i.tenant_id=NEW.tenant_id AND i.run_id=NEW.run_id AND i.call_key=NEW.call_key
    AND d.lease_token=token;
 IF NOT FOUND OR intent.tool_key IS DISTINCT FROM NEW.tool_key
    OR intent.input_body IS DISTINCT FROM NEW.input_body
    OR NEW.metadata->>'tool_call_id' IS DISTINCT FROM intent.id::text THEN
  RAISE EXCEPTION 'AGENT_TOOL_DISPATCH_RECEIPT_MISMATCH' USING ERRCODE='22023';
 END IF;
 NEW.tool_intent_id:=intent.id;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.require_tool_dispatch_receipt() FROM PUBLIC;
"""

# Frozen before/after function bodies follow; never load historical code at migration time.

OLD_RESERVE = r"""
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
"""

RESERVE = r"""
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
    IF wanted_kind='tool' THEN
        calls_used:=calls_used+cehub_ai.tool_intent_call_count(wanted_tenant,lineage.id);
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
"""

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
        ELSIF EXISTS(SELECT 1 FROM cehub_ai.agent_tool_dispatches d
            WHERE d.tenant_id=r.tenant_id AND d.run_id=r.id
              AND NOT EXISTS(SELECT 1 FROM cehub_ai.agent_tool_observations o
                WHERE o.tenant_id=d.tenant_id AND o.run_id=d.run_id
                  AND o.tool_intent_id=d.intent_id)) THEN
            stop_reason := 'AGENT_TOOL_RECEIPT_UNKNOWN';
        ELSIF r.dispatch_deadline <= clock_timestamp() THEN
            stop_reason := 'AGENT_TRIGGER_DEADLINE_EXCEEDED';
        ELSIF checkpoint.id IS NULL THEN
            IF EXISTS(SELECT 1 FROM cehub_ai.agent_tool_intents i
                WHERE i.tenant_id=r.tenant_id AND i.run_id=r.id
                  AND NOT EXISTS(SELECT 1 FROM cehub_ai.agent_tool_dispatches d
                    WHERE d.intent_id=i.id)) THEN
                stop_reason := 'AGENT_TOOL_NOT_DISPATCHED';
            ELSE
                stop_reason := 'AGENT_CHECKPOINT_MISSING';
            END IF;
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
    op.execute(RESERVE)
    op.execute(RECOVER)
    op.execute("""CREATE TRIGGER require_tool_dispatch_receipt BEFORE INSERT
      ON cehub_ai.agent_tool_observations FOR EACH ROW
      EXECUTE FUNCTION cehub_ai.require_tool_dispatch_receipt();""")
    op.execute("""DO $body$ BEGIN
      IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_agent') THEN
        GRANT EXECUTE ON FUNCTION cehub_ai.prepare_agent_tool_call(uuid,varchar,varchar,text),
          cehub_ai.dispatch_agent_tool_call(uuid) TO pdos_agent;
      END IF;
    END $body$;""")


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN
      IF EXISTS(SELECT 1 FROM cehub_ai.agent_tool_intents) THEN
        RAISE EXCEPTION 'cannot remove persistent tool intent history';
      END IF;
    END $body$;""")
    op.execute(OLD_RESERVE)
    op.execute(OLD_RECOVER)
    op.execute("DROP TRIGGER require_tool_dispatch_receipt ON cehub_ai.agent_tool_observations")
    op.execute("DROP FUNCTION IF EXISTS cehub_ai.require_tool_dispatch_receipt()")
    op.execute("DROP FUNCTION IF EXISTS cehub_ai.dispatch_agent_tool_call(uuid)")
    op.execute(
        "DROP FUNCTION IF EXISTS cehub_ai.prepare_agent_tool_call(uuid,varchar,varchar,text)"
    )
    op.execute("DROP FUNCTION IF EXISTS cehub_ai.tool_intent_call_count(uuid,uuid)")
    op.execute("ALTER TABLE cehub_ai.agent_tool_observations DROP COLUMN tool_intent_id")
    op.execute("DROP TABLE cehub_ai.agent_tool_dispatches")
    op.execute("DROP TABLE cehub_ai.agent_tool_intents")
    op.execute("DROP TABLE cehub_ai.agent_tool_accounting_epochs")
