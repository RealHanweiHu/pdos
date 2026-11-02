"""Frozen release exception schema over actual ordinary-owner s0_0783."""

PREVIOUS_FUNCTIONS = {'m3_lifecycle_nodes(uuid,uuid,uuid[])': 'CREATE OR REPLACE FUNCTION public.m3_lifecycle_nodes(t uuid, '
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
                                         "ARRAY['agent_runs','action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents'] "
                                         'ELSE ARRAY[\n'
                                         '  '
                                         "'artifact_versions','claims','definition_revisions','definition_sources','definition_specs',\n"
                                         '  '
                                         "'proposals','proposal_items','proposal_item_versions','proposal_submissions','proposal_decisions',\n"
                                         '  '
                                         "'category_knowledge_entries','category_knowledge_current','parameter_versions','parameter_current',\n"
                                         '  '
                                         "'evidence_links','promotion_proofs','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents'] "
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
                                         'links=public.m3_lifecycle_source_links(t,c,name,payload); END '
                                         'IF;\n'
                                         "   -- Preserve predecessor's conservative legacy graph; "
                                         'M3-only nodes use\n'
                                         '   -- strictly typed/relational links. Root lookup never uses '
                                         'free-text UUIDs.\n'
                                         '   IF identities IS NULL AND '
                                         "name<>ALL(ARRAY['native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals']) "
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
                                                    "DECLARE links uuid[]='{}'; extra uuid[]; key text; "
                                                    'keys text[]; item jsonb; container jsonb;\n'
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
                                                    "  WHEN 'proposal_sources' THEN ARRAY['source_id']\n"
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
                                                    "  WHEN 'evidence_links' THEN ARRAY['evidence_id']\n"
                                                    "  WHEN 'claim_withdrawals' THEN ARRAY['claim_id']\n"
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
                                                    "('manufacturing_baseline_publications','native_pilot_runs','native_pilot_observations','release_packages','release_decisions','release_policy_facts','external_handoff_authorizations','external_receipts') "
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
                                                    "links=array_append(links,(item->>'id')::uuid); END "
                                                    'IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{material_snapshot,statistics,issues}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); END "
                                                    'IF;\n'
                                                    '  END LOOP;\n'
                                                    '  '
                                                    "item=payload#>'{material_snapshot,statistics,resource,fact}';\n"
                                                    "  IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); END "
                                                    'IF;\n'
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
                                                    "payload#>'{body,declaration}' ELSE payload->'body' "
                                                    'END;\n'
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
                                                    '  -- These are Closed DTO configuration references '
                                                    'fixed by the policy owner.\n'
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
                                                    " ELSIF table_name='category_knowledge_entries' AND "
                                                    "payload->>'kind'='voice' THEN\n"
                                                    '  links=links || '
                                                    "public.m3_lifecycle_typed_links(t,c,payload->'content'->'representative_refs');\n"
                                                    " ELSIF table_name='category_knowledge_entries' AND "
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
                                                    " ELSIF table_name='category_knowledge_entries' AND "
                                                    "payload->>'id' IS NOT NULL THEN\n"
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
                                                 ' -- They must not turn a source-free item INSERT into '
                                                 'a proposal-history scan.\n'
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
                                                 '  ELSE ARRAY[]::text[] END;\n'
                                                 ' FOREACH key IN ARRAY keys LOOP\n'
                                                 '  IF payload->>key IS NOT NULL THEN '
                                                 'links=array_append(links,(payload->>key)::uuid); END '
                                                 'IF;\n'
                                                 ' END LOOP;\n'
                                                 ' RETURN links;\n'
                                                 'END;\n'
                                                 '$function$\n',
 'protect_object_audience_target()': 'CREATE OR REPLACE FUNCTION '
                                     'public.protect_object_audience_target()\n'
                                     ' RETURNS trigger\n'
                                     ' LANGUAGE plpgsql\n'
                                     " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                     'AS $function$\n'
                                     'DECLARE value jsonb; typ text; own_col text; model_col text;\n'
                                     ' t uuid; c uuid; sid uuid; expected_owner uuid; actual_owner '
                                     'uuid; model uuid;\n'
                                     ' owners jsonb=\'{"action_receipts": "requester_id", '
                                     '"actual_configurations": "owner_id", "artifact_versions": '
                                     '"owner_id", "bom_revisions": "owner_id", '
                                     '"build_authorization_decisions": "owner_id", '
                                     '"build_execution_assessments": "owner_id", "build_lots": '
                                     '"owner_id", "build_operational_facts": "owner_id", '
                                     '"build_readiness": "owner_id", "build_starts": "owner_id", '
                                     '"builds": "owner_id", "capa_current_observations": "owner_id", '
                                     '"capa_current_verification_rules": "owner_id", '
                                     '"capa_named_verification_reviews": "owner_id", '
                                     '"capa_observation_facts": "owner_id", "capa_remediation_links": '
                                     '"owner_id", "capa_verification_evidence": "owner_id", '
                                     '"capa_verification_rule_facts": "owner_id", '
                                     '"change_approval_records": "owner_id", "change_graph_captures": '
                                     '"owner_id", "change_implementation_captures": "owner_id", '
                                     '"change_implementation_records": "owner_id", '
                                     '"change_order_records": "owner_id", "change_request_versions": '
                                     '"owner_id", "claims": "human_owner_id", '
                                     '"controlled_change_coverage_currents": "owner_id", '
                                     '"controlled_change_coverage_facts": "owner_id", '
                                     '"controlled_change_policy_currents": "owner_id", '
                                     '"controlled_change_policy_facts": "owner_id", '
                                     '"controlled_change_selection_currents": "owner_id", '
                                     '"controlled_change_selection_facts": "owner_id", '
                                     '"cost_estimates": "owner_id", "cost_input_snapshots": "owner_id", '
                                     '"cost_source_captures": "owner_id", "definition_revisions": '
                                     '"owner_id", "engineering_configurations": "owner_id", '
                                     '"external_delivery_intents": "owner_id", '
                                     '"external_handoff_authorizations": "owner_id", '
                                     '"external_handoff_currents": "owner_id", "external_receipts": '
                                     '"owner_id", "manufacturing_preparation_currents": "owner_id", '
                                     '"manufacturing_preparation_versions": "owner_id", '
                                     '"measurement_import_captures": "owner_id", "parts": "owner_id", '
                                     '"plan_proposals": "owner_id", "plan_revisions": "owner_id", '
                                     '"process_revisions": "owner_id", "product_variants": "owner_id", '
                                     '"products": "owner_id", "professional_authority_facts": '
                                     '"owner_id", "projects": "owner_id", "proposals": "owner_id", '
                                     '"quality_issue_versions": "owner_id", "quality_policy_facts": '
                                     '"owner_id", "sample_allocations": "owner_id", '
                                     '"sample_readiness_facts": "owner_id", "sample_run_usages": '
                                     '"owner_id", "sample_units": "owner_id", "supply_kit_projections": '
                                     '"owner_id", "supply_snapshots": "owner_id", '
                                     '"supply_source_captures": "owner_id", "test_measurements": '
                                     '"owner_id", "test_resource_facts": "owner_id", '
                                     '"test_resource_reservations": "owner_id", "test_result_actions": '
                                     '"owner_id", "test_result_projections": "owner_id", '
                                     '"uploaded_originals": "owner_id", "variant_revisions": '
                                     '"owner_id", "verification_actual_method_applicabilities": '
                                     '"owner_id", "verification_actual_method_batches": "owner_id", '
                                     '"verification_formal_requests": "owner_id", '
                                     '"verification_handoff_facts": "owner_id", '
                                     '"verification_launch_facts": "owner_id", '
                                     '"verification_method_applicabilities": "owner_id", '
                                     '"verification_preparations": "owner_id", '
                                     '"verification_run_identities": "owner_id", '
                                     '"verification_run_versions": "owner_id", '
                                     '"verification_window_proposals": "owner_id"}\'::jsonb;\n'
                                     'BEGIN\n'
                                     " IF TG_OP='DELETE' THEN value=to_jsonb(OLD); ELSE "
                                     'value=to_jsonb(NEW); END IF;\n'
                                     " IF TG_OP='UPDATE' AND\n"
                                     '   '
                                     'ROW(NEW.tenant_id,NEW.category_id,NEW.object_type,NEW.subject_id,NEW.owner_id)\n'
                                     '   IS DISTINCT FROM '
                                     'ROW(OLD.tenant_id,OLD.category_id,OLD.object_type,OLD.subject_id,OLD.owner_id)\n'
                                     " THEN RAISE EXCEPTION 'audience identity cannot be reassigned' "
                                     "USING ERRCODE='23514'; END IF;\n"
                                     " typ=value->>'object_type'; own_col=owners->>typ;\n"
                                     " t=(value->>'tenant_id')::uuid; c=(value->>'category_id')::uuid;\n"
                                     " sid=(value->>'subject_id')::uuid; "
                                     "expected_owner=(value->>'owner_id')::uuid;\n"
                                     ' IF own_col IS NULL THEN\n'
                                     "  RAISE EXCEPTION 'audience target unavailable' USING "
                                     "ERRCODE='23514';\n"
                                     ' END IF;\n'
                                     " IF typ='variant_revisions' THEN\n"
                                     '  IF '
                                     'm3_lock_variant_revision_audience_target(t,c,sid,expected_owner) '
                                     'IS DISTINCT FROM true THEN\n'
                                     "   RAISE EXCEPTION 'audience target unavailable' USING "
                                     "ERRCODE='23514';\n"
                                     '  END IF;\n'
                                     "  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n"
                                     ' END IF;\n'
                                     " IF typ='product_variants' THEN\n"
                                     '  IF m3_lock_variant_audience_target(t,c,sid,expected_owner) IS '
                                     'DISTINCT FROM true THEN\n'
                                     "   RAISE EXCEPTION 'audience target unavailable' USING "
                                     "ERRCODE='23514';\n"
                                     '  END IF;\n'
                                     "  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n"
                                     ' END IF;\n'
                                     " model_col=CASE WHEN typ='products' THEN 'id' WHEN "
                                     "typ='proposals' THEN 'baseline_product_id' ELSE 'product_id' "
                                     'END;\n'
                                     " EXECUTE format('SELECT %I,%I FROM public.%I WHERE tenant_id=$1 "
                                     "AND category_id=$2 AND id=$3',\n"
                                     '                own_col,model_col,typ) INTO actual_owner,model '
                                     'USING t,c,sid;\n'
                                     ' IF actual_owner IS DISTINCT FROM expected_owner THEN\n'
                                     "  RAISE EXCEPTION 'audience target unavailable' USING "
                                     "ERRCODE='23514';\n"
                                     ' END IF;\n'
                                     ' IF model IS NOT NULL THEN\n'
                                     '  PERFORM 1 FROM products WHERE tenant_id=t AND category_id=c AND '
                                     'id=model FOR UPDATE;\n'
                                     '  IF NOT FOUND THEN\n'
                                     "   RAISE EXCEPTION 'audience model unavailable' USING "
                                     "ERRCODE='23514';\n"
                                     '  END IF;\n'
                                     ' END IF;\n'
                                     " EXECUTE format('SELECT %I FROM public.%I\n"
                                     "  WHERE tenant_id=$1 AND category_id=$2 AND id=$3 FOR UPDATE',\n"
                                     '                own_col,typ) INTO actual_owner USING t,c,sid;\n'
                                     ' IF actual_owner IS DISTINCT FROM expected_owner THEN\n'
                                     "  RAISE EXCEPTION 'audience target unavailable' USING "
                                     "ERRCODE='23514';\n"
                                     ' END IF;\n'
                                     " IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n"
                                     'END $function$\n'}

