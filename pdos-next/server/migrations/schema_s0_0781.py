"""Frozen release policy DDL and exact actual 0780 lifecycle predecessor."""

# ruff: noqa: E501 -- Preserve exact PostgreSQL function definitions.

PREVIOUS_FUNCTIONS = {'m3_lifecycle_nodes(uuid,uuid,uuid[])': 'CREATE OR REPLACE FUNCTION public.m3_lifecycle_nodes(t '
                                         'uuid, c uuid, identities uuid[] DEFAULT NULL::uuid[])\n'
                                         ' RETURNS TABLE(table_name text, node_id uuid, links '
                                         'uuid[])\n'
                                         ' LANGUAGE plpgsql\n'
                                         ' STABLE SECURITY DEFINER\n'
                                         " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                         'AS $function$\n'
                                         'DECLARE name text; payload jsonb; controls uuid[];\n'
                                         'BEGIN\n'
                                         ' IF identities IS NULL THEN\n'
                                         "  SELECT coalesce(array_agg(id),'{}') INTO controls FROM "
                                         'public.action_receipts\n'
                                         '   WHERE tenant_id=t AND category_id=c AND operation '
                                         "LIKE 'evidence.lifecycle.%';\n"
                                         " ELSE controls='{}'; END IF;\n"
                                         ' FOREACH name IN ARRAY CASE WHEN identities IS NULL THEN '
                                         "ARRAY['agent_runs','action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions'] "
                                         'ELSE ARRAY[\n'
                                         '  '
                                         "'artifact_versions','claims','definition_revisions','definition_sources','definition_specs',\n"
                                         '  '
                                         "'proposals','proposal_items','proposal_item_versions','proposal_submissions','proposal_decisions',\n"
                                         '  '
                                         "'category_knowledge_entries','category_knowledge_current','parameter_versions','parameter_current',\n"
                                         '  '
                                         "'evidence_links','promotion_proofs','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions'] "
                                         'END LOOP\n'
                                         '  FOR payload IN EXECUTE CASE WHEN '
                                         "name=ANY(ARRAY['audit_entries','outbox_events','request_keys'])\n"
                                         "   THEN format('SELECT to_jsonb(x) FROM public.%I x JOIN "
                                         'public.action_receipts r ON r.id=x.receipt_id AND '
                                         'r.tenant_id=x.tenant_id WHERE x.tenant_id=$1 AND '
                                         "r.category_id=$2',name)\n"
                                         "   ELSE format('SELECT to_jsonb(x) FROM public.%I x "
                                         'WHERE tenant_id=$1 AND category_id=$2 AND ($3 IS NULL OR '
                                         "%I=ANY($3))',name,\n"
                                         "    CASE name WHEN 'category_knowledge_current' THEN "
                                         "'lineage_id'\n"
                                         "     WHEN 'parameter_current' THEN 'parameter_id' ELSE "
                                         "'id' END)\n"
                                         '   END USING t,c,identities LOOP\n'
                                         "   IF (payload->>'receipt_id')::uuid=ANY(controls) OR\n"
                                         "    (name='action_receipts' AND payload->>'operation' "
                                         "LIKE 'evidence.lifecycle.%') THEN CONTINUE; END IF;\n"
                                         '   table_name=name;\n'
                                         "   node_id=CASE name WHEN 'category_knowledge_current' "
                                         "THEN (payload->>'lineage_id')::uuid\n"
                                         "    WHEN 'parameter_current' THEN "
                                         "(payload->>'parameter_id')::uuid ELSE "
                                         "(payload->>'id')::uuid END;\n"
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
                                         "name<>ALL(ARRAY['native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals']) "
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
                                                    'public.m3_lifecycle_source_links(t uuid, c '
                                                    'uuid, table_name text, payload jsonb)\n'
                                                    ' RETURNS uuid[]\n'
                                                    ' LANGUAGE plpgsql\n'
                                                    ' STABLE SECURITY DEFINER\n'
                                                    " SET search_path TO 'pg_catalog', 'public', "
                                                    "'pg_temp'\n"
                                                    'AS $function$\n'
                                                    "DECLARE links uuid[]='{}'; extra uuid[]; key "
                                                    'text; keys text[]; item jsonb; container '
                                                    'jsonb;\n'
                                                    ' target_kind text; referenced_target uuid; '
                                                    'referenced_version integer;\n'
                                                    'BEGIN\n'
                                                    " IF table_name='agent_runs' THEN RETURN "
                                                    'public.kernel_lifecycle_links(table_name,payload); '
                                                    'END IF;\n'
                                                    ' -- Only actual top-level relation columns '
                                                    'establish raw UUID edges. Arbitrary\n'
                                                    ' -- content dictionaries are not relational '
                                                    'rows, even if an extra key happens\n'
                                                    ' -- to be named source_id or item_id.\n'
                                                    ' keys=CASE table_name\n'
                                                    "  WHEN 'artifact_versions' THEN "
                                                    "ARRAY['original_id']\n"
                                                    "  WHEN 'claims' THEN "
                                                    "ARRAY['artifact_id','snapshot_id']\n"
                                                    "  WHEN 'definition_revisions' THEN "
                                                    "ARRAY['derived_from_definition_id','parent_definition_id',\n"
                                                    '   '
                                                    "'source_proposal_id','source_submission_id']\n"
                                                    "  WHEN 'definition_sources' THEN "
                                                    "ARRAY['artifact_id']\n"
                                                    "  WHEN 'definition_specs' THEN "
                                                    'ARRAY[]::text[]\n'
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
                                                    "  WHEN 'manufacturing_baseline_publications' "
                                                    'THEN '
                                                    "ARRAY['baseline_id','process_id','previous_id']\n"
                                                    "  WHEN 'manufacturing_publication_currents' "
                                                    "THEN ARRAY['version_id']\n"
                                                    "  WHEN 'manufacturing_publication_documents' "
                                                    "THEN ARRAY['document_id','process_id']\n"
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
                                                    '  ELSE ARRAY[]::text[] END;\n'
                                                    ' FOREACH key IN ARRAY keys LOOP\n'
                                                    '  IF payload->>key IS NOT NULL THEN '
                                                    'links=array_append(links,(payload->>key)::uuid); '
                                                    'END IF;\n'
                                                    ' END LOOP;\n'
                                                    " -- Publication's exact saved read set is a "
                                                    'validated Artifact relationship.\n'
                                                    ' -- Do not scan its declaration, body, reason '
                                                    'or arbitrary JSON UUID values.\n'
                                                    ' IF table_name IN '
                                                    "('manufacturing_baseline_publications','native_pilot_runs','native_pilot_observations','release_packages','release_decisions') "
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
                                                    '  -- FixedObject.ref is a closed, '
                                                    'server-resolved version reference, not '
                                                    'arbitrary body UUID text.\n'
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
                                                    ' -- These stored fields are validated '
                                                    'Reference containers. Do not feed the\n'
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
                                                    ' -- commercial_target, voice, and competitor '
                                                    'have nested source contracts.\n'
                                                    " IF table_name='proposal_item_versions' AND "
                                                    "payload->>'kind'='commercial_target' THEN\n"
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['target_price','cost','volume'] LOOP\n"
                                                    '   links=links || '
                                                    "public.m3_lifecycle_typed_links(t,c,payload->'content'->key->'source');\n"
                                                    '  END LOOP;\n'
                                                    ' ELSIF '
                                                    "table_name='category_knowledge_entries' AND "
                                                    "payload->>'kind'='voice' THEN\n"
                                                    '  links=links || '
                                                    "public.m3_lifecycle_typed_links(t,c,payload->'content'->'representative_refs');\n"
                                                    ' ELSIF '
                                                    "table_name='category_knowledge_entries' AND "
                                                    "payload->>'kind'='competitor' THEN\n"
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
                                                    '   -- The frozen read projection records '
                                                    'actual EvidenceLink provenance here.\n'
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
                                                    ' -- dependency; lifecycle cleanup must not '
                                                    'erase their audit source.\n'
                                                    " IF table_name='proposal_item_versions' AND "
                                                    "payload->>'item_id' IS NOT NULL THEN\n"
                                                    "  target_kind='proposal_item'; "
                                                    "referenced_target=(payload->>'item_id')::uuid;\n"
                                                    '  '
                                                    "referenced_version=(payload->>'version')::integer;\n"
                                                    ' ELSIF '
                                                    "table_name='category_knowledge_entries' AND "
                                                    "payload->>'id' IS NOT NULL THEN\n"
                                                    "  target_kind='knowledge_entry'; "
                                                    "referenced_target=(payload->>'id')::uuid;\n"
                                                    '  '
                                                    "referenced_version=(payload->>'version')::integer;\n"
                                                    " ELSIF table_name='definition_specs' AND "
                                                    "payload->>'id' IS NOT NULL THEN\n"
                                                    "  target_kind='definition_spec'; "
                                                    "referenced_target=(payload->>'id')::uuid;\n"
                                                    '  SELECT revision INTO referenced_version '
                                                    'FROM public.definition_revisions\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "id=(payload->>'definition_id')::uuid;\n"
                                                    ' END IF;\n'
                                                    ' IF referenced_target IS NOT NULL AND '
                                                    'referenced_version IS NOT NULL THEN\n'
                                                    '  SELECT '
                                                    "coalesce(array_agg(link.evidence_id),'{}') "
                                                    'INTO extra FROM public.evidence_links link\n'
                                                    '   WHERE link.tenant_id=t AND '
                                                    'link.category_id=c AND '
                                                    'link.target_type=target_kind\n'
                                                    '    AND link.target_id=referenced_target AND '
                                                    'link.target_version=referenced_version;\n'
                                                    '  links=links || extra;\n'
                                                    ' END IF;\n'
                                                    ' -- Child source rows point to their parent, '
                                                    'whereas dependency traversal needs\n'
                                                    " -- the parent's fixed source children as "
                                                    'well. Keep the actual relational edge.\n'
                                                    " IF table_name='definition_revisions' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO "
                                                    'extra FROM (\n'
                                                    '   SELECT id FROM public.definition_sources '
                                                    'WHERE tenant_id=t AND category_id=c\n'
                                                    "    AND definition_id=(payload->>'id')::uuid\n"
                                                    '   UNION ALL SELECT id FROM '
                                                    'public.definition_specs WHERE tenant_id=t AND '
                                                    'category_id=c\n'
                                                    "    AND definition_id=(payload->>'id')::uuid\n"
                                                    '  ) children;\n'
                                                    '  links=links || extra;\n'
                                                    " ELSIF table_name='proposals' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO "
                                                    'extra FROM public.proposal_item_versions\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "proposal_id=(payload->>'id')::uuid;\n"
                                                    '  links=links || extra;\n'
                                                    " ELSIF table_name='proposal_items' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO "
                                                    'extra FROM public.proposal_item_versions\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "item_id=(payload->>'id')::uuid;\n"
                                                    '  links=links || extra;\n'
                                                    " ELSIF table_name='product_target_segments' "
                                                    'THEN\n'
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO "
                                                    'extra FROM public.category_knowledge_entries\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "lineage_id=(payload->>'segment_lineage_id')::uuid\n"
                                                    '    AND '
                                                    "version=(payload->>'segment_version')::integer;\n"
                                                    '  links=links || extra;\n'
                                                    " ELSIF table_name='parameter_current' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO "
                                                    'extra FROM public.parameter_versions\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "parameter_id=(payload->>'parameter_id')::uuid\n"
                                                    '    AND '
                                                    "version=(payload->>'current_version')::integer;\n"
                                                    '  links=links || extra;\n'
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
                                                 "  WHEN 'proposal_items' THEN "
                                                 "ARRAY['proposal_id']\n"
                                                 "  WHEN 'proposal_item_versions' THEN "
                                                 "ARRAY['proposal_id','item_id']\n"
                                                 "  WHEN 'proposal_sources' THEN "
                                                 "ARRAY['proposal_id']\n"
                                                 "  WHEN 'proposal_submissions' THEN "
                                                 "ARRAY['proposal_id']\n"
                                                 "  WHEN 'proposal_decisions' THEN "
                                                 "ARRAY['proposal_id','created_definition_id']\n"
                                                 "  WHEN 'evidence_links' THEN ARRAY['target_id']\n"
                                                 "  WHEN 'manufacturing_baseline_publications' "
                                                 "THEN ARRAY['project_id']\n"
                                                 "  WHEN 'manufacturing_publication_currents' THEN "
                                                 "ARRAY['series_id']\n"
                                                 "  WHEN 'manufacturing_publication_documents' "
                                                 "THEN ARRAY['publication_id']\n"
                                                 "  WHEN 'native_pilot_runs' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'native_pilot_currents' THEN "
                                                 "ARRAY['pilot_id']\n"
                                                 "  WHEN 'native_pilot_observations' THEN "
                                                 "ARRAY['pilot_id']\n"
                                                 "  WHEN 'release_packages' THEN "
                                                 "ARRAY['project_id','series_id']\n"
                                                 "  WHEN 'release_package_currents' THEN "
                                                 "ARRAY['series_id']\n"
                                                 "  WHEN 'release_decisions' THEN "
                                                 "ARRAY['package_id']\n"
                                                 '  ELSE ARRAY[]::text[] END;\n'
                                                 ' FOREACH key IN ARRAY keys LOOP\n'
                                                 '  IF payload->>key IS NOT NULL THEN '
                                                 'links=array_append(links,(payload->>key)::uuid); '
                                                 'END IF;\n'
                                                 ' END LOOP;\n'
                                                 ' RETURN links;\n'
                                                 'END;\n'
                                                 '$function$\n'}

