"""Frozen M3 original-reference closure and lifecycle fences (ordinary owner)."""
# ruff: noqa: E501 -- frozen SQL and exact predecessor catalog literals

M3_TABLES = (
    "proposals",
    "proposal_items",
    "proposal_item_versions",
    "proposal_revisions",
    "proposal_sources",
    "proposal_submissions",
    "proposal_decisions",
    "project_open_items",
    "category_knowledge_entries",
    "category_knowledge_current",
    "product_target_segments",
    "parameter_versions",
    "parameter_current",
    "promotion_proofs",
    "evidence_links",
    "claim_withdrawals",
)

# Filled with frozen predecessor literals below; never import a live catalog.
PREDECESSOR_SUMMARY = "CREATE OR REPLACE FUNCTION public.lifecycle_reference_summary(t uuid, c uuid, p uuid, roots uuid[])\n RETURNS TABLE(object_id uuid, reference_count integer, formal_history boolean, read_version bigint)\n LANGUAGE plpgsql\n STABLE SECURITY DEFINER\n SET search_path TO 'pg_catalog', 'public', 'pg_temp'\nAS $function$\nDECLARE tables text[]=ARRAY['agent_runs','action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests']; table_name text; payload jsonb;\n graph jsonb[]='{}'; controls uuid[]; reached uuid[]='{}'; selected integer[]='{}';\n node jsonb; links uuid[]; row_id uuid; oid uuid; i integer; changed boolean;\nBEGIN\n IF NOT category_access(t,c,false) OR (p IS NOT NULL AND NOT EXISTS(\n  SELECT 1 FROM products WHERE id=p AND tenant_id=t AND category_id=c\n )) THEN RETURN; END IF;\n SELECT COALESCE(array_agg(id),'{}') INTO controls FROM action_receipts\n  WHERE tenant_id=t AND category_id=c AND product_id IS NOT DISTINCT FROM p AND operation LIKE 'evidence.lifecycle.%';\n FOREACH table_name IN ARRAY tables LOOP\n  FOR payload IN EXECUTE CASE WHEN table_name=ANY(ARRAY['audit_entries','outbox_events','request_keys'])\n   THEN format('SELECT to_jsonb(x) FROM public.%I x JOIN action_receipts r ON r.id=x.receipt_id AND r.tenant_id=x.tenant_id WHERE x.tenant_id=$1 AND ( $2 IS NULL OR r.product_id=$2 ) AND r.category_id=$3',table_name)\n   ELSE format('SELECT to_jsonb(x) FROM public.%I x WHERE tenant_id=$1 AND ( $2 IS NULL OR product_id=$2 ) AND category_id=$3',table_name)\n   END USING t,p,c LOOP\n   IF (payload->>'receipt_id')::uuid=ANY(controls) OR\n     (table_name='action_receipts' AND payload->>'operation' LIKE 'evidence.lifecycle.%') THEN CONTINUE; END IF;\n   graph=array_append(graph,jsonb_build_object('table',table_name,'id',payload->>'id',\n     'links',to_jsonb(kernel_lifecycle_links(table_name,payload))));\n  END LOOP;\n END LOOP;\n IF p IS NULL THEN\n  SELECT lifecycle_epoch INTO read_version FROM categories WHERE id=c AND tenant_id=t;\n ELSE\n  SELECT lifecycle_epoch INTO read_version FROM products WHERE id=p AND tenant_id=t AND category_id=c;\n END IF;\n FOREACH oid IN ARRAY roots LOOP\n  IF NOT (\n   EXISTS(SELECT 1 FROM upload_attempts WHERE id=oid AND tenant_id=t AND category_id=c AND product_id IS NOT DISTINCT FROM p AND owner_id=scope_requester()) OR\n   EXISTS(SELECT 1 FROM uploaded_originals WHERE id=oid AND tenant_id=t AND category_id=c AND product_id IS NOT DISTINCT FROM p AND owner_id=scope_requester()) OR\n   EXISTS(SELECT 1 FROM lifecycle_objects WHERE id=oid AND tenant_id=t AND category_id=c AND product_id IS NOT DISTINCT FROM p AND owner_id=scope_requester())\n  ) THEN CONTINUE; END IF;\n  object_id=oid; reached=ARRAY[oid]; selected='{}'; changed=true;\n WHILE changed LOOP\n  changed=false;\n  IF cardinality(graph)>0 THEN\n   FOR i IN 1..cardinality(graph) LOOP\n    IF i=ANY(selected) THEN CONTINUE; END IF;\n    node=graph[i]; row_id=(node->>'id')::uuid;\n    SELECT COALESCE(array_agg(v::uuid),'{}') INTO links FROM jsonb_array_elements_text(node->'links') AS x(v);\n    IF row_id=oid OR links && reached THEN\n     selected=array_append(selected,i);\n     IF row_id IS NOT NULL AND NOT row_id=ANY(reached) THEN reached=array_append(reached,row_id); END IF;\n     changed=true;\n    END IF;\n   END LOOP;\n  END IF;\n END LOOP;\n reference_count=cardinality(selected); formal_history=false;\n FOREACH i IN ARRAY selected LOOP\n  IF NOT (graph[i]->>'table'=ANY(ARRAY['uploaded_originals','artifact_versions','original_security',\n    'original_scan_requests','original_scan_results','outbox_events','audit_entries'])) THEN\n   formal_history=true; EXIT;\n  END IF;\n END LOOP;\n RETURN NEXT;\n END LOOP;\nEND $function$\n"
GRAPH_TABLES = (
    "agent_runs",
    "action_receipts",
    "actual_configurations",
    "artifact_versions",
    "audit_entries",
    "bom_lines",
    "bom_revisions",
    "build_authorization_decisions",
    "build_current_authorizations",
    "build_current_execution_assessments",
    "build_execution_assessments",
    "build_lots",
    "build_operational_current",
    "build_operational_facts",
    "build_readiness",
    "build_starts",
    "builds",
    "capa_current_observations",
    "capa_current_verification_rules",
    "capa_named_verification_reviews",
    "capa_observation_facts",
    "capa_remediation_links",
    "capa_verification_evidence",
    "capa_verification_rule_facts",
    "change_approval_records",
    "change_dependency_clocks",
    "change_graph_captures",
    "change_implementation_captures",
    "change_implementation_records",
    "change_order_records",
    "change_request_currents",
    "change_request_versions",
    "claim_consumptions",
    "claims",
    "controlled_change_coverage_currents",
    "controlled_change_coverage_facts",
    "controlled_change_policy_currents",
    "controlled_change_policy_facts",
    "controlled_change_selection_currents",
    "controlled_change_selection_facts",
    "cost_current_inputs",
    "cost_estimates",
    "cost_input_snapshots",
    "cost_source_captures",
    "definition_revisions",
    "definition_sources",
    "definition_specs",
    "engineering_configurations",
    "manufacturing_baseline_document_links",
    "manufacturing_preparation_currents",
    "manufacturing_preparation_versions",
    "measurement_import_captures",
    "operational_material_holds",
    "operational_resource_occupancies",
    "original_scan_requests",
    "original_scan_results",
    "original_security",
    "outbox_events",
    "parts",
    "plan_proposals",
    "plan_revisions",
    "process_revisions",
    "product_variants",
    "professional_authority_current",
    "professional_authority_facts",
    "project_product_links",
    "project_tasks",
    "project_work_packages",
    "projects",
    "quality_current_issues",
    "quality_current_policies",
    "quality_event_failure_links",
    "quality_failure_maps",
    "quality_issue_versions",
    "quality_policy_facts",
    "request_keys",
    "runs",
    "sample_allocations",
    "sample_current_readiness",
    "sample_readiness_facts",
    "sample_run_usages",
    "sample_units",
    "sample_usage_sentinels",
    "supply_current_snapshots",
    "supply_kit_projections",
    "supply_snapshots",
    "supply_source_captures",
    "task_dependencies",
    "test_measurements",
    "test_resource_current",
    "test_resource_facts",
    "test_resource_reservations",
    "test_result_actions",
    "test_result_projections",
    "uploaded_originals",
    "variant_revisions",
    "verification_actual_method_applicabilities",
    "verification_actual_method_batches",
    "verification_current_actual_methods",
    "verification_current_formal_requests",
    "verification_current_preparations",
    "verification_current_runs",
    "verification_formal_requests",
    "verification_handoff_facts",
    "verification_launch_facts",
    "verification_method_applicabilities",
    "verification_preparations",
    "verification_run_identities",
    "verification_run_versions",
    "verification_window_proposals",
    "work_requests",
    "proposals",
    "proposal_items",
    "proposal_item_versions",
    "proposal_revisions",
    "proposal_sources",
    "proposal_submissions",
    "proposal_decisions",
    "project_open_items",
    "category_knowledge_entries",
    "category_knowledge_current",
    "product_target_segments",
    "parameter_versions",
    "parameter_current",
    "promotion_proofs",
    "evidence_links",
    "claim_withdrawals",
)