EXCEPTION_FUNCTIONS = {'m3_lifecycle_nodes(uuid,uuid,uuid[])': 'CREATE OR REPLACE FUNCTION public.m3_lifecycle_nodes(t uuid, '
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
                                         "ARRAY['agent_runs','action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents'] "
                                         'ELSE ARRAY[\n'
                                         '  '
                                         "'artifact_versions','claims','definition_revisions','definition_sources','definition_specs',\n"
                                         '  '
                                         "'proposals','proposal_items','proposal_item_versions','proposal_submissions','proposal_decisions',\n"
                                         '  '
                                         "'category_knowledge_entries','category_knowledge_current','parameter_versions','parameter_current',\n"
                                         '  '
                                         "'evidence_links','promotion_proofs','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents'] "
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
                                         'links=public.m3_lifecycle_source_links(t,c,name,payload); END '
                                         'IF;\n'
                                         "   -- Preserve predecessor's conservative legacy graph; "
                                         'M3-only nodes use\n'
                                         '   -- strictly typed/relational links. Root lookup never uses '
                                         'free-text UUIDs.\n'
                                         '   IF identities IS NULL AND '
                                         "name<>ALL(ARRAY['native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals']) "
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
                                                    "DECLARE links uuid[]='{}'; extra uuid[]; key text; "
                                                    'keys text[]; item jsonb; container jsonb;\n'
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
                                                    "  WHEN 'proposal_sources' THEN ARRAY['source_id']\n"
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
                                                    "  WHEN 'evidence_links' THEN ARRAY['evidence_id']\n"
                                                    "  WHEN 'claim_withdrawals' THEN ARRAY['claim_id']\n"
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
                                                    "links=array_append(links,(item->>'id')::uuid); END "
                                                    'IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{material_snapshot,statistics,issues}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); END "
                                                    'IF;\n'
                                                    '  END LOOP;\n'
                                                    '  '
                                                    "item=payload#>'{material_snapshot,statistics,resource,fact}';\n"
                                                    "  IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); END "
                                                    'IF;\n'
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
                                                    "payload#>'{body,declaration}' ELSE payload->'body' "
                                                    'END;\n'
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
                                                    '  -- These are Closed DTO configuration references '
                                                    'fixed by the policy owner.\n'
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
                                                    " ELSIF table_name='category_knowledge_entries' AND "
                                                    "payload->>'kind'='voice' THEN\n"
                                                    '  links=links || '
                                                    "public.m3_lifecycle_typed_links(t,c,payload->'content'->'representative_refs');\n"
                                                    " ELSIF table_name='category_knowledge_entries' AND "
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
                                                    " ELSIF table_name='category_knowledge_entries' AND "
                                                    "payload->>'id' IS NOT NULL THEN\n"
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
                                                 ' -- They must not turn a source-free item INSERT into '
                                                 'a proposal-history scan.\n'
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
                                                 '  ELSE ARRAY[]::text[] END;\n'
                                                 ' FOREACH key IN ARRAY keys LOOP\n'
                                                 '  IF payload->>key IS NOT NULL THEN '
                                                 'links=array_append(links,(payload->>key)::uuid); END '
                                                 'IF;\n'
                                                 ' END LOOP;\n'
                                                 ' RETURN links;\n'
                                                 'END;\n'
                                                 '$function$\n',
 'protect_object_audience_target()': 'CREATE OR REPLACE FUNCTION '
                                     'public.protect_object_audience_target()\n'
                                     ' RETURNS trigger\n'
                                     ' LANGUAGE plpgsql\n'
                                     " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                     'AS $function$\n'
                                     'DECLARE value jsonb; typ text; own_col text; model_col text;\n'
                                     ' t uuid; c uuid; sid uuid; expected_owner uuid; actual_owner '
                                     'uuid; model uuid;\n'
                                     ' owners jsonb=\'{"action_receipts": "requester_id", '
                                     '"actual_configurations": "owner_id", "artifact_versions": '
                                     '"owner_id", "bom_revisions": "owner_id", '
                                     '"build_authorization_decisions": "owner_id", '
                                     '"build_execution_assessments": "owner_id", "build_lots": '
                                     '"owner_id", "build_operational_facts": "owner_id", '
                                     '"build_readiness": "owner_id", "build_starts": "owner_id", '
                                     '"builds": "owner_id", "capa_current_observations": "owner_id", '
                                     '"capa_current_verification_rules": "owner_id", '
                                     '"capa_named_verification_reviews": "owner_id", '
                                     '"capa_observation_facts": "owner_id", "capa_remediation_links": '
                                     '"owner_id", "capa_verification_evidence": "owner_id", '
                                     '"capa_verification_rule_facts": "owner_id", '
                                     '"change_approval_records": "owner_id", "change_graph_captures": '
                                     '"owner_id", "change_implementation_captures": "owner_id", '
                                     '"change_implementation_records": "owner_id", '
                                     '"change_order_records": "owner_id", "change_request_versions": '
                                     '"owner_id", "claims": "human_owner_id", '
                                     '"controlled_change_coverage_currents": "owner_id", '
                                     '"controlled_change_coverage_facts": "owner_id", '
                                     '"controlled_change_policy_currents": "owner_id", '
                                     '"controlled_change_policy_facts": "owner_id", '
                                     '"controlled_change_selection_currents": "owner_id", '
                                     '"controlled_change_selection_facts": "owner_id", '
                                     '"cost_estimates": "owner_id", "cost_input_snapshots": "owner_id", '
                                     '"cost_source_captures": "owner_id", "definition_revisions": '
                                     '"owner_id", "engineering_configurations": "owner_id", '
                                     '"external_delivery_intents": "owner_id", '
                                     '"external_handoff_authorizations": "owner_id", '
                                     '"external_handoff_currents": "owner_id", "external_receipts": '
                                     '"owner_id", "manufacturing_preparation_currents": "owner_id", '
                                     '"manufacturing_preparation_versions": "owner_id", '
                                     '"measurement_import_captures": "owner_id", "parts": "owner_id", '
                                     '"plan_proposals": "owner_id", "plan_revisions": "owner_id", '
                                     '"process_revisions": "owner_id", "product_variants": "owner_id", '
                                     '"products": "owner_id", "professional_authority_facts": '
                                     '"owner_id", "projects": "owner_id", "proposals": "owner_id", '
                                     '"quality_issue_versions": "owner_id", "quality_policy_facts": '
                                     '"owner_id", "release_exception_currents": "owner_id", '
                                     '"release_exception_decisions": "owner_id", "sample_allocations": '
                                     '"owner_id", "sample_readiness_facts": "owner_id", '
                                     '"sample_run_usages": "owner_id", "sample_units": "owner_id", '
                                     '"supply_kit_projections": "owner_id", "supply_snapshots": '
                                     '"owner_id", "supply_source_captures": "owner_id", '
                                     '"test_measurements": "owner_id", "test_resource_facts": '
                                     '"owner_id", "test_resource_reservations": "owner_id", '
                                     '"test_result_actions": "owner_id", "test_result_projections": '
                                     '"owner_id", "uploaded_originals": "owner_id", '
                                     '"variant_revisions": "owner_id", '
                                     '"verification_actual_method_applicabilities": "owner_id", '
                                     '"verification_actual_method_batches": "owner_id", '
                                     '"verification_formal_requests": "owner_id", '
                                     '"verification_handoff_facts": "owner_id", '
                                     '"verification_launch_facts": "owner_id", '
                                     '"verification_method_applicabilities": "owner_id", '
                                     '"verification_preparations": "owner_id", '
                                     '"verification_run_identities": "owner_id", '
                                     '"verification_run_versions": "owner_id", '
                                     '"verification_window_proposals": "owner_id"}\'::jsonb;\n'
                                     'BEGIN\n'
                                     " IF TG_OP='DELETE' THEN value=to_jsonb(OLD); ELSE "
                                     'value=to_jsonb(NEW); END IF;\n'
                                     " IF TG_OP='UPDATE' AND\n"
                                     '   '
                                     'ROW(NEW.tenant_id,NEW.category_id,NEW.object_type,NEW.subject_id,NEW.owner_id)\n'
                                     '   IS DISTINCT FROM '
                                     'ROW(OLD.tenant_id,OLD.category_id,OLD.object_type,OLD.subject_id,OLD.owner_id)\n'
                                     " THEN RAISE EXCEPTION 'audience identity cannot be reassigned' "
                                     "USING ERRCODE='23514'; END IF;\n"
                                     " typ=value->>'object_type'; own_col=owners->>typ;\n"
                                     " t=(value->>'tenant_id')::uuid; c=(value->>'category_id')::uuid;\n"
                                     " sid=(value->>'subject_id')::uuid; "
                                     "expected_owner=(value->>'owner_id')::uuid;\n"
                                     ' IF own_col IS NULL THEN\n'
                                     "  RAISE EXCEPTION 'audience target unavailable' USING "
                                     "ERRCODE='23514';\n"
                                     ' END IF;\n'
                                     " IF typ='variant_revisions' THEN\n"
                                     '  IF '
                                     'm3_lock_variant_revision_audience_target(t,c,sid,expected_owner) '
                                     'IS DISTINCT FROM true THEN\n'
                                     "   RAISE EXCEPTION 'audience target unavailable' USING "
                                     "ERRCODE='23514';\n"
                                     '  END IF;\n'
                                     "  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n"
                                     ' END IF;\n'
                                     " IF typ='product_variants' THEN\n"
                                     '  IF m3_lock_variant_audience_target(t,c,sid,expected_owner) IS '
                                     'DISTINCT FROM true THEN\n'
                                     "   RAISE EXCEPTION 'audience target unavailable' USING "
                                     "ERRCODE='23514';\n"
                                     '  END IF;\n'
                                     "  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n"
                                     ' END IF;\n'
                                     " model_col=CASE WHEN typ='products' THEN 'id' WHEN "
                                     "typ='proposals' THEN 'baseline_product_id' ELSE 'product_id' "
                                     'END;\n'
                                     " EXECUTE format('SELECT %I,%I FROM public.%I WHERE tenant_id=$1 "
                                     "AND category_id=$2 AND id=$3',\n"
                                     '                own_col,model_col,typ) INTO actual_owner,model '
                                     'USING t,c,sid;\n'
                                     ' IF actual_owner IS DISTINCT FROM expected_owner THEN\n'
                                     "  RAISE EXCEPTION 'audience target unavailable' USING "
                                     "ERRCODE='23514';\n"
                                     ' END IF;\n'
                                     ' IF model IS NOT NULL THEN\n'
                                     '  PERFORM 1 FROM products WHERE tenant_id=t AND category_id=c AND '
                                     'id=model FOR UPDATE;\n'
                                     '  IF NOT FOUND THEN\n'
                                     "   RAISE EXCEPTION 'audience model unavailable' USING "
                                     "ERRCODE='23514';\n"
                                     '  END IF;\n'
                                     ' END IF;\n'
                                     " EXECUTE format('SELECT %I FROM public.%I\n"
                                     "  WHERE tenant_id=$1 AND category_id=$2 AND id=$3 FOR UPDATE',\n"
                                     '                own_col,typ) INTO actual_owner USING t,c,sid;\n'
                                     ' IF actual_owner IS DISTINCT FROM expected_owner THEN\n'
                                     "  RAISE EXCEPTION 'audience target unavailable' USING "
                                     "ERRCODE='23514';\n"
                                     ' END IF;\n'
                                     " IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n"
                                     'END $function$\n'}

PREVIOUS_DEADLINE = ('CHECK (((expires_at IS NOT NULL) OR ((operation)::text = ANY '
 "(ARRAY[('release.engineering.approve'::character varying)::text, "
 "('release.manufacturing.approve'::character varying)::text, "
 "('npi.manufacturing_baseline.publish'::character varying)::text, ('mcp.connector.allow'::character "
 "varying)::text, ('ai.skill.qualify'::character varying)::text, "
 "('build.engineering.authorize'::character varying)::text, ('build.manufacturing.authorize'::character "
 "varying)::text, ('change.order.approve'::character varying)::text, "
 "('change.selection.decide'::character varying)::text, ('proposal.g0.decide'::character "
 "varying)::text, ('quality.capa.verification.review'::character varying)::text, "
 "('quality.issue.root_cause.decide'::character varying)::text, ('test.disposition.decide'::character "
 "varying)::text, ('test.run.review'::character varying)::text])) OR ((expires_at IS NULL) AND "
 "((operation)::text = 'integration.handoff.authorize'::text))))")

EXCEPTION_DEADLINE = ('CHECK (((expires_at IS NOT NULL) OR ((operation)::text = ANY '
 "(ARRAY[('release.engineering.approve'::character varying)::text, "
 "('release.manufacturing.approve'::character varying)::text, "
 "('npi.manufacturing_baseline.publish'::character varying)::text, ('mcp.connector.allow'::character "
 "varying)::text, ('ai.skill.qualify'::character varying)::text, "
 "('build.engineering.authorize'::character varying)::text, ('build.manufacturing.authorize'::character "
 "varying)::text, ('change.order.approve'::character varying)::text, "
 "('change.selection.decide'::character varying)::text, ('proposal.g0.decide'::character "
 "varying)::text, ('quality.capa.verification.review'::character varying)::text, "
 "('quality.issue.root_cause.decide'::character varying)::text, ('test.disposition.decide'::character "
 "varying)::text, ('test.run.review'::character varying)::text])) OR ((expires_at IS NULL) AND "
 "((operation)::text = 'integration.handoff.authorize'::text)) OR ((expires_at IS NULL) AND "
 "((operation)::text = ANY ((ARRAY['release.exception.decide'::character varying, "
 "'release.exception.withdraw'::character varying])::text[])))))")

