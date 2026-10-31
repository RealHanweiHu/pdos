CREATE OR REPLACE FUNCTION public.enterprise_index_statistics_repair()
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE
  t uuid := NULLIF(current_setting('pdos.tenant_id', true), '')::uuid;
  a uuid := NULLIF(current_setting('pdos.actor_id', true), '')::uuid;
  r uuid := NULLIF(current_setting('pdos.requester_id', true), '')::uuid;
BEGIN
  IF t IS NULL OR a IS NULL OR r IS NULL
     OR NOT EXISTS (SELECT 1 FROM public.principals p
                    WHERE p.tenant_id=t AND p.id=a AND p.active)
     OR NOT EXISTS (SELECT 1 FROM public.principals p
                    WHERE p.tenant_id=t AND p.id=r AND p.active) THEN
    RAISE EXCEPTION 'Derived index repair requires active bound principals'
      USING ERRCODE='42501';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('enterprise-index:' || t::text, 0));
  INSERT INTO public.enterprise_search_corpus(tenant_id, chunk_count, token_count)
    SELECT t, count(*)::integer, coalesce(sum(c.token_count), 0)::integer
      FROM public.enterprise_search_chunks c WHERE c.tenant_id=t
    ON CONFLICT(tenant_id) DO UPDATE SET
      chunk_count=EXCLUDED.chunk_count, token_count=EXCLUDED.token_count;
  DELETE FROM public.enterprise_search_terms WHERE tenant_id=t;
  INSERT INTO public.enterprise_search_terms(tenant_id, term, document_count)
    SELECT t, terms.term, count(*)::integer
      FROM public.enterprise_search_chunks c
      CROSS JOIN LATERAL (
        SELECT jsonb_object_keys(CASE WHEN jsonb_typeof(c.term_counts)='object'
                                     THEN c.term_counts ELSE '{}'::jsonb END) AS term
        UNION
        SELECT jsonb_object_keys(CASE WHEN jsonb_typeof(c.title_counts)='object'
                                     THEN c.title_counts ELSE '{}'::jsonb END) AS term
      ) terms
      WHERE c.tenant_id=t
      GROUP BY terms.term;
END
$function$
