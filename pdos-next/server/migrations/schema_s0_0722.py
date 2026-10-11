"""Frozen batch audience reader; downgrade is the captured s0_0721 definition.

Only the existing boolean function is replaced. CREATE OR REPLACE retains its
ordinary owner and EXECUTE ACL; standalone audience/live-source helpers keep
all of their original independently callable checks.
"""
# ruff: noqa: E501 -- frozen PostgreSQL function definitions

PREVIOUS = """CREATE OR REPLACE FUNCTION public.business_audience_summary_visible(t uuid, c uuid, p uuid, deps jsonb)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE ref jsonb; body jsonb; typ text; sid uuid; expected_product uuid;
BEGIN
 IF NOT category_access(t,c,false) OR jsonb_typeof(deps) IS DISTINCT FROM 'array'
 THEN RETURN false; END IF;
 IF p IS NOT NULL AND NOT EXISTS(SELECT 1 FROM products r WHERE r.tenant_id=t AND r.category_id=c
  AND r.id=p AND source_object_audience(t,c,'products',r.id,r.owner_id,r.visibility))
 THEN RETURN false; END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(deps) LOOP
  IF jsonb_typeof(ref) IS DISTINCT FROM 'object' OR
    (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(ref) key)
      IS DISTINCT FROM ARRAY['id','product_id','type'] THEN RETURN false; END IF;
  typ=ref->>'type';sid=(ref->>'id')::uuid;expected_product=(ref->>'product_id')::uuid;
  IF NOT typ=ANY(ARRAY['actual_configurations','bom_revisions','build_authorization_decisions','build_execution_assessments','build_lots','build_operational_facts','build_readiness','build_starts','builds','definition_revisions','engineering_configurations','measurement_import_captures','process_revisions','professional_authority_facts','projects','sample_allocations','sample_readiness_facts','sample_run_usages','sample_units','test_measurements','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','verification_actual_method_applicabilities','verification_actual_method_batches','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','quality_issue_versions','quality_event_failure_links','quality_policy_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','capa_observation_facts','capa_named_verification_reviews']) OR sid IS NULL THEN RETURN false; END IF;
  EXECUTE format('SELECT to_jsonb(r) FROM public.%I r WHERE tenant_id=$1 AND category_id=$2 AND id=$3',typ)
   INTO body USING t,c,sid;
  IF body IS NULL OR (body->>'product_id')::uuid IS DISTINCT FROM expected_product OR
   (expected_product IS DISTINCT FROM p AND NOT(expected_product IS NULL AND
    typ=ANY(ARRAY['artifact_versions','uploaded_originals']))) THEN RETURN false; END IF;
  IF NOT source_object_audience(t,c,typ,sid,(body->>'owner_id')::uuid,body->>'visibility')
  THEN RETURN false; END IF;
  IF body ? 'required_source_read_set' AND NOT direct_source_set_visible(t,c,expected_product,body->'required_source_read_set')
  THEN RETURN false; END IF;
  -- These B3 owners keep live links/sources outside required_source_read_set.
  IF typ='projects' AND NOT project_definition_visible(t,c,expected_product,sid)
  THEN RETURN false; END IF;
  IF typ='definition_revisions' AND NOT definition_sources_visible(t,c,expected_product,sid)
  THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $function$
"""

