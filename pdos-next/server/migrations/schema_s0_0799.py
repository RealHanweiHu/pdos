"""Frozen knowledge candidates, exact applicability and named publication schema."""

PREVIOUS_FUNCTIONS = {'m3_lifecycle_row_links(uuid,uuid,text,jsonb)': 'CREATE OR REPLACE FUNCTION '
                                                 'public.m3_lifecycle_row_links(t uuid, c uuid, '
                                                 'table_name text, payload jsonb)\n'
                                                 ' RETURNS uuid[]\n'
                                                 ' LANGUAGE plpgsql\n'
                                                 ' STABLE SECURITY DEFINER\n'
                                                 " SET search_path TO 'pg_catalog', 'public', "
                                                 "'pg_temp'\n"
                                                 'AS $function$\n'
                                                 'DECLARE links uuid[]; key text; keys text[];\n'
                                                 'BEGIN\n'
                                                 ' '
                                                 'links=public.m3_lifecycle_source_links(t,c,table_name,payload);\n'
                                                 ' -- Only the infrequent retention summary needs '
                                                 'host/reverse relationships.\n'
                                                 ' -- They must not turn a source-free item INSERT '
                                                 'into a proposal-history scan.\n'
                                                 ' keys=CASE table_name\n'
                                                 "  WHEN 'definition_sources' THEN "
                                                 "ARRAY['definition_id']\n"
                                                 "  WHEN 'definition_specs' THEN "
                                                 "ARRAY['definition_id']\n"
                                                 "  WHEN 'proposal_items' THEN ARRAY['proposal_id']\n"
                                                 "  WHEN 'proposal_item_versions' THEN "
                                                 "ARRAY['proposal_id','item_id']\n"
                                                 "  WHEN 'proposal_sources' THEN ARRAY['proposal_id']\n"
                                                 "  WHEN 'proposal_submissions' THEN "
                                                 "ARRAY['proposal_id']\n"
                                                 "  WHEN 'proposal_decisions' THEN "
                                                 "ARRAY['proposal_id','created_definition_id']\n"
                                                 "  WHEN 'evidence_links' THEN ARRAY['target_id']\n"
                                                 "  WHEN 'manufacturing_baseline_publications' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'manufacturing_publication_currents' THEN "
                                                 "ARRAY['series_id']\n"
                                                 "  WHEN 'manufacturing_publication_documents' THEN "
                                                 "ARRAY['publication_id']\n"
                                                 "  WHEN 'native_pilot_runs' THEN ARRAY['project_id']\n"
                                                 "  WHEN 'native_pilot_currents' THEN "
                                                 "ARRAY['pilot_id']\n"
                                                 "  WHEN 'native_pilot_observations' THEN "
                                                 "ARRAY['pilot_id']\n"
                                                 "  WHEN 'release_packages' THEN "
                                                 "ARRAY['project_id','series_id']\n"
                                                 "  WHEN 'release_package_currents' THEN "
                                                 "ARRAY['series_id']\n"
                                                 "  WHEN 'release_decisions' THEN ARRAY['package_id']\n"
                                                 "  WHEN 'release_policy_facts' THEN "
                                                 "ARRAY['project_id','series_id']\n"
                                                 "  WHEN 'release_policy_currents' THEN "
                                                 "ARRAY['series_id']\n"
                                                 "  WHEN 'external_handoff_authorizations' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'external_delivery_intents' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'external_receipts' THEN ARRAY['project_id']\n"
                                                 "  WHEN 'external_handoff_currents' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'release_exception_decisions' THEN "
                                                 "ARRAY['project_id','series_id']\n"
                                                 "  WHEN 'release_exception_currents' THEN "
                                                 "ARRAY['project_id','series_id']\n"
                                                 "  WHEN 'work_commitment_reviews' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'work_commitment_review_currents' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'external_wait_versions' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'external_wait_currents' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'project_risk_followups' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'project_risk_followup_currents' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'work_task_versions' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'work_task_currents' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'work_commitment_versions' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'work_commitment_currents' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'project_status_updates' THEN "
                                                 "ARRAY['project_id']\n"
                                                 '  ELSE ARRAY[]::text[] END;\n'
                                                 ' FOREACH key IN ARRAY keys LOOP\n'
                                                 '  IF payload->>key IS NOT NULL THEN '
                                                 'links=array_append(links,(payload->>key)::uuid); END '
                                                 'IF;\n'
                                                 ' END LOOP;\n'
                                                 ' RETURN links;\n'
                                                 'END;\n'
                                                 '$function$\n',
 'm3_lifecycle_nodes(uuid,uuid,uuid[])': 'CREATE OR REPLACE FUNCTION public.m3_lifecycle_nodes(t uuid, '
                                         'c uuid, identities uuid[] DEFAULT NULL::uuid[])\n'
                                         ' RETURNS TABLE(table_name text, node_id uuid, links uuid[])\n'
                                         ' LANGUAGE plpgsql\n'
                                         ' STABLE SECURITY DEFINER\n'
                                         " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                         'AS $function$\n'
                                         'DECLARE name text; payload jsonb; controls uuid[];\n'
                                         'BEGIN\n'
                                         ' IF identities IS NULL THEN\n'
                                         "  SELECT coalesce(array_agg(id),'{}') INTO controls FROM "
                                         'public.action_receipts\n'
                                         '   WHERE tenant_id=t AND category_id=c AND operation LIKE '
                                         "'evidence.lifecycle.%';\n"
                                         " ELSE controls='{}'; END IF;\n"
                                         ' FOREACH name IN ARRAY CASE WHEN identities IS NULL THEN '
                                         "ARRAY['agent_runs','action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','project_risk_followups','project_risk_followup_currents'] "
                                         'ELSE ARRAY[\n'
                                         '  '
                                         "'artifact_versions','claims','definition_revisions','definition_sources','definition_specs',\n"
                                         '  '
                                         "'proposals','proposal_items','proposal_item_versions','proposal_submissions','proposal_decisions',\n"
                                         '  '
                                         "'category_knowledge_entries','category_knowledge_current','parameter_versions','parameter_current',\n"
                                         '  '
                                         "'evidence_links','promotion_proofs','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','project_risk_followups','project_risk_followup_currents'] "
                                         'END LOOP\n'
                                         '  FOR payload IN EXECUTE CASE WHEN '
                                         "name=ANY(ARRAY['audit_entries','outbox_events','request_keys'])\n"
                                         "   THEN format('SELECT to_jsonb(x) FROM public.%I x JOIN "
                                         'public.action_receipts r ON r.id=x.receipt_id AND '
                                         'r.tenant_id=x.tenant_id WHERE x.tenant_id=$1 AND '
                                         "r.category_id=$2',name)\n"
                                         "   ELSE format('SELECT to_jsonb(x) FROM public.%I x WHERE "
                                         'tenant_id=$1 AND category_id=$2 AND ($3 IS NULL OR '
                                         "%I=ANY($3))',name,\n"
                                         "    CASE name WHEN 'category_knowledge_current' THEN "
                                         "'lineage_id'\n"
                                         "     WHEN 'parameter_current' THEN 'parameter_id' ELSE 'id' "
                                         'END)\n'
                                         '   END USING t,c,identities LOOP\n'
                                         "   IF (payload->>'receipt_id')::uuid=ANY(controls) OR\n"
                                         "    (name='action_receipts' AND payload->>'operation' LIKE "
                                         "'evidence.lifecycle.%') THEN CONTINUE; END IF;\n"
                                         '   table_name=name;\n'
                                         "   node_id=CASE name WHEN 'category_knowledge_current' THEN "
                                         "(payload->>'lineage_id')::uuid\n"
                                         "    WHEN 'parameter_current' THEN "
                                         "(payload->>'parameter_id')::uuid ELSE (payload->>'id')::uuid "
                                         'END;\n'
                                         '   IF identities IS NULL THEN '
                                         'links=public.m3_lifecycle_row_links(t,c,name,payload);\n'
                                         '   ELSE '
                                         'links=public.m3_lifecycle_source_links(t,c,name,payload); '
                                         'END IF;\n'
                                         "   -- Preserve predecessor's conservative legacy graph; "
                                         'M3-only nodes use\n'
                                         '   -- strictly typed/relational links. Root lookup never '
                                         'uses free-text UUIDs.\n'
                                         '   IF identities IS NULL AND '
                                         "name<>ALL(ARRAY['native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','project_risk_followups','project_risk_followup_currents','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals']) "
                                         'THEN\n'
                                         '    links=links || '
                                         'public.kernel_lifecycle_links(name,payload);\n'
                                         '   END IF;\n'
                                         '   RETURN NEXT;\n'
                                         '  END LOOP;\n'
                                         ' END LOOP;\n'
                                         'END;\n'
                                         '$function$\n',
 'm3_lifecycle_source_links(uuid,uuid,text,jsonb)': 'CREATE OR REPLACE FUNCTION '
                                                    'public.m3_lifecycle_source_links(t uuid, c uuid, '
                                                    'table_name text, payload jsonb)\n'
                                                    ' RETURNS uuid[]\n'
                                                    ' LANGUAGE plpgsql\n'
                                                    ' STABLE SECURITY DEFINER\n'
                                                    " SET search_path TO 'pg_catalog', 'public', "
                                                    "'pg_temp'\n"
                                                    'AS $function$\n'
                                                    "DECLARE links uuid[]='{}'; extra uuid[]; key "
                                                    'text; keys text[]; item jsonb; container jsonb;\n'
                                                    ' target_kind text; referenced_target uuid; '
                                                    'referenced_version integer;\n'
                                                    'BEGIN\n'
                                                    " IF table_name='agent_runs' THEN RETURN "
                                                    'public.kernel_lifecycle_links(table_name,payload); '
                                                    'END IF;\n'
                                                    ' -- Only actual top-level relation columns '
                                                    'establish raw UUID edges. Arbitrary\n'
                                                    ' -- content dictionaries are not relational rows, '
                                                    'even if an extra key happens\n'
                                                    ' -- to be named source_id or item_id.\n'
                                                    ' keys=CASE table_name\n'
                                                    "  WHEN 'artifact_versions' THEN "
                                                    "ARRAY['original_id']\n"
                                                    "  WHEN 'claims' THEN "
                                                    "ARRAY['artifact_id','snapshot_id']\n"
                                                    "  WHEN 'definition_revisions' THEN "
                                                    "ARRAY['derived_from_definition_id','parent_definition_id',\n"
                                                    "   'source_proposal_id','source_submission_id']\n"
                                                    "  WHEN 'definition_sources' THEN "
                                                    "ARRAY['artifact_id']\n"
                                                    "  WHEN 'definition_specs' THEN ARRAY[]::text[]\n"
                                                    "  WHEN 'proposals' THEN "
                                                    "ARRAY['baseline_definition_id','current_submission_id']\n"
                                                    "  WHEN 'proposal_items' THEN ARRAY[]::text[]\n"
                                                    "  WHEN 'proposal_item_versions' THEN "
                                                    'ARRAY[]::text[]\n'
                                                    "  WHEN 'proposal_revisions' THEN "
                                                    "ARRAY['proposal_id']\n"
                                                    "  WHEN 'proposal_sources' THEN "
                                                    "ARRAY['source_id']\n"
                                                    "  WHEN 'proposal_submissions' THEN "
                                                    'ARRAY[]::text[]\n'
                                                    "  WHEN 'proposal_decisions' THEN "
                                                    "ARRAY['submission_id']\n"
                                                    "  WHEN 'project_open_items' THEN "
                                                    "ARRAY['source_question_id','source_spec_item_id','g0_decision_id']\n"
                                                    "  WHEN 'category_knowledge_current' THEN "
                                                    "ARRAY['current_entry_id']\n"
                                                    "  WHEN 'promotion_proofs' THEN "
                                                    "ARRAY['knowledge_entry_id','source_proposal_id']\n"
                                                    "  WHEN 'evidence_links' THEN "
                                                    "ARRAY['evidence_id']\n"
                                                    "  WHEN 'claim_withdrawals' THEN "
                                                    "ARRAY['claim_id']\n"
                                                    "  WHEN 'manufacturing_baseline_publications' THEN "
                                                    "ARRAY['baseline_id','process_id','previous_id']\n"
                                                    "  WHEN 'manufacturing_publication_currents' THEN "
                                                    "ARRAY['version_id']\n"
                                                    "  WHEN 'manufacturing_publication_documents' THEN "
                                                    "ARRAY['document_id','process_id']\n"
                                                    "  WHEN 'native_pilot_runs' THEN "
                                                    "ARRAY['build_id','lot_id','actual_configuration_id','engineering_configuration_id','process_id','publication_id']\n"
                                                    "  WHEN 'native_pilot_currents' THEN "
                                                    "ARRAY['pilot_id','latest_observation_id']\n"
                                                    "  WHEN 'native_pilot_observations' THEN "
                                                    "ARRAY['pilot_id','previous_observation_id']\n"
                                                    "  WHEN 'release_packages' THEN "
                                                    "ARRAY['previous_id']\n"
                                                    "  WHEN 'release_package_currents' THEN "
                                                    "ARRAY['version_id']\n"
                                                    "  WHEN 'release_decisions' THEN "
                                                    "ARRAY['package_id']\n"
                                                    "  WHEN 'release_policy_facts' THEN "
                                                    "ARRAY['previous_id']\n"
                                                    "  WHEN 'release_policy_currents' THEN "
                                                    "ARRAY['fact_id']\n"
                                                    "  WHEN 'external_handoff_authorizations' THEN "
                                                    "ARRAY['package_id','engineering_decision_id','manufacturing_decision_id']\n"
                                                    "  WHEN 'external_delivery_intents' THEN "
                                                    "ARRAY['handoff_id']\n"
                                                    "  WHEN 'external_receipts' THEN "
                                                    "ARRAY['handoff_id','intent_id','previous_receipt_id','reconciles_id']\n"
                                                    "  WHEN 'external_handoff_currents' THEN "
                                                    "ARRAY['handoff_id','intent_id','latest_receipt_id']\n"
                                                    "  WHEN 'release_exception_decisions' THEN "
                                                    "ARRAY['basis_package_id','policy_fact_id','previous_id']\n"
                                                    "  WHEN 'release_exception_currents' THEN "
                                                    "ARRAY['basis_package_id','policy_fact_id','decision_id']\n"
                                                    "  WHEN 'work_commitment_reviews' THEN "
                                                    "ARRAY['commitment_id','task_version_id','submission_id','previous_id']\n"
                                                    "  WHEN 'work_commitment_review_currents' THEN "
                                                    "ARRAY['version_id']\n"
                                                    "  WHEN 'external_wait_versions' THEN "
                                                    "ARRAY['previous_id']\n"
                                                    "  WHEN 'external_wait_currents' THEN "
                                                    "ARRAY['version_id']\n"
                                                    "  WHEN 'project_risk_followups' THEN "
                                                    "ARRAY['previous_id','risk_id','g0_decision_id']\n"
                                                    "  WHEN 'project_risk_followup_currents' THEN "
                                                    "ARRAY['version_id']\n"
                                                    "  WHEN 'work_task_versions' THEN "
                                                    "ARRAY['previous_id']\n"
                                                    "  WHEN 'work_task_currents' THEN "
                                                    "ARRAY['version_id']\n"
                                                    "  WHEN 'work_commitment_versions' THEN "
                                                    "ARRAY['replaces_id']\n"
                                                    "  WHEN 'work_commitment_currents' THEN "
                                                    "ARRAY['version_id']\n"
                                                    "  WHEN 'project_status_updates' THEN "
                                                    'ARRAY[]::text[]\n'
                                                    '  ELSE ARRAY[]::text[] END;\n'
                                                    ' FOREACH key IN ARRAY keys LOOP\n'
                                                    '  IF payload->>key IS NOT NULL THEN '
                                                    'links=array_append(links,(payload->>key)::uuid); '
                                                    'END IF;\n'
                                                    ' END LOOP;\n'
                                                    " -- Publication's exact saved read set is a "
                                                    'validated Artifact relationship.\n'
                                                    ' -- Do not scan its declaration, body, reason or '
                                                    'arbitrary JSON UUID values.\n'
                                                    ' IF table_name IN '
                                                    "('manufacturing_baseline_publications','native_pilot_runs','native_pilot_observations','release_packages','release_decisions','release_policy_facts','external_handoff_authorizations','external_receipts','release_exception_decisions') "
                                                    'THEN\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload->'required_source_read_set','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'artifact_id' IS NOT NULL THEN\n"
                                                    '    '
                                                    "links=array_append(links,(item->>'artifact_id')::uuid);\n"
                                                    '   END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    ' IF table_name IN '
                                                    "('native_pilot_runs','native_pilot_observations') "
                                                    'THEN\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{material_snapshot,statistics,samples}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{material_snapshot,statistics,issues}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  '
                                                    "item=payload#>'{material_snapshot,statistics,resource,fact}';\n"
                                                    "  IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); "
                                                    'END IF;\n'
                                                    ' END IF;\n'
                                                    " IF table_name='release_packages' THEN\n"
                                                    '  -- FixedObject.ref is a closed, server-resolved '
                                                    'version reference, not arbitrary body UUID text.\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{body,objects}','[]')) "
                                                    'LOOP\n'
                                                    "   container=item->'ref';\n"
                                                    '   IF '
                                                    "container->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','manufacturing_publication','test_run','pilot_run','issue','change','exception','artifact','work_instruction','control_plan','build_lot','line'])\n"
                                                    "    AND container->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(container->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    ' IF table_name IN '
                                                    "('external_handoff_authorizations','external_delivery_intents') "
                                                    'THEN\n'
                                                    '  -- Only closed, owner-verified mapping and '
                                                    'manifest references are source edges.\n'
                                                    '  container=CASE WHEN '
                                                    "table_name='external_handoff_authorizations' THEN "
                                                    "payload#>'{body,declaration}' ELSE "
                                                    "payload->'body' END;\n"
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(container->'mappings','[]')) "
                                                    'LOOP\n'
                                                    '   IF '
                                                    "item->'ref'->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','part','bom_revision','artifact','work_instruction','control_plan'])\n"
                                                    "    AND item->'ref'->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->'ref'->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(container->'manifest','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->'artifact'->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->'artifact'->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    " IF table_name='release_policy_facts' THEN\n"
                                                    '  -- These are Closed DTO configuration '
                                                    'references fixed by the policy owner.\n'
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['definition','engineering_configuration','manufacturing_configuration'] "
                                                    'LOOP\n'
                                                    '   '
                                                    "container=payload#>ARRAY['material','subject_config',key];\n"
                                                    "   IF container->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(container->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    ' -- These stored fields are validated Reference '
                                                    'containers. Do not feed the\n'
                                                    ' -- whole row or arbitrary content into the '
                                                    'canonical Reference parser.\n'
                                                    ' IF '
                                                    "table_name=ANY(ARRAY['proposals','proposal_item_versions','proposal_submissions',\n"
                                                    '  '
                                                    "'category_knowledge_entries','definition_specs']) "
                                                    'THEN\n'
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['source_refs','direct_source_refs','context_refs','baseline_claim_refs'] "
                                                    'LOOP\n'
                                                    '   links=links || '
                                                    'public.m3_lifecycle_typed_links(t,c,payload->key);\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    ' -- Match ItemInput.content_schema and '
                                                    'category_service._references: only\n'
                                                    ' -- commercial_target, voice, and competitor have '
                                                    'nested source contracts.\n'
                                                    " IF table_name='proposal_item_versions' AND "
                                                    "payload->>'kind'='commercial_target' THEN\n"
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['target_price','cost','volume'] LOOP\n"
                                                    '   links=links || '
                                                    "public.m3_lifecycle_typed_links(t,c,payload->'content'->key->'source');\n"
                                                    '  END LOOP;\n'
                                                    " ELSIF table_name='category_knowledge_entries' "
                                                    "AND payload->>'kind'='voice' THEN\n"
                                                    '  links=links || '
                                                    "public.m3_lifecycle_typed_links(t,c,payload->'content'->'representative_refs');\n"
                                                    " ELSIF table_name='category_knowledge_entries' "
                                                    "AND payload->>'kind'='competitor' THEN\n"
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['metrics','features','prices'] LOOP\n"
                                                    '   FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload->'content'->key,'[]')) "
                                                    'LOOP\n'
                                                    '    links=links || '
                                                    "public.m3_lifecycle_typed_links(t,c,item->'source_ref');\n"
                                                    '   END LOOP;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    " IF table_name='proposal_submissions' THEN\n"
                                                    "  container=payload->'frozen_document';\n"
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['source_refs','direct_source_refs','context_refs','baseline_claim_refs'] "
                                                    'LOOP\n'
                                                    '   links=links || '
                                                    'public.m3_lifecycle_typed_links(t,c,container->key);\n'
                                                    '  END LOOP;\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(container->'items','[]')) "
                                                    'LOOP\n'
                                                    '   links=links || '
                                                    "public.m3_lifecycle_source_links(t,c,'proposal_item_versions',item-ARRAY['item_id','proposal_id']);\n"
                                                    '   -- The frozen read projection records actual '
                                                    'EvidenceLink provenance here.\n'
                                                    '   links=links || '
                                                    "public.m3_lifecycle_typed_links(t,c,item->'evidence_links');\n"
                                                    '  END LOOP;\n'
                                                    " ELSIF table_name='promotion_proofs' THEN\n"
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload->'source_item_refs','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'item_id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'item_id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    ' -- Exact persisted EvidenceLink targets '
                                                    'supplement these immutable versions.\n'
                                                    ' -- Reverted links and withdrawn Claims still '
                                                    'retain the original historical\n'
                                                    ' -- dependency; lifecycle cleanup must not erase '
                                                    'their audit source.\n'
                                                    " IF table_name='proposal_item_versions' AND "
                                                    "payload->>'item_id' IS NOT NULL THEN\n"
                                                    "  target_kind='proposal_item'; "
                                                    "referenced_target=(payload->>'item_id')::uuid;\n"
                                                    '  '
                                                    "referenced_version=(payload->>'version')::integer;\n"
                                                    " ELSIF table_name='category_knowledge_entries' "
                                                    "AND payload->>'id' IS NOT NULL THEN\n"
                                                    "  target_kind='knowledge_entry'; "
                                                    "referenced_target=(payload->>'id')::uuid;\n"
                                                    '  '
                                                    "referenced_version=(payload->>'version')::integer;\n"
                                                    " ELSIF table_name='definition_specs' AND "
                                                    "payload->>'id' IS NOT NULL THEN\n"
                                                    "  target_kind='definition_spec'; "
                                                    "referenced_target=(payload->>'id')::uuid;\n"
                                                    '  SELECT revision INTO referenced_version FROM '
                                                    'public.definition_revisions\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "id=(payload->>'definition_id')::uuid;\n"
                                                    ' END IF;\n'
                                                    ' IF referenced_target IS NOT NULL AND '
                                                    'referenced_version IS NOT NULL THEN\n'
                                                    '  SELECT '
                                                    "coalesce(array_agg(link.evidence_id),'{}') INTO "
                                                    'extra FROM public.evidence_links link\n'
                                                    '   WHERE link.tenant_id=t AND link.category_id=c '
                                                    'AND link.target_type=target_kind\n'
                                                    '    AND link.target_id=referenced_target AND '
                                                    'link.target_version=referenced_version;\n'
                                                    '  links=links || extra;\n'
                                                    ' END IF;\n'
                                                    ' -- Child source rows point to their parent, '
                                                    'whereas dependency traversal needs\n'
                                                    " -- the parent's fixed source children as well. "
                                                    'Keep the actual relational edge.\n'
                                                    " IF table_name='definition_revisions' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO extra "
                                                    'FROM (\n'
                                                    '   SELECT id FROM public.definition_sources WHERE '
                                                    'tenant_id=t AND category_id=c\n'
                                                    "    AND definition_id=(payload->>'id')::uuid\n"
                                                    '   UNION ALL SELECT id FROM '
                                                    'public.definition_specs WHERE tenant_id=t AND '
                                                    'category_id=c\n'
                                                    "    AND definition_id=(payload->>'id')::uuid\n"
                                                    '  ) children;\n'
                                                    '  links=links || extra;\n'
                                                    " ELSIF table_name='proposals' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO extra "
                                                    'FROM public.proposal_item_versions\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "proposal_id=(payload->>'id')::uuid;\n"
                                                    '  links=links || extra;\n'
                                                    " ELSIF table_name='proposal_items' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO extra "
                                                    'FROM public.proposal_item_versions\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "item_id=(payload->>'id')::uuid;\n"
                                                    '  links=links || extra;\n'
                                                    " ELSIF table_name='product_target_segments' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO extra "
                                                    'FROM public.category_knowledge_entries\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "lineage_id=(payload->>'segment_lineage_id')::uuid\n"
                                                    '    AND '
                                                    "version=(payload->>'segment_version')::integer;\n"
                                                    '  links=links || extra;\n'
                                                    " ELSIF table_name='parameter_current' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO extra "
                                                    'FROM public.parameter_versions\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "parameter_id=(payload->>'parameter_id')::uuid\n"
                                                    '    AND '
                                                    "version=(payload->>'current_version')::integer;\n"
                                                    '  links=links || extra;\n'
                                                    ' END IF;\n'
                                                    '\n'
                                                    ' IF table_name IN '
                                                    "('work_task_versions','work_commitment_versions','project_status_updates') "
                                                    'THEN\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload->'reads','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'artifact_id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'artifact_id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    "  IF table_name='work_task_versions' AND "
                                                    "payload#>>'{body,plan_task,id}' IS NOT NULL THEN\n"
                                                    '   '
                                                    "links=array_append(links,(payload#>>'{body,plan_task,id}')::uuid);\n"
                                                    '  END IF;\n'
                                                    "  IF table_name='work_commitment_versions' THEN\n"
                                                    "   SELECT coalesce(array_agg(id),'{}') INTO extra "
                                                    'FROM public.work_task_versions\n'
                                                    '    WHERE tenant_id=t AND category_id=c AND '
                                                    "task_id=(payload->>'task_id')::uuid AND "
                                                    "revision=(payload->>'task_revision')::integer;\n"
                                                    '   links=links||extra;\n'
                                                    "  ELSIF table_name='project_status_updates' THEN\n"
                                                    '   FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload->'task_refs','[]')) "
                                                    'LOOP\n'
                                                    "    SELECT coalesce(array_agg(id),'{}') INTO "
                                                    'extra FROM public.work_task_versions\n'
                                                    '     WHERE tenant_id=t AND category_id=c AND '
                                                    "task_id=(item->>'id')::uuid AND "
                                                    "revision=(item->>'revision')::integer;\n"
                                                    '    links=links||extra;\n'
                                                    '   END LOOP;\n'
                                                    '  END IF;\n'
                                                    ' END IF;\n'
                                                    '\n'
                                                    " IF table_name='work_commitment_reviews' THEN\n"
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload->'reads','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'artifact_id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'artifact_id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    '\n'
                                                    " IF table_name='external_wait_versions' THEN\n"
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['milestone','build','calendar'] LOOP\n"
                                                    "   container=payload#>ARRAY['body',key];\n"
                                                    "   IF container->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(container->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    "  container=payload#>'{body,replaces}';\n"
                                                    "  IF container->>'id' IS NOT NULL THEN\n"
                                                    "   SELECT coalesce(array_agg(id),'{}') INTO extra "
                                                    'FROM public.external_wait_versions\n'
                                                    '    WHERE tenant_id=t AND category_id=c AND '
                                                    "wait_id=(container->>'id')::uuid AND "
                                                    "revision=(container->>'revision')::integer;\n"
                                                    '   links=links||extra;\n'
                                                    '  END IF;\n'
                                                    ' END IF;\n'
                                                    " IF table_name='project_risk_followups' THEN\n"
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    ' RETURN links;\n'
                                                    'END;\n'
                                                    '$function$\n'}

