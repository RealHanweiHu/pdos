-- PDOS S2-2b Agent runtime least-privilege boundary.
-- Run as the schema owner after Alembic migrations and agent-runtime-roles.sql.
-- This script is idempotent, creates no passwords, and must be reviewed by the DBA.

BEGIN;

DO $preflight$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pdos_worker')
       OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pdos_agent') THEN
        RAISE EXCEPTION
            'Run agent-runtime-roles.sql as the database administrator first';
    END IF;
END
$preflight$;

REVOKE ALL ON SCHEMA cehub_core, cehub_project, cehub_product, cehub_quality,
    cehub_supplier, cehub_cost, cehub_memory, cehub_event, cehub_audit, cehub_ai
    FROM pdos_worker, pdos_agent;
REVOKE ALL ON SCHEMA cehub_core, cehub_project, cehub_product, cehub_quality,
    cehub_supplier, cehub_cost, cehub_memory, cehub_event, cehub_audit, cehub_ai
    FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA cehub_core, cehub_project, cehub_product,
    cehub_quality, cehub_supplier, cehub_cost, cehub_memory, cehub_event,
    cehub_audit, cehub_ai FROM pdos_worker, pdos_agent;
REVOKE ALL ON ALL TABLES IN SCHEMA cehub_core, cehub_project, cehub_product,
    cehub_quality, cehub_supplier, cehub_cost, cehub_memory, cehub_event,
    cehub_audit, cehub_ai FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA cehub_core, cehub_project, cehub_product,
    cehub_quality, cehub_supplier, cehub_cost, cehub_memory, cehub_event,
    cehub_audit, cehub_ai FROM pdos_worker, pdos_agent;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA cehub_ai FROM pdos_worker, pdos_agent;

GRANT USAGE ON SCHEMA cehub_event, cehub_ai TO pdos_worker;
GRANT SELECT ON cehub_event.events TO pdos_worker;
GRANT SELECT, INSERT ON cehub_ai.agent_dispatcher_cursors TO pdos_worker;
GRANT UPDATE (last_event_row_id, updated_at)
    ON cehub_ai.agent_dispatcher_cursors TO pdos_worker;
GRANT SELECT, INSERT ON cehub_ai.agent_subscriptions TO pdos_worker;
GRANT UPDATE (
    status,
    consecutive_failure_count,
    failure_threshold,
    paused_reason,
    updated_at
) ON cehub_ai.agent_subscriptions TO pdos_worker;
GRANT SELECT, INSERT ON cehub_ai.agent_runs TO pdos_worker;
GRANT UPDATE (
    status,
    last_event_row_id,
    event_count,
    event_row_ids,
    updated_at
) ON cehub_ai.agent_runs TO pdos_worker;

