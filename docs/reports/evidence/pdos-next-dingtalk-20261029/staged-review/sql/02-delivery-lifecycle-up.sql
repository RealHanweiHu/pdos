CREATE POLICY dingtalk_lifecycle_owner_metadata ON public.dingtalk_deliveries FOR SELECT TO pdos_next_owner USING (tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid);

GRANT SELECT(id,tenant_id,content_kind,source_dependencies) ON public.dingtalk_deliveries TO pdos_next_owner;

CREATE OR REPLACE FUNCTION public.m3_lifecycle_source_links(t uuid, c uuid, table_name text, payload jsonb)
 RETURNS uuid[]
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
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
  WHEN 'manufacturing_baseline_publications' THEN ARRAY['baseline_id','process_id','previous_id']
  WHEN 'manufacturing_publication_currents' THEN ARRAY['version_id']
  WHEN 'manufacturing_publication_documents' THEN ARRAY['document_id','process_id']
  WHEN 'native_pilot_runs' THEN ARRAY['build_id','lot_id','actual_configuration_id','engineering_configuration_id','process_id','publication_id']
  WHEN 'native_pilot_currents' THEN ARRAY['pilot_id','latest_observation_id']
  WHEN 'native_pilot_observations' THEN ARRAY['pilot_id','previous_observation_id']
  WHEN 'release_packages' THEN ARRAY['previous_id']
  WHEN 'release_package_currents' THEN ARRAY['version_id']
  WHEN 'release_decisions' THEN ARRAY['package_id']
  WHEN 'release_policy_facts' THEN ARRAY['previous_id']
  WHEN 'release_policy_currents' THEN ARRAY['fact_id']
  WHEN 'external_handoff_authorizations' THEN ARRAY['package_id','engineering_decision_id','manufacturing_decision_id']
  WHEN 'external_delivery_intents' THEN ARRAY['handoff_id']
  WHEN 'external_receipts' THEN ARRAY['handoff_id','intent_id','previous_receipt_id','reconciles_id']
  WHEN 'external_handoff_currents' THEN ARRAY['handoff_id','intent_id','latest_receipt_id']
  WHEN 'release_exception_decisions' THEN ARRAY['basis_package_id','policy_fact_id','previous_id']
  WHEN 'release_exception_currents' THEN ARRAY['basis_package_id','policy_fact_id','decision_id']
  WHEN 'work_commitment_reviews' THEN ARRAY['commitment_id','task_version_id','submission_id','previous_id']
  WHEN 'work_commitment_review_currents' THEN ARRAY['version_id']
  WHEN 'external_wait_versions' THEN ARRAY['previous_id']
  WHEN 'external_wait_currents' THEN ARRAY['version_id']
  WHEN 'project_risk_followups' THEN ARRAY['previous_id','risk_id','g0_decision_id']
  WHEN 'project_risk_followup_currents' THEN ARRAY['version_id']
  WHEN 'work_task_versions' THEN ARRAY['previous_id']
  WHEN 'work_task_currents' THEN ARRAY['version_id']
  WHEN 'work_commitment_versions' THEN ARRAY['replaces_id']
  WHEN 'work_commitment_currents' THEN ARRAY['version_id']
  WHEN 'project_status_updates' THEN ARRAY[]::text[]
  ELSE ARRAY[]::text[] END;
 FOREACH key IN ARRAY keys LOOP
  IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;
 END LOOP;
 -- Publication's exact saved read set is a validated Artifact relationship.
 -- Do not scan its declaration, body, reason or arbitrary JSON UUID values.
 IF table_name IN ('manufacturing_baseline_publications','native_pilot_runs','native_pilot_observations','release_packages','release_decisions','release_policy_facts','external_handoff_authorizations','external_receipts','release_exception_decisions') THEN
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'required_source_read_set','[]')) LOOP
   IF item->>'artifact_id' IS NOT NULL THEN
    links=array_append(links,(item->>'artifact_id')::uuid);
   END IF;
  END LOOP;
 END IF;
 IF table_name IN ('native_pilot_runs','native_pilot_observations') THEN
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{material_snapshot,statistics,samples}','[]')) LOOP
   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;
  END LOOP;
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{material_snapshot,statistics,issues}','[]')) LOOP
   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;
  END LOOP;
  item=payload#>'{material_snapshot,statistics,resource,fact}';
  IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;
 END IF;
 IF table_name='release_packages' THEN
  -- FixedObject.ref is a closed, server-resolved version reference, not arbitrary body UUID text.
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{body,objects}','[]')) LOOP
   container=item->'ref';
   IF container->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','manufacturing_publication','test_run','pilot_run','issue','change','exception','artifact','work_instruction','control_plan','build_lot','line'])
    AND container->>'id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); END IF;
  END LOOP;
 END IF;
 IF table_name IN ('external_handoff_authorizations','external_delivery_intents') THEN
  -- Only closed, owner-verified mapping and manifest references are source edges.
  container=CASE WHEN table_name='external_handoff_authorizations' THEN payload#>'{body,declaration}' ELSE payload->'body' END;
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'mappings','[]')) LOOP
   IF item->'ref'->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','part','bom_revision','artifact','work_instruction','control_plan'])
    AND item->'ref'->>'id' IS NOT NULL THEN links=array_append(links,(item->'ref'->>'id')::uuid); END IF;
  END LOOP;
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'manifest','[]')) LOOP
   IF item->'artifact'->>'id' IS NOT NULL THEN links=array_append(links,(item->'artifact'->>'id')::uuid); END IF;
  END LOOP;
 END IF;
 IF table_name='release_policy_facts' THEN
  -- These are Closed DTO configuration references fixed by the policy owner.
  FOREACH key IN ARRAY ARRAY['definition','engineering_configuration','manufacturing_configuration'] LOOP
   container=payload#>ARRAY['material','subject_config',key];
   IF container->>'id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); END IF;
  END LOOP;
 END IF;
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

 IF table_name IN ('work_task_versions','work_commitment_versions','project_status_updates') THEN
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP
   IF item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'artifact_id')::uuid); END IF;
  END LOOP;
  IF table_name='work_task_versions' AND payload#>>'{body,plan_task,id}' IS NOT NULL THEN
   links=array_append(links,(payload#>>'{body,plan_task,id}')::uuid);
  END IF;
  IF table_name='work_commitment_versions' THEN
   SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.work_task_versions
    WHERE tenant_id=t AND category_id=c AND task_id=(payload->>'task_id')::uuid AND revision=(payload->>'task_revision')::integer;
   links=links||extra;
  ELSIF table_name='project_status_updates' THEN
   FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'task_refs','[]')) LOOP
    SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.work_task_versions
     WHERE tenant_id=t AND category_id=c AND task_id=(item->>'id')::uuid AND revision=(item->>'revision')::integer;
    links=links||extra;
   END LOOP;
  END IF;
 END IF;

 IF table_name='work_commitment_reviews' THEN
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP
   IF item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'artifact_id')::uuid); END IF;
  END LOOP;
 END IF;

 IF table_name='external_wait_versions' THEN
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP
   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;
  END LOOP;
  FOREACH key IN ARRAY ARRAY['milestone','build','calendar'] LOOP
   container=payload#>ARRAY['body',key];
   IF container->>'id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); END IF;
  END LOOP;
  container=payload#>'{body,replaces}';
  IF container->>'id' IS NOT NULL THEN
   SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.external_wait_versions
    WHERE tenant_id=t AND category_id=c AND wait_id=(container->>'id')::uuid AND revision=(container->>'revision')::integer;
   links=links||extra;
  END IF;
 END IF;
 IF table_name='project_risk_followups' THEN
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP
   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;
  END LOOP;
 END IF;

 IF table_name IN ('knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents') THEN
  FOREACH key IN ARRAY ARRAY['previous_id','version_id','candidate_version_id','assessment_id','publication_id'] LOOP
   IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;
  END LOOP;
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP
   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;
  END LOOP;
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP
   IF item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'artifact_id')::uuid); END IF;
  END LOOP;
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{source_basis,result_receipts}','[]')) LOOP
   IF item->>'receipt_id' IS NOT NULL THEN links=array_append(links,(item->>'receipt_id')::uuid); END IF;
   IF item->>'row_id' IS NOT NULL THEN links=array_append(links,(item->>'row_id')::uuid); END IF;
  END LOOP;
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{source_basis,professional,fact_refs}','[]')) LOOP
   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;
  END LOOP;
  IF payload#>>'{source_basis,target,id}' IS NOT NULL THEN links=array_append(links,(payload#>>'{source_basis,target,id}')::uuid); END IF;
 END IF;

 IF table_name IN ('field_feedback_versions','field_feedback_currents','field_response_records') THEN
  FOREACH key IN ARRAY ARRAY['previous_id','version_id','feedback_version_id'] LOOP
   IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;
  END LOOP;
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP
   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;
  END LOOP;
  FOREACH key IN ARRAY ARRAY['engineering_configuration','manufacturing_configuration','batch'] LOOP
   IF payload#>>ARRAY['body','location',key,'id'] IS NOT NULL THEN links=array_append(links,(payload#>>ARRAY['body','location',key,'id'])::uuid); END IF;
  END LOOP;
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{source_basis,result_receipts}','[]')) LOOP
   IF item->>'receipt_id' IS NOT NULL THEN links=array_append(links,(item->>'receipt_id')::uuid); END IF;
   IF item->>'row_id' IS NOT NULL THEN links=array_append(links,(item->>'row_id')::uuid); END IF;
  END LOOP;
 END IF;
 IF table_name IN ('change_request_versions','change_graph_captures') THEN
  FOR container IN SELECT value FROM jsonb_each(coalesce(payload#>'{source_basis,owners}','{}')) LOOP
   IF container->>'feedback_version_id' IS NOT NULL THEN links=array_append(links,(container->>'feedback_version_id')::uuid); END IF;
  END LOOP;
 END IF;

 -- Closed native Field plan and occurrence references, never arbitrary UUID prose.
 IF table_name='controlled_change_selection_facts' AND payload->>'basis_kind'='field_intent' THEN
  IF payload->>'feedback_version_id' IS NOT NULL THEN
   links=array_append(links,(payload->>'feedback_version_id')::uuid);
  END IF;
 END IF;
 IF table_name='change_implementation_captures'
  AND payload#>>'{occurrence_snapshot,schema_version}'='pdos-field-change-implementation-occurrence-v1' THEN
  FOREACH key IN ARRAY ARRAY['feedback_version_id','selection_id'] LOOP
   IF payload#>>ARRAY['occurrence_snapshot',key] IS NOT NULL THEN
    links=array_append(links,(payload#>>ARRAY['occurrence_snapshot',key])::uuid);
   END IF;
  END LOOP;
 END IF;

 IF table_name='change_completion_records' THEN
  FOREACH key IN ARRAY ARRAY['project_id','change_version_id','order_record_id','shared_proof_id'] LOOP
   IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;
  END LOOP;
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'required_source_read_set','[]')) LOOP
   IF item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'artifact_id')::uuid); END IF;
  END LOOP;
  IF payload#>>'{native_input,lot,id}' IS NOT NULL THEN links=array_append(links,(payload#>>'{native_input,lot,id}')::uuid); END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{native_input,sample_refs}','[]')) LOOP
   links=array_append(links,(item->>'id')::uuid);
  END LOOP;
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{native_input,mappings}','[]')) LOOP
   SELECT coalesce(array_agg(id),'{}') INTO extra FROM verification_run_versions
    WHERE tenant_id=t AND category_id=c AND run_id=(item#>>'{run,id}')::uuid AND revision=(item#>>'{run,revision}')::integer;
   links=links||extra; links=array_append(links,(item->>'sample_id')::uuid);
  END LOOP;
 END IF;

 -- Closed native owner DTOs: retain exact outputs and native execution/report rows.
 IF table_name='change_completion_records' THEN
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{fact_snapshot,output_refs}','[]')) LOOP
   IF item->>'kind'='test_run' THEN
    SELECT coalesce(array_agg(id),'{}') INTO extra FROM verification_run_versions
     WHERE tenant_id=t AND category_id=c AND run_id=(item->>'id')::uuid AND revision=(item->>'revision')::integer;
    links=links||extra;
   ELSIF item->>'kind'=ANY(ARRAY['engineering_configuration','manufacturing_configuration','build','sample']) THEN
    links=array_append(links,(item->>'id')::uuid);
   END IF;
  END LOOP;
  IF payload#>>'{owner_basis,schema_version}'='pdos-native-build-adoption-read-v1' THEN
   FOREACH key IN ARRAY ARRAY['previous_build','successor_build','actual_configuration','lot','start'] LOOP
    IF payload#>>ARRAY['owner_basis',key,'id'] IS NOT NULL THEN
     links=array_append(links,(payload#>>ARRAY['owner_basis',key,'id'])::uuid);
    END IF;
   END LOOP;
  ELSIF payload#>>'{owner_basis,schema_version}'='pdos-native-change-run-verification-v1' THEN
   FOR container IN SELECT value FROM jsonb_each(coalesce(payload#>'{owner_basis,runs}','{}')) LOOP
    FOREACH key IN ARRAY ARRAY['run_version_id','request_version_id','projection_id'] LOOP
     IF container->>key IS NOT NULL THEN links=array_append(links,(container->>key)::uuid); END IF;
    END LOOP;
   END LOOP;
  END IF;
 END IF;

 -- F: only server-verified fixed answer proofs establish these dependency edges.
 -- Native deferred atoms bind these exact arrays to real source ledgers.
 IF table_name IN ('category_knowledge_entries','knowledge_candidate_versions','knowledge_rule_versions','knowledge_answer_reviews','knowledge_gap_submissions') THEN
  container=CASE table_name WHEN 'category_knowledge_entries' THEN payload->'answer_sources'
   WHEN 'knowledge_candidate_versions' THEN payload#>'{source_basis,answer_sources}'
   WHEN 'knowledge_rule_versions' THEN payload#>'{source_basis,answer_sources}'
   ELSE payload->'source_proof' END;
  links=links||public.assistant_source_lifecycle_links(t,c,coalesce(container,'[]'::jsonb));
 END IF;

 -- G private outbound body copies have no category column. Only the fixed
 -- server footprint subset for this REAL category establishes retention edges.
 IF table_name='dingtalk_deliveries' THEN
  IF payload->>'tenant_id' IS DISTINCT FROM t::text OR c IS NULL THEN
   RAISE EXCEPTION 'Delivery retention scope mismatch' USING ERRCODE='23514'; END IF;
  SELECT coalesce(jsonb_agg(value),'[]'::jsonb) INTO container
   FROM jsonb_array_elements(coalesce(payload->'source_dependencies','[]'::jsonb))
   WHERE value->>'category_id'=c::text;
  links=links||public.assistant_source_lifecycle_links(t,c,container);
 END IF;
 RETURN links;
END;
$function$;

CREATE OR REPLACE FUNCTION public.m3_lifecycle_nodes(t uuid, c uuid, identities uuid[] DEFAULT NULL::uuid[])
 RETURNS TABLE(table_name text, node_id uuid, links uuid[])
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE name text; payload jsonb; controls uuid[];
BEGIN
 IF identities IS NULL THEN
  SELECT coalesce(array_agg(id),'{}') INTO controls FROM public.action_receipts
   WHERE tenant_id=t AND category_id=c AND operation LIKE 'evidence.lifecycle.%';
 ELSE controls='{}'; END IF;
 FOREACH name IN ARRAY CASE WHEN identities IS NULL THEN ARRAY['agent_runs','action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','project_risk_followups','project_risk_followup_currents','knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents','field_feedback_versions','field_feedback_currents','field_response_records','knowledge_answer_reviews','knowledge_gap_submissions'] ELSE ARRAY[
  'artifact_versions','claims','definition_revisions','definition_sources','definition_specs',
  'proposals','proposal_items','proposal_item_versions','proposal_submissions','proposal_decisions',
  'category_knowledge_entries','category_knowledge_current','parameter_versions','parameter_current',
  'evidence_links','promotion_proofs','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','project_risk_followups','project_risk_followup_currents','knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents','field_feedback_versions','field_feedback_currents','field_response_records','knowledge_answer_reviews','knowledge_gap_submissions'] END LOOP
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
   IF identities IS NULL AND name<>ALL(ARRAY['native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','project_risk_followups','project_risk_followup_currents','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents','field_feedback_versions','field_feedback_currents','field_response_records','knowledge_answer_reviews','knowledge_gap_submissions']) THEN
    links=links || public.kernel_lifecycle_links(name,payload);
   END IF;
   RETURN NEXT;
  END LOOP;
 END LOOP;

 -- Read exactly the retained metadata, never Delivery.payload. One personal
 -- answer may appear in several categories, each with its own source subset.
 FOR payload IN
  SELECT jsonb_build_object('id',d.id,'tenant_id',d.tenant_id,
   'content_kind',d.content_kind,'source_dependencies',d.source_dependencies)
  FROM public.dingtalk_deliveries d
  WHERE d.tenant_id=t AND d.content_kind='answer'
   AND (identities IS NULL OR d.id=ANY(identities))
   AND EXISTS(SELECT 1 FROM jsonb_array_elements(d.source_dependencies) dependency
    WHERE dependency->>'category_id'=c::text)
 LOOP
  table_name='dingtalk_deliveries'; node_id=(payload->>'id')::uuid;
  links=public.m3_lifecycle_source_links(t,c,table_name,payload);
  RETURN NEXT;
 END LOOP;
END;
$function$;

CREATE FUNCTION public.dingtalk_lifecycle_reference_clock() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $dingtalk_lifecycle$
DECLARE t uuid; dependencies jsonb; kind text; payload jsonb; categories uuid[];
 c uuid; model_id uuid; roots uuid[]='{}'; affected integer;
BEGIN
 IF TG_TABLE_NAME<>'dingtalk_deliveries' THEN RAISE EXCEPTION 'Delivery-only lifecycle guard' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
  IF ROW(NEW.tenant_id,NEW.source_dependencies,NEW.content_kind,NEW.payload_sha256) IS DISTINCT FROM
   ROW(OLD.tenant_id,OLD.source_dependencies,OLD.content_kind,OLD.payload_sha256) THEN
   RAISE EXCEPTION 'Delivery retention footprint is immutable' USING ERRCODE='23514',CONSTRAINT='dingtalk_source_identity_immutable'; END IF;
  -- Transport receipt/state updates neither create nor remove this immutable
  -- copy. They remain possible while old roots are pending/quarantined.
  RETURN NEW;
 END IF;
 IF TG_OP='DELETE' THEN t=OLD.tenant_id; dependencies=OLD.source_dependencies; kind=OLD.content_kind;
 ELSE t=NEW.tenant_id; dependencies=NEW.source_dependencies; kind=NEW.content_kind; END IF;
 IF t IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid
  OR jsonb_typeof(dependencies) IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'Delivery retention tenant/shape mismatch' USING ERRCODE='23514'; END IF;
 IF kind<>'answer' THEN
  IF jsonb_array_length(dependencies)<>0 THEN RAISE EXCEPTION 'Control messages have no business footprint' USING ERRCODE='23514'; END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
 END IF;
 IF jsonb_array_length(dependencies)=0 OR EXISTS(SELECT 1 FROM jsonb_array_elements(dependencies) d
  WHERE jsonb_typeof(d)<>'object' OR NOT(d ?& ARRAY['source_type','source_id','source_revision','content_hash','category_id'])
   OR d-ARRAY['source_type','source_id','source_revision','content_hash','category_id']<>'{}'::jsonb
   OR d->>'category_id' IS NULL) THEN
  RAISE EXCEPTION 'Fixed Delivery source footprint required' USING ERRCODE='23514'; END IF;
 SELECT array_agg(id ORDER BY id) INTO categories FROM
  (SELECT DISTINCT (value->>'category_id')::uuid AS id FROM jsonb_array_elements(dependencies)) groups;
 -- Preserve native category→product order: lock ALL actual categories sorted
 -- before touching any product, then update actual root products sorted.
 PERFORM 1 FROM public.categories WHERE tenant_id=t AND id=ANY(categories) ORDER BY id FOR UPDATE;
 GET DIAGNOSTICS affected=ROW_COUNT;
 IF affected<>cardinality(categories) THEN RAISE EXCEPTION 'Delivery source category unavailable' USING ERRCODE='23514'; END IF;
 payload=jsonb_build_object('tenant_id',t,'source_dependencies',dependencies,'content_kind',kind);
 FOREACH c IN ARRAY categories LOOP
  roots=roots||public.m3_lifecycle_roots(t,c,'dingtalk_deliveries',payload);
 END LOOP;
 FOR model_id IN SELECT DISTINCT id FROM (
  SELECT product_id AS id FROM public.uploaded_originals WHERE tenant_id=t AND category_id=ANY(categories) AND id=ANY(roots)
  UNION SELECT product_id FROM public.lifecycle_objects WHERE tenant_id=t AND category_id=ANY(categories) AND id=ANY(roots)
  UNION SELECT product_id FROM public.upload_attempts WHERE tenant_id=t AND category_id=ANY(categories) AND id=ANY(roots)
 ) affected_products WHERE id IS NOT NULL ORDER BY id LOOP
  UPDATE public.products SET lifecycle_epoch=lifecycle_epoch+1
   WHERE tenant_id=t AND category_id=ANY(categories) AND id=model_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'Delivery source product unavailable' USING ERRCODE='23514'; END IF;
 END LOOP;
 UPDATE public.categories SET lifecycle_epoch=lifecycle_epoch+1 WHERE tenant_id=t AND id=ANY(categories);
 IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$dingtalk_lifecycle$;

ALTER FUNCTION public.dingtalk_lifecycle_reference_clock() OWNER TO pdos_next_owner;

REVOKE ALL ON FUNCTION public.dingtalk_lifecycle_reference_clock() FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch;

GRANT EXECUTE ON FUNCTION public.dingtalk_lifecycle_reference_clock() TO pdos_next_owner;

CREATE FUNCTION public.dingtalk_lifecycle_reference_gate() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $dingtalk_lifecycle$
DECLARE c uuid; roots uuid[]; payload jsonb;
BEGIN
 IF TG_TABLE_NAME<>'dingtalk_deliveries' THEN RAISE EXCEPTION 'Delivery-only lifecycle guard' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 IF TG_OP='UPDATE' THEN
  IF ROW(NEW.tenant_id,NEW.source_dependencies,NEW.content_kind,NEW.payload_sha256) IS DISTINCT FROM
   ROW(OLD.tenant_id,OLD.source_dependencies,OLD.content_kind,OLD.payload_sha256) THEN
   RAISE EXCEPTION 'Delivery retention footprint is immutable' USING ERRCODE='23514',CONSTRAINT='dingtalk_source_identity_immutable'; END IF;
  RETURN NEW;
 END IF;
 IF NEW.content_kind<>'answer' THEN RETURN NEW; END IF;
 payload=jsonb_build_object('tenant_id',NEW.tenant_id,'content_kind',NEW.content_kind,'source_dependencies',NEW.source_dependencies);
 FOR c IN SELECT DISTINCT (value->>'category_id')::uuid FROM jsonb_array_elements(NEW.source_dependencies) ORDER BY 1 LOOP
  roots=public.m3_lifecycle_roots(NEW.tenant_id,c,'dingtalk_deliveries',payload);
  IF EXISTS(SELECT 1 FROM public.lifecycle_objects o WHERE o.tenant_id=NEW.tenant_id AND o.category_id=c
   AND o.id=ANY(roots) AND (o.state->'value'->>'pending_intent_id' IS NOT NULL
    OR o.state->'value'->>'disposition' IN ('quarantined','unknown','purged'))) THEN
   RAISE EXCEPTION 'Pending original prohibits outbound body copy'
    USING ERRCODE='23514',CONSTRAINT='m3_source_reference_fence'; END IF;
 END LOOP;
 RETURN NEW;
END;
$dingtalk_lifecycle$;

ALTER FUNCTION public.dingtalk_lifecycle_reference_gate() OWNER TO pdos_next_owner;

REVOKE ALL ON FUNCTION public.dingtalk_lifecycle_reference_gate() FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch;

GRANT EXECUTE ON FUNCTION public.dingtalk_lifecycle_reference_gate() TO pdos_next_owner;

CREATE TRIGGER category_lifecycle_clock BEFORE INSERT OR UPDATE OR DELETE ON public.dingtalk_deliveries FOR EACH ROW EXECUTE FUNCTION public.dingtalk_lifecycle_reference_clock();

CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON public.dingtalk_deliveries FOR EACH ROW EXECUTE FUNCTION public.dingtalk_lifecycle_reference_gate();