FUNCTION = """CREATE OR REPLACE FUNCTION public.business_audience_summary_visible(
 t uuid, c uuid, p uuid, deps jsonb
) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $function$
DECLARE
 dep jsonb; source_ref jsonb; typ text; sid uuid; expected_product uuid;
 requester uuid; ids uuid[]; found_count integer; item record;
 audience_columns text; source_column text; has_sources boolean;
 saw_sources boolean=false; merged_sources jsonb='[]'::jsonb;
BEGIN
 -- The same current category authorization protects all owner-internal reads.
 IF NOT category_access(t,c,false)
    OR jsonb_typeof(deps) IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 requester=scope_requester();
 IF p IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM public.products r
  WHERE r.tenant_id=t AND r.category_id=c AND r.id=p AND (
   r.visibility='category' OR r.owner_id=requester OR EXISTS(
    SELECT 1 FROM public.object_audiences a
    WHERE a.tenant_id=t AND a.category_id=c AND a.object_type='products'
      AND a.subject_id=r.id AND a.owner_id=r.owner_id AND a.principal_id=requester
   )
  )
 ) THEN RETURN false; END IF;

 -- Validate every identity before it can reach a dynamic relation identifier.
 FOR dep IN SELECT value FROM jsonb_array_elements(deps) LOOP
  IF jsonb_typeof(dep) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
  IF (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(dep) key)
      IS DISTINCT FROM ARRAY['id','product_id','type']
     OR jsonb_typeof(dep->'type') IS DISTINCT FROM 'string'
     OR jsonb_typeof(dep->'id') IS DISTINCT FROM 'string'
     OR jsonb_typeof(dep->'product_id') NOT IN ('string','null')
  THEN RETURN false; END IF;
  typ=dep->>'type';
  IF NOT typ=ANY(ARRAY['actual_configurations','bom_revisions','build_authorization_decisions','build_execution_assessments','build_lots','build_operational_facts','build_readiness','build_starts','builds','definition_revisions','engineering_configurations','measurement_import_captures','process_revisions','professional_authority_facts','projects','sample_allocations','sample_readiness_facts','sample_run_usages','sample_units','test_measurements','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','verification_actual_method_applicabilities','verification_actual_method_batches','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','quality_issue_versions','quality_event_failure_links','quality_policy_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','capa_observation_facts','capa_named_verification_reviews']) THEN RETURN false; END IF;
  BEGIN
   sid=(dep->>'id')::uuid;
   expected_product=(dep->>'product_id')::uuid;
  EXCEPTION WHEN invalid_text_representation THEN RETURN false;
  END;
  IF sid IS NULL OR (expected_product IS DISTINCT FROM p AND NOT(
    expected_product IS NULL AND typ=ANY(ARRAY['artifact_versions','uploaded_originals'])
  )) THEN RETURN false; END IF;
 END LOOP;

 FOR typ IN SELECT DISTINCT value->>'type' FROM jsonb_array_elements(deps) LOOP
  SELECT array_agg(DISTINCT (value->>'id')::uuid) INTO ids
   FROM jsonb_array_elements(deps) WHERE value->>'type'=typ;
  found_count=0;
  has_sources=typ=ANY(ARRAY['actual_configurations','bom_revisions','build_authorization_decisions','build_execution_assessments','build_lots','build_operational_facts','build_starts','engineering_configurations','measurement_import_captures','process_revisions','professional_authority_facts','sample_allocations','sample_readiness_facts','sample_run_usages','sample_units','test_measurements','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','verification_actual_method_applicabilities','verification_actual_method_batches','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_versions','verification_window_proposals','quality_issue_versions','quality_event_failure_links','quality_policy_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','capa_observation_facts','capa_named_verification_reviews']);
  -- The failure-link row inherits audience from its complete ancestor summary;
  -- it has neither column. Preserve the previous NULL/IF-NOT semantics.
  audience_columns=CASE WHEN typ='quality_event_failure_links'
   THEN 'NULL::uuid AS owner_id,NULL::text AS visibility'
   ELSE 'r.owner_id,r.visibility' END;
  source_column=CASE WHEN has_sources THEN 'r.required_source_read_set'
   ELSE 'NULL::jsonb' END;
  FOR item IN EXECUTE format(
   'SELECT r.id,r.product_id,%s,%s AS source_reads FROM public.%I r '
   'WHERE r.tenant_id=$1 AND r.category_id=$2 AND r.id=ANY($3)',
   audience_columns,source_column,typ
  ) USING t,c,ids LOOP
   found_count=found_count+1;
   IF item.product_id IS DISTINCT FROM p THEN RETURN false; END IF;
   -- Inline only the pure audience predicate, after the same root access check.
   -- The independently callable source_object_audience remains unchanged.
   IF NOT (item.visibility='category' OR item.owner_id=requester OR EXISTS(
    SELECT 1 FROM public.object_audiences a
    WHERE a.tenant_id=t AND a.category_id=c AND a.object_type=typ
      AND a.subject_id=item.id AND a.owner_id=item.owner_id AND a.principal_id=requester
   )) THEN RETURN false; END IF;
   IF has_sources THEN
    IF jsonb_typeof(item.source_reads) IS DISTINCT FROM 'array' THEN RETURN false; END IF;
    FOR source_ref IN SELECT value FROM jsonb_array_elements(item.source_reads) LOOP
     IF jsonb_typeof(source_ref) IS DISTINCT FROM 'object'
        OR jsonb_typeof(source_ref->'artifact_id') IS DISTINCT FROM 'string'
     THEN RETURN false; END IF;
     BEGIN
      sid=(source_ref->>'artifact_id')::uuid;
     EXCEPTION WHEN invalid_text_representation THEN RETURN false;
     END;
     IF sid IS NULL THEN RETURN false; END IF;
    END LOOP;
    merged_sources=merged_sources||item.source_reads;
    saw_sources=true;
   END IF;
   -- These B3 owners keep live links/sources outside required_source_read_set.
   IF typ='projects' AND NOT project_definition_visible(t,c,item.product_id,item.id)
   THEN RETURN false; END IF;
   IF typ='definition_revisions' AND NOT definition_sources_visible(t,c,item.product_id,item.id)
   THEN RETURN false; END IF;
  END LOOP;
  -- Duplicate input refs share one exact identity, but none may be missing.
  IF found_count IS DISTINCT FROM cardinality(ids) THEN RETURN false; END IF;
 END LOOP;

 -- Every dep's declared and actual product has matched p. Union all complete
 -- read sets without truncation; the live source predicate runs once for it.
 IF saw_sources THEN
  SELECT COALESCE(jsonb_agg(value ORDER BY value::text),'[]'::jsonb)
   INTO merged_sources FROM (
    SELECT DISTINCT value FROM jsonb_array_elements(merged_sources)
   ) complete_reads;
  IF NOT direct_source_set_visible(t,c,p,merged_sources) THEN RETURN false; END IF;
 END IF;
 RETURN true;
END $function$;
"""