TYPED_LINKS = """
CREATE FUNCTION public.m3_lifecycle_typed_links(t uuid,c uuid,value jsonb)
RETURNS uuid[] LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path TO 'pg_catalog','public','pg_temp'
AS $function$
DECLARE answer uuid[]='{}'; child record; item jsonb; parsed uuid; fixed uuid;
BEGIN
 IF jsonb_typeof(value)='object' THEN
  IF value->>'type'=ANY(ARRAY['artifact','original','claim','snapshot','knowledge','definition','parameter'])
   AND jsonb_typeof(value->'id')='string' AND jsonb_typeof(value->'version')='number' THEN
   BEGIN
    parsed=(value->>'id')::uuid;
    IF value->>'type'='parameter' THEN
     SELECT id INTO fixed FROM public.parameter_versions WHERE tenant_id=t AND category_id=c
      AND parameter_id=parsed AND version=(value->>'version')::integer;
     IF fixed IS NOT NULL THEN answer=array_append(answer,fixed); END IF;
    ELSE answer=array_append(answer,parsed); END IF;
   EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN NULL;
   END;
  END IF;
  FOR child IN SELECT key,v FROM jsonb_each(value) AS x(key,v) LOOP
   IF child.key=ANY(ARRAY['source_refs','direct_source_refs','context_refs','baseline_claim_refs',
    'sources','source_ref','source','representative_refs','evidence'])
    AND jsonb_typeof(child.v) IN ('object','array') THEN
    answer=answer || public.m3_lifecycle_typed_links(t,c,child.v);
   END IF;
  END LOOP;
 ELSIF jsonb_typeof(value)='array' THEN
  FOR item IN SELECT v FROM jsonb_array_elements(value) AS x(v) LOOP
   answer=answer || public.m3_lifecycle_typed_links(t,c,item);
  END LOOP;
 END IF;
 RETURN answer;
END;
$function$
"""

