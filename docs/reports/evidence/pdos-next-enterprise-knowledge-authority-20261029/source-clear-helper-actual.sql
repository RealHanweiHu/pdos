CREATE OR REPLACE FUNCTION public.enterprise_index_source_clear(kind text, sid uuid, category uuid, expected_key text, expected_ids uuid[])
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
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
END $function$
