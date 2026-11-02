"""Reviewed derived-statistics role/function only; all source authority remains ordinary RLS."""
# ruff: noqa: E501 -- reviewed frozen SQL text is preserved exactly.

CREATE_ROLE = "CREATE ROLE pdos_enterprise_index_maintainer NOLOGIN NOSUPERUSER NOBYPASSRLS\n  NOINHERIT NOCREATEDB NOCREATEROLE NOREPLICATION;"

SCHEMA_SQL = (
    "GRANT USAGE ON SCHEMA public TO pdos_enterprise_index_maintainer",
    "GRANT SELECT(tenant_id,id,active) ON public.principals\n  TO pdos_enterprise_index_maintainer",
    "CREATE POLICY enterprise_statistics_identity ON public.principals\n  FOR SELECT TO pdos_enterprise_index_maintainer\n  USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid\n    AND id IN (NULLIF(current_setting('pdos.actor_id',true),'')::uuid,\n               NULLIF(current_setting('pdos.requester_id',true),'')::uuid))",
    "GRANT SELECT(tenant_id,token_count,term_counts,title_counts)\n  ON public.enterprise_search_chunks TO pdos_enterprise_index_maintainer",
    "CREATE POLICY enterprise_statistics_metadata ON public.enterprise_search_chunks\n  FOR SELECT TO pdos_enterprise_index_maintainer\n  USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid)",
    "GRANT SELECT,INSERT,UPDATE ON public.enterprise_search_corpus\n  TO pdos_enterprise_index_maintainer",
    "GRANT SELECT,INSERT,DELETE ON public.enterprise_search_terms\n  TO pdos_enterprise_index_maintainer",
    "CREATE FUNCTION public.enterprise_index_statistics_repair()\nRETURNS void\nLANGUAGE plpgsql\nSECURITY DEFINER\nSET search_path = pg_catalog, public, pg_temp\nAS $$\nDECLARE\n  t uuid := NULLIF(current_setting('pdos.tenant_id', true), '')::uuid;\n  a uuid := NULLIF(current_setting('pdos.actor_id', true), '')::uuid;\n  r uuid := NULLIF(current_setting('pdos.requester_id', true), '')::uuid;\nBEGIN\n  IF t IS NULL OR a IS NULL OR r IS NULL\n     OR NOT EXISTS (SELECT 1 FROM public.principals p\n                    WHERE p.tenant_id=t AND p.id=a AND p.active)\n     OR NOT EXISTS (SELECT 1 FROM public.principals p\n                    WHERE p.tenant_id=t AND p.id=r AND p.active) THEN\n    RAISE EXCEPTION 'Derived index repair requires active bound principals'\n      USING ERRCODE='42501';\n  END IF;\n  PERFORM pg_advisory_xact_lock(hashtextextended('enterprise-index:' || t::text, 0));\n  INSERT INTO public.enterprise_search_corpus(tenant_id, chunk_count, token_count)\n    SELECT t, count(*)::integer, coalesce(sum(c.token_count), 0)::integer\n      FROM public.enterprise_search_chunks c WHERE c.tenant_id=t\n    ON CONFLICT(tenant_id) DO UPDATE SET\n      chunk_count=EXCLUDED.chunk_count, token_count=EXCLUDED.token_count;\n  DELETE FROM public.enterprise_search_terms WHERE tenant_id=t;\n  INSERT INTO public.enterprise_search_terms(tenant_id, term, document_count)\n    SELECT t, terms.term, count(*)::integer\n      FROM public.enterprise_search_chunks c\n      CROSS JOIN LATERAL (\n        SELECT jsonb_object_keys(CASE WHEN jsonb_typeof(c.term_counts)='object'\n                                     THEN c.term_counts ELSE '{}'::jsonb END) AS term\n        UNION\n        SELECT jsonb_object_keys(CASE WHEN jsonb_typeof(c.title_counts)='object'\n                                     THEN c.title_counts ELSE '{}'::jsonb END) AS term\n      ) terms\n      WHERE c.tenant_id=t\n      GROUP BY terms.term;\nEND\n$$;",
    "REVOKE ALL ON FUNCTION public.enterprise_index_statistics_repair()\n  FROM PUBLIC, pdos_agent, pdos_next_auth, pdos_next_dispatch",
    "GRANT EXECUTE ON FUNCTION public.enterprise_index_statistics_repair() TO pdos_next_app",
)

TRANSFER_SQL = (
    "GRANT CREATE ON SCHEMA public TO pdos_enterprise_index_maintainer",
    "ALTER FUNCTION public.enterprise_index_statistics_repair()\n  OWNER TO pdos_enterprise_index_maintainer",
    "REVOKE CREATE ON SCHEMA public FROM pdos_enterprise_index_maintainer",
)

DOWNGRADE_SQL = (
    "DROP POLICY enterprise_statistics_metadata ON public.enterprise_search_chunks",
    "DROP POLICY enterprise_statistics_identity ON public.principals",
    "REVOKE SELECT(tenant_id,token_count,term_counts,title_counts) ON public.enterprise_search_chunks FROM pdos_enterprise_index_maintainer",
    "REVOKE SELECT(tenant_id,id,active) ON public.principals FROM pdos_enterprise_index_maintainer",
    "REVOKE SELECT,INSERT,UPDATE ON public.enterprise_search_corpus FROM pdos_enterprise_index_maintainer",
    "REVOKE SELECT,INSERT,DELETE ON public.enterprise_search_terms FROM pdos_enterprise_index_maintainer",
    "REVOKE USAGE ON SCHEMA public FROM pdos_enterprise_index_maintainer",
)