SOURCE_LINKS = """
CREATE FUNCTION public.m3_lifecycle_source_links(t uuid,c uuid,table_name text,payload jsonb)
RETURNS uuid[] LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path TO 'pg_catalog','public','pg_temp'
AS $function$
DECLARE links uuid[]='{}'; extra uuid[]; key text; keys text[]; item jsonb; container jsonb;
 target_kind text; referenced_target uuid; referenced_version integer;
BEGIN
 IF table_name='agent_runs' THEN RETURN public.kernel_lifecycle_links(table_name,payload); END IF;
 -- Only actual top-level relation columns establish raw UUID edges. Arbitrary
 -- content dictionaries are not relational rows, even if an extra key happens
 -- to be named source_id or item_id.
 keys=CASE table_name
  WHEN 'artifact_versions' THEN ARRAY['original_id']
  WHEN 'claims' THEN ARRAY['artifact_id','snapshot_id']
  WHEN 'definition_revisions' THEN ARRAY['derived_from_definition_id','parent_definition_id',
   'source_proposal_id','source_submission_id']
  WHEN 'definition_sources' THEN ARRAY['artifact_id']
  WHEN 'definition_specs' THEN ARRAY[]::text[]
  WHEN 'proposals' THEN ARRAY['baseline_definition_id','current_submission_id']
  WHEN 'proposal_items' THEN ARRAY[]::text[]
  WHEN 'proposal_item_versions' THEN ARRAY[]::text[]
  WHEN 'proposal_revisions' THEN ARRAY['proposal_id']
  WHEN 'proposal_sources' THEN ARRAY['source_id']
  WHEN 'proposal_submissions' THEN ARRAY[]::text[]
  WHEN 'proposal_decisions' THEN ARRAY['submission_id']
  WHEN 'project_open_items' THEN ARRAY['source_question_id','source_spec_item_id','g0_decision_id']
  WHEN 'category_knowledge_current' THEN ARRAY['current_entry_id']
  WHEN 'promotion_proofs' THEN ARRAY['knowledge_entry_id','source_proposal_id']
  WHEN 'evidence_links' THEN ARRAY['evidence_id']
  WHEN 'claim_withdrawals' THEN ARRAY['claim_id']
  ELSE ARRAY[]::text[] END;
 FOREACH key IN ARRAY keys LOOP
  IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;
 END LOOP;
 -- These stored fields are validated Reference containers. Do not feed the
 -- whole row or arbitrary content into the canonical Reference parser.
 IF table_name=ANY(ARRAY['proposals','proposal_item_versions','proposal_submissions',
  'category_knowledge_entries','definition_specs']) THEN
  FOREACH key IN ARRAY ARRAY['source_refs','direct_source_refs','context_refs','baseline_claim_refs'] LOOP
   links=links || public.m3_lifecycle_typed_links(t,c,payload->key);
  END LOOP;
 END IF;
 -- Match ItemInput.content_schema and category_service._references: only
 -- commercial_target, voice, and competitor have nested source contracts.
 IF table_name='proposal_item_versions' AND payload->>'kind'='commercial_target' THEN
  FOREACH key IN ARRAY ARRAY['target_price','cost','volume'] LOOP
   links=links || public.m3_lifecycle_typed_links(t,c,payload->'content'->key->'source');
  END LOOP;
 ELSIF table_name='category_knowledge_entries' AND payload->>'kind'='voice' THEN
  links=links || public.m3_lifecycle_typed_links(t,c,payload->'content'->'representative_refs');
 ELSIF table_name='category_knowledge_entries' AND payload->>'kind'='competitor' THEN
  FOREACH key IN ARRAY ARRAY['metrics','features','prices'] LOOP
   FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'content'->key,'[]')) LOOP
    links=links || public.m3_lifecycle_typed_links(t,c,item->'source_ref');
   END LOOP;
  END LOOP;
 END IF;
 IF table_name='proposal_submissions' THEN
  container=payload->'frozen_document';
  FOREACH key IN ARRAY ARRAY['source_refs','direct_source_refs','context_refs','baseline_claim_refs'] LOOP
   links=links || public.m3_lifecycle_typed_links(t,c,container->key);
  END LOOP;
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'items','[]')) LOOP
   links=links || public.m3_lifecycle_source_links(t,c,'proposal_item_versions',item-ARRAY['item_id','proposal_id']);
   -- The frozen read projection records actual EvidenceLink provenance here.
   links=links || public.m3_lifecycle_typed_links(t,c,item->'evidence_links');
  END LOOP;
 ELSIF table_name='promotion_proofs' THEN
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'source_item_refs','[]')) LOOP
   IF item->>'item_id' IS NOT NULL THEN links=array_append(links,(item->>'item_id')::uuid); END IF;
  END LOOP;
 END IF;
 -- Exact persisted EvidenceLink targets supplement these immutable versions.
 -- Reverted links and withdrawn Claims still retain the original historical
 -- dependency; lifecycle cleanup must not erase their audit source.
 IF table_name='proposal_item_versions' AND payload->>'item_id' IS NOT NULL THEN
  target_kind='proposal_item'; referenced_target=(payload->>'item_id')::uuid;
  referenced_version=(payload->>'version')::integer;
 ELSIF table_name='category_knowledge_entries' AND payload->>'id' IS NOT NULL THEN
  target_kind='knowledge_entry'; referenced_target=(payload->>'id')::uuid;
  referenced_version=(payload->>'version')::integer;
 ELSIF table_name='definition_specs' AND payload->>'id' IS NOT NULL THEN
  target_kind='definition_spec'; referenced_target=(payload->>'id')::uuid;
  SELECT revision INTO referenced_version FROM public.definition_revisions
   WHERE tenant_id=t AND category_id=c AND id=(payload->>'definition_id')::uuid;
 END IF;
 IF referenced_target IS NOT NULL AND referenced_version IS NOT NULL THEN
  SELECT coalesce(array_agg(link.evidence_id),'{}') INTO extra FROM public.evidence_links link
   WHERE link.tenant_id=t AND link.category_id=c AND link.target_type=target_kind
    AND link.target_id=referenced_target AND link.target_version=referenced_version;
  links=links || extra;
 END IF;
 -- Child source rows point to their parent, whereas dependency traversal needs
 -- the parent's fixed source children as well. Keep the actual relational edge.
 IF table_name='definition_revisions' THEN
  SELECT coalesce(array_agg(id),'{}') INTO extra FROM (
   SELECT id FROM public.definition_sources WHERE tenant_id=t AND category_id=c
    AND definition_id=(payload->>'id')::uuid
   UNION ALL SELECT id FROM public.definition_specs WHERE tenant_id=t AND category_id=c
    AND definition_id=(payload->>'id')::uuid
  ) children;
  links=links || extra;
 ELSIF table_name='proposals' THEN
  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.proposal_item_versions
   WHERE tenant_id=t AND category_id=c AND proposal_id=(payload->>'id')::uuid;
  links=links || extra;
 ELSIF table_name='proposal_items' THEN
  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.proposal_item_versions
   WHERE tenant_id=t AND category_id=c AND item_id=(payload->>'id')::uuid;
  links=links || extra;
 ELSIF table_name='product_target_segments' THEN
  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.category_knowledge_entries
   WHERE tenant_id=t AND category_id=c AND lineage_id=(payload->>'segment_lineage_id')::uuid
    AND version=(payload->>'segment_version')::integer;
  links=links || extra;
 ELSIF table_name='parameter_current' THEN
  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.parameter_versions
   WHERE tenant_id=t AND category_id=c AND parameter_id=(payload->>'parameter_id')::uuid
    AND version=(payload->>'current_version')::integer;
  links=links || extra;
 END IF;
 RETURN links;
END;
$function$
"""

