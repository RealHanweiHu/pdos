"""Optional native answer proof NULL handling; root assigns the actual next revision.

The previous function is the exact G843 candidate pin. Only optional knowledge
answer_sources normalize absent/JSON null; mandatory F and G proofs stay strict.
"""
# ruff: noqa: E501 -- auditable complete static SQL function pins

SIGNATURE = "m3_lifecycle_source_links(uuid,uuid,text,jsonb)"

PREVIOUS_FUNCTIONS = {SIGNATURE: r"""CREATE OR REPLACE FUNCTION public.m3_lifecycle_source_links(t uuid, c uuid, table_name text, payload jsonb)
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
$function$
"""}

NATIVE_FUNCTIONS = {SIGNATURE: r"""CREATE OR REPLACE FUNCTION public.m3_lifecycle_source_links(t uuid, c uuid, table_name text, payload jsonb)
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
  -- Only these native knowledge rows have an optional answer-derived proof.
  -- to_jsonb(row) represents an SQL NULL column as a JSON null member.
  IF table_name IN ('category_knowledge_entries','knowledge_candidate_versions','knowledge_rule_versions') THEN
   container=coalesce(nullif(container,'null'::jsonb),'[]'::jsonb);
  END IF;
  -- Review/Gap proof remains required and reaches the strict resolver unchanged.
  links=links||public.assistant_source_lifecycle_links(t,c,container);
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
$function$
"""}

SCHEMA_SQL = tuple(NATIVE_FUNCTIONS.values())
DOWNGRADE_SQL = tuple(PREVIOUS_FUNCTIONS.values())