SCHEMA_SQL = ('\n'
 'CREATE TABLE release_exception_decisions (\n'
 '\tproduct_id UUID NOT NULL, \n'
 '\tproject_id UUID NOT NULL, \n'
 '\trevision INTEGER NOT NULL, \n'
 '\tseries_id UUID NOT NULL, \n'
 '\tprevious_id UUID, \n'
 '\tprevious_revision INTEGER, \n'
 '\towner_id UUID NOT NULL, \n'
 '\twriter_id UUID NOT NULL, \n'
 '\tactor_id UUID NOT NULL, \n'
 '\trequester_id UUID NOT NULL, \n'
 '\tvisibility VARCHAR(16) NOT NULL, \n'
 '\tbasis_package_id UUID NOT NULL, \n'
 '\tbasis_package_revision INTEGER NOT NULL, \n'
 '\tpolicy_fact_id UUID NOT NULL, \n'
 '\tpolicy_fact_revision INTEGER NOT NULL, \n'
 '\tdiscipline VARCHAR(16) NOT NULL, \n'
 '\tpurpose TEXT NOT NULL, \n'
 '\taction VARCHAR(16) NOT NULL, \n'
 '\toperation VARCHAR(80) NOT NULL, \n'
 '\twrite_tier VARCHAR(4) NOT NULL, \n'
 '\texpiry TIMESTAMP WITH TIME ZONE, \n'
 '\tbody JSONB NOT NULL, \n'
 '\tbody_sha256 VARCHAR(64) NOT NULL, \n'
 '\tmaterial_snapshot JSONB NOT NULL, \n'
 '\tinput_snapshot JSONB NOT NULL, \n'
 '\tsource_basis JSONB NOT NULL, \n'
 '\tsources JSONB NOT NULL, \n'
 '\trequired_source_read_set JSONB NOT NULL, \n'
 '\tauthority_snapshot JSONB NOT NULL, \n'
 '\tcommand_id UUID NOT NULL, \n'
 '\treceipt_id UUID NOT NULL, \n'
 '\tintent_digest VARCHAR(64) NOT NULL, \n'
 '\trequest_digest VARCHAR(64) NOT NULL, \n'
 '\tshared_proof_id UUID NOT NULL, \n'
 '\tshared_proof_revision INTEGER NOT NULL, \n'
 '\tproof_consumed_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tproof_expires_at TIMESTAMP WITH TIME ZONE, \n'
 '\ttoken_sha256 VARCHAR(64) NOT NULL, \n'
 '\tmaterial_sha256 VARCHAR(64) NOT NULL, \n'
 '\tread_set_sha256 VARCHAR(64) NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tcategory_id UUID NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(tenant_id, category_id, product_id) REFERENCES products (tenant_id, category_id, id), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id) REFERENCES projects (tenant_id, product_id, id), \n'
 '\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n'
 "\tCHECK (visibility IN ('private','category','audience')), \n"
 "\tCHECK (discipline IN ('engineering','manufacturing') AND length(purpose)>0), \n"
 '\tCHECK (basis_package_revision>0 AND policy_fact_revision>0), \n'
 '\tUNIQUE (tenant_id, id), \n'
 '\tUNIQUE (tenant_id, product_id, id, revision), \n'
 '\tUNIQUE (tenant_id, category_id, product_id, project_id, series_id, owner_id, visibility, id, '
 'revision), \n'
 '\tUNIQUE (tenant_id, category_id, product_id, project_id, series_id, owner_id, visibility, id, '
 'revision, action), \n'
 '\tUNIQUE (tenant_id, previous_id), \n'
 '\tUNIQUE (tenant_id, receipt_id), \n'
 '\tUNIQUE (tenant_id, command_id), \n'
 '\tUNIQUE (tenant_id, shared_proof_id), \n'
 '\tUNIQUE (tenant_id, product_id, actor_id, operation, intent_digest), \n'
 '\tFOREIGN KEY(tenant_id, category_id, product_id, project_id, series_id, owner_id, visibility, '
 'previous_id, previous_revision) REFERENCES release_exception_decisions (tenant_id, category_id, '
 'product_id, project_id, series_id, owner_id, visibility, id, revision), \n'
 '\tFOREIGN KEY(tenant_id, product_id, basis_package_id, basis_package_revision) REFERENCES '
 'release_packages (tenant_id, product_id, id, revision), \n'
 '\tFOREIGN KEY(tenant_id, policy_fact_id) REFERENCES release_policy_facts (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, writer_id) REFERENCES principals (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, actor_id) REFERENCES principals (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, requester_id) REFERENCES principals (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, receipt_id) REFERENCES action_receipts (tenant_id, id) DEFERRABLE INITIALLY '
 'DEFERRED, \n'
 '\tFOREIGN KEY(tenant_id, shared_proof_id) REFERENCES confirmations (tenant_id, id) DEFERRABLE '
 'INITIALLY DEFERRED, \n'
 "\tCHECK (revision=1 AND shared_proof_revision>0 AND write_tier='T2'), \n"
 '\tCHECK (actor_id=requester_id AND writer_id=actor_id), \n'
 "\tCHECK ((action='approved' AND operation='release.exception.decide' AND series_id=id AND previous_id "
 "IS NULL AND previous_revision IS NULL) OR (action='withdrawn' AND "
 "operation='release.exception.withdraw' AND previous_id=series_id AND previous_id<>id AND "
 'previous_revision=1)), \n'
 '\tCHECK (proof_consumed_at<=created_at AND (proof_expires_at IS NULL OR '
 'created_at<proof_expires_at)), \n'
 "\tCHECK (action='withdrawn' OR expiry IS NULL OR created_at<expiry), \n"
 "\tCHECK (jsonb_typeof(body)='object' AND jsonb_typeof(material_snapshot)='object' AND "
 "jsonb_typeof(input_snapshot)='object' AND jsonb_typeof(source_basis)='object' AND "
 "jsonb_typeof(authority_snapshot)='object' AND jsonb_typeof(sources)='array' AND "
 "jsonb_array_length(sources)>0 AND jsonb_typeof(required_source_read_set)='array' AND "
 'jsonb_array_length(required_source_read_set)>0), \n'
 "\tCHECK (body_sha256 ~ '^[a-f0-9]{64}$' AND intent_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ "
 "'^[a-f0-9]{64}$' AND token_sha256 ~ '^[a-f0-9]{64}$' AND material_sha256 ~ '^[a-f0-9]{64}$' AND "
 "read_set_sha256 ~ '^[a-f0-9]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_release_exception_decisions_category_id ON release_exception_decisions (category_id)',
 'CREATE INDEX ix_release_exception_decisions_tenant_id ON release_exception_decisions (tenant_id)',
 '\n'
 'CREATE TABLE release_exception_currents (\n'
 '\tproduct_id UUID NOT NULL, \n'
 '\tproject_id UUID NOT NULL, \n'
 '\tseries_id UUID NOT NULL, \n'
 '\towner_id UUID NOT NULL, \n'
 '\tvisibility VARCHAR(16) NOT NULL, \n'
 '\tbasis_package_id UUID NOT NULL, \n'
 '\tbasis_package_revision INTEGER NOT NULL, \n'
 '\tpolicy_fact_id UUID NOT NULL, \n'
 '\tpolicy_fact_revision INTEGER NOT NULL, \n'
 '\tdiscipline VARCHAR(16) NOT NULL, \n'
 '\tpurpose TEXT NOT NULL, \n'
 '\tdecision_id UUID NOT NULL, \n'
 '\tdecision_revision INTEGER NOT NULL, \n'
 '\taction VARCHAR(16) NOT NULL, \n'
 '\tepoch INTEGER NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tcategory_id UUID NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(tenant_id, category_id, product_id) REFERENCES products (tenant_id, category_id, id), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id) REFERENCES projects (tenant_id, product_id, id), \n'
 '\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n'
 "\tCHECK (visibility IN ('private','category','audience')), \n"
 "\tCHECK (discipline IN ('engineering','manufacturing') AND length(purpose)>0), \n"
 '\tCHECK (basis_package_revision>0 AND policy_fact_revision>0), \n'
 '\tUNIQUE (tenant_id, category_id, product_id, project_id, series_id), \n'
 '\tFOREIGN KEY(tenant_id, category_id, product_id, project_id, series_id, owner_id, visibility, '
 'decision_id, decision_revision, action) REFERENCES release_exception_decisions (tenant_id, '
 'category_id, product_id, project_id, series_id, owner_id, visibility, id, revision, action), \n'
 "\tCHECK (decision_revision=1 AND ((action='approved' AND epoch=1 AND decision_id=series_id) OR "
 "(action='withdrawn' AND epoch=2 AND decision_id<>series_id)))\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_release_exception_currents_category_id ON release_exception_currents (category_id)',
 'CREATE INDEX ix_release_exception_currents_tenant_id ON release_exception_currents (tenant_id)',
 'CREATE FUNCTION public.assert_release_exception_members(t uuid,target uuid) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_exception$\n'
 '\n'
 'DECLARE v public.release_exception_decisions; r public.action_receipts; c public.confirmations; '
 'event_name text;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT v FROM public.release_exception_decisions WHERE tenant_id=t AND id=target;\n'
 ' SELECT * INTO STRICT c FROM public.confirmations WHERE tenant_id=t AND id=v.shared_proof_id;\n'
 ' SELECT * INTO STRICT r FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;\n'
 " event_name=CASE WHEN v.action='approved' THEN 'release.exception_decided' ELSE "
 "'release.exception_withdrawn' END;\n"
 ' IF ROW(c.category_id,c.product_id,c.actor_id,c.subject_type,c.subject_id,c.operation,c.revision)\n'
 '   IS DISTINCT FROM '
 "ROW(v.category_id,v.product_id,v.actor_id,'product'::varchar,v.product_id,v.operation,v.shared_proof_revision)\n"
 '  OR c.consumed IS DISTINCT FROM true OR c.token_hash IS DISTINCT FROM v.token_sha256\n'
 '  OR c.payload_digest IS DISTINCT FROM v.material_sha256 OR c.snapshot IS DISTINCT FROM '
 "v.input_snapshot->'review'\n"
 '  OR c.expires_at IS DISTINCT FROM v.proof_expires_at\n'
 '  OR NOT(c.created_at<=v.proof_consumed_at AND v.proof_consumed_at<=v.created_at\n'
 '   AND (c.expires_at IS NULL OR v.created_at<c.expires_at))\n'
 '  OR '
 'ROW(r.category_id,r.product_id,r.command_id,r.confirmation_id,r.actor_id,r.requester_id,r.operation,\n'
 '   r.subject_type,r.subject_id,r.subject_revision,r.visibility,r.request_digest,r.intent_digest)\n'
 '   IS DISTINCT FROM '
 'ROW(v.category_id,v.product_id,v.command_id,v.shared_proof_id,v.actor_id,v.requester_id,v.operation,\n'
 "    'release_exception'::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)\n"
 '  OR r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL\n'
 "  OR r.result IS DISTINCT FROM jsonb_build_object('id',v.id,'revision',v.revision,'status',v.action)\n"
 '  OR r.created_at<v.created_at OR (c.expires_at IS NOT NULL AND r.created_at>=c.expires_at)\n'
 '  OR (SELECT count(*) FROM public.action_receipts x WHERE x.tenant_id=t AND x.operation=v.operation\n'
 "    AND x.subject_type='release_exception' AND x.subject_id=v.id AND "
 'x.subject_revision=v.revision)<>1\n'
 '  OR (SELECT count(*) FROM public.audit_entries x WHERE x.tenant_id=t AND x.receipt_id=r.id)<>1\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.audit_entries a WHERE a.tenant_id=t AND a.receipt_id=r.id\n'
 '    AND a.category_id=v.category_id AND a.actor_id=v.actor_id AND a.operation=v.operation AND '
 'a.created_at>=v.created_at)\n'
 '  OR (SELECT count(*) FROM public.outbox_events x WHERE x.tenant_id=t AND x.receipt_id=r.id)<>1\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.outbox_events e WHERE e.tenant_id=t AND e.receipt_id=r.id\n'
 '    AND e.category_id=v.category_id AND e.actor_id=v.actor_id AND e.type=event_name\n'
 '    AND e.subject_id=v.id AND e.subject_revision=v.revision AND e.schema_version=1\n'
 '    AND e.correlation_id=coalesce(r.agent_run_id,r.run_id,v.command_id) AND '
 'e.created_at>=v.created_at)\n'
 "  OR v.input_snapshot->>'original_key_sha256' IS NULL\n"
 "  OR v.input_snapshot->>'original_key_sha256' !~ '^[a-f0-9]{64}$'\n"
 "  OR (v.input_snapshot->'command') ? 'idempotency_key'\n"
 "  OR (v.input_snapshot->'command'->'payload') ? 'approval_token'\n"
 "  OR (v.input_snapshot->'semantic') ? 'approval_token'\n"
 '  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND '
 'k.category_id=v.category_id\n'
 '    AND k.receipt_id=r.id AND k.actor_id=v.actor_id AND k.digest=v.request_digest\n'
 "    AND encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.input_snapshot->>'original_key_sha256') "
 'THEN\n'
 "  RAISE EXCEPTION 'Release exception original common group mismatch' USING ERRCODE='23514'; END IF;\n"
 'END;\n'
 '$release_exception$',
 'CREATE FUNCTION public.assert_release_exception_write(t uuid,target uuid) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_exception$\n'
 '\n'
 'DECLARE v public.release_exception_decisions; command jsonb; review jsonb; ref jsonb; basis jsonb; vx '
 'xid; rx xid; cx xid;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT v FROM public.release_exception_decisions WHERE tenant_id=t AND id=target;\n'
 ' SELECT xmin INTO vx FROM public.release_exception_decisions WHERE tenant_id=t AND id=target;\n'
 ' SELECT xmin INTO rx FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;\n'
 ' SELECT xmin INTO cx FROM public.confirmations WHERE tenant_id=t AND id=v.shared_proof_id;\n'
 ' PERFORM public.assert_release_exception_members(t,target);\n'
 " command=v.input_snapshot->'command'; review=v.input_snapshot->'review';\n"
 ' IF v.actor_id IS DISTINCT FROM public.scope_actor() OR v.requester_id IS DISTINCT FROM '
 'public.scope_requester()\n'
 '  OR v.actor_id<>v.requester_id OR v.writer_id<>v.actor_id OR NOT '
 'public.category_access(t,v.category_id,true)\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=t AND p.id=v.actor_id AND '
 "p.kind='human' AND p.active)\n"
 '  OR vx IS DISTINCT FROM rx OR vx IS DISTINCT FROM cx\n'
 '  OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(v.input_snapshot) key)\n'
 "    IS DISTINCT FROM ARRAY['command','original_key_sha256','review','semantic']\n"
 "  OR command->>'operation' IS DISTINCT FROM v.operation OR command->>'command_id' IS DISTINCT FROM "
 'v.command_id::text\n'
 "  OR command->>'category_id' IS DISTINCT FROM v.category_id::text OR command->>'product_id' IS "
 'DISTINCT FROM v.product_id::text\n'
 "  OR command->'payload' IS DISTINCT FROM v.input_snapshot->'semantic'\n"
 "  OR v.body->'declaration' IS DISTINCT FROM v.input_snapshot->'semantic'\n"
 "  OR NOT COALESCE((command->'source_read_set') @> v.required_source_read_set,false)\n"
 "  OR NOT COALESCE(v.required_source_read_set @> (command->'source_read_set'),false)\n"
 "  OR jsonb_array_length(command->'source_read_set')<>jsonb_array_length(v.required_source_read_set)\n"
 "  OR v.shared_proof_revision::text IS DISTINCT FROM command->>'expected_revision'\n"
 "  OR review->>'operation' IS DISTINCT FROM v.operation\n"
 "  OR review->'required_source_read_set' IS DISTINCT FROM v.required_source_read_set\n"
 "  OR review->'read_basis' IS DISTINCT FROM v.source_basis\n"
 "  OR (v.body||jsonb_build_object('prepared_at',null)) IS DISTINCT FROM review->'after'\n"
 "  OR v.body->'scope' IS DISTINCT FROM "
 "jsonb_build_object('tenant_id',t,'product_id',v.product_id,'project_id',v.project_id)\n"
 "  OR v.body->>'category_id' IS DISTINCT FROM v.category_id::text\n"
 "  OR v.body->>'owner_id' IS DISTINCT FROM v.owner_id::text OR v.body->>'visibility' IS DISTINCT FROM "
 'v.visibility\n'
 "  OR v.body->>'operation' IS DISTINCT FROM v.operation OR v.body->>'action' IS DISTINCT FROM "
 'v.action\n'
 "  OR v.body->>'discipline' IS DISTINCT FROM v.discipline OR v.body->>'purpose' IS DISTINCT FROM "
 'v.purpose\n'
 "  OR v.body->'basis_package' IS DISTINCT FROM "
 "jsonb_build_object('id',v.basis_package_id,'revision',v.basis_package_revision)\n"
 "  OR v.body->'policy_fact' IS DISTINCT FROM "
 "jsonb_build_object('id',v.policy_fact_id,'revision',v.policy_fact_revision)\n"
 "  OR (v.body->>'expiry')::timestamptz IS DISTINCT FROM v.expiry\n"
 "  OR v.body->'sources' IS DISTINCT FROM v.sources OR v.body->'required_source_read_set' IS DISTINCT "
 'FROM v.required_source_read_set\n'
 "  OR v.body->'signers' IS DISTINCT FROM jsonb_build_array(v.actor_id)\n"
 "  OR v.body->>'state' IS DISTINCT FROM 'READY' OR v.body->'unknown' IS DISTINCT FROM '[]'::jsonb\n"
 "  OR v.body->'blocked' IS DISTINCT FROM '[]'::jsonb\n"
 '  OR NOT EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id=t AND p.category_id=v.category_id\n'
 "    AND p.id=v.product_id AND p.revision::text=command->>'expected_revision')\n"
 '  OR NOT EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=t AND p.category_id=v.category_id\n'
 '    AND p.product_id=v.product_id AND p.id=v.project_id)\n'
 '  OR NOT public.direct_source_set_visible(t,v.category_id,v.product_id,v.required_source_read_set)\n'
 "  OR (SELECT count(DISTINCT x->>'artifact_id') FROM jsonb_array_elements(v.required_source_read_set) "
 'x)\n'
 '    <>jsonb_array_length(v.required_source_read_set)\n'
 '  OR EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id '
 'AND x.xmin IS DISTINCT FROM vx)\n'
 '  OR EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id '
 'AND x.xmin IS DISTINCT FROM vx)\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND '
 'k.receipt_id=v.receipt_id\n'
 '    AND k.actor_id=v.actor_id AND k.digest=v.request_digest AND k.xmin=vx\n'
 "    AND encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.input_snapshot->>'original_key_sha256') "
 'THEN\n'
 "  RAISE EXCEPTION 'Release exception requires actual named scope and one common transaction' USING "
 "ERRCODE='23514'; END IF;\n"
 " IF jsonb_typeof(v.source_basis->'artifact_sources') IS DISTINCT FROM 'object'\n"
 '  OR (SELECT count(*) FROM '
 "jsonb_object_keys(v.source_basis->'artifact_sources'))<>jsonb_array_length(v.required_source_read_set) "
 'THEN\n'
 "  RAISE EXCEPTION 'Release exception complete direct source basis required' USING ERRCODE='23514'; "
 'END IF;\n'
 ' FOR ref IN SELECT value FROM jsonb_array_elements(v.required_source_read_set) LOOP\n'
 "  basis=v.source_basis->'artifact_sources'->(ref->>'artifact_id');\n"
 "  IF basis IS NULL OR jsonb_typeof(ref->'expected_revision') IS DISTINCT FROM 'number'\n"
 '   OR NOT EXISTS(SELECT 1 FROM public.artifact_versions a WHERE a.tenant_id=t AND '
 'a.category_id=v.category_id\n'
 "    AND a.id::text=ref->>'artifact_id' AND a.revision::text=ref->>'expected_revision' AND "
 "a.status='active'\n"
 "    AND a.revision::text=basis->>'revision' AND a.content_hash=basis->>'sha256'\n"
 "    AND a.owner_id::text=basis->>'owner_id' AND a.visibility=basis->>'visibility'\n"
 "    AND (v.visibility='private' OR a.visibility<>'private')\n"
 '    AND (a.original_id IS NULL OR EXISTS(SELECT 1 FROM public.uploaded_originals o\n'
 '     JOIN public.original_security sec ON sec.tenant_id=o.tenant_id AND sec.original_id=o.id\n'
 '     WHERE o.tenant_id=t AND o.category_id=v.category_id AND o.id=a.original_id AND '
 "o.status='parsed'\n"
 "      AND o.id::text=basis->>'original_id' AND o.revision::text=basis->>'original_revision'\n"
 "      AND o.content_hash=basis->>'original_sha256' AND o.owner_id::text=basis->>'original_owner_id'\n"
 "      AND o.visibility=basis->>'original_visibility' AND sec.epoch::text=basis->>'security_epoch'\n"
 "      AND sec.source_state='active' AND sec.disposition='active' AND (v.visibility='private' OR "
 "o.visibility<>'private')))) THEN\n"
 "   RAISE EXCEPTION 'Release exception direct source version security or audience changed' USING "
 "ERRCODE='23514'; END IF;\n"
 ' END LOOP;\n'
 " IF EXISTS(SELECT 1 FROM jsonb_array_elements(v.sources) src WHERE src->>'kind'='artifact' AND NOT "
 'EXISTS(\n'
 '   SELECT 1 FROM jsonb_array_elements(v.required_source_read_set) rd\n'
 "   WHERE rd->>'artifact_id'=src->>'id' AND rd->'expected_revision'=src->'revision')) THEN\n"
 "  RAISE EXCEPTION 'Release exception source omitted from direct read set' USING ERRCODE='23514'; END "
 'IF;\n'
 'END;\n'
 '$release_exception$',
 'CREATE FUNCTION public.assert_release_exception_authority(t uuid,target uuid) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_exception$\n'
 '\n'
 'DECLARE v public.release_exception_decisions; auth jsonb; ref jsonb;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT v FROM public.release_exception_decisions WHERE tenant_id=t AND id=target;\n'
 ' auth=v.authority_snapshot;\n'
 " IF v.input_snapshot->'review'->'authority' IS DISTINCT FROM auth\n"
 "  OR auth->'scope' IS DISTINCT FROM v.body->'scope' OR auth->>'subject_id' IS DISTINCT FROM "
 'v.actor_id::text\n'
 "  OR auth->>'operation' IS DISTINCT FROM v.operation OR auth->>'purpose' IS DISTINCT FROM v.purpose\n"
 "  OR auth->'authorized' IS DISTINCT FROM 'true'::jsonb OR auth->'qualified' IS DISTINCT FROM "
 "'true'::jsonb\n"
 '  OR NOT public.capture_authority_time_current(auth,v.created_at)\n'
 "  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(auth->'fact_refs')) THEN\n"
 "  RAISE EXCEPTION 'Release exception requires actual current named professional authority' USING "
 "ERRCODE='23514'; END IF;\n"
 " FOR ref IN SELECT value FROM jsonb_array_elements(auth->'fact_refs') LOOP\n"
 '  IF NOT EXISTS(SELECT 1 FROM public.professional_authority_facts f JOIN '
 'public.professional_authority_current cur\n'
 '   ON cur.tenant_id=f.tenant_id AND cur.category_id=f.category_id AND cur.product_id=f.product_id AND '
 'cur.project_id=f.project_id\n'
 '    AND cur.subject_id=f.subject_id AND cur.kind=f.kind AND cur.series_id=f.series_id AND '
 'cur.fact_id=f.id AND cur.fact_revision=f.revision\n'
 '   WHERE f.tenant_id=t AND f.category_id=v.category_id AND f.product_id=v.product_id AND '
 'f.project_id=v.project_id\n'
 "    AND f.subject_id=v.actor_id AND f.id::text=ref->>'id' AND f.revision::text=ref->>'revision'\n"
 "    AND cur.epoch::text=ref->>'epoch' AND f.fact_sha256=ref->>'fact_sha256' AND "
 "f.state=ref->>'state'\n"
 "    AND f.role=ref->>'role' AND f.kind=ref->>'kind' AND f.series_id::text=ref->>'series_id'\n"
 "    AND f.issuer_key=ref->>'issuer_key' AND f.issuer_version=ref->>'issuer_version' AND "
 "f.nature=ref->>'nature'\n"
 "    AND f.operations=ref->'operations' AND f.purposes=ref->'purposes'\n"
 "    AND f.valid_from IS NOT DISTINCT FROM (ref->>'valid_from')::timestamptz\n"
 "    AND f.valid_until IS NOT DISTINCT FROM (ref->>'valid_until')::timestamptz) THEN\n"
 "   RAISE EXCEPTION 'Release exception professional fact or Current changed' USING ERRCODE='23514'; "
 'END IF;\n'
 ' END LOOP;\n'
 " IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(auth->'roles') AS roles(role_name)\n"
 "   WHERE role_name IN ('engineering','manufacturing','quality') AND NOT EXISTS(\n"
 "    SELECT kind FROM unnest(ARRAY['duty','qualification']) kind WHERE NOT EXISTS(\n"
 "     SELECT 1 FROM jsonb_array_elements(auth->'fact_refs') f WHERE f->>'kind'=kind AND "
 "f->>'role'=role_name\n"
 "      AND f->>'state'='active' AND (f->'operations') @> jsonb_build_array(v.operation)\n"
 "      AND (f->'purposes') @> jsonb_build_array(v.purpose)\n"
 "      AND (f->>'valid_from')::timestamptz<=v.created_at AND "
 "v.created_at<(f->>'valid_until')::timestamptz))) THEN\n"
 "  RAISE EXCEPTION 'Release exception needs applicable duty and qualification' USING ERRCODE='23514'; "
 'END IF;\n'
 'END;\n'
 '$release_exception$',
 'CREATE FUNCTION public.release_exception_scope_covers(bound jsonb,chosen jsonb) RETURNS boolean\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_exception$\n'
 '\n'
 'DECLARE key text; b jsonb; c jsonb;\n'
 'BEGIN\n'
 " IF jsonb_typeof(bound) IS DISTINCT FROM 'object' OR jsonb_typeof(chosen) IS DISTINCT FROM 'object' "
 'THEN RETURN false; END IF;\n'
 " FOREACH key IN ARRAY ARRAY['lots','lines','regions'] LOOP\n"
 '  b=bound->key; c=chosen->key;\n'
 "  IF c IS NULL OR c='null'::jsonb THEN\n"
 "   IF b IS NOT NULL AND b<>'null'::jsonb THEN RETURN false; END IF;\n"
 "  ELSIF jsonb_typeof(c) IS DISTINCT FROM 'array' THEN RETURN false;\n"
 "  ELSIF c='[]'::jsonb THEN\n"
 "   IF b IS DISTINCT FROM '[]'::jsonb THEN RETURN false; END IF;\n"
 "  ELSIF jsonb_typeof(b) IS DISTINCT FROM 'array' OR NOT(b @> c) THEN RETURN false;\n"
 '  END IF;\n'
 ' END LOOP;\n'
 " FOREACH key IN ARRAY ARRAY['site','unit'] LOOP\n"
 '  IF bound->key IS DISTINCT FROM chosen->key THEN RETURN false; END IF;\n'
 ' END LOOP;\n'
 " IF chosen->>'quantity' IS NULL THEN RETURN bound->>'quantity' IS NULL; END IF;\n"
 " IF bound->>'quantity' IS NULL THEN RETURN false; END IF;\n"
 " RETURN (chosen->>'quantity')::numeric>0 AND "
 "(chosen->>'quantity')::numeric<=(bound->>'quantity')::numeric;\n"
 'END;\n'
 '$release_exception$',
 'CREATE FUNCTION public.assert_release_exception_decision(t uuid,target uuid) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_exception$\n'
 '\n'
 'DECLARE v public.release_exception_decisions; p public.release_packages; f '
 'public.release_policy_facts;\n'
 ' prior public.release_exception_decisions; cur public.release_exception_currents; key text; '
 'check_value jsonb; policy_rule jsonb; vx xid; cx xid;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT v FROM public.release_exception_decisions WHERE tenant_id=t AND id=target;\n'
 ' SELECT xmin INTO vx FROM public.release_exception_decisions WHERE tenant_id=t AND id=target;\n'
 ' SELECT * INTO STRICT p FROM public.release_packages WHERE tenant_id=t AND id=v.basis_package_id;\n'
 ' SELECT * INTO STRICT f FROM public.release_policy_facts WHERE tenant_id=t AND id=v.policy_fact_id;\n'
 ' SELECT * INTO STRICT cur FROM public.release_exception_currents WHERE tenant_id=t AND '
 'series_id=v.series_id;\n'
 ' SELECT xmin INTO cx FROM public.release_exception_currents WHERE tenant_id=t AND id=cur.id;\n'
 ' PERFORM public.assert_release_exception_write(t,target);\n'
 ' PERFORM public.assert_release_exception_authority(t,target);\n'
 ' IF vx IS DISTINCT FROM cx\n'
 '  OR ROW(p.category_id,p.product_id,p.project_id,p.revision,p.owner_id,p.visibility)\n'
 '   IS DISTINCT FROM '
 'ROW(v.category_id,v.product_id,v.project_id,v.basis_package_revision,v.owner_id,v.visibility)\n'
 '  OR ROW(f.category_id,f.product_id,f.project_id,f.revision,f.purpose)\n'
 '   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.policy_fact_revision,v.purpose)\n'
 "  OR v.body->>'policy_version' IS DISTINCT FROM f.policy_version\n"
 "  OR v.body->'subject_config' IS DISTINCT FROM p.body->'declaration'->'subject_config'\n"
 '  OR v.purpose IS DISTINCT FROM p.purpose\n'
 '  OR ROW(cur.category_id,cur.product_id,cur.project_id,cur.series_id,cur.owner_id,cur.visibility,\n'
 '    '
 'cur.basis_package_id,cur.basis_package_revision,cur.policy_fact_id,cur.policy_fact_revision,cur.discipline,cur.purpose,\n'
 '    cur.decision_id,cur.decision_revision,cur.action,cur.epoch)\n'
 '   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.series_id,v.owner_id,v.visibility,\n'
 '    '
 'v.basis_package_id,v.basis_package_revision,v.policy_fact_id,v.policy_fact_revision,v.discipline,v.purpose,\n'
 "    v.id,v.revision,v.action,(CASE WHEN v.action='approved' THEN 1 ELSE 2 END)) THEN\n"
 "  RAISE EXCEPTION 'Release exception fixed package policy or Current binding mismatch' USING "
 "ERRCODE='23514'; END IF;\n"
 " IF v.action='approved' THEN\n"
 "  IF v.body->'previous' IS DISTINCT FROM 'null'::jsonb\n"
 '   OR NOT EXISTS(SELECT 1 FROM public.release_package_currents c WHERE c.tenant_id=t AND '
 'c.category_id=v.category_id\n'
 '    AND c.product_id=v.product_id AND c.project_id=v.project_id AND c.series_id=p.series_id AND '
 'c.version_id=p.id AND c.revision=p.revision)\n'
 '   OR NOT EXISTS(SELECT 1 FROM public.release_policy_currents c WHERE c.tenant_id=t AND '
 'c.category_id=v.category_id\n'
 '    AND c.product_id=v.product_id AND c.project_id=v.project_id AND '
 'c.purpose_sha256=f.purpose_sha256\n'
 '    AND c.fact_id=f.id AND c.revision=f.revision AND c.epoch=f.epoch)\n'
 "   OR f.status<>'active' OR (f.valid_from IS NOT NULL AND v.created_at<f.valid_from)\n"
 '   OR (f.valid_until IS NOT NULL AND v.created_at>=f.valid_until)\n'
 '   OR (v.expiry IS NOT NULL AND v.created_at>=v.expiry)\n'
 "   OR f.material->'scope' IS DISTINCT FROM v.body->'scope'\n"
 "   OR f.material->'subject_config' IS DISTINCT FROM v.body->'subject_config'\n"
 "   OR p.body->'policy'->>'version' IS DISTINCT FROM f.policy_version\n"
 '   OR NOT '
 "public.release_exception_scope_covers(p.body->'declaration'->'release_scope',v.body->'release_scope')\n"
 "   OR NOT public.release_exception_scope_covers(f.material->'release_scope',v.body->'release_scope')\n"
 "   OR v.body->'declaration'->'basis_package' IS DISTINCT FROM v.body->'basis_package'\n"
 "   OR v.body->'declaration'->>'discipline' IS DISTINCT FROM v.discipline\n"
 "   OR v.body->'declaration'->>'purpose' IS DISTINCT FROM v.purpose\n"
 '   OR EXISTS(SELECT 1 FROM '
 "unnest(ARRAY['release_scope','check_keys','limits','risk_controls','expiry','reason']) name\n"
 "    WHERE v.body->'declaration'->name IS DISTINCT FROM v.body->name)\n"
 "   OR jsonb_typeof(v.body->'check_keys') IS DISTINCT FROM 'array' OR "
 "jsonb_array_length(v.body->'check_keys')=0\n"
 "   OR jsonb_array_length(v.body->'check_keys')<>(SELECT count(DISTINCT value) FROM "
 "jsonb_array_elements_text(v.body->'check_keys'))\n"
 "   OR jsonb_array_length(v.body->'selected_checks')<>jsonb_array_length(v.body->'check_keys') THEN\n"
 "   RAISE EXCEPTION 'New release exception requires actual current applicable package and policy' "
 "USING ERRCODE='23514'; END IF;\n"
 "  FOR key IN SELECT value FROM jsonb_array_elements_text(v.body->'check_keys') LOOP\n"
 "   SELECT value INTO STRICT check_value FROM jsonb_array_elements(p.body->'checks') WHERE "
 "value->>'key'=key;\n"
 "   SELECT value INTO STRICT policy_rule FROM jsonb_array_elements(f.material->'rules') WHERE "
 "value->>'id'=key;\n"
 "   IF NOT(v.body->'selected_checks' @> jsonb_build_array(check_value))\n"
 "    OR check_value->'applicable' IS DISTINCT FROM 'true'::jsonb\n"
 "    OR check_value->'non_waivable' IS DISTINCT FROM 'false'::jsonb\n"
 "    OR check_value->>'discipline' NOT IN(v.discipline,'both') OR policy_rule->'waivable' IS DISTINCT "
 "FROM 'true'::jsonb\n"
 "    OR policy_rule->>'discipline' NOT IN(v.discipline,'both')\n"
 "    OR NOT(policy_rule->'allowed_purpose' @> jsonb_build_array(v.purpose))\n"
 "    OR NOT public.release_exception_scope_covers(policy_rule->'scope',v.body->'release_scope')\n"
 "    OR (check_value->'release_scope'<>'null'::jsonb AND NOT "
 "public.release_exception_scope_covers(check_value->'release_scope',v.body->'release_scope')) THEN\n"
 "    RAISE EXCEPTION 'Release exception cannot alter a check or bypass a non-waivable rule' USING "
 "ERRCODE='23514'; END IF;\n"
 '  END LOOP;\n'
 ' ELSE\n'
 '  SELECT * INTO STRICT prior FROM public.release_exception_decisions WHERE tenant_id=t AND '
 'id=v.previous_id;\n'
 '  PERFORM public.assert_release_exception_members(t,prior.id);\n'
 "  IF prior.action<>'approved' OR prior.revision<>v.previous_revision\n"
 "   OR v.body->'previous' IS DISTINCT FROM "
 "jsonb_build_object('id',prior.id,'revision',prior.revision)\n"
 "   OR v.body->'declaration'->'exception' IS DISTINCT FROM v.body->'previous'\n"
 '   OR v.expiry IS DISTINCT FROM prior.expiry\n'
 '   OR '
 "(v.body-ARRAY['operation','action','declaration','previous','sources','required_source_read_set','signers','prepared_at','reason','state','unknown','blocked'])\n"
 '    IS DISTINCT FROM '
 "(prior.body-ARRAY['operation','action','declaration','previous','sources','required_source_read_set','signers','prepared_at','reason','state','unknown','blocked']) "
 'THEN\n'
 "   RAISE EXCEPTION 'Withdrawal retains the original approved limits and binding' USING "
 "ERRCODE='23514'; END IF;\n"
 ' END IF;\n'
 'END;\n'
 '$release_exception$',
 'CREATE FUNCTION public.protect_release_exception_current() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_exception$\n'
 '\n'
 'BEGIN\n'
 " IF TG_OP='INSERT' THEN\n"
 "  IF NEW.action='approved' AND NEW.epoch=1 AND NEW.decision_id=NEW.series_id AND "
 'NEW.decision_revision=1 THEN RETURN NEW; END IF;\n'
 " ELSIF TG_OP='UPDATE' THEN\n"
 "  IF (to_jsonb(NEW)-ARRAY['decision_id','decision_revision','action','epoch'])\n"
 "   IS NOT DISTINCT FROM (to_jsonb(OLD)-ARRAY['decision_id','decision_revision','action','epoch'])\n"
 "   AND OLD.action='approved' AND OLD.epoch=1 AND NEW.action='withdrawn' AND NEW.epoch=OLD.epoch+1\n"
 '   AND EXISTS(SELECT 1 FROM public.release_exception_decisions v WHERE v.tenant_id=NEW.tenant_id AND '
 'v.id=NEW.decision_id\n'
 "    AND v.revision=NEW.decision_revision AND v.action='withdrawn' AND v.series_id=NEW.series_id\n"
 '    AND v.previous_id=OLD.decision_id AND v.previous_revision=OLD.decision_revision) THEN RETURN NEW; '
 'END IF;\n'
 ' END IF;\n'
 " RAISE EXCEPTION 'Release exception Current permits one approved to withdrawn CAS' USING "
 "ERRCODE='23514';\n"
 'END;\n'
 '$release_exception$',
 'CREATE FUNCTION public.require_release_exception_current() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_exception$\n'
 '\n'
 'DECLARE cur public.release_exception_currents; v public.release_exception_decisions; cx xid; vx xid;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT cur FROM public.release_exception_currents WHERE tenant_id=NEW.tenant_id AND '
 'id=NEW.id;\n'
 ' SELECT xmin INTO cx FROM public.release_exception_currents WHERE tenant_id=NEW.tenant_id AND '
 'id=NEW.id;\n'
 ' SELECT * INTO STRICT v FROM public.release_exception_decisions WHERE tenant_id=NEW.tenant_id AND '
 'id=cur.decision_id;\n'
 ' SELECT xmin INTO vx FROM public.release_exception_decisions WHERE tenant_id=NEW.tenant_id AND '
 'id=cur.decision_id;\n'
 ' IF cx IS DISTINCT FROM vx\n'
 '  OR ROW(cur.category_id,cur.product_id,cur.project_id,cur.series_id,cur.owner_id,cur.visibility,\n'
 '    '
 'cur.basis_package_id,cur.basis_package_revision,cur.policy_fact_id,cur.policy_fact_revision,cur.discipline,cur.purpose,\n'
 '    cur.decision_revision,cur.action,cur.epoch)\n'
 '   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.series_id,v.owner_id,v.visibility,\n'
 '    '
 'v.basis_package_id,v.basis_package_revision,v.policy_fact_id,v.policy_fact_revision,v.discipline,v.purpose,\n'
 "    v.revision,v.action,(CASE WHEN v.action='approved' THEN 1 ELSE 2 END)) THEN\n"
 "  RAISE EXCEPTION 'Release exception Current requires its new immutable decision' USING "
 "ERRCODE='23514'; END IF;\n"
 ' RETURN NULL;\n'
 'END;\n'
 '$release_exception$',
 'CREATE FUNCTION public.protect_release_exception_proof() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_exception$\n'
 '\n'
 'DECLARE old_scoped boolean=false; new_scoped boolean=false;\n'
 'BEGIN\n'
 " IF TG_OP<>'INSERT' THEN old_scoped=OLD.operation IN "
 "('release.exception.decide','release.exception.withdraw'); END IF;\n"
 " IF TG_OP<>'DELETE' THEN new_scoped=NEW.operation IN "
 "('release.exception.decide','release.exception.withdraw'); END IF;\n"
 ' IF old_scoped OR new_scoped THEN\n'
 "  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Release exception proof history retained' USING "
 "ERRCODE='23514';\n"
 "  ELSIF TG_OP='INSERT' THEN\n"
 "   IF NEW.consumed IS DISTINCT FROM false THEN RAISE EXCEPTION 'Release exception proof starts "
 "unconsumed' USING ERRCODE='23514'; END IF;\n"
 '  ELSIF NOT(old_scoped AND new_scoped) OR OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS '
 'DISTINCT FROM true\n'
 "   OR (to_jsonb(NEW)-'consumed') IS DISTINCT FROM (to_jsonb(OLD)-'consumed') THEN\n"
 "   RAISE EXCEPTION 'Release exception proof permits only original false to true' USING "
 "ERRCODE='23514'; END IF;\n"
 ' END IF;\n'
 " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
 'END;\n'
 '$release_exception$',
 'CREATE FUNCTION public.require_release_exception_transition() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_exception$\n'
 '\n'
 'BEGIN\n'
 " IF NEW.operation IN ('release.exception.decide','release.exception.withdraw') THEN\n"
 '  IF OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true\n'
 '   OR (SELECT count(*) FROM public.release_exception_decisions d WHERE d.tenant_id=NEW.tenant_id\n'
 '    AND d.shared_proof_id=NEW.id AND d.operation=NEW.operation)<>1 THEN\n'
 "   RAISE EXCEPTION 'Consumed exception T2 requires one actual immutable decision' USING "
 "ERRCODE='23514'; END IF;\n"
 ' END IF;\n'
 ' RETURN NULL;\n'
 'END;\n'
 '$release_exception$',
 'CREATE FUNCTION public.protect_release_exception_receipt() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_exception$\n'
 '\n'
 'DECLARE scoped boolean=false;\n'
 'BEGIN\n'
 " IF TG_OP<>'INSERT' THEN scoped=OLD.operation IN "
 "('release.exception.decide','release.exception.withdraw') OR OLD.subject_type='release_exception'; "
 'END IF;\n'
 " IF TG_OP<>'DELETE' THEN scoped=scoped OR NEW.operation IN "
 "('release.exception.decide','release.exception.withdraw') OR NEW.subject_type='release_exception'; "
 'END IF;\n'
 " IF scoped AND TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Release exception common receipt is immutable' "
 "USING ERRCODE='23514'; END IF;\n"
 " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
 'END;\n'
 '$release_exception$',
 'CREATE FUNCTION public.protect_release_exception_member() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_exception$\n'
 '\n'
 'DECLARE scoped boolean=false; old_scoped boolean=false;\n'
 'BEGIN\n'
 " IF TG_OP<>'DELETE' THEN\n"
 '  SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=NEW.tenant_id AND '
 'r.id=NEW.receipt_id\n'
 "   AND (r.operation IN ('release.exception.decide','release.exception.withdraw') OR "
 "r.subject_type='release_exception')) INTO scoped;\n"
 ' END IF;\n'
 " IF TG_OP<>'INSERT' THEN\n"
 '  SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=OLD.tenant_id AND '
 'r.id=OLD.receipt_id\n'
 "   AND (r.operation IN ('release.exception.decide','release.exception.withdraw') OR "
 "r.subject_type='release_exception')) INTO old_scoped;\n"
 ' END IF;\n'
 " IF TG_OP<>'INSERT' AND (scoped OR old_scoped) THEN\n"
 "  IF TG_OP='UPDATE' AND TG_TABLE_NAME='outbox_events'\n"
 "   AND (to_jsonb(NEW)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) IS NOT "
 'DISTINCT FROM\n'
 "    (to_jsonb(OLD)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) THEN "
 'RETURN NEW; END IF;\n'
 "  RAISE EXCEPTION 'Release exception original audit event or key is immutable' USING ERRCODE='23514'; "
 'END IF;\n'
 " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
 'END;\n'
 '$release_exception$',
 'CREATE FUNCTION public.require_release_exception_member() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_exception$\n'
 '\n'
 'DECLARE r public.action_receipts;\n'
 'BEGIN\n'
 " IF TG_TABLE_NAME='action_receipts' THEN r=NEW;\n"
 ' ELSE SELECT * INTO r FROM public.action_receipts WHERE tenant_id=NEW.tenant_id AND '
 'id=NEW.receipt_id; END IF;\n'
 " IF r.operation IN ('release.exception.decide','release.exception.withdraw') OR "
 "r.subject_type='release_exception' THEN\n"
 "  IF r.subject_type IS DISTINCT FROM 'release_exception' THEN\n"
 "   RAISE EXCEPTION 'Release exception common subject mismatch' USING ERRCODE='23514'; END IF;\n"
 '  PERFORM public.assert_release_exception_members(r.tenant_id,r.subject_id);\n'
 ' END IF;\n'
 ' RETURN NULL;\n'
 'END;\n'
 '$release_exception$',
 'CREATE FUNCTION public.require_release_exception_decision() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_exception$\n'
 'BEGIN PERFORM public.assert_release_exception_decision(NEW.tenant_id,NEW.id); RETURN NULL; END;\n'
 '$release_exception$',
 'CREATE FUNCTION public.reject_release_exception_mutation() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $release_exception$\n'
 "BEGIN RAISE EXCEPTION 'Release exception decisions are immutable' USING ERRCODE='23514'; END;\n"
 '$release_exception$',
 'REVOKE ALL ON FUNCTION public.assert_release_exception_members(uuid,uuid) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.assert_release_exception_write(uuid,uuid) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.assert_release_exception_authority(uuid,uuid) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.release_exception_scope_covers(jsonb,jsonb) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.assert_release_exception_decision(uuid,uuid) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.protect_release_exception_current() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.require_release_exception_current() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.protect_release_exception_proof() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.require_release_exception_transition() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.protect_release_exception_receipt() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.protect_release_exception_member() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.require_release_exception_member() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.require_release_exception_decision() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.reject_release_exception_mutation() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'ALTER TABLE public."release_exception_decisions" ENABLE ROW LEVEL SECURITY',
 'ALTER TABLE public."release_exception_decisions" FORCE ROW LEVEL SECURITY',
 'CREATE POLICY owner_internal ON public."release_exception_decisions" TO pdos_next_owner USING (true) '
 'WITH CHECK (true)',
 'CREATE POLICY release_exception_read ON public."release_exception_decisions" FOR SELECT TO '
 'pdos_next_app USING (public.scope_actor()=public.scope_requester() AND EXISTS(SELECT 1 FROM '
 "public.principals h WHERE h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND "
 "h.id=public.scope_actor() AND h.kind='human' AND h.active) AND "
 'public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM public.products p WHERE '
 'p.tenant_id=release_exception_decisions.tenant_id AND '
 'p.category_id=release_exception_decisions.category_id AND '
 'p.id=release_exception_decisions.product_id) AND EXISTS(SELECT 1 FROM public.projects p WHERE '
 'p.tenant_id=release_exception_decisions.tenant_id AND '
 'p.category_id=release_exception_decisions.category_id AND '
 'p.product_id=release_exception_decisions.product_id AND p.id=release_exception_decisions.project_id) '
 'AND EXISTS(SELECT 1 FROM public.release_packages p WHERE '
 'p.tenant_id=release_exception_decisions.tenant_id AND '
 'p.category_id=release_exception_decisions.category_id AND '
 'p.product_id=release_exception_decisions.product_id AND '
 'p.project_id=release_exception_decisions.project_id AND '
 'p.owner_id=release_exception_decisions.owner_id AND '
 'p.visibility=release_exception_decisions.visibility AND '
 'p.id=release_exception_decisions.basis_package_id AND '
 'p.revision=release_exception_decisions.basis_package_revision) AND EXISTS(SELECT 1 FROM '
 'public.release_policy_facts f WHERE f.tenant_id=release_exception_decisions.tenant_id AND '
 'f.id=release_exception_decisions.policy_fact_id AND '
 'f.revision=release_exception_decisions.policy_fact_revision) AND '
 'public.direct_source_set_visible(tenant_id,category_id,product_id,release_exception_decisions.required_source_read_set))',
 'CREATE POLICY release_exception_insert ON public."release_exception_decisions" FOR INSERT TO '
 'pdos_next_app WITH CHECK (public.scope_actor()=public.scope_requester() AND EXISTS(SELECT 1 FROM '
 "public.principals h WHERE h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND "
 "h.id=public.scope_actor() AND h.kind='human' AND h.active) AND "
 'public.category_access(tenant_id,category_id,true) AND public.scope_actor()=public.scope_requester() '
 'AND EXISTS(SELECT 1 FROM public.principals h WHERE '
 "h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND h.id=public.scope_actor() AND "
 "h.kind='human' AND h.active) AND public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 "
 'FROM public.products p WHERE p.tenant_id=release_exception_decisions.tenant_id AND '
 'p.category_id=release_exception_decisions.category_id AND '
 'p.id=release_exception_decisions.product_id) AND EXISTS(SELECT 1 FROM public.projects p WHERE '
 'p.tenant_id=release_exception_decisions.tenant_id AND '
 'p.category_id=release_exception_decisions.category_id AND '
 'p.product_id=release_exception_decisions.product_id AND p.id=release_exception_decisions.project_id) '
 'AND EXISTS(SELECT 1 FROM public.release_packages p WHERE '
 'p.tenant_id=release_exception_decisions.tenant_id AND '
 'p.category_id=release_exception_decisions.category_id AND '
 'p.product_id=release_exception_decisions.product_id AND '
 'p.project_id=release_exception_decisions.project_id AND '
 'p.owner_id=release_exception_decisions.owner_id AND '
 'p.visibility=release_exception_decisions.visibility AND '
 'p.id=release_exception_decisions.basis_package_id AND '
 'p.revision=release_exception_decisions.basis_package_revision) AND EXISTS(SELECT 1 FROM '
 'public.release_policy_facts f WHERE f.tenant_id=release_exception_decisions.tenant_id AND '
 'f.id=release_exception_decisions.policy_fact_id AND '
 'f.revision=release_exception_decisions.policy_fact_revision) AND '
 'public.direct_source_set_visible(tenant_id,category_id,product_id,release_exception_decisions.required_source_read_set))',
 'REVOKE ALL ON public."release_exception_decisions" FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'GRANT SELECT,INSERT ON public."release_exception_decisions" TO pdos_next_app',
 'ALTER TABLE public."release_exception_currents" ENABLE ROW LEVEL SECURITY',
 'ALTER TABLE public."release_exception_currents" FORCE ROW LEVEL SECURITY',
 'CREATE POLICY owner_internal ON public."release_exception_currents" TO pdos_next_owner USING (true) '
 'WITH CHECK (true)',
 'CREATE POLICY release_exception_read ON public."release_exception_currents" FOR SELECT TO '
 'pdos_next_app USING (public.scope_actor()=public.scope_requester() AND EXISTS(SELECT 1 FROM '
 "public.principals h WHERE h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND "
 "h.id=public.scope_actor() AND h.kind='human' AND h.active) AND "
 'public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM '
 'public.release_exception_decisions d WHERE d.tenant_id=release_exception_currents.tenant_id AND '
 'd.category_id=release_exception_currents.category_id AND '
 'd.product_id=release_exception_currents.product_id AND '
 'd.project_id=release_exception_currents.project_id AND '
 'd.series_id=release_exception_currents.series_id AND d.owner_id=release_exception_currents.owner_id '
 'AND d.visibility=release_exception_currents.visibility AND '
 'd.id=release_exception_currents.decision_id AND '
 'd.revision=release_exception_currents.decision_revision))',
 'CREATE POLICY release_exception_insert ON public."release_exception_currents" FOR INSERT TO '
 'pdos_next_app WITH CHECK (public.scope_actor()=public.scope_requester() AND EXISTS(SELECT 1 FROM '
 "public.principals h WHERE h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND "
 "h.id=public.scope_actor() AND h.kind='human' AND h.active) AND "
 'public.category_access(tenant_id,category_id,true) AND public.scope_actor()=public.scope_requester() '
 'AND EXISTS(SELECT 1 FROM public.principals h WHERE '
 "h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND h.id=public.scope_actor() AND "
 "h.kind='human' AND h.active) AND public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 "
 'FROM public.release_exception_decisions d WHERE d.tenant_id=release_exception_currents.tenant_id AND '
 'd.category_id=release_exception_currents.category_id AND '
 'd.product_id=release_exception_currents.product_id AND '
 'd.project_id=release_exception_currents.project_id AND '
 'd.series_id=release_exception_currents.series_id AND d.owner_id=release_exception_currents.owner_id '
 'AND d.visibility=release_exception_currents.visibility AND '
 'd.id=release_exception_currents.decision_id AND '
 'd.revision=release_exception_currents.decision_revision))',
 'REVOKE ALL ON public."release_exception_currents" FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'GRANT SELECT,INSERT ON public."release_exception_currents" TO pdos_next_app',
 'CREATE POLICY release_exception_advance ON public."release_exception_currents" FOR UPDATE TO '
 'pdos_next_app USING (public.scope_actor()=public.scope_requester() AND EXISTS(SELECT 1 FROM '
 "public.principals h WHERE h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND "
 "h.id=public.scope_actor() AND h.kind='human' AND h.active) AND "
 'public.category_access(tenant_id,category_id,true) AND public.scope_actor()=public.scope_requester() '
 'AND EXISTS(SELECT 1 FROM public.principals h WHERE '
 "h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND h.id=public.scope_actor() AND "
 "h.kind='human' AND h.active) AND public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 "
 'FROM public.release_exception_decisions d WHERE d.tenant_id=release_exception_currents.tenant_id AND '
 'd.category_id=release_exception_currents.category_id AND '
 'd.product_id=release_exception_currents.product_id AND '
 'd.project_id=release_exception_currents.project_id AND '
 'd.series_id=release_exception_currents.series_id AND d.owner_id=release_exception_currents.owner_id '
 'AND d.visibility=release_exception_currents.visibility AND '
 'd.id=release_exception_currents.decision_id AND '
 'd.revision=release_exception_currents.decision_revision)) WITH CHECK '
 '(public.scope_actor()=public.scope_requester() AND EXISTS(SELECT 1 FROM public.principals h WHERE '
 "h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND h.id=public.scope_actor() AND "
 "h.kind='human' AND h.active) AND public.category_access(tenant_id,category_id,true) AND "
 'public.scope_actor()=public.scope_requester() AND EXISTS(SELECT 1 FROM public.principals h WHERE '
 "h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND h.id=public.scope_actor() AND "
 "h.kind='human' AND h.active) AND public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 "
 'FROM public.release_exception_decisions d WHERE d.tenant_id=release_exception_currents.tenant_id AND '
 'd.category_id=release_exception_currents.category_id AND '
 'd.product_id=release_exception_currents.product_id AND '
 'd.project_id=release_exception_currents.project_id AND '
 'd.series_id=release_exception_currents.series_id AND d.owner_id=release_exception_currents.owner_id '
 'AND d.visibility=release_exception_currents.visibility AND '
 'd.id=release_exception_currents.decision_id AND '
 'd.revision=release_exception_currents.decision_revision))',
 'GRANT UPDATE(decision_id,decision_revision,action,epoch) ON public."release_exception_currents" TO '
 'pdos_next_app',
 'CREATE TRIGGER release_exception_category BEFORE INSERT ON public.release_exception_decisions FOR '
 'EACH ROW EXECUTE FUNCTION public.bind_model_category()',
 'CREATE TRIGGER release_exception_category_immutable BEFORE UPDATE ON '
 'public.release_exception_decisions FOR EACH ROW EXECUTE FUNCTION public.protect_category_binding()',
 'CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON '
 'public.release_exception_decisions FOR EACH ROW EXECUTE FUNCTION public.lifecycle_reference_gate()',
 'CREATE TRIGGER category_lifecycle_clock AFTER INSERT OR UPDATE OR DELETE ON '
 'public.release_exception_decisions FOR EACH ROW EXECUTE FUNCTION public.category_lifecycle_clock()',
 'CREATE TRIGGER release_exception_category BEFORE INSERT ON public.release_exception_currents FOR EACH '
 'ROW EXECUTE FUNCTION public.bind_model_category()',
 'CREATE TRIGGER release_exception_category_immutable BEFORE UPDATE ON '
 'public.release_exception_currents FOR EACH ROW EXECUTE FUNCTION public.protect_category_binding()',
 'CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON '
 'public.release_exception_currents FOR EACH ROW EXECUTE FUNCTION public.lifecycle_reference_gate()',
 'CREATE TRIGGER category_lifecycle_clock AFTER INSERT OR UPDATE OR DELETE ON '
 'public.release_exception_currents FOR EACH ROW EXECUTE FUNCTION public.category_lifecycle_clock()',
 'CREATE TRIGGER release_exception_immutable BEFORE UPDATE OR DELETE ON '
 'public.release_exception_decisions FOR EACH ROW EXECUTE FUNCTION '
 'public.reject_release_exception_mutation()',
 'CREATE CONSTRAINT TRIGGER release_exception_decision_atom AFTER INSERT ON '
 'public.release_exception_decisions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION '
 'public.require_release_exception_decision()',
 'CREATE TRIGGER release_exception_current_guard BEFORE INSERT OR UPDATE OR DELETE ON '
 'public.release_exception_currents FOR EACH ROW EXECUTE FUNCTION '
 'public.protect_release_exception_current()',
 'CREATE CONSTRAINT TRIGGER release_exception_current_atom AFTER INSERT OR UPDATE ON '
 'public.release_exception_currents DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION '
 'public.require_release_exception_current()',
 'CREATE TRIGGER release_exception_proof_guard BEFORE INSERT OR UPDATE OR DELETE ON '
 'public.confirmations FOR EACH ROW EXECUTE FUNCTION public.protect_release_exception_proof()',
 'CREATE CONSTRAINT TRIGGER release_exception_proof_target AFTER UPDATE ON public.confirmations '
 'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION '
 'public.require_release_exception_transition()',
 'CREATE TRIGGER release_exception_receipt_guard BEFORE INSERT OR UPDATE OR DELETE ON '
 'public.action_receipts FOR EACH ROW EXECUTE FUNCTION public.protect_release_exception_receipt()',
 'CREATE CONSTRAINT TRIGGER release_exception_member_atom AFTER INSERT ON public.action_receipts '
 'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_release_exception_member()',
 'CREATE CONSTRAINT TRIGGER release_exception_member_atom AFTER INSERT ON public.audit_entries '
 'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_release_exception_member()',
 'CREATE TRIGGER release_exception_member_guard BEFORE INSERT OR UPDATE OR DELETE ON '
 'public.audit_entries FOR EACH ROW EXECUTE FUNCTION public.protect_release_exception_member()',
 'CREATE CONSTRAINT TRIGGER release_exception_member_atom AFTER INSERT ON public.outbox_events '
 'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_release_exception_member()',
 'CREATE TRIGGER release_exception_member_guard BEFORE INSERT OR UPDATE OR DELETE ON '
 'public.outbox_events FOR EACH ROW EXECUTE FUNCTION public.protect_release_exception_member()',
 'CREATE CONSTRAINT TRIGGER release_exception_member_atom AFTER INSERT ON public.request_keys '
 'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_release_exception_member()',
 'CREATE TRIGGER release_exception_member_guard BEFORE INSERT OR UPDATE OR DELETE ON '
 'public.request_keys FOR EACH ROW EXECUTE FUNCTION public.protect_release_exception_member()',
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
 "ARRAY['agent_runs','action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents'] "
 'ELSE ARRAY[\n'
 "  'artifact_versions','claims','definition_revisions','definition_sources','definition_specs',\n"
 "  'proposals','proposal_items','proposal_item_versions','proposal_submissions','proposal_decisions',\n"
 '  '
 "'category_knowledge_entries','category_knowledge_current','parameter_versions','parameter_current',\n"
 '  '
 "'evidence_links','promotion_proofs','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents'] "
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
 "    (name='action_receipts' AND payload->>'operation' LIKE 'evidence.lifecycle.%') THEN CONTINUE; END "
 'IF;\n'
 '   table_name=name;\n'
 "   node_id=CASE name WHEN 'category_knowledge_current' THEN (payload->>'lineage_id')::uuid\n"
 "    WHEN 'parameter_current' THEN (payload->>'parameter_id')::uuid ELSE (payload->>'id')::uuid END;\n"
 '   IF identities IS NULL THEN links=public.m3_lifecycle_row_links(t,c,name,payload);\n'
 '   ELSE links=public.m3_lifecycle_source_links(t,c,name,payload); END IF;\n'
 "   -- Preserve predecessor's conservative legacy graph; M3-only nodes use\n"
 '   -- strictly typed/relational links. Root lookup never uses free-text UUIDs.\n'
 '   IF identities IS NULL AND '
 "name<>ALL(ARRAY['native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals']) "
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
 "  container=CASE WHEN table_name='external_handoff_authorizations' THEN payload#>'{body,declaration}' "
 "ELSE payload->'body' END;\n"
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'mappings','[]')) LOOP\n"
 '   IF '
 "item->'ref'->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','part','bom_revision','artifact','work_instruction','control_plan'])\n"
 "    AND item->'ref'->>'id' IS NOT NULL THEN links=array_append(links,(item->'ref'->>'id')::uuid); END "
 'IF;\n'
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
 "  FOREACH key IN ARRAY ARRAY['source_refs','direct_source_refs','context_refs','baseline_claim_refs'] "
 'LOOP\n'
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
 "  FOREACH key IN ARRAY ARRAY['source_refs','direct_source_refs','context_refs','baseline_claim_refs'] "
 'LOOP\n'
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
 ' RETURN links;\n'
 'END;\n'
 '$function$\n',
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
 '  ELSE ARRAY[]::text[] END;\n'
 ' FOREACH key IN ARRAY keys LOOP\n'
 '  IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n'
 ' END LOOP;\n'
 ' RETURN links;\n'
 'END;\n'
 '$function$\n',
 'CREATE OR REPLACE FUNCTION public.protect_object_audience_target()\n'
 ' RETURNS trigger\n'
 ' LANGUAGE plpgsql\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 'DECLARE value jsonb; typ text; own_col text; model_col text;\n'
 ' t uuid; c uuid; sid uuid; expected_owner uuid; actual_owner uuid; model uuid;\n'
 ' owners jsonb=\'{"action_receipts": "requester_id", "actual_configurations": "owner_id", '
 '"artifact_versions": "owner_id", "bom_revisions": "owner_id", "build_authorization_decisions": '
 '"owner_id", "build_execution_assessments": "owner_id", "build_lots": "owner_id", '
 '"build_operational_facts": "owner_id", "build_readiness": "owner_id", "build_starts": "owner_id", '
 '"builds": "owner_id", "capa_current_observations": "owner_id", "capa_current_verification_rules": '
 '"owner_id", "capa_named_verification_reviews": "owner_id", "capa_observation_facts": "owner_id", '
 '"capa_remediation_links": "owner_id", "capa_verification_evidence": "owner_id", '
 '"capa_verification_rule_facts": "owner_id", "change_approval_records": "owner_id", '
 '"change_graph_captures": "owner_id", "change_implementation_captures": "owner_id", '
 '"change_implementation_records": "owner_id", "change_order_records": "owner_id", '
 '"change_request_versions": "owner_id", "claims": "human_owner_id", '
 '"controlled_change_coverage_currents": "owner_id", "controlled_change_coverage_facts": "owner_id", '
 '"controlled_change_policy_currents": "owner_id", "controlled_change_policy_facts": "owner_id", '
 '"controlled_change_selection_currents": "owner_id", "controlled_change_selection_facts": "owner_id", '
 '"cost_estimates": "owner_id", "cost_input_snapshots": "owner_id", "cost_source_captures": "owner_id", '
 '"definition_revisions": "owner_id", "engineering_configurations": "owner_id", '
 '"external_delivery_intents": "owner_id", "external_handoff_authorizations": "owner_id", '
 '"external_handoff_currents": "owner_id", "external_receipts": "owner_id", '
 '"manufacturing_preparation_currents": "owner_id", "manufacturing_preparation_versions": "owner_id", '
 '"measurement_import_captures": "owner_id", "parts": "owner_id", "plan_proposals": "owner_id", '
 '"plan_revisions": "owner_id", "process_revisions": "owner_id", "product_variants": "owner_id", '
 '"products": "owner_id", "professional_authority_facts": "owner_id", "projects": "owner_id", '
 '"proposals": "owner_id", "quality_issue_versions": "owner_id", "quality_policy_facts": "owner_id", '
 '"release_exception_currents": "owner_id", "release_exception_decisions": "owner_id", '
 '"sample_allocations": "owner_id", "sample_readiness_facts": "owner_id", "sample_run_usages": '
 '"owner_id", "sample_units": "owner_id", "supply_kit_projections": "owner_id", "supply_snapshots": '
 '"owner_id", "supply_source_captures": "owner_id", "test_measurements": "owner_id", '
 '"test_resource_facts": "owner_id", "test_resource_reservations": "owner_id", "test_result_actions": '
 '"owner_id", "test_result_projections": "owner_id", "uploaded_originals": "owner_id", '
 '"variant_revisions": "owner_id", "verification_actual_method_applicabilities": "owner_id", '
 '"verification_actual_method_batches": "owner_id", "verification_formal_requests": "owner_id", '
 '"verification_handoff_facts": "owner_id", "verification_launch_facts": "owner_id", '
 '"verification_method_applicabilities": "owner_id", "verification_preparations": "owner_id", '
 '"verification_run_identities": "owner_id", "verification_run_versions": "owner_id", '
 '"verification_window_proposals": "owner_id"}\'::jsonb;\n'
 'BEGIN\n'
 " IF TG_OP='DELETE' THEN value=to_jsonb(OLD); ELSE value=to_jsonb(NEW); END IF;\n"
 " IF TG_OP='UPDATE' AND\n"
 '   ROW(NEW.tenant_id,NEW.category_id,NEW.object_type,NEW.subject_id,NEW.owner_id)\n'
 '   IS DISTINCT FROM ROW(OLD.tenant_id,OLD.category_id,OLD.object_type,OLD.subject_id,OLD.owner_id)\n'
 " THEN RAISE EXCEPTION 'audience identity cannot be reassigned' USING ERRCODE='23514'; END IF;\n"
 " typ=value->>'object_type'; own_col=owners->>typ;\n"
 " t=(value->>'tenant_id')::uuid; c=(value->>'category_id')::uuid;\n"
 " sid=(value->>'subject_id')::uuid; expected_owner=(value->>'owner_id')::uuid;\n"
 ' IF own_col IS NULL THEN\n'
 "  RAISE EXCEPTION 'audience target unavailable' USING ERRCODE='23514';\n"
 ' END IF;\n'
 " IF typ='variant_revisions' THEN\n"
 '  IF m3_lock_variant_revision_audience_target(t,c,sid,expected_owner) IS DISTINCT FROM true THEN\n'
 "   RAISE EXCEPTION 'audience target unavailable' USING ERRCODE='23514';\n"
 '  END IF;\n'
 "  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n"
 ' END IF;\n'
 " IF typ='product_variants' THEN\n"
 '  IF m3_lock_variant_audience_target(t,c,sid,expected_owner) IS DISTINCT FROM true THEN\n'
 "   RAISE EXCEPTION 'audience target unavailable' USING ERRCODE='23514';\n"
 '  END IF;\n'
 "  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n"
 ' END IF;\n'
 " model_col=CASE WHEN typ='products' THEN 'id' WHEN typ='proposals' THEN 'baseline_product_id' ELSE "
 "'product_id' END;\n"
 " EXECUTE format('SELECT %I,%I FROM public.%I WHERE tenant_id=$1 AND category_id=$2 AND id=$3',\n"
 '                own_col,model_col,typ) INTO actual_owner,model USING t,c,sid;\n'
 ' IF actual_owner IS DISTINCT FROM expected_owner THEN\n'
 "  RAISE EXCEPTION 'audience target unavailable' USING ERRCODE='23514';\n"
 ' END IF;\n'
 ' IF model IS NOT NULL THEN\n'
 '  PERFORM 1 FROM products WHERE tenant_id=t AND category_id=c AND id=model FOR UPDATE;\n'
 '  IF NOT FOUND THEN\n'
 "   RAISE EXCEPTION 'audience model unavailable' USING ERRCODE='23514';\n"
 '  END IF;\n'
 ' END IF;\n'
 " EXECUTE format('SELECT %I FROM public.%I\n"
 "  WHERE tenant_id=$1 AND category_id=$2 AND id=$3 FOR UPDATE',\n"
 '                own_col,typ) INTO actual_owner USING t,c,sid;\n'
 ' IF actual_owner IS DISTINCT FROM expected_owner THEN\n'
 "  RAISE EXCEPTION 'audience target unavailable' USING ERRCODE='23514';\n"
 ' END IF;\n'
 " IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n"
 'END $function$\n',
 'ALTER TABLE public.confirmations DROP CONSTRAINT ck_confirmations_decision_deadline',
 'ALTER TABLE public.confirmations ADD CONSTRAINT ck_confirmations_decision_deadline CHECK '
 '(((((expires_at IS NOT NULL) OR ((operation)::text = ANY '
 "(ARRAY[('release.engineering.approve'::character varying)::text, "
 "('release.manufacturing.approve'::character varying)::text, "
 "('npi.manufacturing_baseline.publish'::character varying)::text, ('mcp.connector.allow'::character "
 "varying)::text, ('ai.skill.qualify'::character varying)::text, "
 "('build.engineering.authorize'::character varying)::text, ('build.manufacturing.authorize'::character "
 "varying)::text, ('change.order.approve'::character varying)::text, "
 "('change.selection.decide'::character varying)::text, ('proposal.g0.decide'::character "
 "varying)::text, ('quality.capa.verification.review'::character varying)::text, "
 "('quality.issue.root_cause.decide'::character varying)::text, ('test.disposition.decide'::character "
 "varying)::text, ('test.run.review'::character varying)::text])) OR ((expires_at IS NULL) AND "
 "((operation)::text = 'integration.handoff.authorize'::text))))) OR (expires_at IS NULL AND operation "
 "IN ('release.exception.decide','release.exception.withdraw')))")