ROW_LINKS = """
CREATE FUNCTION public.m3_lifecycle_row_links(t uuid,c uuid,table_name text,payload jsonb)
RETURNS uuid[] LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path TO 'pg_catalog','public','pg_temp'
AS $function$
DECLARE links uuid[]; key text; keys text[];
BEGIN
 links=public.m3_lifecycle_source_links(t,c,table_name,payload);
 -- Only the infrequent retention summary needs host/reverse relationships.
 -- They must not turn a source-free item INSERT into a proposal-history scan.
 keys=CASE table_name
  WHEN 'definition_sources' THEN ARRAY['definition_id']
  WHEN 'definition_specs' THEN ARRAY['definition_id']
  WHEN 'proposal_items' THEN ARRAY['proposal_id']
  WHEN 'proposal_item_versions' THEN ARRAY['proposal_id','item_id']
  WHEN 'proposal_sources' THEN ARRAY['proposal_id']
  WHEN 'proposal_submissions' THEN ARRAY['proposal_id']
  WHEN 'proposal_decisions' THEN ARRAY['proposal_id','created_definition_id']
  WHEN 'evidence_links' THEN ARRAY['target_id']
  ELSE ARRAY[]::text[] END;
 FOREACH key IN ARRAY keys LOOP
  IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;
 END LOOP;
 RETURN links;
END;
$function$
"""

