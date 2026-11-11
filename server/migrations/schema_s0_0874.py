"""Deterministic T0 quality facts per tenant × skill package × model version (D117, P41-8, P42).

Every number here is computed from actual run receipts and the human actions that
followed them; no model judgment is involved. One internal function classifies the
completed T0 writes of one skill version and model version; the others expose it:

- ``kernel_skill_quality_counts``: numbers only, for the T0 gate inside any run.
- ``kernel_skill_quality_basis``: the run and receipt identities behind those numbers,
  for the current human tenant administrator only.
- ``kernel_skill_quality_groups``: which skill and model versions wrote at all.
- ``kernel_skill_spot_check_sample``: the deterministic 20 % sample with a weekly
  minimum of min(2, T0 runs that week) (P42), for the current human administrator.

Windows and thresholds are passed in by the application (P41 values live in code), so
no skill package, prompt or threshold is frozen into the database.
"""

# SQL statements retain their reviewable clauses (as in schema_s0_0875).
# ruff: noqa: E501

FACTS = "kernel_skill_t0_facts(uuid,varchar,varchar,varchar,timestamptz,integer,integer)"
COUNTS = "kernel_skill_quality_counts(uuid,varchar,varchar,varchar,timestamptz,integer,integer)"
BASIS = "kernel_skill_quality_basis(uuid,varchar,varchar,varchar,timestamptz,integer,integer)"
GROUPS = "kernel_skill_quality_groups(uuid,varchar)"
SAMPLE = "kernel_skill_spot_check_sample(uuid,varchar,varchar,varchar,timestamptz,integer)"
ROLES = "PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"
# Read-only views run in READ ONLY snapshots, so this check takes no row lock
# (kernel_admin_authorized() locks the admin row for writes).
ADMIN_CHECK = """IF p_tenant IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid
   OR public.scope_actor() IS NULL OR public.scope_actor() IS DISTINCT FROM public.scope_requester()
   OR NOT EXISTS(SELECT 1 FROM public.tenant_administrators a
    JOIN public.principals p ON p.tenant_id=a.tenant_id AND p.id=a.principal_id
    WHERE a.tenant_id=p_tenant AND a.principal_id=public.scope_actor() AND a.active
    AND p.active AND p.kind='human') THEN
  RAISE EXCEPTION 'Current human tenant administrator required' USING ERRCODE='42501';
 END IF;"""