POLICY_FUNCTIONS = {'m3_lifecycle_nodes(uuid,uuid,uuid[])': 'CREATE OR REPLACE FUNCTION public.m3_lifecycle_nodes(t '
                                         'uuid, c uuid, identities uuid[] DEFAULT NULL::uuid[])\n'
                                         ' RETURNS TABLE(table_name text, node_id uuid, links '
                                         'uuid[])\n'
                                         ' LANGUAGE plpgsql\n'
                                         ' STABLE SECURITY DEFINER\n'
                                         " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                         'AS $function$\n'
                                         'DECLARE name text; payload jsonb; controls uuid[];\n'
                                         'BEGIN\n'
                                         ' IF identities IS NULL THEN\n'
                                         "  SELECT coalesce(array_agg(id),'{}') INTO controls FROM "
                                         'public.action_receipts\n'
                                         '   WHERE tenant_id=t AND category_id=c AND operation '
                                         "LIKE 'evidence.lifecycle.%';\n"
                                         " ELSE controls='{}'; END IF;\n"
                                         ' FOREACH name IN ARRAY CASE WHEN identities IS NULL THEN '
                                         "ARRAY['agent_runs','action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents'] "
                                         'ELSE ARRAY[\n'
                                         '  '
                                         "'artifact_versions','claims','definition_revisions','definition_sources','definition_specs',\n"
                                         '  '
                                         "'proposals','proposal_items','proposal_item_versions','proposal_submissions','proposal_decisions',\n"
                                         '  '
                                         "'category_knowledge_entries','category_knowledge_current','parameter_versions','parameter_current',\n"
                                         '  '
                                         "'evidence_links','promotion_proofs','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents'] "
                                         'END LOOP\n'
                                         '  FOR payload IN EXECUTE CASE WHEN '
                                         "name=ANY(ARRAY['audit_entries','outbox_events','request_keys'])\n"
                                         "   THEN format('SELECT to_jsonb(x) FROM public.%I x JOIN "
                                         'public.action_receipts r ON r.id=x.receipt_id AND '
                                         'r.tenant_id=x.tenant_id WHERE x.tenant_id=$1 AND '
                                         "r.category_id=$2',name)\n"
                                         "   ELSE format('SELECT to_jsonb(x) FROM public.%I x "
                                         'WHERE tenant_id=$1 AND category_id=$2 AND ($3 IS NULL OR '
                                         "%I=ANY($3))',name,\n"
                                         "    CASE name WHEN 'category_knowledge_current' THEN "
                                         "'lineage_id'\n"
                                         "     WHEN 'parameter_current' THEN 'parameter_id' ELSE "
                                         "'id' END)\n"
                                         '   END USING t,c,identities LOOP\n'
                                         "   IF (payload->>'receipt_id')::uuid=ANY(controls) OR\n"
                                         "    (name='action_receipts' AND payload->>'operation' "
                                         "LIKE 'evidence.lifecycle.%') THEN CONTINUE; END IF;\n"
                                         '   table_name=name;\n'
                                         "   node_id=CASE name WHEN 'category_knowledge_current' "
                                         "THEN (payload->>'lineage_id')::uuid\n"
                                         "    WHEN 'parameter_current' THEN "
                                         "(payload->>'parameter_id')::uuid ELSE "
                                         "(payload->>'id')::uuid END;\n"
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
                                         "name<>ALL(ARRAY['native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals']) "
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
                                                    'public.m3_lifecycle_source_links(t uuid, c '
                                                    'uuid, table_name text, payload jsonb)\n'
                                                    ' RETURNS uuid[]\n'
                                                    ' LANGUAGE plpgsql\n'
                                                    ' STABLE SECURITY DEFINER\n'
                                                    " SET search_path TO 'pg_catalog', 'public', "
                                                    "'pg_temp'\n"
                                                    'AS $function$\n'
                                                    "DECLARE links uuid[]='{}'; extra uuid[]; key "
                                                    'text; keys text[]; item jsonb; container '
                                                    'jsonb;\n'
                                                    ' target_kind text; referenced_target uuid; '
                                                    'referenced_version integer;\n'
                                                    'BEGIN\n'
                                                    " IF table_name='agent_runs' THEN RETURN "
                                                    'public.kernel_lifecycle_links(table_name,payload); '
                                                    'END IF;\n'
                                                    ' -- Only actual top-level relation columns '
                                                    'establish raw UUID edges. Arbitrary\n'
                                                    ' -- content dictionaries are not relational '
                                                    'rows, even if an extra key happens\n'
                                                    ' -- to be named source_id or item_id.\n'
                                                    ' keys=CASE table_name\n'
                                                    "  WHEN 'artifact_versions' THEN "
                                                    "ARRAY['original_id']\n"
                                                    "  WHEN 'claims' THEN "
                                                    "ARRAY['artifact_id','snapshot_id']\n"
                                                    "  WHEN 'definition_revisions' THEN "
                                                    "ARRAY['derived_from_definition_id','parent_definition_id',\n"
                                                    '   '
                                                    "'source_proposal_id','source_submission_id']\n"
                                                    "  WHEN 'definition_sources' THEN "
                                                    "ARRAY['artifact_id']\n"
                                                    "  WHEN 'definition_specs' THEN "
                                                    'ARRAY[]::text[]\n'
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
                                                    "  WHEN 'manufacturing_baseline_publications' "
                                                    'THEN '
                                                    "ARRAY['baseline_id','process_id','previous_id']\n"
                                                    "  WHEN 'manufacturing_publication_currents' "
                                                    "THEN ARRAY['version_id']\n"
                                                    "  WHEN 'manufacturing_publication_documents' "
                                                    "THEN ARRAY['document_id','process_id']\n"
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
                                                    '  ELSE ARRAY[]::text[] END;\n'
                                                    ' FOREACH key IN ARRAY keys LOOP\n'
                                                    '  IF payload->>key IS NOT NULL THEN '
                                                    'links=array_append(links,(payload->>key)::uuid); '
                                                    'END IF;\n'
                                                    ' END LOOP;\n'
                                                    " -- Publication's exact saved read set is a "
                                                    'validated Artifact relationship.\n'
                                                    ' -- Do not scan its declaration, body, reason '
                                                    'or arbitrary JSON UUID values.\n'
                                                    ' IF table_name IN '
                                                    "('manufacturing_baseline_publications','native_pilot_runs','native_pilot_observations','release_packages','release_decisions','release_policy_facts') "
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
                                                    '  -- FixedObject.ref is a closed, '
                                                    'server-resolved version reference, not '
                                                    'arbitrary body UUID text.\n'
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
                                                    ' -- These stored fields are validated '
                                                    'Reference containers. Do not feed the\n'
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
                                                    ' -- commercial_target, voice, and competitor '
                                                    'have nested source contracts.\n'
                                                    " IF table_name='proposal_item_versions' AND "
                                                    "payload->>'kind'='commercial_target' THEN\n"
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['target_price','cost','volume'] LOOP\n"
                                                    '   links=links || '
                                                    "public.m3_lifecycle_typed_links(t,c,payload->'content'->key->'source');\n"
                                                    '  END LOOP;\n'
                                                    ' ELSIF '
                                                    "table_name='category_knowledge_entries' AND "
                                                    "payload->>'kind'='voice' THEN\n"
                                                    '  links=links || '
                                                    "public.m3_lifecycle_typed_links(t,c,payload->'content'->'representative_refs');\n"
                                                    ' ELSIF '
                                                    "table_name='category_knowledge_entries' AND "
                                                    "payload->>'kind'='competitor' THEN\n"
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
                                                    '   -- The frozen read projection records '
                                                    'actual EvidenceLink provenance here.\n'
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
                                                    ' -- dependency; lifecycle cleanup must not '
                                                    'erase their audit source.\n'
                                                    " IF table_name='proposal_item_versions' AND "
                                                    "payload->>'item_id' IS NOT NULL THEN\n"
                                                    "  target_kind='proposal_item'; "
                                                    "referenced_target=(payload->>'item_id')::uuid;\n"
                                                    '  '
                                                    "referenced_version=(payload->>'version')::integer;\n"
                                                    ' ELSIF '
                                                    "table_name='category_knowledge_entries' AND "
                                                    "payload->>'id' IS NOT NULL THEN\n"
                                                    "  target_kind='knowledge_entry'; "
                                                    "referenced_target=(payload->>'id')::uuid;\n"
                                                    '  '
                                                    "referenced_version=(payload->>'version')::integer;\n"
                                                    " ELSIF table_name='definition_specs' AND "
                                                    "payload->>'id' IS NOT NULL THEN\n"
                                                    "  target_kind='definition_spec'; "
                                                    "referenced_target=(payload->>'id')::uuid;\n"
                                                    '  SELECT revision INTO referenced_version '
                                                    'FROM public.definition_revisions\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "id=(payload->>'definition_id')::uuid;\n"
                                                    ' END IF;\n'
                                                    ' IF referenced_target IS NOT NULL AND '
                                                    'referenced_version IS NOT NULL THEN\n'
                                                    '  SELECT '
                                                    "coalesce(array_agg(link.evidence_id),'{}') "
                                                    'INTO extra FROM public.evidence_links link\n'
                                                    '   WHERE link.tenant_id=t AND '
                                                    'link.category_id=c AND '
                                                    'link.target_type=target_kind\n'
                                                    '    AND link.target_id=referenced_target AND '
                                                    'link.target_version=referenced_version;\n'
                                                    '  links=links || extra;\n'
                                                    ' END IF;\n'
                                                    ' -- Child source rows point to their parent, '
                                                    'whereas dependency traversal needs\n'
                                                    " -- the parent's fixed source children as "
                                                    'well. Keep the actual relational edge.\n'
                                                    " IF table_name='definition_revisions' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO "
                                                    'extra FROM (\n'
                                                    '   SELECT id FROM public.definition_sources '
                                                    'WHERE tenant_id=t AND category_id=c\n'
                                                    "    AND definition_id=(payload->>'id')::uuid\n"
                                                    '   UNION ALL SELECT id FROM '
                                                    'public.definition_specs WHERE tenant_id=t AND '
                                                    'category_id=c\n'
                                                    "    AND definition_id=(payload->>'id')::uuid\n"
                                                    '  ) children;\n'
                                                    '  links=links || extra;\n'
                                                    " ELSIF table_name='proposals' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO "
                                                    'extra FROM public.proposal_item_versions\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "proposal_id=(payload->>'id')::uuid;\n"
                                                    '  links=links || extra;\n'
                                                    " ELSIF table_name='proposal_items' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO "
                                                    'extra FROM public.proposal_item_versions\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "item_id=(payload->>'id')::uuid;\n"
                                                    '  links=links || extra;\n'
                                                    " ELSIF table_name='product_target_segments' "
                                                    'THEN\n'
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO "
                                                    'extra FROM public.category_knowledge_entries\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "lineage_id=(payload->>'segment_lineage_id')::uuid\n"
                                                    '    AND '
                                                    "version=(payload->>'segment_version')::integer;\n"
                                                    '  links=links || extra;\n'
                                                    " ELSIF table_name='parameter_current' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO "
                                                    'extra FROM public.parameter_versions\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "parameter_id=(payload->>'parameter_id')::uuid\n"
                                                    '    AND '
                                                    "version=(payload->>'current_version')::integer;\n"
                                                    '  links=links || extra;\n'
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
                                                 "  WHEN 'proposal_items' THEN "
                                                 "ARRAY['proposal_id']\n"
                                                 "  WHEN 'proposal_item_versions' THEN "
                                                 "ARRAY['proposal_id','item_id']\n"
                                                 "  WHEN 'proposal_sources' THEN "
                                                 "ARRAY['proposal_id']\n"
                                                 "  WHEN 'proposal_submissions' THEN "
                                                 "ARRAY['proposal_id']\n"
                                                 "  WHEN 'proposal_decisions' THEN "
                                                 "ARRAY['proposal_id','created_definition_id']\n"
                                                 "  WHEN 'evidence_links' THEN ARRAY['target_id']\n"
                                                 "  WHEN 'manufacturing_baseline_publications' "
                                                 "THEN ARRAY['project_id']\n"
                                                 "  WHEN 'manufacturing_publication_currents' THEN "
                                                 "ARRAY['series_id']\n"
                                                 "  WHEN 'manufacturing_publication_documents' "
                                                 "THEN ARRAY['publication_id']\n"
                                                 "  WHEN 'native_pilot_runs' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'native_pilot_currents' THEN "
                                                 "ARRAY['pilot_id']\n"
                                                 "  WHEN 'native_pilot_observations' THEN "
                                                 "ARRAY['pilot_id']\n"
                                                 "  WHEN 'release_packages' THEN "
                                                 "ARRAY['project_id','series_id']\n"
                                                 "  WHEN 'release_package_currents' THEN "
                                                 "ARRAY['series_id']\n"
                                                 "  WHEN 'release_decisions' THEN "
                                                 "ARRAY['package_id']\n"
                                                 "  WHEN 'release_policy_facts' THEN "
                                                 "ARRAY['project_id','series_id']\n"
                                                 "  WHEN 'release_policy_currents' THEN "
                                                 "ARRAY['series_id']\n"
                                                 '  ELSE ARRAY[]::text[] END;\n'
                                                 ' FOREACH key IN ARRAY keys LOOP\n'
                                                 '  IF payload->>key IS NOT NULL THEN '
                                                 'links=array_append(links,(payload->>key)::uuid); '
                                                 'END IF;\n'
                                                 ' END LOOP;\n'
                                                 ' RETURN links;\n'
                                                 'END;\n'
                                                 '$function$\n'}