DOWNGRADE_SQL = ('LOCK TABLE '
 'public.release_exception_decisions,public.release_exception_currents,public.confirmations,public.action_receipts '
 'IN ACCESS EXCLUSIVE MODE',
 'DO $release_exception$ BEGIN\n'
 ' IF EXISTS(SELECT 1 FROM public.release_exception_decisions) OR EXISTS(SELECT 1 FROM '
 'public.release_exception_currents)\n'
 '  OR EXISTS(SELECT 1 FROM public.confirmations WHERE operation IN '
 "('release.exception.decide','release.exception.withdraw'))\n"
 '  OR EXISTS(SELECT 1 FROM public.action_receipts WHERE operation IN '
 "('release.exception.decide','release.exception.withdraw') OR subject_type='release_exception') THEN\n"
 "  RAISE EXCEPTION 'Release exception business history retained; downgrade refused' USING "
 "ERRCODE='23514'; END IF;\n"
 'END; $release_exception$',
 'DROP TRIGGER release_exception_proof_guard ON public.confirmations',
 'DROP TRIGGER release_exception_proof_target ON public.confirmations',
 'DROP TRIGGER release_exception_receipt_guard ON public.action_receipts',
 'DROP TRIGGER release_exception_member_atom ON public.action_receipts',
 'DROP TRIGGER release_exception_member_atom ON public.audit_entries',
 'DROP TRIGGER release_exception_member_atom ON public.outbox_events',
 'DROP TRIGGER release_exception_member_atom ON public.request_keys',
 'DROP TRIGGER release_exception_member_guard ON public.audit_entries',
 'DROP TRIGGER release_exception_member_guard ON public.outbox_events',
 'DROP TRIGGER release_exception_member_guard ON public.request_keys',
 'DROP TABLE public.release_exception_currents',
 'DROP TABLE public.release_exception_decisions',
 'DROP FUNCTION public.reject_release_exception_mutation()',
 'DROP FUNCTION public.require_release_exception_decision()',
 'DROP FUNCTION public.require_release_exception_member()',
 'DROP FUNCTION public.protect_release_exception_member()',
 'DROP FUNCTION public.protect_release_exception_receipt()',
 'DROP FUNCTION public.require_release_exception_transition()',
 'DROP FUNCTION public.protect_release_exception_proof()',
 'DROP FUNCTION public.require_release_exception_current()',
 'DROP FUNCTION public.protect_release_exception_current()',
 'DROP FUNCTION public.assert_release_exception_decision(uuid,uuid)',
 'DROP FUNCTION public.release_exception_scope_covers(jsonb,jsonb)',
 'DROP FUNCTION public.assert_release_exception_authority(uuid,uuid)',
 'DROP FUNCTION public.assert_release_exception_write(uuid,uuid)',
 'DROP FUNCTION public.assert_release_exception_members(uuid,uuid)',
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
 "ARRAY['agent_runs','action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents'] "
 'ELSE ARRAY[\n'
 "  'artifact_versions','claims','definition_revisions','definition_sources','definition_specs',\n"
 "  'proposals','proposal_items','proposal_item_versions','proposal_submissions','proposal_decisions',\n"
 '  '
 "'category_knowledge_entries','category_knowledge_current','parameter_versions','parameter_current',\n"
 '  '
 "'evidence_links','promotion_proofs','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents'] "
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
 "    (name='action_receipts' AND payload->>'operation' LIKE 'evidence.lifecycle.%') THEN CONTINUE; END "
 'IF;\n'
 '   table_name=name;\n'
 "   node_id=CASE name WHEN 'category_knowledge_current' THEN (payload->>'lineage_id')::uuid\n"
 "    WHEN 'parameter_current' THEN (payload->>'parameter_id')::uuid ELSE (payload->>'id')::uuid END;\n"
 '   IF identities IS NULL THEN links=public.m3_lifecycle_row_links(t,c,name,payload);\n'
 '   ELSE links=public.m3_lifecycle_source_links(t,c,name,payload); END IF;\n'
 "   -- Preserve predecessor's conservative legacy graph; M3-only nodes use\n"
 '   -- strictly typed/relational links. Root lookup never uses free-text UUIDs.\n'
 '   IF identities IS NULL AND '
 "name<>ALL(ARRAY['native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals']) "
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
 '  ELSE ARRAY[]::text[] END;\n'
 ' FOREACH key IN ARRAY keys LOOP\n'
 '  IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n'
 ' END LOOP;\n'
 " -- Publication's exact saved read set is a validated Artifact relationship.\n"
 ' -- Do not scan its declaration, body, reason or arbitrary JSON UUID values.\n'
 ' IF table_name IN '
 "('manufacturing_baseline_publications','native_pilot_runs','native_pilot_observations','release_packages','release_decisions','release_policy_facts','external_handoff_authorizations','external_receipts') "
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
 "  container=CASE WHEN table_name='external_handoff_authorizations' THEN payload#>'{body,declaration}' "
 "ELSE payload->'body' END;\n"
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'mappings','[]')) LOOP\n"
 '   IF '
 "item->'ref'->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','part','bom_revision','artifact','work_instruction','control_plan'])\n"
 "    AND item->'ref'->>'id' IS NOT NULL THEN links=array_append(links,(item->'ref'->>'id')::uuid); END "
 'IF;\n'
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
 "  FOREACH key IN ARRAY ARRAY['source_refs','direct_source_refs','context_refs','baseline_claim_refs'] "
 'LOOP\n'
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
 "  FOREACH key IN ARRAY ARRAY['source_refs','direct_source_refs','context_refs','baseline_claim_refs'] "
 'LOOP\n'
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
 ' RETURN links;\n'
 'END;\n'
 '$function$\n',
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
 '  ELSE ARRAY[]::text[] END;\n'
 ' FOREACH key IN ARRAY keys LOOP\n'
 '  IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n'
 ' END LOOP;\n'
 ' RETURN links;\n'
 'END;\n'
 '$function$\n',
 'CREATE OR REPLACE FUNCTION public.protect_object_audience_target()\n'
 ' RETURNS trigger\n'
 ' LANGUAGE plpgsql\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 'DECLARE value jsonb; typ text; own_col text; model_col text;\n'
 ' t uuid; c uuid; sid uuid; expected_owner uuid; actual_owner uuid; model uuid;\n'
 ' owners jsonb=\'{"action_receipts": "requester_id", "actual_configurations": "owner_id", '
 '"artifact_versions": "owner_id", "bom_revisions": "owner_id", "build_authorization_decisions": '
 '"owner_id", "build_execution_assessments": "owner_id", "build_lots": "owner_id", '
 '"build_operational_facts": "owner_id", "build_readiness": "owner_id", "build_starts": "owner_id", '
 '"builds": "owner_id", "capa_current_observations": "owner_id", "capa_current_verification_rules": '
 '"owner_id", "capa_named_verification_reviews": "owner_id", "capa_observation_facts": "owner_id", '
 '"capa_remediation_links": "owner_id", "capa_verification_evidence": "owner_id", '
 '"capa_verification_rule_facts": "owner_id", "change_approval_records": "owner_id", '
 '"change_graph_captures": "owner_id", "change_implementation_captures": "owner_id", '
 '"change_implementation_records": "owner_id", "change_order_records": "owner_id", '
 '"change_request_versions": "owner_id", "claims": "human_owner_id", '
 '"controlled_change_coverage_currents": "owner_id", "controlled_change_coverage_facts": "owner_id", '
 '"controlled_change_policy_currents": "owner_id", "controlled_change_policy_facts": "owner_id", '
 '"controlled_change_selection_currents": "owner_id", "controlled_change_selection_facts": "owner_id", '
 '"cost_estimates": "owner_id", "cost_input_snapshots": "owner_id", "cost_source_captures": "owner_id", '
 '"definition_revisions": "owner_id", "engineering_configurations": "owner_id", '
 '"external_delivery_intents": "owner_id", "external_handoff_authorizations": "owner_id", '
 '"external_handoff_currents": "owner_id", "external_receipts": "owner_id", '
 '"manufacturing_preparation_currents": "owner_id", "manufacturing_preparation_versions": "owner_id", '
 '"measurement_import_captures": "owner_id", "parts": "owner_id", "plan_proposals": "owner_id", '
 '"plan_revisions": "owner_id", "process_revisions": "owner_id", "product_variants": "owner_id", '
 '"products": "owner_id", "professional_authority_facts": "owner_id", "projects": "owner_id", '
 '"proposals": "owner_id", "quality_issue_versions": "owner_id", "quality_policy_facts": "owner_id", '
 '"sample_allocations": "owner_id", "sample_readiness_facts": "owner_id", "sample_run_usages": '
 '"owner_id", "sample_units": "owner_id", "supply_kit_projections": "owner_id", "supply_snapshots": '
 '"owner_id", "supply_source_captures": "owner_id", "test_measurements": "owner_id", '
 '"test_resource_facts": "owner_id", "test_resource_reservations": "owner_id", "test_result_actions": '
 '"owner_id", "test_result_projections": "owner_id", "uploaded_originals": "owner_id", '
 '"variant_revisions": "owner_id", "verification_actual_method_applicabilities": "owner_id", '
 '"verification_actual_method_batches": "owner_id", "verification_formal_requests": "owner_id", '
 '"verification_handoff_facts": "owner_id", "verification_launch_facts": "owner_id", '
 '"verification_method_applicabilities": "owner_id", "verification_preparations": "owner_id", '
 '"verification_run_identities": "owner_id", "verification_run_versions": "owner_id", '
 '"verification_window_proposals": "owner_id"}\'::jsonb;\n'
 'BEGIN\n'
 " IF TG_OP='DELETE' THEN value=to_jsonb(OLD); ELSE value=to_jsonb(NEW); END IF;\n"
 " IF TG_OP='UPDATE' AND\n"
 '   ROW(NEW.tenant_id,NEW.category_id,NEW.object_type,NEW.subject_id,NEW.owner_id)\n'
 '   IS DISTINCT FROM ROW(OLD.tenant_id,OLD.category_id,OLD.object_type,OLD.subject_id,OLD.owner_id)\n'
 " THEN RAISE EXCEPTION 'audience identity cannot be reassigned' USING ERRCODE='23514'; END IF;\n"
 " typ=value->>'object_type'; own_col=owners->>typ;\n"
 " t=(value->>'tenant_id')::uuid; c=(value->>'category_id')::uuid;\n"
 " sid=(value->>'subject_id')::uuid; expected_owner=(value->>'owner_id')::uuid;\n"
 ' IF own_col IS NULL THEN\n'
 "  RAISE EXCEPTION 'audience target unavailable' USING ERRCODE='23514';\n"
 ' END IF;\n'
 " IF typ='variant_revisions' THEN\n"
 '  IF m3_lock_variant_revision_audience_target(t,c,sid,expected_owner) IS DISTINCT FROM true THEN\n'
 "   RAISE EXCEPTION 'audience target unavailable' USING ERRCODE='23514';\n"
 '  END IF;\n'
 "  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n"
 ' END IF;\n'
 " IF typ='product_variants' THEN\n"
 '  IF m3_lock_variant_audience_target(t,c,sid,expected_owner) IS DISTINCT FROM true THEN\n'
 "   RAISE EXCEPTION 'audience target unavailable' USING ERRCODE='23514';\n"
 '  END IF;\n'
 "  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n"
 ' END IF;\n'
 " model_col=CASE WHEN typ='products' THEN 'id' WHEN typ='proposals' THEN 'baseline_product_id' ELSE "
 "'product_id' END;\n"
 " EXECUTE format('SELECT %I,%I FROM public.%I WHERE tenant_id=$1 AND category_id=$2 AND id=$3',\n"
 '                own_col,model_col,typ) INTO actual_owner,model USING t,c,sid;\n'
 ' IF actual_owner IS DISTINCT FROM expected_owner THEN\n'
 "  RAISE EXCEPTION 'audience target unavailable' USING ERRCODE='23514';\n"
 ' END IF;\n'
 ' IF model IS NOT NULL THEN\n'
 '  PERFORM 1 FROM products WHERE tenant_id=t AND category_id=c AND id=model FOR UPDATE;\n'
 '  IF NOT FOUND THEN\n'
 "   RAISE EXCEPTION 'audience model unavailable' USING ERRCODE='23514';\n"
 '  END IF;\n'
 ' END IF;\n'
 " EXECUTE format('SELECT %I FROM public.%I\n"
 "  WHERE tenant_id=$1 AND category_id=$2 AND id=$3 FOR UPDATE',\n"
 '                own_col,typ) INTO actual_owner USING t,c,sid;\n'
 ' IF actual_owner IS DISTINCT FROM expected_owner THEN\n'
 "  RAISE EXCEPTION 'audience target unavailable' USING ERRCODE='23514';\n"
 ' END IF;\n'
 " IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n"
 'END $function$\n',
 'ALTER TABLE public.confirmations DROP CONSTRAINT ck_confirmations_decision_deadline',
 'ALTER TABLE public.confirmations ADD CONSTRAINT ck_confirmations_decision_deadline CHECK '
 '(((expires_at IS NOT NULL) OR ((operation)::text = ANY '
 "(ARRAY[('release.engineering.approve'::character varying)::text, "
 "('release.manufacturing.approve'::character varying)::text, "
 "('npi.manufacturing_baseline.publish'::character varying)::text, ('mcp.connector.allow'::character "
 "varying)::text, ('ai.skill.qualify'::character varying)::text, "
 "('build.engineering.authorize'::character varying)::text, ('build.manufacturing.authorize'::character "
 "varying)::text, ('change.order.approve'::character varying)::text, "
 "('change.selection.decide'::character varying)::text, ('proposal.g0.decide'::character "
 "varying)::text, ('quality.capa.verification.review'::character varying)::text, "
 "('quality.issue.root_cause.decide'::character varying)::text, ('test.disposition.decide'::character "
 "varying)::text, ('test.run.review'::character varying)::text])) OR ((expires_at IS NULL) AND "
 "((operation)::text = 'integration.handoff.authorize'::text))))")

