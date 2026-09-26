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
GRANT SELECT ON cehub_ai.agent_runs TO pdos_worker;
GRANT INSERT (
    id, tenant_id, project_id, subscription_id, agent_key, status,
    window_started_at, window_ended_at, first_event_row_id, last_event_row_id,
    event_count, event_row_ids, context_version, run_context, started_at, completed_at,
    error_code, created_at, updated_at
) ON cehub_ai.agent_runs TO pdos_worker;
GRANT UPDATE (
    status,
    last_event_row_id,
    event_count,
    event_row_ids,
    updated_at
) ON cehub_ai.agent_runs TO pdos_worker;

CREATE OR REPLACE FUNCTION cehub_ai.agent_lease_is_current(
 wanted_run uuid,wanted_token uuid
) RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
 SELECT cehub_ai.agent_base_lease_is_current(wanted_run,wanted_token)
    AND cehub_ai.event_authorization_is_current(wanted_run);
$body$;
REVOKE ALL ON FUNCTION cehub_ai.agent_lease_is_current(uuid,uuid) FROM PUBLIC;

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

CREATE OR REPLACE FUNCTION cehub_ai.agent_base_lease_is_current(
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
REVOKE ALL ON FUNCTION cehub_ai.agent_base_lease_is_current(uuid, uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.event_authorization_history_missing(wanted_run uuid)
RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
 SELECT EXISTS(SELECT 1 FROM cehub_ai.budget_run_links WHERE run_id=wanted_run)
 AND NOT EXISTS(SELECT 1 FROM cehub_ai.agent_authorizations WHERE run_id=wanted_run)
 AND (EXISTS(SELECT 1 FROM cehub_ai.agent_tool_intents WHERE run_id=wanted_run)
   OR EXISTS(SELECT 1 FROM cehub_ai.agent_tool_observations WHERE run_id=wanted_run)
   OR EXISTS(SELECT 1 FROM cehub_ai.model_invocations WHERE run_id=wanted_run)
   OR EXISTS(SELECT 1 FROM cehub_ai.agent_result_checkpoints WHERE run_id=wanted_run)
   OR EXISTS(SELECT 1 FROM cehub_ai.agent_run_recoveries WHERE run_id=wanted_run));
$body$;
REVOKE ALL ON FUNCTION cehub_ai.event_authorization_history_missing(uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.event_authorization_is_current(wanted_run uuid)
RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
 SELECT NOT EXISTS(SELECT 1 FROM cehub_ai.budget_run_links b WHERE b.run_id=wanted_run)
  OR EXISTS(SELECT 1 FROM cehub_ai.agent_authorizations a
    JOIN cehub_ai.agent_runs r ON r.tenant_id=a.tenant_id AND r.id=a.run_id
    JOIN cehub_ai.agent_service_principals p ON p.tenant_id=a.tenant_id AND p.id=a.principal_id
    JOIN cehub_ai.agent_subscriptions s ON s.tenant_id=p.tenant_id AND s.id=p.subscription_id
    WHERE a.run_id=wanted_run AND a.expires_at>clock_timestamp()
      AND p.revision=a.principal_revision AND p.status='active' AND s.status='active'
      AND r.subscription_id=s.id AND r.agent_key=s.agent_key
      AND a.body#>>'{scope,ref_id}'=r.project_id::text);
$body$;
REVOKE ALL ON FUNCTION cehub_ai.event_authorization_is_current(uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.issue_event_authorization(wanted_run uuid,wanted_token uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE;s cehub_ai.agent_subscriptions%ROWTYPE;
 p cehub_ai.agent_service_principals%ROWTYPE;lid uuid;deadline timestamptz;
 auth_id uuid:=gen_random_uuid();stamp timestamptz:=clock_timestamp();body jsonb;
 actor uuid; actor_count bigint; project_source jsonb; subscription_source jsonb;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE id=wanted_run FOR UPDATE;
 IF NOT FOUND OR NOT cehub_ai.agent_base_lease_is_current(r.id,wanted_token) THEN
  RAISE EXCEPTION 'Agent authorization lease is invalid' USING ERRCODE='42501';
 END IF;
 SELECT l.id,least(l.absolute_deadline,r.dispatch_deadline) INTO lid,deadline
  FROM cehub_ai.budget_lineages l JOIN cehub_ai.budget_run_links b
   ON b.tenant_id=l.tenant_id AND b.lineage_id=l.id WHERE b.run_id=r.id AND b.tenant_id=r.tenant_id;
 IF lid IS NULL THEN RETURN; END IF;
 IF EXISTS(SELECT 1 FROM cehub_ai.agent_authorizations
   WHERE run_id=r.id AND tenant_id=r.tenant_id) THEN
  IF NOT cehub_ai.event_authorization_is_current(r.id) THEN
   RAISE EXCEPTION 'Agent authorization lease is no longer valid' USING ERRCODE='42501';
  END IF;
  RETURN;
 END IF;
 IF cehub_ai.event_authorization_history_missing(r.id) THEN
  RAISE EXCEPTION 'Agent authorization lease history is unavailable' USING ERRCODE='42501';
 END IF;
 SELECT * INTO s FROM cehub_ai.agent_subscriptions
  WHERE tenant_id=r.tenant_id AND id=r.subscription_id FOR SHARE;
 stamp:=clock_timestamp();
 IF NOT FOUND OR s.status<>'active' OR s.agent_key<>r.agent_key OR deadline<=stamp THEN
  RAISE EXCEPTION 'Agent authorization lease policy is invalid' USING ERRCODE='42501';
 END IF;
 INSERT INTO cehub_ai.agent_service_principals
  VALUES(s.id,s.tenant_id,s.id,'event-agent:' || s.agent_key,'active',1,stamp,stamp)
  ON CONFLICT(tenant_id,subscription_id) DO NOTHING;
 SELECT * INTO p FROM cehub_ai.agent_service_principals
  WHERE tenant_id=s.tenant_id AND subscription_id=s.id;
 SELECT count(DISTINCT a.actor_user_id),(array_agg(DISTINCT a.actor_user_id)
   FILTER(WHERE a.actor_user_id IS NOT NULL))[1] INTO actor_count,actor
  FROM cehub_audit.audit_log a JOIN cehub_event.events e
   ON e.tenant_id=a.tenant_id AND e.event_id=a.event_id
  WHERE e.id=r.last_event_row_id AND e.tenant_id=r.tenant_id AND a.project_id=r.project_id;
 IF actor_count<>1 THEN actor:=NULL; END IF;
 project_source:=jsonb_build_object('tenant_id',r.tenant_id,'project_id',r.project_id,
  'kind','project','ref_id',r.project_id,'as_of',stamp,'digest',
  encode(sha256(convert_to(jsonb_build_object('tenant_id',r.tenant_id,'id',r.project_id)::text,
    'UTF8')),'hex'));
 subscription_source:=jsonb_build_object('tenant_id',r.tenant_id,'kind','agent_subscription',
  'ref_id',s.id,'as_of',stamp,'digest',encode(sha256(convert_to(jsonb_build_object(
    'id',s.id,'tenant_id',s.tenant_id,'agent_key',s.agent_key,'principal_revision',p.revision)::text,
    'UTF8')),'hex'));
 body:=jsonb_build_object('schema_version',1,'id',auth_id,'tenant_id',r.tenant_id,
  'scope',jsonb_build_object('kind','project','ref_id',r.project_id),'version',1,
  'owner_user_id',NULL,'sources',jsonb_build_array(project_source,subscription_source),
  'run_id',r.id,'lineage_id',lid,'principal_kind','service','principal_id',p.id,
  'trigger_actor_user_id',actor,'delegation_id',NULL,'policy_version','event-service-project.v1',
  'purpose','event_assessment','issued_at',stamp,'expires_at',deadline,
  'capability_version',r.agent_key || '.event.v1','toolset_version','internal-read-tools.v1');
 INSERT INTO cehub_ai.agent_authorizations VALUES(auth_id,r.tenant_id,r.id,lid,p.id,p.revision,
  body,stamp,deadline);
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.issue_event_authorization(uuid,uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.read_agent_authorization()
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE rid uuid:=nullif(current_setting('pdos.agent_run_id',true),'')::uuid;body jsonb;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 IF NOT cehub_ai.agent_lease_is_current(rid,token) THEN
  RAISE EXCEPTION 'Agent authorization lease is invalid' USING ERRCODE='42501';
 END IF;
 SELECT a.body INTO body FROM cehub_ai.agent_authorizations a WHERE run_id=rid;
 RETURN body;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.read_agent_authorization() FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.attach_event_authorization()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE aid uuid;
BEGIN
 SELECT id INTO aid FROM cehub_ai.agent_authorizations
  WHERE tenant_id=NEW.tenant_id AND run_id=NEW.run_id;
 IF NOT cehub_ai.event_authorization_is_current(NEW.run_id)
   OR NEW.authorization_id IS NOT NULL AND NEW.authorization_id IS DISTINCT FROM aid THEN
  RAISE EXCEPTION 'Agent receipt authorization lease is invalid' USING ERRCODE='42501';
 END IF;
 NEW.authorization_id:=aid;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.attach_event_authorization() FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.agent_authorized_project_allows(
 wanted_tenant uuid,wanted_project uuid
) RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
 SELECT EXISTS(SELECT 1 FROM cehub_ai.agent_runs r
  WHERE r.id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid
   AND r.tenant_id=wanted_tenant
  AND cehub_ai.agent_lease_is_current(r.id,
    nullif(current_setting('pdos.agent_lease_token',true),'')::uuid)
  AND (NOT EXISTS(SELECT 1 FROM cehub_ai.budget_run_links b WHERE b.run_id=r.id)
       OR r.project_id=wanted_project));
$body$;
REVOKE ALL ON FUNCTION cehub_ai.agent_authorized_project_allows(uuid,uuid) FROM PUBLIC;

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
          AND cehub_ai.agent_lease_is_current(run.id,
              nullif(current_setting('pdos.agent_lease_token', true), '')::uuid)
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
          AND cehub_ai.agent_lease_is_current(run.id,
              nullif(current_setting('pdos.agent_lease_token', true), '')::uuid)
          AND run.tenant_id = row_tenant_id
    )
$function$;

CREATE OR REPLACE FUNCTION cehub_ai.agent_tenant_agent_scope_allows(
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
          AND cehub_ai.agent_lease_is_current(run.id,
              nullif(current_setting('pdos.agent_lease_token', true), '')::uuid)
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
    PERFORM cehub_ai.expire_queued_dispatch_runs(1000);
    SELECT * INTO claimed_run
    FROM cehub_ai.agent_runs AS candidate
    WHERE candidate.status = 'queued' AND candidate.request_id IS NULL
      AND candidate.subscription_id IS NOT NULL
      AND NOT EXISTS(SELECT 1 FROM cehub_ai.event_run_pauses p
       WHERE p.run_id=candidate.id AND p.resolved_at IS NULL)
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

    PERFORM cehub_ai.issue_event_authorization(claimed_run.id,generated_lease);

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
    document.classification,
    document.media_type,
    document.extraction_status
FROM cehub_project.document_fragments AS fragment
JOIN cehub_project.documents AS document
  ON document.tenant_id = fragment.tenant_id
 AND document.project_id = fragment.project_id
 AND document.id = fragment.document_id
WHERE cehub_ai.agent_scope_allows(fragment.tenant_id, fragment.project_id)
  AND document.classification = 'internal';

CREATE OR REPLACE VIEW cehub_ai.agent_user_role_projection
WITH (security_barrier = true)
AS
SELECT
    member.tenant_id,
    member.project_id,
    project_user.role,
    count(*)::integer AS active_member_count
FROM cehub_project.project_members AS member
JOIN cehub_core.users AS project_user
  ON project_user.tenant_id = member.tenant_id
 AND project_user.id = member.user_id
WHERE cehub_ai.agent_scope_allows(member.tenant_id, member.project_id)
  AND project_user.is_active = true
GROUP BY member.tenant_id, member.project_id, project_user.role;

CREATE OR REPLACE VIEW cehub_ai.agent_memory_projection
WITH (security_barrier = true)
AS
SELECT
    memory.id AS memory_id,
    memory.tenant_id,
    memory.project_id,
    memory.title,
    memory.content,
    memory.applicability,
    memory.tags,
    memory.source_refs,
    memory.content_sha256,
    embedding.provider,
    embedding.model,
    embedding.dimensions,
    embedding.embedding
FROM cehub_memory.memories AS memory
JOIN cehub_memory.memory_embeddings AS embedding
  ON embedding.tenant_id = memory.tenant_id
 AND embedding.project_id = memory.project_id
 AND embedding.memory_id = memory.id
 AND embedding.content_sha256 = memory.content_sha256
WHERE cehub_ai.agent_scope_allows(memory.tenant_id, memory.project_id)
  AND memory.status = 'verified'
  AND EXISTS (SELECT 1 FROM cehub_memory.memory_source_assessments a
   WHERE a.tenant_id=memory.tenant_id AND a.memory_id=memory.id
    AND a.state IN ('current','manual'));

CREATE OR REPLACE VIEW cehub_ai.agent_engineering_evidence_projection
WITH (security_barrier = true)
AS
SELECT
    bom.tenant_id,
    bom.project_id,
    'development_bom'::text AS entity,
    bom.id AS entity_id,
    bom.code || ' · ' || bom.name || ' · v' || bom.version::text AS label,
    concat(
        'type=', bom.bom_type,
        '; item_count=', count(item.id)::text,
        CASE
            WHEN nullif(btrim(coalesce(bom.notes, '')), '') IS NULL THEN ''
            ELSE '; notes=' || left(bom.notes, 2000)
        END
    ) AS excerpt,
    bom.updated_at AS observed_at
FROM cehub_product.development_boms AS bom
LEFT JOIN cehub_product.development_bom_items AS item
  ON item.tenant_id = bom.tenant_id
 AND item.project_id = bom.project_id
 AND item.bom_id = bom.id
WHERE cehub_ai.agent_scope_allows(bom.tenant_id, bom.project_id)
GROUP BY bom.id
UNION ALL
SELECT
    ecr.tenant_id,
    ecr.project_id,
    'engineering_change_request'::text AS entity,
    ecr.id AS entity_id,
    ecr.code || ' · ' || ecr.title AS label,
    concat(
        'status=', ecr.status,
        '; affected_bom_count=', count(affected.bom_id)::text,
        '; reason=', left(ecr.reason, 2000)
    ) AS excerpt,
    ecr.updated_at AS observed_at
FROM cehub_product.engineering_change_requests AS ecr
LEFT JOIN cehub_product.ecr_affected_boms AS affected
  ON affected.tenant_id = ecr.tenant_id
 AND affected.project_id = ecr.project_id
 AND affected.ecr_id = ecr.id
WHERE cehub_ai.agent_scope_allows(ecr.tenant_id, ecr.project_id)
GROUP BY ecr.id;

CREATE OR REPLACE VIEW cehub_ai.agent_quality_evidence_projection
WITH (security_barrier = true)
AS
SELECT
    test_case.tenant_id,
    test_case.project_id,
    'test_case'::text AS entity,
    test_case.id AS entity_id,
    test_case.title AS label,
    concat(
        'category=', test_case.category,
        '; severity=', test_case.severity,
        '; status=', test_case.status,
        CASE
            WHEN nullif(btrim(coalesce(test_case.result_notes, '')), '') IS NULL THEN ''
            ELSE '; result=' || left(test_case.result_notes, 2000)
        END
    ) AS excerpt,
    test_case.updated_at AS observed_at
FROM cehub_quality.test_cases AS test_case
WHERE cehub_ai.agent_scope_allows(test_case.tenant_id, test_case.project_id)
  AND test_case.status IN ('failed', 'blocked')
UNION ALL
SELECT
    complaint.tenant_id,
    complaint.project_id,
    'complaint'::text AS entity,
    complaint.id AS entity_id,
    complaint.code || ' · ' || complaint.title AS label,
    concat(
        'severity=', complaint.severity,
        '; status=', complaint.status,
        '; description=', left(complaint.description, 2000),
        CASE
            WHEN nullif(btrim(coalesce(complaint.affected_scope, '')), '') IS NULL THEN ''
            ELSE '; affected_scope=' || left(complaint.affected_scope, 1000)
        END
    ) AS excerpt,
    complaint.updated_at AS observed_at
FROM cehub_quality.complaints AS complaint
WHERE cehub_ai.agent_scope_allows(complaint.tenant_id, complaint.project_id)
UNION ALL
SELECT
    ncr.tenant_id,
    ncr.project_id,
    'nonconformance_report'::text AS entity,
    ncr.id AS entity_id,
    ncr.code AS label,
    concat(
        'severity=', ncr.severity,
        '; status=', ncr.status,
        '; nonconformity=', left(ncr.nonconformity, 2000),
        '; approved_root_cause=', coalesce(left(root_cause.root_cause, 1500), 'none'),
        '; capa_action_count=', count(action.id)::text
    ) AS excerpt,
    ncr.updated_at AS observed_at
FROM cehub_quality.nonconformance_reports AS ncr
LEFT JOIN cehub_quality.root_cause_analyses AS root_cause
  ON root_cause.tenant_id = ncr.tenant_id
 AND root_cause.project_id = ncr.project_id
 AND root_cause.ncr_id = ncr.id
 AND root_cause.status = 'approved'
LEFT JOIN cehub_quality.capa_actions AS action
  ON action.tenant_id = ncr.tenant_id
 AND action.project_id = ncr.project_id
 AND action.ncr_id = ncr.id
WHERE cehub_ai.agent_scope_allows(ncr.tenant_id, ncr.project_id)
GROUP BY ncr.id, root_cause.root_cause;

CREATE OR REPLACE VIEW cehub_ai.agent_supplier_delay_projection
WITH (security_barrier = true)
AS
SELECT
    event.id AS event_row_id,
    event.tenant_id,
    event.project_id,
    project.code AS project_code,
    supplier.code AS supplier_code,
    supplier.name AS supplier_name,
    event.payload->>'expected_date' AS expected_date,
    event.payload->>'reported_date' AS reported_date,
    event.timestamp AS observed_at
FROM cehub_event.events AS event
JOIN cehub_project.projects AS project
  ON project.tenant_id = event.tenant_id
 AND project.id = event.project_id
JOIN cehub_supplier.suppliers AS supplier
  ON supplier.tenant_id = event.tenant_id
 AND supplier.id::text = event.payload->>'supplier_id'
WHERE cehub_ai.agent_tenant_agent_scope_allows(
        event.tenant_id,
        'supplier_intelligence'
    )
  AND cehub_ai.agent_authorized_project_allows(event.tenant_id,event.project_id)
  AND event.event_type = 'SUPPLIER_DELAY_REPORTED';

CREATE OR REPLACE VIEW cehub_ai.agent_portfolio_projection
WITH (security_barrier = true)
AS
SELECT
    project.tenant_id,
    project.id AS project_id,
    project.code,
    project.name,
    project.status,
    coalesce(stage.code, 'unassigned') AS stage_code,
    (
        SELECT count(*) FROM cehub_project.issues AS issue
        WHERE issue.tenant_id = project.tenant_id
          AND issue.project_id = project.id
          AND issue.status <> 'closed'
    ) AS open_issue_count,
    (
        SELECT count(*) FROM cehub_project.risks AS risk
        WHERE risk.tenant_id = project.tenant_id
          AND risk.project_id = project.id
          AND risk.status <> 'closed'
    ) AS open_risk_count,
    (
        SELECT count(*) FROM cehub_project.tasks AS task
        WHERE task.tenant_id = project.tenant_id
          AND task.project_id = project.id
          AND task.due_date < CURRENT_DATE
          AND task.status NOT IN ('done', 'skipped')
    ) AS overdue_task_count,
    (
        SELECT count(*) FROM cehub_project.gates AS gate
        WHERE gate.tenant_id = project.tenant_id
          AND gate.project_id = project.id
          AND gate.status IN ('preparing', 'reviewing')
    ) AS pending_gate_count,
    project.updated_at AS observed_at
FROM cehub_project.projects AS project
LEFT JOIN cehub_project.stages AS stage
  ON stage.tenant_id = project.tenant_id
 AND stage.workflow_id = project.workflow_id
 AND stage.id = project.current_stage_id
WHERE cehub_ai.agent_tenant_agent_scope_allows(
        project.tenant_id,
        'executive_intelligence'
    )
  AND cehub_ai.agent_authorized_project_allows(project.tenant_id,project.id)
  AND project.status IN ('approved', 'active', 'on_hold');

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
    cehub_ai.agent_user_role_projection,
    cehub_ai.agent_memory_projection,
    cehub_ai.agent_engineering_evidence_projection,
    cehub_ai.agent_quality_evidence_projection,
    cehub_ai.agent_supplier_delay_projection,
    cehub_ai.agent_portfolio_projection,
    cehub_ai.agent_model_settings_projection,
    cehub_ai.agent_model_usage_projection,
    cehub_ai.agent_run_usage_projection,
    cehub_ai.agent_finding_quality_projection
    TO pdos_agent;
GRANT INSERT ON cehub_ai.model_invocations TO pdos_agent;
GRANT EXECUTE ON FUNCTION cehub_ai.agent_scope_allows(uuid, uuid) TO pdos_agent;
GRANT EXECUTE ON FUNCTION cehub_ai.agent_tenant_scope_allows(uuid) TO pdos_agent;
GRANT EXECUTE ON FUNCTION cehub_ai.agent_tenant_agent_scope_allows(
    uuid, varchar
) TO pdos_agent;
GRANT EXECUTE ON FUNCTION cehub_ai.agent_invocation_scope_allows(
    uuid, uuid, uuid, varchar
) TO pdos_agent;
GRANT EXECUTE ON FUNCTION cehub_ai.claim_agent_run(timestamptz) TO pdos_agent;
GRANT EXECUTE ON FUNCTION cehub_ai.renew_agent_run_lease(uuid, uuid) TO pdos_agent;
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
REVOKE ALL ON FUNCTION cehub_ai.agent_tenant_agent_scope_allows(
    uuid, varchar
) FROM PUBLIC;
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

-- Run-lease scoped legacy admission; no policy or tenant arguments from the Agent.
CREATE OR REPLACE FUNCTION cehub_ai.agent_open_model_call()
RETURNS TABLE(session_id uuid, error_code text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog AS $function$
DECLARE active_run cehub_ai.agent_runs%ROWTYPE;
BEGIN
    SELECT * INTO active_run FROM cehub_ai.agent_runs
      WHERE id = nullif(current_setting('pdos.agent_run_id', true), '')::uuid;
    IF NOT FOUND OR NOT cehub_ai.agent_invocation_scope_allows(
        active_run.tenant_id, active_run.project_id, active_run.id, active_run.agent_key
    ) THEN RAISE EXCEPTION 'Agent model call scope invalid' USING ERRCODE = '42501'; END IF;
    RETURN QUERY SELECT * FROM cehub_ai.open_model_call(active_run.tenant_id,
        active_run.id, active_run.project_id, active_run.agent_key::text, 'legacy'::text);
END
$function$;

CREATE OR REPLACE FUNCTION cehub_ai.agent_finish_model_call(wanted_session uuid, trace_id uuid)
RETURNS void LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog AS $function$
DECLARE call cehub_ai.model_call_sessions%ROWTYPE;
BEGIN
    SELECT * INTO call FROM cehub_ai.model_call_sessions WHERE id = wanted_session;
    IF NOT FOUND OR NOT cehub_ai.agent_invocation_scope_allows(
        call.tenant_id, call.project_id, call.run_id, call.agent_key
    ) THEN RAISE EXCEPTION 'Agent model call scope invalid' USING ERRCODE = '42501'; END IF;
    PERFORM cehub_ai.finish_model_call(call.tenant_id, wanted_session, trace_id);
END
$function$;

CREATE OR REPLACE FUNCTION cehub_ai.agent_mark_model_call_unknown(wanted_session uuid)
RETURNS void LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog AS $function$
DECLARE call cehub_ai.model_call_sessions%ROWTYPE;
BEGIN
    SELECT * INTO call FROM cehub_ai.model_call_sessions WHERE id = wanted_session;
    IF NOT FOUND OR NOT cehub_ai.agent_invocation_scope_allows(
        call.tenant_id, call.project_id, call.run_id, call.agent_key
    ) THEN RAISE EXCEPTION 'Agent model call scope invalid' USING ERRCODE = '42501'; END IF;
    PERFORM cehub_ai.mark_model_call_unknown(call.tenant_id, wanted_session);
END
$function$;

REVOKE ALL ON FUNCTION cehub_ai.agent_open_model_call() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.agent_finish_model_call(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.agent_mark_model_call_unknown(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION cehub_ai.agent_open_model_call() TO pdos_agent;
GRANT EXECUTE ON FUNCTION cehub_ai.agent_finish_model_call(uuid, uuid) TO pdos_agent;
GRANT EXECUTE ON FUNCTION cehub_ai.agent_mark_model_call_unknown(uuid) TO pdos_agent;


-- Only advances model attempts already reserved by a trusted service. No policy,
-- amount, tenant or run arguments; the lease is the authorization boundary.
CREATE OR REPLACE FUNCTION cehub_ai.agent_transition_model_budget(
    wanted_attempt uuid, wanted_action text, evidence_body text
) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog AS $function$
DECLARE active_run cehub_ai.agent_runs%ROWTYPE;
BEGIN
    SELECT * INTO active_run FROM cehub_ai.agent_runs
      WHERE id = nullif(current_setting('pdos.agent_run_id', true), '')::uuid;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Agent budget scope invalid' USING ERRCODE = '42501';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('pdos-budget:' || active_run.tenant_id::text, 0));
    SELECT * INTO active_run FROM cehub_ai.agent_runs WHERE id = active_run.id FOR SHARE;
    IF NOT cehub_ai.agent_invocation_scope_allows(
        active_run.tenant_id, active_run.project_id, active_run.id, active_run.agent_key
    ) THEN RAISE EXCEPTION 'Agent budget scope invalid' USING ERRCODE = '42501'; END IF;
    RETURN cehub_ai.transition_bound_model_budget(active_run.tenant_id,
        active_run.id, wanted_attempt, wanted_action, evidence_body);
END
$function$;
REVOKE ALL ON FUNCTION cehub_ai.agent_transition_model_budget(uuid, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION cehub_ai.agent_transition_model_budget(uuid, text, text) TO pdos_agent;

-- A lease can read only its service-frozen lineage; it cannot create/change one.
CREATE OR REPLACE FUNCTION cehub_ai.agent_budget_profile()
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog AS $function$
DECLARE active_run cehub_ai.agent_runs%ROWTYPE; lineage cehub_ai.budget_lineages%ROWTYPE;
BEGIN
    SELECT * INTO active_run FROM cehub_ai.agent_runs
      WHERE id = nullif(current_setting('pdos.agent_run_id', true), '')::uuid;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Agent budget scope invalid' USING ERRCODE = '42501';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('pdos-budget:' || active_run.tenant_id::text, 0));
    SELECT * INTO active_run FROM cehub_ai.agent_runs WHERE id = active_run.id FOR SHARE;
    IF NOT cehub_ai.agent_invocation_scope_allows(
        active_run.tenant_id, active_run.project_id, active_run.id, active_run.agent_key
    ) THEN RAISE EXCEPTION 'Agent budget scope invalid' USING ERRCODE = '42501'; END IF;
    SELECT l.* INTO lineage FROM cehub_ai.budget_lineages l
      JOIN cehub_ai.budget_run_links r ON r.tenant_id = l.tenant_id AND r.lineage_id = l.id
      WHERE r.tenant_id = active_run.tenant_id AND r.run_id = active_run.id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'BUDGET_RUN_UNBOUND' USING ERRCODE = '22023';
    END IF;
    RETURN jsonb_build_object('tenant_id',active_run.tenant_id,'run_id',active_run.id,
        'project_id',active_run.project_id,'agent_key',active_run.agent_key,
        'lineage_id',lineage.id,'profile',lineage.profile,'profile_digest',lineage.profile_digest);
END
$function$;

CREATE OR REPLACE FUNCTION cehub_ai.agent_reserve_model_budget(
    wanted_attempt uuid, measured_input bigint, binding jsonb
) RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog AS $function$
DECLARE bound jsonb; setting cehub_ai.tenant_model_settings%ROWTYPE;
BEGIN
    bound := cehub_ai.agent_budget_profile();
    SELECT * INTO setting FROM cehub_ai.tenant_model_settings
      WHERE tenant_id = (bound->>'tenant_id')::uuid FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'BUDGET_TENANT_POLICY_REQUIRED' USING ERRCODE = '22023';
    END IF;
    IF binding IS NULL OR jsonb_typeof(binding->'output_limit') IS DISTINCT FROM 'number'
       OR (binding->>'output_limit') !~ '^[1-9][0-9]{0,17}$' THEN
        RAISE EXCEPTION 'BUDGET_REQUEST_BINDING_INVALID' USING ERRCODE = '22023';
    END IF;
    IF binding->>'provider' IS DISTINCT FROM setting.provider
       OR binding->>'model' IS DISTINCT FROM setting.model THEN
        RAISE EXCEPTION 'BUDGET_MODEL_SELECTION_CHANGED' USING ERRCODE = '22023';
    END IF;
    RETURN cehub_ai.reserve_run_budget((bound->>'tenant_id')::uuid,(bound->>'run_id')::uuid,
        wanted_attempt,'model',measured_input,(binding->>'output_limit')::bigint,
        setting.daily_token_budget,binding);
END
$function$;

CREATE OR REPLACE FUNCTION cehub_ai.agent_open_budgeted_model_call()
RETURNS TABLE(session_id uuid,error_code text) LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog AS $function$
DECLARE bound jsonb;
BEGIN
    bound := cehub_ai.agent_budget_profile();
    IF NOT EXISTS (SELECT 1 FROM cehub_ai.tenant_model_settings
        WHERE tenant_id = (bound->>'tenant_id')::uuid) THEN
        RETURN QUERY SELECT NULL::uuid,'BUDGET_TENANT_POLICY_REQUIRED'::text; RETURN;
    END IF;
    RETURN QUERY SELECT * FROM cehub_ai.open_model_call((bound->>'tenant_id')::uuid,
        (bound->>'run_id')::uuid,(bound->>'project_id')::uuid,bound->>'agent_key','budgeted');
EXCEPTION WHEN invalid_parameter_value THEN
    RETURN QUERY SELECT NULL::uuid,SQLERRM;
END
$function$;
REVOKE ALL ON FUNCTION cehub_ai.agent_budget_profile() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.agent_reserve_model_budget(uuid,bigint,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.agent_open_budgeted_model_call() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION cehub_ai.agent_budget_profile() TO pdos_agent;
GRANT EXECUTE ON FUNCTION cehub_ai.agent_reserve_model_budget(uuid,bigint,jsonb) TO pdos_agent;
GRANT EXECUTE ON FUNCTION cehub_ai.agent_open_budgeted_model_call() TO pdos_agent;


-- 0072: lease-scoped active execution budget check.
CREATE OR REPLACE FUNCTION cehub_ai.agent_check_active_budget()
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
GRANT EXECUTE ON FUNCTION cehub_ai.agent_check_active_budget() TO pdos_agent;

-- 0073: completed result checkpoints and database-only recovery.
CREATE OR REPLACE FUNCTION cehub_ai.save_agent_result_checkpoint(
    wanted_run uuid,wanted_token uuid,body_text text
) RETURNS uuid LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; payload jsonb; invocation uuid;
    previous cehub_ai.agent_result_checkpoints%ROWTYPE; new_id uuid := gen_random_uuid();
BEGIN
    SELECT * INTO r FROM cehub_ai.agent_runs WHERE id=wanted_run FOR UPDATE;
    IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(wanted_run,wanted_token) THEN
        RAISE EXCEPTION 'Agent run lease is invalid' USING ERRCODE='42501';
    END IF;
    IF body_text IS NULL OR octet_length(body_text)>262144 THEN
        RAISE EXCEPTION 'AGENT_CHECKPOINT_INVALID' USING ERRCODE='22023';
    END IF;
    payload := body_text::jsonb;
    IF jsonb_typeof(payload) IS DISTINCT FROM 'object'
       OR payload->>'version' IS DISTINCT FROM 'agent-result.v1'
       OR payload#>>'{context,run_id}' IS DISTINCT FROM r.id::text
       OR payload#>>'{context,tenant_id}' IS DISTINCT FROM r.tenant_id::text
       OR payload#>>'{context,project_id}' IS DISTINCT FROM r.project_id::text
       OR payload#>>'{context,agent_key}' IS DISTINCT FROM r.agent_key
       OR payload->>'runtime_digest' IS NULL
       OR payload->>'runtime_digest' !~ '^[a-f0-9]{64}$'
       OR (payload#>>'{result,status}' IN ('succeeded','degraded')) IS NOT TRUE THEN
        RAISE EXCEPTION 'AGENT_CHECKPOINT_INVALID' USING ERRCODE='22023';
    END IF;
    invocation := (payload#>>'{result,invocation_id}')::uuid;
    IF invocation IS NULL OR NOT EXISTS(SELECT 1 FROM cehub_ai.model_invocations
       WHERE id=invocation AND tenant_id=r.tenant_id AND run_id=r.id
         AND project_id=r.project_id AND agent_key=r.agent_key
         AND (payload#>>'{result,status}' <> 'succeeded' OR status='succeeded')) THEN
        RAISE EXCEPTION 'AGENT_CHECKPOINT_TRACE_INVALID' USING ERRCODE='22023';
    END IF;
    SELECT * INTO previous FROM cehub_ai.agent_result_checkpoints
      WHERE tenant_id=r.tenant_id AND run_id=r.id;
    IF FOUND THEN
        IF previous.body IS DISTINCT FROM payload THEN
            RAISE EXCEPTION 'AGENT_CHECKPOINT_CONFLICT' USING ERRCODE='22023';
        END IF;
        RETURN previous.id;
    END IF;
    IF NOT cehub_ai.agent_lease_is_current(wanted_run,wanted_token) THEN
        RAISE EXCEPTION 'Agent run lease expired before checkpoint' USING ERRCODE='42501';
    END IF;
    INSERT INTO cehub_ai.agent_result_checkpoints VALUES(new_id,r.tenant_id,r.id,invocation,payload,
        encode(sha256(convert_to(payload::text,'UTF8')),'hex'),clock_timestamp());
    RETURN new_id;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.save_agent_result_checkpoint(uuid,uuid,text) FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.load_agent_result_checkpoint(
    wanted_run uuid,wanted_token uuid
) RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; checkpoint cehub_ai.agent_result_checkpoints%ROWTYPE;
BEGIN
    SELECT * INTO r FROM cehub_ai.agent_runs WHERE id=wanted_run;
    IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(wanted_run,wanted_token) THEN
        RAISE EXCEPTION 'Agent run lease is invalid' USING ERRCODE='42501';
    END IF;
    IF r.run_context->>'_resume_checkpoint_id' IS NULL THEN RETURN NULL; END IF;
    IF NOT EXISTS(SELECT 1 FROM cehub_ai.agent_subscriptions
        WHERE id=r.subscription_id AND tenant_id=r.tenant_id AND status='active') THEN
        RAISE EXCEPTION 'AGENT_RECOVERY_SUBSCRIPTION_PAUSED' USING ERRCODE='22023';
    END IF;
    IF EXISTS(SELECT 1 FROM cehub_ai.budget_run_links
              WHERE tenant_id=r.tenant_id AND run_id=r.id) THEN
        PERFORM cehub_ai.check_run_active_budget(r.tenant_id,r.id);
    END IF;
    SELECT * INTO checkpoint FROM cehub_ai.agent_result_checkpoints
      WHERE tenant_id=r.tenant_id AND run_id=r.id
        AND id=(r.run_context->>'_resume_checkpoint_id')::uuid;
    IF NOT FOUND OR checkpoint.body_sha256 IS DISTINCT FROM
        encode(sha256(convert_to(checkpoint.body::text,'UTF8')),'hex') THEN
        RAISE EXCEPTION 'AGENT_CHECKPOINT_MISSING_OR_CORRUPT' USING ERRCODE='22023';
    END IF;
    RETURN checkpoint.body;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.load_agent_result_checkpoint(uuid,uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.recover_expired_agent_runs(batch_limit integer)
RETURNS TABLE(run_id uuid,action text,reason text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; checkpoint cehub_ai.agent_result_checkpoints%ROWTYPE;
    step_cp cehub_ai.agent_loop_checkpoints%ROWTYPE; receipt uuid; result_action text; stop_reason text; attempts bigint; attempt_limit integer;
    expired_token uuid; observed_at timestamptz;
BEGIN
    IF batch_limit IS NULL OR batch_limit<1 OR batch_limit>1000 THEN
        RAISE EXCEPTION 'invalid recovery batch size' USING ERRCODE='22023';
    END IF;
    FOR r IN SELECT * FROM cehub_ai.agent_runs
      WHERE status='running' AND subscription_id IS NOT NULL AND request_id IS NULL
        AND (nullif(run_context->>'_lease_expires_at','')::timestamptz <= clock_timestamp()
             OR NOT cehub_ai.event_authorization_is_current(id))
        AND nullif(run_context->>'_lease_token','') IS NOT NULL
      ORDER BY updated_at,id LIMIT batch_limit FOR UPDATE SKIP LOCKED LOOP
        observed_at := clock_timestamp();
        expired_token := (r.run_context->>'_lease_token')::uuid;
        IF cehub_ai.agent_lease_is_current(r.id,expired_token) THEN CONTINUE; END IF;
        SELECT * INTO checkpoint FROM cehub_ai.agent_result_checkpoints c
          WHERE c.tenant_id=r.tenant_id AND c.run_id=r.id;
        SELECT * INTO step_cp FROM cehub_ai.agent_loop_checkpoints c
          WHERE c.tenant_id=r.tenant_id AND c.run_id=r.id ORDER BY next_step DESC LIMIT 1;
        SELECT f.id INTO receipt FROM cehub_ai.findings f
          WHERE f.tenant_id=r.tenant_id AND f.run_id=r.id ORDER BY f.created_at,f.id LIMIT 1;
        result_action := 'stopped'; stop_reason := NULL;
        IF receipt IS NOT NULL THEN
            result_action := 'receipt_completed';
        ELSIF NOT cehub_ai.event_authorization_is_current(r.id)
          AND (r.dispatch_deadline IS NULL OR r.dispatch_deadline>clock_timestamp())
          AND NOT EXISTS(SELECT 1 FROM cehub_ai.budget_run_links b
            JOIN cehub_ai.budget_lineages l ON l.tenant_id=b.tenant_id AND l.id=b.lineage_id
            WHERE b.run_id=r.id AND l.absolute_deadline<=clock_timestamp()) THEN
            stop_reason := 'AGENT_AUTHORIZATION_CHANGED';
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
        ELSIF EXISTS(SELECT 1 FROM cehub_ai.budget_run_links b
            JOIN cehub_ai.budget_lineages l ON l.tenant_id=b.tenant_id AND l.id=b.lineage_id
            WHERE b.run_id=r.id AND l.absolute_deadline<=clock_timestamp()) THEN
            stop_reason := 'BUDGET_LINEAGE_EXPIRED';
        ELSIF checkpoint.id IS NULL AND step_cp.id IS NOT NULL AND EXISTS(
            SELECT 1 FROM cehub_ai.model_invocations m WHERE m.tenant_id=r.tenant_id
             AND m.run_id=r.id AND NOT m.id=ANY(step_cp.trace_ids)) THEN
            stop_reason := 'AGENT_LOOP_CHECKPOINT_INCOMPLETE';
        ELSIF checkpoint.id IS NULL AND step_cp.id IS NULL THEN
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
        INSERT INTO cehub_ai.agent_run_recoveries
        (id,tenant_id,run_id,checkpoint_id,finding_id,action,reason,expired_lease_token,created_at,
         loop_checkpoint_id) VALUES(gen_random_uuid(),r.tenant_id,r.id,
            checkpoint.id,receipt,result_action,stop_reason,expired_token,observed_at,step_cp.id);
        IF result_action='resume_queued' THEN
            UPDATE cehub_ai.agent_runs SET status='queued',started_at=NULL,completed_at=NULL,
              error_code=NULL,updated_at=observed_at,
              run_context=(run_context - '_lease_token' - '_lease_expires_at' - '_lease_renewed_at')
                || jsonb_build_object('_resume_checkpoint_id',checkpoint.id,'_resume_loop_checkpoint_id',CASE WHEN checkpoint.id IS NULL THEN step_cp.id ELSE NULL END)
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

GRANT EXECUTE ON FUNCTION cehub_ai.save_agent_result_checkpoint(uuid,uuid,text),
    cehub_ai.load_agent_result_checkpoint(uuid,uuid) TO pdos_agent;
GRANT EXECUTE ON FUNCTION cehub_ai.recover_expired_agent_runs(integer) TO pdos_worker;

CREATE OR REPLACE FUNCTION cehub_ai.expire_queued_dispatch_runs(batch_limit integer)
RETURNS integer LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE count_expired integer;
BEGIN
 IF batch_limit IS NULL OR batch_limit<1 OR batch_limit>1000 THEN
  RAISE EXCEPTION 'invalid expiry batch size' USING ERRCODE='22023';
 END IF;
 WITH due AS (SELECT r.id,CASE
    WHEN r.dispatch_deadline<=clock_timestamp() THEN 'AGENT_TRIGGER_DEADLINE_EXCEEDED'
    WHEN EXISTS(SELECT 1 FROM cehub_ai.budget_run_links b JOIN cehub_ai.budget_lineages l
      ON l.tenant_id=b.tenant_id AND l.id=b.lineage_id WHERE b.run_id=r.id
       AND l.absolute_deadline<=clock_timestamp()) THEN 'BUDGET_LINEAGE_EXPIRED'
    ELSE 'AGENT_AUTHORIZATION_CHANGED' END AS reason
   FROM cehub_ai.agent_runs r WHERE r.status IN ('debouncing','queued')
    AND r.request_id IS NULL AND r.subscription_id IS NOT NULL AND (
     cehub_ai.event_authorization_history_missing(r.id) OR
     r.dispatch_deadline<=clock_timestamp()
     OR EXISTS(SELECT 1 FROM cehub_ai.budget_run_links b JOIN cehub_ai.budget_lineages l
       ON l.tenant_id=b.tenant_id AND l.id=b.lineage_id WHERE b.run_id=r.id
        AND (l.absolute_deadline<=clock_timestamp() OR NOT EXISTS(
          SELECT 1 FROM cehub_ai.agent_subscriptions s WHERE s.id=r.subscription_id
           AND s.tenant_id=r.tenant_id AND s.status='active')))
     OR EXISTS(SELECT 1 FROM cehub_ai.agent_authorizations a WHERE a.run_id=r.id
       AND NOT cehub_ai.event_authorization_is_current(r.id)))
   ORDER BY r.dispatch_deadline,r.id LIMIT batch_limit FOR UPDATE OF r SKIP LOCKED)
 UPDATE cehub_ai.agent_runs r SET status='failed',error_code=due.reason,
   completed_at=clock_timestamp(),updated_at=clock_timestamp() FROM due WHERE due.id=r.id;
 GET DIAGNOSTICS count_expired=ROW_COUNT;
 RETURN count_expired;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.expire_queued_dispatch_runs(integer) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION cehub_ai.expire_queued_dispatch_runs(integer) TO pdos_worker;

GRANT INSERT(dispatch_key,dispatch_policy,dispatch_deadline) ON cehub_ai.agent_runs TO pdos_worker;

CREATE OR REPLACE FUNCTION cehub_ai.append_agent_tool_observation(
 wanted_key varchar,wanted_tool varchar,input_text text,output_text text,metadata_text text
) RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; old cehub_ai.agent_tool_observations%ROWTYPE;
 args jsonb; result jsonb; meta jsonb; observation_id uuid:=gen_random_uuid();
 next_sequence integer;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid FOR UPDATE;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent observation lease is invalid' USING ERRCODE='42501';
 END IF;
 IF wanted_key IS NULL OR length(wanted_key) NOT BETWEEN 1 AND 128
  OR input_text IS NULL OR output_text IS NULL OR metadata_text IS NULL
  OR octet_length(input_text)+octet_length(output_text)+octet_length(metadata_text)>262144 THEN
  RAISE EXCEPTION 'AGENT_OBSERVATION_INVALID' USING ERRCODE='22023';
 END IF;
 IF (wanted_tool IN ('get_project_context','get_recent_events','search_memory') OR
  wanted_tool='get_engineering_evidence' AND r.agent_key='engineering_intelligence' OR
  wanted_tool='get_quality_evidence' AND r.agent_key='quality_intelligence' OR
  wanted_tool='get_supplier_delay_evidence' AND r.agent_key='supplier_intelligence' OR
  wanted_tool='get_portfolio_brief' AND r.agent_key='executive_intelligence') IS NOT TRUE THEN
  RAISE EXCEPTION 'AGENT_OBSERVATION_TOOL_INVALID' USING ERRCODE='22023';
 END IF;
 args:=input_text::jsonb; result:=output_text::jsonb; meta:=metadata_text::jsonb;
 IF jsonb_typeof(args) IS DISTINCT FROM 'object' OR jsonb_typeof(result) IS DISTINCT FROM 'object'
  OR jsonb_typeof(meta) IS DISTINCT FROM 'object'
  OR args->>'project_id' IS DISTINCT FROM r.project_id::text
  OR meta->>'tenant_id' IS DISTINCT FROM r.tenant_id::text
  OR meta->>'run_id' IS DISTINCT FROM r.id::text
  OR jsonb_typeof(meta->'sources') IS DISTINCT FROM 'array'
  OR (meta->>'status' IN ('completed','partial','unavailable','failed','cancelled')) IS NOT TRUE
  OR meta->>'input_digest' !~ '^[a-f0-9]{64}$' OR meta->>'input_digest' IS NULL
  OR meta->>'output_digest' !~ '^[a-f0-9]{64}$' OR meta->>'output_digest' IS NULL THEN
  RAISE EXCEPTION 'AGENT_OBSERVATION_INVALID' USING ERRCODE='22023';
 END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(meta->'sources') s
   WHERE s->>'tenant_id' IS DISTINCT FROM r.tenant_id::text) THEN
  RAISE EXCEPTION 'AGENT_OBSERVATION_SOURCE_SCOPE' USING ERRCODE='22023';
 END IF;
 meta:=meta || jsonb_build_object(
  'input_digest',encode(sha256(convert_to(args::text,'UTF8')),'hex'),
  'output_digest',encode(sha256(convert_to(result::text,'UTF8')),'hex'));
 SELECT * INTO old FROM cehub_ai.agent_tool_observations
  WHERE tenant_id=r.tenant_id AND run_id=r.id AND call_key=wanted_key;
 IF FOUND THEN
  IF old.tool_key IS DISTINCT FROM wanted_tool OR old.input_body IS DISTINCT FROM args
   OR old.output_body IS DISTINCT FROM result OR
   (old.metadata - 'id' - 'sequence' - 'observed_at' - 'as_of' - 'sources') IS DISTINCT FROM
   (meta - 'id' - 'sequence' - 'observed_at' - 'as_of' - 'sources') OR
   (SELECT jsonb_agg(s - 'as_of') FROM jsonb_array_elements(old.metadata->'sources') s)
   IS DISTINCT FROM
   (SELECT jsonb_agg(s - 'as_of') FROM jsonb_array_elements(meta->'sources') s) THEN
   RAISE EXCEPTION 'AGENT_OBSERVATION_CONFLICT' USING ERRCODE='22023';
  END IF;
  RETURN old.metadata;
 END IF;
 SELECT coalesce(max(sequence),0)+1 INTO next_sequence FROM cehub_ai.agent_tool_observations
  WHERE tenant_id=r.tenant_id AND run_id=r.id;
 meta:=meta || jsonb_build_object('id',observation_id,'sequence',next_sequence,
                                 'observed_at',clock_timestamp());
 IF NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent observation lease expired' USING ERRCODE='42501';
 END IF;
 INSERT INTO cehub_ai.agent_tool_observations VALUES(observation_id,r.tenant_id,r.id,
  next_sequence,wanted_key,wanted_tool,args,result,meta,clock_timestamp());
 RETURN meta;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.append_agent_tool_observation(varchar,varchar,text,text,text)
 FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.freeze_agent_context_receipt(
 wanted_call uuid,body_text text,observation_ids uuid[]
) RETURNS uuid LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; previous cehub_ai.agent_context_receipts%ROWTYPE;
 payload jsonb; receipt_id uuid:=gen_random_uuid(); previous_ids uuid[]; actual_ids uuid[];
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid FOR UPDATE;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent context receipt lease is invalid' USING ERRCODE='42501';
 END IF;
 IF wanted_call IS NULL OR body_text IS NULL OR octet_length(body_text)>262144
  OR observation_ids IS NULL OR coalesce(cardinality(observation_ids),0) NOT BETWEEN 1 AND 1000 THEN
  RAISE EXCEPTION 'AGENT_CONTEXT_RECEIPT_INVALID' USING ERRCODE='22023';
 END IF;
 payload:=body_text::jsonb;
 IF payload#>>'{context,project,id}' IS DISTINCT FROM r.project_id::text THEN
  RAISE EXCEPTION 'AGENT_CONTEXT_RECEIPT_SCOPE' USING ERRCODE='22023';
 END IF;
 SELECT array_agg(id ORDER BY sequence) INTO actual_ids FROM cehub_ai.agent_tool_observations
  WHERE tenant_id=r.tenant_id AND run_id=r.id AND id=ANY(observation_ids);
 IF actual_ids IS DISTINCT FROM observation_ids THEN
  RAISE EXCEPTION 'AGENT_CONTEXT_OBSERVATIONS_INVALID' USING ERRCODE='22023';
 END IF;
 SELECT * INTO previous FROM cehub_ai.agent_context_receipts
  WHERE tenant_id=r.tenant_id AND run_id=r.id AND model_call_id=wanted_call;
 IF FOUND THEN
  SELECT array_agg(observation_id ORDER BY position) INTO previous_ids
   FROM cehub_ai.agent_context_observations WHERE context_receipt_id=previous.id;
  IF previous.body IS DISTINCT FROM payload OR previous_ids IS DISTINCT FROM observation_ids THEN
   RAISE EXCEPTION 'AGENT_CONTEXT_RECEIPT_CONFLICT' USING ERRCODE='22023';
  END IF;
  RETURN previous.id;
 END IF;
 IF NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent context receipt lease expired' USING ERRCODE='42501';
 END IF;
 INSERT INTO cehub_ai.agent_context_receipts VALUES(receipt_id,r.tenant_id,r.id,wanted_call,payload,
  encode(sha256(convert_to(payload::text,'UTF8')),'hex'),clock_timestamp());
 INSERT INTO cehub_ai.agent_context_observations
  SELECT r.tenant_id,r.id,receipt_id,value,ordinality
    FROM unnest(observation_ids) WITH ORDINALITY AS ids(value,ordinality);
 RETURN receipt_id;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.freeze_agent_context_receipt(uuid,text,uuid[]) FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.verify_agent_context_receipt(
 wanted_receipt uuid,wanted_call uuid,body_text text
) RETURNS void LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; receipt cehub_ai.agent_context_receipts%ROWTYPE;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent context receipt lease is invalid' USING ERRCODE='42501';
 END IF;
 SELECT * INTO receipt FROM cehub_ai.agent_context_receipts
  WHERE id=wanted_receipt AND tenant_id=r.tenant_id AND run_id=r.id AND model_call_id=wanted_call;
 IF NOT FOUND OR receipt.body IS DISTINCT FROM body_text::jsonb
  OR receipt.body_sha256 IS DISTINCT FROM
  encode(sha256(convert_to(receipt.body::text,'UTF8')),'hex') THEN
  RAISE EXCEPTION 'AGENT_CONTEXT_RECEIPT_MISMATCH' USING ERRCODE='22023';
 END IF;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.verify_agent_context_receipt(uuid,uuid,text) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION
 cehub_ai.append_agent_tool_observation(varchar,varchar,text,text,text),
 cehub_ai.freeze_agent_context_receipt(uuid,text,uuid[]),
 cehub_ai.verify_agent_context_receipt(uuid,uuid,text) TO pdos_agent;


-- Durable pre-handler tool intent and single dispatch.
CREATE OR REPLACE FUNCTION cehub_ai.tool_intent_call_count(
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
GRANT EXECUTE ON FUNCTION cehub_ai.prepare_agent_tool_call(uuid,varchar,varchar,text),
 cehub_ai.dispatch_agent_tool_call(uuid) TO pdos_agent;

CREATE OR REPLACE FUNCTION cehub_ai.read_agent_loop_binding()
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent loop binding lease is invalid' USING ERRCODE='42501';
 END IF;
 RETURN r.loop_binding;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.read_agent_loop_binding() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION cehub_ai.read_agent_loop_binding() TO pdos_agent;

GRANT EXECUTE ON FUNCTION cehub_ai.read_agent_authorization(),
 cehub_ai.agent_authorized_project_allows(uuid,uuid) TO pdos_agent;


CREATE OR REPLACE FUNCTION cehub_ai.agent_manifest_sources_are_current(
 wanted_tenant uuid,wanted_run uuid,wanted_receipt uuid
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE pid uuid;
BEGIN
 SELECT project_id INTO pid FROM cehub_ai.agent_runs
  WHERE tenant_id=wanted_tenant AND id=wanted_run;
 IF NOT FOUND OR NOT cehub_ai.event_authorization_is_current(wanted_run) THEN RETURN false; END IF;
 RETURN NOT EXISTS(SELECT 1 FROM cehub_ai.agent_context_observations link
  JOIN cehub_ai.agent_tool_observations o ON o.id=link.observation_id
   AND o.tenant_id=link.tenant_id AND o.run_id=link.run_id,
   LATERAL jsonb_array_elements(coalesce(o.output_body->'items','[]'::jsonb)) item
  WHERE link.tenant_id=wanted_tenant AND link.run_id=wanted_run
   AND link.context_receipt_id=wanted_receipt AND o.tool_key='search_memory' AND NOT EXISTS(
    SELECT 1 FROM cehub_memory.memories memory JOIN cehub_memory.memory_embeddings embedding
     ON embedding.tenant_id=memory.tenant_id AND embedding.project_id=memory.project_id
      AND embedding.memory_id=memory.id AND embedding.content_sha256=memory.content_sha256
     WHERE memory.tenant_id=wanted_tenant AND memory.project_id=pid AND memory.status='verified'
      AND memory.id::text=item->>'memory_id' AND memory.content_sha256=item->>'content_sha256'));
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.agent_manifest_sources_are_current(uuid,uuid,uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.verify_agent_context_sources(wanted_receipt uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent context source lease is invalid' USING ERRCODE='42501';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.agent_context_receipts
  WHERE tenant_id=r.tenant_id AND run_id=r.id AND id=wanted_receipt) THEN
  RAISE EXCEPTION 'AGENT_MANIFEST_RECEIPT_INVALID' USING ERRCODE='22023';
 END IF;
 IF EXISTS(SELECT 1 FROM cehub_ai.agent_authorizations WHERE run_id=r.id)
  AND NOT cehub_ai.agent_manifest_sources_are_current(r.tenant_id,r.id,wanted_receipt) THEN
  RAISE EXCEPTION 'AGENT_MANIFEST_SOURCE_ACCESS_CHANGED' USING ERRCODE='22023';
 END IF;
 RETURN true;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.verify_agent_context_sources(uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.verify_agent_manifest_sources()
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent manifest source lease is invalid' USING ERRCODE='42501';
 END IF;
 IF EXISTS(SELECT 1 FROM cehub_ai.agent_context_manifests m
  WHERE m.tenant_id=r.tenant_id AND m.run_id=r.id
   AND EXISTS(SELECT 1 FROM cehub_ai.budget_journal j
    WHERE j.tenant_id=m.tenant_id AND j.run_id=m.run_id AND j.attempt_id=m.attempt_id
     AND j.dispatched_at IS NOT NULL)
   AND NOT cehub_ai.agent_manifest_sources_are_current(r.tenant_id,r.id,m.context_receipt_id)) THEN
  RAISE EXCEPTION 'AGENT_MANIFEST_SOURCE_ACCESS_CHANGED' USING ERRCODE='22023';
 END IF;
 RETURN true;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.verify_agent_manifest_sources() FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.bind_agent_runtime_bundle(body_text text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; supplied jsonb;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid FOR UPDATE;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent bundle lease is invalid' USING ERRCODE='42501';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.agent_authorizations WHERE run_id=r.id) THEN
  RETURN NULL;
 END IF;
 IF body_text IS NULL OR octet_length(body_text)>524288 THEN
  RAISE EXCEPTION 'AGENT_BUNDLE_INVALID' USING ERRCODE='22023';
 END IF;
 supplied:=body_text::jsonb;
 IF supplied->>'version' IS DISTINCT FROM 'event-runtime-bundle.v1'
  OR supplied#>>'{compiled,agent_key}' IS DISTINCT FROM r.agent_key
  OR (supplied->>'release_bundle_version' ~ '^sha256:[a-f0-9]{64}$') IS NOT TRUE
  OR (supplied->>'capability_version' ~ '^sha256:[a-f0-9]{64}$') IS NOT TRUE
  OR (supplied->>'toolset_version' ~ '^sha256:[a-f0-9]{64}$') IS NOT TRUE
  OR (supplied->>'projection_version' ~ '^sha256:[a-f0-9]{64}$') IS NOT TRUE
  OR (supplied->>'policy_version' ~ '^sha256:[a-f0-9]{64}$') IS NOT TRUE THEN
  RAISE EXCEPTION 'AGENT_BUNDLE_INVALID' USING ERRCODE='22023';
 END IF;
 IF r.execution_bundle IS NOT NULL THEN
  IF r.execution_bundle IS DISTINCT FROM supplied THEN
   RAISE EXCEPTION 'AGENT_BUNDLE_VERSION_CHANGED' USING ERRCODE='22023';
  END IF;
  RETURN r.execution_bundle;
 END IF;
 IF EXISTS(SELECT 1 FROM cehub_ai.agent_tool_intents WHERE run_id=r.id)
  OR EXISTS(SELECT 1 FROM cehub_ai.model_invocations WHERE run_id=r.id)
  OR EXISTS(SELECT 1 FROM cehub_ai.agent_result_checkpoints WHERE run_id=r.id) THEN
  RAISE EXCEPTION 'AGENT_BUNDLE_HISTORY_UNAVAILABLE' USING ERRCODE='22023';
 END IF;
 UPDATE cehub_ai.agent_runs SET execution_bundle=supplied WHERE id=r.id;
 RETURN supplied;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.bind_agent_runtime_bundle(text) FROM PUBLIC;

CREATE OR REPLACE FUNCTION cehub_ai.freeze_agent_context_manifest(
 wanted_receipt uuid,wanted_attempt uuid,pins_text text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE;receipt cehub_ai.agent_context_receipts%ROWTYPE;
 admission cehub_ai.budget_journal%ROWTYPE;previous cehub_ai.agent_context_manifests%ROWTYPE;
 first_manifest cehub_ai.agent_context_manifests%ROWTYPE;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
 aid uuid;mid uuid:=gen_random_uuid();stamp timestamptz:=clock_timestamp();n integer;
 pins jsonb;body jsonb;observations jsonb;sources jsonb;missing jsonb;omissions jsonb;
 has_partial boolean;watermark bigint;model_version text;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid FOR UPDATE;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent manifest lease is invalid' USING ERRCODE='42501';
 END IF;
 SELECT id INTO aid FROM cehub_ai.agent_authorizations WHERE run_id=r.id AND tenant_id=r.tenant_id;
 IF aid IS NULL THEN RETURN NULL; END IF;
 IF r.execution_bundle IS NULL THEN
  RAISE EXCEPTION 'AGENT_BUNDLE_REQUIRED' USING ERRCODE='22023';
 END IF;
 SELECT * INTO receipt FROM cehub_ai.agent_context_receipts
  WHERE id=wanted_receipt AND tenant_id=r.tenant_id AND run_id=r.id AND authorization_id=aid;
 IF NOT FOUND THEN RAISE EXCEPTION 'AGENT_MANIFEST_RECEIPT_INVALID' USING ERRCODE='22023'; END IF;
 SELECT * INTO admission FROM cehub_ai.budget_journal
  WHERE tenant_id=r.tenant_id AND run_id=r.id AND attempt_id=wanted_attempt
  ORDER BY revision DESC LIMIT 1;
 IF NOT FOUND OR admission.call_kind<>'model' OR admission.reservation_status<>'reserved'
  OR admission.dispatched_at IS NOT NULL OR admission.output_tokens<=0
  OR admission.request_binding->>'model_call_id' IS DISTINCT FROM receipt.model_call_id::text THEN
  RAISE EXCEPTION 'AGENT_MANIFEST_ADMISSION_INVALID' USING ERRCODE='22023';
 END IF;
 IF pins_text IS NULL OR octet_length(pins_text)>65536 THEN
  RAISE EXCEPTION 'AGENT_MANIFEST_PINS_INVALID' USING ERRCODE='22023';
 END IF;
 pins:=pins_text::jsonb;
 IF pins#>>'{qualification,status}' IS DISTINCT FROM 'passed'
  OR pins#>>'{qualification,provider}' IS DISTINCT FROM admission.request_binding->>'provider'
  OR pins#>>'{qualification,model}' IS DISTINCT FROM admission.request_binding->>'model'
  OR jsonb_typeof(pins->'removed_paths') IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'AGENT_MANIFEST_PINS_INVALID' USING ERRCODE='22023';
 END IF;
 model_version:='sha256:' || encode(sha256(convert_to(jsonb_build_object(
  'qualification',pins->'qualification','meter_ref',admission.request_binding->'qualification_ref',
  'meter_version',admission.request_binding->'meter_version',
  'loop_qualification',r.loop_binding)::text,'UTF8')),'hex');
 IF NOT cehub_ai.agent_manifest_sources_are_current(r.tenant_id,r.id,receipt.id) THEN
  RAISE EXCEPTION 'AGENT_MANIFEST_SOURCE_ACCESS_CHANGED' USING ERRCODE='22023';
 END IF;
 SELECT * INTO previous FROM cehub_ai.agent_context_manifests
  WHERE tenant_id=r.tenant_id AND run_id=r.id AND attempt_id=wanted_attempt;
 IF FOUND THEN
  IF previous.context_receipt_id<>wanted_receipt OR previous.pins IS DISTINCT FROM pins THEN
   RAISE EXCEPTION 'AGENT_MANIFEST_CONFLICT' USING ERRCODE='22023';
  END IF;
  RETURN previous.body;
 END IF;
 SELECT * INTO first_manifest FROM cehub_ai.agent_context_manifests
  WHERE tenant_id=r.tenant_id AND run_id=r.id ORDER BY revision_no LIMIT 1;
 IF FOUND AND (first_manifest.body->>'model_qualification_version'<>model_version
  OR first_manifest.body->>'prompt_version' IS DISTINCT FROM receipt.body->>'prompt_version'
  OR first_manifest.body->>'output_schema_version' IS DISTINCT FROM
     'sha256:' || (receipt.body->>'output_schema_sha256')) THEN
  RAISE EXCEPTION 'AGENT_MANIFEST_VERSION_CHANGED' USING ERRCODE='22023';
 END IF;
 SELECT * INTO previous FROM cehub_ai.agent_context_manifests
  WHERE tenant_id=r.tenant_id AND run_id=r.id ORDER BY revision_no DESC LIMIT 1;
 n:=coalesce(previous.revision_no,0)+1;
 SELECT coalesce(jsonb_agg(o.id ORDER BY link.position),'[]'::jsonb),
  coalesce(jsonb_agg(o.tool_key || ':' || (o.metadata->>'status') || ':' || o.sequence)
   FILTER(WHERE o.metadata->>'status' IN ('failed','unavailable','cancelled')),'[]'::jsonb),
  coalesce(bool_or(o.metadata->>'status'='partial'),false)
 INTO observations,missing,has_partial
 FROM cehub_ai.agent_context_observations link JOIN cehub_ai.agent_tool_observations o
  ON o.tenant_id=link.tenant_id AND o.run_id=link.run_id AND o.id=link.observation_id
 WHERE link.tenant_id=r.tenant_id AND link.run_id=r.id AND link.context_receipt_id=receipt.id;
 SELECT coalesce(jsonb_agg(s ORDER BY s::text),'[]'::jsonb) INTO sources FROM (
  SELECT DISTINCT s FROM cehub_ai.agent_context_observations link
  JOIN cehub_ai.agent_tool_observations o ON o.id=link.observation_id
   AND o.tenant_id=link.tenant_id AND o.run_id=link.run_id,
   LATERAL jsonb_array_elements(o.metadata->'sources') s
  WHERE link.tenant_id=r.tenant_id AND link.run_id=r.id
   AND link.context_receipt_id=receipt.id) selected;
 SELECT greatest(r.last_event_row_id,coalesce(max((s->>'ref_id')::bigint),0)) INTO watermark
  FROM jsonb_array_elements(sources) s WHERE s->>'kind'='event';
 SELECT coalesce(jsonb_agg('projection_removed:' || value),'[]'::jsonb) INTO omissions
  FROM jsonb_array_elements_text(pins->'removed_paths');
 SELECT omissions || coalesce(jsonb_agg('tool_omitted:' || o.tool_key || ':' || o.sequence
  || ' shown=' || (o.metadata->>'shown_count') || ' total='
  || coalesce(o.metadata->>'total_count','unknown')),'[]'::jsonb) INTO omissions
 FROM cehub_ai.agent_context_observations link JOIN cehub_ai.agent_tool_observations o
  ON o.id=link.observation_id AND o.tenant_id=link.tenant_id AND o.run_id=link.run_id
 WHERE link.tenant_id=r.tenant_id AND link.run_id=r.id AND link.context_receipt_id=receipt.id
  AND o.metadata->>'status' IN ('partial','unavailable','failed','cancelled');
 stamp:=clock_timestamp();
 body:=jsonb_build_object('id',mid,'tenant_id',r.tenant_id,'run_id',r.id,'authorization_id',aid,
  'revision_no',n,'parent_revision_id',previous.id,'goal_revision',1,
  'release_bundle_version',r.execution_bundle->'release_bundle_version',
  'capability_version',r.execution_bundle->'capability_version',
  'prompt_version',receipt.body->'prompt_version','skill_versions','[]'::jsonb,
  'toolset_version',r.execution_bundle->'toolset_version',
  'projection_version',r.execution_bundle->'projection_version',
  'model_qualification_version',model_version,
  'output_schema_version','sha256:' || (receipt.body->>'output_schema_sha256'),
  'policy_version',r.execution_bundle->'policy_version','observation_ids',observations,
  'event_watermark',watermark,'selected_sources',sources,'omission_reasons',omissions,
  'estimated_input_tokens',admission.input_tokens,'reserved_output_tokens',admission.output_tokens,
  'completeness',CASE WHEN jsonb_array_length(missing)>0 THEN 'context_incomplete'
   WHEN has_partial THEN 'partial' ELSE 'complete' END,'missing',missing,'built_at',stamp);
 body:=body || jsonb_build_object('digest',encode(sha256(convert_to(body::text,'UTF8')),'hex'));
 IF NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent manifest lease expired' USING ERRCODE='42501';
 END IF;
 INSERT INTO cehub_ai.agent_context_manifests VALUES(mid,r.tenant_id,r.id,aid,receipt.id,
  admission.id,wanted_attempt,n,previous.id,body,pins,stamp);
 RETURN body;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.freeze_agent_context_manifest(uuid,uuid,text) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION cehub_ai.bind_agent_runtime_bundle(text),
 cehub_ai.freeze_agent_context_manifest(uuid,uuid,text),
 cehub_ai.verify_agent_manifest_sources(),
 cehub_ai.verify_agent_context_sources(uuid) TO pdos_agent;

-- Application Owner expiry is deterministic; no model or business write privilege.
GRANT EXECUTE ON FUNCTION cehub_ai.expire_application_runs(integer) TO pdos_worker;


CREATE OR REPLACE FUNCTION cehub_ai.save_agent_loop_checkpoint(body_text text) RETURNS uuid
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; payload jsonb; step integer; invocation uuid;
 old cehub_ai.agent_loop_checkpoints%ROWTYPE; cid uuid:=gen_random_uuid(); traces uuid[];
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid FOR UPDATE;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent loop checkpoint lease is invalid' USING ERRCODE='42501'; END IF;
 IF r.loop_binding IS NULL OR body_text IS NULL OR octet_length(body_text)>262144 THEN
  RAISE EXCEPTION 'AGENT_LOOP_CHECKPOINT_INVALID' USING ERRCODE='22023'; END IF;
 payload:=body_text::jsonb; step:=(payload->>'next_step')::integer;
 invocation:=(payload->>'model_invocation_id')::uuid;
 IF payload->>'version' IS DISTINCT FROM 'agent-loop-checkpoint.v1'
  OR payload#>>'{context,run_id}' IS DISTINCT FROM r.id::text
  OR payload#>>'{context,tenant_id}' IS DISTINCT FROM r.tenant_id::text
  OR payload#>>'{context,project_id}' IS DISTINCT FROM r.project_id::text
  OR payload#>>'{context,agent_key}' IS DISTINCT FROM r.agent_key
  OR (step BETWEEN 1 AND 99) IS NOT TRUE
  OR (payload->>'runtime_digest' ~ '^[a-f0-9]{64}$') IS NOT TRUE
  OR NOT EXISTS(SELECT 1 FROM cehub_ai.model_invocations m WHERE m.id=invocation
    AND m.tenant_id=r.tenant_id AND m.run_id=r.id AND m.status='succeeded') THEN
  RAISE EXCEPTION 'AGENT_LOOP_CHECKPOINT_INVALID' USING ERRCODE='22023'; END IF;
 PERFORM cehub_ai.check_run_active_budget(r.tenant_id,r.id);
 PERFORM cehub_ai.verify_agent_manifest_sources();
 IF EXISTS(SELECT 1 FROM (
  SELECT DISTINCT ON(e.session_id) e.state FROM cehub_ai.model_call_events e
   JOIN cehub_ai.model_call_sessions s ON s.id=e.session_id
   WHERE s.tenant_id=r.tenant_id AND s.run_id=r.id ORDER BY e.session_id,e.revision DESC
  ) latest WHERE state IN ('open','unknown')) OR EXISTS(SELECT 1 FROM (
  SELECT DISTINCT ON(j.attempt_id) j.held_tokens FROM cehub_ai.budget_journal j
   WHERE j.tenant_id=r.tenant_id AND j.run_id=r.id ORDER BY j.attempt_id,j.revision DESC
  ) latest WHERE held_tokens>0) OR EXISTS(SELECT 1 FROM cehub_ai.agent_tool_dispatches d
   WHERE d.tenant_id=r.tenant_id AND d.run_id=r.id AND NOT EXISTS(
    SELECT 1 FROM cehub_ai.agent_tool_observations o WHERE o.tenant_id=d.tenant_id
     AND o.run_id=d.run_id AND o.tool_intent_id=d.intent_id)) THEN
  RAISE EXCEPTION 'AGENT_LOOP_CHECKPOINT_RECEIPT_UNKNOWN' USING ERRCODE='22023'; END IF;
 SELECT * INTO old FROM cehub_ai.agent_loop_checkpoints
  WHERE tenant_id=r.tenant_id AND run_id=r.id AND next_step=step;
 IF FOUND THEN
  IF old.body IS DISTINCT FROM payload THEN
   RAISE EXCEPTION 'AGENT_LOOP_CHECKPOINT_CONFLICT' USING ERRCODE='22023'; END IF;
  RETURN old.id;
 END IF;
 IF step<>(SELECT coalesce(max(next_step),0)+1 FROM cehub_ai.agent_loop_checkpoints
   WHERE tenant_id=r.tenant_id AND run_id=r.id) THEN
  RAISE EXCEPTION 'AGENT_LOOP_CHECKPOINT_SEQUENCE' USING ERRCODE='22023'; END IF;
 SELECT array_agg(id ORDER BY id) INTO traces FROM cehub_ai.model_invocations
  WHERE tenant_id=r.tenant_id AND run_id=r.id;
 INSERT INTO cehub_ai.agent_loop_checkpoints VALUES(cid,r.tenant_id,r.id,step,invocation,traces,
  payload,encode(sha256(convert_to(payload::text,'UTF8')),'hex'),clock_timestamp());
 RETURN cid;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.save_agent_loop_checkpoint(text) FROM PUBLIC;
CREATE OR REPLACE FUNCTION cehub_ai.load_agent_loop_checkpoint() RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; cp cehub_ai.agent_loop_checkpoints%ROWTYPE;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent loop checkpoint lease is invalid' USING ERRCODE='42501'; END IF;
 IF r.run_context->>'_resume_loop_checkpoint_id' IS NULL THEN RETURN NULL; END IF;
 PERFORM cehub_ai.check_run_active_budget(r.tenant_id,r.id);
 SELECT * INTO cp FROM cehub_ai.agent_loop_checkpoints WHERE tenant_id=r.tenant_id AND run_id=r.id
  AND id=(r.run_context->>'_resume_loop_checkpoint_id')::uuid;
 IF NOT FOUND OR cp.body_sha256 IS DISTINCT FROM
  encode(sha256(convert_to(cp.body::text,'UTF8')),'hex') OR EXISTS(
   SELECT 1 FROM cehub_ai.model_invocations m WHERE m.tenant_id=r.tenant_id AND m.run_id=r.id
    AND NOT m.id=ANY(cp.trace_ids)) THEN
  RAISE EXCEPTION 'AGENT_LOOP_CHECKPOINT_INCOMPLETE' USING ERRCODE='22023'; END IF;
 RETURN cp.body;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.load_agent_loop_checkpoint() FROM PUBLIC;

GRANT EXECUTE ON FUNCTION cehub_ai.save_agent_loop_checkpoint(text),
 cehub_ai.load_agent_loop_checkpoint() TO pdos_agent;


CREATE OR REPLACE FUNCTION cehub_ai.honor_event_pause() RETURNS boolean
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

GRANT EXECUTE ON FUNCTION cehub_ai.honor_event_pause() TO pdos_agent;

COMMIT;