SCHEMA_SQL = ('\n'
 'CREATE TABLE release_policy_facts (\n'
 '\tproduct_id UUID NOT NULL, \n'
 '\tproject_id UUID NOT NULL, \n'
 '\tseries_id UUID NOT NULL, \n'
 '\trevision INTEGER NOT NULL, \n'
 '\tepoch INTEGER NOT NULL, \n'
 '\tprevious_id UUID, \n'
 '\tprevious_revision INTEGER, \n'
 '\towner_id UUID NOT NULL, \n'
 '\twriter_id UUID NOT NULL, \n'
 '\tactor_id UUID NOT NULL, \n'
 '\trequester_id UUID NOT NULL, \n'
 '\tvisibility VARCHAR(16) NOT NULL, \n'
 '\tpurpose TEXT NOT NULL, \n'
 '\tpurpose_sha256 VARCHAR(64) NOT NULL, \n'
 '\tpolicy_version TEXT NOT NULL, \n'
 '\tstatus VARCHAR(16) NOT NULL, \n'
 '\tnature VARCHAR(16) NOT NULL, \n'
 '\toperation VARCHAR(80) NOT NULL, \n'
 '\tvalid_from TIMESTAMP WITH TIME ZONE, \n'
 '\tvalid_until TIMESTAMP WITH TIME ZONE, \n'
 '\tmaterial JSONB NOT NULL, \n'
 '\tmaterial_sha256 VARCHAR(64) NOT NULL, \n'
 '\tsource JSONB NOT NULL, \n'
 '\tsources JSONB NOT NULL, \n'
 '\trequired_source_read_set JSONB NOT NULL, \n'
 '\tsource_basis JSONB NOT NULL, \n'
 '\tauthority_snapshot JSONB NOT NULL, \n'
 '\tinput_snapshot JSONB NOT NULL, \n'
 '\tintent_digest VARCHAR(64) NOT NULL, \n'
 '\trequest_digest VARCHAR(64) NOT NULL, \n'
 '\tfact_sha256 VARCHAR(64) NOT NULL, \n'
 '\tcommand_id UUID NOT NULL, \n'
 '\treceipt_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tcategory_id UUID NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(tenant_id, category_id, product_id) REFERENCES products (tenant_id, category_id, '
 'id), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id) REFERENCES projects (tenant_id, product_id, '
 'id), \n'
 '\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n'
 "\tCHECK (visibility IN ('private','category','audience')), \n"
 '\tCHECK (revision>0 AND epoch=revision), \n'
 "\tCHECK (purpose_sha256 ~ '^[a-f0-9]{64}$'), \n"
 '\tUNIQUE (tenant_id, id), \n'
 '\tUNIQUE (tenant_id, product_id, project_id, purpose_sha256, revision), \n'
 '\tUNIQUE (tenant_id, category_id, product_id, project_id, purpose_sha256, series_id, owner_id, '
 'visibility, id, revision), \n'
 '\tUNIQUE (tenant_id, category_id, product_id, project_id, purpose_sha256, series_id, owner_id, '
 'visibility, id, revision, epoch), \n'
 '\tUNIQUE (tenant_id, receipt_id), \n'
 '\tUNIQUE (tenant_id, command_id), \n'
 '\tUNIQUE (tenant_id, product_id, actor_id, operation, intent_digest), \n'
 '\tFOREIGN KEY(tenant_id, category_id, product_id, project_id, purpose_sha256, series_id, '
 'owner_id, visibility, previous_id, previous_revision) REFERENCES release_policy_facts '
 '(tenant_id, category_id, product_id, project_id, purpose_sha256, series_id, owner_id, '
 'visibility, id, revision) DEFERRABLE INITIALLY DEFERRED, \n'
 '\tFOREIGN KEY(tenant_id, writer_id) REFERENCES principals (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, actor_id) REFERENCES principals (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, requester_id) REFERENCES principals (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, receipt_id) REFERENCES action_receipts (tenant_id, id) DEFERRABLE '
 'INITIALLY DEFERRED, \n'
 '\tCHECK ((revision=1 AND epoch=1 AND series_id=id AND previous_id IS NULL AND previous_revision '
 'IS NULL) OR (revision>1 AND previous_id IS NOT NULL AND previous_id<>id AND previous_revision>0 '
 'AND revision=previous_revision+1)), \n'
 "\tCHECK (operation='release.policy.import' AND status IN ('active','withdrawn')), \n"
 "\tCHECK (nature IN ('real','synthetic')), \n"
 '\tCHECK (writer_id=actor_id AND actor_id=requester_id), \n'
 '\tCHECK (valid_from IS NULL OR valid_until IS NULL OR valid_from<valid_until), \n'
 '\tCHECK (length(purpose)>0 AND length(policy_version)>0), \n'
 "\tCHECK (jsonb_typeof(material)='object' AND jsonb_typeof(source)='object' AND "
 "jsonb_typeof(source_basis)='object' AND jsonb_typeof(authority_snapshot)='object' AND "
 "jsonb_typeof(input_snapshot)='object' AND jsonb_typeof(sources)='array' AND "
 "jsonb_array_length(sources)>0 AND jsonb_typeof(required_source_read_set)='array' AND "
 'jsonb_array_length(required_source_read_set)>0), \n'
 "\tCHECK (material_sha256 ~ '^[a-f0-9]{64}$' AND fact_sha256 ~ '^[a-f0-9]{64}$' AND intent_digest "
 "~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_release_policy_facts_category_id ON release_policy_facts (category_id)',
 'CREATE INDEX ix_release_policy_facts_tenant_id ON release_policy_facts (tenant_id)',
 '\n'
 'CREATE TABLE release_policy_currents (\n'
 '\tproduct_id UUID NOT NULL, \n'
 '\tproject_id UUID NOT NULL, \n'
 '\tpurpose_sha256 VARCHAR(64) NOT NULL, \n'
 '\tseries_id UUID NOT NULL, \n'
 '\towner_id UUID NOT NULL, \n'
 '\tvisibility VARCHAR(16) NOT NULL, \n'
 '\tfact_id UUID NOT NULL, \n'
 '\trevision INTEGER NOT NULL, \n'
 '\tepoch INTEGER NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tcategory_id UUID NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(tenant_id, category_id, product_id) REFERENCES products (tenant_id, category_id, '
 'id), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id) REFERENCES projects (tenant_id, product_id, '
 'id), \n'
 '\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n'
 "\tCHECK (visibility IN ('private','category','audience')), \n"
 '\tCHECK (revision>0 AND epoch=revision), \n'
 "\tCHECK (purpose_sha256 ~ '^[a-f0-9]{64}$'), \n"
 '\tUNIQUE (tenant_id, product_id, project_id, purpose_sha256), \n'
 '\tFOREIGN KEY(tenant_id, category_id, product_id, project_id, purpose_sha256, series_id, '
 'owner_id, visibility, fact_id, revision, epoch) REFERENCES release_policy_facts (tenant_id, '
 'category_id, product_id, project_id, purpose_sha256, series_id, owner_id, visibility, id, '
 'revision, epoch)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_release_policy_currents_category_id ON release_policy_currents (category_id)',
 'CREATE INDEX ix_release_policy_currents_tenant_id ON release_policy_currents (tenant_id)',
 'CREATE FUNCTION public.assert_release_policy_members(t uuid,target uuid) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_policy$\n'
 '\n'
 'DECLARE v public.release_policy_facts; r public.action_receipts;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT v FROM public.release_policy_facts WHERE tenant_id=t AND id=target;\n'
 ' SELECT * INTO STRICT r FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;\n'
 ' IF '
 'ROW(r.category_id,r.product_id,r.command_id,r.actor_id,r.requester_id,r.operation,r.subject_type,\n'
 '    r.subject_id,r.subject_revision,r.visibility,r.request_digest,r.intent_digest)\n'
 '  IS DISTINCT FROM '
 "ROW(v.category_id,v.product_id,v.command_id,v.actor_id,v.requester_id,'release.policy.import'::varchar,\n"
 '    '
 "'release_policy_fact'::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)\n"
 '  OR r.confirmation_id IS NOT NULL OR r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL\n'
 '  OR r.result IS DISTINCT FROM '
 "jsonb_build_object('id',v.id,'revision',v.revision,'status',v.status)\n"
 '  OR r.created_at<v.created_at\n'
 '  OR (SELECT count(*) FROM public.action_receipts x WHERE x.tenant_id=t AND '
 "x.operation='release.policy.import'\n"
 "    AND x.subject_type='release_policy_fact' AND x.subject_id=v.id AND "
 'x.subject_revision=v.revision)<>1\n'
 '  OR (SELECT count(*) FROM public.audit_entries x WHERE x.tenant_id=t AND x.receipt_id=r.id)<>1\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.audit_entries a WHERE a.tenant_id=t AND a.receipt_id=r.id\n'
 '    AND a.category_id=v.category_id AND a.actor_id=v.actor_id AND a.operation=v.operation AND '
 'a.created_at>=v.created_at)\n'
 '  OR (SELECT count(*) FROM public.outbox_events x WHERE x.tenant_id=t AND x.receipt_id=r.id)<>1\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.outbox_events e WHERE e.tenant_id=t AND e.receipt_id=r.id\n'
 '    AND e.category_id=v.category_id AND e.actor_id=v.actor_id AND '
 "e.type='release.policy_imported'\n"
 '    AND e.subject_id=v.id AND e.subject_revision=v.revision AND e.schema_version=1\n'
 '    AND e.correlation_id=coalesce(r.agent_run_id,r.run_id,v.command_id) AND '
 'e.created_at>=v.created_at)\n'
 "  OR v.input_snapshot->>'original_key_sha256' IS NULL\n"
 "  OR v.input_snapshot->>'original_key_sha256' !~ '^[a-f0-9]{64}$'\n"
 '  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND '
 'k.category_id=v.category_id\n'
 '    AND k.receipt_id=r.id AND k.actor_id=v.actor_id AND k.digest=v.request_digest\n'
 "    AND encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.input_snapshot->>'original_key_sha256') "
 'THEN\n'
 "  RAISE EXCEPTION 'Release policy original common group mismatch' USING ERRCODE='23514'; END "
 'IF;\n'
 'END;\n'
 '$release_policy$',
 'CREATE FUNCTION public.assert_release_policy_atom(t uuid,target uuid) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_policy$\n'
 '\n'
 'DECLARE v public.release_policy_facts; cur public.release_policy_currents; a '
 'public.artifact_versions;\n'
 ' ref jsonb; basis jsonb; auth jsonb; position text[]; line text; vx xid; cx xid; rx xid;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT v FROM public.release_policy_facts WHERE tenant_id=t AND id=target;\n'
 ' SELECT xmin INTO vx FROM public.release_policy_facts WHERE tenant_id=t AND id=target;\n'
 ' SELECT * INTO STRICT cur FROM public.release_policy_currents WHERE tenant_id=t AND '
 'product_id=v.product_id\n'
 '  AND project_id=v.project_id AND purpose_sha256=v.purpose_sha256;\n'
 ' SELECT xmin INTO cx FROM public.release_policy_currents WHERE tenant_id=t AND id=cur.id;\n'
 ' SELECT xmin INTO rx FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;\n'
 ' PERFORM public.assert_release_policy_members(t,target);\n'
 ' IF v.actor_id IS DISTINCT FROM public.scope_actor() OR v.requester_id IS DISTINCT FROM '
 'public.scope_requester()\n'
 '  OR v.actor_id<>v.requester_id OR v.writer_id<>v.actor_id OR NOT '
 'public.category_access(t,v.category_id,true)\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=t AND p.id=v.actor_id AND '
 "p.kind='human' AND p.active)\n"
 '  OR NOT EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=t AND '
 'p.category_id=v.category_id\n'
 '    AND p.product_id=v.product_id AND p.id=v.project_id AND p.owner_id=v.owner_id)\n'
 '  OR vx IS DISTINCT FROM cx OR vx IS DISTINCT FROM rx\n'
 '  OR '
 'ROW(cur.category_id,cur.product_id,cur.project_id,cur.series_id,cur.owner_id,cur.visibility,cur.fact_id,cur.revision,cur.epoch)\n'
 '   IS DISTINCT FROM '
 'ROW(v.category_id,v.product_id,v.project_id,v.series_id,v.owner_id,v.visibility,v.id,v.revision,v.epoch)\n'
 '  OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(v.input_snapshot) key)\n'
 "   IS DISTINCT FROM ARRAY['original_key_sha256','payload']\n"
 "  OR v.input_snapshot->'payload'->>'project_id' IS DISTINCT FROM v.project_id::text\n"
 "  OR v.input_snapshot->'payload'->'source' IS DISTINCT FROM v.source\n"
 "  OR (v.revision=1 AND v.input_snapshot->'payload'->'expected_previous' IS DISTINCT FROM "
 "'null'::jsonb)\n"
 "  OR (v.revision>1 AND v.input_snapshot->'payload'->'expected_previous'\n"
 "   IS DISTINCT FROM jsonb_build_object('id',v.previous_id,'revision',v.previous_revision))\n"
 "  OR v.material->'scope' IS DISTINCT FROM "
 "jsonb_build_object('tenant_id',t,'product_id',v.product_id,'project_id',v.project_id)\n"
 "  OR v.material->>'category_id' IS DISTINCT FROM v.category_id::text\n"
 "  OR v.material->>'publisher_id' IS DISTINCT FROM v.actor_id::text\n"
 "  OR v.material->>'owner_id' IS DISTINCT FROM v.owner_id::text\n"
 "  OR v.material->>'visibility' IS DISTINCT FROM v.visibility\n"
 "  OR v.material->>'purpose' IS DISTINCT FROM v.purpose\n"
 "  OR v.material->>'policy_version' IS DISTINCT FROM v.policy_version\n"
 "  OR v.material->>'nature' IS DISTINCT FROM v.nature\n"
 "  OR v.material->>'status' IS DISTINCT FROM v.status\n"
 "  OR (v.material->>'valid_from')::timestamptz IS DISTINCT FROM v.valid_from\n"
 "  OR (v.material->>'valid_until')::timestamptz IS DISTINCT FROM v.valid_until\n"
 '  OR NOT '
 'public.direct_source_set_visible(t,v.category_id,v.product_id,v.required_source_read_set)\n'
 '  OR NOT(v.sources @> jsonb_build_array(v.source))\n'
 '  OR EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)\n'
 '  OR EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND '
 'k.receipt_id=v.receipt_id\n'
 '    AND k.actor_id=v.actor_id AND k.digest=v.request_digest AND k.xmin=vx\n'
 "    AND encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.input_snapshot->>'original_key_sha256') "
 'THEN\n'
 "  RAISE EXCEPTION 'Release policy requires actual named scope and one transaction' USING "
 "ERRCODE='23514'; END IF;\n"
 ' '
 "position=regexp_match(v.source->>'position','^line:([1-9][0-9]*);quote_sha256:([a-f0-9]{64})$');\n"
 " IF v.source->>'kind' IS DISTINCT FROM 'artifact' OR position IS NULL\n"
 "  OR jsonb_typeof(v.source->'revision') IS DISTINCT FROM 'number' THEN\n"
 "  RAISE EXCEPTION 'Release policy requires an exact original artifact line' USING "
 "ERRCODE='23514'; END IF;\n"
 ' SELECT * INTO STRICT a FROM public.artifact_versions WHERE tenant_id=t AND '
 'category_id=v.category_id\n'
 "  AND id::text=v.source->>'id' AND revision::text=v.source->>'revision' AND status='active';\n"
 ' '
 "line=(regexp_split_to_array(a.content,E'\\r\\n|[\\n\\r\\013\\014\\034-\\036\\u0085\\u2028\\u2029]'))[position[1]::integer];\n"
 " IF line IS NULL OR encode(sha256(convert_to(line,'UTF8')),'hex')<>position[2] OR line::jsonb IS "
 'DISTINCT FROM v.material THEN\n'
 "  RAISE EXCEPTION 'Release policy original material changed' USING ERRCODE='23514'; END IF;\n"
 ' IF (SELECT count(*) FROM '
 'jsonb_object_keys(v.source_basis))<>jsonb_array_length(v.required_source_read_set)\n'
 "  OR (SELECT count(DISTINCT x->>'artifact_id') FROM "
 'jsonb_array_elements(v.required_source_read_set) x)\n'
 '   <>jsonb_array_length(v.required_source_read_set) THEN\n'
 "  RAISE EXCEPTION 'Release policy complete source basis required' USING ERRCODE='23514'; END "
 'IF;\n'
 ' FOR ref IN SELECT value FROM jsonb_array_elements(v.required_source_read_set) LOOP\n'
 "  basis=v.source_basis->(ref->>'artifact_id');\n"
 "  IF basis IS NULL OR jsonb_typeof(ref->'expected_revision') IS DISTINCT FROM 'number'\n"
 '   OR NOT EXISTS(SELECT 1 FROM public.artifact_versions art WHERE art.tenant_id=t AND '
 'art.category_id=v.category_id\n'
 "    AND art.id::text=ref->>'artifact_id' AND art.revision::text=ref->>'expected_revision' AND "
 "art.status='active'\n"
 "    AND art.revision::text=basis->>'revision' AND art.content_hash=basis->>'sha256'\n"
 "    AND art.owner_id::text=basis->>'owner_id' AND art.visibility=basis->>'visibility'\n"
 "    AND (v.visibility='private' OR art.visibility<>'private')\n"
 '    AND (art.original_id IS NULL OR EXISTS(SELECT 1 FROM public.uploaded_originals o\n'
 '     JOIN public.original_security sec ON sec.tenant_id=o.tenant_id AND sec.original_id=o.id\n'
 '     WHERE o.tenant_id=t AND o.category_id=v.category_id AND o.id=art.original_id AND '
 "o.status='parsed'\n"
 "      AND o.id::text=basis->>'original_id' AND o.revision::text=basis->>'original_revision'\n"
 "      AND o.content_hash=basis->>'original_sha256' AND "
 "o.owner_id::text=basis->>'original_owner_id'\n"
 "      AND o.visibility=basis->>'original_visibility' AND "
 "sec.epoch::text=basis->>'security_epoch'\n"
 "      AND sec.source_state='active' AND sec.disposition='active' AND (v.visibility='private' OR "
 "o.visibility<>'private')))) THEN\n"
 "   RAISE EXCEPTION 'Release policy direct source version security or audience changed' USING "
 "ERRCODE='23514'; END IF;\n"
 ' END LOOP;\n'
 ' IF EXISTS(SELECT 1 FROM jsonb_array_elements(v.sources) src WHERE NOT EXISTS(\n'
 '   SELECT 1 FROM jsonb_array_elements(v.required_source_read_set) rd\n'
 "   WHERE rd->>'artifact_id'=src->>'id' AND rd->'expected_revision'=src->'revision')) THEN\n"
 "  RAISE EXCEPTION 'Release policy sources must be in the actual read set' USING ERRCODE='23514'; "
 'END IF;\n'
 ' auth=v.authority_snapshot;\n'
 " IF EXISTS(SELECT 1 FROM jsonb_array_elements(auth->'required_source_read_set') rd\n"
 '   WHERE NOT (v.required_source_read_set @> jsonb_build_array(rd))) THEN\n'
 "  RAISE EXCEPTION 'Release policy must retain actual publisher sources' USING ERRCODE='23514'; "
 'END IF;\n'
 " IF auth->'scope' IS DISTINCT FROM v.material->'scope' OR auth->>'subject_id' IS DISTINCT FROM "
 'v.actor_id::text\n'
 "  OR auth->>'operation' IS DISTINCT FROM 'release.policy.import' OR auth->>'purpose' IS DISTINCT "
 'FROM v.purpose\n'
 "  OR auth->'authorized' IS DISTINCT FROM 'true'::jsonb OR auth->'qualified' IS DISTINCT FROM "
 "'true'::jsonb\n"
 "  OR auth->'synthetic' IS DISTINCT FROM to_jsonb(v.nature='synthetic')\n"
 '  OR NOT public.capture_authority_time_current(auth,v.created_at)\n'
 "  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(auth->'roles') r WHERE r IN "
 "('engineering','manufacturing','quality'))\n"
 "  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(auth->'fact_refs')) THEN\n"
 "  RAISE EXCEPTION 'Release policy requires actual publisher authority' USING ERRCODE='23514'; "
 'END IF;\n'
 " FOR ref IN SELECT value FROM jsonb_array_elements(auth->'fact_refs') LOOP\n"
 '  IF NOT EXISTS(SELECT 1 FROM public.professional_authority_facts f JOIN '
 'public.professional_authority_current p\n'
 '    ON p.tenant_id=f.tenant_id AND p.category_id=f.category_id AND p.product_id=f.product_id AND '
 'p.project_id=f.project_id\n'
 '    AND p.subject_id=f.subject_id AND p.kind=f.kind AND p.series_id=f.series_id AND '
 'p.fact_id=f.id AND p.fact_revision=f.revision\n'
 '   WHERE f.tenant_id=t AND f.category_id=v.category_id AND f.product_id=v.product_id AND '
 'f.project_id=v.project_id\n'
 "    AND f.subject_id=v.actor_id AND f.id::text=ref->>'id' AND f.revision::text=ref->>'revision'\n"
 "    AND p.epoch::text=ref->>'epoch' AND f.fact_sha256=ref->>'fact_sha256'\n"
 "    AND f.series_id::text=ref->>'series_id' AND f.kind=ref->>'kind' AND f.role=ref->>'role'\n"
 "    AND f.state=ref->>'state' AND f.nature=ref->>'nature' AND f.issuer_key=ref->>'issuer_key'\n"
 "    AND f.issuer_version=ref->>'issuer_version' AND f.operations=ref->'operations' AND "
 "f.purposes=ref->'purposes'\n"
 "    AND f.valid_from IS NOT DISTINCT FROM (ref->>'valid_from')::timestamptz\n"
 "    AND f.valid_until IS NOT DISTINCT FROM (ref->>'valid_until')::timestamptz) THEN\n"
 "   RAISE EXCEPTION 'Release policy professional fact or Current changed' USING ERRCODE='23514'; "
 'END IF;\n'
 ' END LOOP;\n'
 " IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(auth->'roles') AS roles(role_name)\n"
 "   WHERE role_name IN ('engineering','manufacturing','quality') AND NOT EXISTS(\n"
 "    SELECT kind FROM unnest(ARRAY['duty','qualification']) kind WHERE NOT EXISTS(\n"
 "     SELECT 1 FROM jsonb_array_elements(auth->'fact_refs') f WHERE f->>'kind'=kind AND "
 "f->>'role'=role_name\n"
 "      AND f->>'state'='active' AND (f->'operations') @> "
 '\'["release.policy.import"]\'::jsonb\n'
 "      AND (f->'purposes') @> jsonb_build_array(v.purpose)\n"
 "      AND (f->>'valid_from')::timestamptz<=v.created_at AND "
 "v.created_at<(f->>'valid_until')::timestamptz))) THEN\n"
 "  RAISE EXCEPTION 'Release policy needs an actual applicable duty and qualification' USING "
 "ERRCODE='23514'; END IF;\n"
 'END;\n'
 '$release_policy$',
 'CREATE FUNCTION public.protect_release_policy_current() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_policy$\n'
 '\n'
 'BEGIN\n'
 " IF TG_OP='INSERT' THEN\n"
 '  IF NEW.revision=1 AND NEW.epoch=1 AND NEW.fact_id=NEW.series_id THEN RETURN NEW; END IF;\n'
 " ELSIF TG_OP='UPDATE' THEN\n"
 "  IF (to_jsonb(NEW)-ARRAY['fact_id','revision','epoch']) IS NOT DISTINCT FROM\n"
 "    (to_jsonb(OLD)-ARRAY['fact_id','revision','epoch'])\n"
 '   AND NEW.revision=OLD.revision+1 AND NEW.epoch=OLD.epoch+1\n'
 '   AND EXISTS(SELECT 1 FROM public.release_policy_facts f WHERE f.tenant_id=NEW.tenant_id\n'
 '    AND f.category_id=NEW.category_id AND f.product_id=NEW.product_id AND '
 'f.project_id=NEW.project_id\n'
 '    AND f.purpose_sha256=NEW.purpose_sha256 AND f.series_id=NEW.series_id AND '
 'f.owner_id=NEW.owner_id\n'
 '    AND f.visibility=NEW.visibility AND f.id=NEW.fact_id AND f.revision=NEW.revision AND '
 'f.epoch=NEW.epoch\n'
 '    AND f.previous_id=OLD.fact_id AND f.previous_revision=OLD.revision) THEN RETURN NEW; END '
 'IF;\n'
 ' END IF;\n'
 " RAISE EXCEPTION 'Release policy Current advances one exact successor' USING ERRCODE='23514';\n"
 'END;\n'
 '$release_policy$',
 'CREATE FUNCTION public.require_release_policy_current() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_policy$\n'
 '\n'
 'DECLARE cur public.release_policy_currents; cx xid;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT cur FROM public.release_policy_currents WHERE tenant_id=NEW.tenant_id AND '
 'id=NEW.id;\n'
 ' SELECT xmin INTO cx FROM public.release_policy_currents WHERE tenant_id=NEW.tenant_id AND '
 'id=NEW.id;\n'
 ' IF NOT EXISTS(SELECT 1 FROM public.release_policy_facts f WHERE f.tenant_id=cur.tenant_id\n'
 '   AND f.category_id=cur.category_id AND f.product_id=cur.product_id AND '
 'f.project_id=cur.project_id\n'
 '   AND f.series_id=cur.series_id AND f.purpose_sha256=cur.purpose_sha256 AND '
 'f.owner_id=cur.owner_id\n'
 '   AND f.visibility=cur.visibility AND f.id=cur.fact_id AND f.revision=cur.revision AND '
 'f.epoch=cur.epoch AND f.xmin=cx) THEN\n'
 "  RAISE EXCEPTION 'Release policy Current requires its same-transaction fact' USING "
 "ERRCODE='23514'; END IF;\n"
 ' RETURN NULL;\n'
 'END;\n'
 '$release_policy$',
 'CREATE FUNCTION public.protect_release_policy_receipt() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_policy$\n'
 '\n'
 'DECLARE scoped boolean=false;\n'
 'BEGIN\n'
 " IF TG_OP<>'INSERT' THEN scoped=OLD.operation='release.policy.import' OR "
 "OLD.subject_type='release_policy_fact'; END IF;\n"
 " IF TG_OP<>'DELETE' THEN scoped=scoped OR NEW.operation='release.policy.import' OR "
 "NEW.subject_type='release_policy_fact'; END IF;\n"
 " IF scoped AND TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Release policy receipt is immutable' USING "
 "ERRCODE='23514'; END IF;\n"
 " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
 'END;\n'
 '$release_policy$',
 'CREATE FUNCTION public.protect_release_policy_member() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_policy$\n'
 '\n'
 'DECLARE scoped boolean=false; old_scoped boolean=false;\n'
 'BEGIN\n'
 " IF TG_OP<>'DELETE' THEN\n"
 '  SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=NEW.tenant_id AND '
 'r.id=NEW.receipt_id\n'
 "   AND (r.operation='release.policy.import' OR r.subject_type='release_policy_fact')) INTO "
 'scoped;\n'
 ' END IF;\n'
 " IF TG_OP<>'INSERT' THEN\n"
 '  SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=OLD.tenant_id AND '
 'r.id=OLD.receipt_id\n'
 "   AND (r.operation='release.policy.import' OR r.subject_type='release_policy_fact')) INTO "
 'old_scoped;\n'
 ' END IF;\n'
 " IF TG_OP<>'INSERT' AND (scoped OR old_scoped) THEN\n"
 "  IF TG_OP='UPDATE' AND TG_TABLE_NAME='outbox_events'\n"
 "   AND (to_jsonb(NEW)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) IS "
 'NOT DISTINCT FROM\n'
 "    (to_jsonb(OLD)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) THEN "
 'RETURN NEW; END IF;\n'
 "  RAISE EXCEPTION 'Release policy original common member is immutable' USING ERRCODE='23514'; "
 'END IF;\n'
 " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
 'END;\n'
 '$release_policy$',
 'CREATE FUNCTION public.require_release_policy_member() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_policy$\n'
 '\n'
 'DECLARE r public.action_receipts;\n'
 'BEGIN\n'
 " IF TG_TABLE_NAME='action_receipts' THEN r=NEW;\n"
 ' ELSE SELECT * INTO r FROM public.action_receipts WHERE tenant_id=NEW.tenant_id AND '
 'id=NEW.receipt_id; END IF;\n'
 " IF r.operation='release.policy.import' OR r.subject_type='release_policy_fact' THEN\n"
 "  IF r.operation IS DISTINCT FROM 'release.policy.import' OR r.subject_type IS DISTINCT FROM "
 "'release_policy_fact' THEN\n"
 "   RAISE EXCEPTION 'Release policy common subject mismatch' USING ERRCODE='23514'; END IF;\n"
 '  PERFORM public.assert_release_policy_members(r.tenant_id,r.subject_id);\n'
 ' END IF;\n'
 ' RETURN NULL;\n'
 'END;\n'
 '$release_policy$',
 'CREATE FUNCTION public.require_release_policy_atom() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_policy$\n'
 'BEGIN PERFORM public.assert_release_policy_atom(NEW.tenant_id,NEW.id); RETURN NULL; END;\n'
 '$release_policy$',
 'CREATE FUNCTION public.reject_release_policy_mutation() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_policy$\n'
 "BEGIN RAISE EXCEPTION 'Release policy history is immutable' USING ERRCODE='23514'; END;\n"
 '$release_policy$',
 'REVOKE ALL ON FUNCTION public.assert_release_policy_members(uuid,uuid) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.assert_release_policy_atom(uuid,uuid) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.protect_release_policy_current() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.require_release_policy_current() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.protect_release_policy_receipt() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.protect_release_policy_member() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.require_release_policy_member() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.require_release_policy_atom() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.reject_release_policy_mutation() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'ALTER TABLE public."release_policy_facts" ENABLE ROW LEVEL SECURITY',
 'ALTER TABLE public."release_policy_facts" FORCE ROW LEVEL SECURITY',
 'CREATE POLICY owner_internal ON public."release_policy_facts" TO pdos_next_owner USING (true) '
 'WITH CHECK (true)',
 'CREATE POLICY release_policy_read ON public."release_policy_facts" FOR SELECT TO pdos_next_app '
 'USING (public.category_access(tenant_id,category_id) AND '
 "(release_policy_facts.visibility='category' OR "
 'release_policy_facts.owner_id=public.scope_requester() OR EXISTS(SELECT 1 FROM '
 'public.object_audiences a WHERE a.tenant_id=release_policy_facts.tenant_id AND '
 "a.category_id=release_policy_facts.category_id AND a.object_type='release_policy_facts' AND "
 'a.subject_id=release_policy_facts.id AND a.owner_id=release_policy_facts.owner_id AND '
 'a.principal_id=public.scope_requester())) AND EXISTS(SELECT 1 FROM public.products p WHERE '
 'p.tenant_id=release_policy_facts.tenant_id AND p.category_id=release_policy_facts.category_id '
 'AND p.id=release_policy_facts.product_id) AND EXISTS(SELECT 1 FROM public.projects p WHERE '
 'p.tenant_id=release_policy_facts.tenant_id AND p.category_id=release_policy_facts.category_id '
 'AND p.product_id=release_policy_facts.product_id AND p.id=release_policy_facts.project_id) AND '
 'public.direct_source_set_visible(tenant_id,category_id,product_id,release_policy_facts.required_source_read_set))',
 'CREATE POLICY release_policy_insert ON public."release_policy_facts" FOR INSERT TO pdos_next_app '
 'WITH CHECK (public.category_access(tenant_id,category_id,true) AND '
 'public.scope_actor()=public.scope_requester() AND EXISTS(SELECT 1 FROM public.principals p WHERE '
 "p.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND "
 "p.id=public.scope_actor() AND p.kind='human' AND p.active) AND "
 "public.category_access(tenant_id,category_id) AND (release_policy_facts.visibility='category' OR "
 'release_policy_facts.owner_id=public.scope_requester() OR EXISTS(SELECT 1 FROM '
 'public.object_audiences a WHERE a.tenant_id=release_policy_facts.tenant_id AND '
 "a.category_id=release_policy_facts.category_id AND a.object_type='release_policy_facts' AND "
 'a.subject_id=release_policy_facts.id AND a.owner_id=release_policy_facts.owner_id AND '
 'a.principal_id=public.scope_requester())) AND EXISTS(SELECT 1 FROM public.products p WHERE '
 'p.tenant_id=release_policy_facts.tenant_id AND p.category_id=release_policy_facts.category_id '
 'AND p.id=release_policy_facts.product_id) AND EXISTS(SELECT 1 FROM public.projects p WHERE '
 'p.tenant_id=release_policy_facts.tenant_id AND p.category_id=release_policy_facts.category_id '
 'AND p.product_id=release_policy_facts.product_id AND p.id=release_policy_facts.project_id) AND '
 'public.direct_source_set_visible(tenant_id,category_id,product_id,release_policy_facts.required_source_read_set))',
 'REVOKE ALL ON public."release_policy_facts" FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'GRANT SELECT,INSERT ON public."release_policy_facts" TO pdos_next_app',
 'ALTER TABLE public."release_policy_currents" ENABLE ROW LEVEL SECURITY',
 'ALTER TABLE public."release_policy_currents" FORCE ROW LEVEL SECURITY',
 'CREATE POLICY owner_internal ON public."release_policy_currents" TO pdos_next_owner USING (true) '
 'WITH CHECK (true)',
 'CREATE POLICY release_policy_read ON public."release_policy_currents" FOR SELECT TO '
 'pdos_next_app USING (public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM '
 'public.release_policy_facts f WHERE f.tenant_id=release_policy_currents.tenant_id AND '
 'f.category_id=release_policy_currents.category_id AND '
 'f.product_id=release_policy_currents.product_id AND '
 'f.project_id=release_policy_currents.project_id AND f.id=release_policy_currents.fact_id AND '
 'f.revision=release_policy_currents.revision AND f.epoch=release_policy_currents.epoch))',
 'CREATE POLICY release_policy_insert ON public."release_policy_currents" FOR INSERT TO '
 'pdos_next_app WITH CHECK (public.category_access(tenant_id,category_id,true) AND '
 'public.scope_actor()=public.scope_requester() AND EXISTS(SELECT 1 FROM public.principals p WHERE '
 "p.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND "
 "p.id=public.scope_actor() AND p.kind='human' AND p.active) AND "
 'public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM '
 'public.release_policy_facts f WHERE f.tenant_id=release_policy_currents.tenant_id AND '
 'f.category_id=release_policy_currents.category_id AND '
 'f.product_id=release_policy_currents.product_id AND '
 'f.project_id=release_policy_currents.project_id AND f.id=release_policy_currents.fact_id AND '
 'f.revision=release_policy_currents.revision AND f.epoch=release_policy_currents.epoch))',
 'REVOKE ALL ON public."release_policy_currents" FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'GRANT SELECT,INSERT ON public."release_policy_currents" TO pdos_next_app',
 'CREATE POLICY release_policy_advance ON public."release_policy_currents" FOR UPDATE TO '
 'pdos_next_app USING (public.category_access(tenant_id,category_id,true) AND '
 'public.scope_actor()=public.scope_requester() AND EXISTS(SELECT 1 FROM public.principals p WHERE '
 "p.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND "
 "p.id=public.scope_actor() AND p.kind='human' AND p.active) AND "
 'public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM '
 'public.release_policy_facts f WHERE f.tenant_id=release_policy_currents.tenant_id AND '
 'f.category_id=release_policy_currents.category_id AND '
 'f.product_id=release_policy_currents.product_id AND '
 'f.project_id=release_policy_currents.project_id AND f.id=release_policy_currents.fact_id AND '
 'f.revision=release_policy_currents.revision AND f.epoch=release_policy_currents.epoch)) WITH '
 'CHECK (public.category_access(tenant_id,category_id,true) AND '
 'public.scope_actor()=public.scope_requester() AND EXISTS(SELECT 1 FROM public.principals p WHERE '
 "p.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND "
 "p.id=public.scope_actor() AND p.kind='human' AND p.active) AND "
 'public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM '
 'public.release_policy_facts f WHERE f.tenant_id=release_policy_currents.tenant_id AND '
 'f.category_id=release_policy_currents.category_id AND '
 'f.product_id=release_policy_currents.product_id AND '
 'f.project_id=release_policy_currents.project_id AND f.id=release_policy_currents.fact_id AND '
 'f.revision=release_policy_currents.revision AND f.epoch=release_policy_currents.epoch))',
 'GRANT UPDATE(fact_id,revision,epoch) ON public."release_policy_currents" TO pdos_next_app',
 'CREATE POLICY release_policy_receipt_insert ON public.action_receipts FOR INSERT TO '
 "pdos_next_app WITH CHECK (operation='release.policy.import' AND "
 "subject_type='release_policy_fact' AND confirmation_id IS NULL AND run_id IS NULL AND "
 'agent_run_id IS NULL AND actor_id=public.scope_actor() AND requester_id=public.scope_requester() '
 'AND actor_id=requester_id AND public.category_access(tenant_id,category_id,true) AND '
 'EXISTS(SELECT 1 FROM public.release_policy_facts f WHERE f.tenant_id=action_receipts.tenant_id '
 'AND f.category_id=action_receipts.category_id AND f.product_id=action_receipts.product_id AND '
 'f.id=action_receipts.subject_id AND f.revision=action_receipts.subject_revision AND '
 'f.receipt_id=action_receipts.id AND f.actor_id=action_receipts.actor_id))',
 'CREATE POLICY release_policy_member_insert ON public.audit_entries FOR INSERT TO pdos_next_app '
 'WITH CHECK (EXISTS(SELECT 1 FROM public.action_receipts r WHERE '
 'r.tenant_id=audit_entries.tenant_id AND r.category_id=audit_entries.category_id AND '
 "r.id=audit_entries.receipt_id AND r.operation='release.policy.import' AND "
 "r.subject_type='release_policy_fact' AND r.actor_id=public.scope_actor() AND "
 'r.requester_id=public.scope_requester() AND r.actor_id=audit_entries.actor_id) AND '
 "public.category_access(tenant_id,category_id,true) AND operation='release.policy.import')",
 'CREATE POLICY release_policy_member_insert ON public.outbox_events FOR INSERT TO pdos_next_app '
 'WITH CHECK (EXISTS(SELECT 1 FROM public.action_receipts r WHERE '
 'r.tenant_id=outbox_events.tenant_id AND r.category_id=outbox_events.category_id AND '
 "r.id=outbox_events.receipt_id AND r.operation='release.policy.import' AND "
 "r.subject_type='release_policy_fact' AND r.actor_id=public.scope_actor() AND "
 'r.requester_id=public.scope_requester() AND r.actor_id=outbox_events.actor_id) AND '
 "public.category_access(tenant_id,category_id,true) AND type='release.policy_imported')",
 'CREATE POLICY release_policy_member_insert ON public.request_keys FOR INSERT TO pdos_next_app '
 'WITH CHECK (EXISTS(SELECT 1 FROM public.action_receipts r WHERE '
 'r.tenant_id=request_keys.tenant_id AND r.category_id=request_keys.category_id AND '
 "r.id=request_keys.receipt_id AND r.operation='release.policy.import' AND "
 "r.subject_type='release_policy_fact' AND r.actor_id=public.scope_actor() AND "
 'r.requester_id=public.scope_requester() AND r.actor_id=request_keys.actor_id) AND '
 'public.category_access(tenant_id,category_id,true) AND actor_id=public.scope_actor())',
 'CREATE TRIGGER release_policy_category BEFORE INSERT ON public.release_policy_facts FOR EACH ROW '
 'EXECUTE FUNCTION public.bind_model_category()',
 'CREATE TRIGGER release_policy_category_immutable BEFORE UPDATE ON public.release_policy_facts '
 'FOR EACH ROW EXECUTE FUNCTION public.protect_category_binding()',
 'CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON '
 'public.release_policy_facts FOR EACH ROW EXECUTE FUNCTION public.lifecycle_reference_gate()',
 'CREATE TRIGGER category_lifecycle_clock AFTER INSERT OR UPDATE OR DELETE ON '
 'public.release_policy_facts FOR EACH ROW EXECUTE FUNCTION public.category_lifecycle_clock()',
 'CREATE TRIGGER release_policy_category BEFORE INSERT ON public.release_policy_currents FOR EACH '
 'ROW EXECUTE FUNCTION public.bind_model_category()',
 'CREATE TRIGGER release_policy_category_immutable BEFORE UPDATE ON public.release_policy_currents '
 'FOR EACH ROW EXECUTE FUNCTION public.protect_category_binding()',
 'CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON '
 'public.release_policy_currents FOR EACH ROW EXECUTE FUNCTION public.lifecycle_reference_gate()',
 'CREATE TRIGGER category_lifecycle_clock AFTER INSERT OR UPDATE OR DELETE ON '
 'public.release_policy_currents FOR EACH ROW EXECUTE FUNCTION public.category_lifecycle_clock()',
 'CREATE TRIGGER release_policy_immutable BEFORE UPDATE OR DELETE ON public.release_policy_facts '
 'FOR EACH ROW EXECUTE FUNCTION public.reject_release_policy_mutation()',
 'CREATE TRIGGER release_policy_current_guard BEFORE INSERT OR UPDATE OR DELETE ON '
 'public.release_policy_currents FOR EACH ROW EXECUTE FUNCTION '
 'public.protect_release_policy_current()',
 'CREATE CONSTRAINT TRIGGER release_policy_atom AFTER INSERT ON public.release_policy_facts '
 'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_release_policy_atom()',
 'CREATE CONSTRAINT TRIGGER release_policy_current_atom AFTER INSERT OR UPDATE ON '
 'public.release_policy_currents DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION '
 'public.require_release_policy_current()',
 'CREATE TRIGGER release_policy_receipt_guard BEFORE INSERT OR UPDATE OR DELETE ON '
 'public.action_receipts FOR EACH ROW EXECUTE FUNCTION public.protect_release_policy_receipt()',
 'CREATE CONSTRAINT TRIGGER release_policy_member_atom AFTER INSERT ON public.action_receipts '
 'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION '
 'public.require_release_policy_member()',
 'CREATE CONSTRAINT TRIGGER release_policy_member_atom AFTER INSERT ON public.audit_entries '
 'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION '
 'public.require_release_policy_member()',
 'CREATE TRIGGER release_policy_member_guard BEFORE INSERT OR UPDATE OR DELETE ON '
 'public.audit_entries FOR EACH ROW EXECUTE FUNCTION public.protect_release_policy_member()',
 'CREATE CONSTRAINT TRIGGER release_policy_member_atom AFTER INSERT ON public.outbox_events '
 'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION '
 'public.require_release_policy_member()',
 'CREATE TRIGGER release_policy_member_guard BEFORE INSERT OR UPDATE OR DELETE ON '
 'public.outbox_events FOR EACH ROW EXECUTE FUNCTION public.protect_release_policy_member()',
 'CREATE CONSTRAINT TRIGGER release_policy_member_atom AFTER INSERT ON public.request_keys '
 'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION '
 'public.require_release_policy_member()',
 'CREATE TRIGGER release_policy_member_guard BEFORE INSERT OR UPDATE OR DELETE ON '
 'public.request_keys FOR EACH ROW EXECUTE FUNCTION public.protect_release_policy_member()',
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
 "ARRAY['agent_runs','action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents'] "
 'ELSE ARRAY[\n'
 "  'artifact_versions','claims','definition_revisions','definition_sources','definition_specs',\n"
 '  '
 "'proposals','proposal_items','proposal_item_versions','proposal_submissions','proposal_decisions',\n"
 '  '
 "'category_knowledge_entries','category_knowledge_current','parameter_versions','parameter_current',\n"
 '  '
 "'evidence_links','promotion_proofs','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents'] "
 'END LOOP\n'
 '  FOR payload IN EXECUTE CASE WHEN '
 "name=ANY(ARRAY['audit_entries','outbox_events','request_keys'])\n"
 "   THEN format('SELECT to_jsonb(x) FROM public.%I x JOIN public.action_receipts r ON "
 "r.id=x.receipt_id AND r.tenant_id=x.tenant_id WHERE x.tenant_id=$1 AND r.category_id=$2',name)\n"
 "   ELSE format('SELECT to_jsonb(x) FROM public.%I x WHERE tenant_id=$1 AND category_id=$2 AND "
 "($3 IS NULL OR %I=ANY($3))',name,\n"
 "    CASE name WHEN 'category_knowledge_current' THEN 'lineage_id'\n"
 "     WHEN 'parameter_current' THEN 'parameter_id' ELSE 'id' END)\n"
 '   END USING t,c,identities LOOP\n'
 "   IF (payload->>'receipt_id')::uuid=ANY(controls) OR\n"
 "    (name='action_receipts' AND payload->>'operation' LIKE 'evidence.lifecycle.%') THEN "
 'CONTINUE; END IF;\n'
 '   table_name=name;\n'
 "   node_id=CASE name WHEN 'category_knowledge_current' THEN (payload->>'lineage_id')::uuid\n"
 "    WHEN 'parameter_current' THEN (payload->>'parameter_id')::uuid ELSE (payload->>'id')::uuid "
 'END;\n'
 '   IF identities IS NULL THEN links=public.m3_lifecycle_row_links(t,c,name,payload);\n'
 '   ELSE links=public.m3_lifecycle_source_links(t,c,name,payload); END IF;\n'
 "   -- Preserve predecessor's conservative legacy graph; M3-only nodes use\n"
 '   -- strictly typed/relational links. Root lookup never uses free-text UUIDs.\n'
 '   IF identities IS NULL AND '
 "name<>ALL(ARRAY['native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals']) "
 'THEN\n'
 '    links=links || public.kernel_lifecycle_links(name,payload);\n'
 '   END IF;\n'
 '   RETURN NEXT;\n'
 '  END LOOP;\n'
 ' END LOOP;\n'
 'END;\n'
 '$function$\n',
 'CREATE OR REPLACE FUNCTION public.m3_lifecycle_source_links(t uuid, c uuid, table_name text, '
 'payload jsonb)\n'
 ' RETURNS uuid[]\n'
 ' LANGUAGE plpgsql\n'
 ' STABLE SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 "DECLARE links uuid[]='{}'; extra uuid[]; key text; keys text[]; item jsonb; container jsonb;\n"
 ' target_kind text; referenced_target uuid; referenced_version integer;\n'
 'BEGIN\n'
 " IF table_name='agent_runs' THEN RETURN public.kernel_lifecycle_links(table_name,payload); END "
 'IF;\n'
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
 "  WHEN 'project_open_items' THEN "
 "ARRAY['source_question_id','source_spec_item_id','g0_decision_id']\n"
 "  WHEN 'category_knowledge_current' THEN ARRAY['current_entry_id']\n"
 "  WHEN 'promotion_proofs' THEN ARRAY['knowledge_entry_id','source_proposal_id']\n"
 "  WHEN 'evidence_links' THEN ARRAY['evidence_id']\n"
 "  WHEN 'claim_withdrawals' THEN ARRAY['claim_id']\n"
 "  WHEN 'manufacturing_baseline_publications' THEN "
 "ARRAY['baseline_id','process_id','previous_id']\n"
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
 '  ELSE ARRAY[]::text[] END;\n'
 ' FOREACH key IN ARRAY keys LOOP\n'
 '  IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n'
 ' END LOOP;\n'
 " -- Publication's exact saved read set is a validated Artifact relationship.\n"
 ' -- Do not scan its declaration, body, reason or arbitrary JSON UUID values.\n'
 ' IF table_name IN '
 "('manufacturing_baseline_publications','native_pilot_runs','native_pilot_observations','release_packages','release_decisions','release_policy_facts') "
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
 '  -- FixedObject.ref is a closed, server-resolved version reference, not arbitrary body UUID '
 'text.\n'
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{body,objects}','[]')) "
 'LOOP\n'
 "   container=item->'ref';\n"
 '   IF '
 "container->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','manufacturing_publication','test_run','pilot_run','issue','change','exception','artifact','work_instruction','control_plan','build_lot','line'])\n"
 "    AND container->>'id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); "
 'END IF;\n'
 '  END LOOP;\n'
 ' END IF;\n'
 " IF table_name='release_policy_facts' THEN\n"
 '  -- These are Closed DTO configuration references fixed by the policy owner.\n'
 '  FOREACH key IN ARRAY '
 "ARRAY['definition','engineering_configuration','manufacturing_configuration'] LOOP\n"
 "   container=payload#>ARRAY['material','subject_config',key];\n"
 "   IF container->>'id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); END "
 'IF;\n'
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
 '  links=links || '
 "public.m3_lifecycle_typed_links(t,c,payload->'content'->'representative_refs');\n"
 " ELSIF table_name='category_knowledge_entries' AND payload->>'kind'='competitor' THEN\n"
 "  FOREACH key IN ARRAY ARRAY['metrics','features','prices'] LOOP\n"
 "   FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'content'->key,'[]')) "
 'LOOP\n'
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
 "   IF item->>'item_id' IS NOT NULL THEN links=array_append(links,(item->>'item_id')::uuid); END "
 'IF;\n'
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
 ' RETURN links;\n'
 'END;\n'
 '$function$\n',
 'CREATE OR REPLACE FUNCTION public.m3_lifecycle_row_links(t uuid, c uuid, table_name text, '
 'payload jsonb)\n'
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
 '  ELSE ARRAY[]::text[] END;\n'
 ' FOREACH key IN ARRAY keys LOOP\n'
 '  IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n'
 ' END LOOP;\n'
 ' RETURN links;\n'
 'END;\n'
 '$function$\n')