KNOWLEDGE_FUNCTIONS = {'reject_knowledge_mutation()': 'CREATE OR REPLACE FUNCTION public.reject_knowledge_mutation()\n'
                                ' RETURNS trigger\n'
                                ' LANGUAGE plpgsql\n'
                                ' SECURITY DEFINER\n'
                                " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                'AS $function$\n'
                                "BEGIN RAISE EXCEPTION 'Knowledge facts and assessment history are "
                                "immutable' USING ERRCODE='23514'; END;\n"
                                '$function$\n',
 'protect_knowledge_candidate_current()': 'CREATE OR REPLACE FUNCTION '
                                          'public.protect_knowledge_candidate_current()\n'
                                          ' RETURNS trigger\n'
                                          ' LANGUAGE plpgsql\n'
                                          ' SECURITY DEFINER\n'
                                          " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                          'AS $function$\n'
                                          '\n'
                                          'BEGIN\n'
                                          " IF TG_OP='INSERT' AND NEW.revision=1 THEN RETURN NEW;\n"
                                          " ELSIF TG_OP='UPDATE' AND "
                                          "(to_jsonb(NEW)-ARRAY['version_id','revision']) IS NOT "
                                          'DISTINCT FROM '
                                          "(to_jsonb(OLD)-ARRAY['version_id','revision'])\n"
                                          '  AND NEW.revision=OLD.revision+1 AND EXISTS(SELECT 1 FROM '
                                          'public.knowledge_candidate_versions v WHERE '
                                          'v.tenant_id=NEW.tenant_id\n'
                                          '   AND v.id=NEW.version_id AND v.revision=NEW.revision AND '
                                          'v.previous_id=OLD.version_id AND '
                                          'v.previous_revision=OLD.revision) THEN RETURN NEW;\n'
                                          ' END IF;\n'
                                          " RAISE EXCEPTION 'knowledge_candidate_currents requires "
                                          "exact immutable-scope single-step CAS' USING "
                                          "ERRCODE='23514';\n"
                                          'END;\n'
                                          '$function$\n',
 'require_knowledge_candidate_current()': 'CREATE OR REPLACE FUNCTION '
                                          'public.require_knowledge_candidate_current()\n'
                                          ' RETURNS trigger\n'
                                          ' LANGUAGE plpgsql\n'
                                          ' SECURITY DEFINER\n'
                                          " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                          'AS $function$\n'
                                          '\n'
                                          'DECLARE cur public.knowledge_candidate_currents; fixed '
                                          'public.knowledge_candidate_versions; cx xid; vx xid;\n'
                                          'BEGIN\n'
                                          ' SELECT * INTO STRICT cur FROM '
                                          'public.knowledge_candidate_currents WHERE '
                                          'tenant_id=NEW.tenant_id AND id=NEW.id;\n'
                                          ' SELECT xmin INTO cx FROM '
                                          'public.knowledge_candidate_currents WHERE '
                                          'tenant_id=NEW.tenant_id AND id=NEW.id;\n'
                                          ' SELECT * INTO STRICT fixed FROM '
                                          'public.knowledge_candidate_versions WHERE '
                                          'tenant_id=NEW.tenant_id AND id=cur.version_id;\n'
                                          ' SELECT xmin INTO vx FROM '
                                          'public.knowledge_candidate_versions WHERE '
                                          'tenant_id=NEW.tenant_id AND id=cur.version_id;\n'
                                          ' IF vx IS DISTINCT FROM cx\n'
                                          '  OR '
                                          'ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.candidate_id,cur.version_id,cur.revision)\n'
                                          '   IS DISTINCT FROM '
                                          'ROW(fixed.category_id,fixed.product_id,fixed.project_id,fixed.owner_id,fixed.visibility,fixed.candidate_id,fixed.id,fixed.revision) '
                                          'THEN\n'
                                          "  RAISE EXCEPTION 'Knowledge Current requires its exact "
                                          "same-transaction scoped version' USING ERRCODE='23514'; END "
                                          'IF;\n'
                                          ' RETURN NULL;\n'
                                          'END;\n'
                                          '$function$\n',
 'protect_knowledge_rule_current()': 'CREATE OR REPLACE FUNCTION '
                                     'public.protect_knowledge_rule_current()\n'
                                     ' RETURNS trigger\n'
                                     ' LANGUAGE plpgsql\n'
                                     ' SECURITY DEFINER\n'
                                     " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                     'AS $function$\n'
                                     '\n'
                                     'BEGIN\n'
                                     " IF TG_OP='INSERT' AND NEW.revision=1 THEN RETURN NEW;\n"
                                     " ELSIF TG_OP='UPDATE' AND "
                                     "(to_jsonb(NEW)-ARRAY['version_id','revision']) IS NOT DISTINCT "
                                     "FROM (to_jsonb(OLD)-ARRAY['version_id','revision'])\n"
                                     '  AND NEW.revision=OLD.revision+1 AND EXISTS(SELECT 1 FROM '
                                     'public.knowledge_rule_versions v WHERE '
                                     'v.tenant_id=NEW.tenant_id\n'
                                     '   AND v.id=NEW.version_id AND v.revision=NEW.revision AND '
                                     'v.previous_id=OLD.version_id AND '
                                     'v.previous_revision=OLD.revision) THEN RETURN NEW;\n'
                                     ' END IF;\n'
                                     " RAISE EXCEPTION 'knowledge_rule_currents requires exact "
                                     "immutable-scope single-step CAS' USING ERRCODE='23514';\n"
                                     'END;\n'
                                     '$function$\n',
 'require_knowledge_rule_current()': 'CREATE OR REPLACE FUNCTION '
                                     'public.require_knowledge_rule_current()\n'
                                     ' RETURNS trigger\n'
                                     ' LANGUAGE plpgsql\n'
                                     ' SECURITY DEFINER\n'
                                     " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                     'AS $function$\n'
                                     '\n'
                                     'DECLARE cur public.knowledge_rule_currents; fixed '
                                     'public.knowledge_rule_versions; cx xid; vx xid;\n'
                                     'BEGIN\n'
                                     ' SELECT * INTO STRICT cur FROM public.knowledge_rule_currents '
                                     'WHERE tenant_id=NEW.tenant_id AND id=NEW.id;\n'
                                     ' SELECT xmin INTO cx FROM public.knowledge_rule_currents WHERE '
                                     'tenant_id=NEW.tenant_id AND id=NEW.id;\n'
                                     ' SELECT * INTO STRICT fixed FROM public.knowledge_rule_versions '
                                     'WHERE tenant_id=NEW.tenant_id AND id=cur.version_id;\n'
                                     ' SELECT xmin INTO vx FROM public.knowledge_rule_versions WHERE '
                                     'tenant_id=NEW.tenant_id AND id=cur.version_id;\n'
                                     ' IF vx IS DISTINCT FROM cx\n'
                                     '  OR '
                                     'ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.rule_id,cur.version_id,cur.revision)\n'
                                     '   IS DISTINCT FROM '
                                     'ROW(fixed.category_id,fixed.product_id,fixed.project_id,fixed.owner_id,fixed.visibility,fixed.rule_id,fixed.id,fixed.revision) '
                                     'THEN\n'
                                     "  RAISE EXCEPTION 'Knowledge Current requires its exact "
                                     "same-transaction scoped version' USING ERRCODE='23514'; END IF;\n"
                                     ' RETURN NULL;\n'
                                     'END;\n'
                                     '$function$\n',
 'assert_knowledge_members(uuid,uuid,text)': 'CREATE OR REPLACE FUNCTION '
                                             'public.assert_knowledge_members(t uuid, target uuid, '
                                             'kind text)\n'
                                             ' RETURNS void\n'
                                             ' LANGUAGE plpgsql\n'
                                             ' SECURITY DEFINER\n'
                                             " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                             'AS $function$\n'
                                             '\n'
                                             'DECLARE v record; receipt public.action_receipts; proof '
                                             'public.confirmations;\n'
                                             ' expected jsonb; event_name text;\n'
                                             'BEGIN\n'
                                             " IF kind='knowledge_candidate' THEN\n"
                                             '  SELECT * INTO STRICT v FROM '
                                             'public.knowledge_candidate_versions WHERE tenant_id=t '
                                             'AND id=target;\n'
                                             '  '
                                             "expected=jsonb_build_object('id',v.id,'revision',v.revision,'status','draft','candidate_id',v.candidate_id,'project_id',v.project_id);\n"
                                             "  event_name='knowledge.candidate_created';\n"
                                             " ELSIF kind='design_rule' THEN\n"
                                             '  SELECT * INTO STRICT v FROM '
                                             'public.knowledge_rule_versions WHERE tenant_id=t AND '
                                             'id=target;\n'
                                             '  '
                                             "expected=jsonb_build_object('id',v.id,'revision',v.revision,'status','published','rule_id',v.rule_id,'project_id',v.project_id,'assessment_id',v.assessment_id);\n"
                                             "  event_name='knowledge.rule_published';\n"
                                             " ELSE RAISE EXCEPTION 'Unknown knowledge subject' USING "
                                             "ERRCODE='23514'; END IF;\n"
                                             ' SELECT * INTO STRICT receipt FROM '
                                             'public.action_receipts WHERE tenant_id=t AND '
                                             'id=v.receipt_id;\n'
                                             ' IF '
                                             'ROW(receipt.category_id,receipt.product_id,receipt.command_id,receipt.confirmation_id,receipt.actor_id,receipt.requester_id,receipt.operation,receipt.subject_type,receipt.subject_id,receipt.subject_revision,receipt.visibility,receipt.request_digest,receipt.intent_digest)\n'
                                             '  IS DISTINCT FROM '
                                             'ROW(v.category_id,v.product_id,v.command_id,v.confirmation_id,v.actor_id,v.requester_id,v.operation,kind::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)\n'
                                             '  OR receipt.result IS DISTINCT FROM expected OR '
                                             'receipt.created_at<v.created_at\n'
                                             '  OR (SELECT count(*) FROM public.action_receipts x '
                                             'WHERE x.tenant_id=t AND x.operation=v.operation AND '
                                             'x.subject_type=kind AND x.subject_id=v.id AND '
                                             'x.subject_revision=v.revision)<>1\n'
                                             '  OR (SELECT count(*) FROM public.audit_entries x WHERE '
                                             'x.tenant_id=t AND x.receipt_id=v.receipt_id)<>1\n'
                                             '  OR NOT EXISTS(SELECT 1 FROM public.audit_entries x '
                                             'WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND '
                                             'x.category_id=v.category_id AND x.actor_id=v.actor_id '
                                             'AND x.operation=v.operation AND '
                                             'x.created_at>=v.created_at)\n'
                                             '  OR (SELECT count(*) FROM public.outbox_events x WHERE '
                                             'x.tenant_id=t AND x.receipt_id=v.receipt_id)<>1\n'
                                             '  OR NOT EXISTS(SELECT 1 FROM public.outbox_events x '
                                             'WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND '
                                             'x.category_id=v.category_id AND x.actor_id=v.actor_id '
                                             'AND x.type=event_name AND x.subject_id=v.id AND '
                                             'x.subject_revision=v.revision AND x.schema_version=1 AND '
                                             'x.correlation_id=coalesce(receipt.agent_run_id,receipt.run_id,v.command_id) '
                                             'AND x.created_at>=v.created_at)\n'
                                             "  OR v.command->>'original_key_sha256' IS NULL OR "
                                             "v.command->>'original_key_sha256' !~ '^[a-f0-9]{64}$'\n"
                                             "  OR v.command->'envelope' ? 'idempotency_key'\n"
                                             "  OR v.command->'envelope'->'payload' ? "
                                             "'confirmation_token' OR v.command->'envelope'->'payload' "
                                             "? 'approval_token'\n"
                                             '  OR NOT EXISTS(SELECT 1 FROM public.request_keys x '
                                             'WHERE x.tenant_id=t AND x.category_id=v.category_id AND '
                                             'x.receipt_id=v.receipt_id AND x.actor_id=v.actor_id AND '
                                             'x.digest=v.request_digest AND '
                                             "encode(sha256(convert_to(x.key,'UTF8')),'hex')=v.command->>'original_key_sha256') "
                                             'THEN\n'
                                             "  RAISE EXCEPTION 'Knowledge original receipt audit "
                                             "event or request mismatch' USING ERRCODE='23514'; END "
                                             'IF;\n'
                                             " IF kind='design_rule' THEN\n"
                                             '  SELECT * INTO STRICT proof FROM public.confirmations '
                                             'WHERE tenant_id=t AND id=v.confirmation_id;\n'
                                             '  IF proof.consumed IS DISTINCT FROM true\n'
                                             '   OR '
                                             'ROW(proof.category_id,proof.product_id,proof.actor_id,proof.operation,proof.subject_type,proof.subject_id,proof.revision)\n'
                                             '    IS DISTINCT FROM '
                                             "ROW(v.category_id,v.product_id,v.actor_id,v.operation,'product'::varchar,v.product_id,(v.command->'envelope'->>'expected_revision')::integer)\n"
                                             '   OR proof.snapshot IS DISTINCT FROM '
                                             "v.command->'review' OR proof.created_at>v.created_at\n"
                                             '   OR (proof.expires_at IS NOT NULL AND '
                                             '(v.created_at>=proof.expires_at OR '
                                             'receipt.created_at>=proof.expires_at))\n'
                                             '   OR receipt.run_id IS NOT NULL OR receipt.agent_run_id '
                                             'IS NOT NULL\n'
                                             '   OR v.actor_id<>v.requester_id THEN\n'
                                             "   RAISE EXCEPTION 'Knowledge rule requires the actual "
                                             "named consumed T2 proof' USING ERRCODE='23514'; END IF;\n"
                                             ' END IF;\n'
                                             'END;\n'
                                             '$function$\n',
 'assert_knowledge_common(uuid,uuid,text)': 'CREATE OR REPLACE FUNCTION '
                                            'public.assert_knowledge_common(t uuid, target uuid, kind '
                                            'text)\n'
                                            ' RETURNS void\n'
                                            ' LANGUAGE plpgsql\n'
                                            ' SECURITY DEFINER\n'
                                            " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                            'AS $function$\n'
                                            '\n'
                                            'DECLARE v record; envelope jsonb; vx xid; rx xid; px xid; '
                                            'ref jsonb; basis jsonb;\n'
                                            'BEGIN\n'
                                            " IF kind='knowledge_candidate' THEN\n"
                                            '  SELECT x.*,x.xmin AS tx INTO STRICT v FROM '
                                            'public.knowledge_candidate_versions x WHERE x.tenant_id=t '
                                            'AND x.id=target;\n'
                                            " ELSIF kind='design_rule' THEN\n"
                                            '  SELECT x.*,x.xmin AS tx INTO STRICT v FROM '
                                            'public.knowledge_rule_versions x WHERE x.tenant_id=t AND '
                                            'x.id=target;\n'
                                            " ELSE RAISE EXCEPTION 'Unknown knowledge subject' USING "
                                            "ERRCODE='23514'; END IF;\n"
                                            ' vx=v.tx;\n'
                                            ' SELECT xmin INTO rx FROM public.action_receipts WHERE '
                                            'tenant_id=t AND id=v.receipt_id;\n'
                                            ' PERFORM public.assert_knowledge_members(t,target,kind);\n'
                                            " envelope=v.command->'envelope';\n"
                                            ' IF v.actor_id IS DISTINCT FROM public.scope_actor() OR '
                                            'v.requester_id IS DISTINCT FROM public.scope_requester()\n'
                                            '  OR v.writer_id<>v.actor_id OR vx IS DISTINCT FROM rx OR '
                                            'NOT public.category_access(t,v.category_id,true)\n'
                                            '  OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE '
                                            'h.tenant_id=t AND h.id=v.actor_id AND h.active)\n'
                                            '  OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE '
                                            "h.tenant_id=t AND h.id=v.requester_id AND h.kind='human' "
                                            'AND h.active)\n'
                                            "  OR envelope->>'operation' IS DISTINCT FROM v.operation "
                                            "OR envelope->>'command_id' IS DISTINCT FROM "
                                            'v.command_id::text\n'
                                            "  OR envelope->>'category_id' IS DISTINCT FROM "
                                            "v.category_id::text OR envelope->>'product_id' IS "
                                            'DISTINCT FROM v.product_id::text\n'
                                            "  OR envelope->'payload'->>'project_id' IS DISTINCT FROM "
                                            'v.project_id::text\n'
                                            "  OR v.command->'review'->'declaration' IS DISTINCT FROM "
                                            "envelope->'payload'\n"
                                            "  OR v.command->'review'->>'operation' IS DISTINCT FROM "
                                            'v.operation\n'
                                            "  OR v.command->'review'->'sources' IS DISTINCT FROM "
                                            'v.sources\n'
                                            "  OR v.command->'review'->'source_basis' IS DISTINCT FROM "
                                            'v.source_basis\n'
                                            '  OR v.body IS DISTINCT FROM '
                                            "v.command->'review'->'after'\n"
                                            '  OR (v.product_id IS NULL AND NOT EXISTS(SELECT 1 FROM '
                                            'public.categories c WHERE c.tenant_id=t AND '
                                            'c.id=v.category_id AND '
                                            "c.revision::text=envelope->>'expected_revision'))\n"
                                            '  OR (v.product_id IS NOT NULL AND NOT EXISTS(SELECT 1 '
                                            'FROM public.products p WHERE p.tenant_id=t AND '
                                            'p.category_id=v.category_id AND p.id=v.product_id AND '
                                            "p.revision::text=envelope->>'expected_revision'))\n"
                                            '  OR (v.project_id IS NOT NULL AND NOT EXISTS(SELECT 1 '
                                            'FROM public.projects p WHERE p.tenant_id=t AND '
                                            'p.category_id=v.category_id AND p.product_id=v.product_id '
                                            'AND p.id=v.project_id))\n'
                                            "  OR NOT COALESCE(envelope->'source_read_set' @> "
                                            'v.reads,false) OR NOT COALESCE(v.reads @> '
                                            "(envelope->'source_read_set'),false)\n"
                                            '  OR '
                                            "jsonb_array_length(envelope->'source_read_set')<>jsonb_array_length(v.reads)\n"
                                            '  OR NOT '
                                            'public.direct_source_set_visible(t,v.category_id,v.product_id,v.reads)\n'
                                            '  OR NOT '
                                            'public.knowledge_content_sources_visible(t,v.category_id,v.product_id,v.source_basis)\n'
                                            '  OR NOT '
                                            'public.knowledge_result_sources_visible(t,v.category_id,v.product_id,v.source_basis)\n'
                                            '  OR (v.actor_id<>v.requester_id AND NOT EXISTS(SELECT 1 '
                                            'FROM public.action_receipts r WHERE r.tenant_id=t AND '
                                            'r.id=v.receipt_id AND coalesce(r.agent_run_id,r.run_id) '
                                            'IS NOT NULL))\n'
                                            "  OR (kind='design_rule' AND (v.actor_id<>v.requester_id "
                                            'OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE '
                                            "h.tenant_id=t AND h.id=v.actor_id AND h.kind='human' AND "
                                            'h.active)))\n'
                                            '  OR EXISTS(SELECT 1 FROM public.audit_entries x WHERE '
                                            'x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS '
                                            'DISTINCT FROM vx)\n'
                                            '  OR EXISTS(SELECT 1 FROM public.outbox_events x WHERE '
                                            'x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS '
                                            'DISTINCT FROM vx)\n'
                                            '  OR NOT EXISTS(SELECT 1 FROM public.request_keys x WHERE '
                                            'x.tenant_id=t AND x.receipt_id=v.receipt_id AND '
                                            'x.actor_id=v.actor_id AND x.digest=v.request_digest AND '
                                            'x.xmin=vx AND '
                                            "encode(sha256(convert_to(x.key,'UTF8')),'hex')=v.command->>'original_key_sha256') "
                                            'THEN\n'
                                            "  RAISE EXCEPTION 'Knowledge requires actual scope actor "
                                            "sources and one common transaction' USING "
                                            "ERRCODE='23514'; END IF;\n"
                                            ' IF v.confirmation_id IS NOT NULL THEN\n'
                                            '  SELECT xmin INTO px FROM public.confirmations WHERE '
                                            'tenant_id=t AND id=v.confirmation_id;\n'
                                            '  IF px IS DISTINCT FROM vx THEN RAISE EXCEPTION '
                                            "'Knowledge T2 proof consumption must share its new rule "
                                            "transaction' USING ERRCODE='23514'; END IF;\n"
                                            ' END IF;\n'
                                            ' FOR ref IN SELECT value FROM '
                                            'jsonb_array_elements(v.reads) LOOP\n'
                                            '  IF NOT EXISTS(SELECT 1 FROM public.artifact_versions a '
                                            'WHERE a.tenant_id=t AND a.category_id=v.category_id\n'
                                            "   AND a.id::text=ref->>'artifact_id' AND "
                                            "a.revision::text=ref->>'expected_revision' AND "
                                            "a.status='active'\n"
                                            '   AND (a.original_id IS NULL OR EXISTS(SELECT 1 FROM '
                                            'public.uploaded_originals o JOIN public.original_security '
                                            'sec ON sec.tenant_id=o.tenant_id AND '
                                            'sec.original_id=o.id\n'
                                            '    WHERE o.tenant_id=t AND o.category_id=v.category_id '
                                            "AND o.id=a.original_id AND o.status='parsed' AND "
                                            "sec.source_state='active' AND sec.disposition='active'))) "
                                            'THEN\n'
                                            "   RAISE EXCEPTION 'Knowledge content or authority "
                                            "original is no longer current' USING ERRCODE='23514'; END "
                                            'IF;\n'
                                            ' END LOOP;\n'
                                            " IF jsonb_typeof(v.source_basis->'artifacts') IS DISTINCT "
                                            "FROM 'array' THEN\n"
                                            "  RAISE EXCEPTION 'Work direct source metadata required' "
                                            "USING ERRCODE='23514'; END IF;\n"
                                            ' FOR basis IN SELECT value FROM '
                                            "jsonb_array_elements(v.source_basis->'artifacts') LOOP\n"
                                            '  IF NOT EXISTS(SELECT 1 FROM public.artifact_versions a '
                                            'WHERE a.tenant_id=t AND a.category_id=v.category_id\n'
                                            '   AND a.product_id::text IS NOT DISTINCT FROM '
                                            "basis->>'product_id' AND a.id::text=basis->>'id'\n"
                                            "   AND a.revision::text=basis->>'revision' AND "
                                            "a.content_hash=basis->>'hash' AND a.status='active'\n"
                                            "   AND a.status=basis->>'status' AND "
                                            "a.owner_id::text=basis->>'owner_id' AND "
                                            "a.visibility=basis->>'visibility'\n"
                                            "   AND (v.visibility='private' OR "
                                            "(a.visibility='category' AND (a.product_id IS NULL OR "
                                            'EXISTS(SELECT 1 FROM public.products source_product WHERE '
                                            'source_product.tenant_id=t AND '
                                            'source_product.category_id=v.category_id AND '
                                            'source_product.id=a.product_id AND '
                                            "source_product.visibility='category'))))\n"
                                            "   AND (NOT(basis ? 'original') OR EXISTS(SELECT 1 FROM "
                                            'public.original_security sec\n'
                                            '    WHERE sec.tenant_id=t AND '
                                            'sec.original_id=a.original_id AND '
                                            "sec.original_id::text=basis->'original'->>'id'\n"
                                            "     AND sec.epoch::text=basis->'original'->>'epoch' AND "
                                            "sec.source_state='active' AND sec.disposition='active'))) "
                                            'THEN\n'
                                            "   RAISE EXCEPTION 'Retained work source metadata "
                                            "changed' USING ERRCODE='23514'; END IF;\n"
                                            ' END LOOP;\n'
                                            ' FOR ref IN SELECT value FROM '
                                            'jsonb_array_elements(v.sources) LOOP\n'
                                            '  SELECT value INTO STRICT basis FROM '
                                            "jsonb_array_elements(v.source_basis->'artifacts') WHERE "
                                            "value->>'id'=ref->>'id';\n"
                                            "  IF ref->>'kind' IS DISTINCT FROM 'artifact' OR NOT "
                                            'EXISTS(SELECT 1 FROM jsonb_array_elements(v.reads) rd '
                                            "WHERE rd->>'artifact_id'=ref->>'id' AND "
                                            "rd->'expected_revision'=ref->'revision')\n"
                                            '   OR NOT EXISTS(SELECT 1 FROM public.artifact_versions a '
                                            'WHERE a.tenant_id=t AND a.category_id=v.category_id\n'
                                            "    AND a.id::text=ref->>'id' AND "
                                            "a.revision::text=ref->>'revision' AND a.status='active'\n"
                                            "    AND a.revision::text=basis->>'revision' AND "
                                            "a.content_hash=basis->>'hash' AND "
                                            "a.status=basis->>'status'\n"
                                            "    AND a.owner_id::text=basis->>'owner_id' AND "
                                            "a.visibility=basis->>'visibility'\n"
                                            "    AND (v.visibility='private' OR "
                                            "(a.visibility='category' AND (a.product_id IS NULL OR "
                                            'EXISTS(SELECT 1 FROM public.products source_product WHERE '
                                            'source_product.tenant_id=t AND '
                                            'source_product.category_id=v.category_id AND '
                                            'source_product.id=a.product_id AND '
                                            "source_product.visibility='category'))))\n"
                                            '    AND ((a.original_id IS NULL AND '
                                            "basis->>'source_kind'='registered_native_text' AND "
                                            'EXISTS(\n'
                                            '      SELECT 1 FROM public.action_receipts r WHERE '
                                            'r.tenant_id=t AND r.subject_id=a.id AND '
                                            'r.subject_revision=a.revision\n'
                                            "       AND r.subject_type='artifact' AND "
                                            "r.operation='evidence.artifact.register' AND "
                                            "r.id::text=basis->'registration'->>'receipt_id'\n"
                                            '       AND '
                                            "r.actor_id::text=basis->'registration'->>'actor_id' AND "
                                            "r.requester_id::text=basis->'registration'->>'requester_id'\n"
                                            '       AND r.run_id::text IS NOT DISTINCT FROM '
                                            "basis->'registration'->>'run_id'))\n"
                                            '     OR (a.original_id IS NOT NULL AND '
                                            "basis->>'source_kind'='uploaded_original' AND EXISTS(\n"
                                            '      SELECT 1 FROM public.uploaded_originals o JOIN '
                                            'public.original_security sec ON sec.tenant_id=o.tenant_id '
                                            'AND sec.original_id=o.id\n'
                                            '       WHERE o.tenant_id=t AND '
                                            'o.category_id=v.category_id AND o.id=a.original_id AND '
                                            "o.id::text=basis->'original'->>'id'\n"
                                            "        AND o.status='parsed' AND "
                                            "sec.epoch::text=basis->'original'->>'epoch' AND "
                                            "sec.source_state='active' AND sec.disposition='active'\n"
                                            '        AND '
                                            "sec.source_state=basis->'original'->>'source_state' AND "
                                            "sec.disposition=basis->'original'->>'disposition'\n"
                                            "        AND (v.visibility='private' OR "
                                            "o.visibility='category'))))) THEN\n"
                                            "   RAISE EXCEPTION 'Work source metadata security or "
                                            "audience changed' USING ERRCODE='23514'; END IF;\n"
                                            ' END LOOP;\n'
                                            'END;\n'
                                            '$function$\n',
 'assert_knowledge_professional(uuid,uuid)': 'CREATE OR REPLACE FUNCTION '
                                             'public.assert_knowledge_professional(t uuid, target '
                                             'uuid)\n'
                                             ' RETURNS void\n'
                                             ' LANGUAGE plpgsql\n'
                                             ' SECURITY DEFINER\n'
                                             " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                             'AS $function$\n'
                                             '\n'
                                             'DECLARE v public.knowledge_rule_versions; authority '
                                             'jsonb; reference jsonb;\n'
                                             ' fact public.professional_authority_facts; pointer '
                                             'public.professional_authority_current;\n'
                                             ' has_duty boolean=false; has_qualification '
                                             'boolean=false;\n'
                                             'BEGIN\n'
                                             ' SELECT * INTO STRICT v FROM '
                                             'public.knowledge_rule_versions WHERE tenant_id=t AND '
                                             'id=target;\n'
                                             " authority=v.source_basis->'professional';\n"
                                             " IF jsonb_typeof(authority) IS DISTINCT FROM 'object'\n"
                                             "  OR authority->'scope' IS DISTINCT FROM "
                                             "jsonb_build_object('tenant_id',t,'product_id',v.product_id,'project_id',v.project_id)\n"
                                             "  OR authority->>'subject_id' IS DISTINCT FROM "
                                             'v.actor_id::text\n'
                                             "  OR authority->>'operation' IS DISTINCT FROM "
                                             'v.operation\n'
                                             "  OR authority->>'purpose' IS DISTINCT FROM "
                                             "v.body->'applicability'->>'purpose'\n"
                                             "  OR authority->'authorized' IS DISTINCT FROM "
                                             "'true'::jsonb OR authority->'qualified' IS DISTINCT FROM "
                                             "'true'::jsonb\n"
                                             "  OR authority->'roles' IS DISTINCT FROM "
                                             '\'["knowledge"]\'::jsonb\n'
                                             "  OR jsonb_typeof(authority->'fact_refs') IS DISTINCT "
                                             "FROM 'array'\n"
                                             "  OR jsonb_array_length(authority->'fact_refs')=0\n"
                                             '  OR v.nature IS DISTINCT FROM (CASE WHEN '
                                             "authority->'synthetic'='true'::jsonb THEN 'synthetic' "
                                             "ELSE 'real' END) THEN\n"
                                             "  RAISE EXCEPTION 'Knowledge publication requires its "
                                             "own actual named authority scope' USING ERRCODE='23514'; "
                                             'END IF;\n'
                                             ' FOR reference IN SELECT value FROM '
                                             "jsonb_array_elements(authority->'fact_refs') LOOP\n"
                                             '  SELECT * INTO fact FROM '
                                             'public.professional_authority_facts f WHERE '
                                             'f.tenant_id=t AND f.product_id=v.product_id AND '
                                             'f.project_id=v.project_id\n'
                                             '   AND f.subject_id=v.actor_id AND '
                                             "f.id::text=reference->>'id' AND "
                                             "f.revision::text=reference->>'revision';\n"
                                             "  IF NOT FOUND THEN RAISE EXCEPTION 'Knowledge authority "
                                             "cannot be invented from a snapshot' USING "
                                             "ERRCODE='23514'; END IF;\n"
                                             '  SELECT * INTO pointer FROM '
                                             'public.professional_authority_current p WHERE '
                                             'p.tenant_id=t AND p.product_id=v.product_id AND '
                                             'p.project_id=v.project_id\n'
                                             '   AND p.subject_id=v.actor_id AND p.fact_id=fact.id AND '
                                             'p.fact_revision=fact.revision AND '
                                             'p.series_id=fact.series_id AND '
                                             "p.epoch::text=reference->>'epoch';\n"
                                             '  IF NOT FOUND OR fact.fact_sha256 IS DISTINCT FROM '
                                             "reference->>'fact_sha256'\n"
                                             '   OR fact.series_id::text IS DISTINCT FROM '
                                             "reference->>'series_id'\n"
                                             "   OR fact.kind IS DISTINCT FROM reference->>'kind' OR "
                                             "fact.role IS DISTINCT FROM reference->>'role'\n"
                                             "   OR fact.nature IS DISTINCT FROM reference->>'nature' "
                                             "OR fact.state IS DISTINCT FROM reference->>'state'\n"
                                             '   OR fact.issuer_key IS DISTINCT FROM '
                                             "reference->>'issuer_key' OR fact.issuer_version IS "
                                             "DISTINCT FROM reference->>'issuer_version'\n"
                                             '   OR fact.operations IS DISTINCT FROM '
                                             "reference->'operations' OR fact.purposes IS DISTINCT "
                                             "FROM reference->'purposes'\n"
                                             '   OR NOT coalesce(v.reads @> '
                                             'fact.required_source_read_set,false) THEN\n'
                                             "   RAISE EXCEPTION 'Knowledge authority snapshot must "
                                             "bind actual current duty and qualification facts' USING "
                                             "ERRCODE='23514'; END IF;\n"
                                             "  IF fact.role='knowledge' AND fact.state='active' AND "
                                             'fact.valid_from<=v.created_at AND '
                                             'v.created_at<fact.valid_until\n'
                                             '   AND fact.operations @> jsonb_build_array(v.operation) '
                                             'AND fact.purposes @> '
                                             "jsonb_build_array(v.body->'applicability'->>'purpose') "
                                             'THEN\n'
                                             "   IF fact.kind='duty' THEN has_duty=true; ELSIF "
                                             "fact.kind='qualification' THEN has_qualification=true; "
                                             'END IF;\n'
                                             '  END IF;\n'
                                             ' END LOOP;\n'
                                             ' IF NOT has_duty OR NOT has_qualification THEN\n'
                                             "  RAISE EXCEPTION 'Prior engineering quality or "
                                             "manufacturing roles do not grant knowledge publication' "
                                             "USING ERRCODE='23514'; END IF;\n"
                                             'END;\n'
                                             '$function$\n',
 'protect_knowledge_receipt()': 'CREATE OR REPLACE FUNCTION public.protect_knowledge_receipt()\n'
                                ' RETURNS trigger\n'
                                ' LANGUAGE plpgsql\n'
                                ' SECURITY DEFINER\n'
                                " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                'AS $function$\n'
                                '\n'
                                'DECLARE scoped boolean=false;\n'
                                'BEGIN\n'
                                " IF TG_OP<>'INSERT' THEN scoped=OLD.operation IN "
                                "('knowledge.candidate.create','knowledge.rule.publish') OR "
                                "OLD.subject_type IN ('knowledge_candidate','design_rule'); END IF;\n"
                                " IF TG_OP<>'DELETE' THEN scoped=scoped OR NEW.operation IN "
                                "('knowledge.candidate.create','knowledge.rule.publish') OR "
                                "NEW.subject_type IN ('knowledge_candidate','design_rule'); END IF;\n"
                                " IF scoped AND TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Knowledge "
                                "receipt history is immutable' USING ERRCODE='23514'; END IF;\n"
                                " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
                                'END;\n'
                                '$function$\n',
 'protect_knowledge_member()': 'CREATE OR REPLACE FUNCTION public.protect_knowledge_member()\n'
                               ' RETURNS trigger\n'
                               ' LANGUAGE plpgsql\n'
                               ' SECURITY DEFINER\n'
                               " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                               'AS $function$\n'
                               '\n'
                               'DECLARE scoped boolean=false; old_scoped boolean=false;\n'
                               'BEGIN\n'
                               " IF TG_OP<>'DELETE' THEN SELECT EXISTS(SELECT 1 FROM "
                               'public.action_receipts r WHERE r.tenant_id=NEW.tenant_id AND '
                               'r.id=NEW.receipt_id AND (r.operation IN '
                               "('knowledge.candidate.create','knowledge.rule.publish') OR "
                               "r.subject_type IN ('knowledge_candidate','design_rule'))) INTO scoped; "
                               'END IF;\n'
                               " IF TG_OP<>'INSERT' THEN SELECT EXISTS(SELECT 1 FROM "
                               'public.action_receipts r WHERE r.tenant_id=OLD.tenant_id AND '
                               'r.id=OLD.receipt_id AND (r.operation IN '
                               "('knowledge.candidate.create','knowledge.rule.publish') OR "
                               "r.subject_type IN ('knowledge_candidate','design_rule'))) INTO "
                               'old_scoped; END IF;\n'
                               " IF TG_OP<>'INSERT' AND (scoped OR old_scoped) THEN\n"
                               "  IF TG_OP='UPDATE' AND TG_TABLE_NAME='outbox_events' AND "
                               "(to_jsonb(NEW)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) "
                               'IS NOT DISTINCT FROM '
                               "(to_jsonb(OLD)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) "
                               'THEN RETURN NEW; END IF;\n'
                               "  RAISE EXCEPTION 'Knowledge original audit event or request key is "
                               "immutable' USING ERRCODE='23514'; END IF;\n"
                               " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
                               'END;\n'
                               '$function$\n',
 'require_knowledge_member()': 'CREATE OR REPLACE FUNCTION public.require_knowledge_member()\n'
                               ' RETURNS trigger\n'
                               ' LANGUAGE plpgsql\n'
                               ' SECURITY DEFINER\n'
                               " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                               'AS $function$\n'
                               '\n'
                               'DECLARE receipt public.action_receipts;\n'
                               'BEGIN\n'
                               " IF TG_TABLE_NAME='action_receipts' THEN receipt=NEW; ELSE SELECT * "
                               'INTO receipt FROM public.action_receipts WHERE tenant_id=NEW.tenant_id '
                               'AND id=NEW.receipt_id; END IF;\n'
                               ' IF receipt.operation IN '
                               "('knowledge.candidate.create','knowledge.rule.publish') OR "
                               "receipt.subject_type IN ('knowledge_candidate','design_rule') THEN\n"
                               '  PERFORM '
                               'public.assert_knowledge_members(receipt.tenant_id,receipt.subject_id,receipt.subject_type::text); '
                               'END IF;\n'
                               ' RETURN NULL;\n'
                               'END;\n'
                               '$function$\n',
 'protect_knowledge_confirmation()': 'CREATE OR REPLACE FUNCTION '
                                     'public.protect_knowledge_confirmation()\n'
                                     ' RETURNS trigger\n'
                                     ' LANGUAGE plpgsql\n'
                                     ' SECURITY DEFINER\n'
                                     " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                     'AS $function$\n'
                                     '\n'
                                     'DECLARE old_scoped boolean=false; new_scoped boolean=false;\n'
                                     'BEGIN\n'
                                     " IF TG_OP<>'INSERT' THEN "
                                     "old_scoped=OLD.operation='knowledge.rule.publish'; END IF;\n"
                                     " IF TG_OP<>'DELETE' THEN "
                                     "new_scoped=NEW.operation='knowledge.rule.publish'; END IF;\n"
                                     ' IF old_scoped OR new_scoped THEN\n'
                                     "  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Knowledge publication "
                                     "confirmation history retained' USING ERRCODE='23514';\n"
                                     "  ELSIF TG_OP='INSERT' THEN\n"
                                     '   IF NEW.consumed IS DISTINCT FROM false THEN RAISE EXCEPTION '
                                     "'Knowledge publication proof starts unconsumed' USING "
                                     "ERRCODE='23514'; END IF;\n"
                                     '  ELSIF NOT(old_scoped AND new_scoped) OR OLD.consumed IS '
                                     'DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true\n'
                                     "   OR (to_jsonb(NEW)-'consumed') IS DISTINCT FROM "
                                     "(to_jsonb(OLD)-'consumed') THEN\n"
                                     "   RAISE EXCEPTION 'Knowledge publication proof consumes only "
                                     "its original false to true' USING ERRCODE='23514'; END IF;\n"
                                     ' END IF;\n'
                                     " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
                                     'END;\n'
                                     '$function$\n',
 'require_knowledge_confirmation()': 'CREATE OR REPLACE FUNCTION '
                                     'public.require_knowledge_confirmation()\n'
                                     ' RETURNS trigger\n'
                                     ' LANGUAGE plpgsql\n'
                                     ' SECURITY DEFINER\n'
                                     " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                     'AS $function$\n'
                                     '\n'
                                     'BEGIN\n'
                                     " IF NEW.operation='knowledge.rule.publish' THEN\n"
                                     '  IF OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS '
                                     'DISTINCT FROM true\n'
                                     '   OR (SELECT count(*) FROM public.knowledge_rule_versions v '
                                     'WHERE v.tenant_id=NEW.tenant_id AND v.confirmation_id=NEW.id AND '
                                     'v.operation=NEW.operation)<>1 THEN\n'
                                     "   RAISE EXCEPTION 'Consumed knowledge T2 proof needs exactly "
                                     "one new publication' USING ERRCODE='23514'; END IF;\n"
                                     ' END IF;\n'
                                     ' RETURN NULL;\n'
                                     'END;\n'
                                     '$function$\n',
 'assert_knowledge_candidate(uuid,uuid)': 'CREATE OR REPLACE FUNCTION '
                                          'public.assert_knowledge_candidate(t uuid, target uuid)\n'
                                          ' RETURNS void\n'
                                          ' LANGUAGE plpgsql\n'
                                          ' SECURITY DEFINER\n'
                                          " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                          'AS $function$\n'
                                          '\n'
                                          'DECLARE v public.knowledge_candidate_versions; prior '
                                          'public.knowledge_candidate_versions;\n'
                                          ' cur public.knowledge_candidate_currents; payload jsonb; '
                                          'expected jsonb; vx xid; cx xid;\n'
                                          'BEGIN\n'
                                          ' SELECT * INTO STRICT v FROM '
                                          'public.knowledge_candidate_versions WHERE tenant_id=t AND '
                                          'id=target;\n'
                                          ' SELECT xmin INTO vx FROM '
                                          'public.knowledge_candidate_versions WHERE tenant_id=t AND '
                                          'id=target;\n'
                                          ' PERFORM '
                                          "public.assert_knowledge_common(t,target,'knowledge_candidate');\n"
                                          ' SELECT * INTO STRICT cur FROM '
                                          'public.knowledge_candidate_currents WHERE tenant_id=t AND '
                                          'category_id=v.category_id AND candidate_id=v.candidate_id;\n'
                                          ' SELECT xmin INTO cx FROM '
                                          'public.knowledge_candidate_currents WHERE tenant_id=t AND '
                                          'id=cur.id;\n'
                                          " payload=v.command->'envelope'->'payload';\n"
                                          ' '
                                          "expected=jsonb_build_object('candidate_id',v.candidate_id,'revision',v.revision,'title',payload->'title',\n"
                                          '  '
                                          "'lesson',payload->'lesson','evidence_summary',payload->'evidence_summary',\n"
                                          '  '
                                          "'applicability_hypothesis',payload->'applicability_hypothesis','result_receipts',payload->'result_receipts');\n"
                                          ' IF vx IS DISTINCT FROM cx OR v.body IS DISTINCT FROM '
                                          'expected\n'
                                          "  OR payload->>'visibility' IS DISTINCT FROM v.visibility\n"
                                          '  OR v.owner_id<>v.requester_id\n'
                                          '  OR '
                                          'ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.candidate_id,cur.version_id,cur.revision)\n'
                                          '   IS DISTINCT FROM '
                                          'ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.candidate_id,v.id,v.revision) '
                                          'THEN\n'
                                          "  RAISE EXCEPTION 'Knowledge candidate requires exact "
                                          "declared content and same-transaction Current' USING "
                                          "ERRCODE='23514'; END IF;\n"
                                          ' IF v.revision=1 THEN\n'
                                          '  IF '
                                          "coalesce(payload->'candidate','null'::jsonb)<>'null'::jsonb\n"
                                          '   OR '
                                          "coalesce(v.command->'review'->'before','null'::jsonb)<>'null'::jsonb\n"
                                          '   OR v.owner_id<>v.requester_id THEN\n'
                                          "   RAISE EXCEPTION 'First knowledge candidate binds its "
                                          "actual requester and declared category scope' USING "
                                          "ERRCODE='23514'; END IF;\n"
                                          ' ELSE\n'
                                          '  SELECT * INTO STRICT prior FROM '
                                          'public.knowledge_candidate_versions WHERE tenant_id=t AND '
                                          'id=v.previous_id;\n'
                                          "  IF payload->'candidate' IS DISTINCT FROM "
                                          "jsonb_build_object('id',v.candidate_id,'revision',v.previous_revision)\n"
                                          "   OR v.command->'review'->'before' IS DISTINCT FROM "
                                          'prior.body\n'
                                          '   OR '
                                          'ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.candidate_id)\n'
                                          '    IS DISTINCT FROM '
                                          'ROW(prior.category_id,prior.product_id,prior.project_id,prior.owner_id,prior.visibility,prior.candidate_id) '
                                          'THEN\n'
                                          "   RAISE EXCEPTION 'Knowledge candidate continuation cannot "
                                          "replace its fixed scope or predecessor' USING "
                                          "ERRCODE='23514'; END IF;\n"
                                          '  IF EXISTS(SELECT 1 FROM public.principals actor WHERE '
                                          'actor.tenant_id=t AND actor.id=v.actor_id AND '
                                          "actor.kind='agent')\n"
                                          '   AND (prior.actor_id<>v.actor_id OR NOT EXISTS(SELECT 1 '
                                          'FROM public.principals author WHERE author.tenant_id=t AND '
                                          "author.id=prior.actor_id AND author.kind='agent')\n"
                                          '    OR EXISTS(SELECT 1 FROM public.knowledge_rule_versions '
                                          'consumed WHERE consumed.tenant_id=t AND '
                                          'consumed.category_id=v.category_id AND '
                                          'consumed.candidate_id=v.candidate_id)) THEN\n'
                                          "   RAISE EXCEPTION 'AI may continue only its own "
                                          'unpublished candidate lineage without overwriting human '
                                          "content' USING ERRCODE='23514'; END IF;\n"
                                          ' END IF;\n'
                                          'END;\n'
                                          '$function$\n',
 'require_knowledge_candidate()': 'CREATE OR REPLACE FUNCTION public.require_knowledge_candidate()\n'
                                  ' RETURNS trigger\n'
                                  ' LANGUAGE plpgsql\n'
                                  ' SECURITY DEFINER\n'
                                  " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                  'AS $function$\n'
                                  'BEGIN PERFORM '
                                  'public.assert_knowledge_candidate(NEW.tenant_id,NEW.id); RETURN '
                                  'NULL; END;\n'
                                  '$function$\n',
 'assert_knowledge_rule(uuid,uuid)': 'CREATE OR REPLACE FUNCTION public.assert_knowledge_rule(t uuid, '
                                     'target uuid)\n'
                                     ' RETURNS void\n'
                                     ' LANGUAGE plpgsql\n'
                                     ' SECURITY DEFINER\n'
                                     " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                     'AS $function$\n'
                                     '\n'
                                     'DECLARE v public.knowledge_rule_versions; prior '
                                     'public.knowledge_rule_versions;\n'
                                     ' cur public.knowledge_rule_currents; candidate '
                                     'public.knowledge_candidate_versions;\n'
                                     ' candidate_current public.knowledge_candidate_currents; '
                                     'assessment public.knowledge_applicability_assessments;\n'
                                     ' payload jsonb; expected jsonb; applicability jsonb; '
                                     'expected_assessment jsonb; vx xid; cx xid; ax xid;\n'
                                     'BEGIN\n'
                                     ' SELECT * INTO STRICT v FROM public.knowledge_rule_versions '
                                     'WHERE tenant_id=t AND id=target;\n'
                                     ' SELECT xmin INTO vx FROM public.knowledge_rule_versions WHERE '
                                     'tenant_id=t AND id=target;\n'
                                     ' PERFORM '
                                     "public.assert_knowledge_common(t,target,'design_rule');\n"
                                     ' PERFORM public.assert_knowledge_professional(t,target);\n'
                                     ' SELECT * INTO STRICT cur FROM public.knowledge_rule_currents '
                                     'WHERE tenant_id=t AND category_id=v.category_id AND '
                                     'rule_id=v.rule_id;\n'
                                     ' SELECT xmin INTO cx FROM public.knowledge_rule_currents WHERE '
                                     'tenant_id=t AND id=cur.id;\n'
                                     ' SELECT * INTO STRICT candidate FROM '
                                     'public.knowledge_candidate_versions WHERE tenant_id=t AND '
                                     'category_id=v.category_id AND id=v.candidate_version_id;\n'
                                     ' SELECT * INTO STRICT candidate_current FROM '
                                     'public.knowledge_candidate_currents WHERE tenant_id=t AND '
                                     'category_id=v.category_id AND candidate_id=v.candidate_id;\n'
                                     ' SELECT * INTO STRICT assessment FROM '
                                     'public.knowledge_applicability_assessments WHERE tenant_id=t AND '
                                     'id=v.assessment_id;\n'
                                     ' SELECT xmin INTO ax FROM '
                                     'public.knowledge_applicability_assessments WHERE tenant_id=t AND '
                                     'id=v.assessment_id;\n'
                                     " payload=v.command->'envelope'->'payload'; "
                                     "applicability=payload->'applicability';\n"
                                     ' '
                                     "expected_assessment=applicability||jsonb_build_object('candidate_version',jsonb_build_object('id',candidate.id,'revision',candidate.revision),\n"
                                     "  'assessor_id',v.actor_id,'withdrawal_reason',NULL);\n"
                                     ' '
                                     "expected=jsonb_build_object('rule_id',v.rule_id,'revision',v.revision,'candidate',jsonb_build_object('id',v.candidate_id,'revision',v.candidate_revision),\n"
                                     '  '
                                     "'candidate_version_id',v.candidate_version_id,'assessment_id',v.assessment_id,'title',payload->'title','rule_text',payload->'rule_text',\n"
                                     "  'applicability',assessment.body,'nature',v.nature);\n"
                                     ' IF vx IS DISTINCT FROM cx OR vx IS DISTINCT FROM ax\n'
                                     '  OR '
                                     'ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.rule_id,cur.version_id,cur.revision)\n'
                                     '   IS DISTINCT FROM '
                                     'ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.rule_id,v.id,v.revision)\n'
                                     '  OR candidate.candidate_id<>v.candidate_id OR '
                                     'candidate.revision<>v.candidate_revision\n'
                                     "  OR (candidate.visibility='private' AND "
                                     "(v.visibility<>'private' OR candidate.owner_id<>v.owner_id))\n"
                                     '  OR candidate_current.version_id<>candidate.id OR '
                                     'candidate_current.revision<>candidate.revision\n'
                                     "  OR v.source_basis->'candidate' IS DISTINCT FROM "
                                     "jsonb_build_object('id',candidate.id,'revision',candidate.revision,'body_sha256',candidate.body_sha256)\n"
                                     "  OR payload->'candidate' IS DISTINCT FROM "
                                     "jsonb_build_object('id',candidate.candidate_id,'revision',candidate.revision)\n"
                                     '  OR assessment.body IS DISTINCT FROM expected_assessment OR '
                                     'v.body IS DISTINCT FROM expected\n'
                                     '  OR '
                                     'ROW(assessment.category_id,assessment.product_id,assessment.project_id,assessment.owner_id,assessment.visibility,assessment.publication_id,assessment.candidate_version_id,assessment.candidate_revision,assessment.actor_id,assessment.receipt_id)\n'
                                     '   IS DISTINCT FROM '
                                     'ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.id,v.candidate_version_id,v.candidate_revision,v.actor_id,v.receipt_id)\n'
                                     "  OR assessment.body->>'decision' IS DISTINCT FROM 'applicable'\n"
                                     "  OR (assessment.body->>'valid_from')::timestamptz IS DISTINCT "
                                     'FROM v.valid_from\n'
                                     "  OR (assessment.body->>'valid_until')::timestamptz IS DISTINCT "
                                     'FROM v.valid_until THEN\n'
                                     "  RAISE EXCEPTION 'Knowledge publication binds exact candidate "
                                     "assessment authority and one atomic group' USING "
                                     "ERRCODE='23514'; END IF;\n"
                                     " IF applicability->'target'->>'kind'='engineering_configuration' "
                                     'THEN\n'
                                     '  IF NOT EXISTS(SELECT 1 FROM public.engineering_configurations '
                                     'target WHERE target.tenant_id=t AND '
                                     'target.category_id=v.category_id AND '
                                     'target.product_id=v.product_id\n'
                                     "   AND target.id::text=applicability->'target'->>'id' AND "
                                     "target.revision::text=applicability->'target'->>'revision'\n"
                                     '   AND '
                                     "v.source_basis->'target'=jsonb_build_object('kind','engineering_configuration','id',target.id,'revision',target.revision,'product_id',target.product_id,'owner_id',target.owner_id,'visibility',target.visibility,'sources',target.sources,'required_source_read_set',target.required_source_read_set)\n"
                                     '   AND coalesce(v.reads @> '
                                     'target.required_source_read_set,false)\n'
                                     '   AND EXISTS(SELECT 1 FROM public.project_product_links link '
                                     'WHERE link.tenant_id=t AND link.category_id=v.category_id AND '
                                     'link.product_id=v.product_id AND link.project_id=v.project_id '
                                     'AND link.definition_id=target.definition_id AND '
                                     'link.definition_revision=target.definition_revision)\n'
                                     "   AND (target.visibility='category' OR "
                                     'target.owner_id=public.scope_requester() OR EXISTS(SELECT 1 FROM '
                                     'public.object_audiences audience WHERE audience.tenant_id=t AND '
                                     'audience.category_id=v.category_id AND '
                                     "audience.object_type='engineering_configurations' AND "
                                     'audience.subject_id=target.id AND '
                                     'audience.owner_id=target.owner_id AND '
                                     'audience.principal_id=public.scope_requester()))\n'
                                     "   AND (v.visibility='private' OR target.visibility='category')) "
                                     'THEN\n'
                                     "   RAISE EXCEPTION 'Knowledge target must be an actual readable "
                                     "fixed engineering configuration' USING ERRCODE='23514'; END IF;\n"
                                     " ELSIF applicability->'target'->>'kind'='process_revision' THEN\n"
                                     '  IF NOT EXISTS(SELECT 1 FROM public.process_revisions target '
                                     'WHERE target.tenant_id=t AND target.category_id=v.category_id '
                                     'AND target.product_id=v.product_id\n'
                                     "   AND target.id::text=applicability->'target'->>'id' AND "
                                     "target.revision::text=applicability->'target'->>'revision'\n"
                                     '   AND '
                                     "v.source_basis->'target'=jsonb_build_object('kind','process_revision','id',target.id,'revision',target.revision,'product_id',target.product_id,'owner_id',target.owner_id,'visibility',target.visibility,'sources',target.sources,'required_source_read_set',target.required_source_read_set)\n"
                                     '   AND coalesce(v.reads @> '
                                     'target.required_source_read_set,false)\n'
                                     '   AND EXISTS(SELECT 1 FROM public.engineering_configurations '
                                     'engineering JOIN public.project_product_links link ON '
                                     'link.tenant_id=engineering.tenant_id AND '
                                     'link.category_id=engineering.category_id AND '
                                     'link.product_id=engineering.product_id AND '
                                     'link.definition_id=engineering.definition_id AND '
                                     'link.definition_revision=engineering.definition_revision\n'
                                     '    WHERE engineering.tenant_id=t AND '
                                     'engineering.category_id=v.category_id AND '
                                     'engineering.product_id=v.product_id AND '
                                     'engineering.id=target.engineering_configuration_id AND '
                                     'engineering.revision=target.engineering_revision AND '
                                     'link.project_id=v.project_id)\n'
                                     "   AND (target.visibility='category' OR "
                                     'target.owner_id=public.scope_requester() OR EXISTS(SELECT 1 FROM '
                                     'public.object_audiences audience WHERE audience.tenant_id=t AND '
                                     'audience.category_id=v.category_id AND '
                                     "audience.object_type='process_revisions' AND "
                                     'audience.subject_id=target.id AND '
                                     'audience.owner_id=target.owner_id AND '
                                     'audience.principal_id=public.scope_requester()))\n'
                                     "   AND (v.visibility='private' OR target.visibility='category')) "
                                     'THEN\n'
                                     "   RAISE EXCEPTION 'Knowledge target must be an actual readable "
                                     "fixed manufacturing configuration' USING ERRCODE='23514'; END "
                                     'IF;\n'
                                     " ELSE RAISE EXCEPTION 'Knowledge target configuration kind is "
                                     "not registered' USING ERRCODE='23514'; END IF;\n"
                                     ' IF v.revision=1 THEN\n'
                                     "  IF coalesce(payload->'rule','null'::jsonb)<>'null'::jsonb\n"
                                     '   OR '
                                     "coalesce(v.command->'review'->'before','null'::jsonb)<>'null'::jsonb "
                                     'OR v.owner_id<>v.requester_id THEN\n'
                                     "   RAISE EXCEPTION 'First published rule binds the actual named "
                                     "publisher' USING ERRCODE='23514'; END IF;\n"
                                     ' ELSE\n'
                                     '  SELECT * INTO STRICT prior FROM public.knowledge_rule_versions '
                                     'WHERE tenant_id=t AND id=v.previous_id;\n'
                                     "  IF payload->'rule' IS DISTINCT FROM "
                                     "jsonb_build_object('id',v.rule_id,'revision',v.previous_revision)\n"
                                     "   OR v.command->'review'->'before' IS DISTINCT FROM prior.body\n"
                                     '   OR '
                                     'ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.rule_id)\n'
                                     '    IS DISTINCT FROM '
                                     'ROW(prior.category_id,prior.product_id,prior.project_id,prior.owner_id,prior.visibility,prior.rule_id) '
                                     'THEN\n'
                                     "   RAISE EXCEPTION 'Published rule continuation cannot replace "
                                     "fixed scope or its original predecessor' USING ERRCODE='23514'; "
                                     'END IF;\n'
                                     ' END IF;\n'
                                     'END;\n'
                                     '$function$\n',
 'require_knowledge_rule()': 'CREATE OR REPLACE FUNCTION public.require_knowledge_rule()\n'
                             ' RETURNS trigger\n'
                             ' LANGUAGE plpgsql\n'
                             ' SECURITY DEFINER\n'
                             " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                             'AS $function$\n'
                             'BEGIN PERFORM public.assert_knowledge_rule(NEW.tenant_id,NEW.id); RETURN '
                             'NULL; END;\n'
                             '$function$\n',
 'assert_knowledge_assessment(uuid,uuid)': 'CREATE OR REPLACE FUNCTION '
                                           'public.assert_knowledge_assessment(t uuid, target uuid)\n'
                                           ' RETURNS void\n'
                                           ' LANGUAGE plpgsql\n'
                                           ' SECURITY DEFINER\n'
                                           " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                           'AS $function$\n'
                                           '\n'
                                           'DECLARE assessment '
                                           'public.knowledge_applicability_assessments; publication '
                                           'public.knowledge_rule_versions; ax xid; vx xid;\n'
                                           'BEGIN\n'
                                           ' SELECT * INTO STRICT assessment FROM '
                                           'public.knowledge_applicability_assessments WHERE '
                                           'tenant_id=t AND id=target;\n'
                                           ' SELECT xmin INTO ax FROM '
                                           'public.knowledge_applicability_assessments WHERE '
                                           'tenant_id=t AND id=target;\n'
                                           ' SELECT * INTO STRICT publication FROM '
                                           'public.knowledge_rule_versions WHERE tenant_id=t AND '
                                           'id=assessment.publication_id;\n'
                                           ' SELECT xmin INTO vx FROM public.knowledge_rule_versions '
                                           'WHERE tenant_id=t AND id=assessment.publication_id;\n'
                                           ' IF ax IS DISTINCT FROM vx OR '
                                           'publication.assessment_id<>assessment.id\n'
                                           '  OR assessment.body IS DISTINCT FROM '
                                           "publication.body->'applicability'\n"
                                           '  OR '
                                           'ROW(assessment.category_id,assessment.product_id,assessment.project_id,assessment.owner_id,assessment.visibility,assessment.candidate_version_id,assessment.candidate_revision,assessment.actor_id,assessment.receipt_id)\n'
                                           '   IS DISTINCT FROM '
                                           'ROW(publication.category_id,publication.product_id,publication.project_id,publication.owner_id,publication.visibility,publication.candidate_version_id,publication.candidate_revision,publication.actor_id,publication.receipt_id) '
                                           'THEN\n'
                                           "  RAISE EXCEPTION 'Applicability assessment exists only as "
                                           "its one actual T2 publication child' USING "
                                           "ERRCODE='23514'; END IF;\n"
                                           'END;\n'
                                           '$function$\n',
 'require_knowledge_assessment()': 'CREATE OR REPLACE FUNCTION public.require_knowledge_assessment()\n'
                                   ' RETURNS trigger\n'
                                   ' LANGUAGE plpgsql\n'
                                   ' SECURITY DEFINER\n'
                                   " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                   'AS $function$\n'
                                   'BEGIN PERFORM '
                                   'public.assert_knowledge_assessment(NEW.tenant_id,NEW.id); RETURN '
                                   'NULL; END;\n'
                                   '$function$\n',
 'knowledge_content_sources_visible(uuid,uuid,uuid,jsonb)': 'CREATE OR REPLACE FUNCTION '
                                                            'public.knowledge_content_sources_visible(t '
                                                            'uuid, c uuid, p uuid, basis jsonb)\n'
                                                            ' RETURNS boolean\n'
                                                            ' LANGUAGE plpgsql\n'
                                                            ' STABLE\n'
                                                            " SET search_path TO 'pg_catalog', "
                                                            "'public', 'pg_temp'\n"
                                                            'AS $function$\n'
                                                            'DECLARE expected jsonb; actual_product '
                                                            'uuid; original_id uuid; found_source '
                                                            'boolean;\n'
                                                            'BEGIN\n'
                                                            ' IF t IS DISTINCT FROM '
                                                            "nullif(current_setting('pdos.tenant_id',true),'')::uuid\n"
                                                            '  OR NOT public.category_access(t,c) OR '
                                                            'jsonb_typeof(basis) IS DISTINCT FROM '
                                                            "'object'\n"
                                                            "  OR jsonb_typeof(basis->'artifacts') IS "
                                                            "DISTINCT FROM 'array' THEN RETURN false; "
                                                            'END IF;\n'
                                                            ' FOR expected IN SELECT value FROM '
                                                            "jsonb_array_elements(basis->'artifacts') "
                                                            'LOOP\n'
                                                            '  IF jsonb_typeof(expected) IS DISTINCT '
                                                            "FROM 'object' OR NOT(expected ? "
                                                            "'product_id')\n"
                                                            "   OR expected->>'category_id' IS "
                                                            'DISTINCT FROM c::text THEN RETURN false; '
                                                            'END IF;\n'
                                                            '  SELECT a.product_id,a.original_id,true '
                                                            'INTO '
                                                            'actual_product,original_id,found_source\n'
                                                            '   FROM public.artifact_versions a WHERE '
                                                            'a.tenant_id=t AND a.category_id=c\n'
                                                            "    AND a.id::text=expected->>'id' AND "
                                                            'a.product_id::text IS NOT DISTINCT FROM '
                                                            "expected->>'product_id';\n"
                                                            '  IF found_source IS DISTINCT FROM true '
                                                            'THEN RETURN false; END IF;\n'
                                                            '  IF actual_product IS NOT NULL AND NOT '
                                                            'EXISTS(SELECT 1 FROM public.products '
                                                            'source_product\n'
                                                            '    WHERE source_product.tenant_id=t AND '
                                                            'source_product.category_id=c AND '
                                                            'source_product.id=actual_product) THEN '
                                                            'RETURN false; END IF;\n'
                                                            '  IF original_id IS NOT NULL THEN\n'
                                                            '   IF original_id::text IS DISTINCT FROM '
                                                            "expected->'original'->>'id'\n"
                                                            '    OR NOT EXISTS(SELECT 1 FROM '
                                                            'public.uploaded_originals o WHERE '
                                                            'o.tenant_id=t AND o.category_id=c\n'
                                                            '     AND o.product_id IS NOT DISTINCT '
                                                            'FROM actual_product AND o.id=original_id) '
                                                            'THEN RETURN false; END IF;\n'
                                                            '  END IF;\n'
                                                            ' END LOOP;\n'
                                                            ' RETURN true;\n'
                                                            'EXCEPTION WHEN '
                                                            'invalid_text_representation OR '
                                                            'numeric_value_out_of_range THEN RETURN '
                                                            'false;\n'
                                                            'END;\n'
                                                            '$function$\n',
 'knowledge_result_sources_visible(uuid,uuid,uuid,jsonb)': 'CREATE OR REPLACE FUNCTION '
                                                           'public.knowledge_result_sources_visible(t '
                                                           'uuid, c uuid, p uuid, basis jsonb)\n'
                                                           ' RETURNS boolean\n'
                                                           ' LANGUAGE plpgsql\n'
                                                           ' STABLE\n'
                                                           " SET search_path TO 'pg_catalog', "
                                                           "'public', 'pg_temp'\n"
                                                           'AS $function$\n'
                                                           '\n'
                                                           'DECLARE expected jsonb; visible boolean;\n'
                                                           'BEGIN\n'
                                                           ' IF t IS DISTINCT FROM '
                                                           "nullif(current_setting('pdos.tenant_id',true),'')::uuid\n"
                                                           '  OR NOT public.category_access(t,c) OR '
                                                           'jsonb_typeof(basis) IS DISTINCT FROM '
                                                           "'object'\n"
                                                           '  OR '
                                                           "jsonb_typeof(basis->'result_receipts') IS "
                                                           "DISTINCT FROM 'array' THEN RETURN false; "
                                                           'END IF;\n'
                                                           ' FOR expected IN SELECT value FROM '
                                                           "jsonb_array_elements(basis->'result_receipts') "
                                                           'LOOP\n'
                                                           '  IF jsonb_typeof(expected) IS DISTINCT '
                                                           "FROM 'object' OR expected->>'category_id' "
                                                           'IS DISTINCT FROM c::text THEN RETURN '
                                                           'false;\n'
                                                           '\n'
                                                           " ELSIF expected->>'table'='builds' AND "
                                                           "expected->>'subject_type'='build' THEN\n"
                                                           '  SELECT EXISTS(SELECT 1 FROM '
                                                           'public.builds native\n'
                                                           '   JOIN public.products source_product ON '
                                                           'source_product.tenant_id=native.tenant_id\n'
                                                           '    AND '
                                                           'source_product.category_id=native.category_id '
                                                           'AND source_product.id=native.product_id\n'
                                                           '   JOIN public.projects source_project ON '
                                                           'source_project.tenant_id=native.tenant_id\n'
                                                           '    AND '
                                                           'source_project.category_id=native.category_id '
                                                           'AND '
                                                           'source_project.product_id=native.product_id\n'
                                                           '    AND '
                                                           'source_project.id=native.project_id\n'
                                                           '   WHERE native.tenant_id=t AND '
                                                           'native.category_id=c AND '
                                                           "native.id::text=expected->>'row_id'\n"
                                                           '    AND '
                                                           "native.product_id::text=expected->>'product_id' "
                                                           'AND '
                                                           "native.project_id::text=expected->>'project_id'\n"
                                                           '    AND '
                                                           "native.revision::text=expected->>'revision'\n"
                                                           '    AND '
                                                           "native.id::text=expected->>'subject_id'\n"
                                                           '    AND '
                                                           "native.revision::text=expected->>'subject_revision'\n"
                                                           "    AND expected->>'operation' IN "
                                                           "('build.create')\n"
                                                           '    AND '
                                                           "expected->>'material_contract'='builds.fixed_fields/v1'\n"
                                                           '  ) INTO visible;\n'
                                                           '\n'
                                                           ' ELSIF '
                                                           "expected->>'table'='actual_configurations' "
                                                           'AND '
                                                           "expected->>'subject_type'='actual_configuration' "
                                                           'THEN\n'
                                                           '  SELECT EXISTS(SELECT 1 FROM '
                                                           'public.actual_configurations native\n'
                                                           '   JOIN public.products source_product ON '
                                                           'source_product.tenant_id=native.tenant_id\n'
                                                           '    AND '
                                                           'source_product.category_id=native.category_id '
                                                           'AND source_product.id=native.product_id\n'
                                                           '   JOIN public.projects source_project ON '
                                                           'source_project.tenant_id=native.tenant_id\n'
                                                           '    AND '
                                                           'source_project.category_id=native.category_id '
                                                           'AND '
                                                           'source_project.product_id=native.product_id\n'
                                                           '    AND '
                                                           'source_project.id=native.project_id\n'
                                                           '   WHERE native.tenant_id=t AND '
                                                           'native.category_id=c AND '
                                                           "native.id::text=expected->>'row_id'\n"
                                                           '    AND '
                                                           "native.product_id::text=expected->>'product_id' "
                                                           'AND '
                                                           "native.project_id::text=expected->>'project_id'\n"
                                                           '    AND '
                                                           "native.revision::text=expected->>'revision'\n"
                                                           '    AND '
                                                           "native.id::text=expected->>'subject_id'\n"
                                                           '    AND '
                                                           "native.revision::text=expected->>'subject_revision'\n"
                                                           "    AND expected->>'operation' IN "
                                                           "('build.configuration.actual.record')\n"
                                                           '    AND '
                                                           "expected->>'material_contract'='actual_configurations.fixed_fields/v1'\n"
                                                           '  ) INTO visible;\n'
                                                           '\n'
                                                           " ELSIF expected->>'table'='build_lots' AND "
                                                           "expected->>'subject_type'='build_lot' "
                                                           'THEN\n'
                                                           '  SELECT EXISTS(SELECT 1 FROM '
                                                           'public.build_lots native\n'
                                                           '   JOIN public.products source_product ON '
                                                           'source_product.tenant_id=native.tenant_id\n'
                                                           '    AND '
                                                           'source_product.category_id=native.category_id '
                                                           'AND source_product.id=native.product_id\n'
                                                           '   JOIN public.projects source_project ON '
                                                           'source_project.tenant_id=native.tenant_id\n'
                                                           '    AND '
                                                           'source_project.category_id=native.category_id '
                                                           'AND '
                                                           'source_project.product_id=native.product_id\n'
                                                           '    AND '
                                                           'source_project.id=native.project_id\n'
                                                           '   WHERE native.tenant_id=t AND '
                                                           'native.category_id=c AND '
                                                           "native.id::text=expected->>'row_id'\n"
                                                           '    AND '
                                                           "native.product_id::text=expected->>'product_id' "
                                                           'AND '
                                                           "native.project_id::text=expected->>'project_id'\n"
                                                           '    AND '
                                                           "native.revision::text=expected->>'revision'\n"
                                                           '    AND '
                                                           "native.id::text=expected->>'subject_id'\n"
                                                           '    AND '
                                                           "native.revision::text=expected->>'subject_revision'\n"
                                                           "    AND expected->>'operation' IN "
                                                           "('build.output.record')\n"
                                                           '    AND '
                                                           "expected->>'material_contract'='build_lots.fixed_fields/v1'\n"
                                                           '  ) INTO visible;\n'
                                                           '\n'
                                                           ' ELSIF '
                                                           "expected->>'table'='verification_run_versions' "
                                                           "AND expected->>'subject_type'='test_run' "
                                                           'THEN\n'
                                                           '  SELECT EXISTS(SELECT 1 FROM '
                                                           'public.verification_run_versions native\n'
                                                           '   JOIN public.products source_product ON '
                                                           'source_product.tenant_id=native.tenant_id\n'
                                                           '    AND '
                                                           'source_product.category_id=native.category_id '
                                                           'AND source_product.id=native.product_id\n'
                                                           '   JOIN public.projects source_project ON '
                                                           'source_project.tenant_id=native.tenant_id\n'
                                                           '    AND '
                                                           'source_project.category_id=native.category_id '
                                                           'AND '
                                                           'source_project.product_id=native.product_id\n'
                                                           '    AND '
                                                           'source_project.id=native.project_id\n'
                                                           '   WHERE native.tenant_id=t AND '
                                                           'native.category_id=c AND '
                                                           "native.id::text=expected->>'row_id'\n"
                                                           '    AND '
                                                           "native.product_id::text=expected->>'product_id' "
                                                           'AND '
                                                           "native.project_id::text=expected->>'project_id'\n"
                                                           '    AND '
                                                           "native.revision::text=expected->>'revision'\n"
                                                           '    AND '
                                                           "native.id::text=expected->>'subject_id'\n"
                                                           '    AND '
                                                           "native.revision::text=expected->>'subject_revision'\n"
                                                           "    AND expected->>'operation' IN "
                                                           "('test.run.plan','verification.schedule.promise','test.run.start','test.results.import','test.run.review','test.disposition.decide') "
                                                           'AND '
                                                           "native.operation=expected->>'operation'\n"
                                                           '    AND '
                                                           "expected->>'material_contract'='verification_run_versions.run_snapshot/v1' "
                                                           'AND '
                                                           "native.snapshot_sha256=expected->>'body_sha256'\n"
                                                           '  ) INTO visible;\n'
                                                           '\n'
                                                           ' ELSIF '
                                                           "expected->>'table'='quality_issue_versions' "
                                                           'AND '
                                                           "expected->>'subject_type'='quality_issue' "
                                                           'THEN\n'
                                                           '  SELECT EXISTS(SELECT 1 FROM '
                                                           'public.quality_issue_versions native\n'
                                                           '   JOIN public.products source_product ON '
                                                           'source_product.tenant_id=native.tenant_id\n'
                                                           '    AND '
                                                           'source_product.category_id=native.category_id '
                                                           'AND source_product.id=native.product_id\n'
                                                           '   JOIN public.projects source_project ON '
                                                           'source_project.tenant_id=native.tenant_id\n'
                                                           '    AND '
                                                           'source_project.category_id=native.category_id '
                                                           'AND '
                                                           'source_project.product_id=native.product_id\n'
                                                           '    AND '
                                                           'source_project.id=native.project_id\n'
                                                           '   WHERE native.tenant_id=t AND '
                                                           'native.category_id=c AND '
                                                           "native.id::text=expected->>'row_id'\n"
                                                           '    AND '
                                                           "native.product_id::text=expected->>'product_id' "
                                                           'AND '
                                                           "native.project_id::text=expected->>'project_id'\n"
                                                           '    AND '
                                                           "native.revision::text=expected->>'revision'\n"
                                                           '    AND '
                                                           "native.id::text=expected->>'subject_id'\n"
                                                           '    AND '
                                                           "native.revision::text=expected->>'subject_revision'\n"
                                                           "    AND expected->>'operation' IN "
                                                           "('quality.issue.create','quality.issue.merge','quality.issue.triage','quality.issue.containment.record','quality.capa.draft','quality.issue.root_cause.decide','quality.capa.actions.complete') "
                                                           'AND '
                                                           "native.operation=expected->>'operation'\n"
                                                           '    AND '
                                                           "expected->>'material_contract'='quality_issue_versions.issue_snapshot/v1' "
                                                           'AND '
                                                           "native.snapshot_sha256=expected->>'body_sha256'\n"
                                                           '  ) INTO visible;\n'
                                                           '\n'
                                                           ' ELSIF '
                                                           "expected->>'table'='change_request_versions' "
                                                           'AND '
                                                           "expected->>'subject_type'='change_request' "
                                                           'THEN\n'
                                                           '  SELECT EXISTS(SELECT 1 FROM '
                                                           'public.change_request_versions native\n'
                                                           '   JOIN public.products source_product ON '
                                                           'source_product.tenant_id=native.tenant_id\n'
                                                           '    AND '
                                                           'source_product.category_id=native.category_id '
                                                           'AND source_product.id=native.product_id\n'
                                                           '   JOIN public.projects source_project ON '
                                                           'source_project.tenant_id=native.tenant_id\n'
                                                           '    AND '
                                                           'source_project.category_id=native.category_id '
                                                           'AND '
                                                           'source_project.product_id=native.product_id\n'
                                                           '    AND '
                                                           'source_project.id=native.project_id\n'
                                                           '   WHERE native.tenant_id=t AND '
                                                           'native.category_id=c AND '
                                                           "native.id::text=expected->>'row_id'\n"
                                                           '    AND '
                                                           "native.product_id::text=expected->>'product_id' "
                                                           'AND '
                                                           "native.project_id::text=expected->>'project_id'\n"
                                                           '    AND '
                                                           "native.revision::text=expected->>'revision'\n"
                                                           '    AND '
                                                           "native.id::text=expected->>'subject_id'\n"
                                                           '    AND '
                                                           "native.revision::text=expected->>'subject_revision'\n"
                                                           "    AND expected->>'operation' IN "
                                                           "('change.request.create','change.impact.compute','change.order.prepare','change.order.approve','change.implementation.record') "
                                                           'AND '
                                                           "native.operation=expected->>'operation'\n"
                                                           '    AND '
                                                           "expected->>'material_contract'='change_request_versions.request_snapshot/v1' "
                                                           'AND '
                                                           "native.request_sha256=expected->>'body_sha256'\n"
                                                           '  ) INTO visible;\n'
                                                           '  ELSE RETURN false; END IF;\n'
                                                           '  IF visible IS DISTINCT FROM true OR NOT '
                                                           'public.knowledge_content_sources_visible(t,c,p,\n'
                                                           '   '
                                                           "jsonb_build_object('artifacts',expected->'artifacts')) "
                                                           'THEN RETURN false; END IF;\n'
                                                           ' END LOOP;\n'
                                                           ' RETURN true;\n'
                                                           'EXCEPTION WHEN invalid_text_representation '
                                                           'OR numeric_value_out_of_range THEN RETURN '
                                                           'false;\n'
                                                           'END;\n'
                                                           '$function$\n',
 'm3_lifecycle_nodes(uuid,uuid,uuid[])': 'CREATE OR REPLACE FUNCTION public.m3_lifecycle_nodes(t uuid, '
                                         'c uuid, identities uuid[] DEFAULT NULL::uuid[])\n'
                                         ' RETURNS TABLE(table_name text, node_id uuid, links uuid[])\n'
                                         ' LANGUAGE plpgsql\n'
                                         ' STABLE SECURITY DEFINER\n'
                                         " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                         'AS $function$\n'
                                         'DECLARE name text; payload jsonb; controls uuid[];\n'
                                         'BEGIN\n'
                                         ' IF identities IS NULL THEN\n'
                                         "  SELECT coalesce(array_agg(id),'{}') INTO controls FROM "
                                         'public.action_receipts\n'
                                         '   WHERE tenant_id=t AND category_id=c AND operation LIKE '
                                         "'evidence.lifecycle.%';\n"
                                         " ELSE controls='{}'; END IF;\n"
                                         ' FOREACH name IN ARRAY CASE WHEN identities IS NULL THEN '
                                         "ARRAY['agent_runs','action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','project_risk_followups','project_risk_followup_currents','knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents'] "
                                         'ELSE ARRAY[\n'
                                         '  '
                                         "'artifact_versions','claims','definition_revisions','definition_sources','definition_specs',\n"
                                         '  '
                                         "'proposals','proposal_items','proposal_item_versions','proposal_submissions','proposal_decisions',\n"
                                         '  '
                                         "'category_knowledge_entries','category_knowledge_current','parameter_versions','parameter_current',\n"
                                         '  '
                                         "'evidence_links','promotion_proofs','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','project_risk_followups','project_risk_followup_currents','knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents'] "
                                         'END LOOP\n'
                                         '  FOR payload IN EXECUTE CASE WHEN '
                                         "name=ANY(ARRAY['audit_entries','outbox_events','request_keys'])\n"
                                         "   THEN format('SELECT to_jsonb(x) FROM public.%I x JOIN "
                                         'public.action_receipts r ON r.id=x.receipt_id AND '
                                         'r.tenant_id=x.tenant_id WHERE x.tenant_id=$1 AND '
                                         "r.category_id=$2',name)\n"
                                         "   ELSE format('SELECT to_jsonb(x) FROM public.%I x WHERE "
                                         'tenant_id=$1 AND category_id=$2 AND ($3 IS NULL OR '
                                         "%I=ANY($3))',name,\n"
                                         "    CASE name WHEN 'category_knowledge_current' THEN "
                                         "'lineage_id'\n"
                                         "     WHEN 'parameter_current' THEN 'parameter_id' ELSE 'id' "
                                         'END)\n'
                                         '   END USING t,c,identities LOOP\n'
                                         "   IF (payload->>'receipt_id')::uuid=ANY(controls) OR\n"
                                         "    (name='action_receipts' AND payload->>'operation' LIKE "
                                         "'evidence.lifecycle.%') THEN CONTINUE; END IF;\n"
                                         '   table_name=name;\n'
                                         "   node_id=CASE name WHEN 'category_knowledge_current' THEN "
                                         "(payload->>'lineage_id')::uuid\n"
                                         "    WHEN 'parameter_current' THEN "
                                         "(payload->>'parameter_id')::uuid ELSE (payload->>'id')::uuid "
                                         'END;\n'
                                         '   IF identities IS NULL THEN '
                                         'links=public.m3_lifecycle_row_links(t,c,name,payload);\n'
                                         '   ELSE '
                                         'links=public.m3_lifecycle_source_links(t,c,name,payload); '
                                         'END IF;\n'
                                         "   -- Preserve predecessor's conservative legacy graph; "
                                         'M3-only nodes use\n'
                                         '   -- strictly typed/relational links. Root lookup never '
                                         'uses free-text UUIDs.\n'
                                         '   IF identities IS NULL AND '
                                         "name<>ALL(ARRAY['native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','project_risk_followups','project_risk_followup_currents','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents']) "
                                         'THEN\n'
                                         '    links=links || '
                                         'public.kernel_lifecycle_links(name,payload);\n'
                                         '   END IF;\n'
                                         '   RETURN NEXT;\n'
                                         '  END LOOP;\n'
                                         ' END LOOP;\n'
                                         'END;\n'
                                         '$function$\n',
 'm3_lifecycle_source_links(uuid,uuid,text,jsonb)': 'CREATE OR REPLACE FUNCTION '
                                                    'public.m3_lifecycle_source_links(t uuid, c uuid, '
                                                    'table_name text, payload jsonb)\n'
                                                    ' RETURNS uuid[]\n'
                                                    ' LANGUAGE plpgsql\n'
                                                    ' STABLE SECURITY DEFINER\n'
                                                    " SET search_path TO 'pg_catalog', 'public', "
                                                    "'pg_temp'\n"
                                                    'AS $function$\n'
                                                    "DECLARE links uuid[]='{}'; extra uuid[]; key "
                                                    'text; keys text[]; item jsonb; container jsonb;\n'
                                                    ' target_kind text; referenced_target uuid; '
                                                    'referenced_version integer;\n'
                                                    'BEGIN\n'
                                                    " IF table_name='agent_runs' THEN RETURN "
                                                    'public.kernel_lifecycle_links(table_name,payload); '
                                                    'END IF;\n'
                                                    ' -- Only actual top-level relation columns '
                                                    'establish raw UUID edges. Arbitrary\n'
                                                    ' -- content dictionaries are not relational rows, '
                                                    'even if an extra key happens\n'
                                                    ' -- to be named source_id or item_id.\n'
                                                    ' keys=CASE table_name\n'
                                                    "  WHEN 'artifact_versions' THEN "
                                                    "ARRAY['original_id']\n"
                                                    "  WHEN 'claims' THEN "
                                                    "ARRAY['artifact_id','snapshot_id']\n"
                                                    "  WHEN 'definition_revisions' THEN "
                                                    "ARRAY['derived_from_definition_id','parent_definition_id',\n"
                                                    "   'source_proposal_id','source_submission_id']\n"
                                                    "  WHEN 'definition_sources' THEN "
                                                    "ARRAY['artifact_id']\n"
                                                    "  WHEN 'definition_specs' THEN ARRAY[]::text[]\n"
                                                    "  WHEN 'proposals' THEN "
                                                    "ARRAY['baseline_definition_id','current_submission_id']\n"
                                                    "  WHEN 'proposal_items' THEN ARRAY[]::text[]\n"
                                                    "  WHEN 'proposal_item_versions' THEN "
                                                    'ARRAY[]::text[]\n'
                                                    "  WHEN 'proposal_revisions' THEN "
                                                    "ARRAY['proposal_id']\n"
                                                    "  WHEN 'proposal_sources' THEN "
                                                    "ARRAY['source_id']\n"
                                                    "  WHEN 'proposal_submissions' THEN "
                                                    'ARRAY[]::text[]\n'
                                                    "  WHEN 'proposal_decisions' THEN "
                                                    "ARRAY['submission_id']\n"
                                                    "  WHEN 'project_open_items' THEN "
                                                    "ARRAY['source_question_id','source_spec_item_id','g0_decision_id']\n"
                                                    "  WHEN 'category_knowledge_current' THEN "
                                                    "ARRAY['current_entry_id']\n"
                                                    "  WHEN 'promotion_proofs' THEN "
                                                    "ARRAY['knowledge_entry_id','source_proposal_id']\n"
                                                    "  WHEN 'evidence_links' THEN "
                                                    "ARRAY['evidence_id']\n"
                                                    "  WHEN 'claim_withdrawals' THEN "
                                                    "ARRAY['claim_id']\n"
                                                    "  WHEN 'manufacturing_baseline_publications' THEN "
                                                    "ARRAY['baseline_id','process_id','previous_id']\n"
                                                    "  WHEN 'manufacturing_publication_currents' THEN "
                                                    "ARRAY['version_id']\n"
                                                    "  WHEN 'manufacturing_publication_documents' THEN "
                                                    "ARRAY['document_id','process_id']\n"
                                                    "  WHEN 'native_pilot_runs' THEN "
                                                    "ARRAY['build_id','lot_id','actual_configuration_id','engineering_configuration_id','process_id','publication_id']\n"
                                                    "  WHEN 'native_pilot_currents' THEN "
                                                    "ARRAY['pilot_id','latest_observation_id']\n"
                                                    "  WHEN 'native_pilot_observations' THEN "
                                                    "ARRAY['pilot_id','previous_observation_id']\n"
                                                    "  WHEN 'release_packages' THEN "
                                                    "ARRAY['previous_id']\n"
                                                    "  WHEN 'release_package_currents' THEN "
                                                    "ARRAY['version_id']\n"
                                                    "  WHEN 'release_decisions' THEN "
                                                    "ARRAY['package_id']\n"
                                                    "  WHEN 'release_policy_facts' THEN "
                                                    "ARRAY['previous_id']\n"
                                                    "  WHEN 'release_policy_currents' THEN "
                                                    "ARRAY['fact_id']\n"
                                                    "  WHEN 'external_handoff_authorizations' THEN "
                                                    "ARRAY['package_id','engineering_decision_id','manufacturing_decision_id']\n"
                                                    "  WHEN 'external_delivery_intents' THEN "
                                                    "ARRAY['handoff_id']\n"
                                                    "  WHEN 'external_receipts' THEN "
                                                    "ARRAY['handoff_id','intent_id','previous_receipt_id','reconciles_id']\n"
                                                    "  WHEN 'external_handoff_currents' THEN "
                                                    "ARRAY['handoff_id','intent_id','latest_receipt_id']\n"
                                                    "  WHEN 'release_exception_decisions' THEN "
                                                    "ARRAY['basis_package_id','policy_fact_id','previous_id']\n"
                                                    "  WHEN 'release_exception_currents' THEN "
                                                    "ARRAY['basis_package_id','policy_fact_id','decision_id']\n"
                                                    "  WHEN 'work_commitment_reviews' THEN "
                                                    "ARRAY['commitment_id','task_version_id','submission_id','previous_id']\n"
                                                    "  WHEN 'work_commitment_review_currents' THEN "
                                                    "ARRAY['version_id']\n"
                                                    "  WHEN 'external_wait_versions' THEN "
                                                    "ARRAY['previous_id']\n"
                                                    "  WHEN 'external_wait_currents' THEN "
                                                    "ARRAY['version_id']\n"
                                                    "  WHEN 'project_risk_followups' THEN "
                                                    "ARRAY['previous_id','risk_id','g0_decision_id']\n"
                                                    "  WHEN 'project_risk_followup_currents' THEN "
                                                    "ARRAY['version_id']\n"
                                                    "  WHEN 'work_task_versions' THEN "
                                                    "ARRAY['previous_id']\n"
                                                    "  WHEN 'work_task_currents' THEN "
                                                    "ARRAY['version_id']\n"
                                                    "  WHEN 'work_commitment_versions' THEN "
                                                    "ARRAY['replaces_id']\n"
                                                    "  WHEN 'work_commitment_currents' THEN "
                                                    "ARRAY['version_id']\n"
                                                    "  WHEN 'project_status_updates' THEN "
                                                    'ARRAY[]::text[]\n'
                                                    '  ELSE ARRAY[]::text[] END;\n'
                                                    ' FOREACH key IN ARRAY keys LOOP\n'
                                                    '  IF payload->>key IS NOT NULL THEN '
                                                    'links=array_append(links,(payload->>key)::uuid); '
                                                    'END IF;\n'
                                                    ' END LOOP;\n'
                                                    " -- Publication's exact saved read set is a "
                                                    'validated Artifact relationship.\n'
                                                    ' -- Do not scan its declaration, body, reason or '
                                                    'arbitrary JSON UUID values.\n'
                                                    ' IF table_name IN '
                                                    "('manufacturing_baseline_publications','native_pilot_runs','native_pilot_observations','release_packages','release_decisions','release_policy_facts','external_handoff_authorizations','external_receipts','release_exception_decisions') "
                                                    'THEN\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload->'required_source_read_set','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'artifact_id' IS NOT NULL THEN\n"
                                                    '    '
                                                    "links=array_append(links,(item->>'artifact_id')::uuid);\n"
                                                    '   END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    ' IF table_name IN '
                                                    "('native_pilot_runs','native_pilot_observations') "
                                                    'THEN\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{material_snapshot,statistics,samples}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{material_snapshot,statistics,issues}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  '
                                                    "item=payload#>'{material_snapshot,statistics,resource,fact}';\n"
                                                    "  IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); "
                                                    'END IF;\n'
                                                    ' END IF;\n'
                                                    " IF table_name='release_packages' THEN\n"
                                                    '  -- FixedObject.ref is a closed, server-resolved '
                                                    'version reference, not arbitrary body UUID text.\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{body,objects}','[]')) "
                                                    'LOOP\n'
                                                    "   container=item->'ref';\n"
                                                    '   IF '
                                                    "container->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','manufacturing_publication','test_run','pilot_run','issue','change','exception','artifact','work_instruction','control_plan','build_lot','line'])\n"
                                                    "    AND container->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(container->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    ' IF table_name IN '
                                                    "('external_handoff_authorizations','external_delivery_intents') "
                                                    'THEN\n'
                                                    '  -- Only closed, owner-verified mapping and '
                                                    'manifest references are source edges.\n'
                                                    '  container=CASE WHEN '
                                                    "table_name='external_handoff_authorizations' THEN "
                                                    "payload#>'{body,declaration}' ELSE "
                                                    "payload->'body' END;\n"
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(container->'mappings','[]')) "
                                                    'LOOP\n'
                                                    '   IF '
                                                    "item->'ref'->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','part','bom_revision','artifact','work_instruction','control_plan'])\n"
                                                    "    AND item->'ref'->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->'ref'->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(container->'manifest','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->'artifact'->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->'artifact'->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    " IF table_name='release_policy_facts' THEN\n"
                                                    '  -- These are Closed DTO configuration '
                                                    'references fixed by the policy owner.\n'
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['definition','engineering_configuration','manufacturing_configuration'] "
                                                    'LOOP\n'
                                                    '   '
                                                    "container=payload#>ARRAY['material','subject_config',key];\n"
                                                    "   IF container->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(container->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    ' -- These stored fields are validated Reference '
                                                    'containers. Do not feed the\n'
                                                    ' -- whole row or arbitrary content into the '
                                                    'canonical Reference parser.\n'
                                                    ' IF '
                                                    "table_name=ANY(ARRAY['proposals','proposal_item_versions','proposal_submissions',\n"
                                                    '  '
                                                    "'category_knowledge_entries','definition_specs']) "
                                                    'THEN\n'
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['source_refs','direct_source_refs','context_refs','baseline_claim_refs'] "
                                                    'LOOP\n'
                                                    '   links=links || '
                                                    'public.m3_lifecycle_typed_links(t,c,payload->key);\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    ' -- Match ItemInput.content_schema and '
                                                    'category_service._references: only\n'
                                                    ' -- commercial_target, voice, and competitor have '
                                                    'nested source contracts.\n'
                                                    " IF table_name='proposal_item_versions' AND "
                                                    "payload->>'kind'='commercial_target' THEN\n"
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['target_price','cost','volume'] LOOP\n"
                                                    '   links=links || '
                                                    "public.m3_lifecycle_typed_links(t,c,payload->'content'->key->'source');\n"
                                                    '  END LOOP;\n'
                                                    " ELSIF table_name='category_knowledge_entries' "
                                                    "AND payload->>'kind'='voice' THEN\n"
                                                    '  links=links || '
                                                    "public.m3_lifecycle_typed_links(t,c,payload->'content'->'representative_refs');\n"
                                                    " ELSIF table_name='category_knowledge_entries' "
                                                    "AND payload->>'kind'='competitor' THEN\n"
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['metrics','features','prices'] LOOP\n"
                                                    '   FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload->'content'->key,'[]')) "
                                                    'LOOP\n'
                                                    '    links=links || '
                                                    "public.m3_lifecycle_typed_links(t,c,item->'source_ref');\n"
                                                    '   END LOOP;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    " IF table_name='proposal_submissions' THEN\n"
                                                    "  container=payload->'frozen_document';\n"
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['source_refs','direct_source_refs','context_refs','baseline_claim_refs'] "
                                                    'LOOP\n'
                                                    '   links=links || '
                                                    'public.m3_lifecycle_typed_links(t,c,container->key);\n'
                                                    '  END LOOP;\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(container->'items','[]')) "
                                                    'LOOP\n'
                                                    '   links=links || '
                                                    "public.m3_lifecycle_source_links(t,c,'proposal_item_versions',item-ARRAY['item_id','proposal_id']);\n"
                                                    '   -- The frozen read projection records actual '
                                                    'EvidenceLink provenance here.\n'
                                                    '   links=links || '
                                                    "public.m3_lifecycle_typed_links(t,c,item->'evidence_links');\n"
                                                    '  END LOOP;\n'
                                                    " ELSIF table_name='promotion_proofs' THEN\n"
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload->'source_item_refs','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'item_id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'item_id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    ' -- Exact persisted EvidenceLink targets '
                                                    'supplement these immutable versions.\n'
                                                    ' -- Reverted links and withdrawn Claims still '
                                                    'retain the original historical\n'
                                                    ' -- dependency; lifecycle cleanup must not erase '
                                                    'their audit source.\n'
                                                    " IF table_name='proposal_item_versions' AND "
                                                    "payload->>'item_id' IS NOT NULL THEN\n"
                                                    "  target_kind='proposal_item'; "
                                                    "referenced_target=(payload->>'item_id')::uuid;\n"
                                                    '  '
                                                    "referenced_version=(payload->>'version')::integer;\n"
                                                    " ELSIF table_name='category_knowledge_entries' "
                                                    "AND payload->>'id' IS NOT NULL THEN\n"
                                                    "  target_kind='knowledge_entry'; "
                                                    "referenced_target=(payload->>'id')::uuid;\n"
                                                    '  '
                                                    "referenced_version=(payload->>'version')::integer;\n"
                                                    " ELSIF table_name='definition_specs' AND "
                                                    "payload->>'id' IS NOT NULL THEN\n"
                                                    "  target_kind='definition_spec'; "
                                                    "referenced_target=(payload->>'id')::uuid;\n"
                                                    '  SELECT revision INTO referenced_version FROM '
                                                    'public.definition_revisions\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "id=(payload->>'definition_id')::uuid;\n"
                                                    ' END IF;\n'
                                                    ' IF referenced_target IS NOT NULL AND '
                                                    'referenced_version IS NOT NULL THEN\n'
                                                    '  SELECT '
                                                    "coalesce(array_agg(link.evidence_id),'{}') INTO "
                                                    'extra FROM public.evidence_links link\n'
                                                    '   WHERE link.tenant_id=t AND link.category_id=c '
                                                    'AND link.target_type=target_kind\n'
                                                    '    AND link.target_id=referenced_target AND '
                                                    'link.target_version=referenced_version;\n'
                                                    '  links=links || extra;\n'
                                                    ' END IF;\n'
                                                    ' -- Child source rows point to their parent, '
                                                    'whereas dependency traversal needs\n'
                                                    " -- the parent's fixed source children as well. "
                                                    'Keep the actual relational edge.\n'
                                                    " IF table_name='definition_revisions' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO extra "
                                                    'FROM (\n'
                                                    '   SELECT id FROM public.definition_sources WHERE '
                                                    'tenant_id=t AND category_id=c\n'
                                                    "    AND definition_id=(payload->>'id')::uuid\n"
                                                    '   UNION ALL SELECT id FROM '
                                                    'public.definition_specs WHERE tenant_id=t AND '
                                                    'category_id=c\n'
                                                    "    AND definition_id=(payload->>'id')::uuid\n"
                                                    '  ) children;\n'
                                                    '  links=links || extra;\n'
                                                    " ELSIF table_name='proposals' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO extra "
                                                    'FROM public.proposal_item_versions\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "proposal_id=(payload->>'id')::uuid;\n"
                                                    '  links=links || extra;\n'
                                                    " ELSIF table_name='proposal_items' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO extra "
                                                    'FROM public.proposal_item_versions\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "item_id=(payload->>'id')::uuid;\n"
                                                    '  links=links || extra;\n'
                                                    " ELSIF table_name='product_target_segments' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO extra "
                                                    'FROM public.category_knowledge_entries\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "lineage_id=(payload->>'segment_lineage_id')::uuid\n"
                                                    '    AND '
                                                    "version=(payload->>'segment_version')::integer;\n"
                                                    '  links=links || extra;\n'
                                                    " ELSIF table_name='parameter_current' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO extra "
                                                    'FROM public.parameter_versions\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "parameter_id=(payload->>'parameter_id')::uuid\n"
                                                    '    AND '
                                                    "version=(payload->>'current_version')::integer;\n"
                                                    '  links=links || extra;\n'
                                                    ' END IF;\n'
                                                    '\n'
                                                    ' IF table_name IN '
                                                    "('work_task_versions','work_commitment_versions','project_status_updates') "
                                                    'THEN\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload->'reads','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'artifact_id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'artifact_id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    "  IF table_name='work_task_versions' AND "
                                                    "payload#>>'{body,plan_task,id}' IS NOT NULL THEN\n"
                                                    '   '
                                                    "links=array_append(links,(payload#>>'{body,plan_task,id}')::uuid);\n"
                                                    '  END IF;\n'
                                                    "  IF table_name='work_commitment_versions' THEN\n"
                                                    "   SELECT coalesce(array_agg(id),'{}') INTO extra "
                                                    'FROM public.work_task_versions\n'
                                                    '    WHERE tenant_id=t AND category_id=c AND '
                                                    "task_id=(payload->>'task_id')::uuid AND "
                                                    "revision=(payload->>'task_revision')::integer;\n"
                                                    '   links=links||extra;\n'
                                                    "  ELSIF table_name='project_status_updates' THEN\n"
                                                    '   FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload->'task_refs','[]')) "
                                                    'LOOP\n'
                                                    "    SELECT coalesce(array_agg(id),'{}') INTO "
                                                    'extra FROM public.work_task_versions\n'
                                                    '     WHERE tenant_id=t AND category_id=c AND '
                                                    "task_id=(item->>'id')::uuid AND "
                                                    "revision=(item->>'revision')::integer;\n"
                                                    '    links=links||extra;\n'
                                                    '   END LOOP;\n'
                                                    '  END IF;\n'
                                                    ' END IF;\n'
                                                    '\n'
                                                    " IF table_name='work_commitment_reviews' THEN\n"
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload->'reads','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'artifact_id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'artifact_id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    '\n'
                                                    " IF table_name='external_wait_versions' THEN\n"
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['milestone','build','calendar'] LOOP\n"
                                                    "   container=payload#>ARRAY['body',key];\n"
                                                    "   IF container->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(container->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    "  container=payload#>'{body,replaces}';\n"
                                                    "  IF container->>'id' IS NOT NULL THEN\n"
                                                    "   SELECT coalesce(array_agg(id),'{}') INTO extra "
                                                    'FROM public.external_wait_versions\n'
                                                    '    WHERE tenant_id=t AND category_id=c AND '
                                                    "wait_id=(container->>'id')::uuid AND "
                                                    "revision=(container->>'revision')::integer;\n"
                                                    '   links=links||extra;\n'
                                                    '  END IF;\n'
                                                    ' END IF;\n'
                                                    " IF table_name='project_risk_followups' THEN\n"
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    '\n'
                                                    ' IF table_name IN '
                                                    "('knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents') "
                                                    'THEN\n'
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['previous_id','version_id','candidate_version_id','assessment_id','publication_id'] "
                                                    'LOOP\n'
                                                    '   IF payload->>key IS NOT NULL THEN '
                                                    'links=array_append(links,(payload->>key)::uuid); '
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload->'reads','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'artifact_id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'artifact_id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{source_basis,result_receipts}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'receipt_id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'receipt_id')::uuid); "
                                                    'END IF;\n'
                                                    "   IF item->>'row_id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'row_id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{source_basis,professional,fact_refs}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    "  IF payload#>>'{source_basis,target,id}' IS NOT "
                                                    'NULL THEN '
                                                    "links=array_append(links,(payload#>>'{source_basis,target,id}')::uuid); "
                                                    'END IF;\n'
                                                    ' END IF;\n'
                                                    ' RETURN links;\n'
                                                    'END;\n'
                                                    '$function$\n',
 'm3_lifecycle_row_links(uuid,uuid,text,jsonb)': 'CREATE OR REPLACE FUNCTION '
                                                 'public.m3_lifecycle_row_links(t uuid, c uuid, '
                                                 'table_name text, payload jsonb)\n'
                                                 ' RETURNS uuid[]\n'
                                                 ' LANGUAGE plpgsql\n'
                                                 ' STABLE SECURITY DEFINER\n'
                                                 " SET search_path TO 'pg_catalog', 'public', "
                                                 "'pg_temp'\n"
                                                 'AS $function$\n'
                                                 'DECLARE links uuid[]; key text; keys text[];\n'
                                                 'BEGIN\n'
                                                 ' '
                                                 'links=public.m3_lifecycle_source_links(t,c,table_name,payload);\n'
                                                 ' -- Only the infrequent retention summary needs '
                                                 'host/reverse relationships.\n'
                                                 ' -- They must not turn a source-free item INSERT '
                                                 'into a proposal-history scan.\n'
                                                 ' keys=CASE table_name\n'
                                                 "  WHEN 'definition_sources' THEN "
                                                 "ARRAY['definition_id']\n"
                                                 "  WHEN 'definition_specs' THEN "
                                                 "ARRAY['definition_id']\n"
                                                 "  WHEN 'proposal_items' THEN ARRAY['proposal_id']\n"
                                                 "  WHEN 'proposal_item_versions' THEN "
                                                 "ARRAY['proposal_id','item_id']\n"
                                                 "  WHEN 'proposal_sources' THEN ARRAY['proposal_id']\n"
                                                 "  WHEN 'proposal_submissions' THEN "
                                                 "ARRAY['proposal_id']\n"
                                                 "  WHEN 'proposal_decisions' THEN "
                                                 "ARRAY['proposal_id','created_definition_id']\n"
                                                 "  WHEN 'evidence_links' THEN ARRAY['target_id']\n"
                                                 "  WHEN 'manufacturing_baseline_publications' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'manufacturing_publication_currents' THEN "
                                                 "ARRAY['series_id']\n"
                                                 "  WHEN 'manufacturing_publication_documents' THEN "
                                                 "ARRAY['publication_id']\n"
                                                 "  WHEN 'native_pilot_runs' THEN ARRAY['project_id']\n"
                                                 "  WHEN 'native_pilot_currents' THEN "
                                                 "ARRAY['pilot_id']\n"
                                                 "  WHEN 'native_pilot_observations' THEN "
                                                 "ARRAY['pilot_id']\n"
                                                 "  WHEN 'release_packages' THEN "
                                                 "ARRAY['project_id','series_id']\n"
                                                 "  WHEN 'release_package_currents' THEN "
                                                 "ARRAY['series_id']\n"
                                                 "  WHEN 'release_decisions' THEN ARRAY['package_id']\n"
                                                 "  WHEN 'release_policy_facts' THEN "
                                                 "ARRAY['project_id','series_id']\n"
                                                 "  WHEN 'release_policy_currents' THEN "
                                                 "ARRAY['series_id']\n"
                                                 "  WHEN 'external_handoff_authorizations' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'external_delivery_intents' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'external_receipts' THEN ARRAY['project_id']\n"
                                                 "  WHEN 'external_handoff_currents' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'release_exception_decisions' THEN "
                                                 "ARRAY['project_id','series_id']\n"
                                                 "  WHEN 'release_exception_currents' THEN "
                                                 "ARRAY['project_id','series_id']\n"
                                                 "  WHEN 'work_commitment_reviews' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'work_commitment_review_currents' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'external_wait_versions' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'external_wait_currents' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'project_risk_followups' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'knowledge_candidate_versions' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'knowledge_candidate_currents' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'knowledge_applicability_assessments' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'knowledge_rule_versions' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'knowledge_rule_currents' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'project_risk_followup_currents' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'work_task_versions' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'work_task_currents' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'work_commitment_versions' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'work_commitment_currents' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'project_status_updates' THEN "
                                                 "ARRAY['project_id']\n"
                                                 '  ELSE ARRAY[]::text[] END;\n'
                                                 ' FOREACH key IN ARRAY keys LOOP\n'
                                                 '  IF payload->>key IS NOT NULL THEN '
                                                 'links=array_append(links,(payload->>key)::uuid); END '
                                                 'IF;\n'
                                                 ' END LOOP;\n'
                                                 ' RETURN links;\n'
                                                 'END;\n'
                                                 '$function$\n'}