CREATE OR REPLACE FUNCTION cehub_ai.agent_scope_allows(
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
$function$;

CREATE OR REPLACE FUNCTION cehub_ai.agent_tenant_scope_allows(
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
$function$;

CREATE OR REPLACE FUNCTION cehub_ai.agent_invocation_scope_allows(
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
$function$;

CREATE OR REPLACE FUNCTION cehub_ai.claim_agent_run(
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
$function$;

CREATE OR REPLACE FUNCTION cehub_ai.bind_agent_scope(
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
$function$;

CREATE OR REPLACE VIEW cehub_ai.agent_run_projection
WITH (security_barrier = true)
AS
SELECT
    run.id,
    run.tenant_id,
    run.project_id,
    run.subscription_id,
    run.agent_key,
    run.status,
    run.window_started_at,
    run.window_ended_at,
    run.first_event_row_id,
    run.last_event_row_id,
    run.event_count,
    run.event_row_ids,
    run.created_at
FROM cehub_ai.agent_runs AS run
WHERE cehub_ai.agent_scope_allows(run.tenant_id, run.project_id);

CREATE OR REPLACE VIEW cehub_ai.agent_project_projection
WITH (security_barrier = true)
AS
SELECT
    project.id,
    project.tenant_id,
    project.workflow_id,
    project.code,
    project.name,
    project.status,
    project.current_stage_id,
    stage.code AS current_stage_code,
    stage.name AS current_stage_name,
    stage.sequence AS current_stage_sequence,
    (
        SELECT max(all_stages.sequence)
        FROM cehub_project.stages AS all_stages
        WHERE all_stages.tenant_id = project.tenant_id
          AND all_stages.workflow_id = project.workflow_id
    ) AS max_stage_sequence
FROM cehub_project.projects AS project
LEFT JOIN cehub_project.stages AS stage
  ON stage.tenant_id = project.tenant_id
 AND stage.workflow_id = project.workflow_id
 AND stage.id = project.current_stage_id
WHERE cehub_ai.agent_scope_allows(project.tenant_id, project.id);

CREATE OR REPLACE VIEW cehub_ai.agent_issue_projection
WITH (security_barrier = true)
AS
SELECT issue.id, issue.tenant_id, issue.project_id, issue.status, issue.created_at
FROM cehub_project.issues AS issue
WHERE cehub_ai.agent_scope_allows(issue.tenant_id, issue.project_id);

CREATE OR REPLACE VIEW cehub_ai.agent_risk_projection
WITH (security_barrier = true)
AS
SELECT risk.id, risk.tenant_id, risk.project_id, risk.status, risk.created_at
FROM cehub_project.risks AS risk
WHERE cehub_ai.agent_scope_allows(risk.tenant_id, risk.project_id);

CREATE OR REPLACE VIEW cehub_ai.agent_task_projection
WITH (security_barrier = true)
AS
SELECT task.id, task.tenant_id, task.project_id, task.status, task.due_date, task.created_at
FROM cehub_project.tasks AS task
WHERE cehub_ai.agent_scope_allows(task.tenant_id, task.project_id);

CREATE OR REPLACE VIEW cehub_ai.agent_gate_projection
WITH (security_barrier = true)
AS
SELECT gate.id, gate.tenant_id, gate.project_id, gate.status, gate.review_due_at
FROM cehub_project.gates AS gate
WHERE cehub_ai.agent_scope_allows(gate.tenant_id, gate.project_id);

CREATE OR REPLACE VIEW cehub_ai.agent_event_projection
WITH (security_barrier = true)
AS
SELECT
    event.id,
    event.tenant_id,
    event.project_id,
    event.event_type,
    event.entity,
    event.entity_id,
    event.timestamp
FROM cehub_event.events AS event
WHERE cehub_ai.agent_scope_allows(event.tenant_id, event.project_id);

CREATE OR REPLACE VIEW cehub_ai.agent_document_fragment_projection
WITH (security_barrier = true)
AS
SELECT
    fragment.id,
    fragment.tenant_id,
    fragment.project_id,
    fragment.document_id,
    fragment.ordinal,
    fragment.locator,
    fragment.text,
    document.filename,
    document.classification
FROM cehub_project.document_fragments AS fragment
JOIN cehub_project.documents AS document
  ON document.tenant_id = fragment.tenant_id
 AND document.project_id = fragment.project_id
 AND document.id = fragment.document_id
WHERE cehub_ai.agent_scope_allows(fragment.tenant_id, fragment.project_id)
  AND document.classification = 'internal';

CREATE OR REPLACE VIEW cehub_ai.agent_model_settings_projection
WITH (security_barrier = true)
AS
SELECT setting.tenant_id, setting.provider, setting.model, setting.daily_token_budget
FROM cehub_ai.tenant_model_settings AS setting
WHERE cehub_ai.agent_tenant_scope_allows(setting.tenant_id);

CREATE OR REPLACE VIEW cehub_ai.agent_model_usage_projection
WITH (security_barrier = true)
AS
SELECT invocation.tenant_id, invocation.total_tokens, invocation.created_at
FROM cehub_ai.model_invocations AS invocation
WHERE cehub_ai.agent_tenant_scope_allows(invocation.tenant_id);

CREATE OR REPLACE VIEW cehub_ai.agent_run_usage_projection
WITH (security_barrier = true)
AS
SELECT run.tenant_id, run.agent_key, run.created_at
FROM cehub_ai.agent_runs AS run
WHERE cehub_ai.agent_tenant_scope_allows(run.tenant_id);

CREATE OR REPLACE VIEW cehub_ai.agent_finding_quality_projection
WITH (security_barrier = true)
AS
SELECT
    control.tenant_id,
    control.agent_key,
    control.finding_type,
    control.status
FROM cehub_ai.finding_quality_controls AS control
WHERE cehub_ai.agent_tenant_scope_allows(control.tenant_id);

CREATE OR REPLACE FUNCTION cehub_ai.persist_agent_run_context(
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
       OR frozen_context->>'agent_key' <> scoped_run.agent_key THEN
        RAISE EXCEPTION 'Agent run context is invalid' USING ERRCODE = '42501';
    END IF;

    UPDATE cehub_ai.agent_runs AS target
    SET run_context = frozen_context || jsonb_build_object(
            '_lease_token', bound_lease_token::text
        ),
        updated_at = persisted_at
    WHERE target.id = scoped_run.id;
END
$function$;

CREATE OR REPLACE FUNCTION cehub_ai.complete_agent_run(
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
$function$;

CREATE OR REPLACE FUNCTION cehub_ai.fail_agent_run(
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
$function$;

CREATE OR REPLACE FUNCTION cehub_ai.create_agent_finding(
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
$function$;

ALTER TABLE cehub_ai.model_invocations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pdos_agent_insert_model_invocations
    ON cehub_ai.model_invocations;
CREATE POLICY pdos_agent_insert_model_invocations
    ON cehub_ai.model_invocations
    FOR INSERT
    TO pdos_agent
    WITH CHECK (
        cehub_ai.agent_invocation_scope_allows(
            tenant_id,
            project_id,
            run_id,
            agent_key
        )
    );

GRANT USAGE ON SCHEMA cehub_ai TO pdos_agent;
GRANT SELECT ON
    cehub_ai.agent_run_projection,
    cehub_ai.agent_project_projection,
    cehub_ai.agent_issue_projection,
    cehub_ai.agent_risk_projection,
    cehub_ai.agent_task_projection,
    cehub_ai.agent_gate_projection,
    cehub_ai.agent_event_projection,
    cehub_ai.agent_document_fragment_projection,
    cehub_ai.agent_model_settings_projection,
    cehub_ai.agent_model_usage_projection,
    cehub_ai.agent_run_usage_projection,
    cehub_ai.agent_finding_quality_projection
    TO pdos_agent;
GRANT INSERT ON cehub_ai.model_invocations TO pdos_agent;
GRANT EXECUTE ON FUNCTION cehub_ai.agent_scope_allows(uuid, uuid) TO pdos_agent;
GRANT EXECUTE ON FUNCTION cehub_ai.agent_tenant_scope_allows(uuid) TO pdos_agent;
GRANT EXECUTE ON FUNCTION cehub_ai.agent_invocation_scope_allows(
    uuid, uuid, uuid, varchar
) TO pdos_agent;
GRANT EXECUTE ON FUNCTION cehub_ai.claim_agent_run(timestamptz) TO pdos_agent;
GRANT EXECUTE ON FUNCTION cehub_ai.bind_agent_scope(uuid, uuid) TO pdos_agent;
GRANT EXECUTE ON FUNCTION cehub_ai.persist_agent_run_context(
    uuid, uuid, jsonb, timestamptz
) TO pdos_agent;
GRANT EXECUTE ON FUNCTION cehub_ai.complete_agent_run(
    uuid, uuid, varchar, varchar, timestamptz
) TO pdos_agent;
GRANT EXECUTE ON FUNCTION cehub_ai.fail_agent_run(
    uuid, uuid, varchar, timestamptz
) TO pdos_agent;
GRANT EXECUTE ON FUNCTION cehub_ai.create_agent_finding(
    uuid, uuid, uuid, uuid, varchar, varchar, varchar, text, jsonb, jsonb,
    smallint, varchar, timestamptz
) TO pdos_agent;

REVOKE ALL ON FUNCTION cehub_ai.agent_scope_allows(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.agent_tenant_scope_allows(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.agent_invocation_scope_allows(
    uuid, uuid, uuid, varchar
) FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.claim_agent_run(timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.bind_agent_scope(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.persist_agent_run_context(
    uuid, uuid, jsonb, timestamptz
) FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.complete_agent_run(
    uuid, uuid, varchar, varchar, timestamptz
) FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.fail_agent_run(
    uuid, uuid, varchar, timestamptz
) FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.create_agent_finding(
    uuid, uuid, uuid, uuid, varchar, varchar, varchar, text, jsonb, jsonb,
    smallint, varchar, timestamptz
) FROM PUBLIC;

COMMIT;
