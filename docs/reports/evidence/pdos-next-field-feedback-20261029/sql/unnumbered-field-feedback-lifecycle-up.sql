CREATE OR REPLACE FUNCTION public.assistant_source_lifecycle_links(t uuid,c uuid,proof jsonb) RETURNS uuid[] LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $assistant_lifecycle$

DECLARE links uuid[]='{}'; item jsonb; container jsonb; key text;
BEGIN
 IF jsonb_typeof(proof) IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'Fixed assistant source dependencies must be an array' USING ERRCODE='23514'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(proof) LOOP
  IF item->>'category_id' IS DISTINCT FROM c::text
   OR item->>'source_type' IS NULL
   OR item->>'source_type'<>ALL(ARRAY['artifact','knowledge','issue','capa','change','external_wait','supply','build','test_run','field_feedback'])
   OR item->>'source_id' IS NULL
   OR item->>'source_revision' IS NULL OR item->>'source_revision' !~ '^[1-9][0-9]*$'
   OR item->>'content_hash' IS NULL OR item->>'content_hash' !~ '^[a-f0-9]{64}$' THEN
   RAISE EXCEPTION 'Assistant dependency must retain its actual fixed identity' USING ERRCODE='23514';
  END IF;
  links=array_append(links,(item->>'source_id')::uuid);
  -- Exact original dependency projection, not read permission or business facts.
  -- Build/test record IDs resolve their own real registered Artifact read sets.
  FOR container IN
   SELECT s.required_source_read_set AS reads FROM public.quality_issue_versions s WHERE item->>'source_type'='issue' AND s.tenant_id=t AND s.category_id=c AND s.id::text=item->>'source_id'
   UNION ALL
   SELECT s.required_source_read_set AS reads FROM public.quality_issue_versions s WHERE item->>'source_type'='capa' AND s.tenant_id=t AND s.category_id=c AND s.id::text=item->>'source_id'
   UNION ALL
   SELECT s.required_source_read_set AS reads FROM public.change_request_versions s WHERE item->>'source_type'='change' AND s.tenant_id=t AND s.category_id=c AND s.id::text=item->>'source_id'
   UNION ALL
   SELECT s.reads AS reads FROM public.external_wait_versions s WHERE item->>'source_type'='external_wait' AND s.tenant_id=t AND s.category_id=c AND s.id::text=item->>'source_id'
   UNION ALL
   SELECT s.required_source_read_set AS reads FROM public.supply_snapshots s WHERE item->>'source_type'='supply' AND s.tenant_id=t AND s.category_id=c AND s.id::text=item->>'source_id'
   UNION ALL
   SELECT s.required_source_read_set AS reads FROM public.build_starts s WHERE item->>'source_type'='build' AND s.tenant_id=t AND s.category_id=c AND s.id::text=item->>'source_id'
   UNION ALL
   SELECT s.required_source_read_set AS reads FROM public.actual_configurations s WHERE item->>'source_type'='build' AND s.tenant_id=t AND s.category_id=c AND s.id::text=item->>'source_id'
   UNION ALL
   SELECT s.required_source_read_set AS reads FROM public.build_lots s WHERE item->>'source_type'='build' AND s.tenant_id=t AND s.category_id=c AND s.id::text=item->>'source_id'
   UNION ALL
   SELECT s.required_source_read_set AS reads FROM public.verification_run_versions s WHERE item->>'source_type'='test_run' AND s.tenant_id=t AND s.category_id=c AND s.id::text=item->>'source_id'
   UNION ALL
   SELECT s.required_source_read_set AS reads FROM public.test_result_actions s WHERE item->>'source_type'='test_run' AND s.tenant_id=t AND s.category_id=c AND s.id::text=item->>'source_id'
   UNION ALL
   SELECT coalesce(e.required_source_read_set,'[]'::jsonb)||coalesce(p.required_source_read_set,'[]'::jsonb) AS reads FROM public.builds b JOIN public.engineering_configurations e ON e.tenant_id=b.tenant_id AND e.category_id=b.category_id AND e.id=b.engineering_configuration_id JOIN public.process_revisions p ON p.tenant_id=b.tenant_id AND p.category_id=b.category_id AND p.id=b.manufacturing_configuration_id WHERE item->>'source_type'='build' AND b.tenant_id=t AND b.category_id=c AND b.id::text=item->>'source_id'
   UNION ALL
   SELECT coalesce(jsonb_agg(jsonb_build_object('artifact_id',root->'id',
      'expected_revision',root->'revision')),'[]'::jsonb) AS reads
    FROM public.field_feedback_versions s
     CROSS JOIN LATERAL jsonb_array_elements(s.source_basis->'artifacts') root
    WHERE item->>'source_type'='field_feedback' AND s.tenant_id=t AND s.category_id=c
     AND s.id::text=item->>'source_id'
   UNION ALL
   SELECT coalesce(jsonb_agg(jsonb_build_object('artifact_id',root->'id',
      'expected_revision',root->'revision')),'[]'::jsonb) AS reads
    FROM public.field_response_records s
     CROSS JOIN LATERAL jsonb_array_elements(s.source_basis->'artifacts') root
    WHERE item->>'source_type'='field_feedback' AND s.tenant_id=t AND s.category_id=c
     AND s.id::text=item->>'source_id'
  LOOP
   FOR key IN SELECT value->>'artifact_id' FROM jsonb_array_elements(coalesce(container,'[]'::jsonb)) LOOP
    IF key IS NOT NULL THEN links=array_append(links,key::uuid); END IF;
   END LOOP;
  END LOOP;
 END LOOP;
 RETURN links;
END
;
$assistant_lifecycle$;

REVOKE ALL ON FUNCTION public.assistant_source_lifecycle_links(uuid,uuid,jsonb) FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch;