SCHEMA_SQL = ('CREATE FUNCTION public.knowledge_content_sources_visible(t uuid,c uuid,p uuid,basis jsonb) RETURNS '
 'boolean\n'
 'LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog,public,pg_temp AS '
 '$knowledge_provenance$\n'
 'DECLARE expected jsonb; actual_product uuid; original_id uuid; found_source boolean;\n'
 'BEGIN\n'
 " IF t IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid\n"
 "  OR NOT public.category_access(t,c) OR jsonb_typeof(basis) IS DISTINCT FROM 'object'\n"
 "  OR jsonb_typeof(basis->'artifacts') IS DISTINCT FROM 'array' THEN RETURN false; END IF;\n"
 " FOR expected IN SELECT value FROM jsonb_array_elements(basis->'artifacts') LOOP\n"
 "  IF jsonb_typeof(expected) IS DISTINCT FROM 'object' OR NOT(expected ? 'product_id')\n"
 "   OR expected->>'category_id' IS DISTINCT FROM c::text THEN RETURN false; END IF;\n"
 '  SELECT a.product_id,a.original_id,true INTO actual_product,original_id,found_source\n'
 '   FROM public.artifact_versions a WHERE a.tenant_id=t AND a.category_id=c\n'
 "    AND a.id::text=expected->>'id' AND a.product_id::text IS NOT DISTINCT FROM "
 "expected->>'product_id';\n"
 '  IF found_source IS DISTINCT FROM true THEN RETURN false; END IF;\n'
 '  IF actual_product IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.products source_product\n'
 '    WHERE source_product.tenant_id=t AND source_product.category_id=c AND '
 'source_product.id=actual_product) THEN RETURN false; END IF;\n'
 '  IF original_id IS NOT NULL THEN\n'
 "   IF original_id::text IS DISTINCT FROM expected->'original'->>'id'\n"
 '    OR NOT EXISTS(SELECT 1 FROM public.uploaded_originals o WHERE o.tenant_id=t AND o.category_id=c\n'
 '     AND o.product_id IS NOT DISTINCT FROM actual_product AND o.id=original_id) THEN RETURN false; '
 'END IF;\n'
 '  END IF;\n'
 ' END LOOP;\n'
 ' RETURN true;\n'
 'EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN RETURN false;\n'
 'END;\n'
 '$knowledge_provenance$',
 'CREATE FUNCTION public.knowledge_result_sources_visible(t uuid,c uuid,p uuid,basis jsonb) RETURNS '
 'boolean\n'
 'LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog,public,pg_temp AS '
 '$knowledge_provenance$\n'
 '\n'
 'DECLARE expected jsonb; visible boolean;\n'
 'BEGIN\n'
 " IF t IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid\n"
 "  OR NOT public.category_access(t,c) OR jsonb_typeof(basis) IS DISTINCT FROM 'object'\n"
 "  OR jsonb_typeof(basis->'result_receipts') IS DISTINCT FROM 'array' THEN RETURN false; END IF;\n"
 " FOR expected IN SELECT value FROM jsonb_array_elements(basis->'result_receipts') LOOP\n"
 "  IF jsonb_typeof(expected) IS DISTINCT FROM 'object' OR expected->>'category_id' IS DISTINCT FROM "
 'c::text THEN RETURN false;\n'
 '\n'
 " ELSIF expected->>'table'='builds' AND expected->>'subject_type'='build' THEN\n"
 '  SELECT EXISTS(SELECT 1 FROM public.builds native\n'
 '   JOIN public.products source_product ON source_product.tenant_id=native.tenant_id\n'
 '    AND source_product.category_id=native.category_id AND source_product.id=native.product_id\n'
 '   JOIN public.projects source_project ON source_project.tenant_id=native.tenant_id\n'
 '    AND source_project.category_id=native.category_id AND '
 'source_project.product_id=native.product_id\n'
 '    AND source_project.id=native.project_id\n'
 "   WHERE native.tenant_id=t AND native.category_id=c AND native.id::text=expected->>'row_id'\n"
 "    AND native.product_id::text=expected->>'product_id' AND "
 "native.project_id::text=expected->>'project_id'\n"
 "    AND native.revision::text=expected->>'revision'\n"
 "    AND native.id::text=expected->>'subject_id'\n"
 "    AND native.revision::text=expected->>'subject_revision'\n"
 "    AND expected->>'operation' IN ('build.create')\n"
 "    AND expected->>'material_contract'='builds.fixed_fields/v1'\n"
 '  ) INTO visible;\n'
 '\n'
 " ELSIF expected->>'table'='actual_configurations' AND "
 "expected->>'subject_type'='actual_configuration' THEN\n"
 '  SELECT EXISTS(SELECT 1 FROM public.actual_configurations native\n'
 '   JOIN public.products source_product ON source_product.tenant_id=native.tenant_id\n'
 '    AND source_product.category_id=native.category_id AND source_product.id=native.product_id\n'
 '   JOIN public.projects source_project ON source_project.tenant_id=native.tenant_id\n'
 '    AND source_project.category_id=native.category_id AND '
 'source_project.product_id=native.product_id\n'
 '    AND source_project.id=native.project_id\n'
 "   WHERE native.tenant_id=t AND native.category_id=c AND native.id::text=expected->>'row_id'\n"
 "    AND native.product_id::text=expected->>'product_id' AND "
 "native.project_id::text=expected->>'project_id'\n"
 "    AND native.revision::text=expected->>'revision'\n"
 "    AND native.id::text=expected->>'subject_id'\n"
 "    AND native.revision::text=expected->>'subject_revision'\n"
 "    AND expected->>'operation' IN ('build.configuration.actual.record')\n"
 "    AND expected->>'material_contract'='actual_configurations.fixed_fields/v1'\n"
 '  ) INTO visible;\n'
 '\n'
 " ELSIF expected->>'table'='build_lots' AND expected->>'subject_type'='build_lot' THEN\n"
 '  SELECT EXISTS(SELECT 1 FROM public.build_lots native\n'
 '   JOIN public.products source_product ON source_product.tenant_id=native.tenant_id\n'
 '    AND source_product.category_id=native.category_id AND source_product.id=native.product_id\n'
 '   JOIN public.projects source_project ON source_project.tenant_id=native.tenant_id\n'
 '    AND source_project.category_id=native.category_id AND '
 'source_project.product_id=native.product_id\n'
 '    AND source_project.id=native.project_id\n'
 "   WHERE native.tenant_id=t AND native.category_id=c AND native.id::text=expected->>'row_id'\n"
 "    AND native.product_id::text=expected->>'product_id' AND "
 "native.project_id::text=expected->>'project_id'\n"
 "    AND native.revision::text=expected->>'revision'\n"
 "    AND native.id::text=expected->>'subject_id'\n"
 "    AND native.revision::text=expected->>'subject_revision'\n"
 "    AND expected->>'operation' IN ('build.output.record')\n"
 "    AND expected->>'material_contract'='build_lots.fixed_fields/v1'\n"
 '  ) INTO visible;\n'
 '\n'
 " ELSIF expected->>'table'='verification_run_versions' AND expected->>'subject_type'='test_run' THEN\n"
 '  SELECT EXISTS(SELECT 1 FROM public.verification_run_versions native\n'
 '   JOIN public.products source_product ON source_product.tenant_id=native.tenant_id\n'
 '    AND source_product.category_id=native.category_id AND source_product.id=native.product_id\n'
 '   JOIN public.projects source_project ON source_project.tenant_id=native.tenant_id\n'
 '    AND source_project.category_id=native.category_id AND '
 'source_project.product_id=native.product_id\n'
 '    AND source_project.id=native.project_id\n'
 "   WHERE native.tenant_id=t AND native.category_id=c AND native.id::text=expected->>'row_id'\n"
 "    AND native.product_id::text=expected->>'product_id' AND "
 "native.project_id::text=expected->>'project_id'\n"
 "    AND native.revision::text=expected->>'revision'\n"
 "    AND native.id::text=expected->>'subject_id'\n"
 "    AND native.revision::text=expected->>'subject_revision'\n"
 "    AND expected->>'operation' IN "
 "('test.run.plan','verification.schedule.promise','test.run.start','test.results.import','test.run.review','test.disposition.decide') "
 "AND native.operation=expected->>'operation'\n"
 "    AND expected->>'material_contract'='verification_run_versions.run_snapshot/v1' AND "
 "native.snapshot_sha256=expected->>'body_sha256'\n"
 '  ) INTO visible;\n'
 '\n'
 " ELSIF expected->>'table'='quality_issue_versions' AND expected->>'subject_type'='quality_issue' "
 'THEN\n'
 '  SELECT EXISTS(SELECT 1 FROM public.quality_issue_versions native\n'
 '   JOIN public.products source_product ON source_product.tenant_id=native.tenant_id\n'
 '    AND source_product.category_id=native.category_id AND source_product.id=native.product_id\n'
 '   JOIN public.projects source_project ON source_project.tenant_id=native.tenant_id\n'
 '    AND source_project.category_id=native.category_id AND '
 'source_project.product_id=native.product_id\n'
 '    AND source_project.id=native.project_id\n'
 "   WHERE native.tenant_id=t AND native.category_id=c AND native.id::text=expected->>'row_id'\n"
 "    AND native.product_id::text=expected->>'product_id' AND "
 "native.project_id::text=expected->>'project_id'\n"
 "    AND native.revision::text=expected->>'revision'\n"
 "    AND native.id::text=expected->>'subject_id'\n"
 "    AND native.revision::text=expected->>'subject_revision'\n"
 "    AND expected->>'operation' IN "
 "('quality.issue.create','quality.issue.merge','quality.issue.triage','quality.issue.containment.record','quality.capa.draft','quality.issue.root_cause.decide','quality.capa.actions.complete') "
 "AND native.operation=expected->>'operation'\n"
 "    AND expected->>'material_contract'='quality_issue_versions.issue_snapshot/v1' AND "
 "native.snapshot_sha256=expected->>'body_sha256'\n"
 '  ) INTO visible;\n'
 '\n'
 " ELSIF expected->>'table'='change_request_versions' AND expected->>'subject_type'='change_request' "
 'THEN\n'
 '  SELECT EXISTS(SELECT 1 FROM public.change_request_versions native\n'
 '   JOIN public.products source_product ON source_product.tenant_id=native.tenant_id\n'
 '    AND source_product.category_id=native.category_id AND source_product.id=native.product_id\n'
 '   JOIN public.projects source_project ON source_project.tenant_id=native.tenant_id\n'
 '    AND source_project.category_id=native.category_id AND '
 'source_project.product_id=native.product_id\n'
 '    AND source_project.id=native.project_id\n'
 "   WHERE native.tenant_id=t AND native.category_id=c AND native.id::text=expected->>'row_id'\n"
 "    AND native.product_id::text=expected->>'product_id' AND "
 "native.project_id::text=expected->>'project_id'\n"
 "    AND native.revision::text=expected->>'revision'\n"
 "    AND native.id::text=expected->>'subject_id'\n"
 "    AND native.revision::text=expected->>'subject_revision'\n"
 "    AND expected->>'operation' IN "
 "('change.request.create','change.impact.compute','change.order.prepare','change.order.approve','change.implementation.record') "
 "AND native.operation=expected->>'operation'\n"
 "    AND expected->>'material_contract'='change_request_versions.request_snapshot/v1' AND "
 "native.request_sha256=expected->>'body_sha256'\n"
 '  ) INTO visible;\n'
 '  ELSE RETURN false; END IF;\n'
 '  IF visible IS DISTINCT FROM true OR NOT public.knowledge_content_sources_visible(t,c,p,\n'
 "   jsonb_build_object('artifacts',expected->'artifacts')) THEN RETURN false; END IF;\n"
 ' END LOOP;\n'
 ' RETURN true;\n'
 'EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN RETURN false;\n'
 'END;\n'
 '$knowledge_provenance$',
 'REVOKE ALL ON FUNCTION '
 'public.knowledge_content_sources_visible(uuid,uuid,uuid,jsonb),public.knowledge_result_sources_visible(uuid,uuid,uuid,jsonb) '
 'FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'GRANT EXECUTE ON FUNCTION '
 'public.knowledge_content_sources_visible(uuid,uuid,uuid,jsonb),public.knowledge_result_sources_visible(uuid,uuid,uuid,jsonb) '
 'TO pdos_next_app',
 '\n'
 'CREATE TABLE knowledge_candidate_versions (\n'
 '\tcandidate_id UUID NOT NULL, \n'
 '\tprevious_id UUID, \n'
 '\tprevious_revision INTEGER, \n'
 '\trevision INTEGER NOT NULL, \n'
 '\twriter_id UUID NOT NULL, \n'
 '\tactor_id UUID NOT NULL, \n'
 '\trequester_id UUID NOT NULL, \n'
 '\toperation VARCHAR(80) NOT NULL, \n'
 '\tcommand_id UUID NOT NULL, \n'
 '\tcommand JSONB NOT NULL, \n'
 '\tsources JSONB NOT NULL, \n'
 '\treads JSONB NOT NULL, \n'
 '\tsource_basis JSONB NOT NULL, \n'
 '\tbody JSONB NOT NULL, \n'
 '\tbody_sha256 VARCHAR(64) NOT NULL, \n'
 '\tintent_digest VARCHAR(64) NOT NULL, \n'
 '\trequest_digest VARCHAR(64) NOT NULL, \n'
 '\treceipt_id UUID NOT NULL, \n'
 '\tconfirmation_id UUID, \n'
 '\tcategory_id UUID NOT NULL, \n'
 '\tproduct_id UUID, \n'
 '\tproject_id UUID, \n'
 '\towner_id UUID NOT NULL, \n'
 '\tvisibility VARCHAR(16) NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(tenant_id, category_id) REFERENCES categories (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, category_id, product_id) REFERENCES products (tenant_id, category_id, '
 'id), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id) REFERENCES projects (tenant_id, product_id, id), \n'
 '\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n'
 "\tCHECK (visibility IN ('private','category')), \n"
 '\tCHECK (project_id IS NULL OR product_id IS NOT NULL), \n'
 '\tUNIQUE (tenant_id, id), \n'
 '\tUNIQUE (tenant_id, category_id, id, revision), \n'
 '\tUNIQUE (tenant_id, receipt_id), \n'
 '\tUNIQUE (tenant_id, command_id), \n'
 '\tUNIQUE (tenant_id, category_id, actor_id, operation, intent_digest), \n'
 '\tFOREIGN KEY(tenant_id, writer_id) REFERENCES principals (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, actor_id) REFERENCES principals (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, requester_id) REFERENCES principals (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, receipt_id) REFERENCES action_receipts (tenant_id, id) DEFERRABLE INITIALLY '
 'DEFERRED, \n'
 '\tFOREIGN KEY(tenant_id, confirmation_id) REFERENCES confirmations (tenant_id, id) DEFERRABLE '
 'INITIALLY DEFERRED, \n'
 '\tCHECK (writer_id=actor_id AND revision>0), \n'
 "\tCHECK (jsonb_typeof(command)='object' AND jsonb_typeof(body)='object' AND "
 "jsonb_typeof(source_basis)='object' AND jsonb_typeof(sources)='array' AND "
 "jsonb_typeof(reads)='array' AND jsonb_array_length(sources)>0 AND jsonb_array_length(reads)>0), \n"
 "\tCHECK (body_sha256 ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$' AND intent_digest ~ "
 "'^[a-f0-9]{64}$'), \n"
 '\tUNIQUE (tenant_id, category_id, candidate_id, revision), \n'
 '\tUNIQUE (tenant_id, category_id, candidate_id, id, revision), \n'
 '\tFOREIGN KEY(tenant_id, category_id, candidate_id, previous_id, previous_revision) REFERENCES '
 'knowledge_candidate_versions (tenant_id, category_id, candidate_id, id, revision), \n'
 '\tCONSTRAINT knowledge_candidate_chain CHECK ((revision=1 AND candidate_id=id AND previous_id IS '
 'NULL AND previous_revision IS NULL) OR (revision>1 AND previous_id IS NOT NULL AND previous_id<>id '
 'AND previous_revision=revision-1)), \n'
 "\tCONSTRAINT knowledge_candidate_t0_only CHECK (operation='knowledge.candidate.create' AND "
 'confirmation_id IS NULL)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_knowledge_candidate_versions_category_id ON knowledge_candidate_versions '
 '(category_id)',
 'CREATE INDEX ix_knowledge_candidate_versions_tenant_id ON knowledge_candidate_versions (tenant_id)',
 '\n'
 'CREATE TABLE knowledge_candidate_currents (\n'
 '\tcandidate_id UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\trevision INTEGER NOT NULL, \n'
 '\tcategory_id UUID NOT NULL, \n'
 '\tproduct_id UUID, \n'
 '\tproject_id UUID, \n'
 '\towner_id UUID NOT NULL, \n'
 '\tvisibility VARCHAR(16) NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(tenant_id, category_id) REFERENCES categories (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, category_id, product_id) REFERENCES products (tenant_id, category_id, '
 'id), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id) REFERENCES projects (tenant_id, product_id, id), \n'
 '\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n'
 "\tCHECK (visibility IN ('private','category')), \n"
 '\tCHECK (project_id IS NULL OR product_id IS NOT NULL), \n'
 '\tUNIQUE (tenant_id, category_id, candidate_id), \n'
 '\tFOREIGN KEY(tenant_id, category_id, candidate_id, version_id, revision) REFERENCES '
 'knowledge_candidate_versions (tenant_id, category_id, candidate_id, id, revision), \n'
 '\tCONSTRAINT knowledge_candidate_current_revision CHECK (revision>0)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_knowledge_candidate_currents_category_id ON knowledge_candidate_currents '
 '(category_id)',
 'CREATE INDEX ix_knowledge_candidate_currents_tenant_id ON knowledge_candidate_currents (tenant_id)',
 '\n'
 'CREATE TABLE knowledge_applicability_assessments (\n'
 '\tpublication_id UUID NOT NULL, \n'
 '\tcandidate_version_id UUID NOT NULL, \n'
 '\tcandidate_revision INTEGER NOT NULL, \n'
 '\tactor_id UUID NOT NULL, \n'
 '\tbody JSONB NOT NULL, \n'
 '\tbody_sha256 VARCHAR(64) NOT NULL, \n'
 '\treceipt_id UUID NOT NULL, \n'
 '\tcategory_id UUID NOT NULL, \n'
 '\tproduct_id UUID, \n'
 '\tproject_id UUID, \n'
 '\towner_id UUID NOT NULL, \n'
 '\tvisibility VARCHAR(16) NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(tenant_id, category_id) REFERENCES categories (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, category_id, product_id) REFERENCES products (tenant_id, category_id, '
 'id), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id) REFERENCES projects (tenant_id, product_id, id), \n'
 '\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n'
 "\tCHECK (visibility IN ('private','category')), \n"
 '\tCHECK (project_id IS NULL OR product_id IS NOT NULL), \n'
 '\tUNIQUE (tenant_id, id), \n'
 '\tUNIQUE (tenant_id, publication_id), \n'
 '\tUNIQUE (tenant_id, id, publication_id), \n'
 '\tFOREIGN KEY(tenant_id, category_id, candidate_version_id, candidate_revision) REFERENCES '
 'knowledge_candidate_versions (tenant_id, category_id, id, revision), \n'
 '\tFOREIGN KEY(tenant_id, actor_id) REFERENCES principals (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, receipt_id) REFERENCES action_receipts (tenant_id, id) DEFERRABLE INITIALLY '
 'DEFERRED, \n'
 '\tCONSTRAINT knowledge_assessment_fixed_scope CHECK (product_id IS NOT NULL AND project_id IS NOT '
 "NULL AND candidate_revision>0 AND jsonb_typeof(body)='object' AND body_sha256 ~ '^[a-f0-9]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_knowledge_applicability_assessments_category_id ON '
 'knowledge_applicability_assessments (category_id)',
 'CREATE INDEX ix_knowledge_applicability_assessments_tenant_id ON knowledge_applicability_assessments '
 '(tenant_id)',
 '\n'
 'CREATE TABLE knowledge_rule_versions (\n'
 '\trule_id UUID NOT NULL, \n'
 '\tcandidate_id UUID NOT NULL, \n'
 '\tcandidate_version_id UUID NOT NULL, \n'
 '\tcandidate_revision INTEGER NOT NULL, \n'
 '\tprevious_id UUID, \n'
 '\tprevious_revision INTEGER, \n'
 '\tassessment_id UUID NOT NULL, \n'
 '\tnature VARCHAR(16) NOT NULL, \n'
 '\tvalid_from TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tvalid_until TIMESTAMP WITH TIME ZONE, \n'
 '\trevision INTEGER NOT NULL, \n'
 '\twriter_id UUID NOT NULL, \n'
 '\tactor_id UUID NOT NULL, \n'
 '\trequester_id UUID NOT NULL, \n'
 '\toperation VARCHAR(80) NOT NULL, \n'
 '\tcommand_id UUID NOT NULL, \n'
 '\tcommand JSONB NOT NULL, \n'
 '\tsources JSONB NOT NULL, \n'
 '\treads JSONB NOT NULL, \n'
 '\tsource_basis JSONB NOT NULL, \n'
 '\tbody JSONB NOT NULL, \n'
 '\tbody_sha256 VARCHAR(64) NOT NULL, \n'
 '\tintent_digest VARCHAR(64) NOT NULL, \n'
 '\trequest_digest VARCHAR(64) NOT NULL, \n'
 '\treceipt_id UUID NOT NULL, \n'
 '\tconfirmation_id UUID, \n'
 '\tcategory_id UUID NOT NULL, \n'
 '\tproduct_id UUID, \n'
 '\tproject_id UUID, \n'
 '\towner_id UUID NOT NULL, \n'
 '\tvisibility VARCHAR(16) NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(tenant_id, category_id) REFERENCES categories (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, category_id, product_id) REFERENCES products (tenant_id, category_id, '
 'id), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id) REFERENCES projects (tenant_id, product_id, id), \n'
 '\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n'
 "\tCHECK (visibility IN ('private','category')), \n"
 '\tCHECK (project_id IS NULL OR product_id IS NOT NULL), \n'
 '\tUNIQUE (tenant_id, id), \n'
 '\tUNIQUE (tenant_id, category_id, id, revision), \n'
 '\tUNIQUE (tenant_id, receipt_id), \n'
 '\tUNIQUE (tenant_id, command_id), \n'
 '\tUNIQUE (tenant_id, category_id, actor_id, operation, intent_digest), \n'
 '\tFOREIGN KEY(tenant_id, writer_id) REFERENCES principals (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, actor_id) REFERENCES principals (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, requester_id) REFERENCES principals (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, receipt_id) REFERENCES action_receipts (tenant_id, id) DEFERRABLE INITIALLY '
 'DEFERRED, \n'
 '\tFOREIGN KEY(tenant_id, confirmation_id) REFERENCES confirmations (tenant_id, id) DEFERRABLE '
 'INITIALLY DEFERRED, \n'
 '\tCHECK (writer_id=actor_id AND revision>0), \n'
 "\tCHECK (jsonb_typeof(command)='object' AND jsonb_typeof(body)='object' AND "
 "jsonb_typeof(source_basis)='object' AND jsonb_typeof(sources)='array' AND "
 "jsonb_typeof(reads)='array' AND jsonb_array_length(sources)>0 AND jsonb_array_length(reads)>0), \n"
 "\tCHECK (body_sha256 ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$' AND intent_digest ~ "
 "'^[a-f0-9]{64}$'), \n"
 '\tUNIQUE (tenant_id, category_id, rule_id, revision), \n'
 '\tUNIQUE (tenant_id, category_id, rule_id, id, revision), \n'
 '\tUNIQUE (tenant_id, id, assessment_id), \n'
 '\tFOREIGN KEY(tenant_id, category_id, rule_id, previous_id, previous_revision) REFERENCES '
 'knowledge_rule_versions (tenant_id, category_id, rule_id, id, revision), \n'
 '\tFOREIGN KEY(tenant_id, category_id, candidate_id, candidate_version_id, candidate_revision) '
 'REFERENCES knowledge_candidate_versions (tenant_id, category_id, candidate_id, id, revision), \n'
 '\tCONSTRAINT knowledge_rule_chain CHECK ((revision=1 AND rule_id=id AND previous_id IS NULL AND '
 'previous_revision IS NULL) OR (revision>1 AND previous_id IS NOT NULL AND previous_id<>id AND '
 'previous_revision=revision-1)), \n'
 "\tCONSTRAINT knowledge_rule_t2_only CHECK (operation='knowledge.rule.publish' AND confirmation_id IS "
 'NOT NULL AND writer_id=actor_id AND actor_id=requester_id), \n'
 '\tCONSTRAINT knowledge_rule_fixed_scope CHECK (product_id IS NOT NULL AND project_id IS NOT NULL AND '
 "candidate_revision>0 AND nature IN ('real','synthetic') AND (valid_until IS NULL OR "
 'valid_from<valid_until))\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_knowledge_rule_versions_category_id ON knowledge_rule_versions (category_id)',
 'CREATE INDEX ix_knowledge_rule_versions_tenant_id ON knowledge_rule_versions (tenant_id)',
 '\n'
 'CREATE TABLE knowledge_rule_currents (\n'
 '\trule_id UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\trevision INTEGER NOT NULL, \n'
 '\tcategory_id UUID NOT NULL, \n'
 '\tproduct_id UUID, \n'
 '\tproject_id UUID, \n'
 '\towner_id UUID NOT NULL, \n'
 '\tvisibility VARCHAR(16) NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(tenant_id, category_id) REFERENCES categories (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, category_id, product_id) REFERENCES products (tenant_id, category_id, '
 'id), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id) REFERENCES projects (tenant_id, product_id, id), \n'
 '\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n'
 "\tCHECK (visibility IN ('private','category')), \n"
 '\tCHECK (project_id IS NULL OR product_id IS NOT NULL), \n'
 '\tUNIQUE (tenant_id, category_id, rule_id), \n'
 '\tFOREIGN KEY(tenant_id, category_id, rule_id, version_id, revision) REFERENCES '
 'knowledge_rule_versions (tenant_id, category_id, rule_id, id, revision), \n'
 '\tCONSTRAINT knowledge_rule_current_scope CHECK (product_id IS NOT NULL AND project_id IS NOT NULL '
 'AND revision>0)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_knowledge_rule_currents_category_id ON knowledge_rule_currents (category_id)',
 'CREATE INDEX ix_knowledge_rule_currents_tenant_id ON knowledge_rule_currents (tenant_id)',
 'ALTER TABLE knowledge_applicability_assessments ADD CONSTRAINT knowledge_assessment_publication_fk '
 'FOREIGN KEY(tenant_id, publication_id, id) REFERENCES knowledge_rule_versions (tenant_id, id, '
 'assessment_id) DEFERRABLE INITIALLY DEFERRED',
 'ALTER TABLE knowledge_rule_versions ADD CONSTRAINT knowledge_rule_assessment_fk FOREIGN '
 'KEY(tenant_id, assessment_id, id) REFERENCES knowledge_applicability_assessments (tenant_id, id, '
 'publication_id) DEFERRABLE INITIALLY DEFERRED',
 'CREATE FUNCTION public.reject_knowledge_mutation() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge$\n'
 "BEGIN RAISE EXCEPTION 'Knowledge facts and assessment history are immutable' USING ERRCODE='23514'; "
 'END;\n'
 '$knowledge$',
 'CREATE FUNCTION public.protect_knowledge_candidate_current() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge$\n'
 '\n'
 'BEGIN\n'
 " IF TG_OP='INSERT' AND NEW.revision=1 THEN RETURN NEW;\n"
 " ELSIF TG_OP='UPDATE' AND (to_jsonb(NEW)-ARRAY['version_id','revision']) IS NOT DISTINCT FROM "
 "(to_jsonb(OLD)-ARRAY['version_id','revision'])\n"
 '  AND NEW.revision=OLD.revision+1 AND EXISTS(SELECT 1 FROM public.knowledge_candidate_versions v '
 'WHERE v.tenant_id=NEW.tenant_id\n'
 '   AND v.id=NEW.version_id AND v.revision=NEW.revision AND v.previous_id=OLD.version_id AND '
 'v.previous_revision=OLD.revision) THEN RETURN NEW;\n'
 ' END IF;\n'
 " RAISE EXCEPTION 'knowledge_candidate_currents requires exact immutable-scope single-step CAS' USING "
 "ERRCODE='23514';\n"
 'END;\n'
 '$knowledge$',
 'CREATE FUNCTION public.require_knowledge_candidate_current() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge$\n'
 '\n'
 'DECLARE cur public.knowledge_candidate_currents; fixed public.knowledge_candidate_versions; cx xid; '
 'vx xid;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT cur FROM public.knowledge_candidate_currents WHERE tenant_id=NEW.tenant_id AND '
 'id=NEW.id;\n'
 ' SELECT xmin INTO cx FROM public.knowledge_candidate_currents WHERE tenant_id=NEW.tenant_id AND '
 'id=NEW.id;\n'
 ' SELECT * INTO STRICT fixed FROM public.knowledge_candidate_versions WHERE tenant_id=NEW.tenant_id '
 'AND id=cur.version_id;\n'
 ' SELECT xmin INTO vx FROM public.knowledge_candidate_versions WHERE tenant_id=NEW.tenant_id AND '
 'id=cur.version_id;\n'
 ' IF vx IS DISTINCT FROM cx\n'
 '  OR '
 'ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.candidate_id,cur.version_id,cur.revision)\n'
 '   IS DISTINCT FROM '
 'ROW(fixed.category_id,fixed.product_id,fixed.project_id,fixed.owner_id,fixed.visibility,fixed.candidate_id,fixed.id,fixed.revision) '
 'THEN\n'
 "  RAISE EXCEPTION 'Knowledge Current requires its exact same-transaction scoped version' USING "
 "ERRCODE='23514'; END IF;\n"
 ' RETURN NULL;\n'
 'END;\n'
 '$knowledge$',
 'CREATE FUNCTION public.protect_knowledge_rule_current() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge$\n'
 '\n'
 'BEGIN\n'
 " IF TG_OP='INSERT' AND NEW.revision=1 THEN RETURN NEW;\n"
 " ELSIF TG_OP='UPDATE' AND (to_jsonb(NEW)-ARRAY['version_id','revision']) IS NOT DISTINCT FROM "
 "(to_jsonb(OLD)-ARRAY['version_id','revision'])\n"
 '  AND NEW.revision=OLD.revision+1 AND EXISTS(SELECT 1 FROM public.knowledge_rule_versions v WHERE '
 'v.tenant_id=NEW.tenant_id\n'
 '   AND v.id=NEW.version_id AND v.revision=NEW.revision AND v.previous_id=OLD.version_id AND '
 'v.previous_revision=OLD.revision) THEN RETURN NEW;\n'
 ' END IF;\n'
 " RAISE EXCEPTION 'knowledge_rule_currents requires exact immutable-scope single-step CAS' USING "
 "ERRCODE='23514';\n"
 'END;\n'
 '$knowledge$',
 'CREATE FUNCTION public.require_knowledge_rule_current() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge$\n'
 '\n'
 'DECLARE cur public.knowledge_rule_currents; fixed public.knowledge_rule_versions; cx xid; vx xid;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT cur FROM public.knowledge_rule_currents WHERE tenant_id=NEW.tenant_id AND '
 'id=NEW.id;\n'
 ' SELECT xmin INTO cx FROM public.knowledge_rule_currents WHERE tenant_id=NEW.tenant_id AND '
 'id=NEW.id;\n'
 ' SELECT * INTO STRICT fixed FROM public.knowledge_rule_versions WHERE tenant_id=NEW.tenant_id AND '
 'id=cur.version_id;\n'
 ' SELECT xmin INTO vx FROM public.knowledge_rule_versions WHERE tenant_id=NEW.tenant_id AND '
 'id=cur.version_id;\n'
 ' IF vx IS DISTINCT FROM cx\n'
 '  OR '
 'ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.rule_id,cur.version_id,cur.revision)\n'
 '   IS DISTINCT FROM '
 'ROW(fixed.category_id,fixed.product_id,fixed.project_id,fixed.owner_id,fixed.visibility,fixed.rule_id,fixed.id,fixed.revision) '
 'THEN\n'
 "  RAISE EXCEPTION 'Knowledge Current requires its exact same-transaction scoped version' USING "
 "ERRCODE='23514'; END IF;\n"
 ' RETURN NULL;\n'
 'END;\n'
 '$knowledge$',
 'CREATE FUNCTION public.assert_knowledge_members(t uuid,target uuid,kind text) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge$\n'
 '\n'
 'DECLARE v record; receipt public.action_receipts; proof public.confirmations;\n'
 ' expected jsonb; event_name text;\n'
 'BEGIN\n'
 " IF kind='knowledge_candidate' THEN\n"
 '  SELECT * INTO STRICT v FROM public.knowledge_candidate_versions WHERE tenant_id=t AND id=target;\n'
 '  '
 "expected=jsonb_build_object('id',v.id,'revision',v.revision,'status','draft','candidate_id',v.candidate_id,'project_id',v.project_id);\n"
 "  event_name='knowledge.candidate_created';\n"
 " ELSIF kind='design_rule' THEN\n"
 '  SELECT * INTO STRICT v FROM public.knowledge_rule_versions WHERE tenant_id=t AND id=target;\n'
 '  '
 "expected=jsonb_build_object('id',v.id,'revision',v.revision,'status','published','rule_id',v.rule_id,'project_id',v.project_id,'assessment_id',v.assessment_id);\n"
 "  event_name='knowledge.rule_published';\n"
 " ELSE RAISE EXCEPTION 'Unknown knowledge subject' USING ERRCODE='23514'; END IF;\n"
 ' SELECT * INTO STRICT receipt FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;\n'
 ' IF '
 'ROW(receipt.category_id,receipt.product_id,receipt.command_id,receipt.confirmation_id,receipt.actor_id,receipt.requester_id,receipt.operation,receipt.subject_type,receipt.subject_id,receipt.subject_revision,receipt.visibility,receipt.request_digest,receipt.intent_digest)\n'
 '  IS DISTINCT FROM '
 'ROW(v.category_id,v.product_id,v.command_id,v.confirmation_id,v.actor_id,v.requester_id,v.operation,kind::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)\n'
 '  OR receipt.result IS DISTINCT FROM expected OR receipt.created_at<v.created_at\n'
 '  OR (SELECT count(*) FROM public.action_receipts x WHERE x.tenant_id=t AND x.operation=v.operation '
 'AND x.subject_type=kind AND x.subject_id=v.id AND x.subject_revision=v.revision)<>1\n'
 '  OR (SELECT count(*) FROM public.audit_entries x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id)<>1\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id AND x.category_id=v.category_id AND x.actor_id=v.actor_id AND '
 'x.operation=v.operation AND x.created_at>=v.created_at)\n'
 '  OR (SELECT count(*) FROM public.outbox_events x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id)<>1\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id AND x.category_id=v.category_id AND x.actor_id=v.actor_id AND '
 'x.type=event_name AND x.subject_id=v.id AND x.subject_revision=v.revision AND x.schema_version=1 AND '
 'x.correlation_id=coalesce(receipt.agent_run_id,receipt.run_id,v.command_id) AND '
 'x.created_at>=v.created_at)\n'
 "  OR v.command->>'original_key_sha256' IS NULL OR v.command->>'original_key_sha256' !~ "
 "'^[a-f0-9]{64}$'\n"
 "  OR v.command->'envelope' ? 'idempotency_key'\n"
 "  OR v.command->'envelope'->'payload' ? 'confirmation_token' OR v.command->'envelope'->'payload' ? "
 "'approval_token'\n"
 '  OR NOT EXISTS(SELECT 1 FROM public.request_keys x WHERE x.tenant_id=t AND '
 'x.category_id=v.category_id AND x.receipt_id=v.receipt_id AND x.actor_id=v.actor_id AND '
 'x.digest=v.request_digest AND '
 "encode(sha256(convert_to(x.key,'UTF8')),'hex')=v.command->>'original_key_sha256') THEN\n"
 "  RAISE EXCEPTION 'Knowledge original receipt audit event or request mismatch' USING "
 "ERRCODE='23514'; END IF;\n"
 " IF kind='design_rule' THEN\n"
 '  SELECT * INTO STRICT proof FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;\n'
 '  IF proof.consumed IS DISTINCT FROM true\n'
 '   OR '
 'ROW(proof.category_id,proof.product_id,proof.actor_id,proof.operation,proof.subject_type,proof.subject_id,proof.revision)\n'
 '    IS DISTINCT FROM '
 "ROW(v.category_id,v.product_id,v.actor_id,v.operation,'product'::varchar,v.product_id,(v.command->'envelope'->>'expected_revision')::integer)\n"
 "   OR proof.snapshot IS DISTINCT FROM v.command->'review' OR proof.created_at>v.created_at\n"
 '   OR (proof.expires_at IS NOT NULL AND (v.created_at>=proof.expires_at OR '
 'receipt.created_at>=proof.expires_at))\n'
 '   OR receipt.run_id IS NOT NULL OR receipt.agent_run_id IS NOT NULL\n'
 '   OR v.actor_id<>v.requester_id THEN\n'
 "   RAISE EXCEPTION 'Knowledge rule requires the actual named consumed T2 proof' USING "
 "ERRCODE='23514'; END IF;\n"
 ' END IF;\n'
 'END;\n'
 '$knowledge$',
 'CREATE FUNCTION public.assert_knowledge_common(t uuid,target uuid,kind text) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge$\n'
 '\n'
 'DECLARE v record; envelope jsonb; vx xid; rx xid; px xid; ref jsonb; basis jsonb;\n'
 'BEGIN\n'
 " IF kind='knowledge_candidate' THEN\n"
 '  SELECT x.*,x.xmin AS tx INTO STRICT v FROM public.knowledge_candidate_versions x WHERE '
 'x.tenant_id=t AND x.id=target;\n'
 " ELSIF kind='design_rule' THEN\n"
 '  SELECT x.*,x.xmin AS tx INTO STRICT v FROM public.knowledge_rule_versions x WHERE x.tenant_id=t '
 'AND x.id=target;\n'
 " ELSE RAISE EXCEPTION 'Unknown knowledge subject' USING ERRCODE='23514'; END IF;\n"
 ' vx=v.tx;\n'
 ' SELECT xmin INTO rx FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;\n'
 ' PERFORM public.assert_knowledge_members(t,target,kind);\n'
 " envelope=v.command->'envelope';\n"
 ' IF v.actor_id IS DISTINCT FROM public.scope_actor() OR v.requester_id IS DISTINCT FROM '
 'public.scope_requester()\n'
 '  OR v.writer_id<>v.actor_id OR vx IS DISTINCT FROM rx OR NOT '
 'public.category_access(t,v.category_id,true)\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=t AND h.id=v.actor_id AND '
 'h.active)\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=t AND h.id=v.requester_id AND '
 "h.kind='human' AND h.active)\n"
 "  OR envelope->>'operation' IS DISTINCT FROM v.operation OR envelope->>'command_id' IS DISTINCT FROM "
 'v.command_id::text\n'
 "  OR envelope->>'category_id' IS DISTINCT FROM v.category_id::text OR envelope->>'product_id' IS "
 'DISTINCT FROM v.product_id::text\n'
 "  OR envelope->'payload'->>'project_id' IS DISTINCT FROM v.project_id::text\n"
 "  OR v.command->'review'->'declaration' IS DISTINCT FROM envelope->'payload'\n"
 "  OR v.command->'review'->>'operation' IS DISTINCT FROM v.operation\n"
 "  OR v.command->'review'->'sources' IS DISTINCT FROM v.sources\n"
 "  OR v.command->'review'->'source_basis' IS DISTINCT FROM v.source_basis\n"
 "  OR v.body IS DISTINCT FROM v.command->'review'->'after'\n"
 '  OR (v.product_id IS NULL AND NOT EXISTS(SELECT 1 FROM public.categories c WHERE c.tenant_id=t AND '
 "c.id=v.category_id AND c.revision::text=envelope->>'expected_revision'))\n"
 '  OR (v.product_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id=t '
 'AND p.category_id=v.category_id AND p.id=v.product_id AND '
 "p.revision::text=envelope->>'expected_revision'))\n"
 '  OR (v.project_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=t '
 'AND p.category_id=v.category_id AND p.product_id=v.product_id AND p.id=v.project_id))\n'
 "  OR NOT COALESCE(envelope->'source_read_set' @> v.reads,false) OR NOT COALESCE(v.reads @> "
 "(envelope->'source_read_set'),false)\n"
 "  OR jsonb_array_length(envelope->'source_read_set')<>jsonb_array_length(v.reads)\n"
 '  OR NOT public.direct_source_set_visible(t,v.category_id,v.product_id,v.reads)\n'
 '  OR NOT public.knowledge_content_sources_visible(t,v.category_id,v.product_id,v.source_basis)\n'
 '  OR NOT public.knowledge_result_sources_visible(t,v.category_id,v.product_id,v.source_basis)\n'
 '  OR (v.actor_id<>v.requester_id AND NOT EXISTS(SELECT 1 FROM public.action_receipts r WHERE '
 'r.tenant_id=t AND r.id=v.receipt_id AND coalesce(r.agent_run_id,r.run_id) IS NOT NULL))\n'
 "  OR (kind='design_rule' AND (v.actor_id<>v.requester_id OR NOT EXISTS(SELECT 1 FROM "
 "public.principals h WHERE h.tenant_id=t AND h.id=v.actor_id AND h.kind='human' AND h.active)))\n"
 '  OR EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id '
 'AND x.xmin IS DISTINCT FROM vx)\n'
 '  OR EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id '
 'AND x.xmin IS DISTINCT FROM vx)\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.request_keys x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id AND x.actor_id=v.actor_id AND x.digest=v.request_digest AND x.xmin=vx AND '
 "encode(sha256(convert_to(x.key,'UTF8')),'hex')=v.command->>'original_key_sha256') THEN\n"
 "  RAISE EXCEPTION 'Knowledge requires actual scope actor sources and one common transaction' USING "
 "ERRCODE='23514'; END IF;\n"
 ' IF v.confirmation_id IS NOT NULL THEN\n'
 '  SELECT xmin INTO px FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;\n'
 "  IF px IS DISTINCT FROM vx THEN RAISE EXCEPTION 'Knowledge T2 proof consumption must share its new "
 "rule transaction' USING ERRCODE='23514'; END IF;\n"
 ' END IF;\n'
 ' FOR ref IN SELECT value FROM jsonb_array_elements(v.reads) LOOP\n'
 '  IF NOT EXISTS(SELECT 1 FROM public.artifact_versions a WHERE a.tenant_id=t AND '
 'a.category_id=v.category_id\n'
 "   AND a.id::text=ref->>'artifact_id' AND a.revision::text=ref->>'expected_revision' AND "
 "a.status='active'\n"
 '   AND (a.original_id IS NULL OR EXISTS(SELECT 1 FROM public.uploaded_originals o JOIN '
 'public.original_security sec ON sec.tenant_id=o.tenant_id AND sec.original_id=o.id\n'
 "    WHERE o.tenant_id=t AND o.category_id=v.category_id AND o.id=a.original_id AND o.status='parsed' "
 "AND sec.source_state='active' AND sec.disposition='active'))) THEN\n"
 "   RAISE EXCEPTION 'Knowledge content or authority original is no longer current' USING "
 "ERRCODE='23514'; END IF;\n"
 ' END LOOP;\n'
 " IF jsonb_typeof(v.source_basis->'artifacts') IS DISTINCT FROM 'array' THEN\n"
 "  RAISE EXCEPTION 'Work direct source metadata required' USING ERRCODE='23514'; END IF;\n"
 " FOR basis IN SELECT value FROM jsonb_array_elements(v.source_basis->'artifacts') LOOP\n"
 '  IF NOT EXISTS(SELECT 1 FROM public.artifact_versions a WHERE a.tenant_id=t AND '
 'a.category_id=v.category_id\n'
 "   AND a.product_id::text IS NOT DISTINCT FROM basis->>'product_id' AND a.id::text=basis->>'id'\n"
 "   AND a.revision::text=basis->>'revision' AND a.content_hash=basis->>'hash' AND a.status='active'\n"
 "   AND a.status=basis->>'status' AND a.owner_id::text=basis->>'owner_id' AND "
 "a.visibility=basis->>'visibility'\n"
 "   AND (v.visibility='private' OR (a.visibility='category' AND (a.product_id IS NULL OR "
 'EXISTS(SELECT 1 FROM public.products source_product WHERE source_product.tenant_id=t AND '
 'source_product.category_id=v.category_id AND source_product.id=a.product_id AND '
 "source_product.visibility='category'))))\n"
 "   AND (NOT(basis ? 'original') OR EXISTS(SELECT 1 FROM public.original_security sec\n"
 '    WHERE sec.tenant_id=t AND sec.original_id=a.original_id AND '
 "sec.original_id::text=basis->'original'->>'id'\n"
 "     AND sec.epoch::text=basis->'original'->>'epoch' AND sec.source_state='active' AND "
 "sec.disposition='active'))) THEN\n"
 "   RAISE EXCEPTION 'Retained work source metadata changed' USING ERRCODE='23514'; END IF;\n"
 ' END LOOP;\n'
 ' FOR ref IN SELECT value FROM jsonb_array_elements(v.sources) LOOP\n'
 "  SELECT value INTO STRICT basis FROM jsonb_array_elements(v.source_basis->'artifacts') WHERE "
 "value->>'id'=ref->>'id';\n"
 "  IF ref->>'kind' IS DISTINCT FROM 'artifact' OR NOT EXISTS(SELECT 1 FROM "
 "jsonb_array_elements(v.reads) rd WHERE rd->>'artifact_id'=ref->>'id' AND "
 "rd->'expected_revision'=ref->'revision')\n"
 '   OR NOT EXISTS(SELECT 1 FROM public.artifact_versions a WHERE a.tenant_id=t AND '
 'a.category_id=v.category_id\n'
 "    AND a.id::text=ref->>'id' AND a.revision::text=ref->>'revision' AND a.status='active'\n"
 "    AND a.revision::text=basis->>'revision' AND a.content_hash=basis->>'hash' AND "
 "a.status=basis->>'status'\n"
 "    AND a.owner_id::text=basis->>'owner_id' AND a.visibility=basis->>'visibility'\n"
 "    AND (v.visibility='private' OR (a.visibility='category' AND (a.product_id IS NULL OR "
 'EXISTS(SELECT 1 FROM public.products source_product WHERE source_product.tenant_id=t AND '
 'source_product.category_id=v.category_id AND source_product.id=a.product_id AND '
 "source_product.visibility='category'))))\n"
 "    AND ((a.original_id IS NULL AND basis->>'source_kind'='registered_native_text' AND EXISTS(\n"
 '      SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=t AND r.subject_id=a.id AND '
 'r.subject_revision=a.revision\n'
 "       AND r.subject_type='artifact' AND r.operation='evidence.artifact.register' AND "
 "r.id::text=basis->'registration'->>'receipt_id'\n"
 "       AND r.actor_id::text=basis->'registration'->>'actor_id' AND "
 "r.requester_id::text=basis->'registration'->>'requester_id'\n"
 "       AND r.run_id::text IS NOT DISTINCT FROM basis->'registration'->>'run_id'))\n"
 "     OR (a.original_id IS NOT NULL AND basis->>'source_kind'='uploaded_original' AND EXISTS(\n"
 '      SELECT 1 FROM public.uploaded_originals o JOIN public.original_security sec ON '
 'sec.tenant_id=o.tenant_id AND sec.original_id=o.id\n'
 '       WHERE o.tenant_id=t AND o.category_id=v.category_id AND o.id=a.original_id AND '
 "o.id::text=basis->'original'->>'id'\n"
 "        AND o.status='parsed' AND sec.epoch::text=basis->'original'->>'epoch' AND "
 "sec.source_state='active' AND sec.disposition='active'\n"
 "        AND sec.source_state=basis->'original'->>'source_state' AND "
 "sec.disposition=basis->'original'->>'disposition'\n"
 "        AND (v.visibility='private' OR o.visibility='category'))))) THEN\n"
 "   RAISE EXCEPTION 'Work source metadata security or audience changed' USING ERRCODE='23514'; END "
 'IF;\n'
 ' END LOOP;\n'
 'END;\n'
 '$knowledge$',
 'CREATE FUNCTION public.assert_knowledge_professional(t uuid,target uuid) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge$\n'
 '\n'
 'DECLARE v public.knowledge_rule_versions; authority jsonb; reference jsonb;\n'
 ' fact public.professional_authority_facts; pointer public.professional_authority_current;\n'
 ' has_duty boolean=false; has_qualification boolean=false;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT v FROM public.knowledge_rule_versions WHERE tenant_id=t AND id=target;\n'
 " authority=v.source_basis->'professional';\n"
 " IF jsonb_typeof(authority) IS DISTINCT FROM 'object'\n"
 "  OR authority->'scope' IS DISTINCT FROM "
 "jsonb_build_object('tenant_id',t,'product_id',v.product_id,'project_id',v.project_id)\n"
 "  OR authority->>'subject_id' IS DISTINCT FROM v.actor_id::text\n"
 "  OR authority->>'operation' IS DISTINCT FROM v.operation\n"
 "  OR authority->>'purpose' IS DISTINCT FROM v.body->'applicability'->>'purpose'\n"
 "  OR authority->'authorized' IS DISTINCT FROM 'true'::jsonb OR authority->'qualified' IS DISTINCT "
 "FROM 'true'::jsonb\n"
 '  OR authority->\'roles\' IS DISTINCT FROM \'["knowledge"]\'::jsonb\n'
 "  OR jsonb_typeof(authority->'fact_refs') IS DISTINCT FROM 'array'\n"
 "  OR jsonb_array_length(authority->'fact_refs')=0\n"
 "  OR v.nature IS DISTINCT FROM (CASE WHEN authority->'synthetic'='true'::jsonb THEN 'synthetic' ELSE "
 "'real' END) THEN\n"
 "  RAISE EXCEPTION 'Knowledge publication requires its own actual named authority scope' USING "
 "ERRCODE='23514'; END IF;\n"
 " FOR reference IN SELECT value FROM jsonb_array_elements(authority->'fact_refs') LOOP\n"
 '  SELECT * INTO fact FROM public.professional_authority_facts f WHERE f.tenant_id=t AND '
 'f.product_id=v.product_id AND f.project_id=v.project_id\n'
 "   AND f.subject_id=v.actor_id AND f.id::text=reference->>'id' AND "
 "f.revision::text=reference->>'revision';\n"
 "  IF NOT FOUND THEN RAISE EXCEPTION 'Knowledge authority cannot be invented from a snapshot' USING "
 "ERRCODE='23514'; END IF;\n"
 '  SELECT * INTO pointer FROM public.professional_authority_current p WHERE p.tenant_id=t AND '
 'p.product_id=v.product_id AND p.project_id=v.project_id\n'
 '   AND p.subject_id=v.actor_id AND p.fact_id=fact.id AND p.fact_revision=fact.revision AND '
 "p.series_id=fact.series_id AND p.epoch::text=reference->>'epoch';\n"
 "  IF NOT FOUND OR fact.fact_sha256 IS DISTINCT FROM reference->>'fact_sha256'\n"
 "   OR fact.series_id::text IS DISTINCT FROM reference->>'series_id'\n"
 "   OR fact.kind IS DISTINCT FROM reference->>'kind' OR fact.role IS DISTINCT FROM "
 "reference->>'role'\n"
 "   OR fact.nature IS DISTINCT FROM reference->>'nature' OR fact.state IS DISTINCT FROM "
 "reference->>'state'\n"
 "   OR fact.issuer_key IS DISTINCT FROM reference->>'issuer_key' OR fact.issuer_version IS DISTINCT "
 "FROM reference->>'issuer_version'\n"
 "   OR fact.operations IS DISTINCT FROM reference->'operations' OR fact.purposes IS DISTINCT FROM "
 "reference->'purposes'\n"
 '   OR NOT coalesce(v.reads @> fact.required_source_read_set,false) THEN\n'
 "   RAISE EXCEPTION 'Knowledge authority snapshot must bind actual current duty and qualification "
 "facts' USING ERRCODE='23514'; END IF;\n"
 "  IF fact.role='knowledge' AND fact.state='active' AND fact.valid_from<=v.created_at AND "
 'v.created_at<fact.valid_until\n'
 '   AND fact.operations @> jsonb_build_array(v.operation) AND fact.purposes @> '
 "jsonb_build_array(v.body->'applicability'->>'purpose') THEN\n"
 "   IF fact.kind='duty' THEN has_duty=true; ELSIF fact.kind='qualification' THEN "
 'has_qualification=true; END IF;\n'
 '  END IF;\n'
 ' END LOOP;\n'
 ' IF NOT has_duty OR NOT has_qualification THEN\n'
 "  RAISE EXCEPTION 'Prior engineering quality or manufacturing roles do not grant knowledge "
 "publication' USING ERRCODE='23514'; END IF;\n"
 'END;\n'
 '$knowledge$',
 'CREATE FUNCTION public.protect_knowledge_receipt() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge$\n'
 '\n'
 'DECLARE scoped boolean=false;\n'
 'BEGIN\n'
 " IF TG_OP<>'INSERT' THEN scoped=OLD.operation IN "
 "('knowledge.candidate.create','knowledge.rule.publish') OR OLD.subject_type IN "
 "('knowledge_candidate','design_rule'); END IF;\n"
 " IF TG_OP<>'DELETE' THEN scoped=scoped OR NEW.operation IN "
 "('knowledge.candidate.create','knowledge.rule.publish') OR NEW.subject_type IN "
 "('knowledge_candidate','design_rule'); END IF;\n"
 " IF scoped AND TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Knowledge receipt history is immutable' USING "
 "ERRCODE='23514'; END IF;\n"
 " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
 'END;\n'
 '$knowledge$',
 'CREATE FUNCTION public.protect_knowledge_member() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge$\n'
 '\n'
 'DECLARE scoped boolean=false; old_scoped boolean=false;\n'
 'BEGIN\n'
 " IF TG_OP<>'DELETE' THEN SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE "
 'r.tenant_id=NEW.tenant_id AND r.id=NEW.receipt_id AND (r.operation IN '
 "('knowledge.candidate.create','knowledge.rule.publish') OR r.subject_type IN "
 "('knowledge_candidate','design_rule'))) INTO scoped; END IF;\n"
 " IF TG_OP<>'INSERT' THEN SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE "
 'r.tenant_id=OLD.tenant_id AND r.id=OLD.receipt_id AND (r.operation IN '
 "('knowledge.candidate.create','knowledge.rule.publish') OR r.subject_type IN "
 "('knowledge_candidate','design_rule'))) INTO old_scoped; END IF;\n"
 " IF TG_OP<>'INSERT' AND (scoped OR old_scoped) THEN\n"
 "  IF TG_OP='UPDATE' AND TG_TABLE_NAME='outbox_events' AND "
 "(to_jsonb(NEW)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) IS NOT "
 "DISTINCT FROM (to_jsonb(OLD)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) "
 'THEN RETURN NEW; END IF;\n'
 "  RAISE EXCEPTION 'Knowledge original audit event or request key is immutable' USING "
 "ERRCODE='23514'; END IF;\n"
 " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
 'END;\n'
 '$knowledge$',
 'CREATE FUNCTION public.require_knowledge_member() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge$\n'
 '\n'
 'DECLARE receipt public.action_receipts;\n'
 'BEGIN\n'
 " IF TG_TABLE_NAME='action_receipts' THEN receipt=NEW; ELSE SELECT * INTO receipt FROM "
 'public.action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id; END IF;\n'
 " IF receipt.operation IN ('knowledge.candidate.create','knowledge.rule.publish') OR "
 "receipt.subject_type IN ('knowledge_candidate','design_rule') THEN\n"
 '  PERFORM '
 'public.assert_knowledge_members(receipt.tenant_id,receipt.subject_id,receipt.subject_type::text); '
 'END IF;\n'
 ' RETURN NULL;\n'
 'END;\n'
 '$knowledge$',
 'CREATE FUNCTION public.protect_knowledge_confirmation() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge$\n'
 '\n'
 'DECLARE old_scoped boolean=false; new_scoped boolean=false;\n'
 'BEGIN\n'
 " IF TG_OP<>'INSERT' THEN old_scoped=OLD.operation='knowledge.rule.publish'; END IF;\n"
 " IF TG_OP<>'DELETE' THEN new_scoped=NEW.operation='knowledge.rule.publish'; END IF;\n"
 ' IF old_scoped OR new_scoped THEN\n'
 "  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Knowledge publication confirmation history retained' USING "
 "ERRCODE='23514';\n"
 "  ELSIF TG_OP='INSERT' THEN\n"
 "   IF NEW.consumed IS DISTINCT FROM false THEN RAISE EXCEPTION 'Knowledge publication proof starts "
 "unconsumed' USING ERRCODE='23514'; END IF;\n"
 '  ELSIF NOT(old_scoped AND new_scoped) OR OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS '
 'DISTINCT FROM true\n'
 "   OR (to_jsonb(NEW)-'consumed') IS DISTINCT FROM (to_jsonb(OLD)-'consumed') THEN\n"
 "   RAISE EXCEPTION 'Knowledge publication proof consumes only its original false to true' USING "
 "ERRCODE='23514'; END IF;\n"
 ' END IF;\n'
 " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
 'END;\n'
 '$knowledge$',
 'CREATE FUNCTION public.require_knowledge_confirmation() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge$\n'
 '\n'
 'BEGIN\n'
 " IF NEW.operation='knowledge.rule.publish' THEN\n"
 '  IF OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true\n'
 '   OR (SELECT count(*) FROM public.knowledge_rule_versions v WHERE v.tenant_id=NEW.tenant_id AND '
 'v.confirmation_id=NEW.id AND v.operation=NEW.operation)<>1 THEN\n'
 "   RAISE EXCEPTION 'Consumed knowledge T2 proof needs exactly one new publication' USING "
 "ERRCODE='23514'; END IF;\n"
 ' END IF;\n'
 ' RETURN NULL;\n'
 'END;\n'
 '$knowledge$',
 'CREATE FUNCTION public.assert_knowledge_candidate(t uuid,target uuid) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge$\n'
 '\n'
 'DECLARE v public.knowledge_candidate_versions; prior public.knowledge_candidate_versions;\n'
 ' cur public.knowledge_candidate_currents; payload jsonb; expected jsonb; vx xid; cx xid;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT v FROM public.knowledge_candidate_versions WHERE tenant_id=t AND id=target;\n'
 ' SELECT xmin INTO vx FROM public.knowledge_candidate_versions WHERE tenant_id=t AND id=target;\n'
 " PERFORM public.assert_knowledge_common(t,target,'knowledge_candidate');\n"
 ' SELECT * INTO STRICT cur FROM public.knowledge_candidate_currents WHERE tenant_id=t AND '
 'category_id=v.category_id AND candidate_id=v.candidate_id;\n'
 ' SELECT xmin INTO cx FROM public.knowledge_candidate_currents WHERE tenant_id=t AND id=cur.id;\n'
 " payload=v.command->'envelope'->'payload';\n"
 ' '
 "expected=jsonb_build_object('candidate_id',v.candidate_id,'revision',v.revision,'title',payload->'title',\n"
 "  'lesson',payload->'lesson','evidence_summary',payload->'evidence_summary',\n"
 '  '
 "'applicability_hypothesis',payload->'applicability_hypothesis','result_receipts',payload->'result_receipts');\n"
 ' IF vx IS DISTINCT FROM cx OR v.body IS DISTINCT FROM expected\n'
 "  OR payload->>'visibility' IS DISTINCT FROM v.visibility\n"
 '  OR v.owner_id<>v.requester_id\n'
 '  OR '
 'ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.candidate_id,cur.version_id,cur.revision)\n'
 '   IS DISTINCT FROM '
 'ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.candidate_id,v.id,v.revision) '
 'THEN\n'
 "  RAISE EXCEPTION 'Knowledge candidate requires exact declared content and same-transaction Current' "
 "USING ERRCODE='23514'; END IF;\n"
 ' IF v.revision=1 THEN\n'
 "  IF coalesce(payload->'candidate','null'::jsonb)<>'null'::jsonb\n"
 "   OR coalesce(v.command->'review'->'before','null'::jsonb)<>'null'::jsonb\n"
 '   OR v.owner_id<>v.requester_id THEN\n'
 "   RAISE EXCEPTION 'First knowledge candidate binds its actual requester and declared category "
 "scope' USING ERRCODE='23514'; END IF;\n"
 ' ELSE\n'
 '  SELECT * INTO STRICT prior FROM public.knowledge_candidate_versions WHERE tenant_id=t AND '
 'id=v.previous_id;\n'
 "  IF payload->'candidate' IS DISTINCT FROM "
 "jsonb_build_object('id',v.candidate_id,'revision',v.previous_revision)\n"
 "   OR v.command->'review'->'before' IS DISTINCT FROM prior.body\n"
 '   OR ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.candidate_id)\n'
 '    IS DISTINCT FROM '
 'ROW(prior.category_id,prior.product_id,prior.project_id,prior.owner_id,prior.visibility,prior.candidate_id) '
 'THEN\n'
 "   RAISE EXCEPTION 'Knowledge candidate continuation cannot replace its fixed scope or predecessor' "
 "USING ERRCODE='23514'; END IF;\n"
 '  IF EXISTS(SELECT 1 FROM public.principals actor WHERE actor.tenant_id=t AND actor.id=v.actor_id '
 "AND actor.kind='agent')\n"
 '   AND (prior.actor_id<>v.actor_id OR NOT EXISTS(SELECT 1 FROM public.principals author WHERE '
 "author.tenant_id=t AND author.id=prior.actor_id AND author.kind='agent')\n"
 '    OR EXISTS(SELECT 1 FROM public.knowledge_rule_versions consumed WHERE consumed.tenant_id=t AND '
 'consumed.category_id=v.category_id AND consumed.candidate_id=v.candidate_id)) THEN\n'
 "   RAISE EXCEPTION 'AI may continue only its own unpublished candidate lineage without overwriting "
 "human content' USING ERRCODE='23514'; END IF;\n"
 ' END IF;\n'
 'END;\n'
 '$knowledge$',
 'CREATE FUNCTION public.require_knowledge_candidate() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge$\n'
 'BEGIN PERFORM public.assert_knowledge_candidate(NEW.tenant_id,NEW.id); RETURN NULL; END;\n'
 '$knowledge$',
 'CREATE FUNCTION public.assert_knowledge_rule(t uuid,target uuid) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge$\n'
 '\n'
 'DECLARE v public.knowledge_rule_versions; prior public.knowledge_rule_versions;\n'
 ' cur public.knowledge_rule_currents; candidate public.knowledge_candidate_versions;\n'
 ' candidate_current public.knowledge_candidate_currents; assessment '
 'public.knowledge_applicability_assessments;\n'
 ' payload jsonb; expected jsonb; applicability jsonb; expected_assessment jsonb; vx xid; cx xid; ax '
 'xid;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT v FROM public.knowledge_rule_versions WHERE tenant_id=t AND id=target;\n'
 ' SELECT xmin INTO vx FROM public.knowledge_rule_versions WHERE tenant_id=t AND id=target;\n'
 " PERFORM public.assert_knowledge_common(t,target,'design_rule');\n"
 ' PERFORM public.assert_knowledge_professional(t,target);\n'
 ' SELECT * INTO STRICT cur FROM public.knowledge_rule_currents WHERE tenant_id=t AND '
 'category_id=v.category_id AND rule_id=v.rule_id;\n'
 ' SELECT xmin INTO cx FROM public.knowledge_rule_currents WHERE tenant_id=t AND id=cur.id;\n'
 ' SELECT * INTO STRICT candidate FROM public.knowledge_candidate_versions WHERE tenant_id=t AND '
 'category_id=v.category_id AND id=v.candidate_version_id;\n'
 ' SELECT * INTO STRICT candidate_current FROM public.knowledge_candidate_currents WHERE tenant_id=t '
 'AND category_id=v.category_id AND candidate_id=v.candidate_id;\n'
 ' SELECT * INTO STRICT assessment FROM public.knowledge_applicability_assessments WHERE tenant_id=t '
 'AND id=v.assessment_id;\n'
 ' SELECT xmin INTO ax FROM public.knowledge_applicability_assessments WHERE tenant_id=t AND '
 'id=v.assessment_id;\n'
 " payload=v.command->'envelope'->'payload'; applicability=payload->'applicability';\n"
 ' '
 "expected_assessment=applicability||jsonb_build_object('candidate_version',jsonb_build_object('id',candidate.id,'revision',candidate.revision),\n"
 "  'assessor_id',v.actor_id,'withdrawal_reason',NULL);\n"
 ' '
 "expected=jsonb_build_object('rule_id',v.rule_id,'revision',v.revision,'candidate',jsonb_build_object('id',v.candidate_id,'revision',v.candidate_revision),\n"
 '  '
 "'candidate_version_id',v.candidate_version_id,'assessment_id',v.assessment_id,'title',payload->'title','rule_text',payload->'rule_text',\n"
 "  'applicability',assessment.body,'nature',v.nature);\n"
 ' IF vx IS DISTINCT FROM cx OR vx IS DISTINCT FROM ax\n'
 '  OR '
 'ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.rule_id,cur.version_id,cur.revision)\n'
 '   IS DISTINCT FROM '
 'ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.rule_id,v.id,v.revision)\n'
 '  OR candidate.candidate_id<>v.candidate_id OR candidate.revision<>v.candidate_revision\n'
 "  OR (candidate.visibility='private' AND (v.visibility<>'private' OR "
 'candidate.owner_id<>v.owner_id))\n'
 '  OR candidate_current.version_id<>candidate.id OR candidate_current.revision<>candidate.revision\n'
 "  OR v.source_basis->'candidate' IS DISTINCT FROM "
 "jsonb_build_object('id',candidate.id,'revision',candidate.revision,'body_sha256',candidate.body_sha256)\n"
 "  OR payload->'candidate' IS DISTINCT FROM "
 "jsonb_build_object('id',candidate.candidate_id,'revision',candidate.revision)\n"
 '  OR assessment.body IS DISTINCT FROM expected_assessment OR v.body IS DISTINCT FROM expected\n'
 '  OR '
 'ROW(assessment.category_id,assessment.product_id,assessment.project_id,assessment.owner_id,assessment.visibility,assessment.publication_id,assessment.candidate_version_id,assessment.candidate_revision,assessment.actor_id,assessment.receipt_id)\n'
 '   IS DISTINCT FROM '
 'ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.id,v.candidate_version_id,v.candidate_revision,v.actor_id,v.receipt_id)\n'
 "  OR assessment.body->>'decision' IS DISTINCT FROM 'applicable'\n"
 "  OR (assessment.body->>'valid_from')::timestamptz IS DISTINCT FROM v.valid_from\n"
 "  OR (assessment.body->>'valid_until')::timestamptz IS DISTINCT FROM v.valid_until THEN\n"
 "  RAISE EXCEPTION 'Knowledge publication binds exact candidate assessment authority and one atomic "
 "group' USING ERRCODE='23514'; END IF;\n"
 " IF applicability->'target'->>'kind'='engineering_configuration' THEN\n"
 '  IF NOT EXISTS(SELECT 1 FROM public.engineering_configurations target WHERE target.tenant_id=t AND '
 'target.category_id=v.category_id AND target.product_id=v.product_id\n'
 "   AND target.id::text=applicability->'target'->>'id' AND "
 "target.revision::text=applicability->'target'->>'revision'\n"
 '   AND '
 "v.source_basis->'target'=jsonb_build_object('kind','engineering_configuration','id',target.id,'revision',target.revision,'product_id',target.product_id,'owner_id',target.owner_id,'visibility',target.visibility,'sources',target.sources,'required_source_read_set',target.required_source_read_set)\n"
 '   AND coalesce(v.reads @> target.required_source_read_set,false)\n'
 '   AND EXISTS(SELECT 1 FROM public.project_product_links link WHERE link.tenant_id=t AND '
 'link.category_id=v.category_id AND link.product_id=v.product_id AND link.project_id=v.project_id AND '
 'link.definition_id=target.definition_id AND link.definition_revision=target.definition_revision)\n'
 "   AND (target.visibility='category' OR target.owner_id=public.scope_requester() OR EXISTS(SELECT 1 "
 'FROM public.object_audiences audience WHERE audience.tenant_id=t AND '
 "audience.category_id=v.category_id AND audience.object_type='engineering_configurations' AND "
 'audience.subject_id=target.id AND audience.owner_id=target.owner_id AND '
 'audience.principal_id=public.scope_requester()))\n'
 "   AND (v.visibility='private' OR target.visibility='category')) THEN\n"
 "   RAISE EXCEPTION 'Knowledge target must be an actual readable fixed engineering configuration' "
 "USING ERRCODE='23514'; END IF;\n"
 " ELSIF applicability->'target'->>'kind'='process_revision' THEN\n"
 '  IF NOT EXISTS(SELECT 1 FROM public.process_revisions target WHERE target.tenant_id=t AND '
 'target.category_id=v.category_id AND target.product_id=v.product_id\n'
 "   AND target.id::text=applicability->'target'->>'id' AND "
 "target.revision::text=applicability->'target'->>'revision'\n"
 '   AND '
 "v.source_basis->'target'=jsonb_build_object('kind','process_revision','id',target.id,'revision',target.revision,'product_id',target.product_id,'owner_id',target.owner_id,'visibility',target.visibility,'sources',target.sources,'required_source_read_set',target.required_source_read_set)\n"
 '   AND coalesce(v.reads @> target.required_source_read_set,false)\n'
 '   AND EXISTS(SELECT 1 FROM public.engineering_configurations engineering JOIN '
 'public.project_product_links link ON link.tenant_id=engineering.tenant_id AND '
 'link.category_id=engineering.category_id AND link.product_id=engineering.product_id AND '
 'link.definition_id=engineering.definition_id AND '
 'link.definition_revision=engineering.definition_revision\n'
 '    WHERE engineering.tenant_id=t AND engineering.category_id=v.category_id AND '
 'engineering.product_id=v.product_id AND engineering.id=target.engineering_configuration_id AND '
 'engineering.revision=target.engineering_revision AND link.project_id=v.project_id)\n'
 "   AND (target.visibility='category' OR target.owner_id=public.scope_requester() OR EXISTS(SELECT 1 "
 'FROM public.object_audiences audience WHERE audience.tenant_id=t AND '
 "audience.category_id=v.category_id AND audience.object_type='process_revisions' AND "
 'audience.subject_id=target.id AND audience.owner_id=target.owner_id AND '
 'audience.principal_id=public.scope_requester()))\n'
 "   AND (v.visibility='private' OR target.visibility='category')) THEN\n"
 "   RAISE EXCEPTION 'Knowledge target must be an actual readable fixed manufacturing configuration' "
 "USING ERRCODE='23514'; END IF;\n"
 " ELSE RAISE EXCEPTION 'Knowledge target configuration kind is not registered' USING ERRCODE='23514'; "
 'END IF;\n'
 ' IF v.revision=1 THEN\n'
 "  IF coalesce(payload->'rule','null'::jsonb)<>'null'::jsonb\n"
 "   OR coalesce(v.command->'review'->'before','null'::jsonb)<>'null'::jsonb OR "
 'v.owner_id<>v.requester_id THEN\n'
 "   RAISE EXCEPTION 'First published rule binds the actual named publisher' USING ERRCODE='23514'; "
 'END IF;\n'
 ' ELSE\n'
 '  SELECT * INTO STRICT prior FROM public.knowledge_rule_versions WHERE tenant_id=t AND '
 'id=v.previous_id;\n'
 "  IF payload->'rule' IS DISTINCT FROM "
 "jsonb_build_object('id',v.rule_id,'revision',v.previous_revision)\n"
 "   OR v.command->'review'->'before' IS DISTINCT FROM prior.body\n"
 '   OR ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.rule_id)\n'
 '    IS DISTINCT FROM '
 'ROW(prior.category_id,prior.product_id,prior.project_id,prior.owner_id,prior.visibility,prior.rule_id) '
 'THEN\n'
 "   RAISE EXCEPTION 'Published rule continuation cannot replace fixed scope or its original "
 "predecessor' USING ERRCODE='23514'; END IF;\n"
 ' END IF;\n'
 'END;\n'
 '$knowledge$',
 'CREATE FUNCTION public.require_knowledge_rule() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge$\n'
 'BEGIN PERFORM public.assert_knowledge_rule(NEW.tenant_id,NEW.id); RETURN NULL; END;\n'
 '$knowledge$',
 'CREATE FUNCTION public.assert_knowledge_assessment(t uuid,target uuid) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge$\n'
 '\n'
 'DECLARE assessment public.knowledge_applicability_assessments; publication '
 'public.knowledge_rule_versions; ax xid; vx xid;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT assessment FROM public.knowledge_applicability_assessments WHERE tenant_id=t '
 'AND id=target;\n'
 ' SELECT xmin INTO ax FROM public.knowledge_applicability_assessments WHERE tenant_id=t AND '
 'id=target;\n'
 ' SELECT * INTO STRICT publication FROM public.knowledge_rule_versions WHERE tenant_id=t AND '
 'id=assessment.publication_id;\n'
 ' SELECT xmin INTO vx FROM public.knowledge_rule_versions WHERE tenant_id=t AND '
 'id=assessment.publication_id;\n'
 ' IF ax IS DISTINCT FROM vx OR publication.assessment_id<>assessment.id\n'
 "  OR assessment.body IS DISTINCT FROM publication.body->'applicability'\n"
 '  OR '
 'ROW(assessment.category_id,assessment.product_id,assessment.project_id,assessment.owner_id,assessment.visibility,assessment.candidate_version_id,assessment.candidate_revision,assessment.actor_id,assessment.receipt_id)\n'
 '   IS DISTINCT FROM '
 'ROW(publication.category_id,publication.product_id,publication.project_id,publication.owner_id,publication.visibility,publication.candidate_version_id,publication.candidate_revision,publication.actor_id,publication.receipt_id) '
 'THEN\n'
 "  RAISE EXCEPTION 'Applicability assessment exists only as its one actual T2 publication child' "
 "USING ERRCODE='23514'; END IF;\n"
 'END;\n'
 '$knowledge$',
 'CREATE FUNCTION public.require_knowledge_assessment() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge$\n'
 'BEGIN PERFORM public.assert_knowledge_assessment(NEW.tenant_id,NEW.id); RETURN NULL; END;\n'
 '$knowledge$',
 'REVOKE ALL ON FUNCTION public.reject_knowledge_mutation() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.protect_knowledge_candidate_current() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.require_knowledge_candidate_current() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.protect_knowledge_rule_current() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.require_knowledge_rule_current() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.assert_knowledge_members(uuid,uuid,text) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.assert_knowledge_common(uuid,uuid,text) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.assert_knowledge_professional(uuid,uuid) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.protect_knowledge_receipt() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.protect_knowledge_member() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.require_knowledge_member() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.protect_knowledge_confirmation() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.require_knowledge_confirmation() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.assert_knowledge_candidate(uuid,uuid) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.require_knowledge_candidate() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.assert_knowledge_rule(uuid,uuid) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.require_knowledge_rule() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.assert_knowledge_assessment(uuid,uuid) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.require_knowledge_assessment() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'ALTER TABLE public."knowledge_candidate_versions" ENABLE ROW LEVEL SECURITY',
 'ALTER TABLE public."knowledge_candidate_versions" FORCE ROW LEVEL SECURITY',
 'CREATE POLICY owner_internal ON public."knowledge_candidate_versions" TO pdos_next_owner USING(true) '
 'WITH CHECK(true)',
 'CREATE POLICY knowledge_read ON public."knowledge_candidate_versions" FOR SELECT TO pdos_next_app '
 "USING(public.category_access(tenant_id,category_id) AND (visibility='category' OR "
 'owner_id=public.scope_requester()) AND (knowledge_candidate_versions.product_id IS NULL OR '
 'EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id=knowledge_candidate_versions.tenant_id AND '
 'p.category_id=knowledge_candidate_versions.category_id AND '
 'p.id=knowledge_candidate_versions.product_id)) AND (knowledge_candidate_versions.project_id IS NULL '
 'OR EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=knowledge_candidate_versions.tenant_id '
 'AND p.category_id=knowledge_candidate_versions.category_id AND '
 'p.product_id=knowledge_candidate_versions.product_id AND '
 'p.id=knowledge_candidate_versions.project_id)) AND '
 'public.knowledge_content_sources_visible(tenant_id,category_id,product_id,source_basis) AND '
 '(public.knowledge_result_sources_visible(tenant_id,category_id,product_id,source_basis)))',
 'CREATE POLICY knowledge_insert ON public."knowledge_candidate_versions" FOR INSERT TO pdos_next_app '
 'WITH CHECK(public.category_access(tenant_id,category_id,true) AND '
 "public.category_access(tenant_id,category_id) AND (visibility='category' OR "
 'owner_id=public.scope_requester()) AND (knowledge_candidate_versions.product_id IS NULL OR '
 'EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id=knowledge_candidate_versions.tenant_id AND '
 'p.category_id=knowledge_candidate_versions.category_id AND '
 'p.id=knowledge_candidate_versions.product_id)) AND (knowledge_candidate_versions.project_id IS NULL '
 'OR EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=knowledge_candidate_versions.tenant_id '
 'AND p.category_id=knowledge_candidate_versions.category_id AND '
 'p.product_id=knowledge_candidate_versions.product_id AND '
 'p.id=knowledge_candidate_versions.project_id)))',
 'REVOKE ALL ON public."knowledge_candidate_versions" FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'GRANT SELECT,INSERT ON public."knowledge_candidate_versions" TO pdos_next_app',
 'ALTER TABLE public."knowledge_candidate_currents" ENABLE ROW LEVEL SECURITY',
 'ALTER TABLE public."knowledge_candidate_currents" FORCE ROW LEVEL SECURITY',
 'CREATE POLICY owner_internal ON public."knowledge_candidate_currents" TO pdos_next_owner USING(true) '
 'WITH CHECK(true)',
 'CREATE POLICY knowledge_read ON public."knowledge_candidate_currents" FOR SELECT TO pdos_next_app '
 "USING(public.category_access(tenant_id,category_id) AND (visibility='category' OR "
 'owner_id=public.scope_requester()) AND (knowledge_candidate_currents.product_id IS NULL OR '
 'EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id=knowledge_candidate_currents.tenant_id AND '
 'p.category_id=knowledge_candidate_currents.category_id AND '
 'p.id=knowledge_candidate_currents.product_id)) AND (knowledge_candidate_currents.project_id IS NULL '
 'OR EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=knowledge_candidate_currents.tenant_id '
 'AND p.category_id=knowledge_candidate_currents.category_id AND '
 'p.product_id=knowledge_candidate_currents.product_id AND '
 'p.id=knowledge_candidate_currents.project_id)) AND EXISTS(SELECT 1 FROM '
 'public.knowledge_candidate_versions fixed WHERE '
 'fixed.tenant_id=knowledge_candidate_currents.tenant_id AND '
 'fixed.category_id=knowledge_candidate_currents.category_id AND '
 'fixed.id=knowledge_candidate_currents.version_id AND '
 'fixed.revision=knowledge_candidate_currents.revision AND '
 'fixed.candidate_id=knowledge_candidate_currents.candidate_id AND '
 'ROW(fixed.product_id,fixed.project_id,fixed.owner_id,fixed.visibility) IS NOT DISTINCT FROM '
 'ROW(knowledge_candidate_currents.product_id,knowledge_candidate_currents.project_id,knowledge_candidate_currents.owner_id,knowledge_candidate_currents.visibility)))',
 'CREATE POLICY knowledge_insert ON public."knowledge_candidate_currents" FOR INSERT TO pdos_next_app '
 'WITH CHECK(public.category_access(tenant_id,category_id,true) AND '
 "public.category_access(tenant_id,category_id) AND (visibility='category' OR "
 'owner_id=public.scope_requester()) AND (knowledge_candidate_currents.product_id IS NULL OR '
 'EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id=knowledge_candidate_currents.tenant_id AND '
 'p.category_id=knowledge_candidate_currents.category_id AND '
 'p.id=knowledge_candidate_currents.product_id)) AND (knowledge_candidate_currents.project_id IS NULL '
 'OR EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=knowledge_candidate_currents.tenant_id '
 'AND p.category_id=knowledge_candidate_currents.category_id AND '
 'p.product_id=knowledge_candidate_currents.product_id AND '
 'p.id=knowledge_candidate_currents.project_id)))',
 'REVOKE ALL ON public."knowledge_candidate_currents" FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'GRANT SELECT,INSERT ON public."knowledge_candidate_currents" TO pdos_next_app',
 'CREATE POLICY knowledge_advance ON public."knowledge_candidate_currents" FOR UPDATE TO pdos_next_app '
 'USING(public.category_access(tenant_id,category_id,true) AND '
 "public.category_access(tenant_id,category_id) AND (visibility='category' OR "
 'owner_id=public.scope_requester()) AND (knowledge_candidate_currents.product_id IS NULL OR '
 'EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id=knowledge_candidate_currents.tenant_id AND '
 'p.category_id=knowledge_candidate_currents.category_id AND '
 'p.id=knowledge_candidate_currents.product_id)) AND (knowledge_candidate_currents.project_id IS NULL '
 'OR EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=knowledge_candidate_currents.tenant_id '
 'AND p.category_id=knowledge_candidate_currents.category_id AND '
 'p.product_id=knowledge_candidate_currents.product_id AND '
 'p.id=knowledge_candidate_currents.project_id)) AND EXISTS(SELECT 1 FROM '
 'public.knowledge_candidate_versions fixed WHERE '
 'fixed.tenant_id=knowledge_candidate_currents.tenant_id AND '
 'fixed.category_id=knowledge_candidate_currents.category_id AND '
 'fixed.id=knowledge_candidate_currents.version_id AND '
 'fixed.revision=knowledge_candidate_currents.revision AND '
 'fixed.candidate_id=knowledge_candidate_currents.candidate_id AND '
 'ROW(fixed.product_id,fixed.project_id,fixed.owner_id,fixed.visibility) IS NOT DISTINCT FROM '
 'ROW(knowledge_candidate_currents.product_id,knowledge_candidate_currents.project_id,knowledge_candidate_currents.owner_id,knowledge_candidate_currents.visibility))) '
 'WITH CHECK(public.category_access(tenant_id,category_id,true) AND '
 "public.category_access(tenant_id,category_id) AND (visibility='category' OR "
 'owner_id=public.scope_requester()) AND (knowledge_candidate_currents.product_id IS NULL OR '
 'EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id=knowledge_candidate_currents.tenant_id AND '
 'p.category_id=knowledge_candidate_currents.category_id AND '
 'p.id=knowledge_candidate_currents.product_id)) AND (knowledge_candidate_currents.project_id IS NULL '
 'OR EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=knowledge_candidate_currents.tenant_id '
 'AND p.category_id=knowledge_candidate_currents.category_id AND '
 'p.product_id=knowledge_candidate_currents.product_id AND '
 'p.id=knowledge_candidate_currents.project_id)))',
 'GRANT UPDATE(version_id,revision) ON public."knowledge_candidate_currents" TO pdos_next_app',
 'ALTER TABLE public."knowledge_applicability_assessments" ENABLE ROW LEVEL SECURITY',
 'ALTER TABLE public."knowledge_applicability_assessments" FORCE ROW LEVEL SECURITY',
 'CREATE POLICY owner_internal ON public."knowledge_applicability_assessments" TO pdos_next_owner '
 'USING(true) WITH CHECK(true)',
 'CREATE POLICY knowledge_read ON public."knowledge_applicability_assessments" FOR SELECT TO '
 "pdos_next_app USING(public.category_access(tenant_id,category_id) AND (visibility='category' OR "
 'owner_id=public.scope_requester()) AND (knowledge_applicability_assessments.product_id IS NULL OR '
 'EXISTS(SELECT 1 FROM public.products p WHERE '
 'p.tenant_id=knowledge_applicability_assessments.tenant_id AND '
 'p.category_id=knowledge_applicability_assessments.category_id AND '
 'p.id=knowledge_applicability_assessments.product_id)) AND '
 '(knowledge_applicability_assessments.project_id IS NULL OR EXISTS(SELECT 1 FROM public.projects p '
 'WHERE p.tenant_id=knowledge_applicability_assessments.tenant_id AND '
 'p.category_id=knowledge_applicability_assessments.category_id AND '
 'p.product_id=knowledge_applicability_assessments.product_id AND '
 'p.id=knowledge_applicability_assessments.project_id)) AND EXISTS(SELECT 1 FROM '
 'public.knowledge_rule_versions publication WHERE '
 'publication.tenant_id=knowledge_applicability_assessments.tenant_id AND '
 'publication.category_id=knowledge_applicability_assessments.category_id AND '
 'publication.id=knowledge_applicability_assessments.publication_id AND '
 'publication.assessment_id=knowledge_applicability_assessments.id AND '
 'publication.candidate_version_id=knowledge_applicability_assessments.candidate_version_id AND '
 'publication.candidate_revision=knowledge_applicability_assessments.candidate_revision AND '
 'ROW(publication.product_id,publication.project_id,publication.owner_id,publication.visibility) IS '
 'NOT DISTINCT FROM '
 'ROW(knowledge_applicability_assessments.product_id,knowledge_applicability_assessments.project_id,knowledge_applicability_assessments.owner_id,knowledge_applicability_assessments.visibility)))',
 'CREATE POLICY knowledge_insert ON public."knowledge_applicability_assessments" FOR INSERT TO '
 'pdos_next_app WITH CHECK(public.category_access(tenant_id,category_id,true) AND '
 'public.scope_actor()=public.scope_requester() AND EXISTS(SELECT 1 FROM public.principals h WHERE '
 "h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND h.id=public.scope_actor() "
 "AND h.kind='human' AND h.active) AND public.category_access(tenant_id,category_id) AND "
 "(visibility='category' OR owner_id=public.scope_requester()) AND "
 '(knowledge_applicability_assessments.product_id IS NULL OR EXISTS(SELECT 1 FROM public.products p '
 'WHERE p.tenant_id=knowledge_applicability_assessments.tenant_id AND '
 'p.category_id=knowledge_applicability_assessments.category_id AND '
 'p.id=knowledge_applicability_assessments.product_id)) AND '
 '(knowledge_applicability_assessments.project_id IS NULL OR EXISTS(SELECT 1 FROM public.projects p '
 'WHERE p.tenant_id=knowledge_applicability_assessments.tenant_id AND '
 'p.category_id=knowledge_applicability_assessments.category_id AND '
 'p.product_id=knowledge_applicability_assessments.product_id AND '
 'p.id=knowledge_applicability_assessments.project_id)))',
 'REVOKE ALL ON public."knowledge_applicability_assessments" FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'GRANT SELECT,INSERT ON public."knowledge_applicability_assessments" TO pdos_next_app',
 'ALTER TABLE public."knowledge_rule_versions" ENABLE ROW LEVEL SECURITY',
 'ALTER TABLE public."knowledge_rule_versions" FORCE ROW LEVEL SECURITY',
 'CREATE POLICY owner_internal ON public."knowledge_rule_versions" TO pdos_next_owner USING(true) WITH '
 'CHECK(true)',
 'CREATE POLICY knowledge_read ON public."knowledge_rule_versions" FOR SELECT TO pdos_next_app '
 "USING(public.category_access(tenant_id,category_id) AND (visibility='category' OR "
 'owner_id=public.scope_requester()) AND (knowledge_rule_versions.product_id IS NULL OR EXISTS(SELECT '
 '1 FROM public.products p WHERE p.tenant_id=knowledge_rule_versions.tenant_id AND '
 'p.category_id=knowledge_rule_versions.category_id AND p.id=knowledge_rule_versions.product_id)) AND '
 '(knowledge_rule_versions.project_id IS NULL OR EXISTS(SELECT 1 FROM public.projects p WHERE '
 'p.tenant_id=knowledge_rule_versions.tenant_id AND p.category_id=knowledge_rule_versions.category_id '
 'AND p.product_id=knowledge_rule_versions.product_id AND p.id=knowledge_rule_versions.project_id)) '
 'AND public.knowledge_content_sources_visible(tenant_id,category_id,product_id,source_basis) AND '
 '(public.knowledge_result_sources_visible(tenant_id,category_id,product_id,source_basis)))',
 'CREATE POLICY knowledge_insert ON public."knowledge_rule_versions" FOR INSERT TO pdos_next_app WITH '
 'CHECK(public.category_access(tenant_id,category_id,true) AND '
 'public.scope_actor()=public.scope_requester() AND EXISTS(SELECT 1 FROM public.principals h WHERE '
 "h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND h.id=public.scope_actor() "
 "AND h.kind='human' AND h.active) AND public.category_access(tenant_id,category_id) AND "
 "(visibility='category' OR owner_id=public.scope_requester()) AND (knowledge_rule_versions.product_id "
 'IS NULL OR EXISTS(SELECT 1 FROM public.products p WHERE '
 'p.tenant_id=knowledge_rule_versions.tenant_id AND p.category_id=knowledge_rule_versions.category_id '
 'AND p.id=knowledge_rule_versions.product_id)) AND (knowledge_rule_versions.project_id IS NULL OR '
 'EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=knowledge_rule_versions.tenant_id AND '
 'p.category_id=knowledge_rule_versions.category_id AND '
 'p.product_id=knowledge_rule_versions.product_id AND p.id=knowledge_rule_versions.project_id)))',
 'REVOKE ALL ON public."knowledge_rule_versions" FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'GRANT SELECT,INSERT ON public."knowledge_rule_versions" TO pdos_next_app',
 'ALTER TABLE public."knowledge_rule_currents" ENABLE ROW LEVEL SECURITY',
 'ALTER TABLE public."knowledge_rule_currents" FORCE ROW LEVEL SECURITY',
 'CREATE POLICY owner_internal ON public."knowledge_rule_currents" TO pdos_next_owner USING(true) WITH '
 'CHECK(true)',
 'CREATE POLICY knowledge_read ON public."knowledge_rule_currents" FOR SELECT TO pdos_next_app '
 "USING(public.category_access(tenant_id,category_id) AND (visibility='category' OR "
 'owner_id=public.scope_requester()) AND (knowledge_rule_currents.product_id IS NULL OR EXISTS(SELECT '
 '1 FROM public.products p WHERE p.tenant_id=knowledge_rule_currents.tenant_id AND '
 'p.category_id=knowledge_rule_currents.category_id AND p.id=knowledge_rule_currents.product_id)) AND '
 '(knowledge_rule_currents.project_id IS NULL OR EXISTS(SELECT 1 FROM public.projects p WHERE '
 'p.tenant_id=knowledge_rule_currents.tenant_id AND p.category_id=knowledge_rule_currents.category_id '
 'AND p.product_id=knowledge_rule_currents.product_id AND p.id=knowledge_rule_currents.project_id)) '
 'AND EXISTS(SELECT 1 FROM public.knowledge_rule_versions fixed WHERE '
 'fixed.tenant_id=knowledge_rule_currents.tenant_id AND '
 'fixed.category_id=knowledge_rule_currents.category_id AND '
 'fixed.id=knowledge_rule_currents.version_id AND fixed.revision=knowledge_rule_currents.revision AND '
 'fixed.rule_id=knowledge_rule_currents.rule_id AND '
 'ROW(fixed.product_id,fixed.project_id,fixed.owner_id,fixed.visibility) IS NOT DISTINCT FROM '
 'ROW(knowledge_rule_currents.product_id,knowledge_rule_currents.project_id,knowledge_rule_currents.owner_id,knowledge_rule_currents.visibility)))',
 'CREATE POLICY knowledge_insert ON public."knowledge_rule_currents" FOR INSERT TO pdos_next_app WITH '
 'CHECK(public.category_access(tenant_id,category_id,true) AND '
 'public.scope_actor()=public.scope_requester() AND EXISTS(SELECT 1 FROM public.principals h WHERE '
 "h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND h.id=public.scope_actor() "
 "AND h.kind='human' AND h.active) AND public.category_access(tenant_id,category_id) AND "
 "(visibility='category' OR owner_id=public.scope_requester()) AND (knowledge_rule_currents.product_id "
 'IS NULL OR EXISTS(SELECT 1 FROM public.products p WHERE '
 'p.tenant_id=knowledge_rule_currents.tenant_id AND p.category_id=knowledge_rule_currents.category_id '
 'AND p.id=knowledge_rule_currents.product_id)) AND (knowledge_rule_currents.project_id IS NULL OR '
 'EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=knowledge_rule_currents.tenant_id AND '
 'p.category_id=knowledge_rule_currents.category_id AND '
 'p.product_id=knowledge_rule_currents.product_id AND p.id=knowledge_rule_currents.project_id)))',
 'REVOKE ALL ON public."knowledge_rule_currents" FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'GRANT SELECT,INSERT ON public."knowledge_rule_currents" TO pdos_next_app',
 'CREATE POLICY knowledge_advance ON public."knowledge_rule_currents" FOR UPDATE TO pdos_next_app '
 'USING(public.category_access(tenant_id,category_id,true) AND '
 'public.scope_actor()=public.scope_requester() AND EXISTS(SELECT 1 FROM public.principals h WHERE '
 "h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND h.id=public.scope_actor() "
 "AND h.kind='human' AND h.active) AND public.category_access(tenant_id,category_id) AND "
 "(visibility='category' OR owner_id=public.scope_requester()) AND (knowledge_rule_currents.product_id "
 'IS NULL OR EXISTS(SELECT 1 FROM public.products p WHERE '
 'p.tenant_id=knowledge_rule_currents.tenant_id AND p.category_id=knowledge_rule_currents.category_id '
 'AND p.id=knowledge_rule_currents.product_id)) AND (knowledge_rule_currents.project_id IS NULL OR '
 'EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=knowledge_rule_currents.tenant_id AND '
 'p.category_id=knowledge_rule_currents.category_id AND '
 'p.product_id=knowledge_rule_currents.product_id AND p.id=knowledge_rule_currents.project_id)) AND '
 'EXISTS(SELECT 1 FROM public.knowledge_rule_versions fixed WHERE '
 'fixed.tenant_id=knowledge_rule_currents.tenant_id AND '
 'fixed.category_id=knowledge_rule_currents.category_id AND '
 'fixed.id=knowledge_rule_currents.version_id AND fixed.revision=knowledge_rule_currents.revision AND '
 'fixed.rule_id=knowledge_rule_currents.rule_id AND '
 'ROW(fixed.product_id,fixed.project_id,fixed.owner_id,fixed.visibility) IS NOT DISTINCT FROM '
 'ROW(knowledge_rule_currents.product_id,knowledge_rule_currents.project_id,knowledge_rule_currents.owner_id,knowledge_rule_currents.visibility))) '
 'WITH CHECK(public.category_access(tenant_id,category_id,true) AND '
 'public.scope_actor()=public.scope_requester() AND EXISTS(SELECT 1 FROM public.principals h WHERE '
 "h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND h.id=public.scope_actor() "
 "AND h.kind='human' AND h.active) AND public.category_access(tenant_id,category_id) AND "
 "(visibility='category' OR owner_id=public.scope_requester()) AND (knowledge_rule_currents.product_id "
 'IS NULL OR EXISTS(SELECT 1 FROM public.products p WHERE '
 'p.tenant_id=knowledge_rule_currents.tenant_id AND p.category_id=knowledge_rule_currents.category_id '
 'AND p.id=knowledge_rule_currents.product_id)) AND (knowledge_rule_currents.project_id IS NULL OR '
 'EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=knowledge_rule_currents.tenant_id AND '
 'p.category_id=knowledge_rule_currents.category_id AND '
 'p.product_id=knowledge_rule_currents.product_id AND p.id=knowledge_rule_currents.project_id)))',
 'GRANT UPDATE(version_id,revision) ON public."knowledge_rule_currents" TO pdos_next_app',
 'CREATE TRIGGER knowledge_candidate_immutable BEFORE UPDATE OR DELETE ON '
 'public.knowledge_candidate_versions FOR EACH ROW EXECUTE FUNCTION public.reject_knowledge_mutation()',
 'CREATE CONSTRAINT TRIGGER knowledge_candidate_atom AFTER INSERT ON '
 'public.knowledge_candidate_versions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION '
 'public.require_knowledge_candidate()',
 'CREATE TRIGGER knowledge_rule_immutable BEFORE UPDATE OR DELETE ON public.knowledge_rule_versions '
 'FOR EACH ROW EXECUTE FUNCTION public.reject_knowledge_mutation()',
 'CREATE CONSTRAINT TRIGGER knowledge_rule_atom AFTER INSERT ON public.knowledge_rule_versions '
 'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_knowledge_rule()',
 'CREATE TRIGGER knowledge_assessment_immutable BEFORE UPDATE OR DELETE ON '
 'public.knowledge_applicability_assessments FOR EACH ROW EXECUTE FUNCTION '
 'public.reject_knowledge_mutation()',
 'CREATE CONSTRAINT TRIGGER knowledge_assessment_atom AFTER INSERT ON '
 'public.knowledge_applicability_assessments DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE '
 'FUNCTION public.require_knowledge_assessment()',
 'CREATE TRIGGER knowledge_candidate_current_guard BEFORE INSERT OR UPDATE OR DELETE ON '
 'public.knowledge_candidate_currents FOR EACH ROW EXECUTE FUNCTION '
 'public.protect_knowledge_candidate_current()',
 'CREATE CONSTRAINT TRIGGER knowledge_candidate_current_atom AFTER INSERT OR UPDATE ON '
 'public.knowledge_candidate_currents DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION '
 'public.require_knowledge_candidate_current()',
 'CREATE TRIGGER knowledge_rule_current_guard BEFORE INSERT OR UPDATE OR DELETE ON '
 'public.knowledge_rule_currents FOR EACH ROW EXECUTE FUNCTION public.protect_knowledge_rule_current()',
 'CREATE CONSTRAINT TRIGGER knowledge_rule_current_atom AFTER INSERT OR UPDATE ON '
 'public.knowledge_rule_currents DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION '
 'public.require_knowledge_rule_current()',
 'CREATE TRIGGER protect_knowledge_receipt BEFORE INSERT OR UPDATE OR DELETE ON public.action_receipts '
 'FOR EACH ROW EXECUTE FUNCTION public.protect_knowledge_receipt()',
 'CREATE TRIGGER protect_knowledge_confirmation BEFORE INSERT OR UPDATE OR DELETE ON '
 'public.confirmations FOR EACH ROW EXECUTE FUNCTION public.protect_knowledge_confirmation()',
 'CREATE CONSTRAINT TRIGGER require_knowledge_confirmation AFTER UPDATE ON public.confirmations '
 'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_knowledge_confirmation()',
 'CREATE CONSTRAINT TRIGGER require_knowledge_member AFTER INSERT ON public.action_receipts DEFERRABLE '
 'INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_knowledge_member()',
 'CREATE TRIGGER protect_knowledge_member BEFORE INSERT OR UPDATE OR DELETE ON public.audit_entries '
 'FOR EACH ROW EXECUTE FUNCTION public.protect_knowledge_member()',
 'CREATE CONSTRAINT TRIGGER require_knowledge_member AFTER INSERT ON public.audit_entries DEFERRABLE '
 'INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_knowledge_member()',
 'CREATE TRIGGER protect_knowledge_member BEFORE INSERT OR UPDATE OR DELETE ON public.outbox_events '
 'FOR EACH ROW EXECUTE FUNCTION public.protect_knowledge_member()',
 'CREATE CONSTRAINT TRIGGER require_knowledge_member AFTER INSERT ON public.outbox_events DEFERRABLE '
 'INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_knowledge_member()',
 'CREATE TRIGGER protect_knowledge_member BEFORE INSERT OR UPDATE OR DELETE ON public.request_keys FOR '
 'EACH ROW EXECUTE FUNCTION public.protect_knowledge_member()',
 'CREATE CONSTRAINT TRIGGER require_knowledge_member AFTER INSERT ON public.request_keys DEFERRABLE '
 'INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_knowledge_member()',
 'ALTER TABLE public.professional_authority_facts DROP CONSTRAINT professional_authority_facts_check',
 'ALTER TABLE public.professional_authority_facts ADD CONSTRAINT professional_authority_facts_check '
 "CHECK ((((kind)::text = ANY ((ARRAY['duty'::character varying, 'qualification'::character "
 "varying])::text[])) AND ((role)::text = ANY ((ARRAY['engineering'::character varying, "
 "'quality'::character varying, 'manufacturing'::character varying, 'knowledge'::character "
 "varying])::text[])) AND ((nature)::text = ANY ((ARRAY['real'::character varying, "
 "'synthetic'::character varying])::text[]))))",
 'CREATE OR REPLACE FUNCTION public.m3_lifecycle_row_links(t uuid, c uuid, table_name text, payload '
 'jsonb)\n'
 ' RETURNS uuid[]\n'
 ' LANGUAGE plpgsql\n'
 ' STABLE SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 'DECLARE links uuid[]; key text; keys text[];\n'
 'BEGIN\n'
 ' links=public.m3_lifecycle_source_links(t,c,table_name,payload);\n'
 ' -- Only the infrequent retention summary needs host/reverse relationships.\n'
 ' -- They must not turn a source-free item INSERT into a proposal-history scan.\n'
 ' keys=CASE table_name\n'
 "  WHEN 'definition_sources' THEN ARRAY['definition_id']\n"
 "  WHEN 'definition_specs' THEN ARRAY['definition_id']\n"
 "  WHEN 'proposal_items' THEN ARRAY['proposal_id']\n"
 "  WHEN 'proposal_item_versions' THEN ARRAY['proposal_id','item_id']\n"
 "  WHEN 'proposal_sources' THEN ARRAY['proposal_id']\n"
 "  WHEN 'proposal_submissions' THEN ARRAY['proposal_id']\n"
 "  WHEN 'proposal_decisions' THEN ARRAY['proposal_id','created_definition_id']\n"
 "  WHEN 'evidence_links' THEN ARRAY['target_id']\n"
 "  WHEN 'manufacturing_baseline_publications' THEN ARRAY['project_id']\n"
 "  WHEN 'manufacturing_publication_currents' THEN ARRAY['series_id']\n"
 "  WHEN 'manufacturing_publication_documents' THEN ARRAY['publication_id']\n"
 "  WHEN 'native_pilot_runs' THEN ARRAY['project_id']\n"
 "  WHEN 'native_pilot_currents' THEN ARRAY['pilot_id']\n"
 "  WHEN 'native_pilot_observations' THEN ARRAY['pilot_id']\n"
 "  WHEN 'release_packages' THEN ARRAY['project_id','series_id']\n"
 "  WHEN 'release_package_currents' THEN ARRAY['series_id']\n"
 "  WHEN 'release_decisions' THEN ARRAY['package_id']\n"
 "  WHEN 'release_policy_facts' THEN ARRAY['project_id','series_id']\n"
 "  WHEN 'release_policy_currents' THEN ARRAY['series_id']\n"
 "  WHEN 'external_handoff_authorizations' THEN ARRAY['project_id']\n"
 "  WHEN 'external_delivery_intents' THEN ARRAY['project_id']\n"
 "  WHEN 'external_receipts' THEN ARRAY['project_id']\n"
 "  WHEN 'external_handoff_currents' THEN ARRAY['project_id']\n"
 "  WHEN 'release_exception_decisions' THEN ARRAY['project_id','series_id']\n"
 "  WHEN 'release_exception_currents' THEN ARRAY['project_id','series_id']\n"
 "  WHEN 'work_commitment_reviews' THEN ARRAY['project_id']\n"
 "  WHEN 'work_commitment_review_currents' THEN ARRAY['project_id']\n"
 "  WHEN 'external_wait_versions' THEN ARRAY['project_id']\n"
 "  WHEN 'external_wait_currents' THEN ARRAY['project_id']\n"
 "  WHEN 'project_risk_followups' THEN ARRAY['project_id']\n"
 "  WHEN 'knowledge_candidate_versions' THEN ARRAY['project_id']\n"
 "  WHEN 'knowledge_candidate_currents' THEN ARRAY['project_id']\n"
 "  WHEN 'knowledge_applicability_assessments' THEN ARRAY['project_id']\n"
 "  WHEN 'knowledge_rule_versions' THEN ARRAY['project_id']\n"
 "  WHEN 'knowledge_rule_currents' THEN ARRAY['project_id']\n"
 "  WHEN 'project_risk_followup_currents' THEN ARRAY['project_id']\n"
 "  WHEN 'work_task_versions' THEN ARRAY['project_id']\n"
 "  WHEN 'work_task_currents' THEN ARRAY['project_id']\n"
 "  WHEN 'work_commitment_versions' THEN ARRAY['project_id']\n"
 "  WHEN 'work_commitment_currents' THEN ARRAY['project_id']\n"
 "  WHEN 'project_status_updates' THEN ARRAY['project_id']\n"
 '  ELSE ARRAY[]::text[] END;\n'
 ' FOREACH key IN ARRAY keys LOOP\n'
 '  IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n'
 ' END LOOP;\n'
 ' RETURN links;\n'
 'END;\n'
 '$function$\n',
 'CREATE OR REPLACE FUNCTION public.m3_lifecycle_nodes(t uuid, c uuid, identities uuid[] DEFAULT '
 'NULL::uuid[])\n'
 ' RETURNS TABLE(table_name text, node_id uuid, links uuid[])\n'
 ' LANGUAGE plpgsql\n'
 ' STABLE SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 'DECLARE name text; payload jsonb; controls uuid[];\n'
 'BEGIN\n'
 ' IF identities IS NULL THEN\n'
 "  SELECT coalesce(array_agg(id),'{}') INTO controls FROM public.action_receipts\n"
 "   WHERE tenant_id=t AND category_id=c AND operation LIKE 'evidence.lifecycle.%';\n"
 " ELSE controls='{}'; END IF;\n"
 ' FOREACH name IN ARRAY CASE WHEN identities IS NULL THEN '
 "ARRAY['agent_runs','action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','project_risk_followups','project_risk_followup_currents','knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents'] "
 'ELSE ARRAY[\n'
 "  'artifact_versions','claims','definition_revisions','definition_sources','definition_specs',\n"
 '  '
 "'proposals','proposal_items','proposal_item_versions','proposal_submissions','proposal_decisions',\n"
 '  '
 "'category_knowledge_entries','category_knowledge_current','parameter_versions','parameter_current',\n"
 '  '
 "'evidence_links','promotion_proofs','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','project_risk_followups','project_risk_followup_currents','knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents'] "
 'END LOOP\n'
 "  FOR payload IN EXECUTE CASE WHEN name=ANY(ARRAY['audit_entries','outbox_events','request_keys'])\n"
 "   THEN format('SELECT to_jsonb(x) FROM public.%I x JOIN public.action_receipts r ON "
 "r.id=x.receipt_id AND r.tenant_id=x.tenant_id WHERE x.tenant_id=$1 AND r.category_id=$2',name)\n"
 "   ELSE format('SELECT to_jsonb(x) FROM public.%I x WHERE tenant_id=$1 AND category_id=$2 AND ($3 IS "
 "NULL OR %I=ANY($3))',name,\n"
 "    CASE name WHEN 'category_knowledge_current' THEN 'lineage_id'\n"
 "     WHEN 'parameter_current' THEN 'parameter_id' ELSE 'id' END)\n"
 '   END USING t,c,identities LOOP\n'
 "   IF (payload->>'receipt_id')::uuid=ANY(controls) OR\n"
 "    (name='action_receipts' AND payload->>'operation' LIKE 'evidence.lifecycle.%') THEN CONTINUE; "
 'END IF;\n'
 '   table_name=name;\n'
 "   node_id=CASE name WHEN 'category_knowledge_current' THEN (payload->>'lineage_id')::uuid\n"
 "    WHEN 'parameter_current' THEN (payload->>'parameter_id')::uuid ELSE (payload->>'id')::uuid END;\n"
 '   IF identities IS NULL THEN links=public.m3_lifecycle_row_links(t,c,name,payload);\n'
 '   ELSE links=public.m3_lifecycle_source_links(t,c,name,payload); END IF;\n'
 "   -- Preserve predecessor's conservative legacy graph; M3-only nodes use\n"
 '   -- strictly typed/relational links. Root lookup never uses free-text UUIDs.\n'
 '   IF identities IS NULL AND '
 "name<>ALL(ARRAY['native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','project_risk_followups','project_risk_followup_currents','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents']) "
 'THEN\n'
 '    links=links || public.kernel_lifecycle_links(name,payload);\n'
 '   END IF;\n'
 '   RETURN NEXT;\n'
 '  END LOOP;\n'
 ' END LOOP;\n'
 'END;\n'
 '$function$\n',
 'CREATE OR REPLACE FUNCTION public.m3_lifecycle_source_links(t uuid, c uuid, table_name text, payload '
 'jsonb)\n'
 ' RETURNS uuid[]\n'
 ' LANGUAGE plpgsql\n'
 ' STABLE SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 "DECLARE links uuid[]='{}'; extra uuid[]; key text; keys text[]; item jsonb; container jsonb;\n"
 ' target_kind text; referenced_target uuid; referenced_version integer;\n'
 'BEGIN\n'
 " IF table_name='agent_runs' THEN RETURN public.kernel_lifecycle_links(table_name,payload); END IF;\n"
 ' -- Only actual top-level relation columns establish raw UUID edges. Arbitrary\n'
 ' -- content dictionaries are not relational rows, even if an extra key happens\n'
 ' -- to be named source_id or item_id.\n'
 ' keys=CASE table_name\n'
 "  WHEN 'artifact_versions' THEN ARRAY['original_id']\n"
 "  WHEN 'claims' THEN ARRAY['artifact_id','snapshot_id']\n"
 "  WHEN 'definition_revisions' THEN ARRAY['derived_from_definition_id','parent_definition_id',\n"
 "   'source_proposal_id','source_submission_id']\n"
 "  WHEN 'definition_sources' THEN ARRAY['artifact_id']\n"
 "  WHEN 'definition_specs' THEN ARRAY[]::text[]\n"
 "  WHEN 'proposals' THEN ARRAY['baseline_definition_id','current_submission_id']\n"
 "  WHEN 'proposal_items' THEN ARRAY[]::text[]\n"
 "  WHEN 'proposal_item_versions' THEN ARRAY[]::text[]\n"
 "  WHEN 'proposal_revisions' THEN ARRAY['proposal_id']\n"
 "  WHEN 'proposal_sources' THEN ARRAY['source_id']\n"
 "  WHEN 'proposal_submissions' THEN ARRAY[]::text[]\n"
 "  WHEN 'proposal_decisions' THEN ARRAY['submission_id']\n"
 "  WHEN 'project_open_items' THEN ARRAY['source_question_id','source_spec_item_id','g0_decision_id']\n"
 "  WHEN 'category_knowledge_current' THEN ARRAY['current_entry_id']\n"
 "  WHEN 'promotion_proofs' THEN ARRAY['knowledge_entry_id','source_proposal_id']\n"
 "  WHEN 'evidence_links' THEN ARRAY['evidence_id']\n"
 "  WHEN 'claim_withdrawals' THEN ARRAY['claim_id']\n"
 "  WHEN 'manufacturing_baseline_publications' THEN ARRAY['baseline_id','process_id','previous_id']\n"
 "  WHEN 'manufacturing_publication_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'manufacturing_publication_documents' THEN ARRAY['document_id','process_id']\n"
 "  WHEN 'native_pilot_runs' THEN "
 "ARRAY['build_id','lot_id','actual_configuration_id','engineering_configuration_id','process_id','publication_id']\n"
 "  WHEN 'native_pilot_currents' THEN ARRAY['pilot_id','latest_observation_id']\n"
 "  WHEN 'native_pilot_observations' THEN ARRAY['pilot_id','previous_observation_id']\n"
 "  WHEN 'release_packages' THEN ARRAY['previous_id']\n"
 "  WHEN 'release_package_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'release_decisions' THEN ARRAY['package_id']\n"
 "  WHEN 'release_policy_facts' THEN ARRAY['previous_id']\n"
 "  WHEN 'release_policy_currents' THEN ARRAY['fact_id']\n"
 "  WHEN 'external_handoff_authorizations' THEN "
 "ARRAY['package_id','engineering_decision_id','manufacturing_decision_id']\n"
 "  WHEN 'external_delivery_intents' THEN ARRAY['handoff_id']\n"
 "  WHEN 'external_receipts' THEN "
 "ARRAY['handoff_id','intent_id','previous_receipt_id','reconciles_id']\n"
 "  WHEN 'external_handoff_currents' THEN ARRAY['handoff_id','intent_id','latest_receipt_id']\n"
 "  WHEN 'release_exception_decisions' THEN ARRAY['basis_package_id','policy_fact_id','previous_id']\n"
 "  WHEN 'release_exception_currents' THEN ARRAY['basis_package_id','policy_fact_id','decision_id']\n"
 "  WHEN 'work_commitment_reviews' THEN "
 "ARRAY['commitment_id','task_version_id','submission_id','previous_id']\n"
 "  WHEN 'work_commitment_review_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'external_wait_versions' THEN ARRAY['previous_id']\n"
 "  WHEN 'external_wait_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'project_risk_followups' THEN ARRAY['previous_id','risk_id','g0_decision_id']\n"
 "  WHEN 'project_risk_followup_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'work_task_versions' THEN ARRAY['previous_id']\n"
 "  WHEN 'work_task_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'work_commitment_versions' THEN ARRAY['replaces_id']\n"
 "  WHEN 'work_commitment_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'project_status_updates' THEN ARRAY[]::text[]\n"
 '  ELSE ARRAY[]::text[] END;\n'
 ' FOREACH key IN ARRAY keys LOOP\n'
 '  IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n'
 ' END LOOP;\n'
 " -- Publication's exact saved read set is a validated Artifact relationship.\n"
 ' -- Do not scan its declaration, body, reason or arbitrary JSON UUID values.\n'
 ' IF table_name IN '
 "('manufacturing_baseline_publications','native_pilot_runs','native_pilot_observations','release_packages','release_decisions','release_policy_facts','external_handoff_authorizations','external_receipts','release_exception_decisions') "
 'THEN\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload->'required_source_read_set','[]')) LOOP\n"
 "   IF item->>'artifact_id' IS NOT NULL THEN\n"
 "    links=array_append(links,(item->>'artifact_id')::uuid);\n"
 '   END IF;\n'
 '  END LOOP;\n'
 ' END IF;\n'
 " IF table_name IN ('native_pilot_runs','native_pilot_observations') THEN\n"
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{material_snapshot,statistics,samples}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{material_snapshot,statistics,issues}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  item=payload#>'{material_snapshot,statistics,resource,fact}';\n"
 "  IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 ' END IF;\n'
 " IF table_name='release_packages' THEN\n"
 '  -- FixedObject.ref is a closed, server-resolved version reference, not arbitrary body UUID text.\n'
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{body,objects}','[]')) LOOP\n"
 "   container=item->'ref';\n"
 '   IF '
 "container->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','manufacturing_publication','test_run','pilot_run','issue','change','exception','artifact','work_instruction','control_plan','build_lot','line'])\n"
 "    AND container->>'id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); END "
 'IF;\n'
 '  END LOOP;\n'
 ' END IF;\n'
 " IF table_name IN ('external_handoff_authorizations','external_delivery_intents') THEN\n"
 '  -- Only closed, owner-verified mapping and manifest references are source edges.\n'
 "  container=CASE WHEN table_name='external_handoff_authorizations' THEN "
 "payload#>'{body,declaration}' ELSE payload->'body' END;\n"
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'mappings','[]')) LOOP\n"
 '   IF '
 "item->'ref'->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','part','bom_revision','artifact','work_instruction','control_plan'])\n"
 "    AND item->'ref'->>'id' IS NOT NULL THEN links=array_append(links,(item->'ref'->>'id')::uuid); "
 'END IF;\n'
 '  END LOOP;\n'
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'manifest','[]')) LOOP\n"
 "   IF item->'artifact'->>'id' IS NOT NULL THEN "
 "links=array_append(links,(item->'artifact'->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 " IF table_name='release_policy_facts' THEN\n"
 '  -- These are Closed DTO configuration references fixed by the policy owner.\n'
 "  FOREACH key IN ARRAY ARRAY['definition','engineering_configuration','manufacturing_configuration'] "
 'LOOP\n'
 "   container=payload#>ARRAY['material','subject_config',key];\n"
 "   IF container->>'id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 ' -- These stored fields are validated Reference containers. Do not feed the\n'
 ' -- whole row or arbitrary content into the canonical Reference parser.\n'
 " IF table_name=ANY(ARRAY['proposals','proposal_item_versions','proposal_submissions',\n"
 "  'category_knowledge_entries','definition_specs']) THEN\n"
 '  FOREACH key IN ARRAY '
 "ARRAY['source_refs','direct_source_refs','context_refs','baseline_claim_refs'] LOOP\n"
 '   links=links || public.m3_lifecycle_typed_links(t,c,payload->key);\n'
 '  END LOOP;\n'
 ' END IF;\n'
 ' -- Match ItemInput.content_schema and category_service._references: only\n'
 ' -- commercial_target, voice, and competitor have nested source contracts.\n'
 " IF table_name='proposal_item_versions' AND payload->>'kind'='commercial_target' THEN\n"
 "  FOREACH key IN ARRAY ARRAY['target_price','cost','volume'] LOOP\n"
 "   links=links || public.m3_lifecycle_typed_links(t,c,payload->'content'->key->'source');\n"
 '  END LOOP;\n'
 " ELSIF table_name='category_knowledge_entries' AND payload->>'kind'='voice' THEN\n"
 "  links=links || public.m3_lifecycle_typed_links(t,c,payload->'content'->'representative_refs');\n"
 " ELSIF table_name='category_knowledge_entries' AND payload->>'kind'='competitor' THEN\n"
 "  FOREACH key IN ARRAY ARRAY['metrics','features','prices'] LOOP\n"
 "   FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'content'->key,'[]')) LOOP\n"
 "    links=links || public.m3_lifecycle_typed_links(t,c,item->'source_ref');\n"
 '   END LOOP;\n'
 '  END LOOP;\n'
 ' END IF;\n'
 " IF table_name='proposal_submissions' THEN\n"
 "  container=payload->'frozen_document';\n"
 '  FOREACH key IN ARRAY '
 "ARRAY['source_refs','direct_source_refs','context_refs','baseline_claim_refs'] LOOP\n"
 '   links=links || public.m3_lifecycle_typed_links(t,c,container->key);\n'
 '  END LOOP;\n'
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'items','[]')) LOOP\n"
 '   links=links || '
 "public.m3_lifecycle_source_links(t,c,'proposal_item_versions',item-ARRAY['item_id','proposal_id']);\n"
 '   -- The frozen read projection records actual EvidenceLink provenance here.\n'
 "   links=links || public.m3_lifecycle_typed_links(t,c,item->'evidence_links');\n"
 '  END LOOP;\n'
 " ELSIF table_name='promotion_proofs' THEN\n"
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'source_item_refs','[]')) "
 'LOOP\n'
 "   IF item->>'item_id' IS NOT NULL THEN links=array_append(links,(item->>'item_id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 ' -- Exact persisted EvidenceLink targets supplement these immutable versions.\n'
 ' -- Reverted links and withdrawn Claims still retain the original historical\n'
 ' -- dependency; lifecycle cleanup must not erase their audit source.\n'
 " IF table_name='proposal_item_versions' AND payload->>'item_id' IS NOT NULL THEN\n"
 "  target_kind='proposal_item'; referenced_target=(payload->>'item_id')::uuid;\n"
 "  referenced_version=(payload->>'version')::integer;\n"
 " ELSIF table_name='category_knowledge_entries' AND payload->>'id' IS NOT NULL THEN\n"
 "  target_kind='knowledge_entry'; referenced_target=(payload->>'id')::uuid;\n"
 "  referenced_version=(payload->>'version')::integer;\n"
 " ELSIF table_name='definition_specs' AND payload->>'id' IS NOT NULL THEN\n"
 "  target_kind='definition_spec'; referenced_target=(payload->>'id')::uuid;\n"
 '  SELECT revision INTO referenced_version FROM public.definition_revisions\n'
 "   WHERE tenant_id=t AND category_id=c AND id=(payload->>'definition_id')::uuid;\n"
 ' END IF;\n'
 ' IF referenced_target IS NOT NULL AND referenced_version IS NOT NULL THEN\n'
 "  SELECT coalesce(array_agg(link.evidence_id),'{}') INTO extra FROM public.evidence_links link\n"
 '   WHERE link.tenant_id=t AND link.category_id=c AND link.target_type=target_kind\n'
 '    AND link.target_id=referenced_target AND link.target_version=referenced_version;\n'
 '  links=links || extra;\n'
 ' END IF;\n'
 ' -- Child source rows point to their parent, whereas dependency traversal needs\n'
 " -- the parent's fixed source children as well. Keep the actual relational edge.\n"
 " IF table_name='definition_revisions' THEN\n"
 "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM (\n"
 '   SELECT id FROM public.definition_sources WHERE tenant_id=t AND category_id=c\n'
 "    AND definition_id=(payload->>'id')::uuid\n"
 '   UNION ALL SELECT id FROM public.definition_specs WHERE tenant_id=t AND category_id=c\n'
 "    AND definition_id=(payload->>'id')::uuid\n"
 '  ) children;\n'
 '  links=links || extra;\n'
 " ELSIF table_name='proposals' THEN\n"
 "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.proposal_item_versions\n"
 "   WHERE tenant_id=t AND category_id=c AND proposal_id=(payload->>'id')::uuid;\n"
 '  links=links || extra;\n'
 " ELSIF table_name='proposal_items' THEN\n"
 "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.proposal_item_versions\n"
 "   WHERE tenant_id=t AND category_id=c AND item_id=(payload->>'id')::uuid;\n"
 '  links=links || extra;\n'
 " ELSIF table_name='product_target_segments' THEN\n"
 "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.category_knowledge_entries\n"
 "   WHERE tenant_id=t AND category_id=c AND lineage_id=(payload->>'segment_lineage_id')::uuid\n"
 "    AND version=(payload->>'segment_version')::integer;\n"
 '  links=links || extra;\n'
 " ELSIF table_name='parameter_current' THEN\n"
 "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.parameter_versions\n"
 "   WHERE tenant_id=t AND category_id=c AND parameter_id=(payload->>'parameter_id')::uuid\n"
 "    AND version=(payload->>'current_version')::integer;\n"
 '  links=links || extra;\n'
 ' END IF;\n'
 '\n'
 " IF table_name IN ('work_task_versions','work_commitment_versions','project_status_updates') THEN\n"
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP\n"
 "   IF item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'artifact_id')::uuid); "
 'END IF;\n'
 '  END LOOP;\n'
 "  IF table_name='work_task_versions' AND payload#>>'{body,plan_task,id}' IS NOT NULL THEN\n"
 "   links=array_append(links,(payload#>>'{body,plan_task,id}')::uuid);\n"
 '  END IF;\n'
 "  IF table_name='work_commitment_versions' THEN\n"
 "   SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.work_task_versions\n"
 "    WHERE tenant_id=t AND category_id=c AND task_id=(payload->>'task_id')::uuid AND "
 "revision=(payload->>'task_revision')::integer;\n"
 '   links=links||extra;\n'
 "  ELSIF table_name='project_status_updates' THEN\n"
 "   FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'task_refs','[]')) LOOP\n"
 "    SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.work_task_versions\n"
 "     WHERE tenant_id=t AND category_id=c AND task_id=(item->>'id')::uuid AND "
 "revision=(item->>'revision')::integer;\n"
 '    links=links||extra;\n'
 '   END LOOP;\n'
 '  END IF;\n'
 ' END IF;\n'
 '\n'
 " IF table_name='work_commitment_reviews' THEN\n"
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP\n"
 "   IF item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'artifact_id')::uuid); "
 'END IF;\n'
 '  END LOOP;\n'
 ' END IF;\n'
 '\n'
 " IF table_name='external_wait_versions' THEN\n"
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  FOREACH key IN ARRAY ARRAY['milestone','build','calendar'] LOOP\n"
 "   container=payload#>ARRAY['body',key];\n"
 "   IF container->>'id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  container=payload#>'{body,replaces}';\n"
 "  IF container->>'id' IS NOT NULL THEN\n"
 "   SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.external_wait_versions\n"
 "    WHERE tenant_id=t AND category_id=c AND wait_id=(container->>'id')::uuid AND "
 "revision=(container->>'revision')::integer;\n"
 '   links=links||extra;\n'
 '  END IF;\n'
 ' END IF;\n'
 " IF table_name='project_risk_followups' THEN\n"
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 '\n'
 ' IF table_name IN '
 "('knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents') "
 'THEN\n'
 '  FOREACH key IN ARRAY '
 "ARRAY['previous_id','version_id','candidate_version_id','assessment_id','publication_id'] LOOP\n"
 '   IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n'
 '  END LOOP;\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP\n"
 "   IF item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'artifact_id')::uuid); "
 'END IF;\n'
 '  END LOOP;\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,result_receipts}','[]')) LOOP\n"
 "   IF item->>'receipt_id' IS NOT NULL THEN links=array_append(links,(item->>'receipt_id')::uuid); "
 'END IF;\n'
 "   IF item->>'row_id' IS NOT NULL THEN links=array_append(links,(item->>'row_id')::uuid); END IF;\n"
 '  END LOOP;\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,professional,fact_refs}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  IF payload#>>'{source_basis,target,id}' IS NOT NULL THEN "
 "links=array_append(links,(payload#>>'{source_basis,target,id}')::uuid); END IF;\n"
 ' END IF;\n'
 ' RETURN links;\n'
 'END;\n'
 '$function$\n',
 'CREATE POLICY knowledge_receipt_content ON public.action_receipts AS RESTRICTIVE FOR SELECT TO '
 "pdos_next_app USING(((subject_type NOT IN ('knowledge_candidate','design_rule')) OR\n"
 " (subject_type='knowledge_candidate' AND EXISTS(SELECT 1 FROM public.knowledge_candidate_versions k "
 'WHERE k.tenant_id=action_receipts.tenant_id AND k.category_id=action_receipts.category_id AND '
 'k.product_id IS NOT DISTINCT FROM action_receipts.product_id AND k.id=action_receipts.subject_id AND '
 'k.revision=action_receipts.subject_revision AND k.receipt_id=action_receipts.id AND '
 'k.operation=action_receipts.operation AND k.actor_id=action_receipts.actor_id)) OR\n'
 " (subject_type='design_rule' AND EXISTS(SELECT 1 FROM public.knowledge_rule_versions k WHERE "
 'k.tenant_id=action_receipts.tenant_id AND k.category_id=action_receipts.category_id AND '
 'k.product_id=action_receipts.product_id AND k.id=action_receipts.subject_id AND '
 'k.revision=action_receipts.subject_revision AND k.receipt_id=action_receipts.id AND '
 'k.operation=action_receipts.operation AND k.actor_id=action_receipts.actor_id))))',
 'CREATE POLICY knowledge_receipt_owner ON public.action_receipts FOR SELECT TO pdos_next_app '
 "USING(subject_type IN ('knowledge_candidate','design_rule') AND ((subject_type NOT IN "
 "('knowledge_candidate','design_rule')) OR\n"
 " (subject_type='knowledge_candidate' AND EXISTS(SELECT 1 FROM public.knowledge_candidate_versions k "
 'WHERE k.tenant_id=action_receipts.tenant_id AND k.category_id=action_receipts.category_id AND '
 'k.product_id IS NOT DISTINCT FROM action_receipts.product_id AND k.id=action_receipts.subject_id AND '
 'k.revision=action_receipts.subject_revision AND k.receipt_id=action_receipts.id AND '
 'k.operation=action_receipts.operation AND k.actor_id=action_receipts.actor_id)) OR\n'
 " (subject_type='design_rule' AND EXISTS(SELECT 1 FROM public.knowledge_rule_versions k WHERE "
 'k.tenant_id=action_receipts.tenant_id AND k.category_id=action_receipts.category_id AND '
 'k.product_id=action_receipts.product_id AND k.id=action_receipts.subject_id AND '
 'k.revision=action_receipts.subject_revision AND k.receipt_id=action_receipts.id AND '
 'k.operation=action_receipts.operation AND k.actor_id=action_receipts.actor_id))))')