NODES_TEMPLATE = """
CREATE FUNCTION public.m3_lifecycle_nodes(t uuid,c uuid,identities uuid[] DEFAULT NULL)
RETURNS TABLE(table_name text,node_id uuid,links uuid[])
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path TO 'pg_catalog','public','pg_temp'
AS $function$
DECLARE name text; payload jsonb; controls uuid[];
BEGIN
 IF identities IS NULL THEN
  SELECT coalesce(array_agg(id),'{}') INTO controls FROM public.action_receipts
   WHERE tenant_id=t AND category_id=c AND operation LIKE 'evidence.lifecycle.%';
 ELSE controls='{}'; END IF;
 FOREACH name IN ARRAY CASE WHEN identities IS NULL THEN __TABLES__ ELSE ARRAY[
  'artifact_versions','claims','definition_revisions','definition_sources','definition_specs',
  'proposals','proposal_items','proposal_item_versions','proposal_submissions','proposal_decisions',
  'category_knowledge_entries','category_knowledge_current','parameter_versions','parameter_current',
  'evidence_links','promotion_proofs'] END LOOP
  FOR payload IN EXECUTE CASE WHEN name=ANY(ARRAY['audit_entries','outbox_events','request_keys'])
   THEN format('SELECT to_jsonb(x) FROM public.%I x JOIN public.action_receipts r ON r.id=x.receipt_id AND r.tenant_id=x.tenant_id WHERE x.tenant_id=$1 AND r.category_id=$2',name)
   ELSE format('SELECT to_jsonb(x) FROM public.%I x WHERE tenant_id=$1 AND category_id=$2 AND ($3 IS NULL OR %I=ANY($3))',name,
    CASE name WHEN 'category_knowledge_current' THEN 'lineage_id'
     WHEN 'parameter_current' THEN 'parameter_id' ELSE 'id' END)
   END USING t,c,identities LOOP
   IF (payload->>'receipt_id')::uuid=ANY(controls) OR
    (name='action_receipts' AND payload->>'operation' LIKE 'evidence.lifecycle.%') THEN CONTINUE; END IF;
   table_name=name;
   node_id=CASE name WHEN 'category_knowledge_current' THEN (payload->>'lineage_id')::uuid
    WHEN 'parameter_current' THEN (payload->>'parameter_id')::uuid ELSE (payload->>'id')::uuid END;
   IF identities IS NULL THEN links=public.m3_lifecycle_row_links(t,c,name,payload);
   ELSE links=public.m3_lifecycle_source_links(t,c,name,payload); END IF;
   -- Preserve predecessor's conservative legacy graph; M3-only nodes use
   -- strictly typed/relational links. Root lookup never uses free-text UUIDs.
   IF identities IS NULL AND name<>ALL(__M3_TABLES__) THEN
    links=links || public.kernel_lifecycle_links(name,payload);
   END IF;
   RETURN NEXT;
  END LOOP;
 END LOOP;
END;
$function$
"""

