"""Checkpoint retention reads only open/closed flags of Runs and batches (D58, P78)."""

FUNCTION = "checkpoint_retention_owners(uuid,uuid[],uuid[])"
ROLES = "PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"

# Batch rows are otherwise visible only under a human actor's scope. The schema owner
# (NOLOGIN, entered only by reviewed SECURITY DEFINER functions) may read them in the
# current tenant scope, as it already may for agent_runs; the one function using it
# returns open/closed flags only.
POLICY_SQL = (
    "CREATE POLICY checkpoint_retention_read ON public.enterprise_embedding_batches "
    "FOR SELECT TO pdos_next_owner "
    "USING (tenant_id=(NULLIF(current_setting('pdos.tenant_id',true),''))::uuid)"
)

UP_SQL = (
    POLICY_SQL,
    """CREATE FUNCTION public.checkpoint_retention_owners(t uuid,run_ids uuid[],batch_ids uuid[])
RETURNS TABLE(kind text,owner_id uuid,open boolean)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $checkpoint_retention$
 SELECT 'run'::text,r.id,r.state IN ('queued','running','waiting_input')
  FROM public.agent_runs r
 WHERE r.tenant_id=t AND t=nullif(current_setting('pdos.tenant_id',true),'')::uuid
  AND cardinality(run_ids)<=200 AND r.id=ANY(run_ids)
 UNION ALL
 SELECT 'embedding_batch'::text,b.id,b.state IN ('queued','running','retryable')
  FROM public.enterprise_embedding_batches b
 WHERE b.tenant_id=t AND t=nullif(current_setting('pdos.tenant_id',true),'')::uuid
  AND cardinality(batch_ids)<=200 AND b.id=ANY(batch_ids);
$checkpoint_retention$""",
    f"REVOKE ALL ON FUNCTION public.{FUNCTION} FROM {ROLES}",
    f"GRANT EXECUTE ON FUNCTION public.{FUNCTION} TO pdos_next_dispatch",
)
DOWN_SQL = (
    f"DROP FUNCTION public.{FUNCTION}",
    "DROP POLICY checkpoint_retention_read ON public.enterprise_embedding_batches",
)
