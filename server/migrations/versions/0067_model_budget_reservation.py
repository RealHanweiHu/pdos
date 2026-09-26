"""Common atomic budget admission and private trace accounting for scoped ports."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0067_model_budget_reservation"
down_revision: str | Sequence[str] | None = "0066_bound_budget_transition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = r"""
CREATE FUNCTION cehub_ai.unbound_model_usage(wanted_tenant uuid, observed_at timestamptz)
RETURNS TABLE(additional_tokens bigint, unresolved_invocation_ids uuid[])
LANGUAGE sql STABLE SET search_path = pg_catalog AS $body$
WITH boundary AS (
    SELECT date_trunc('day', observed_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' AS day
), latest AS (
    SELECT DISTINCT ON (attempt_id) * FROM cehub_ai.budget_journal
    WHERE tenant_id = wanted_tenant ORDER BY attempt_id, revision DESC
), resolutions AS (
    SELECT DISTINCT ON (invocation_id) * FROM cehub_ai.legacy_usage_resolutions
    WHERE tenant_id = wanted_tenant ORDER BY invocation_id, revision DESC
), traces AS (
    SELECT t.*, r.id AS resolution_id, r.input_tokens + r.output_tokens AS resolved_tokens
    FROM cehub_ai.model_invocations t LEFT JOIN resolutions r ON r.invocation_id = t.id
    CROSS JOIN boundary b WHERE t.tenant_id = wanted_tenant AND (
        r.created_at >= b.day OR (r.id IS NULL AND (
            t.created_at >= b.day OR t.usage_status NOT IN ('known', 'not_invoked')
            OR t.budget_call_id::text IN (
                SELECT request_binding->>'model_call_id' FROM latest
                WHERE reservation_status IN ('reserved', 'unknown')
            )
        ))
    )
), coverage AS (
    SELECT run_id, request_binding->>'model_call_id' AS call_id,
        sum(coalesce(nullif(held_tokens, 0), charged_tokens, 0)) AS tokens,
        bool_or(reservation_status IN ('reserved', 'unknown')) AS unresolved
    FROM latest WHERE request_binding IS NOT NULL
    GROUP BY run_id, request_binding->>'model_call_id'
), classified AS (
    SELECT t.*, c.call_id AS covered_call, c.tokens AS covered_tokens,
        c.unresolved AS covered_unresolved, b.day
    FROM traces t CROSS JOIN boundary b LEFT JOIN coverage c
      ON c.run_id = t.run_id AND c.call_id = t.budget_call_id::text
), gaps AS (
    SELECT run_id, covered_call, greatest(0, max(total_tokens) - max(covered_tokens)) AS tokens
    FROM classified WHERE covered_call IS NOT NULL
      AND (created_at >= day OR covered_unresolved)
    GROUP BY run_id, covered_call
)
SELECT (coalesce(sum(CASE
        WHEN covered_call IS NOT NULL THEN 0
        WHEN resolution_id IS NOT NULL THEN resolved_tokens
        WHEN usage_status = 'known' AND input_meter_version = 'normalized_input.v1'
          AND created_at >= day THEN total_tokens ELSE 0 END), 0)
        + coalesce((SELECT sum(tokens) FROM gaps), 0))::bigint,
    coalesce(array_agg(id ORDER BY id) FILTER (WHERE covered_call IS NULL
        AND resolution_id IS NULL AND usage_status <> 'not_invoked'
        AND (usage_status = 'known' AND input_meter_version = 'normalized_input.v1') IS NOT TRUE),
        ARRAY[]::uuid[])
FROM classified;
$body$;
REVOKE ALL ON FUNCTION cehub_ai.unbound_model_usage(uuid, timestamptz) FROM PUBLIC;
"""

RESERVE = r"""
CREATE FUNCTION cehub_ai.reserve_run_budget(
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
"""


def upgrade() -> None:
    op.execute(ACCOUNTING)
    op.execute(RESERVE)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS (SELECT 1 FROM cehub_ai.budget_journal)"))
        .scalar_one()
    ):
        raise RuntimeError("refusing downgrade: budget reservation history exists")
    for signature in (
        "agent_reserve_model_budget(uuid,bigint,jsonb)",
        "agent_budget_profile()",
        "agent_open_budgeted_model_call()",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS cehub_ai.{signature}")
    op.execute(
        "DROP FUNCTION cehub_ai.reserve_run_budget(uuid,uuid,uuid,text,bigint,bigint,bigint,jsonb)"
    )
    op.execute("DROP FUNCTION cehub_ai.unbound_model_usage(uuid,timestamptz)")