ROOTS = """
CREATE FUNCTION public.m3_lifecycle_roots(t uuid,c uuid,table_name text,payload jsonb)
RETURNS uuid[] LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path TO 'pg_catalog','public','pg_temp'
AS $function$
DECLARE reached uuid[]; frontier uuid[]; expanded uuid[];
BEGIN
 reached=public.m3_lifecycle_source_links(t,c,table_name,payload);
 IF cardinality(reached)=0 THEN RETURN '{}'; END IF;
 frontier=reached;
 WHILE cardinality(frontier)>0 LOOP
  SELECT coalesce(array_agg(DISTINCT dependency),'{}') INTO expanded
   FROM public.m3_lifecycle_nodes(t,c,frontier) n CROSS JOIN LATERAL unnest(n.links) dependency
   WHERE NOT dependency=ANY(reached);
  reached=reached || expanded; frontier=expanded;
 END LOOP;
 SELECT coalesce(array_agg(DISTINCT id),'{}') INTO expanded FROM (
  SELECT id FROM public.uploaded_originals WHERE tenant_id=t AND category_id=c AND id=ANY(reached)
  UNION ALL SELECT id FROM public.upload_attempts WHERE tenant_id=t AND category_id=c AND id=ANY(reached)
  UNION ALL SELECT id FROM public.lifecycle_objects WHERE tenant_id=t AND category_id=c AND id=ANY(reached)
 ) originals;
 RETURN expanded;
END;
$function$
"""

