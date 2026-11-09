"""Aggregate health counters for monitoring (D213); numbers only, one tenant per call.

The probe runs with the technical dispatch role, which reads no business table.
This function returns counts and an age, never an identifier or content, and only
for the tenant set on the session, like the dispatcher's own claim function.
"""

FUNCTION = "ops_health_counters(uuid,integer)"
ROLES = "PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"

UP_SQL = (
    """CREATE FUNCTION public.ops_health_counters(t uuid,window_seconds integer)
RETURNS TABLE(outbox_pending bigint,outbox_retrying bigint,
 outbox_oldest_seconds double precision,model_calls_finished bigint,
 model_calls_failed bigint,model_calls_open_long bigint)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $ops_health$
 WITH bounds AS (
  SELECT statement_timestamp() AS at,
   make_interval(secs=>LEAST(GREATEST(window_seconds,60),86400)) AS span
 ), pending AS (
  SELECT count(*) AS total,count(*) FILTER (WHERE e.attempts>0) AS retrying,
   min(e.created_at) AS oldest
  FROM public.outbox_events e WHERE e.tenant_id=t AND e.delivered_at IS NULL
 ), calls AS (
  SELECT
   count(*) FILTER (WHERE c.state IN ('completed','failed','unknown','reconciled')
    AND c.created_at>=b.at-b.span) AS finished,
   count(*) FILTER (WHERE c.state IN ('failed','unknown')
    AND c.created_at>=b.at-b.span) AS failed,
   count(*) FILTER (WHERE c.state='started'
    AND c.created_at<b.at-interval '10 minutes') AS open_long
  FROM public.agent_tool_calls c CROSS JOIN bounds b
  WHERE c.tenant_id=t AND c.execution_binding->>'kind'='model'
 )
 SELECT p.total,p.retrying,
  COALESCE(EXTRACT(EPOCH FROM (b.at-p.oldest)),0)::double precision,
  c.finished,c.failed,c.open_long
 FROM pending p CROSS JOIN calls c CROSS JOIN bounds b
 WHERE t=nullif(current_setting('pdos.tenant_id',true),'')::uuid;
$ops_health$""",
    f"REVOKE ALL ON FUNCTION public.{FUNCTION} FROM {ROLES}",
    f"GRANT EXECUTE ON FUNCTION public.{FUNCTION} TO pdos_next_dispatch",
)
DOWN_SQL = (f"DROP FUNCTION public.{FUNCTION}",)
