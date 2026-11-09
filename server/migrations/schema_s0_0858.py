"""References of citable originals whose clean scan receipt has aged out (D215).

The 24-hour validity is read from each request's own stored policy; this list is
only a prefilter. The worker re-checks every reference with the real parsing gate
before it requests a rescan.
"""

FUNCTION = (
    "original_rescan_candidates(uuid,timestamp with time zone,jsonb,jsonb,"
    "timestamp with time zone,uuid,integer)"
)
ROLES = "PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"

UP_SQL = (
    """CREATE FUNCTION public.original_rescan_candidates(
 t uuid,at timestamp with time zone,scanner jsonb,policy jsonb,
 after_at timestamp with time zone,after_id uuid,page_limit integer)
RETURNS TABLE(category_id uuid,product_id uuid,original_id uuid,requester_id uuid,
 completed_at timestamp with time zone)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $original_rescan$
 SELECT o.category_id,o.product_id,o.id,q.requester_id,(r.result->>'completed_at')::timestamptz
  FROM public.uploaded_originals o
  JOIN public.original_security s ON s.tenant_id=o.tenant_id AND s.original_id=o.id
  JOIN public.original_scan_requests q ON q.tenant_id=s.tenant_id AND q.id=s.current_request_id
  JOIN public.original_scan_results r ON r.tenant_id=q.tenant_id AND r.request_id=q.id
 WHERE o.tenant_id=t AND t=nullif(current_setting('pdos.tenant_id',true),'')::uuid
  AND o.status='parsed' AND s.source_state='active' AND s.disposition='active'
  AND r.status='clean'
  AND ((r.result->>'completed_at')::timestamptz
        + make_interval(secs=>(q.binding#>>'{policy,clean_max_age_seconds}')::double precision)<at
       OR q.binding->'scanner' IS DISTINCT FROM scanner
       OR q.binding->'policy' IS DISTINCT FROM policy)
  AND (after_at IS NULL
       OR ((r.result->>'completed_at')::timestamptz,o.id)>(after_at,coalesce(after_id,o.id)))
 ORDER BY (r.result->>'completed_at')::timestamptz,o.id
 LIMIT LEAST(GREATEST(page_limit,1),200);
$original_rescan$""",
    f"REVOKE ALL ON FUNCTION public.{FUNCTION} FROM {ROLES}",
    f"GRANT EXECUTE ON FUNCTION public.{FUNCTION} TO pdos_next_dispatch",
)
DOWN_SQL = (f"DROP FUNCTION public.{FUNCTION}",)