CLOCK = """
CREATE FUNCTION public.m3_lifecycle_reference_clock()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog','public','pg_temp'
AS $function$
DECLARE payload jsonb; old_payload jsonb; roots uuid[]; t uuid; c uuid; model_id uuid;
BEGIN
 IF TG_OP='DELETE' THEN payload=to_jsonb(OLD); ELSE payload=to_jsonb(NEW); END IF;
 t=(payload->>'tenant_id')::uuid; c=(payload->>'category_id')::uuid;
 IF TG_OP='UPDATE' THEN
  old_payload=to_jsonb(OLD);
  IF ROW(payload->>'tenant_id',payload->>'category_id',payload->>'product_id') IS DISTINCT FROM
   ROW(old_payload->>'tenant_id',old_payload->>'category_id',old_payload->>'product_id') THEN
   RAISE EXCEPTION 'M3 lifecycle source scope is immutable' USING ERRCODE='23514'; END IF;
 END IF;
 PERFORM 1 FROM public.categories WHERE tenant_id=t AND id=c FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'M3 lifecycle category unavailable' USING ERRCODE='23514'; END IF;
 roots=public.m3_lifecycle_roots(t,c,TG_TABLE_NAME,payload);
 IF TG_OP='UPDATE' THEN roots=roots || public.m3_lifecycle_roots(t,c,TG_TABLE_NAME,old_payload); END IF;
 -- Sort actual product roots. Scope ids alone never become source references.
 FOR model_id IN SELECT DISTINCT id FROM (
  SELECT product_id AS id FROM public.uploaded_originals
   WHERE tenant_id=t AND category_id=c AND id=ANY(roots)
  UNION SELECT product_id FROM public.lifecycle_objects
   WHERE tenant_id=t AND category_id=c AND id=ANY(roots)
  UNION SELECT product_id FROM public.upload_attempts
   WHERE tenant_id=t AND category_id=c AND id=ANY(roots)
  UNION SELECT (payload->>'product_id')::uuid
 ) affected WHERE id IS NOT NULL ORDER BY id LOOP
  UPDATE public.products SET lifecycle_epoch=lifecycle_epoch+1
   WHERE tenant_id=t AND category_id=c AND id=model_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'M3 lifecycle product unavailable' USING ERRCODE='23514'; END IF;
 END LOOP;
 UPDATE public.categories SET lifecycle_epoch=lifecycle_epoch+1 WHERE tenant_id=t AND id=c;
 IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$function$
"""

GATE = """
CREATE FUNCTION public.m3_lifecycle_reference_gate()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog','public','pg_temp'
AS $function$
DECLARE payload jsonb; roots uuid[]; t uuid; c uuid;
BEGIN
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 payload=to_jsonb(NEW); t=NEW.tenant_id; c=NEW.category_id;
 roots=public.m3_lifecycle_roots(t,c,TG_TABLE_NAME,payload);
 IF EXISTS(SELECT 1 FROM public.lifecycle_objects o WHERE o.tenant_id=t AND o.category_id=c
  AND o.id=ANY(roots) AND (o.state->'value'->>'pending_intent_id' IS NOT NULL
   OR o.state->'value'->>'disposition' IN ('quarantined','unknown','purged'))) THEN
  RAISE EXCEPTION 'Pending original prohibits M3 business reference'
   USING ERRCODE='23514',CONSTRAINT='m3_source_reference_fence';
 END IF;
 RETURN NEW;
END;
$function$
"""

SUMMARY = """
CREATE OR REPLACE FUNCTION public.lifecycle_reference_summary(t uuid,c uuid,p uuid,roots uuid[])
RETURNS TABLE(object_id uuid,reference_count integer,formal_history boolean,read_version bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path TO 'pg_catalog','public','pg_temp'
AS $function$
DECLARE graph jsonb[]='{}'; reached uuid[]; selected integer[]; node jsonb; oid uuid;
 links uuid[]; row_id uuid; i integer; changed boolean;
BEGIN
 IF NOT category_access(t,c,false) OR (p IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM public.products WHERE tenant_id=t AND category_id=c AND id=p)) THEN RETURN; END IF;
 SELECT coalesce(array_agg(jsonb_build_object('table',n.table_name,'id',n.node_id,'links',n.links)),'{}')
  INTO graph FROM public.m3_lifecycle_nodes(t,c) n;
 IF p IS NULL THEN SELECT lifecycle_epoch INTO read_version FROM public.categories WHERE tenant_id=t AND id=c;
 ELSE SELECT lifecycle_epoch INTO read_version FROM public.products WHERE tenant_id=t AND category_id=c AND id=p; END IF;
 FOREACH oid IN ARRAY roots LOOP
  IF NOT (
   EXISTS(SELECT 1 FROM public.upload_attempts WHERE tenant_id=t AND category_id=c AND id=oid AND product_id IS NOT DISTINCT FROM p AND owner_id=scope_requester()) OR
   EXISTS(SELECT 1 FROM public.uploaded_originals WHERE tenant_id=t AND category_id=c AND id=oid AND product_id IS NOT DISTINCT FROM p AND owner_id=scope_requester()) OR
   EXISTS(SELECT 1 FROM public.lifecycle_objects WHERE tenant_id=t AND category_id=c AND id=oid AND product_id IS NOT DISTINCT FROM p AND owner_id=scope_requester())
  ) THEN CONTINUE; END IF;
  object_id=oid; reached=ARRAY[oid]; selected='{}'; changed=true;
  WHILE changed LOOP
   changed=false;
   IF cardinality(graph)>0 THEN
    FOR i IN 1..cardinality(graph) LOOP
     IF i=ANY(selected) THEN CONTINUE; END IF;
     node=graph[i]; row_id=(node->>'id')::uuid;
     SELECT coalesce(array_agg(v::uuid),'{}') INTO links FROM jsonb_array_elements_text(node->'links') AS x(v);
     IF row_id=oid OR links && reached THEN
      selected=array_append(selected,i);
      IF row_id IS NOT NULL AND NOT row_id=ANY(reached) THEN reached=array_append(reached,row_id); END IF;
      changed=true;
     END IF;
    END LOOP;
   END IF;
  END LOOP;
  reference_count=cardinality(selected); formal_history=false;
  FOREACH i IN ARRAY selected LOOP
   IF NOT (graph[i]->>'table'=ANY(ARRAY['uploaded_originals','artifact_versions','original_security',
    'original_scan_requests','original_scan_results','outbox_events','audit_entries'])) THEN
    formal_history=true; EXIT;
   END IF;
  END LOOP;
  RETURN NEXT;
 END LOOP;
END;
$function$
"""

