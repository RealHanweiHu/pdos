-- Proposed s0_0832 helper. No business source rows or source bodies are read.
-- Provisioned by the trusted migration identity, never by a runtime connection.
CREATE ROLE pdos_enterprise_index_maintainer NOLOGIN NOSUPERUSER NOBYPASSRLS
  NOINHERIT NOCREATEDB NOCREATEROLE NOREPLICATION;
GRANT USAGE ON SCHEMA public TO pdos_enterprise_index_maintainer;
GRANT SELECT(tenant_id,id,active) ON public.principals
  TO pdos_enterprise_index_maintainer;
CREATE POLICY enterprise_statistics_identity ON public.principals
  FOR SELECT TO pdos_enterprise_index_maintainer
  USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
    AND id IN (NULLIF(current_setting('pdos.actor_id',true),'')::uuid,
               NULLIF(current_setting('pdos.requester_id',true),'')::uuid));
GRANT SELECT(tenant_id,token_count,term_counts,title_counts)
  ON public.enterprise_search_chunks TO pdos_enterprise_index_maintainer;
CREATE POLICY enterprise_statistics_metadata ON public.enterprise_search_chunks
  FOR SELECT TO pdos_enterprise_index_maintainer
  USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid);
GRANT SELECT,INSERT,UPDATE ON public.enterprise_search_corpus
  TO pdos_enterprise_index_maintainer;
GRANT SELECT,INSERT,DELETE ON public.enterprise_search_terms
  TO pdos_enterprise_index_maintainer;
-- Existing FORCE RLS tenant policies on these two derived statistics tables
-- remain enabled. No role membership is granted to app/agent/auth/dispatch.
CREATE FUNCTION public.enterprise_index_statistics_repair()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
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
$$;
REVOKE ALL ON FUNCTION public.enterprise_index_statistics_repair()
  FROM PUBLIC, pdos_agent, pdos_next_auth, pdos_next_dispatch;
GRANT EXECUTE ON FUNCTION public.enterprise_index_statistics_repair() TO pdos_next_app;
-- Transfer by the trusted migration identity after the ordinary owner creates
-- the function and policies; CREATE is revoked again within this transaction.
GRANT CREATE ON SCHEMA public TO pdos_enterprise_index_maintainer;
ALTER FUNCTION public.enterprise_index_statistics_repair()
  OWNER TO pdos_enterprise_index_maintainer;
REVOKE CREATE ON SCHEMA public FROM pdos_enterprise_index_maintainer;