UP_SQL = (
    # A human change or a single-item withdrawal is found by the receipt's subject.
    "CREATE INDEX ix_action_receipts_subject_history ON public.action_receipts"
    "(tenant_id,subject_type,subject_id,created_at)",
    "CREATE INDEX ix_agent_tool_calls_t0_skill ON public.agent_tool_calls"
    "(tenant_id,((execution_binding -> 'skill'::text) ->> 'key'::text),created_at) "
    "WHERE (execution_binding ->> 'kind'::text)='domain_t0'::text "
    "AND (state)::text='completed'::text",
    f"""CREATE FUNCTION public.{FACTS.split("(")[0]}(p_tenant uuid,p_skill varchar,
 p_skill_version varchar,p_model_version varchar,p_since timestamptz,
 p_run_window integer,p_write_window integer)
RETURNS TABLE(fact varchar,run_id uuid,receipt_id uuid,written_at timestamptz,
 operation varchar,withdrawn boolean,changed boolean)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $facts$
 WITH w AS (
  SELECT c.run_id AS w_run,c.receipt_id AS w_receipt,c.created_at AS w_at,
   (c.execution_binding->>'operation')::varchar AS w_operation,
   (ar.reverted_at IS NOT NULL OR EXISTS(
     SELECT 1 FROM public.action_receipts x
     WHERE x.tenant_id=r.tenant_id AND x.subject_type=r.subject_type
     AND x.subject_id=r.subject_id AND x.operation='ai.run.revert'
     AND x.created_at>=r.created_at)) AS w_withdrawn,
   EXISTS(
     SELECT 1 FROM public.action_receipts h
     JOIN public.principals p ON p.tenant_id=h.tenant_id AND p.id=h.actor_id AND p.kind='human'
     WHERE h.tenant_id=r.tenant_id AND h.subject_type=r.subject_type
     AND h.subject_id=r.subject_id AND h.created_at>r.created_at AND h.id<>r.id
     AND h.agent_run_id IS NULL AND h.operation<>'ai.run.revert') AS w_changed
  FROM public.agent_tool_calls c
  JOIN public.action_receipts r ON r.tenant_id=c.tenant_id AND r.id=c.receipt_id
  JOIN public.agent_runs ar ON ar.tenant_id=c.tenant_id AND ar.id=c.run_id
  WHERE c.tenant_id=p_tenant AND c.execution_binding->>'kind'='domain_t0'
  AND c.state='completed' AND c.execution_binding->'skill'->>'key'=p_skill
  AND c.execution_binding->'skill'->>'version'=p_skill_version
  AND c.execution_binding->>'model_version'=p_model_version
  AND (p_since IS NULL OR c.created_at>=p_since)
 ), runs AS (
  SELECT w.w_run AS r_run,min(w.w_at) AS r_at,bool_or(w.w_withdrawn) AS r_withdrawn,
   bool_or(w.w_changed AND NOT w.w_withdrawn) AS r_changed
  FROM w GROUP BY w.w_run ORDER BY min(w.w_at) DESC,w.w_run DESC
  LIMIT LEAST(GREATEST(p_run_window,1),500)
 ), writes AS (
  SELECT w.* FROM w ORDER BY w.w_at DESC,w.w_receipt DESC
  LIMIT LEAST(GREATEST(p_write_window,1),500)
 )
 SELECT 'run'::varchar,runs.r_run,NULL::uuid,runs.r_at,NULL::varchar,runs.r_withdrawn,
  runs.r_changed FROM runs
 UNION ALL
 SELECT 'write'::varchar,writes.w_run,writes.w_receipt,writes.w_at,writes.w_operation,
  writes.w_withdrawn,writes.w_changed AND NOT writes.w_withdrawn FROM writes
$facts$""",
    f"""CREATE FUNCTION public.{COUNTS.split("(")[0]}(p_tenant uuid,p_skill varchar,
 p_skill_version varchar,p_model_version varchar,p_since timestamptz,
 p_run_window integer,p_write_window integer)
RETURNS TABLE(runs_window integer,runs_withdrawn integer,writes_window integer,
 writes_changed integer,writes_withdrawn integer)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $counts$
 SELECT count(*) FILTER (WHERE f.fact='run')::integer,
  count(*) FILTER (WHERE f.fact='run' AND f.withdrawn)::integer,
  count(*) FILTER (WHERE f.fact='write')::integer,
  count(*) FILTER (WHERE f.fact='write' AND f.changed)::integer,
  count(*) FILTER (WHERE f.fact='write' AND f.withdrawn)::integer
 FROM public.{FACTS.split("(")[0]}(p_tenant,p_skill,p_skill_version,p_model_version,
  p_since,p_run_window,p_write_window) f
 HAVING p_tenant=nullif(current_setting('pdos.tenant_id',true),'')::uuid
$counts$""",
    f"""CREATE FUNCTION public.{BASIS.split("(")[0]}(p_tenant uuid,p_skill varchar,
 p_skill_version varchar,p_model_version varchar,p_since timestamptz,
 p_run_window integer,p_write_window integer)
RETURNS TABLE(fact varchar,run_id uuid,receipt_id uuid,written_at timestamptz,
 operation varchar,withdrawn boolean,changed boolean)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $basis$
BEGIN
 {ADMIN_CHECK}
 RETURN QUERY SELECT f.fact,f.run_id,f.receipt_id,f.written_at,f.operation,f.withdrawn,f.changed
 FROM public.{FACTS.split("(")[0]}(p_tenant,p_skill,p_skill_version,p_model_version,
  p_since,p_run_window,p_write_window) f;
END $basis$""",
    f"""CREATE FUNCTION public.{GROUPS.split("(")[0]}(p_tenant uuid,p_skill varchar)
RETURNS TABLE(skill_version varchar,model_version varchar,runs_total integer,
 writes_total integer,first_at timestamptz,last_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $groups$
BEGIN
 {ADMIN_CHECK}
 RETURN QUERY SELECT (c.execution_binding->'skill'->>'version')::varchar,
  (c.execution_binding->>'model_version')::varchar,count(DISTINCT c.run_id)::integer,
  count(*)::integer,min(c.created_at),max(c.created_at)
 FROM public.agent_tool_calls c
 WHERE c.tenant_id=p_tenant AND c.execution_binding->>'kind'='domain_t0'
 AND c.state='completed' AND c.execution_binding->'skill'->>'key'=p_skill
 GROUP BY 1,2 ORDER BY max(c.created_at) DESC LIMIT 50;
END $groups$""",
    f"""CREATE FUNCTION public.{SAMPLE.split("(")[0]}(p_tenant uuid,p_skill varchar,
 p_skill_version varchar,p_model_version varchar,p_since timestamptz,p_limit integer)
RETURNS TABLE(run_id uuid,first_at timestamptz,week_start date,sampled boolean,
 reason varchar)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $sample$
BEGIN
 {ADMIN_CHECK}
 RETURN QUERY WITH runs AS (
  SELECT c.run_id AS s_run,min(c.created_at) AS s_at
  FROM public.agent_tool_calls c
  WHERE c.tenant_id=p_tenant AND c.execution_binding->>'kind'='domain_t0'
  AND c.state='completed' AND c.execution_binding->'skill'->>'key'=p_skill
  AND c.execution_binding->'skill'->>'version'=p_skill_version
  AND c.execution_binding->>'model_version'=p_model_version
  AND (p_since IS NULL OR c.created_at>=p_since)
  GROUP BY c.run_id
 ), bucketed AS (
  SELECT runs.s_run,runs.s_at,
   date_trunc('week',runs.s_at AT TIME ZONE 'Asia/Shanghai')::date AS s_week,
   (('x'||lpad(substr(md5(runs.s_run::text),1,8),16,'0'))::bit(64)::bigint % 5)=0 AS s_hash
  FROM runs
 ), weekly AS (
  SELECT b.*,count(*) OVER (PARTITION BY b.s_week) AS s_total,
   count(*) FILTER (WHERE b.s_hash) OVER (PARTITION BY b.s_week) AS s_hashed,
   row_number() OVER (PARTITION BY b.s_week,b.s_hash ORDER BY b.s_at,b.s_run) AS s_rank
  FROM bucketed b
 )
 SELECT w.s_run,w.s_at,w.s_week,
  w.s_hash OR w.s_rank<=LEAST(2,w.s_total)-w.s_hashed,
  (CASE WHEN w.s_hash THEN 'hash_20_percent'
   WHEN w.s_rank<=LEAST(2,w.s_total)-w.s_hashed THEN 'weekly_minimum'
   ELSE 'not_sampled' END)::varchar
 FROM weekly w ORDER BY w.s_at DESC,w.s_run DESC
 LIMIT LEAST(GREATEST(p_limit,1),500);
END $sample$""",
    *(f"REVOKE ALL ON FUNCTION public.{name} FROM {ROLES}" for name in (
        FACTS, COUNTS, BASIS, GROUPS, SAMPLE
    )),
    *(f"GRANT EXECUTE ON FUNCTION public.{name} TO pdos_next_app" for name in (
        COUNTS, BASIS, GROUPS, SAMPLE
    )),
)

DOWN_SQL = (
    *(f"DROP FUNCTION public.{name}" for name in (SAMPLE, GROUPS, BASIS, COUNTS, FACTS)),
    "DROP INDEX public.ix_agent_tool_calls_t0_skill",
    "DROP INDEX public.ix_action_receipts_subject_history",
)