SCHEMA_SQL = (
    TYPED_LINKS,
    SOURCE_LINKS,
    ROW_LINKS,
    NODES_TEMPLATE.replace(
        "__TABLES__", "ARRAY[" + ",".join("'" + n + "'" for n in GRAPH_TABLES) + "]"
    ).replace("__M3_TABLES__", "ARRAY[" + ",".join("'" + n + "'" for n in M3_TABLES) + "]"),
    ROOTS,
    CLOCK,
    GATE,
    SUMMARY,
    "REVOKE ALL ON FUNCTION public.m3_lifecycle_typed_links(uuid,uuid,jsonb), "
    "public.m3_lifecycle_source_links(uuid,uuid,text,jsonb), "
    "public.m3_lifecycle_row_links(uuid,uuid,text,jsonb), public.m3_lifecycle_nodes(uuid,uuid,uuid[]), "
    "public.m3_lifecycle_roots(uuid,uuid,text,jsonb), public.m3_lifecycle_reference_clock(), "
    "public.m3_lifecycle_reference_gate() FROM PUBLIC,pdos_next_app,pdos_next_auth,pdos_next_dispatch,pdos_agent",
    *(
        f"CREATE TRIGGER category_lifecycle_clock BEFORE INSERT OR UPDATE OR DELETE ON public.{name} "
        "FOR EACH ROW EXECUTE FUNCTION public.m3_lifecycle_reference_clock()"
        for name in M3_TABLES
    ),
    *(
        f"CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON public.{name} "
        "FOR EACH ROW EXECUTE FUNCTION public.m3_lifecycle_reference_gate()"
        for name in M3_TABLES
    ),
)
DOWNGRADE_SQL = (
    *(f"DROP TRIGGER lifecycle_reference ON public.{name}" for name in M3_TABLES),
    *(f"DROP TRIGGER category_lifecycle_clock ON public.{name}" for name in M3_TABLES),
    PREDECESSOR_SUMMARY,
    "DROP FUNCTION public.m3_lifecycle_reference_gate()",
    "DROP FUNCTION public.m3_lifecycle_reference_clock()",
    "DROP FUNCTION public.m3_lifecycle_roots(uuid,uuid,text,jsonb)",
    "DROP FUNCTION public.m3_lifecycle_nodes(uuid,uuid,uuid[])",
    "DROP FUNCTION public.m3_lifecycle_row_links(uuid,uuid,text,jsonb)",
    "DROP FUNCTION public.m3_lifecycle_source_links(uuid,uuid,text,jsonb)",
    "DROP FUNCTION public.m3_lifecycle_typed_links(uuid,uuid,jsonb)",
)