DOWNGRADE_SQL = ('LOCK TABLE '
 'public.knowledge_candidate_versions,public.knowledge_candidate_currents,public.knowledge_applicability_assessments,public.knowledge_rule_versions,public.knowledge_rule_currents,public.action_receipts,public.confirmations '
 'IN ACCESS EXCLUSIVE MODE',
 'DO $knowledge$ BEGIN IF EXISTS(SELECT 1 FROM public.knowledge_candidate_versions) OR EXISTS(SELECT 1 '
 'FROM public.knowledge_candidate_currents) OR EXISTS(SELECT 1 FROM '
 'public.knowledge_applicability_assessments) OR EXISTS(SELECT 1 FROM public.knowledge_rule_versions) '
 'OR EXISTS(SELECT 1 FROM public.knowledge_rule_currents) OR EXISTS(SELECT 1 FROM '
 "public.action_receipts WHERE operation IN ('knowledge.candidate.create','knowledge.rule.publish') OR "
 "subject_type IN ('knowledge_candidate','design_rule')) OR EXISTS(SELECT 1 FROM public.confirmations "
 "WHERE operation='knowledge.rule.publish') THEN RAISE EXCEPTION 'Knowledge history retained; "
 "downgrade refused' USING ERRCODE='23514'; END IF; END; $knowledge$",
 'DO $knowledge$ BEGIN IF EXISTS(SELECT 1 FROM public.professional_authority_facts WHERE '
 "role='knowledge') THEN RAISE EXCEPTION 'Knowledge professional history retained; downgrade refused' "
 "USING ERRCODE='23514'; END IF; END; $knowledge$",
 'DROP POLICY knowledge_receipt_owner ON public.action_receipts',
 'DROP POLICY knowledge_receipt_content ON public.action_receipts',
 'CREATE OR REPLACE FUNCTION public.m3_lifecycle_row_links(t uuid, c uuid, table_name text, payload '
 'jsonb)\n'
 ' RETURNS uuid[]\n'
 ' LANGUAGE plpgsql\n'
 ' STABLE SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 'DECLARE links uuid[]; key text; keys text[];\n'
 'BEGIN\n'
 ' links=public.m3_lifecycle_source_links(t,c,table_name,payload);\n'
 ' -- Only the infrequent retention summary needs host/reverse relationships.\n'
 ' -- They must not turn a source-free item INSERT into a proposal-history scan.\n'
 ' keys=CASE table_name\n'
 "  WHEN 'definition_sources' THEN ARRAY['definition_id']\n"
 "  WHEN 'definition_specs' THEN ARRAY['definition_id']\n"
 "  WHEN 'proposal_items' THEN ARRAY['proposal_id']\n"
 "  WHEN 'proposal_item_versions' THEN ARRAY['proposal_id','item_id']\n"
 "  WHEN 'proposal_sources' THEN ARRAY['proposal_id']\n"
 "  WHEN 'proposal_submissions' THEN ARRAY['proposal_id']\n"
 "  WHEN 'proposal_decisions' THEN ARRAY['proposal_id','created_definition_id']\n"
 "  WHEN 'evidence_links' THEN ARRAY['target_id']\n"
 "  WHEN 'manufacturing_baseline_publications' THEN ARRAY['project_id']\n"
 "  WHEN 'manufacturing_publication_currents' THEN ARRAY['series_id']\n"
 "  WHEN 'manufacturing_publication_documents' THEN ARRAY['publication_id']\n"
 "  WHEN 'native_pilot_runs' THEN ARRAY['project_id']\n"
 "  WHEN 'native_pilot_currents' THEN ARRAY['pilot_id']\n"
 "  WHEN 'native_pilot_observations' THEN ARRAY['pilot_id']\n"
 "  WHEN 'release_packages' THEN ARRAY['project_id','series_id']\n"
 "  WHEN 'release_package_currents' THEN ARRAY['series_id']\n"
 "  WHEN 'release_decisions' THEN ARRAY['package_id']\n"
 "  WHEN 'release_policy_facts' THEN ARRAY['project_id','series_id']\n"
 "  WHEN 'release_policy_currents' THEN ARRAY['series_id']\n"
 "  WHEN 'external_handoff_authorizations' THEN ARRAY['project_id']\n"
 "  WHEN 'external_delivery_intents' THEN ARRAY['project_id']\n"
 "  WHEN 'external_receipts' THEN ARRAY['project_id']\n"
 "  WHEN 'external_handoff_currents' THEN ARRAY['project_id']\n"
 "  WHEN 'release_exception_decisions' THEN ARRAY['project_id','series_id']\n"
 "  WHEN 'release_exception_currents' THEN ARRAY['project_id','series_id']\n"
 "  WHEN 'work_commitment_reviews' THEN ARRAY['project_id']\n"
 "  WHEN 'work_commitment_review_currents' THEN ARRAY['project_id']\n"
 "  WHEN 'external_wait_versions' THEN ARRAY['project_id']\n"
 "  WHEN 'external_wait_currents' THEN ARRAY['project_id']\n"
 "  WHEN 'project_risk_followups' THEN ARRAY['project_id']\n"
 "  WHEN 'project_risk_followup_currents' THEN ARRAY['project_id']\n"
 "  WHEN 'work_task_versions' THEN ARRAY['project_id']\n"
 "  WHEN 'work_task_currents' THEN ARRAY['project_id']\n"
 "  WHEN 'work_commitment_versions' THEN ARRAY['project_id']\n"
 "  WHEN 'work_commitment_currents' THEN ARRAY['project_id']\n"
 "  WHEN 'project_status_updates' THEN ARRAY['project_id']\n"
 '  ELSE ARRAY[]::text[] END;\n'
 ' FOREACH key IN ARRAY keys LOOP\n'
 '  IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n'
 ' END LOOP;\n'
 ' RETURN links;\n'
 'END;\n'
 '$function$\n',
 'CREATE OR REPLACE FUNCTION public.m3_lifecycle_nodes(t uuid, c uuid, identities uuid[] DEFAULT '
 'NULL::uuid[])\n'
 ' RETURNS TABLE(table_name text, node_id uuid, links uuid[])\n'
 ' LANGUAGE plpgsql\n'
 ' STABLE SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 'DECLARE name text; payload jsonb; controls uuid[];\n'
 'BEGIN\n'
 ' IF identities IS NULL THEN\n'
 "  SELECT coalesce(array_agg(id),'{}') INTO controls FROM public.action_receipts\n"
 "   WHERE tenant_id=t AND category_id=c AND operation LIKE 'evidence.lifecycle.%';\n"
 " ELSE controls='{}'; END IF;\n"
 ' FOREACH name IN ARRAY CASE WHEN identities IS NULL THEN '
 "ARRAY['agent_runs','action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','project_risk_followups','project_risk_followup_currents'] "
 'ELSE ARRAY[\n'
 "  'artifact_versions','claims','definition_revisions','definition_sources','definition_specs',\n"
 '  '
 "'proposals','proposal_items','proposal_item_versions','proposal_submissions','proposal_decisions',\n"
 '  '
 "'category_knowledge_entries','category_knowledge_current','parameter_versions','parameter_current',\n"
 '  '
 "'evidence_links','promotion_proofs','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','project_risk_followups','project_risk_followup_currents'] "
 'END LOOP\n'
 "  FOR payload IN EXECUTE CASE WHEN name=ANY(ARRAY['audit_entries','outbox_events','request_keys'])\n"
 "   THEN format('SELECT to_jsonb(x) FROM public.%I x JOIN public.action_receipts r ON "
 "r.id=x.receipt_id AND r.tenant_id=x.tenant_id WHERE x.tenant_id=$1 AND r.category_id=$2',name)\n"
 "   ELSE format('SELECT to_jsonb(x) FROM public.%I x WHERE tenant_id=$1 AND category_id=$2 AND ($3 IS "
 "NULL OR %I=ANY($3))',name,\n"
 "    CASE name WHEN 'category_knowledge_current' THEN 'lineage_id'\n"
 "     WHEN 'parameter_current' THEN 'parameter_id' ELSE 'id' END)\n"
 '   END USING t,c,identities LOOP\n'
 "   IF (payload->>'receipt_id')::uuid=ANY(controls) OR\n"
 "    (name='action_receipts' AND payload->>'operation' LIKE 'evidence.lifecycle.%') THEN CONTINUE; "
 'END IF;\n'
 '   table_name=name;\n'
 "   node_id=CASE name WHEN 'category_knowledge_current' THEN (payload->>'lineage_id')::uuid\n"
 "    WHEN 'parameter_current' THEN (payload->>'parameter_id')::uuid ELSE (payload->>'id')::uuid END;\n"
 '   IF identities IS NULL THEN links=public.m3_lifecycle_row_links(t,c,name,payload);\n'
 '   ELSE links=public.m3_lifecycle_source_links(t,c,name,payload); END IF;\n'
 "   -- Preserve predecessor's conservative legacy graph; M3-only nodes use\n"
 '   -- strictly typed/relational links. Root lookup never uses free-text UUIDs.\n'
 '   IF identities IS NULL AND '
 "name<>ALL(ARRAY['native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','project_risk_followups','project_risk_followup_currents','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals']) "
 'THEN\n'
 '    links=links || public.kernel_lifecycle_links(name,payload);\n'
 '   END IF;\n'
 '   RETURN NEXT;\n'
 '  END LOOP;\n'
 ' END LOOP;\n'
 'END;\n'
 '$function$\n',
 'CREATE OR REPLACE FUNCTION public.m3_lifecycle_source_links(t uuid, c uuid, table_name text, payload '
 'jsonb)\n'
 ' RETURNS uuid[]\n'
 ' LANGUAGE plpgsql\n'
 ' STABLE SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 "DECLARE links uuid[]='{}'; extra uuid[]; key text; keys text[]; item jsonb; container jsonb;\n"
 ' target_kind text; referenced_target uuid; referenced_version integer;\n'
 'BEGIN\n'
 " IF table_name='agent_runs' THEN RETURN public.kernel_lifecycle_links(table_name,payload); END IF;\n"
 ' -- Only actual top-level relation columns establish raw UUID edges. Arbitrary\n'
 ' -- content dictionaries are not relational rows, even if an extra key happens\n'
 ' -- to be named source_id or item_id.\n'
 ' keys=CASE table_name\n'
 "  WHEN 'artifact_versions' THEN ARRAY['original_id']\n"
 "  WHEN 'claims' THEN ARRAY['artifact_id','snapshot_id']\n"
 "  WHEN 'definition_revisions' THEN ARRAY['derived_from_definition_id','parent_definition_id',\n"
 "   'source_proposal_id','source_submission_id']\n"
 "  WHEN 'definition_sources' THEN ARRAY['artifact_id']\n"
 "  WHEN 'definition_specs' THEN ARRAY[]::text[]\n"
 "  WHEN 'proposals' THEN ARRAY['baseline_definition_id','current_submission_id']\n"
 "  WHEN 'proposal_items' THEN ARRAY[]::text[]\n"
 "  WHEN 'proposal_item_versions' THEN ARRAY[]::text[]\n"
 "  WHEN 'proposal_revisions' THEN ARRAY['proposal_id']\n"
 "  WHEN 'proposal_sources' THEN ARRAY['source_id']\n"
 "  WHEN 'proposal_submissions' THEN ARRAY[]::text[]\n"
 "  WHEN 'proposal_decisions' THEN ARRAY['submission_id']\n"
 "  WHEN 'project_open_items' THEN ARRAY['source_question_id','source_spec_item_id','g0_decision_id']\n"
 "  WHEN 'category_knowledge_current' THEN ARRAY['current_entry_id']\n"
 "  WHEN 'promotion_proofs' THEN ARRAY['knowledge_entry_id','source_proposal_id']\n"
 "  WHEN 'evidence_links' THEN ARRAY['evidence_id']\n"
 "  WHEN 'claim_withdrawals' THEN ARRAY['claim_id']\n"
 "  WHEN 'manufacturing_baseline_publications' THEN ARRAY['baseline_id','process_id','previous_id']\n"
 "  WHEN 'manufacturing_publication_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'manufacturing_publication_documents' THEN ARRAY['document_id','process_id']\n"
 "  WHEN 'native_pilot_runs' THEN "
 "ARRAY['build_id','lot_id','actual_configuration_id','engineering_configuration_id','process_id','publication_id']\n"
 "  WHEN 'native_pilot_currents' THEN ARRAY['pilot_id','latest_observation_id']\n"
 "  WHEN 'native_pilot_observations' THEN ARRAY['pilot_id','previous_observation_id']\n"
 "  WHEN 'release_packages' THEN ARRAY['previous_id']\n"
 "  WHEN 'release_package_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'release_decisions' THEN ARRAY['package_id']\n"
 "  WHEN 'release_policy_facts' THEN ARRAY['previous_id']\n"
 "  WHEN 'release_policy_currents' THEN ARRAY['fact_id']\n"
 "  WHEN 'external_handoff_authorizations' THEN "
 "ARRAY['package_id','engineering_decision_id','manufacturing_decision_id']\n"
 "  WHEN 'external_delivery_intents' THEN ARRAY['handoff_id']\n"
 "  WHEN 'external_receipts' THEN "
 "ARRAY['handoff_id','intent_id','previous_receipt_id','reconciles_id']\n"
 "  WHEN 'external_handoff_currents' THEN ARRAY['handoff_id','intent_id','latest_receipt_id']\n"
 "  WHEN 'release_exception_decisions' THEN ARRAY['basis_package_id','policy_fact_id','previous_id']\n"
 "  WHEN 'release_exception_currents' THEN ARRAY['basis_package_id','policy_fact_id','decision_id']\n"
 "  WHEN 'work_commitment_reviews' THEN "
 "ARRAY['commitment_id','task_version_id','submission_id','previous_id']\n"
 "  WHEN 'work_commitment_review_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'external_wait_versions' THEN ARRAY['previous_id']\n"
 "  WHEN 'external_wait_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'project_risk_followups' THEN ARRAY['previous_id','risk_id','g0_decision_id']\n"
 "  WHEN 'project_risk_followup_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'work_task_versions' THEN ARRAY['previous_id']\n"
 "  WHEN 'work_task_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'work_commitment_versions' THEN ARRAY['replaces_id']\n"
 "  WHEN 'work_commitment_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'project_status_updates' THEN ARRAY[]::text[]\n"
 '  ELSE ARRAY[]::text[] END;\n'
 ' FOREACH key IN ARRAY keys LOOP\n'
 '  IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n'
 ' END LOOP;\n'
 " -- Publication's exact saved read set is a validated Artifact relationship.\n"
 ' -- Do not scan its declaration, body, reason or arbitrary JSON UUID values.\n'
 ' IF table_name IN '
 "('manufacturing_baseline_publications','native_pilot_runs','native_pilot_observations','release_packages','release_decisions','release_policy_facts','external_handoff_authorizations','external_receipts','release_exception_decisions') "
 'THEN\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload->'required_source_read_set','[]')) LOOP\n"
 "   IF item->>'artifact_id' IS NOT NULL THEN\n"
 "    links=array_append(links,(item->>'artifact_id')::uuid);\n"
 '   END IF;\n'
 '  END LOOP;\n'
 ' END IF;\n'
 " IF table_name IN ('native_pilot_runs','native_pilot_observations') THEN\n"
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{material_snapshot,statistics,samples}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{material_snapshot,statistics,issues}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  item=payload#>'{material_snapshot,statistics,resource,fact}';\n"
 "  IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 ' END IF;\n'
 " IF table_name='release_packages' THEN\n"
 '  -- FixedObject.ref is a closed, server-resolved version reference, not arbitrary body UUID text.\n'
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{body,objects}','[]')) LOOP\n"
 "   container=item->'ref';\n"
 '   IF '
 "container->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','manufacturing_publication','test_run','pilot_run','issue','change','exception','artifact','work_instruction','control_plan','build_lot','line'])\n"
 "    AND container->>'id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); END "
 'IF;\n'
 '  END LOOP;\n'
 ' END IF;\n'
 " IF table_name IN ('external_handoff_authorizations','external_delivery_intents') THEN\n"
 '  -- Only closed, owner-verified mapping and manifest references are source edges.\n'
 "  container=CASE WHEN table_name='external_handoff_authorizations' THEN "
 "payload#>'{body,declaration}' ELSE payload->'body' END;\n"
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'mappings','[]')) LOOP\n"
 '   IF '
 "item->'ref'->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','part','bom_revision','artifact','work_instruction','control_plan'])\n"
 "    AND item->'ref'->>'id' IS NOT NULL THEN links=array_append(links,(item->'ref'->>'id')::uuid); "
 'END IF;\n'
 '  END LOOP;\n'
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'manifest','[]')) LOOP\n"
 "   IF item->'artifact'->>'id' IS NOT NULL THEN "
 "links=array_append(links,(item->'artifact'->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 " IF table_name='release_policy_facts' THEN\n"
 '  -- These are Closed DTO configuration references fixed by the policy owner.\n'
 "  FOREACH key IN ARRAY ARRAY['definition','engineering_configuration','manufacturing_configuration'] "
 'LOOP\n'
 "   container=payload#>ARRAY['material','subject_config',key];\n"
 "   IF container->>'id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 ' -- These stored fields are validated Reference containers. Do not feed the\n'
 ' -- whole row or arbitrary content into the canonical Reference parser.\n'
 " IF table_name=ANY(ARRAY['proposals','proposal_item_versions','proposal_submissions',\n"
 "  'category_knowledge_entries','definition_specs']) THEN\n"
 '  FOREACH key IN ARRAY '
 "ARRAY['source_refs','direct_source_refs','context_refs','baseline_claim_refs'] LOOP\n"
 '   links=links || public.m3_lifecycle_typed_links(t,c,payload->key);\n'
 '  END LOOP;\n'
 ' END IF;\n'
 ' -- Match ItemInput.content_schema and category_service._references: only\n'
 ' -- commercial_target, voice, and competitor have nested source contracts.\n'
 " IF table_name='proposal_item_versions' AND payload->>'kind'='commercial_target' THEN\n"
 "  FOREACH key IN ARRAY ARRAY['target_price','cost','volume'] LOOP\n"
 "   links=links || public.m3_lifecycle_typed_links(t,c,payload->'content'->key->'source');\n"
 '  END LOOP;\n'
 " ELSIF table_name='category_knowledge_entries' AND payload->>'kind'='voice' THEN\n"
 "  links=links || public.m3_lifecycle_typed_links(t,c,payload->'content'->'representative_refs');\n"
 " ELSIF table_name='category_knowledge_entries' AND payload->>'kind'='competitor' THEN\n"
 "  FOREACH key IN ARRAY ARRAY['metrics','features','prices'] LOOP\n"
 "   FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'content'->key,'[]')) LOOP\n"
 "    links=links || public.m3_lifecycle_typed_links(t,c,item->'source_ref');\n"
 '   END LOOP;\n'
 '  END LOOP;\n'
 ' END IF;\n'
 " IF table_name='proposal_submissions' THEN\n"
 "  container=payload->'frozen_document';\n"
 '  FOREACH key IN ARRAY '
 "ARRAY['source_refs','direct_source_refs','context_refs','baseline_claim_refs'] LOOP\n"
 '   links=links || public.m3_lifecycle_typed_links(t,c,container->key);\n'
 '  END LOOP;\n'
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'items','[]')) LOOP\n"
 '   links=links || '
 "public.m3_lifecycle_source_links(t,c,'proposal_item_versions',item-ARRAY['item_id','proposal_id']);\n"
 '   -- The frozen read projection records actual EvidenceLink provenance here.\n'
 "   links=links || public.m3_lifecycle_typed_links(t,c,item->'evidence_links');\n"
 '  END LOOP;\n'
 " ELSIF table_name='promotion_proofs' THEN\n"
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'source_item_refs','[]')) "
 'LOOP\n'
 "   IF item->>'item_id' IS NOT NULL THEN links=array_append(links,(item->>'item_id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 ' -- Exact persisted EvidenceLink targets supplement these immutable versions.\n'
 ' -- Reverted links and withdrawn Claims still retain the original historical\n'
 ' -- dependency; lifecycle cleanup must not erase their audit source.\n'
 " IF table_name='proposal_item_versions' AND payload->>'item_id' IS NOT NULL THEN\n"
 "  target_kind='proposal_item'; referenced_target=(payload->>'item_id')::uuid;\n"
 "  referenced_version=(payload->>'version')::integer;\n"
 " ELSIF table_name='category_knowledge_entries' AND payload->>'id' IS NOT NULL THEN\n"
 "  target_kind='knowledge_entry'; referenced_target=(payload->>'id')::uuid;\n"
 "  referenced_version=(payload->>'version')::integer;\n"
 " ELSIF table_name='definition_specs' AND payload->>'id' IS NOT NULL THEN\n"
 "  target_kind='definition_spec'; referenced_target=(payload->>'id')::uuid;\n"
 '  SELECT revision INTO referenced_version FROM public.definition_revisions\n'
 "   WHERE tenant_id=t AND category_id=c AND id=(payload->>'definition_id')::uuid;\n"
 ' END IF;\n'
 ' IF referenced_target IS NOT NULL AND referenced_version IS NOT NULL THEN\n'
 "  SELECT coalesce(array_agg(link.evidence_id),'{}') INTO extra FROM public.evidence_links link\n"
 '   WHERE link.tenant_id=t AND link.category_id=c AND link.target_type=target_kind\n'
 '    AND link.target_id=referenced_target AND link.target_version=referenced_version;\n'
 '  links=links || extra;\n'
 ' END IF;\n'
 ' -- Child source rows point to their parent, whereas dependency traversal needs\n'
 " -- the parent's fixed source children as well. Keep the actual relational edge.\n"
 " IF table_name='definition_revisions' THEN\n"
 "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM (\n"
 '   SELECT id FROM public.definition_sources WHERE tenant_id=t AND category_id=c\n'
 "    AND definition_id=(payload->>'id')::uuid\n"
 '   UNION ALL SELECT id FROM public.definition_specs WHERE tenant_id=t AND category_id=c\n'
 "    AND definition_id=(payload->>'id')::uuid\n"
 '  ) children;\n'
 '  links=links || extra;\n'
 " ELSIF table_name='proposals' THEN\n"
 "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.proposal_item_versions\n"
 "   WHERE tenant_id=t AND category_id=c AND proposal_id=(payload->>'id')::uuid;\n"
 '  links=links || extra;\n'
 " ELSIF table_name='proposal_items' THEN\n"
 "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.proposal_item_versions\n"
 "   WHERE tenant_id=t AND category_id=c AND item_id=(payload->>'id')::uuid;\n"
 '  links=links || extra;\n'
 " ELSIF table_name='product_target_segments' THEN\n"
 "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.category_knowledge_entries\n"
 "   WHERE tenant_id=t AND category_id=c AND lineage_id=(payload->>'segment_lineage_id')::uuid\n"
 "    AND version=(payload->>'segment_version')::integer;\n"
 '  links=links || extra;\n'
 " ELSIF table_name='parameter_current' THEN\n"
 "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.parameter_versions\n"
 "   WHERE tenant_id=t AND category_id=c AND parameter_id=(payload->>'parameter_id')::uuid\n"
 "    AND version=(payload->>'current_version')::integer;\n"
 '  links=links || extra;\n'
 ' END IF;\n'
 '\n'
 " IF table_name IN ('work_task_versions','work_commitment_versions','project_status_updates') THEN\n"
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP\n"
 "   IF item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'artifact_id')::uuid); "
 'END IF;\n'
 '  END LOOP;\n'
 "  IF table_name='work_task_versions' AND payload#>>'{body,plan_task,id}' IS NOT NULL THEN\n"
 "   links=array_append(links,(payload#>>'{body,plan_task,id}')::uuid);\n"
 '  END IF;\n'
 "  IF table_name='work_commitment_versions' THEN\n"
 "   SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.work_task_versions\n"
 "    WHERE tenant_id=t AND category_id=c AND task_id=(payload->>'task_id')::uuid AND "
 "revision=(payload->>'task_revision')::integer;\n"
 '   links=links||extra;\n'
 "  ELSIF table_name='project_status_updates' THEN\n"
 "   FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'task_refs','[]')) LOOP\n"
 "    SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.work_task_versions\n"
 "     WHERE tenant_id=t AND category_id=c AND task_id=(item->>'id')::uuid AND "
 "revision=(item->>'revision')::integer;\n"
 '    links=links||extra;\n'
 '   END LOOP;\n'
 '  END IF;\n'
 ' END IF;\n'
 '\n'
 " IF table_name='work_commitment_reviews' THEN\n"
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP\n"
 "   IF item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'artifact_id')::uuid); "
 'END IF;\n'
 '  END LOOP;\n'
 ' END IF;\n'
 '\n'
 " IF table_name='external_wait_versions' THEN\n"
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  FOREACH key IN ARRAY ARRAY['milestone','build','calendar'] LOOP\n"
 "   container=payload#>ARRAY['body',key];\n"
 "   IF container->>'id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  container=payload#>'{body,replaces}';\n"
 "  IF container->>'id' IS NOT NULL THEN\n"
 "   SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.external_wait_versions\n"
 "    WHERE tenant_id=t AND category_id=c AND wait_id=(container->>'id')::uuid AND "
 "revision=(container->>'revision')::integer;\n"
 '   links=links||extra;\n'
 '  END IF;\n'
 ' END IF;\n'
 " IF table_name='project_risk_followups' THEN\n"
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 ' RETURN links;\n'
 'END;\n'
 '$function$\n',
 'DROP TRIGGER protect_knowledge_receipt ON public.action_receipts',
 'DROP TRIGGER protect_knowledge_confirmation ON public.confirmations',
 'DROP TRIGGER require_knowledge_confirmation ON public.confirmations',
 'DROP TRIGGER require_knowledge_member ON public.action_receipts',
 'DROP TRIGGER protect_knowledge_member ON public.audit_entries',
 'DROP TRIGGER require_knowledge_member ON public.audit_entries',
 'DROP TRIGGER protect_knowledge_member ON public.outbox_events',
 'DROP TRIGGER require_knowledge_member ON public.outbox_events',
 'DROP TRIGGER protect_knowledge_member ON public.request_keys',
 'DROP TRIGGER require_knowledge_member ON public.request_keys',
 'ALTER TABLE knowledge_rule_versions DROP CONSTRAINT knowledge_rule_assessment_fk',
 'ALTER TABLE knowledge_applicability_assessments DROP CONSTRAINT knowledge_assessment_publication_fk',
 'DROP TABLE public.knowledge_rule_currents',
 'DROP TABLE public.knowledge_applicability_assessments',
 'DROP TABLE public.knowledge_rule_versions',
 'DROP TABLE public.knowledge_candidate_currents',
 'DROP TABLE public.knowledge_candidate_versions',
 'DROP FUNCTION public.require_knowledge_assessment()',
 'DROP FUNCTION public.assert_knowledge_assessment(uuid,uuid)',
 'DROP FUNCTION public.require_knowledge_rule()',
 'DROP FUNCTION public.assert_knowledge_rule(uuid,uuid)',
 'DROP FUNCTION public.require_knowledge_candidate()',
 'DROP FUNCTION public.assert_knowledge_candidate(uuid,uuid)',
 'DROP FUNCTION public.require_knowledge_confirmation()',
 'DROP FUNCTION public.protect_knowledge_confirmation()',
 'DROP FUNCTION public.require_knowledge_member()',
 'DROP FUNCTION public.protect_knowledge_member()',
 'DROP FUNCTION public.protect_knowledge_receipt()',
 'DROP FUNCTION public.assert_knowledge_professional(uuid,uuid)',
 'DROP FUNCTION public.assert_knowledge_common(uuid,uuid,text)',
 'DROP FUNCTION public.assert_knowledge_members(uuid,uuid,text)',
 'DROP FUNCTION public.require_knowledge_rule_current()',
 'DROP FUNCTION public.protect_knowledge_rule_current()',
 'DROP FUNCTION public.require_knowledge_candidate_current()',
 'DROP FUNCTION public.protect_knowledge_candidate_current()',
 'DROP FUNCTION public.reject_knowledge_mutation()',
 'DROP FUNCTION public.knowledge_result_sources_visible(uuid,uuid,uuid,jsonb)',
 'DROP FUNCTION public.knowledge_content_sources_visible(uuid,uuid,uuid,jsonb)',
 'ALTER TABLE public.professional_authority_facts DROP CONSTRAINT professional_authority_facts_check',
 'ALTER TABLE public.professional_authority_facts ADD CONSTRAINT professional_authority_facts_check '
 "CHECK ((((kind)::text = ANY ((ARRAY['duty'::character varying, 'qualification'::character "
 "varying])::text[])) AND ((role)::text = ANY ((ARRAY['engineering'::character varying, "
 "'quality'::character varying, 'manufacturing'::character varying])::text[])) AND ((nature)::text = "
 "ANY ((ARRAY['real'::character varying, 'synthetic'::character varying])::text[]))))")

