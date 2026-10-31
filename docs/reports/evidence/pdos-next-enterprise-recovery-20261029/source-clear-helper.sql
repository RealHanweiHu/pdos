-- Review draft for s0_0834 (down_revision s0_0833); never applied by this agent.
-- The server calls this only after its ordinary RLS read has resolved the exact
-- source/category/revision/hash and computed work_key and deterministic chunk IDs.
-- This function is not a source-authorization oracle or an external/model tool.
GRANT SELECT(id,source_type,source_id,work_key)
  ON public.enterprise_search_chunks TO pdos_enterprise_index_maintainer;
GRANT DELETE ON public.enterprise_search_chunks TO pdos_enterprise_index_maintainer;
CREATE POLICY enterprise_recovery_delete ON public.enterprise_search_chunks
  FOR DELETE TO pdos_enterprise_index_maintainer
  USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid);
GRANT SELECT(tenant_id,source_type,source_id,work_key),DELETE
  ON public.enterprise_search_sources TO pdos_enterprise_index_maintainer;
CREATE POLICY enterprise_recovery_metadata ON public.enterprise_search_sources
  FOR SELECT TO pdos_enterprise_index_maintainer
  USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid);
CREATE POLICY enterprise_recovery_delete ON public.enterprise_search_sources
  FOR DELETE TO pdos_enterprise_index_maintainer
  USING (tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid);
GRANT EXECUTE ON FUNCTION public.category_access(uuid,uuid,boolean)
  TO pdos_enterprise_index_maintainer;

CREATE FUNCTION public.enterprise_index_source_clear(
  kind text, sid uuid, category uuid, expected_key text, expected_ids uuid[])
RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  t uuid := NULLIF(current_setting('pdos.tenant_id',true),'')::uuid;
  a uuid := NULLIF(current_setting('pdos.actor_id',true),'')::uuid;
  r uuid := NULLIF(current_setting('pdos.requester_id',true),'')::uuid;
BEGIN
  IF t IS NULL OR a IS NULL OR r IS NULL
     OR NOT EXISTS(SELECT 1 FROM public.principals p
                   WHERE p.tenant_id=t AND p.id=a AND p.active)
     OR NOT EXISTS(SELECT 1 FROM public.principals p
                   WHERE p.tenant_id=t AND p.id=r AND p.active)
     OR public.category_access(t,category,false) IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'Derived source repair requires active bound source scope'
      USING ERRCODE='42501';
  END IF;
  IF kind IS NULL OR kind NOT IN
     ('artifact','knowledge','issue','capa','change','test_run','build','supply','external_wait')
     OR sid IS NULL OR expected_key IS NULL OR expected_key !~ '^[a-f0-9]{64}$'
     OR expected_ids IS NULL OR array_position(expected_ids,NULL) IS NOT NULL THEN
    RAISE EXCEPTION 'Derived source repair requires projector-computed identity'
      USING ERRCODE='22023';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('enterprise-index:' || t::text,0));
  DELETE FROM public.enterprise_search_chunks c WHERE c.tenant_id=t
    AND ((c.source_type=kind AND c.source_id=sid)
      OR c.work_key=expected_key OR c.id=ANY(expected_ids));
  DELETE FROM public.enterprise_search_sources s WHERE s.tenant_id=t
    AND ((s.source_type=kind AND s.source_id=sid) OR s.work_key=expected_key);
END $$;
REVOKE ALL ON FUNCTION public.enterprise_index_source_clear(text,uuid,uuid,text,uuid[])
  FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch;
GRANT EXECUTE ON FUNCTION public.enterprise_index_source_clear(text,uuid,uuid,text,uuid[])
  TO pdos_next_app;
-- Trusted migrator only; no runtime memberships or SET ROLE grants.
GRANT CREATE ON SCHEMA public TO pdos_enterprise_index_maintainer;
ALTER FUNCTION public.enterprise_index_source_clear(text,uuid,uuid,text,uuid[])
  OWNER TO pdos_enterprise_index_maintainer;
REVOKE CREATE ON SCHEMA public FROM pdos_enterprise_index_maintainer;

-- DOWN removes exactly the new function/policies/privileges above. It retains
-- s0_0832 metadata SELECT, statistics policies/function, role, and all FORCE RLS.