DOWNGRADE_SQL = ('LOCK TABLE public.release_policy_facts,public.release_policy_currents,public.action_receipts IN '
 'ACCESS EXCLUSIVE MODE',
 'DO $release_policy$ BEGIN\n'
 ' IF EXISTS(SELECT 1 FROM public.release_policy_facts) OR EXISTS(SELECT 1 FROM '
 'public.release_policy_currents)\n'
 "  OR EXISTS(SELECT 1 FROM public.action_receipts WHERE operation='release.policy.import' OR "
 "subject_type='release_policy_fact') THEN\n"
 "  RAISE EXCEPTION 'Release policy business history retained; downgrade refused' USING "
 "ERRCODE='23514'; END IF;\n"
 'END; $release_policy$',
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
 "ARRAY['agent_runs','action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions'] "
 'ELSE ARRAY[\n'
 "  'artifact_versions','claims','definition_revisions','definition_sources','definition_specs',\n"
 '  '
 "'proposals','proposal_items','proposal_item_versions','proposal_submissions','proposal_decisions',\n"
 '  '
 "'category_knowledge_entries','category_knowledge_current','parameter_versions','parameter_current',\n"
 '  '
 "'evidence_links','promotion_proofs','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions'] "
 'END LOOP\n'
 '  FOR payload IN EXECUTE CASE WHEN '
 "name=ANY(ARRAY['audit_entries','outbox_events','request_keys'])\n"
 "   THEN format('SELECT to_jsonb(x) FROM public.%I x JOIN public.action_receipts r ON "
 "r.id=x.receipt_id AND r.tenant_id=x.tenant_id WHERE x.tenant_id=$1 AND r.category_id=$2',name)\n"
 "   ELSE format('SELECT to_jsonb(x) FROM public.%I x WHERE tenant_id=$1 AND category_id=$2 AND "
 "($3 IS NULL OR %I=ANY($3))',name,\n"
 "    CASE name WHEN 'category_knowledge_current' THEN 'lineage_id'\n"
 "     WHEN 'parameter_current' THEN 'parameter_id' ELSE 'id' END)\n"
 '   END USING t,c,identities LOOP\n'
 "   IF (payload->>'receipt_id')::uuid=ANY(controls) OR\n"
 "    (name='action_receipts' AND payload->>'operation' LIKE 'evidence.lifecycle.%') THEN "
 'CONTINUE; END IF;\n'
 '   table_name=name;\n'
 "   node_id=CASE name WHEN 'category_knowledge_current' THEN (payload->>'lineage_id')::uuid\n"
 "    WHEN 'parameter_current' THEN (payload->>'parameter_id')::uuid ELSE (payload->>'id')::uuid "
 'END;\n'
 '   IF identities IS NULL THEN links=public.m3_lifecycle_row_links(t,c,name,payload);\n'
 '   ELSE links=public.m3_lifecycle_source_links(t,c,name,payload); END IF;\n'
 "   -- Preserve predecessor's conservative legacy graph; M3-only nodes use\n"
 '   -- strictly typed/relational links. Root lookup never uses free-text UUIDs.\n'
 '   IF identities IS NULL AND '
 "name<>ALL(ARRAY['native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals']) "
 'THEN\n'
 '    links=links || public.kernel_lifecycle_links(name,payload);\n'
 '   END IF;\n'
 '   RETURN NEXT;\n'
 '  END LOOP;\n'
 ' END LOOP;\n'
 'END;\n'
 '$function$\n',
 'CREATE OR REPLACE FUNCTION public.m3_lifecycle_source_links(t uuid, c uuid, table_name text, '
 'payload jsonb)\n'
 ' RETURNS uuid[]\n'
 ' LANGUAGE plpgsql\n'
 ' STABLE SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 "DECLARE links uuid[]='{}'; extra uuid[]; key text; keys text[]; item jsonb; container jsonb;\n"
 ' target_kind text; referenced_target uuid; referenced_version integer;\n'
 'BEGIN\n'
 " IF table_name='agent_runs' THEN RETURN public.kernel_lifecycle_links(table_name,payload); END "
 'IF;\n'
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
 "  WHEN 'project_open_items' THEN "
 "ARRAY['source_question_id','source_spec_item_id','g0_decision_id']\n"
 "  WHEN 'category_knowledge_current' THEN ARRAY['current_entry_id']\n"
 "  WHEN 'promotion_proofs' THEN ARRAY['knowledge_entry_id','source_proposal_id']\n"
 "  WHEN 'evidence_links' THEN ARRAY['evidence_id']\n"
 "  WHEN 'claim_withdrawals' THEN ARRAY['claim_id']\n"
 "  WHEN 'manufacturing_baseline_publications' THEN "
 "ARRAY['baseline_id','process_id','previous_id']\n"
 "  WHEN 'manufacturing_publication_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'manufacturing_publication_documents' THEN ARRAY['document_id','process_id']\n"
 "  WHEN 'native_pilot_runs' THEN "
 "ARRAY['build_id','lot_id','actual_configuration_id','engineering_configuration_id','process_id','publication_id']\n"
 "  WHEN 'native_pilot_currents' THEN ARRAY['pilot_id','latest_observation_id']\n"
 "  WHEN 'native_pilot_observations' THEN ARRAY['pilot_id','previous_observation_id']\n"
 "  WHEN 'release_packages' THEN ARRAY['previous_id']\n"
 "  WHEN 'release_package_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'release_decisions' THEN ARRAY['package_id']\n"
 '  ELSE ARRAY[]::text[] END;\n'
 ' FOREACH key IN ARRAY keys LOOP\n'
 '  IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n'
 ' END LOOP;\n'
 " -- Publication's exact saved read set is a validated Artifact relationship.\n"
 ' -- Do not scan its declaration, body, reason or arbitrary JSON UUID values.\n'
 ' IF table_name IN '
 "('manufacturing_baseline_publications','native_pilot_runs','native_pilot_observations','release_packages','release_decisions') "
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
 '  -- FixedObject.ref is a closed, server-resolved version reference, not arbitrary body UUID '
 'text.\n'
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{body,objects}','[]')) "
 'LOOP\n'
 "   container=item->'ref';\n"
 '   IF '
 "container->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','manufacturing_publication','test_run','pilot_run','issue','change','exception','artifact','work_instruction','control_plan','build_lot','line'])\n"
 "    AND container->>'id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); "
 'END IF;\n'
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
 '  links=links || '
 "public.m3_lifecycle_typed_links(t,c,payload->'content'->'representative_refs');\n"
 " ELSIF table_name='category_knowledge_entries' AND payload->>'kind'='competitor' THEN\n"
 "  FOREACH key IN ARRAY ARRAY['metrics','features','prices'] LOOP\n"
 "   FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'content'->key,'[]')) "
 'LOOP\n'
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
 "   IF item->>'item_id' IS NOT NULL THEN links=array_append(links,(item->>'item_id')::uuid); END "
 'IF;\n'
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
 ' RETURN links;\n'
 'END;\n'
 '$function$\n',
 'CREATE OR REPLACE FUNCTION public.m3_lifecycle_row_links(t uuid, c uuid, table_name text, '
 'payload jsonb)\n'
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
 '  ELSE ARRAY[]::text[] END;\n'
 ' FOREACH key IN ARRAY keys LOOP\n'
 '  IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n'
 ' END LOOP;\n'
 ' RETURN links;\n'
 'END;\n'
 '$function$\n',
 'DROP POLICY release_policy_receipt_insert ON public.action_receipts',
 'DROP POLICY release_policy_member_insert ON public.audit_entries',
 'DROP POLICY release_policy_member_insert ON public.outbox_events',
 'DROP POLICY release_policy_member_insert ON public.request_keys',
 'DROP TRIGGER release_policy_receipt_guard ON public.action_receipts',
 'DROP TRIGGER release_policy_member_atom ON public.action_receipts',
 'DROP TRIGGER release_policy_member_atom ON public.audit_entries',
 'DROP TRIGGER release_policy_member_atom ON public.outbox_events',
 'DROP TRIGGER release_policy_member_atom ON public.request_keys',
 'DROP TRIGGER release_policy_member_guard ON public.audit_entries',
 'DROP TRIGGER release_policy_member_guard ON public.outbox_events',
 'DROP TRIGGER release_policy_member_guard ON public.request_keys',
 'DROP TABLE public.release_policy_currents',
 'DROP TABLE public.release_policy_facts',
 'DROP FUNCTION public.reject_release_policy_mutation()',
 'DROP FUNCTION public.require_release_policy_atom()',
 'DROP FUNCTION public.require_release_policy_member()',
 'DROP FUNCTION public.protect_release_policy_member()',
 'DROP FUNCTION public.protect_release_policy_receipt()',
 'DROP FUNCTION public.require_release_policy_current()',
 'DROP FUNCTION public.protect_release_policy_current()',
 'DROP FUNCTION public.assert_release_policy_atom(uuid,uuid)',
 'DROP FUNCTION public.assert_release_policy_members(uuid,uuid)')

