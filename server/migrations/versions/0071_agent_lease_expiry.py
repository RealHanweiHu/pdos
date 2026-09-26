"""Database-time Agent leases and expiration fences; token identity remains scoped."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0071_agent_lease_expiry"
down_revision: str | Sequence[str] | None = "0070_event_budget_binding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Immutable snapshots: never load the mutable DBA template while migrating.
HELPERS = r"""CREATE OR REPLACE FUNCTION cehub_ai.agent_lease_is_current(
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
FUNCTIONS = [
    (
        "cehub_ai.agent_scope_allows(uuid,uuid)",
        r"""CREATE OR REPLACE FUNCTION cehub_ai.agent_scope_allows(
    row_tenant_id uuid,
    row_project_id uuid
) RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM cehub_ai.agent_runs AS run
        WHERE run.id = nullif(current_setting('pdos.agent_run_id', true), '')::uuid
          AND run.tenant_id = nullif(current_setting('pdos.tenant_id', true), '')::uuid
          AND run.project_id = nullif(current_setting('pdos.project_id', true), '')::uuid
          AND run.run_context->>'_lease_token' =
              nullif(current_setting('pdos.agent_lease_token', true), '')
          AND run.status = 'running'
          AND run.tenant_id = row_tenant_id
          AND run.project_id = row_project_id
    )
$function$;""",
        r"""CREATE OR REPLACE FUNCTION cehub_ai.agent_scope_allows(
    row_tenant_id uuid,
    row_project_id uuid
) RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM cehub_ai.agent_runs AS run
        WHERE run.id = nullif(current_setting('pdos.agent_run_id', true), '')::uuid
          AND run.tenant_id = nullif(current_setting('pdos.tenant_id', true), '')::uuid
          AND run.project_id = nullif(current_setting('pdos.project_id', true), '')::uuid
          AND run.run_context->>'_lease_token' =
              nullif(current_setting('pdos.agent_lease_token', true), '')
          AND run.status = 'running'
          AND cehub_ai.agent_lease_is_current(run.id,
              nullif(current_setting('pdos.agent_lease_token', true), '')::uuid)
          AND run.tenant_id = row_tenant_id
          AND run.project_id = row_project_id
    )
$function$;""",
    ),
    (
        "cehub_ai.agent_tenant_scope_allows(uuid)",
        r"""CREATE OR REPLACE FUNCTION cehub_ai.agent_tenant_scope_allows(
    row_tenant_id uuid
) RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM cehub_ai.agent_runs AS run
        WHERE run.id = nullif(current_setting('pdos.agent_run_id', true), '')::uuid
          AND run.tenant_id = nullif(current_setting('pdos.tenant_id', true), '')::uuid
          AND run.project_id = nullif(current_setting('pdos.project_id', true), '')::uuid
          AND run.run_context->>'_lease_token' =
              nullif(current_setting('pdos.agent_lease_token', true), '')
          AND run.status = 'running'
          AND run.tenant_id = row_tenant_id
    )
$function$;""",
        r"""CREATE OR REPLACE FUNCTION cehub_ai.agent_tenant_scope_allows(
    row_tenant_id uuid
) RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM cehub_ai.agent_runs AS run
        WHERE run.id = nullif(current_setting('pdos.agent_run_id', true), '')::uuid
          AND run.tenant_id = nullif(current_setting('pdos.tenant_id', true), '')::uuid
          AND run.project_id = nullif(current_setting('pdos.project_id', true), '')::uuid
          AND run.run_context->>'_lease_token' =
              nullif(current_setting('pdos.agent_lease_token', true), '')
          AND run.status = 'running'
          AND cehub_ai.agent_lease_is_current(run.id,
              nullif(current_setting('pdos.agent_lease_token', true), '')::uuid)
          AND run.tenant_id = row_tenant_id
    )
$function$;""",
    ),
    (
        "cehub_ai.agent_tenant_agent_scope_allows(uuid,varchar)",
        r"""CREATE OR REPLACE FUNCTION cehub_ai.agent_tenant_agent_scope_allows(
    row_tenant_id uuid,
    required_agent_key varchar
) RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM cehub_ai.agent_runs AS run
        WHERE run.id = nullif(current_setting('pdos.agent_run_id', true), '')::uuid
          AND run.tenant_id = nullif(current_setting('pdos.tenant_id', true), '')::uuid
          AND run.project_id = nullif(current_setting('pdos.project_id', true), '')::uuid
          AND run.run_context->>'_lease_token' =
              nullif(current_setting('pdos.agent_lease_token', true), '')
          AND run.status = 'running'
          AND run.tenant_id = row_tenant_id
          AND run.agent_key = required_agent_key
    )
$function$;""",
        r"""CREATE OR REPLACE FUNCTION cehub_ai.agent_tenant_agent_scope_allows(
    row_tenant_id uuid,
    required_agent_key varchar
) RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM cehub_ai.agent_runs AS run
        WHERE run.id = nullif(current_setting('pdos.agent_run_id', true), '')::uuid
          AND run.tenant_id = nullif(current_setting('pdos.tenant_id', true), '')::uuid
          AND run.project_id = nullif(current_setting('pdos.project_id', true), '')::uuid
          AND run.run_context->>'_lease_token' =
              nullif(current_setting('pdos.agent_lease_token', true), '')
          AND run.status = 'running'
          AND cehub_ai.agent_lease_is_current(run.id,
              nullif(current_setting('pdos.agent_lease_token', true), '')::uuid)
          AND run.tenant_id = row_tenant_id
          AND run.agent_key = required_agent_key
    )
$function$;""",
    ),
    (
        "cehub_ai.agent_invocation_scope_allows(uuid,uuid,uuid,varchar)",
        r"""CREATE OR REPLACE FUNCTION cehub_ai.agent_invocation_scope_allows(
    row_tenant_id uuid,
    row_project_id uuid,
    row_run_id uuid,
    row_agent_key varchar
) RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM cehub_ai.agent_runs AS run
        WHERE run.id = nullif(current_setting('pdos.agent_run_id', true), '')::uuid
          AND run.tenant_id = nullif(current_setting('pdos.tenant_id', true), '')::uuid
          AND run.project_id = nullif(current_setting('pdos.project_id', true), '')::uuid
          AND run.run_context->>'_lease_token' =
              nullif(current_setting('pdos.agent_lease_token', true), '')
          AND run.status = 'running'
          AND run.tenant_id = row_tenant_id
          AND run.project_id = row_project_id
          AND run.id = row_run_id
          AND run.agent_key = row_agent_key
    )
$function$;""",
        r"""CREATE OR REPLACE FUNCTION cehub_ai.agent_invocation_scope_allows(
    row_tenant_id uuid,
    row_project_id uuid,
    row_run_id uuid,
    row_agent_key varchar
) RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM cehub_ai.agent_runs AS run
        WHERE run.id = nullif(current_setting('pdos.agent_run_id', true), '')::uuid
          AND run.tenant_id = nullif(current_setting('pdos.tenant_id', true), '')::uuid
          AND run.project_id = nullif(current_setting('pdos.project_id', true), '')::uuid
          AND run.run_context->>'_lease_token' =
              nullif(current_setting('pdos.agent_lease_token', true), '')
          AND run.status = 'running'
          AND cehub_ai.agent_lease_is_current(run.id,
              nullif(current_setting('pdos.agent_lease_token', true), '')::uuid)
          AND run.tenant_id = row_tenant_id
          AND run.project_id = row_project_id
          AND run.id = row_run_id
          AND run.agent_key = row_agent_key
    )
$function$;""",
    ),
    (
        "cehub_ai.claim_agent_run(timestamptz)",
        r"""CREATE OR REPLACE FUNCTION cehub_ai.claim_agent_run(
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

    UPDATE cehub_ai.agent_runs AS target
    SET status = 'running',
        started_at = claimed_at,
        run_context = jsonb_set(
            target.run_context,
            '{_lease_token}',
            to_jsonb(generated_lease::text),
            true
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
$function$;""",
        r"""CREATE OR REPLACE FUNCTION cehub_ai.claim_agent_run(
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
$function$;""",
    ),
    (
        "cehub_ai.bind_agent_scope(uuid,uuid)",
        r"""CREATE OR REPLACE FUNCTION cehub_ai.bind_agent_scope(
    bound_run_id uuid,
    bound_lease_token uuid
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    scoped_run cehub_ai.agent_runs%ROWTYPE;
BEGIN
    SELECT * INTO scoped_run
    FROM cehub_ai.agent_runs AS run
    WHERE run.id = bound_run_id
      AND run.status = 'running'
      AND run.run_context->>'_lease_token' = bound_lease_token::text;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Agent run lease is invalid' USING ERRCODE = '42501';
    END IF;

    PERFORM set_config('pdos.agent_run_id', scoped_run.id::text, true);
    PERFORM set_config('pdos.tenant_id', scoped_run.tenant_id::text, true);
    PERFORM set_config('pdos.project_id', scoped_run.project_id::text, true);
    PERFORM set_config('pdos.agent_lease_token', bound_lease_token::text, true);
END
$function$;""",
        r"""CREATE OR REPLACE FUNCTION cehub_ai.bind_agent_scope(
    bound_run_id uuid,
    bound_lease_token uuid
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    scoped_run cehub_ai.agent_runs%ROWTYPE;
BEGIN
    SELECT * INTO scoped_run
    FROM cehub_ai.agent_runs AS run
    WHERE run.id = bound_run_id
      AND run.status = 'running'
      AND run.run_context->>'_lease_token' = bound_lease_token::text
      AND cehub_ai.agent_lease_is_current(run.id, bound_lease_token);

    IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(bound_run_id, bound_lease_token) THEN
        RAISE EXCEPTION 'Agent run lease is invalid' USING ERRCODE = '42501';
    END IF;

    PERFORM set_config('pdos.agent_run_id', scoped_run.id::text, true);
    PERFORM set_config('pdos.tenant_id', scoped_run.tenant_id::text, true);
    PERFORM set_config('pdos.project_id', scoped_run.project_id::text, true);
    PERFORM set_config('pdos.agent_lease_token', bound_lease_token::text, true);
END
$function$;""",
    ),
    (
        "cehub_ai.persist_agent_run_context(uuid,uuid,jsonb,timestamptz)",
        r"""CREATE OR REPLACE FUNCTION cehub_ai.persist_agent_run_context(
    bound_run_id uuid,
    bound_lease_token uuid,
    frozen_context jsonb,
    persisted_at timestamptz
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    scoped_run cehub_ai.agent_runs%ROWTYPE;
BEGIN
    SELECT * INTO scoped_run
    FROM cehub_ai.agent_runs AS run
    WHERE run.id = bound_run_id
      AND run.status = 'running'
      AND run.run_context->>'_lease_token' = bound_lease_token::text
    FOR UPDATE;

    IF NOT FOUND
       OR jsonb_typeof(frozen_context) <> 'object'
       OR frozen_context->>'run_id' <> scoped_run.id::text
       OR frozen_context->>'tenant_id' <> scoped_run.tenant_id::text
       OR frozen_context->>'project_id' <> scoped_run.project_id::text
       OR frozen_context->>'agent_key' <> scoped_run.agent_key
       OR frozen_context->>'schema_version' <> '2' THEN
        RAISE EXCEPTION 'Agent run context is invalid' USING ERRCODE = '42501';
    END IF;

    UPDATE cehub_ai.agent_runs AS target
    SET context_version = 'run-context-v2',
        run_context = frozen_context || jsonb_build_object(
            '_lease_token', bound_lease_token::text
        ),
        updated_at = persisted_at
    WHERE target.id = scoped_run.id;
END
$function$;""",
        r"""CREATE OR REPLACE FUNCTION cehub_ai.persist_agent_run_context(
    bound_run_id uuid,
    bound_lease_token uuid,
    frozen_context jsonb,
    persisted_at timestamptz
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    scoped_run cehub_ai.agent_runs%ROWTYPE;
BEGIN
    SELECT * INTO scoped_run
    FROM cehub_ai.agent_runs AS run
    WHERE run.id = bound_run_id
      AND run.status = 'running'
      AND run.run_context->>'_lease_token' = bound_lease_token::text
      AND cehub_ai.agent_lease_is_current(run.id, bound_lease_token)
    FOR UPDATE;

    IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(bound_run_id, bound_lease_token)
       OR jsonb_typeof(frozen_context) <> 'object'
       OR frozen_context->>'run_id' <> scoped_run.id::text
       OR frozen_context->>'tenant_id' <> scoped_run.tenant_id::text
       OR frozen_context->>'project_id' <> scoped_run.project_id::text
       OR frozen_context->>'agent_key' <> scoped_run.agent_key
       OR frozen_context->>'schema_version' <> '2' THEN
        RAISE EXCEPTION 'Agent run context is invalid' USING ERRCODE = '42501';
    END IF;

    UPDATE cehub_ai.agent_runs AS target
    SET context_version = 'run-context-v2',
        run_context = frozen_context || jsonb_build_object(
            '_lease_token', bound_lease_token::text,
            '_lease_expires_at', scoped_run.run_context->'_lease_expires_at',
            '_lease_renewed_at', scoped_run.run_context->'_lease_renewed_at'
        ),
        updated_at = persisted_at
    WHERE target.id = scoped_run.id;
END
$function$;""",
    ),
    (
        "cehub_ai.complete_agent_run(uuid,uuid,varchar,varchar,timestamptz)",
        r"""CREATE OR REPLACE FUNCTION cehub_ai.complete_agent_run(
    bound_run_id uuid,
    bound_lease_token uuid,
    terminal_status varchar,
    terminal_error_code varchar,
    completed_at timestamptz
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    scoped_run cehub_ai.agent_runs%ROWTYPE;
BEGIN
    IF (terminal_status = 'succeeded' AND terminal_error_code IS NOT NULL)
       OR (terminal_status = 'degraded' AND nullif(btrim(terminal_error_code), '') IS NULL)
       OR terminal_status NOT IN ('succeeded', 'degraded') THEN
        RAISE EXCEPTION 'Agent terminal result is invalid' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO scoped_run
    FROM cehub_ai.agent_runs AS run
    WHERE run.id = bound_run_id
      AND run.status = 'running'
      AND run.run_context->>'_lease_token' = bound_lease_token::text
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Agent run lease is invalid' USING ERRCODE = '42501';
    END IF;

    UPDATE cehub_ai.agent_runs AS target
    SET status = terminal_status,
        completed_at = complete_agent_run.completed_at,
        error_code = terminal_error_code,
        updated_at = complete_agent_run.completed_at
    WHERE target.id = scoped_run.id;

    UPDATE cehub_ai.agent_subscriptions AS subscription
    SET consecutive_failure_count = 0,
        updated_at = complete_agent_run.completed_at
    WHERE subscription.id = scoped_run.subscription_id;
END
$function$;""",
        r"""CREATE OR REPLACE FUNCTION cehub_ai.complete_agent_run(
    bound_run_id uuid,
    bound_lease_token uuid,
    terminal_status varchar,
    terminal_error_code varchar,
    completed_at timestamptz
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    scoped_run cehub_ai.agent_runs%ROWTYPE;
BEGIN
    IF (terminal_status = 'succeeded' AND terminal_error_code IS NOT NULL)
       OR (terminal_status = 'degraded' AND nullif(btrim(terminal_error_code), '') IS NULL)
       OR terminal_status NOT IN ('succeeded', 'degraded') THEN
        RAISE EXCEPTION 'Agent terminal result is invalid' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO scoped_run
    FROM cehub_ai.agent_runs AS run
    WHERE run.id = bound_run_id
      AND run.status = 'running'
      AND run.run_context->>'_lease_token' = bound_lease_token::text
      AND cehub_ai.agent_lease_is_current(run.id, bound_lease_token)
    FOR UPDATE;
    IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(bound_run_id, bound_lease_token) THEN
        RAISE EXCEPTION 'Agent run lease is invalid' USING ERRCODE = '42501';
    END IF;

    UPDATE cehub_ai.agent_runs AS target
    SET status = terminal_status,
        completed_at = complete_agent_run.completed_at,
        error_code = terminal_error_code,
        updated_at = complete_agent_run.completed_at
    WHERE target.id = scoped_run.id;

    UPDATE cehub_ai.agent_subscriptions AS subscription
    SET consecutive_failure_count = 0,
        updated_at = complete_agent_run.completed_at
    WHERE subscription.id = scoped_run.subscription_id;
END
$function$;""",
    ),
    (
        "cehub_ai.fail_agent_run(uuid,uuid,varchar,timestamptz)",
        r"""CREATE OR REPLACE FUNCTION cehub_ai.fail_agent_run(
    bound_run_id uuid,
    bound_lease_token uuid,
    terminal_error_code varchar,
    failed_at timestamptz
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    scoped_run cehub_ai.agent_runs%ROWTYPE;
    subscription cehub_ai.agent_subscriptions%ROWTYPE;
    next_failure_count integer;
BEGIN
    IF nullif(btrim(terminal_error_code), '') IS NULL THEN
        RAISE EXCEPTION 'Agent failure code is invalid' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO scoped_run
    FROM cehub_ai.agent_runs AS run
    WHERE run.id = bound_run_id
      AND run.status = 'running'
      AND run.run_context->>'_lease_token' = bound_lease_token::text
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Agent run lease is invalid' USING ERRCODE = '42501';
    END IF;

    SELECT * INTO subscription
    FROM cehub_ai.agent_subscriptions AS current_subscription
    WHERE current_subscription.id = scoped_run.subscription_id
    FOR UPDATE;
    next_failure_count := subscription.consecutive_failure_count + 1;

    UPDATE cehub_ai.agent_runs AS target
    SET status = 'failed',
        completed_at = fail_agent_run.failed_at,
        error_code = terminal_error_code,
        updated_at = fail_agent_run.failed_at
    WHERE target.id = scoped_run.id;

    UPDATE cehub_ai.agent_subscriptions AS target
    SET consecutive_failure_count = next_failure_count,
        status = CASE
            WHEN next_failure_count >= subscription.failure_threshold THEN 'paused'
            ELSE target.status
        END,
        paused_reason = CASE
            WHEN next_failure_count >= subscription.failure_threshold THEN
                'AGENT_RUN_FAILURE_THRESHOLD_REACHED:' || terminal_error_code ||
                ':count=' || next_failure_count::text ||
                ':threshold=' || subscription.failure_threshold::text
            ELSE target.paused_reason
        END,
        updated_at = fail_agent_run.failed_at
    WHERE target.id = subscription.id;
END
$function$;""",
        r"""CREATE OR REPLACE FUNCTION cehub_ai.fail_agent_run(
    bound_run_id uuid,
    bound_lease_token uuid,
    terminal_error_code varchar,
    failed_at timestamptz
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    scoped_run cehub_ai.agent_runs%ROWTYPE;
    subscription cehub_ai.agent_subscriptions%ROWTYPE;
    next_failure_count integer;
BEGIN
    IF nullif(btrim(terminal_error_code), '') IS NULL THEN
        RAISE EXCEPTION 'Agent failure code is invalid' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO scoped_run
    FROM cehub_ai.agent_runs AS run
    WHERE run.id = bound_run_id
      AND run.status = 'running'
      AND run.run_context->>'_lease_token' = bound_lease_token::text
      AND cehub_ai.agent_lease_is_current(run.id, bound_lease_token)
    FOR UPDATE;
    IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(bound_run_id, bound_lease_token) THEN
        RAISE EXCEPTION 'Agent run lease is invalid' USING ERRCODE = '42501';
    END IF;

    SELECT * INTO subscription
    FROM cehub_ai.agent_subscriptions AS current_subscription
    WHERE current_subscription.id = scoped_run.subscription_id
    FOR UPDATE;
    next_failure_count := subscription.consecutive_failure_count + 1;

    IF NOT cehub_ai.agent_lease_is_current(bound_run_id, bound_lease_token) THEN
        RAISE EXCEPTION 'Agent run lease expired during failure handling' USING ERRCODE = '42501';
    END IF;
    UPDATE cehub_ai.agent_runs AS target
    SET status = 'failed',
        completed_at = fail_agent_run.failed_at,
        error_code = terminal_error_code,
        updated_at = fail_agent_run.failed_at
    WHERE target.id = scoped_run.id;

    UPDATE cehub_ai.agent_subscriptions AS target
    SET consecutive_failure_count = next_failure_count,
        status = CASE
            WHEN next_failure_count >= subscription.failure_threshold THEN 'paused'
            ELSE target.status
        END,
        paused_reason = CASE
            WHEN next_failure_count >= subscription.failure_threshold THEN
                'AGENT_RUN_FAILURE_THRESHOLD_REACHED:' || terminal_error_code ||
                ':count=' || next_failure_count::text ||
                ':threshold=' || subscription.failure_threshold::text
            ELSE target.paused_reason
        END,
        updated_at = fail_agent_run.failed_at
    WHERE target.id = subscription.id;
END
$function$;""",
    ),
    (
        (
            "cehub_ai.create_agent_finding(uuid,uuid,uuid,uuid,varchar,va"
            "rchar,varchar,text,jsonb,jsonb,smallint,varchar,timestamptz)"
        ),
        r"""CREATE OR REPLACE FUNCTION cehub_ai.create_agent_finding(
    new_finding_id uuid,
    bound_run_id uuid,
    bound_lease_token uuid,
    bound_model_invocation_id uuid,
    new_origin_key varchar,
    new_finding_type varchar,
    new_title varchar,
    new_summary text,
    new_proposed_payload jsonb,
    new_evidence_event_ids jsonb,
    new_confidence_basis_points smallint,
    new_preflight_version varchar,
    created_at timestamptz
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    scoped_run cehub_ai.agent_runs%ROWTYPE;
    invocation_matches boolean;
    evidence_count integer;
    persisted_event_id varchar := 'ai-finding:' || new_finding_id::text || ':created';
BEGIN
    SELECT * INTO scoped_run
    FROM cehub_ai.agent_runs AS run
    WHERE run.id = bound_run_id
      AND run.status = 'running'
      AND run.run_context->>'_lease_token' = bound_lease_token::text
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Agent run lease is invalid' USING ERRCODE = '42501';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended('finding-quality:' || scoped_run.tenant_id::text, 0)
    );

    SELECT EXISTS (
        SELECT 1
        FROM cehub_ai.model_invocations AS invocation
        WHERE invocation.id = bound_model_invocation_id
          AND invocation.tenant_id = scoped_run.tenant_id
          AND invocation.project_id = scoped_run.project_id
          AND invocation.run_id = scoped_run.id
          AND invocation.agent_key = scoped_run.agent_key
          AND invocation.status = 'succeeded'
    ) INTO invocation_matches;

    IF NOT invocation_matches
       OR EXISTS (
           SELECT 1
           FROM cehub_ai.finding_quality_controls AS control
           WHERE control.tenant_id = scoped_run.tenant_id
             AND control.agent_key = scoped_run.agent_key
             AND control.finding_type = new_finding_type
             AND control.status = 'narrowed'
       )
       OR NOT (
           (scoped_run.agent_key = 'project_intelligence' AND new_finding_type IN (
               'risk_suggestion', 'blocker_alert', 'gate_readiness_anomaly'
           ))
           OR (scoped_run.agent_key = 'knowledge_lite'
               AND new_finding_type = 'knowledge_draft')
           OR (scoped_run.agent_key = 'engineering_intelligence'
               AND new_finding_type IN (
                   'bom_impact_suggestion', 'change_impact_suggestion'
               ))
           OR (scoped_run.agent_key = 'quality_intelligence'
               AND new_finding_type IN (
                   'quality_cluster_alert', 'capa_suggestion'
               ))
           OR (scoped_run.agent_key = 'supplier_intelligence'
               AND new_finding_type = 'supplier_delay_risk')
           OR (scoped_run.agent_key = 'executive_intelligence'
               AND new_finding_type = 'executive_portfolio_brief')
       )
       OR nullif(btrim(new_origin_key), '') IS NULL
       OR nullif(btrim(new_title), '') IS NULL
       OR nullif(btrim(new_summary), '') IS NULL
       OR nullif(btrim(new_preflight_version), '') IS NULL
       OR jsonb_typeof(new_proposed_payload) <> 'object'
       OR jsonb_typeof(new_evidence_event_ids) <> 'array'
       OR jsonb_array_length(new_evidence_event_ids) = 0
       OR new_confidence_basis_points NOT BETWEEN 0 AND 10000 THEN
        RAISE EXCEPTION 'Agent finding preflight is invalid' USING ERRCODE = '42501';
    END IF;

    SELECT count(DISTINCT evidence.value::bigint)
    INTO evidence_count
    FROM jsonb_array_elements_text(new_evidence_event_ids) AS evidence(value)
    WHERE evidence.value ~ '^[1-9][0-9]*$'
      AND EXISTS (
          SELECT 1
          FROM cehub_event.events AS event
          WHERE event.id = evidence.value::bigint
            AND event.tenant_id = scoped_run.tenant_id
            AND event.project_id = scoped_run.project_id
            AND scoped_run.event_row_ids @> to_jsonb(ARRAY[event.id])
      );
    IF evidence_count <> jsonb_array_length(new_evidence_event_ids) THEN
        RAISE EXCEPTION 'Agent finding evidence is outside the run scope'
            USING ERRCODE = '42501';
    END IF;

    INSERT INTO cehub_ai.findings (
        id,
        tenant_id,
        project_id,
        run_id,
        model_invocation_id,
        agent_key,
        finding_type,
        origin_key,
        status,
        title,
        summary,
        proposed_payload,
        evidence_event_ids,
        confidence_basis_points,
        preflight_version,
        created_at,
        updated_at
    ) VALUES (
        new_finding_id,
        scoped_run.tenant_id,
        scoped_run.project_id,
        scoped_run.id,
        bound_model_invocation_id,
        scoped_run.agent_key,
        new_finding_type,
        new_origin_key,
        'pending_review',
        new_title,
        new_summary,
        new_proposed_payload,
        new_evidence_event_ids,
        new_confidence_basis_points,
        new_preflight_version,
        created_at,
        created_at
    );

    INSERT INTO cehub_ai.finding_actions (
        id,
        tenant_id,
        project_id,
        finding_id,
        action,
        actor_user_id,
        from_status,
        to_status,
        detail,
        created_at
    ) VALUES (
        gen_random_uuid(),
        scoped_run.tenant_id,
        scoped_run.project_id,
        new_finding_id,
        'created',
        NULL,
        NULL,
        'pending_review',
        jsonb_build_object('preflight_version', new_preflight_version),
        created_at
    );

    INSERT INTO cehub_event.events (
        tenant_id,
        project_id,
        event_id,
        event_type,
        schema_version,
        source,
        entity,
        entity_id,
        payload,
        timestamp
    ) VALUES (
        scoped_run.tenant_id,
        scoped_run.project_id,
        persisted_event_id,
        'AI_FINDING_CREATED',
        1,
        'ai_runtime',
        'ai_finding',
        new_finding_id,
        jsonb_build_object(
            'finding_id', new_finding_id::text,
            'agent_run_id', scoped_run.id::text
        ),
        created_at
    );

    INSERT INTO cehub_audit.audit_log (
        tenant_id,
        project_id,
        actor_user_id,
        event_id,
        action,
        entity,
        entity_id,
        before_snapshot,
        after_snapshot,
        context,
        timestamp
    ) VALUES (
        scoped_run.tenant_id,
        scoped_run.project_id,
        NULL,
        persisted_event_id,
        'finding.create',
        'ai_finding',
        new_finding_id,
        NULL,
        jsonb_build_object(
            'status', 'pending_review',
            'finding_type', new_finding_type,
            'title', new_title
        ),
        jsonb_build_object(
            'agent_key', scoped_run.agent_key,
            'run_id', scoped_run.id::text,
            'model_invocation_id', bound_model_invocation_id::text
        ),
        created_at
    );
END
$function$;""",
        r"""CREATE OR REPLACE FUNCTION cehub_ai.create_agent_finding(
    new_finding_id uuid,
    bound_run_id uuid,
    bound_lease_token uuid,
    bound_model_invocation_id uuid,
    new_origin_key varchar,
    new_finding_type varchar,
    new_title varchar,
    new_summary text,
    new_proposed_payload jsonb,
    new_evidence_event_ids jsonb,
    new_confidence_basis_points smallint,
    new_preflight_version varchar,
    created_at timestamptz
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    scoped_run cehub_ai.agent_runs%ROWTYPE;
    invocation_matches boolean;
    evidence_count integer;
    persisted_event_id varchar := 'ai-finding:' || new_finding_id::text || ':created';
BEGIN
    SELECT * INTO scoped_run
    FROM cehub_ai.agent_runs AS run
    WHERE run.id = bound_run_id
      AND run.status = 'running'
      AND run.run_context->>'_lease_token' = bound_lease_token::text
      AND cehub_ai.agent_lease_is_current(run.id, bound_lease_token)
    FOR UPDATE;
    IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(bound_run_id, bound_lease_token) THEN
        RAISE EXCEPTION 'Agent run lease is invalid' USING ERRCODE = '42501';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended('finding-quality:' || scoped_run.tenant_id::text, 0)
    );

    SELECT EXISTS (
        SELECT 1
        FROM cehub_ai.model_invocations AS invocation
        WHERE invocation.id = bound_model_invocation_id
          AND invocation.tenant_id = scoped_run.tenant_id
          AND invocation.project_id = scoped_run.project_id
          AND invocation.run_id = scoped_run.id
          AND invocation.agent_key = scoped_run.agent_key
          AND invocation.status = 'succeeded'
    ) INTO invocation_matches;

    IF NOT invocation_matches
       OR EXISTS (
           SELECT 1
           FROM cehub_ai.finding_quality_controls AS control
           WHERE control.tenant_id = scoped_run.tenant_id
             AND control.agent_key = scoped_run.agent_key
             AND control.finding_type = new_finding_type
             AND control.status = 'narrowed'
       )
       OR NOT (
           (scoped_run.agent_key = 'project_intelligence' AND new_finding_type IN (
               'risk_suggestion', 'blocker_alert', 'gate_readiness_anomaly'
           ))
           OR (scoped_run.agent_key = 'knowledge_lite'
               AND new_finding_type = 'knowledge_draft')
           OR (scoped_run.agent_key = 'engineering_intelligence'
               AND new_finding_type IN (
                   'bom_impact_suggestion', 'change_impact_suggestion'
               ))
           OR (scoped_run.agent_key = 'quality_intelligence'
               AND new_finding_type IN (
                   'quality_cluster_alert', 'capa_suggestion'
               ))
           OR (scoped_run.agent_key = 'supplier_intelligence'
               AND new_finding_type = 'supplier_delay_risk')
           OR (scoped_run.agent_key = 'executive_intelligence'
               AND new_finding_type = 'executive_portfolio_brief')
       )
       OR nullif(btrim(new_origin_key), '') IS NULL
       OR nullif(btrim(new_title), '') IS NULL
       OR nullif(btrim(new_summary), '') IS NULL
       OR nullif(btrim(new_preflight_version), '') IS NULL
       OR jsonb_typeof(new_proposed_payload) <> 'object'
       OR jsonb_typeof(new_evidence_event_ids) <> 'array'
       OR jsonb_array_length(new_evidence_event_ids) = 0
       OR new_confidence_basis_points NOT BETWEEN 0 AND 10000 THEN
        RAISE EXCEPTION 'Agent finding preflight is invalid' USING ERRCODE = '42501';
    END IF;

    SELECT count(DISTINCT evidence.value::bigint)
    INTO evidence_count
    FROM jsonb_array_elements_text(new_evidence_event_ids) AS evidence(value)
    WHERE evidence.value ~ '^[1-9][0-9]*$'
      AND EXISTS (
          SELECT 1
          FROM cehub_event.events AS event
          WHERE event.id = evidence.value::bigint
            AND event.tenant_id = scoped_run.tenant_id
            AND event.project_id = scoped_run.project_id
            AND scoped_run.event_row_ids @> to_jsonb(ARRAY[event.id])
      );
    IF evidence_count <> jsonb_array_length(new_evidence_event_ids) THEN
        RAISE EXCEPTION 'Agent finding evidence is outside the run scope'
            USING ERRCODE = '42501';
    END IF;

    IF NOT cehub_ai.agent_lease_is_current(bound_run_id, bound_lease_token) THEN
        RAISE EXCEPTION 'Agent run lease expired before Finding publication'
            USING ERRCODE = '42501';
    END IF;
    INSERT INTO cehub_ai.findings (
        id,
        tenant_id,
        project_id,
        run_id,
        model_invocation_id,
        agent_key,
        finding_type,
        origin_key,
        status,
        title,
        summary,
        proposed_payload,
        evidence_event_ids,
        confidence_basis_points,
        preflight_version,
        created_at,
        updated_at
    ) VALUES (
        new_finding_id,
        scoped_run.tenant_id,
        scoped_run.project_id,
        scoped_run.id,
        bound_model_invocation_id,
        scoped_run.agent_key,
        new_finding_type,
        new_origin_key,
        'pending_review',
        new_title,
        new_summary,
        new_proposed_payload,
        new_evidence_event_ids,
        new_confidence_basis_points,
        new_preflight_version,
        created_at,
        created_at
    );

    INSERT INTO cehub_ai.finding_actions (
        id,
        tenant_id,
        project_id,
        finding_id,
        action,
        actor_user_id,
        from_status,
        to_status,
        detail,
        created_at
    ) VALUES (
        gen_random_uuid(),
        scoped_run.tenant_id,
        scoped_run.project_id,
        new_finding_id,
        'created',
        NULL,
        NULL,
        'pending_review',
        jsonb_build_object('preflight_version', new_preflight_version),
        created_at
    );

    INSERT INTO cehub_event.events (
        tenant_id,
        project_id,
        event_id,
        event_type,
        schema_version,
        source,
        entity,
        entity_id,
        payload,
        timestamp
    ) VALUES (
        scoped_run.tenant_id,
        scoped_run.project_id,
        persisted_event_id,
        'AI_FINDING_CREATED',
        1,
        'ai_runtime',
        'ai_finding',
        new_finding_id,
        jsonb_build_object(
            'finding_id', new_finding_id::text,
            'agent_run_id', scoped_run.id::text
        ),
        created_at
    );

    INSERT INTO cehub_audit.audit_log (
        tenant_id,
        project_id,
        actor_user_id,
        event_id,
        action,
        entity,
        entity_id,
        before_snapshot,
        after_snapshot,
        context,
        timestamp
    ) VALUES (
        scoped_run.tenant_id,
        scoped_run.project_id,
        NULL,
        persisted_event_id,
        'finding.create',
        'ai_finding',
        new_finding_id,
        NULL,
        jsonb_build_object(
            'status', 'pending_review',
            'finding_type', new_finding_type,
            'title', new_title
        ),
        jsonb_build_object(
            'agent_key', scoped_run.agent_key,
            'run_id', scoped_run.id::text,
            'model_invocation_id', bound_model_invocation_id::text
        ),
        created_at
    );
END
$function$;""",
    ),
]


def apply_existing(index: int) -> None:
    for signature, previous, current in FUNCTIONS:
        if op.get_bind().execute(sa.text("SELECT to_regprocedure(:s)"), {"s": signature}).scalar():
            # Function bodies contain literal :count/:threshold labels, not
            # SQLAlchemy bind parameters. Execute the immutable DDL as driver SQL.
            op.get_bind().exec_driver_sql(
                previous if index == 0 else current, execution_options={"no_parameters": True}
            )


def upgrade() -> None:
    op.execute(HELPERS)
    apply_existing(1)
    op.execute("""DO $body$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='pdos_agent') THEN
            GRANT EXECUTE ON FUNCTION cehub_ai.renew_agent_run_lease(uuid,uuid) TO pdos_agent;
        END IF;
    END $body$;""")


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN
        IF EXISTS (SELECT 1 FROM cehub_ai.agent_runs WHERE status='running'
                   AND run_context->>'_lease_expires_at' IS NOT NULL) THEN
            RAISE EXCEPTION 'cannot remove Agent expiry fencing with running lease history';
        END IF;
    END $body$;""")
    apply_existing(0)
    op.execute("DROP FUNCTION IF EXISTS cehub_ai.renew_agent_run_lease(uuid,uuid)")
    op.execute("DROP FUNCTION IF EXISTS cehub_ai.agent_lease_is_current(uuid,uuid)")
