"""Frozen native Field facts, actual location and independent responses."""

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
                                         '$function$\n'}

FIELD_FUNCTIONS = {'m3_lifecycle_row_links(uuid,uuid,text,jsonb)': 'CREATE OR REPLACE FUNCTION '
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
                                                 "  WHEN 'field_feedback_versions' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'field_feedback_currents' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'field_response_records' THEN "
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
                                                    '\n'
                                                    ' IF table_name IN '
                                                    "('field_feedback_versions','field_feedback_currents','field_response_records') "
                                                    'THEN\n'
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['previous_id','version_id','feedback_version_id'] "
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
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['engineering_configuration','manufacturing_configuration','batch'] "
                                                    'LOOP\n'
                                                    "   IF payload#>>ARRAY['body','location',key,'id'] "
                                                    'IS NOT NULL THEN '
                                                    "links=array_append(links,(payload#>>ARRAY['body','location',key,'id'])::uuid); "
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
                                                    ' END IF;\n'
                                                    ' IF table_name IN '
                                                    "('change_request_versions','change_graph_captures') "
                                                    'THEN\n'
                                                    '  FOR container IN SELECT value FROM '
                                                    "jsonb_each(coalesce(payload#>'{source_basis,owners}','{}')) "
                                                    'LOOP\n'
                                                    "   IF container->>'feedback_version_id' IS NOT "
                                                    'NULL THEN '
                                                    "links=array_append(links,(container->>'feedback_version_id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
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
                                         "ARRAY['agent_runs','action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','project_risk_followups','project_risk_followup_currents','knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents','field_feedback_versions','field_feedback_currents','field_response_records'] "
                                         'ELSE ARRAY[\n'
                                         '  '
                                         "'artifact_versions','claims','definition_revisions','definition_sources','definition_specs',\n"
                                         '  '
                                         "'proposals','proposal_items','proposal_item_versions','proposal_submissions','proposal_decisions',\n"
                                         '  '
                                         "'category_knowledge_entries','category_knowledge_current','parameter_versions','parameter_current',\n"
                                         '  '
                                         "'evidence_links','promotion_proofs','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','project_risk_followups','project_risk_followup_currents','knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents','field_feedback_versions','field_feedback_currents','field_response_records'] "
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
                                         "name<>ALL(ARRAY['native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','project_risk_followups','project_risk_followup_currents','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents','field_feedback_versions','field_feedback_currents','field_response_records']) "
                                         'THEN\n'
                                         '    links=links || '
                                         'public.kernel_lifecycle_links(name,payload);\n'
                                         '   END IF;\n'
                                         '   RETURN NEXT;\n'
                                         '  END LOOP;\n'
                                         ' END LOOP;\n'
                                         'END;\n'
                                         '$function$\n',
 'reject_field_mutation()': 'CREATE OR REPLACE FUNCTION public.reject_field_mutation()\n'
                            ' RETURNS trigger\n'
                            ' LANGUAGE plpgsql\n'
                            ' SECURITY DEFINER\n'
                            " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                            'AS $function$\n'
                            "BEGIN RAISE EXCEPTION 'Field facts are immutable' USING ERRCODE='23514'; "
                            'END;\n'
                            '$function$\n',
 'assert_field_common(uuid,uuid,text)': 'CREATE OR REPLACE FUNCTION public.assert_field_common(t uuid, '
                                        'target uuid, kind text)\n'
                                        ' RETURNS void\n'
                                        ' LANGUAGE plpgsql\n'
                                        ' SECURITY DEFINER\n'
                                        " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                        'AS $function$\n'
                                        '\n'
                                        'DECLARE v record; envelope jsonb; vx xid; rx xid; px xid; ref '
                                        'jsonb; basis jsonb; active_sources jsonb;\n'
                                        'BEGIN\n'
                                        '\n'
                                        " IF kind='field_feedback' THEN SELECT x.*,x.xmin AS tx INTO "
                                        'STRICT v FROM public.field_feedback_versions x WHERE '
                                        'x.tenant_id=t AND x.id=target;\n'
                                        " ELSIF kind='field_response' THEN SELECT x.*,x.xmin AS tx "
                                        'INTO STRICT v FROM public.field_response_records x WHERE '
                                        'x.tenant_id=t AND x.id=target;\n'
                                        " ELSE RAISE EXCEPTION 'Unknown Field subject' USING "
                                        "ERRCODE='23514'; END IF;\n"
                                        '\n'
                                        ' vx=v.tx;\n'
                                        ' SELECT xmin INTO rx FROM public.action_receipts WHERE '
                                        'tenant_id=t AND id=v.receipt_id;\n'
                                        ' PERFORM public.assert_field_members(t,target,kind);\n'
                                        " envelope=v.command->'envelope';\n"
                                        ' IF v.actor_id IS DISTINCT FROM public.scope_actor() OR '
                                        'v.requester_id IS DISTINCT FROM public.scope_requester()\n'
                                        '  OR v.writer_id<>v.actor_id OR vx IS DISTINCT FROM rx OR NOT '
                                        'public.category_access(t,v.category_id,true)\n'
                                        '  OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE '
                                        'h.tenant_id=t AND h.id=v.actor_id AND h.active)\n'
                                        '  OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE '
                                        "h.tenant_id=t AND h.id=v.requester_id AND h.kind='human' AND "
                                        'h.active)\n'
                                        "  OR envelope->>'operation' IS DISTINCT FROM v.operation OR "
                                        "envelope->>'command_id' IS DISTINCT FROM v.command_id::text\n"
                                        "  OR envelope->>'category_id' IS DISTINCT FROM "
                                        "v.category_id::text OR envelope->>'product_id' IS DISTINCT "
                                        'FROM v.product_id::text\n'
                                        "  OR v.command->'review'->'declaration' IS DISTINCT FROM "
                                        "envelope->'payload'\n"
                                        "  OR v.command->'review'->>'operation' IS DISTINCT FROM "
                                        'v.operation\n'
                                        "  OR v.command->'review'->'sources' IS DISTINCT FROM "
                                        "envelope->'payload'->'sources'\n"
                                        "  OR v.command->'review'->'source_basis' IS DISTINCT FROM "
                                        'v.source_basis OR v.body IS DISTINCT FROM '
                                        "v.command->'review'->'after'\n"
                                        '  OR (v.product_id IS NULL AND NOT EXISTS(SELECT 1 FROM '
                                        'public.categories c WHERE c.tenant_id=t AND '
                                        'c.id=v.category_id AND '
                                        "c.revision::text=envelope->>'expected_revision'))\n"
                                        '  OR (v.product_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM '
                                        'public.products p WHERE p.tenant_id=t AND '
                                        'p.category_id=v.category_id AND p.id=v.product_id AND '
                                        "p.revision::text=envelope->>'expected_revision'))\n"
                                        '  OR (v.project_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM '
                                        'public.projects p WHERE p.tenant_id=t AND '
                                        'p.category_id=v.category_id AND p.product_id=v.product_id AND '
                                        'p.id=v.project_id))\n'
                                        "  OR NOT coalesce(envelope->'source_read_set' @> "
                                        'v.reads,false) OR NOT coalesce(v.reads @> '
                                        "(envelope->'source_read_set'),false)\n"
                                        '  OR '
                                        "jsonb_array_length(envelope->'source_read_set')<>jsonb_array_length(v.reads)\n"
                                        '  OR NOT '
                                        'public.direct_source_set_visible(t,v.category_id,v.product_id,v.reads)\n'
                                        '  OR NOT '
                                        'public.knowledge_content_sources_visible(t,v.category_id,v.product_id,v.source_basis)\n'
                                        '  OR NOT '
                                        'public.knowledge_result_sources_visible(t,v.category_id,v.product_id,v.source_basis)\n'
                                        '  OR (v.actor_id<>v.requester_id AND NOT EXISTS(SELECT 1 FROM '
                                        'public.action_receipts r WHERE r.tenant_id=t AND '
                                        'r.id=v.receipt_id AND coalesce(r.agent_run_id,r.run_id) IS '
                                        'NOT NULL))\n'
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
                                        "  RAISE EXCEPTION 'Field requires actual scope actor sources "
                                        "and one common transaction' USING ERRCODE='23514'; END IF;\n"
                                        ' IF v.confirmation_id IS NOT NULL THEN\n'
                                        '  SELECT xmin INTO px FROM public.confirmations WHERE '
                                        'tenant_id=t AND id=v.confirmation_id;\n'
                                        "  IF px IS DISTINCT FROM vx THEN RAISE EXCEPTION 'Field T1 "
                                        "consumption shares its new fact transaction' USING "
                                        "ERRCODE='23514'; END IF;\n"
                                        ' END IF;\n'
                                        " IF jsonb_typeof(v.source_basis->'artifacts') IS DISTINCT "
                                        "FROM 'array' THEN\n"
                                        "  RAISE EXCEPTION 'Field requires actual direct-source "
                                        "metadata' USING ERRCODE='23514'; END IF;\n"
                                        ' FOR basis IN SELECT value FROM '
                                        "jsonb_array_elements(v.source_basis->'artifacts') LOOP\n"
                                        '  IF NOT EXISTS(SELECT 1 FROM public.artifact_versions a '
                                        'WHERE a.tenant_id=t AND a.category_id=v.category_id\n'
                                        '   AND a.product_id::text IS NOT DISTINCT FROM '
                                        "basis->>'product_id' AND a.id::text=basis->>'id'\n"
                                        "   AND a.revision::text=basis->>'revision' AND "
                                        "a.content_hash=basis->>'hash'\n"
                                        "   AND (v.visibility='private' OR (a.visibility='category' "
                                        'AND (a.product_id IS NULL OR EXISTS(SELECT 1 FROM '
                                        'public.products source_product\n'
                                        '    WHERE source_product.tenant_id=t AND '
                                        'source_product.category_id=v.category_id AND '
                                        'source_product.id=a.product_id AND '
                                        "source_product.visibility='category'))))\n"
                                        "   AND (a.original_id IS NULL OR v.visibility='private' OR "
                                        'EXISTS(SELECT 1 FROM public.uploaded_originals o\n'
                                        '    WHERE o.tenant_id=t AND o.id=a.original_id AND '
                                        "o.visibility='category'))) THEN\n"
                                        "   RAISE EXCEPTION 'Field historical source hash or actual "
                                        "audience changed' USING ERRCODE='23514'; END IF;\n"
                                        ' END LOOP;\n'
                                        " active_sources=CASE WHEN kind='field_feedback' THEN "
                                        "v.sources ELSE envelope->'payload'->'sources' END;\n"
                                        " IF v.operation='field.feedback.followup.link' THEN\n"
                                        '  active_sources=active_sources||coalesce((SELECT '
                                        'jsonb_agg(content.value) FROM '
                                        "jsonb_array_elements(v.source_basis->'result_receipts') "
                                        'result,\n'
                                        '   LATERAL '
                                        "jsonb_array_elements(result->'direct_content_refs') "
                                        "content),'[]'::jsonb);\n"
                                        ' END IF;\n'
                                        ' FOR ref IN SELECT value FROM '
                                        'jsonb_array_elements(active_sources) LOOP\n'
                                        '  SELECT value INTO STRICT basis FROM '
                                        "jsonb_array_elements(v.source_basis->'artifacts') WHERE "
                                        "value->>'id'=ref->>'id';\n"
                                        "  IF ref->>'kind' IS DISTINCT FROM 'artifact' OR NOT "
                                        'EXISTS(SELECT 1 FROM jsonb_array_elements(v.reads) rd WHERE '
                                        "rd->>'artifact_id'=ref->>'id' AND "
                                        "rd->'expected_revision'=ref->'revision')\n"
                                        '   OR NOT EXISTS(SELECT 1 FROM public.artifact_versions a '
                                        'WHERE a.tenant_id=t AND a.category_id=v.category_id\n'
                                        "    AND a.id::text=ref->>'id' AND "
                                        "a.revision::text=ref->>'revision' AND a.status='active'\n"
                                        '    AND a.product_id::text IS NOT DISTINCT FROM '
                                        "basis->>'product_id' AND a.revision::text=basis->>'revision'\n"
                                        "    AND a.content_hash=basis->>'hash' AND "
                                        "a.status=basis->>'status' AND "
                                        "a.owner_id::text=basis->>'owner_id' AND "
                                        "a.visibility=basis->>'visibility'\n"
                                        '    AND ((a.original_id IS NULL AND '
                                        "basis->>'source_kind'='registered_native_text' AND "
                                        'EXISTS(SELECT 1 FROM public.action_receipts r\n'
                                        '      WHERE r.tenant_id=t AND r.subject_id=a.id AND '
                                        "r.subject_revision=a.revision AND r.subject_type='artifact' "
                                        "AND r.operation='evidence.artifact.register'\n"
                                        "       AND r.id::text=basis->'registration'->>'receipt_id' "
                                        "AND r.actor_id::text=basis->'registration'->>'actor_id'\n"
                                        '       AND '
                                        "r.requester_id::text=basis->'registration'->>'requester_id' "
                                        'AND r.run_id::text IS NOT DISTINCT FROM '
                                        "basis->'registration'->>'run_id'))\n"
                                        '     OR (a.original_id IS NOT NULL AND '
                                        "basis->>'source_kind'='uploaded_original' AND EXISTS(SELECT 1 "
                                        'FROM public.uploaded_originals o\n'
                                        '      JOIN public.original_security sec ON '
                                        'sec.tenant_id=o.tenant_id AND sec.original_id=o.id WHERE '
                                        'o.tenant_id=t AND o.category_id=v.category_id\n'
                                        '       AND o.id=a.original_id AND '
                                        "o.id::text=basis->'original'->>'id' AND o.status='parsed' AND "
                                        "sec.epoch::text=basis->'original'->>'epoch'\n"
                                        "       AND sec.source_state='active' AND "
                                        "sec.disposition='active' AND "
                                        "sec.source_state=basis->'original'->>'source_state'\n"
                                        '       AND '
                                        "sec.disposition=basis->'original'->>'disposition')))) THEN\n"
                                        "   RAISE EXCEPTION 'Field newly adopted direct source "
                                        "metadata changed' USING ERRCODE='23514'; END IF;\n"
                                        ' END LOOP;\n'
                                        'END;\n'
                                        '$function$\n',
 'require_field_feedback()': 'CREATE OR REPLACE FUNCTION public.require_field_feedback()\n'
                             ' RETURNS trigger\n'
                             ' LANGUAGE plpgsql\n'
                             ' SECURITY DEFINER\n'
                             " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                             'AS $function$\n'
                             'BEGIN PERFORM public.assert_field_feedback(NEW.tenant_id,NEW.id); RETURN '
                             'NULL; END;\n'
                             '$function$\n',
 'require_field_response()': 'CREATE OR REPLACE FUNCTION public.require_field_response()\n'
                             ' RETURNS trigger\n'
                             ' LANGUAGE plpgsql\n'
                             ' SECURITY DEFINER\n'
                             " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                             'AS $function$\n'
                             'BEGIN PERFORM public.assert_field_response(NEW.tenant_id,NEW.id); RETURN '
                             'NULL; END;\n'
                             '$function$\n',
 'protect_field_current()': 'CREATE OR REPLACE FUNCTION public.protect_field_current()\n'
                            ' RETURNS trigger\n'
                            ' LANGUAGE plpgsql\n'
                            ' SECURITY DEFINER\n'
                            " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                            'AS $function$\n'
                            '\n'
                            'BEGIN\n'
                            " IF TG_OP='INSERT' AND NEW.revision=1 THEN RETURN NEW;\n"
                            " ELSIF TG_OP='UPDATE'\n"
                            '  AND '
                            "(to_jsonb(NEW)-ARRAY['version_id','revision','product_id','project_id']) "
                            'IS NOT DISTINCT FROM '
                            "(to_jsonb(OLD)-ARRAY['version_id','revision','product_id','project_id'])\n"
                            '  AND NEW.revision=OLD.revision+1 AND (OLD.product_id IS NULL OR '
                            'NEW.product_id=OLD.product_id)\n'
                            '  AND EXISTS(SELECT 1 FROM public.field_feedback_versions v WHERE '
                            'v.tenant_id=NEW.tenant_id AND v.id=NEW.version_id\n'
                            '   AND v.revision=NEW.revision AND v.previous_id=OLD.version_id AND '
                            'v.previous_revision=OLD.revision\n'
                            "   AND v.operation='field.feedback.locate' AND "
                            'v.product_id=NEW.product_id AND v.project_id IS NOT DISTINCT FROM '
                            'NEW.project_id)\n'
                            ' THEN RETURN NEW; END IF;\n'
                            " RAISE EXCEPTION 'Field Current requires an exact single-step location "
                            "CAS' USING ERRCODE='23514';\n"
                            'END;\n'
                            '$function$\n',
 'require_field_current()': 'CREATE OR REPLACE FUNCTION public.require_field_current()\n'
                            ' RETURNS trigger\n'
                            ' LANGUAGE plpgsql\n'
                            ' SECURITY DEFINER\n'
                            " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                            'AS $function$\n'
                            '\n'
                            'DECLARE cur public.field_feedback_currents; fixed '
                            'public.field_feedback_versions; cx xid; vx xid;\n'
                            'BEGIN\n'
                            ' SELECT * INTO STRICT cur FROM public.field_feedback_currents WHERE '
                            'tenant_id=NEW.tenant_id AND id=NEW.id;\n'
                            ' SELECT xmin INTO cx FROM public.field_feedback_currents WHERE '
                            'tenant_id=NEW.tenant_id AND id=NEW.id;\n'
                            ' SELECT * INTO STRICT fixed FROM public.field_feedback_versions WHERE '
                            'tenant_id=NEW.tenant_id AND id=cur.version_id;\n'
                            ' SELECT xmin INTO vx FROM public.field_feedback_versions WHERE '
                            'tenant_id=NEW.tenant_id AND id=cur.version_id;\n'
                            ' IF vx IS DISTINCT FROM cx OR '
                            'ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.feedback_id,cur.version_id,cur.revision)\n'
                            '  IS DISTINCT FROM '
                            'ROW(fixed.category_id,fixed.product_id,fixed.project_id,fixed.owner_id,fixed.visibility,fixed.feedback_id,fixed.id,fixed.revision) '
                            'THEN\n'
                            "  RAISE EXCEPTION 'Field Current requires its exact same-transaction "
                            "version' USING ERRCODE='23514'; END IF;\n"
                            ' RETURN NULL;\n'
                            'END;\n'
                            '$function$\n',
 'assert_field_members(uuid,uuid,text)': 'CREATE OR REPLACE FUNCTION public.assert_field_members(t '
                                         'uuid, target uuid, kind text)\n'
                                         ' RETURNS void\n'
                                         ' LANGUAGE plpgsql\n'
                                         ' SECURITY DEFINER\n'
                                         " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                         'AS $function$\n'
                                         '\n'
                                         'DECLARE v record; r public.action_receipts; proof '
                                         'public.confirmations; expected jsonb; event_name text;\n'
                                         'BEGIN\n'
                                         '\n'
                                         " IF kind='field_feedback' THEN SELECT x.*,x.xmin AS tx INTO "
                                         'STRICT v FROM public.field_feedback_versions x WHERE '
                                         'x.tenant_id=t AND x.id=target;\n'
                                         " ELSIF kind='field_response' THEN SELECT x.*,x.xmin AS tx "
                                         'INTO STRICT v FROM public.field_response_records x WHERE '
                                         'x.tenant_id=t AND x.id=target;\n'
                                         " ELSE RAISE EXCEPTION 'Unknown Field subject' USING "
                                         "ERRCODE='23514'; END IF;\n"
                                         '\n'
                                         ' '
                                         "expected=jsonb_build_object('id',v.id,'revision',v.revision,'status',CASE "
                                         "WHEN kind='field_response' THEN 'recorded' WHEN "
                                         "v.body->'location' IS NOT NULL AND "
                                         "v.body->'location'<>'null'::jsonb THEN 'located' ELSE "
                                         "'unknown' END,\n"
                                         "  'feedback_id',v.feedback_id,'project_id',v.project_id);\n"
                                         " event_name=CASE v.operation WHEN 'field.feedback.create' "
                                         "THEN 'field.feedback_created' WHEN 'field.feedback.locate' "
                                         "THEN 'field.feedback_located'\n"
                                         "  WHEN 'field.feedback.action.record' THEN "
                                         "'field.feedback_action_recorded' WHEN "
                                         "'field.feedback.followup.link' THEN "
                                         "'field.feedback_followup_linked' END;\n"
                                         ' SELECT * INTO STRICT r FROM public.action_receipts WHERE '
                                         'tenant_id=t AND id=v.receipt_id;\n'
                                         ' IF '
                                         'ROW(r.category_id,r.product_id,r.command_id,r.confirmation_id,r.actor_id,r.requester_id,r.operation,r.subject_type,r.subject_id,r.subject_revision,r.visibility,r.request_digest,r.intent_digest)\n'
                                         '  IS DISTINCT FROM '
                                         'ROW(v.category_id,v.product_id,v.command_id,v.confirmation_id,v.actor_id,v.requester_id,v.operation,kind::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)\n'
                                         '  OR r.result IS DISTINCT FROM expected OR '
                                         'r.created_at<v.created_at OR event_name IS NULL\n'
                                         '  OR (SELECT count(*) FROM public.action_receipts x WHERE '
                                         'x.tenant_id=t AND x.operation=v.operation AND '
                                         'x.subject_type=kind AND x.subject_id=v.id AND '
                                         'x.subject_revision=v.revision)<>1\n'
                                         '  OR (SELECT count(*) FROM public.audit_entries x WHERE '
                                         'x.tenant_id=t AND x.receipt_id=v.receipt_id)<>1\n'
                                         '  OR NOT EXISTS(SELECT 1 FROM public.audit_entries x WHERE '
                                         'x.tenant_id=t AND x.receipt_id=v.receipt_id AND '
                                         'x.category_id=v.category_id AND x.actor_id=v.actor_id AND '
                                         'x.operation=v.operation AND x.created_at>=v.created_at)\n'
                                         '  OR (SELECT count(*) FROM public.outbox_events x WHERE '
                                         'x.tenant_id=t AND x.receipt_id=v.receipt_id)<>1\n'
                                         '  OR NOT EXISTS(SELECT 1 FROM public.outbox_events x WHERE '
                                         'x.tenant_id=t AND x.receipt_id=v.receipt_id AND '
                                         'x.category_id=v.category_id AND x.actor_id=v.actor_id AND '
                                         'x.type=event_name AND x.subject_id=v.id AND '
                                         'x.subject_revision=v.revision AND x.schema_version=1 AND '
                                         'x.correlation_id=coalesce(r.agent_run_id,r.run_id,v.command_id) '
                                         'AND x.created_at>=v.created_at)\n'
                                         "  OR v.command->>'original_key_sha256' IS NULL OR "
                                         "v.command->>'original_key_sha256' !~ '^[a-f0-9]{64}$'\n"
                                         "  OR v.command->'envelope' ? 'idempotency_key' OR "
                                         "v.command->'envelope'->'payload' ? 'confirmation_token'\n"
                                         "  OR v.command->'envelope'->'payload' ? 'approval_token'\n"
                                         '  OR NOT EXISTS(SELECT 1 FROM public.request_keys x WHERE '
                                         'x.tenant_id=t AND x.category_id=v.category_id AND '
                                         'x.receipt_id=v.receipt_id AND x.actor_id=v.actor_id AND '
                                         'x.digest=v.request_digest AND '
                                         "encode(sha256(convert_to(x.key,'UTF8')),'hex')=v.command->>'original_key_sha256') "
                                         'THEN\n'
                                         "  RAISE EXCEPTION 'Field original receipt audit event or "
                                         "request key mismatch' USING ERRCODE='23514'; END IF;\n"
                                         " IF v.operation<>'field.feedback.create' THEN\n"
                                         '  SELECT * INTO STRICT proof FROM public.confirmations WHERE '
                                         'tenant_id=t AND id=v.confirmation_id;\n'
                                         '  IF proof.consumed IS DISTINCT FROM true OR '
                                         'ROW(proof.category_id,proof.product_id,proof.actor_id,proof.operation,proof.subject_type,proof.subject_id,proof.revision)\n'
                                         '   IS DISTINCT FROM '
                                         'ROW(v.category_id,v.product_id,v.actor_id,v.operation,(CASE '
                                         "WHEN v.product_id IS NULL THEN 'category' ELSE 'product' "
                                         "END)::varchar,coalesce(v.product_id,v.category_id),(v.command->'envelope'->>'expected_revision')::integer)\n"
                                         "   OR proof.snapshot IS DISTINCT FROM v.command->'review' OR "
                                         'proof.created_at>v.created_at OR proof.expires_at IS NULL\n'
                                         '   OR v.created_at>=proof.expires_at OR '
                                         'r.created_at>=proof.expires_at OR '
                                         'v.actor_id<>v.requester_id\n'
                                         '   OR r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL '
                                         'THEN\n'
                                         "   RAISE EXCEPTION 'Field T1 requires its actual consumed "
                                         "human confirmation' USING ERRCODE='23514'; END IF;\n"
                                         ' END IF;\n'
                                         'END;\n'
                                         '$function$\n',
 'assert_field_feedback(uuid,uuid)': 'CREATE OR REPLACE FUNCTION public.assert_field_feedback(t uuid, '
                                     'target uuid)\n'
                                     ' RETURNS void\n'
                                     ' LANGUAGE plpgsql\n'
                                     ' SECURITY DEFINER\n'
                                     " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                     'AS $function$\n'
                                     '\n'
                                     'DECLARE v public.field_feedback_versions; prior '
                                     'public.field_feedback_versions; cur '
                                     'public.field_feedback_currents;\n'
                                     ' payload jsonb; expected jsonb; location jsonb; vx xid; cx xid;\n'
                                     'BEGIN\n'
                                     ' SELECT * INTO STRICT v FROM public.field_feedback_versions '
                                     'WHERE tenant_id=t AND id=target;\n'
                                     ' SELECT xmin INTO vx FROM public.field_feedback_versions WHERE '
                                     'tenant_id=t AND id=target;\n'
                                     " PERFORM public.assert_field_common(t,target,'field_feedback');\n"
                                     ' SELECT * INTO STRICT cur FROM public.field_feedback_currents '
                                     'WHERE tenant_id=t AND category_id=v.category_id AND '
                                     'feedback_id=v.feedback_id;\n'
                                     ' SELECT xmin INTO cx FROM public.field_feedback_currents WHERE '
                                     'tenant_id=t AND id=cur.id;\n'
                                     " payload=v.command->'envelope'->'payload';\n"
                                     ' IF vx IS DISTINCT FROM cx OR '
                                     'ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.feedback_id,cur.version_id,cur.revision)\n'
                                     '  IS DISTINCT FROM '
                                     'ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.feedback_id,v.id,v.revision)\n'
                                     "  OR v.owner_id<>v.requester_id THEN RAISE EXCEPTION 'Field "
                                     "feedback binds actual owner and same-transaction Current' USING "
                                     "ERRCODE='23514'; END IF;\n"
                                     " IF v.operation='field.feedback.create' THEN\n"
                                     '  '
                                     "expected=jsonb_build_object('feedback_id',v.feedback_id,'revision',1,'title',payload->'title','description',payload->'description',\n"
                                     '   '
                                     "'channel',payload->'channel','feedback_kind',payload->'feedback_kind','received_at',payload->'received_at','reported',payload->'reported','purpose',payload->'purpose','location',NULL);\n"
                                     '  IF v.body IS DISTINCT FROM expected OR v.sources IS DISTINCT '
                                     "FROM payload->'sources' OR v.project_id IS NOT NULL\n"
                                     "   OR payload->>'visibility' IS DISTINCT FROM v.visibility OR "
                                     "coalesce(v.command->'review'->'before','null'::jsonb)<>'null'::jsonb "
                                     'THEN\n'
                                     "   RAISE EXCEPTION 'Field intake records only its actual "
                                     "declared source report, with unknown location' USING "
                                     "ERRCODE='23514'; END IF;\n"
                                     ' ELSE\n'
                                     '  SELECT * INTO STRICT prior FROM public.field_feedback_versions '
                                     'WHERE tenant_id=t AND id=v.previous_id;\n'
                                     "  location=v.body->'location';\n"
                                     '  IF ROW(v.category_id,v.owner_id,v.visibility,v.feedback_id) IS '
                                     'DISTINCT FROM '
                                     'ROW(prior.category_id,prior.owner_id,prior.visibility,prior.feedback_id)\n'
                                     '   OR (prior.product_id IS NOT NULL AND prior.product_id IS '
                                     'DISTINCT FROM v.product_id)\n'
                                     "   OR v.product_id IS NULL OR payload->'feedback' IS DISTINCT "
                                     'FROM '
                                     "jsonb_build_object('id',v.feedback_id,'revision',prior.revision)\n"
                                     "   OR v.command->'review'->'before' IS DISTINCT FROM prior.body\n"
                                     "   OR (v.body-ARRAY['revision','location']) IS DISTINCT FROM "
                                     "(prior.body-ARRAY['revision','location'])\n"
                                     "   OR v.body->'revision' IS DISTINCT FROM to_jsonb(v.revision)\n"
                                     "   OR jsonb_typeof(location) IS DISTINCT FROM 'object' OR "
                                     "location->>'state' IS DISTINCT FROM 'known'\n"
                                     "   OR location->>'product_id' IS DISTINCT FROM "
                                     "v.product_id::text OR location->>'project_id' IS DISTINCT FROM "
                                     'v.project_id::text\n'
                                     "   OR location->'engineering_configuration' IS DISTINCT FROM "
                                     "payload->'engineering_configuration'\n"
                                     "   OR location->'manufacturing_configuration' IS DISTINCT FROM "
                                     "payload->'manufacturing_configuration'\n"
                                     "   OR location->'batch' IS DISTINCT FROM payload->'batch'\n"
                                     "   OR (coalesce(payload->'batch','null'::jsonb)='null'::jsonb "
                                     "AND payload->>'project_id' IS DISTINCT FROM v.project_id::text)\n"
                                     '   OR NOT coalesce(v.sources @> prior.sources,false) OR NOT '
                                     "coalesce(v.sources @> payload->'sources',false)\n"
                                     "   OR NOT coalesce(v.sources @> location->'sources',false)\n"
                                     '   OR EXISTS(SELECT 1 FROM jsonb_array_elements(v.sources) '
                                     'source WHERE NOT(prior.sources @> jsonb_build_array(source)\n'
                                     "    OR payload->'sources' @> jsonb_build_array(source) OR "
                                     "location->'sources' @> jsonb_build_array(source))) THEN\n"
                                     "   RAISE EXCEPTION 'Field location preserves report, privacy and "
                                     "exact predecessor; known product cannot silently change' USING "
                                     "ERRCODE='23514'; END IF;\n"
                                     '  IF NOT EXISTS(SELECT 1 FROM public.engineering_configurations '
                                     'engineering WHERE engineering.tenant_id=t AND '
                                     'engineering.category_id=v.category_id\n'
                                     '   AND engineering.product_id=v.product_id AND '
                                     "engineering.id::text=location->'engineering_configuration'->>'id'\n"
                                     '   AND '
                                     "engineering.revision::text=location->'engineering_configuration'->>'revision'\n"
                                     '   AND coalesce(v.reads @> '
                                     'engineering.required_source_read_set,false)\n'
                                     "   AND (v.visibility='private' OR "
                                     "engineering.visibility='category')\n"
                                     '   AND (v.project_id IS NULL OR EXISTS(SELECT 1 FROM '
                                     'public.project_product_links link WHERE link.tenant_id=t AND '
                                     'link.category_id=v.category_id\n'
                                     '    AND link.product_id=v.product_id AND '
                                     'link.project_id=v.project_id AND '
                                     'link.definition_id=engineering.definition_id AND '
                                     'link.definition_revision=engineering.definition_revision))) '
                                     'THEN\n'
                                     "   RAISE EXCEPTION 'Field location requires an actual "
                                     "engineering configuration in the selected project' USING "
                                     "ERRCODE='23514'; END IF;\n"
                                     '  IF '
                                     "coalesce(location->'manufacturing_configuration','null'::jsonb)<>'null'::jsonb "
                                     'AND NOT EXISTS(SELECT 1 FROM public.process_revisions '
                                     'manufacturing\n'
                                     '   WHERE manufacturing.tenant_id=t AND '
                                     'manufacturing.category_id=v.category_id AND '
                                     'manufacturing.product_id=v.product_id\n'
                                     '    AND '
                                     "manufacturing.id::text=location->'manufacturing_configuration'->>'id' "
                                     'AND '
                                     "manufacturing.revision::text=location->'manufacturing_configuration'->>'revision'\n"
                                     '    AND '
                                     "manufacturing.engineering_configuration_id::text=location->'engineering_configuration'->>'id'\n"
                                     '    AND coalesce(v.reads @> '
                                     'manufacturing.required_source_read_set,false) AND '
                                     "(v.visibility='private' OR manufacturing.visibility='category')) "
                                     'THEN\n'
                                     "   RAISE EXCEPTION 'Field manufacturing configuration must match "
                                     "actual engineering configuration' USING ERRCODE='23514'; END "
                                     'IF;\n'
                                     "  IF coalesce(location->'batch','null'::jsonb)<>'null'::jsonb "
                                     'AND NOT EXISTS(SELECT 1 FROM public.build_lots lot\n'
                                     '   JOIN public.actual_configurations actual ON '
                                     'actual.tenant_id=lot.tenant_id AND '
                                     'actual.product_id=lot.product_id AND '
                                     'actual.id=lot.actual_configuration_id\n'
                                     '   WHERE lot.tenant_id=t AND lot.category_id=v.category_id AND '
                                     'lot.product_id=v.product_id AND lot.project_id=v.project_id\n'
                                     "    AND lot.id::text=location->'batch'->>'id' AND "
                                     "lot.revision::text=location->'batch'->>'revision'\n"
                                     '    AND actual.revision=lot.actual_configuration_revision\n'
                                     '    AND '
                                     "actual.actual_engineering_configuration_id::text=location->'engineering_configuration'->>'id'\n"
                                     '    AND '
                                     "actual.actual_engineering_revision::text=location->'engineering_configuration'->>'revision'\n"
                                     '    AND '
                                     "actual.actual_manufacturing_configuration_id::text=location->'manufacturing_configuration'->>'id'\n"
                                     '    AND '
                                     "actual.actual_manufacturing_revision::text=location->'manufacturing_configuration'->>'revision'\n"
                                     "    AND (payload->>'project_id' IS NULL OR "
                                     "payload->>'project_id'=lot.project_id::text)\n"
                                     '    AND coalesce(v.reads @> lot.required_source_read_set,false) '
                                     'AND coalesce(v.reads @> actual.required_source_read_set,false)\n'
                                     "    AND (v.visibility='private' OR (lot.visibility='category' "
                                     "AND actual.visibility='category'))) THEN\n"
                                     "   RAISE EXCEPTION 'Field batch requires exact native lot and "
                                     "actual physical configuration' USING ERRCODE='23514'; END IF;\n"
                                     ' END IF;\n'
                                     'END;\n'
                                     '$function$\n',
 'assert_field_response(uuid,uuid)': 'CREATE OR REPLACE FUNCTION public.assert_field_response(t uuid, '
                                     'target uuid)\n'
                                     ' RETURNS void\n'
                                     ' LANGUAGE plpgsql\n'
                                     ' SECURITY DEFINER\n'
                                     " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                     'AS $function$\n'
                                     '\n'
                                     'DECLARE v public.field_response_records; parent '
                                     'public.field_feedback_versions; cur '
                                     'public.field_feedback_currents;\n'
                                     ' payload jsonb; expected jsonb; result jsonb; native_receipt '
                                     'public.action_receipts;\n'
                                     'BEGIN\n'
                                     ' SELECT * INTO STRICT v FROM public.field_response_records WHERE '
                                     'tenant_id=t AND id=target;\n'
                                     " PERFORM public.assert_field_common(t,target,'field_response');\n"
                                     ' SELECT * INTO STRICT parent FROM public.field_feedback_versions '
                                     'WHERE tenant_id=t AND category_id=v.category_id AND '
                                     'id=v.feedback_version_id;\n'
                                     ' SELECT * INTO STRICT cur FROM public.field_feedback_currents '
                                     'WHERE tenant_id=t AND category_id=v.category_id AND '
                                     'feedback_id=v.feedback_id;\n'
                                     " payload=v.command->'envelope'->'payload';\n"
                                     ' '
                                     "expected=jsonb_build_object('feedback',payload->'feedback','feedback_version_id',parent.id,'response_kind',v.response_kind,\n"
                                     '  '
                                     "'description',payload->'description','occurred_at',v.body->'occurred_at','result_receipts',coalesce(payload->'result_receipts','[]'::jsonb));\n"
                                     ' IF '
                                     'ROW(v.category_id,v.product_id,v.project_id,v.feedback_id,v.feedback_version_id,v.feedback_revision)\n'
                                     '  IS DISTINCT FROM '
                                     'ROW(parent.category_id,parent.product_id,parent.project_id,parent.feedback_id,parent.id,parent.revision)\n'
                                     '  OR cur.version_id<>parent.id OR cur.revision<>parent.revision\n'
                                     "  OR v.owner_id<>v.requester_id OR (parent.visibility='private' "
                                     "AND v.visibility<>'private')\n"
                                     "  OR payload->>'visibility' IS DISTINCT FROM v.visibility\n"
                                     "  OR payload->'feedback' IS DISTINCT FROM "
                                     "jsonb_build_object('id',parent.feedback_id,'revision',parent.revision)\n"
                                     '  OR v.body IS DISTINCT FROM expected OR v.sources IS DISTINCT '
                                     "FROM payload->'sources'\n"
                                     "  OR (v.body->>'occurred_at')::timestamptz IS DISTINCT FROM "
                                     "(payload->>'occurred_at')::timestamptz\n"
                                     '  OR '
                                     "coalesce(v.command->'review'->'before','null'::jsonb)<>'null'::jsonb\n"
                                     "  OR (v.operation='field.feedback.action.record' AND "
                                     "(payload->>'action_kind' IS DISTINCT FROM v.response_kind OR "
                                     "v.body->'result_receipts'<>'[]'::jsonb))\n"
                                     "  OR NOT coalesce(v.source_basis->'artifacts' @> "
                                     "parent.source_basis->'artifacts',false) THEN\n"
                                     "  RAISE EXCEPTION 'Field response binds exact current parent and "
                                     "new actual facts without advancing its report' USING "
                                     "ERRCODE='23514'; END IF;\n"
                                     " IF v.operation='field.feedback.followup.link' THEN\n"
                                     '  IF v.project_id IS NULL OR '
                                     "jsonb_array_length(payload->'result_receipts')=0\n"
                                     '   OR '
                                     "jsonb_array_length(v.source_basis->'result_receipts')<>jsonb_array_length(payload->'result_receipts')\n"
                                     '   OR EXISTS(SELECT 1 FROM '
                                     "jsonb_array_elements(v.source_basis->'result_receipts') result "
                                     "WHERE result->>'product_id' IS DISTINCT FROM v.product_id::text\n"
                                     "    OR result->>'project_id' IS DISTINCT FROM v.project_id::text "
                                     'OR NOT EXISTS(SELECT 1 FROM '
                                     "jsonb_array_elements(payload->'result_receipts') requested WHERE "
                                     "requested->'receipt_id'=result->'receipt_id')) THEN\n"
                                     "   RAISE EXCEPTION 'Field follow-up references only finite fixed "
                                     "native results in its actual project' USING ERRCODE='23514'; END "
                                     'IF;\n'
                                     '  FOR result IN SELECT value FROM '
                                     "jsonb_array_elements(v.source_basis->'result_receipts') LOOP\n"
                                     '   SELECT * INTO STRICT native_receipt FROM '
                                     'public.action_receipts r WHERE r.tenant_id=t AND '
                                     'r.category_id=v.category_id\n'
                                     "    AND r.id::text=result->>'receipt_id' AND "
                                     "r.product_id=v.product_id AND r.operation=result->>'operation'\n"
                                     "    AND r.subject_type=result->>'subject_type' AND "
                                     "r.subject_id::text=result->>'subject_id'\n"
                                     "    AND r.subject_revision::text=result->>'subject_revision' AND "
                                     "r.request_digest=result->>'receipt_request_digest'\n"
                                     "    AND r.visibility=result->>'receipt_visibility';\n"
                                     "   IF (v.visibility='category' AND "
                                     "(native_receipt.visibility<>'category' OR "
                                     "result->>'visibility'<>'category'\n"
                                     '     OR NOT EXISTS(SELECT 1 FROM public.products p WHERE '
                                     'p.tenant_id=t AND p.id=v.product_id AND '
                                     "p.visibility='category')\n"
                                     '     OR NOT EXISTS(SELECT 1 FROM public.projects p WHERE '
                                     'p.tenant_id=t AND p.id=v.project_id AND '
                                     "p.visibility='category')))\n"
                                     '    OR NOT EXISTS(SELECT 1 FROM public.audit_entries a WHERE '
                                     'a.tenant_id=t AND a.category_id=v.category_id AND '
                                     'a.receipt_id=native_receipt.id\n'
                                     '     AND a.actor_id=native_receipt.actor_id AND '
                                     'a.operation=native_receipt.operation)\n'
                                     '    OR NOT EXISTS(SELECT 1 FROM public.outbox_events e WHERE '
                                     'e.tenant_id=t AND e.category_id=v.category_id AND '
                                     'e.receipt_id=native_receipt.id\n'
                                     '     AND e.subject_id=native_receipt.subject_id AND '
                                     'e.subject_revision=native_receipt.subject_revision AND '
                                     'e.actor_id=native_receipt.actor_id\n'
                                     '     AND e.schema_version=1 AND '
                                     'e.correlation_id=coalesce(native_receipt.agent_run_id,native_receipt.run_id,native_receipt.command_id)) '
                                     'THEN\n'
                                     "    RAISE EXCEPTION 'Field follow-up requires actual native "
                                     "receipt audit event and audience' USING ERRCODE='23514'; END "
                                     'IF;\n'
                                     '  END LOOP;\n'
                                     ' END IF;\n'
                                     'END;\n'
                                     '$function$\n',
 'protect_field_receipt()': 'CREATE OR REPLACE FUNCTION public.protect_field_receipt()\n'
                            ' RETURNS trigger\n'
                            ' LANGUAGE plpgsql\n'
                            ' SECURITY DEFINER\n'
                            " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                            'AS $function$\n'
                            '\n'
                            'DECLARE scoped boolean=false;\n'
                            'BEGIN\n'
                            " IF TG_OP<>'INSERT' THEN scoped=OLD.operation IN "
                            "('field.feedback.create','field.feedback.locate','field.feedback.action.record','field.feedback.followup.link') "
                            "OR OLD.subject_type IN ('field_feedback','field_response'); END IF;\n"
                            " IF TG_OP<>'DELETE' THEN scoped=scoped OR NEW.operation IN "
                            "('field.feedback.create','field.feedback.locate','field.feedback.action.record','field.feedback.followup.link') "
                            "OR NEW.subject_type IN ('field_feedback','field_response'); END IF;\n"
                            " IF scoped AND TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Field receipt "
                            "history is immutable' USING ERRCODE='23514'; END IF;\n"
                            " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
                            'END;\n'
                            '$function$\n',
 'protect_field_member()': 'CREATE OR REPLACE FUNCTION public.protect_field_member()\n'
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
                           "('field.feedback.create','field.feedback.locate','field.feedback.action.record','field.feedback.followup.link') "
                           "OR r.subject_type IN ('field_feedback','field_response'))) INTO scoped; "
                           'END IF;\n'
                           " IF TG_OP<>'INSERT' THEN SELECT EXISTS(SELECT 1 FROM "
                           'public.action_receipts r WHERE r.tenant_id=OLD.tenant_id AND '
                           'r.id=OLD.receipt_id AND (r.operation IN '
                           "('field.feedback.create','field.feedback.locate','field.feedback.action.record','field.feedback.followup.link') "
                           "OR r.subject_type IN ('field_feedback','field_response'))) INTO "
                           'old_scoped; END IF;\n'
                           " IF TG_OP<>'INSERT' AND (scoped OR old_scoped) THEN\n"
                           "  IF TG_OP='UPDATE' AND TG_TABLE_NAME='outbox_events' AND "
                           "(to_jsonb(NEW)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) "
                           'IS NOT DISTINCT FROM '
                           "(to_jsonb(OLD)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) "
                           'THEN RETURN NEW; END IF;\n'
                           "  RAISE EXCEPTION 'Field original audit event or request key is immutable' "
                           "USING ERRCODE='23514'; END IF;\n"
                           " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
                           'END;\n'
                           '$function$\n',
 'require_field_member()': 'CREATE OR REPLACE FUNCTION public.require_field_member()\n'
                           ' RETURNS trigger\n'
                           ' LANGUAGE plpgsql\n'
                           ' SECURITY DEFINER\n'
                           " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                           'AS $function$\n'
                           '\n'
                           'DECLARE receipt public.action_receipts;\n'
                           'BEGIN\n'
                           " IF TG_TABLE_NAME='action_receipts' THEN receipt=NEW; ELSE SELECT * INTO "
                           'receipt FROM public.action_receipts WHERE tenant_id=NEW.tenant_id AND '
                           'id=NEW.receipt_id; END IF;\n'
                           ' IF receipt.operation IN '
                           "('field.feedback.create','field.feedback.locate','field.feedback.action.record','field.feedback.followup.link') "
                           "OR receipt.subject_type IN ('field_feedback','field_response') THEN\n"
                           '  PERFORM '
                           'public.assert_field_members(receipt.tenant_id,receipt.subject_id,receipt.subject_type::text); '
                           'END IF;\n'
                           ' RETURN NULL;\n'
                           'END;\n'
                           '$function$\n',
 'protect_field_confirmation()': 'CREATE OR REPLACE FUNCTION public.protect_field_confirmation()\n'
                                 ' RETURNS trigger\n'
                                 ' LANGUAGE plpgsql\n'
                                 ' SECURITY DEFINER\n'
                                 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                 'AS $function$\n'
                                 '\n'
                                 'DECLARE old_scoped boolean=false; new_scoped boolean=false;\n'
                                 'BEGIN\n'
                                 " IF TG_OP<>'INSERT' THEN old_scoped=OLD.operation IN "
                                 "('field.feedback.locate','field.feedback.action.record','field.feedback.followup.link'); "
                                 'END IF;\n'
                                 " IF TG_OP<>'DELETE' THEN new_scoped=NEW.operation IN "
                                 "('field.feedback.locate','field.feedback.action.record','field.feedback.followup.link'); "
                                 'END IF;\n'
                                 ' IF old_scoped OR new_scoped THEN\n'
                                 "  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Field confirmation history "
                                 "retained' USING ERRCODE='23514';\n"
                                 "  ELSIF TG_OP='INSERT' THEN\n"
                                 '   IF NEW.consumed IS DISTINCT FROM false THEN RAISE EXCEPTION '
                                 "'Field T1 starts unconsumed' USING ERRCODE='23514'; END IF;\n"
                                 '  ELSIF NOT(old_scoped AND new_scoped) OR OLD.consumed IS DISTINCT '
                                 'FROM false OR NEW.consumed IS DISTINCT FROM true\n'
                                 "   OR (to_jsonb(NEW)-'consumed') IS DISTINCT FROM "
                                 "(to_jsonb(OLD)-'consumed') THEN\n"
                                 "   RAISE EXCEPTION 'Field confirmation consumes only its original "
                                 "false to true' USING ERRCODE='23514'; END IF;\n"
                                 ' END IF;\n'
                                 " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
                                 'END;\n'
                                 '$function$\n',
 'require_field_confirmation()': 'CREATE OR REPLACE FUNCTION public.require_field_confirmation()\n'
                                 ' RETURNS trigger\n'
                                 ' LANGUAGE plpgsql\n'
                                 ' SECURITY DEFINER\n'
                                 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                 'AS $function$\n'
                                 '\n'
                                 'BEGIN\n'
                                 ' IF NEW.operation IN '
                                 "('field.feedback.locate','field.feedback.action.record','field.feedback.followup.link') "
                                 'THEN\n'
                                 '  IF OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT '
                                 'FROM true\n'
                                 '   OR (SELECT count(*) FROM (SELECT confirmation_id FROM '
                                 'public.field_feedback_versions v WHERE v.tenant_id=NEW.tenant_id AND '
                                 'v.confirmation_id=NEW.id AND v.operation=NEW.operation\n'
                                 '    UNION ALL SELECT confirmation_id FROM '
                                 'public.field_response_records v WHERE v.tenant_id=NEW.tenant_id AND '
                                 'v.confirmation_id=NEW.id AND v.operation=NEW.operation) refs)<>1 '
                                 'THEN\n'
                                 "   RAISE EXCEPTION 'Consumed Field T1 proof requires exactly one new "
                                 "fact' USING ERRCODE='23514'; END IF;\n"
                                 ' END IF;\n'
                                 ' RETURN NULL;\n'
                                 'END;\n'
                                 '$function$\n',
 'field_receipt_visible(uuid,uuid,uuid,text,uuid,integer,uuid,uuid)': 'CREATE OR REPLACE FUNCTION '
                                                                      'public.field_receipt_visible(t '
                                                                      'uuid, c uuid, p uuid, kind '
                                                                      'text, target uuid, rev integer, '
                                                                      'receipt uuid, actor uuid)\n'
                                                                      ' RETURNS boolean\n'
                                                                      ' LANGUAGE plpgsql\n'
                                                                      ' STABLE\n'
                                                                      ' SET search_path TO '
                                                                      "'pg_catalog', 'public', "
                                                                      "'pg_temp'\n"
                                                                      'AS $function$\n'
                                                                      '\n'
                                                                      'BEGIN\n'
                                                                      ' IF kind NOT IN '
                                                                      "('field_feedback','field_response') "
                                                                      'THEN RETURN true; END IF;\n'
                                                                      ' IF NOT '
                                                                      'public.category_access(t,c) '
                                                                      'THEN RETURN false; END IF;\n'
                                                                      " IF kind='field_feedback' THEN "
                                                                      'RETURN EXISTS(SELECT 1 FROM '
                                                                      'public.field_feedback_versions '
                                                                      'f WHERE f.tenant_id=t AND '
                                                                      'f.category_id=c\n'
                                                                      '  AND f.product_id IS NOT '
                                                                      'DISTINCT FROM p AND f.id=target '
                                                                      'AND f.revision=rev AND '
                                                                      'f.receipt_id=receipt AND '
                                                                      'f.actor_id=actor\n'
                                                                      '  AND f.operation IN '
                                                                      "('field.feedback.create','field.feedback.locate'));\n"
                                                                      " ELSIF kind='field_response' "
                                                                      'THEN RETURN EXISTS(SELECT 1 '
                                                                      'FROM '
                                                                      'public.field_response_records f '
                                                                      'WHERE f.tenant_id=t AND '
                                                                      'f.category_id=c\n'
                                                                      '  AND f.product_id IS NOT '
                                                                      'DISTINCT FROM p AND f.id=target '
                                                                      'AND f.revision=rev AND '
                                                                      'f.receipt_id=receipt AND '
                                                                      'f.actor_id=actor\n'
                                                                      '  AND f.operation IN '
                                                                      "('field.feedback.action.record','field.feedback.followup.link')); "
                                                                      'END IF;\n'
                                                                      ' RETURN false;\n'
                                                                      'END;\n'
                                                                      '$function$\n'}

SCHEMA_SQL = ('\n'
 'CREATE TABLE field_feedback_versions (\n'
 '\tfeedback_id UUID NOT NULL, \n'
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
 '\tUNIQUE (tenant_id, category_id, feedback_id, revision), \n'
 '\tUNIQUE (tenant_id, category_id, feedback_id, id, revision), \n'
 '\tFOREIGN KEY(tenant_id, category_id, feedback_id, previous_id, previous_revision) REFERENCES '
 'field_feedback_versions (tenant_id, category_id, feedback_id, id, revision), \n'
 '\tCONSTRAINT field_feedback_chain CHECK ((revision=1 AND feedback_id=id AND previous_id IS NULL AND '
 'previous_revision IS NULL) OR (revision>1 AND previous_id IS NOT NULL AND previous_id<>id AND '
 'previous_revision=revision-1)), \n'
 "\tCONSTRAINT field_feedback_operation CHECK ((operation='field.feedback.create' AND revision=1 AND "
 "confirmation_id IS NULL) OR (operation='field.feedback.locate' AND revision>1 AND confirmation_id IS "
 'NOT NULL))\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_field_feedback_versions_category_id ON field_feedback_versions (category_id)',
 'CREATE INDEX ix_field_feedback_versions_tenant_id ON field_feedback_versions (tenant_id)',
 '\n'
 'CREATE TABLE field_feedback_currents (\n'
 '\tfeedback_id UUID NOT NULL, \n'
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
 '\tUNIQUE (tenant_id, category_id, feedback_id), \n'
 '\tFOREIGN KEY(tenant_id, category_id, feedback_id, version_id, revision) REFERENCES '
 'field_feedback_versions (tenant_id, category_id, feedback_id, id, revision), \n'
 '\tCONSTRAINT field_feedback_current_revision CHECK (revision>0)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_field_feedback_currents_category_id ON field_feedback_currents (category_id)',
 'CREATE INDEX ix_field_feedback_currents_tenant_id ON field_feedback_currents (tenant_id)',
 '\n'
 'CREATE TABLE field_response_records (\n'
 '\tfeedback_id UUID NOT NULL, \n'
 '\tfeedback_version_id UUID NOT NULL, \n'
 '\tfeedback_revision INTEGER NOT NULL, \n'
 '\tresponse_kind VARCHAR(24) NOT NULL, \n'
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
 '\tFOREIGN KEY(tenant_id, category_id, feedback_id, feedback_version_id, feedback_revision) '
 'REFERENCES field_feedback_versions (tenant_id, category_id, feedback_id, id, revision), \n'
 '\tCHECK (revision=1 AND feedback_revision>0 AND confirmation_id IS NOT NULL), \n'
 "\tCONSTRAINT field_response_operation CHECK ((operation='field.feedback.action.record' AND "
 "response_kind IN ('containment','improvement')) OR (operation='field.feedback.followup.link' AND "
 "response_kind='followup'))\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_field_response_records_category_id ON field_response_records (category_id)',
 'CREATE INDEX ix_field_response_records_tenant_id ON field_response_records (tenant_id)',
 'CREATE FUNCTION public.reject_field_mutation() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $field$\n'
 "BEGIN RAISE EXCEPTION 'Field facts are immutable' USING ERRCODE='23514'; END;\n"
 '$field$',
 'CREATE FUNCTION public.protect_field_current() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $field$\n'
 '\n'
 'BEGIN\n'
 " IF TG_OP='INSERT' AND NEW.revision=1 THEN RETURN NEW;\n"
 " ELSIF TG_OP='UPDATE'\n"
 "  AND (to_jsonb(NEW)-ARRAY['version_id','revision','product_id','project_id']) IS NOT DISTINCT FROM "
 "(to_jsonb(OLD)-ARRAY['version_id','revision','product_id','project_id'])\n"
 '  AND NEW.revision=OLD.revision+1 AND (OLD.product_id IS NULL OR NEW.product_id=OLD.product_id)\n'
 '  AND EXISTS(SELECT 1 FROM public.field_feedback_versions v WHERE v.tenant_id=NEW.tenant_id AND '
 'v.id=NEW.version_id\n'
 '   AND v.revision=NEW.revision AND v.previous_id=OLD.version_id AND '
 'v.previous_revision=OLD.revision\n'
 "   AND v.operation='field.feedback.locate' AND v.product_id=NEW.product_id AND v.project_id IS NOT "
 'DISTINCT FROM NEW.project_id)\n'
 ' THEN RETURN NEW; END IF;\n'
 " RAISE EXCEPTION 'Field Current requires an exact single-step location CAS' USING ERRCODE='23514';\n"
 'END;\n'
 '$field$',
 'CREATE FUNCTION public.require_field_current() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $field$\n'
 '\n'
 'DECLARE cur public.field_feedback_currents; fixed public.field_feedback_versions; cx xid; vx xid;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT cur FROM public.field_feedback_currents WHERE tenant_id=NEW.tenant_id AND '
 'id=NEW.id;\n'
 ' SELECT xmin INTO cx FROM public.field_feedback_currents WHERE tenant_id=NEW.tenant_id AND '
 'id=NEW.id;\n'
 ' SELECT * INTO STRICT fixed FROM public.field_feedback_versions WHERE tenant_id=NEW.tenant_id AND '
 'id=cur.version_id;\n'
 ' SELECT xmin INTO vx FROM public.field_feedback_versions WHERE tenant_id=NEW.tenant_id AND '
 'id=cur.version_id;\n'
 ' IF vx IS DISTINCT FROM cx OR '
 'ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.feedback_id,cur.version_id,cur.revision)\n'
 '  IS DISTINCT FROM '
 'ROW(fixed.category_id,fixed.product_id,fixed.project_id,fixed.owner_id,fixed.visibility,fixed.feedback_id,fixed.id,fixed.revision) '
 'THEN\n'
 "  RAISE EXCEPTION 'Field Current requires its exact same-transaction version' USING ERRCODE='23514'; "
 'END IF;\n'
 ' RETURN NULL;\n'
 'END;\n'
 '$field$',
 'CREATE FUNCTION public.assert_field_members(t uuid,target uuid,kind text) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $field$\n'
 '\n'
 'DECLARE v record; r public.action_receipts; proof public.confirmations; expected jsonb; event_name '
 'text;\n'
 'BEGIN\n'
 '\n'
 " IF kind='field_feedback' THEN SELECT x.*,x.xmin AS tx INTO STRICT v FROM "
 'public.field_feedback_versions x WHERE x.tenant_id=t AND x.id=target;\n'
 " ELSIF kind='field_response' THEN SELECT x.*,x.xmin AS tx INTO STRICT v FROM "
 'public.field_response_records x WHERE x.tenant_id=t AND x.id=target;\n'
 " ELSE RAISE EXCEPTION 'Unknown Field subject' USING ERRCODE='23514'; END IF;\n"
 '\n'
 " expected=jsonb_build_object('id',v.id,'revision',v.revision,'status',CASE WHEN "
 "kind='field_response' THEN 'recorded' WHEN v.body->'location' IS NOT NULL AND "
 "v.body->'location'<>'null'::jsonb THEN 'located' ELSE 'unknown' END,\n"
 "  'feedback_id',v.feedback_id,'project_id',v.project_id);\n"
 " event_name=CASE v.operation WHEN 'field.feedback.create' THEN 'field.feedback_created' WHEN "
 "'field.feedback.locate' THEN 'field.feedback_located'\n"
 "  WHEN 'field.feedback.action.record' THEN 'field.feedback_action_recorded' WHEN "
 "'field.feedback.followup.link' THEN 'field.feedback_followup_linked' END;\n"
 ' SELECT * INTO STRICT r FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;\n'
 ' IF '
 'ROW(r.category_id,r.product_id,r.command_id,r.confirmation_id,r.actor_id,r.requester_id,r.operation,r.subject_type,r.subject_id,r.subject_revision,r.visibility,r.request_digest,r.intent_digest)\n'
 '  IS DISTINCT FROM '
 'ROW(v.category_id,v.product_id,v.command_id,v.confirmation_id,v.actor_id,v.requester_id,v.operation,kind::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)\n'
 '  OR r.result IS DISTINCT FROM expected OR r.created_at<v.created_at OR event_name IS NULL\n'
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
 'x.correlation_id=coalesce(r.agent_run_id,r.run_id,v.command_id) AND x.created_at>=v.created_at)\n'
 "  OR v.command->>'original_key_sha256' IS NULL OR v.command->>'original_key_sha256' !~ "
 "'^[a-f0-9]{64}$'\n"
 "  OR v.command->'envelope' ? 'idempotency_key' OR v.command->'envelope'->'payload' ? "
 "'confirmation_token'\n"
 "  OR v.command->'envelope'->'payload' ? 'approval_token'\n"
 '  OR NOT EXISTS(SELECT 1 FROM public.request_keys x WHERE x.tenant_id=t AND '
 'x.category_id=v.category_id AND x.receipt_id=v.receipt_id AND x.actor_id=v.actor_id AND '
 'x.digest=v.request_digest AND '
 "encode(sha256(convert_to(x.key,'UTF8')),'hex')=v.command->>'original_key_sha256') THEN\n"
 "  RAISE EXCEPTION 'Field original receipt audit event or request key mismatch' USING "
 "ERRCODE='23514'; END IF;\n"
 " IF v.operation<>'field.feedback.create' THEN\n"
 '  SELECT * INTO STRICT proof FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;\n'
 '  IF proof.consumed IS DISTINCT FROM true OR '
 'ROW(proof.category_id,proof.product_id,proof.actor_id,proof.operation,proof.subject_type,proof.subject_id,proof.revision)\n'
 '   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.actor_id,v.operation,(CASE WHEN v.product_id IS '
 "NULL THEN 'category' ELSE 'product' "
 "END)::varchar,coalesce(v.product_id,v.category_id),(v.command->'envelope'->>'expected_revision')::integer)\n"
 "   OR proof.snapshot IS DISTINCT FROM v.command->'review' OR proof.created_at>v.created_at OR "
 'proof.expires_at IS NULL\n'
 '   OR v.created_at>=proof.expires_at OR r.created_at>=proof.expires_at OR '
 'v.actor_id<>v.requester_id\n'
 '   OR r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL THEN\n'
 "   RAISE EXCEPTION 'Field T1 requires its actual consumed human confirmation' USING ERRCODE='23514'; "
 'END IF;\n'
 ' END IF;\n'
 'END;\n'
 '$field$',
 'CREATE FUNCTION public.assert_field_common(t uuid,target uuid,kind text) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $field$\n'
 '\n'
 'DECLARE v record; envelope jsonb; vx xid; rx xid; px xid; ref jsonb; basis jsonb; active_sources '
 'jsonb;\n'
 'BEGIN\n'
 '\n'
 " IF kind='field_feedback' THEN SELECT x.*,x.xmin AS tx INTO STRICT v FROM "
 'public.field_feedback_versions x WHERE x.tenant_id=t AND x.id=target;\n'
 " ELSIF kind='field_response' THEN SELECT x.*,x.xmin AS tx INTO STRICT v FROM "
 'public.field_response_records x WHERE x.tenant_id=t AND x.id=target;\n'
 " ELSE RAISE EXCEPTION 'Unknown Field subject' USING ERRCODE='23514'; END IF;\n"
 '\n'
 ' vx=v.tx;\n'
 ' SELECT xmin INTO rx FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;\n'
 ' PERFORM public.assert_field_members(t,target,kind);\n'
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
 "  OR v.command->'review'->'declaration' IS DISTINCT FROM envelope->'payload'\n"
 "  OR v.command->'review'->>'operation' IS DISTINCT FROM v.operation\n"
 "  OR v.command->'review'->'sources' IS DISTINCT FROM envelope->'payload'->'sources'\n"
 "  OR v.command->'review'->'source_basis' IS DISTINCT FROM v.source_basis OR v.body IS DISTINCT FROM "
 "v.command->'review'->'after'\n"
 '  OR (v.product_id IS NULL AND NOT EXISTS(SELECT 1 FROM public.categories c WHERE c.tenant_id=t AND '
 "c.id=v.category_id AND c.revision::text=envelope->>'expected_revision'))\n"
 '  OR (v.product_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id=t '
 'AND p.category_id=v.category_id AND p.id=v.product_id AND '
 "p.revision::text=envelope->>'expected_revision'))\n"
 '  OR (v.project_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=t '
 'AND p.category_id=v.category_id AND p.product_id=v.product_id AND p.id=v.project_id))\n'
 "  OR NOT coalesce(envelope->'source_read_set' @> v.reads,false) OR NOT coalesce(v.reads @> "
 "(envelope->'source_read_set'),false)\n"
 "  OR jsonb_array_length(envelope->'source_read_set')<>jsonb_array_length(v.reads)\n"
 '  OR NOT public.direct_source_set_visible(t,v.category_id,v.product_id,v.reads)\n'
 '  OR NOT public.knowledge_content_sources_visible(t,v.category_id,v.product_id,v.source_basis)\n'
 '  OR NOT public.knowledge_result_sources_visible(t,v.category_id,v.product_id,v.source_basis)\n'
 '  OR (v.actor_id<>v.requester_id AND NOT EXISTS(SELECT 1 FROM public.action_receipts r WHERE '
 'r.tenant_id=t AND r.id=v.receipt_id AND coalesce(r.agent_run_id,r.run_id) IS NOT NULL))\n'
 '  OR EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id '
 'AND x.xmin IS DISTINCT FROM vx)\n'
 '  OR EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id '
 'AND x.xmin IS DISTINCT FROM vx)\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.request_keys x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id AND x.actor_id=v.actor_id AND x.digest=v.request_digest AND x.xmin=vx AND '
 "encode(sha256(convert_to(x.key,'UTF8')),'hex')=v.command->>'original_key_sha256') THEN\n"
 "  RAISE EXCEPTION 'Field requires actual scope actor sources and one common transaction' USING "
 "ERRCODE='23514'; END IF;\n"
 ' IF v.confirmation_id IS NOT NULL THEN\n'
 '  SELECT xmin INTO px FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;\n'
 "  IF px IS DISTINCT FROM vx THEN RAISE EXCEPTION 'Field T1 consumption shares its new fact "
 "transaction' USING ERRCODE='23514'; END IF;\n"
 ' END IF;\n'
 " IF jsonb_typeof(v.source_basis->'artifacts') IS DISTINCT FROM 'array' THEN\n"
 "  RAISE EXCEPTION 'Field requires actual direct-source metadata' USING ERRCODE='23514'; END IF;\n"
 " FOR basis IN SELECT value FROM jsonb_array_elements(v.source_basis->'artifacts') LOOP\n"
 '  IF NOT EXISTS(SELECT 1 FROM public.artifact_versions a WHERE a.tenant_id=t AND '
 'a.category_id=v.category_id\n'
 "   AND a.product_id::text IS NOT DISTINCT FROM basis->>'product_id' AND a.id::text=basis->>'id'\n"
 "   AND a.revision::text=basis->>'revision' AND a.content_hash=basis->>'hash'\n"
 "   AND (v.visibility='private' OR (a.visibility='category' AND (a.product_id IS NULL OR "
 'EXISTS(SELECT 1 FROM public.products source_product\n'
 '    WHERE source_product.tenant_id=t AND source_product.category_id=v.category_id AND '
 "source_product.id=a.product_id AND source_product.visibility='category'))))\n"
 "   AND (a.original_id IS NULL OR v.visibility='private' OR EXISTS(SELECT 1 FROM "
 'public.uploaded_originals o\n'
 "    WHERE o.tenant_id=t AND o.id=a.original_id AND o.visibility='category'))) THEN\n"
 "   RAISE EXCEPTION 'Field historical source hash or actual audience changed' USING ERRCODE='23514'; "
 'END IF;\n'
 ' END LOOP;\n'
 " active_sources=CASE WHEN kind='field_feedback' THEN v.sources ELSE envelope->'payload'->'sources' "
 'END;\n'
 " IF v.operation='field.feedback.followup.link' THEN\n"
 '  active_sources=active_sources||coalesce((SELECT jsonb_agg(content.value) FROM '
 "jsonb_array_elements(v.source_basis->'result_receipts') result,\n"
 "   LATERAL jsonb_array_elements(result->'direct_content_refs') content),'[]'::jsonb);\n"
 ' END IF;\n'
 ' FOR ref IN SELECT value FROM jsonb_array_elements(active_sources) LOOP\n'
 "  SELECT value INTO STRICT basis FROM jsonb_array_elements(v.source_basis->'artifacts') WHERE "
 "value->>'id'=ref->>'id';\n"
 "  IF ref->>'kind' IS DISTINCT FROM 'artifact' OR NOT EXISTS(SELECT 1 FROM "
 "jsonb_array_elements(v.reads) rd WHERE rd->>'artifact_id'=ref->>'id' AND "
 "rd->'expected_revision'=ref->'revision')\n"
 '   OR NOT EXISTS(SELECT 1 FROM public.artifact_versions a WHERE a.tenant_id=t AND '
 'a.category_id=v.category_id\n'
 "    AND a.id::text=ref->>'id' AND a.revision::text=ref->>'revision' AND a.status='active'\n"
 "    AND a.product_id::text IS NOT DISTINCT FROM basis->>'product_id' AND "
 "a.revision::text=basis->>'revision'\n"
 "    AND a.content_hash=basis->>'hash' AND a.status=basis->>'status' AND "
 "a.owner_id::text=basis->>'owner_id' AND a.visibility=basis->>'visibility'\n"
 "    AND ((a.original_id IS NULL AND basis->>'source_kind'='registered_native_text' AND EXISTS(SELECT "
 '1 FROM public.action_receipts r\n'
 '      WHERE r.tenant_id=t AND r.subject_id=a.id AND r.subject_revision=a.revision AND '
 "r.subject_type='artifact' AND r.operation='evidence.artifact.register'\n"
 "       AND r.id::text=basis->'registration'->>'receipt_id' AND "
 "r.actor_id::text=basis->'registration'->>'actor_id'\n"
 "       AND r.requester_id::text=basis->'registration'->>'requester_id' AND r.run_id::text IS NOT "
 "DISTINCT FROM basis->'registration'->>'run_id'))\n"
 "     OR (a.original_id IS NOT NULL AND basis->>'source_kind'='uploaded_original' AND EXISTS(SELECT 1 "
 'FROM public.uploaded_originals o\n'
 '      JOIN public.original_security sec ON sec.tenant_id=o.tenant_id AND sec.original_id=o.id WHERE '
 'o.tenant_id=t AND o.category_id=v.category_id\n'
 "       AND o.id=a.original_id AND o.id::text=basis->'original'->>'id' AND o.status='parsed' AND "
 "sec.epoch::text=basis->'original'->>'epoch'\n"
 "       AND sec.source_state='active' AND sec.disposition='active' AND "
 "sec.source_state=basis->'original'->>'source_state'\n"
 "       AND sec.disposition=basis->'original'->>'disposition')))) THEN\n"
 "   RAISE EXCEPTION 'Field newly adopted direct source metadata changed' USING ERRCODE='23514'; END "
 'IF;\n'
 ' END LOOP;\n'
 'END;\n'
 '$field$',
 'CREATE FUNCTION public.assert_field_feedback(t uuid,target uuid) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $field$\n'
 '\n'
 'DECLARE v public.field_feedback_versions; prior public.field_feedback_versions; cur '
 'public.field_feedback_currents;\n'
 ' payload jsonb; expected jsonb; location jsonb; vx xid; cx xid;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT v FROM public.field_feedback_versions WHERE tenant_id=t AND id=target;\n'
 ' SELECT xmin INTO vx FROM public.field_feedback_versions WHERE tenant_id=t AND id=target;\n'
 " PERFORM public.assert_field_common(t,target,'field_feedback');\n"
 ' SELECT * INTO STRICT cur FROM public.field_feedback_currents WHERE tenant_id=t AND '
 'category_id=v.category_id AND feedback_id=v.feedback_id;\n'
 ' SELECT xmin INTO cx FROM public.field_feedback_currents WHERE tenant_id=t AND id=cur.id;\n'
 " payload=v.command->'envelope'->'payload';\n"
 ' IF vx IS DISTINCT FROM cx OR '
 'ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.feedback_id,cur.version_id,cur.revision)\n'
 '  IS DISTINCT FROM '
 'ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.feedback_id,v.id,v.revision)\n'
 "  OR v.owner_id<>v.requester_id THEN RAISE EXCEPTION 'Field feedback binds actual owner and "
 "same-transaction Current' USING ERRCODE='23514'; END IF;\n"
 " IF v.operation='field.feedback.create' THEN\n"
 '  '
 "expected=jsonb_build_object('feedback_id',v.feedback_id,'revision',1,'title',payload->'title','description',payload->'description',\n"
 '   '
 "'channel',payload->'channel','feedback_kind',payload->'feedback_kind','received_at',payload->'received_at','reported',payload->'reported','purpose',payload->'purpose','location',NULL);\n"
 "  IF v.body IS DISTINCT FROM expected OR v.sources IS DISTINCT FROM payload->'sources' OR "
 'v.project_id IS NOT NULL\n'
 "   OR payload->>'visibility' IS DISTINCT FROM v.visibility OR "
 "coalesce(v.command->'review'->'before','null'::jsonb)<>'null'::jsonb THEN\n"
 "   RAISE EXCEPTION 'Field intake records only its actual declared source report, with unknown "
 "location' USING ERRCODE='23514'; END IF;\n"
 ' ELSE\n'
 '  SELECT * INTO STRICT prior FROM public.field_feedback_versions WHERE tenant_id=t AND '
 'id=v.previous_id;\n'
 "  location=v.body->'location';\n"
 '  IF ROW(v.category_id,v.owner_id,v.visibility,v.feedback_id) IS DISTINCT FROM '
 'ROW(prior.category_id,prior.owner_id,prior.visibility,prior.feedback_id)\n'
 '   OR (prior.product_id IS NOT NULL AND prior.product_id IS DISTINCT FROM v.product_id)\n'
 "   OR v.product_id IS NULL OR payload->'feedback' IS DISTINCT FROM "
 "jsonb_build_object('id',v.feedback_id,'revision',prior.revision)\n"
 "   OR v.command->'review'->'before' IS DISTINCT FROM prior.body\n"
 "   OR (v.body-ARRAY['revision','location']) IS DISTINCT FROM "
 "(prior.body-ARRAY['revision','location'])\n"
 "   OR v.body->'revision' IS DISTINCT FROM to_jsonb(v.revision)\n"
 "   OR jsonb_typeof(location) IS DISTINCT FROM 'object' OR location->>'state' IS DISTINCT FROM "
 "'known'\n"
 "   OR location->>'product_id' IS DISTINCT FROM v.product_id::text OR location->>'project_id' IS "
 'DISTINCT FROM v.project_id::text\n'
 "   OR location->'engineering_configuration' IS DISTINCT FROM payload->'engineering_configuration'\n"
 "   OR location->'manufacturing_configuration' IS DISTINCT FROM "
 "payload->'manufacturing_configuration'\n"
 "   OR location->'batch' IS DISTINCT FROM payload->'batch'\n"
 "   OR (coalesce(payload->'batch','null'::jsonb)='null'::jsonb AND payload->>'project_id' IS DISTINCT "
 'FROM v.project_id::text)\n'
 '   OR NOT coalesce(v.sources @> prior.sources,false) OR NOT coalesce(v.sources @> '
 "payload->'sources',false)\n"
 "   OR NOT coalesce(v.sources @> location->'sources',false)\n"
 '   OR EXISTS(SELECT 1 FROM jsonb_array_elements(v.sources) source WHERE NOT(prior.sources @> '
 'jsonb_build_array(source)\n'
 "    OR payload->'sources' @> jsonb_build_array(source) OR location->'sources' @> "
 'jsonb_build_array(source))) THEN\n'
 "   RAISE EXCEPTION 'Field location preserves report, privacy and exact predecessor; known product "
 "cannot silently change' USING ERRCODE='23514'; END IF;\n"
 '  IF NOT EXISTS(SELECT 1 FROM public.engineering_configurations engineering WHERE '
 'engineering.tenant_id=t AND engineering.category_id=v.category_id\n'
 '   AND engineering.product_id=v.product_id AND '
 "engineering.id::text=location->'engineering_configuration'->>'id'\n"
 "   AND engineering.revision::text=location->'engineering_configuration'->>'revision'\n"
 '   AND coalesce(v.reads @> engineering.required_source_read_set,false)\n'
 "   AND (v.visibility='private' OR engineering.visibility='category')\n"
 '   AND (v.project_id IS NULL OR EXISTS(SELECT 1 FROM public.project_product_links link WHERE '
 'link.tenant_id=t AND link.category_id=v.category_id\n'
 '    AND link.product_id=v.product_id AND link.project_id=v.project_id AND '
 'link.definition_id=engineering.definition_id AND '
 'link.definition_revision=engineering.definition_revision))) THEN\n'
 "   RAISE EXCEPTION 'Field location requires an actual engineering configuration in the selected "
 "project' USING ERRCODE='23514'; END IF;\n"
 "  IF coalesce(location->'manufacturing_configuration','null'::jsonb)<>'null'::jsonb AND NOT "
 'EXISTS(SELECT 1 FROM public.process_revisions manufacturing\n'
 '   WHERE manufacturing.tenant_id=t AND manufacturing.category_id=v.category_id AND '
 'manufacturing.product_id=v.product_id\n'
 "    AND manufacturing.id::text=location->'manufacturing_configuration'->>'id' AND "
 "manufacturing.revision::text=location->'manufacturing_configuration'->>'revision'\n"
 '    AND '
 "manufacturing.engineering_configuration_id::text=location->'engineering_configuration'->>'id'\n"
 '    AND coalesce(v.reads @> manufacturing.required_source_read_set,false) AND '
 "(v.visibility='private' OR manufacturing.visibility='category')) THEN\n"
 "   RAISE EXCEPTION 'Field manufacturing configuration must match actual engineering configuration' "
 "USING ERRCODE='23514'; END IF;\n"
 "  IF coalesce(location->'batch','null'::jsonb)<>'null'::jsonb AND NOT EXISTS(SELECT 1 FROM "
 'public.build_lots lot\n'
 '   JOIN public.actual_configurations actual ON actual.tenant_id=lot.tenant_id AND '
 'actual.product_id=lot.product_id AND actual.id=lot.actual_configuration_id\n'
 '   WHERE lot.tenant_id=t AND lot.category_id=v.category_id AND lot.product_id=v.product_id AND '
 'lot.project_id=v.project_id\n'
 "    AND lot.id::text=location->'batch'->>'id' AND lot.revision::text=location->'batch'->>'revision'\n"
 '    AND actual.revision=lot.actual_configuration_revision\n'
 '    AND '
 "actual.actual_engineering_configuration_id::text=location->'engineering_configuration'->>'id'\n"
 "    AND actual.actual_engineering_revision::text=location->'engineering_configuration'->>'revision'\n"
 '    AND '
 "actual.actual_manufacturing_configuration_id::text=location->'manufacturing_configuration'->>'id'\n"
 '    AND '
 "actual.actual_manufacturing_revision::text=location->'manufacturing_configuration'->>'revision'\n"
 "    AND (payload->>'project_id' IS NULL OR payload->>'project_id'=lot.project_id::text)\n"
 '    AND coalesce(v.reads @> lot.required_source_read_set,false) AND coalesce(v.reads @> '
 'actual.required_source_read_set,false)\n'
 "    AND (v.visibility='private' OR (lot.visibility='category' AND actual.visibility='category'))) "
 'THEN\n'
 "   RAISE EXCEPTION 'Field batch requires exact native lot and actual physical configuration' USING "
 "ERRCODE='23514'; END IF;\n"
 ' END IF;\n'
 'END;\n'
 '$field$',
 'CREATE FUNCTION public.assert_field_response(t uuid,target uuid) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $field$\n'
 '\n'
 'DECLARE v public.field_response_records; parent public.field_feedback_versions; cur '
 'public.field_feedback_currents;\n'
 ' payload jsonb; expected jsonb; result jsonb; native_receipt public.action_receipts;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT v FROM public.field_response_records WHERE tenant_id=t AND id=target;\n'
 " PERFORM public.assert_field_common(t,target,'field_response');\n"
 ' SELECT * INTO STRICT parent FROM public.field_feedback_versions WHERE tenant_id=t AND '
 'category_id=v.category_id AND id=v.feedback_version_id;\n'
 ' SELECT * INTO STRICT cur FROM public.field_feedback_currents WHERE tenant_id=t AND '
 'category_id=v.category_id AND feedback_id=v.feedback_id;\n'
 " payload=v.command->'envelope'->'payload';\n"
 ' '
 "expected=jsonb_build_object('feedback',payload->'feedback','feedback_version_id',parent.id,'response_kind',v.response_kind,\n"
 '  '
 "'description',payload->'description','occurred_at',v.body->'occurred_at','result_receipts',coalesce(payload->'result_receipts','[]'::jsonb));\n"
 ' IF '
 'ROW(v.category_id,v.product_id,v.project_id,v.feedback_id,v.feedback_version_id,v.feedback_revision)\n'
 '  IS DISTINCT FROM '
 'ROW(parent.category_id,parent.product_id,parent.project_id,parent.feedback_id,parent.id,parent.revision)\n'
 '  OR cur.version_id<>parent.id OR cur.revision<>parent.revision\n'
 "  OR v.owner_id<>v.requester_id OR (parent.visibility='private' AND v.visibility<>'private')\n"
 "  OR payload->>'visibility' IS DISTINCT FROM v.visibility\n"
 "  OR payload->'feedback' IS DISTINCT FROM "
 "jsonb_build_object('id',parent.feedback_id,'revision',parent.revision)\n"
 "  OR v.body IS DISTINCT FROM expected OR v.sources IS DISTINCT FROM payload->'sources'\n"
 "  OR (v.body->>'occurred_at')::timestamptz IS DISTINCT FROM (payload->>'occurred_at')::timestamptz\n"
 "  OR coalesce(v.command->'review'->'before','null'::jsonb)<>'null'::jsonb\n"
 "  OR (v.operation='field.feedback.action.record' AND (payload->>'action_kind' IS DISTINCT FROM "
 "v.response_kind OR v.body->'result_receipts'<>'[]'::jsonb))\n"
 "  OR NOT coalesce(v.source_basis->'artifacts' @> parent.source_basis->'artifacts',false) THEN\n"
 "  RAISE EXCEPTION 'Field response binds exact current parent and new actual facts without advancing "
 "its report' USING ERRCODE='23514'; END IF;\n"
 " IF v.operation='field.feedback.followup.link' THEN\n"
 "  IF v.project_id IS NULL OR jsonb_array_length(payload->'result_receipts')=0\n"
 '   OR '
 "jsonb_array_length(v.source_basis->'result_receipts')<>jsonb_array_length(payload->'result_receipts')\n"
 "   OR EXISTS(SELECT 1 FROM jsonb_array_elements(v.source_basis->'result_receipts') result WHERE "
 "result->>'product_id' IS DISTINCT FROM v.product_id::text\n"
 "    OR result->>'project_id' IS DISTINCT FROM v.project_id::text OR NOT EXISTS(SELECT 1 FROM "
 "jsonb_array_elements(payload->'result_receipts') requested WHERE "
 "requested->'receipt_id'=result->'receipt_id')) THEN\n"
 "   RAISE EXCEPTION 'Field follow-up references only finite fixed native results in its actual "
 "project' USING ERRCODE='23514'; END IF;\n"
 "  FOR result IN SELECT value FROM jsonb_array_elements(v.source_basis->'result_receipts') LOOP\n"
 '   SELECT * INTO STRICT native_receipt FROM public.action_receipts r WHERE r.tenant_id=t AND '
 'r.category_id=v.category_id\n'
 "    AND r.id::text=result->>'receipt_id' AND r.product_id=v.product_id AND "
 "r.operation=result->>'operation'\n"
 "    AND r.subject_type=result->>'subject_type' AND r.subject_id::text=result->>'subject_id'\n"
 "    AND r.subject_revision::text=result->>'subject_revision' AND "
 "r.request_digest=result->>'receipt_request_digest'\n"
 "    AND r.visibility=result->>'receipt_visibility';\n"
 "   IF (v.visibility='category' AND (native_receipt.visibility<>'category' OR "
 "result->>'visibility'<>'category'\n"
 '     OR NOT EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id=t AND p.id=v.product_id AND '
 "p.visibility='category')\n"
 '     OR NOT EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=t AND p.id=v.project_id AND '
 "p.visibility='category')))\n"
 '    OR NOT EXISTS(SELECT 1 FROM public.audit_entries a WHERE a.tenant_id=t AND '
 'a.category_id=v.category_id AND a.receipt_id=native_receipt.id\n'
 '     AND a.actor_id=native_receipt.actor_id AND a.operation=native_receipt.operation)\n'
 '    OR NOT EXISTS(SELECT 1 FROM public.outbox_events e WHERE e.tenant_id=t AND '
 'e.category_id=v.category_id AND e.receipt_id=native_receipt.id\n'
 '     AND e.subject_id=native_receipt.subject_id AND '
 'e.subject_revision=native_receipt.subject_revision AND e.actor_id=native_receipt.actor_id\n'
 '     AND e.schema_version=1 AND '
 'e.correlation_id=coalesce(native_receipt.agent_run_id,native_receipt.run_id,native_receipt.command_id)) '
 'THEN\n'
 "    RAISE EXCEPTION 'Field follow-up requires actual native receipt audit event and audience' USING "
 "ERRCODE='23514'; END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 'END;\n'
 '$field$',
 'CREATE FUNCTION public.require_field_feedback() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $field$\n'
 'BEGIN PERFORM public.assert_field_feedback(NEW.tenant_id,NEW.id); RETURN NULL; END;\n'
 '$field$',
 'CREATE FUNCTION public.require_field_response() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $field$\n'
 'BEGIN PERFORM public.assert_field_response(NEW.tenant_id,NEW.id); RETURN NULL; END;\n'
 '$field$',
 'CREATE FUNCTION public.protect_field_receipt() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $field$\n'
 '\n'
 'DECLARE scoped boolean=false;\n'
 'BEGIN\n'
 " IF TG_OP<>'INSERT' THEN scoped=OLD.operation IN "
 "('field.feedback.create','field.feedback.locate','field.feedback.action.record','field.feedback.followup.link') "
 "OR OLD.subject_type IN ('field_feedback','field_response'); END IF;\n"
 " IF TG_OP<>'DELETE' THEN scoped=scoped OR NEW.operation IN "
 "('field.feedback.create','field.feedback.locate','field.feedback.action.record','field.feedback.followup.link') "
 "OR NEW.subject_type IN ('field_feedback','field_response'); END IF;\n"
 " IF scoped AND TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Field receipt history is immutable' USING "
 "ERRCODE='23514'; END IF;\n"
 " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
 'END;\n'
 '$field$',
 'CREATE FUNCTION public.protect_field_member() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $field$\n'
 '\n'
 'DECLARE scoped boolean=false; old_scoped boolean=false;\n'
 'BEGIN\n'
 " IF TG_OP<>'DELETE' THEN SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE "
 'r.tenant_id=NEW.tenant_id AND r.id=NEW.receipt_id AND (r.operation IN '
 "('field.feedback.create','field.feedback.locate','field.feedback.action.record','field.feedback.followup.link') "
 "OR r.subject_type IN ('field_feedback','field_response'))) INTO scoped; END IF;\n"
 " IF TG_OP<>'INSERT' THEN SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE "
 'r.tenant_id=OLD.tenant_id AND r.id=OLD.receipt_id AND (r.operation IN '
 "('field.feedback.create','field.feedback.locate','field.feedback.action.record','field.feedback.followup.link') "
 "OR r.subject_type IN ('field_feedback','field_response'))) INTO old_scoped; END IF;\n"
 " IF TG_OP<>'INSERT' AND (scoped OR old_scoped) THEN\n"
 "  IF TG_OP='UPDATE' AND TG_TABLE_NAME='outbox_events' AND "
 "(to_jsonb(NEW)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) IS NOT "
 "DISTINCT FROM (to_jsonb(OLD)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) "
 'THEN RETURN NEW; END IF;\n'
 "  RAISE EXCEPTION 'Field original audit event or request key is immutable' USING ERRCODE='23514'; "
 'END IF;\n'
 " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
 'END;\n'
 '$field$',
 'CREATE FUNCTION public.require_field_member() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $field$\n'
 '\n'
 'DECLARE receipt public.action_receipts;\n'
 'BEGIN\n'
 " IF TG_TABLE_NAME='action_receipts' THEN receipt=NEW; ELSE SELECT * INTO receipt FROM "
 'public.action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id; END IF;\n'
 ' IF receipt.operation IN '
 "('field.feedback.create','field.feedback.locate','field.feedback.action.record','field.feedback.followup.link') "
 "OR receipt.subject_type IN ('field_feedback','field_response') THEN\n"
 '  PERFORM '
 'public.assert_field_members(receipt.tenant_id,receipt.subject_id,receipt.subject_type::text); END '
 'IF;\n'
 ' RETURN NULL;\n'
 'END;\n'
 '$field$',
 'CREATE FUNCTION public.protect_field_confirmation() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $field$\n'
 '\n'
 'DECLARE old_scoped boolean=false; new_scoped boolean=false;\n'
 'BEGIN\n'
 " IF TG_OP<>'INSERT' THEN old_scoped=OLD.operation IN "
 "('field.feedback.locate','field.feedback.action.record','field.feedback.followup.link'); END IF;\n"
 " IF TG_OP<>'DELETE' THEN new_scoped=NEW.operation IN "
 "('field.feedback.locate','field.feedback.action.record','field.feedback.followup.link'); END IF;\n"
 ' IF old_scoped OR new_scoped THEN\n'
 "  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Field confirmation history retained' USING "
 "ERRCODE='23514';\n"
 "  ELSIF TG_OP='INSERT' THEN\n"
 "   IF NEW.consumed IS DISTINCT FROM false THEN RAISE EXCEPTION 'Field T1 starts unconsumed' USING "
 "ERRCODE='23514'; END IF;\n"
 '  ELSIF NOT(old_scoped AND new_scoped) OR OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS '
 'DISTINCT FROM true\n'
 "   OR (to_jsonb(NEW)-'consumed') IS DISTINCT FROM (to_jsonb(OLD)-'consumed') THEN\n"
 "   RAISE EXCEPTION 'Field confirmation consumes only its original false to true' USING "
 "ERRCODE='23514'; END IF;\n"
 ' END IF;\n'
 " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
 'END;\n'
 '$field$',
 'CREATE FUNCTION public.require_field_confirmation() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $field$\n'
 '\n'
 'BEGIN\n'
 ' IF NEW.operation IN '
 "('field.feedback.locate','field.feedback.action.record','field.feedback.followup.link') THEN\n"
 '  IF OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true\n'
 '   OR (SELECT count(*) FROM (SELECT confirmation_id FROM public.field_feedback_versions v WHERE '
 'v.tenant_id=NEW.tenant_id AND v.confirmation_id=NEW.id AND v.operation=NEW.operation\n'
 '    UNION ALL SELECT confirmation_id FROM public.field_response_records v WHERE '
 'v.tenant_id=NEW.tenant_id AND v.confirmation_id=NEW.id AND v.operation=NEW.operation) refs)<>1 THEN\n'
 "   RAISE EXCEPTION 'Consumed Field T1 proof requires exactly one new fact' USING ERRCODE='23514'; "
 'END IF;\n'
 ' END IF;\n'
 ' RETURN NULL;\n'
 'END;\n'
 '$field$',
 'REVOKE ALL ON FUNCTION public.reject_field_mutation() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.protect_field_current() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.require_field_current() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.assert_field_members(uuid,uuid,text) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.assert_field_common(uuid,uuid,text) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.assert_field_feedback(uuid,uuid) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.assert_field_response(uuid,uuid) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.require_field_feedback() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.require_field_response() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.protect_field_receipt() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.protect_field_member() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.require_field_member() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.protect_field_confirmation() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.require_field_confirmation() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'CREATE FUNCTION public.field_receipt_visible(t uuid,c uuid,p uuid,kind text,target uuid,rev '
 'integer,receipt uuid,actor uuid) RETURNS boolean\n'
 'LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog,public,pg_temp AS '
 '$field_receipt$\n'
 '\n'
 'BEGIN\n'
 " IF kind NOT IN ('field_feedback','field_response') THEN RETURN true; END IF;\n"
 ' IF NOT public.category_access(t,c) THEN RETURN false; END IF;\n'
 " IF kind='field_feedback' THEN RETURN EXISTS(SELECT 1 FROM public.field_feedback_versions f WHERE "
 'f.tenant_id=t AND f.category_id=c\n'
 '  AND f.product_id IS NOT DISTINCT FROM p AND f.id=target AND f.revision=rev AND '
 'f.receipt_id=receipt AND f.actor_id=actor\n'
 "  AND f.operation IN ('field.feedback.create','field.feedback.locate'));\n"
 " ELSIF kind='field_response' THEN RETURN EXISTS(SELECT 1 FROM public.field_response_records f WHERE "
 'f.tenant_id=t AND f.category_id=c\n'
 '  AND f.product_id IS NOT DISTINCT FROM p AND f.id=target AND f.revision=rev AND '
 'f.receipt_id=receipt AND f.actor_id=actor\n'
 "  AND f.operation IN ('field.feedback.action.record','field.feedback.followup.link')); END IF;\n"
 ' RETURN false;\n'
 'END;\n'
 '$field_receipt$',
 'REVOKE ALL ON FUNCTION public.field_receipt_visible(uuid,uuid,uuid,text,uuid,integer,uuid,uuid) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'GRANT EXECUTE ON FUNCTION public.field_receipt_visible(uuid,uuid,uuid,text,uuid,integer,uuid,uuid) '
 'TO pdos_next_app',
 'ALTER TABLE public."field_feedback_versions" ENABLE ROW LEVEL SECURITY',
 'ALTER TABLE public."field_feedback_versions" FORCE ROW LEVEL SECURITY',
 'CREATE POLICY owner_internal ON public."field_feedback_versions" TO pdos_next_owner USING(true) WITH '
 'CHECK(true)',
 'CREATE POLICY field_read ON public."field_feedback_versions" FOR SELECT TO pdos_next_app '
 "USING(public.category_access(tenant_id,category_id) AND (visibility='category' OR "
 'owner_id=public.scope_requester()) AND (field_feedback_versions.product_id IS NULL OR EXISTS(SELECT '
 '1 FROM public.products p WHERE p.tenant_id=field_feedback_versions.tenant_id AND '
 'p.category_id=field_feedback_versions.category_id AND p.id=field_feedback_versions.product_id)) AND '
 '(field_feedback_versions.project_id IS NULL OR EXISTS(SELECT 1 FROM public.projects p WHERE '
 'p.tenant_id=field_feedback_versions.tenant_id AND p.category_id=field_feedback_versions.category_id '
 'AND p.product_id=field_feedback_versions.product_id AND p.id=field_feedback_versions.project_id)) '
 'AND public.knowledge_content_sources_visible(tenant_id,category_id,product_id,source_basis) AND '
 'public.knowledge_result_sources_visible(tenant_id,category_id,product_id,source_basis))',
 'CREATE POLICY field_insert ON public."field_feedback_versions" FOR INSERT TO pdos_next_app WITH '
 'CHECK(public.category_access(tenant_id,category_id,true) AND '
 "public.category_access(tenant_id,category_id) AND (visibility='category' OR "
 'owner_id=public.scope_requester()) AND (field_feedback_versions.product_id IS NULL OR EXISTS(SELECT '
 '1 FROM public.products p WHERE p.tenant_id=field_feedback_versions.tenant_id AND '
 'p.category_id=field_feedback_versions.category_id AND p.id=field_feedback_versions.product_id)) AND '
 '(field_feedback_versions.project_id IS NULL OR EXISTS(SELECT 1 FROM public.projects p WHERE '
 'p.tenant_id=field_feedback_versions.tenant_id AND p.category_id=field_feedback_versions.category_id '
 'AND p.product_id=field_feedback_versions.product_id AND p.id=field_feedback_versions.project_id)))',
 'REVOKE ALL ON public."field_feedback_versions" FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'GRANT SELECT,INSERT ON public."field_feedback_versions" TO pdos_next_app',
 'ALTER TABLE public."field_feedback_currents" ENABLE ROW LEVEL SECURITY',
 'ALTER TABLE public."field_feedback_currents" FORCE ROW LEVEL SECURITY',
 'CREATE POLICY owner_internal ON public."field_feedback_currents" TO pdos_next_owner USING(true) WITH '
 'CHECK(true)',
 'CREATE POLICY field_read ON public."field_feedback_currents" FOR SELECT TO pdos_next_app '
 "USING(public.category_access(tenant_id,category_id) AND (visibility='category' OR "
 'owner_id=public.scope_requester()) AND (field_feedback_currents.product_id IS NULL OR EXISTS(SELECT '
 '1 FROM public.products p WHERE p.tenant_id=field_feedback_currents.tenant_id AND '
 'p.category_id=field_feedback_currents.category_id AND p.id=field_feedback_currents.product_id)) AND '
 '(field_feedback_currents.project_id IS NULL OR EXISTS(SELECT 1 FROM public.projects p WHERE '
 'p.tenant_id=field_feedback_currents.tenant_id AND p.category_id=field_feedback_currents.category_id '
 'AND p.product_id=field_feedback_currents.product_id AND p.id=field_feedback_currents.project_id)) '
 'AND EXISTS(SELECT 1 FROM public.field_feedback_versions fixed WHERE '
 'fixed.tenant_id=field_feedback_currents.tenant_id AND '
 'fixed.category_id=field_feedback_currents.category_id AND '
 'fixed.feedback_id=field_feedback_currents.feedback_id AND '
 'fixed.id=field_feedback_currents.version_id AND fixed.revision=field_feedback_currents.revision AND '
 'ROW(fixed.product_id,fixed.project_id,fixed.owner_id,fixed.visibility) IS NOT DISTINCT FROM '
 'ROW(field_feedback_currents.product_id,field_feedback_currents.project_id,field_feedback_currents.owner_id,field_feedback_currents.visibility)))',
 'CREATE POLICY field_insert ON public."field_feedback_currents" FOR INSERT TO pdos_next_app WITH '
 'CHECK(public.category_access(tenant_id,category_id,true) AND '
 "public.category_access(tenant_id,category_id) AND (visibility='category' OR "
 'owner_id=public.scope_requester()) AND (field_feedback_currents.product_id IS NULL OR EXISTS(SELECT '
 '1 FROM public.products p WHERE p.tenant_id=field_feedback_currents.tenant_id AND '
 'p.category_id=field_feedback_currents.category_id AND p.id=field_feedback_currents.product_id)) AND '
 '(field_feedback_currents.project_id IS NULL OR EXISTS(SELECT 1 FROM public.projects p WHERE '
 'p.tenant_id=field_feedback_currents.tenant_id AND p.category_id=field_feedback_currents.category_id '
 'AND p.product_id=field_feedback_currents.product_id AND p.id=field_feedback_currents.project_id)))',
 'REVOKE ALL ON public."field_feedback_currents" FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'GRANT SELECT,INSERT ON public."field_feedback_currents" TO pdos_next_app',
 'CREATE POLICY field_advance ON public."field_feedback_currents" FOR UPDATE TO pdos_next_app '
 'USING(public.category_access(tenant_id,category_id,true) AND '
 "public.category_access(tenant_id,category_id) AND (visibility='category' OR "
 'owner_id=public.scope_requester()) AND (field_feedback_currents.product_id IS NULL OR EXISTS(SELECT '
 '1 FROM public.products p WHERE p.tenant_id=field_feedback_currents.tenant_id AND '
 'p.category_id=field_feedback_currents.category_id AND p.id=field_feedback_currents.product_id)) AND '
 '(field_feedback_currents.project_id IS NULL OR EXISTS(SELECT 1 FROM public.projects p WHERE '
 'p.tenant_id=field_feedback_currents.tenant_id AND p.category_id=field_feedback_currents.category_id '
 'AND p.product_id=field_feedback_currents.product_id AND p.id=field_feedback_currents.project_id)) '
 'AND EXISTS(SELECT 1 FROM public.field_feedback_versions fixed WHERE '
 'fixed.tenant_id=field_feedback_currents.tenant_id AND '
 'fixed.category_id=field_feedback_currents.category_id AND '
 'fixed.feedback_id=field_feedback_currents.feedback_id AND '
 'fixed.id=field_feedback_currents.version_id AND fixed.revision=field_feedback_currents.revision AND '
 'ROW(fixed.product_id,fixed.project_id,fixed.owner_id,fixed.visibility) IS NOT DISTINCT FROM '
 'ROW(field_feedback_currents.product_id,field_feedback_currents.project_id,field_feedback_currents.owner_id,field_feedback_currents.visibility))) '
 'WITH CHECK(public.category_access(tenant_id,category_id,true) AND '
 "public.category_access(tenant_id,category_id) AND (visibility='category' OR "
 'owner_id=public.scope_requester()) AND (field_feedback_currents.product_id IS NULL OR EXISTS(SELECT '
 '1 FROM public.products p WHERE p.tenant_id=field_feedback_currents.tenant_id AND '
 'p.category_id=field_feedback_currents.category_id AND p.id=field_feedback_currents.product_id)) AND '
 '(field_feedback_currents.project_id IS NULL OR EXISTS(SELECT 1 FROM public.projects p WHERE '
 'p.tenant_id=field_feedback_currents.tenant_id AND p.category_id=field_feedback_currents.category_id '
 'AND p.product_id=field_feedback_currents.product_id AND p.id=field_feedback_currents.project_id)))',
 'GRANT UPDATE(version_id,revision,product_id,project_id) ON public."field_feedback_currents" TO '
 'pdos_next_app',
 'ALTER TABLE public."field_response_records" ENABLE ROW LEVEL SECURITY',
 'ALTER TABLE public."field_response_records" FORCE ROW LEVEL SECURITY',
 'CREATE POLICY owner_internal ON public."field_response_records" TO pdos_next_owner USING(true) WITH '
 'CHECK(true)',
 'CREATE POLICY field_read ON public."field_response_records" FOR SELECT TO pdos_next_app '
 "USING(public.category_access(tenant_id,category_id) AND (visibility='category' OR "
 'owner_id=public.scope_requester()) AND (field_response_records.product_id IS NULL OR EXISTS(SELECT 1 '
 'FROM public.products p WHERE p.tenant_id=field_response_records.tenant_id AND '
 'p.category_id=field_response_records.category_id AND p.id=field_response_records.product_id)) AND '
 '(field_response_records.project_id IS NULL OR EXISTS(SELECT 1 FROM public.projects p WHERE '
 'p.tenant_id=field_response_records.tenant_id AND p.category_id=field_response_records.category_id '
 'AND p.product_id=field_response_records.product_id AND p.id=field_response_records.project_id)) AND '
 'public.knowledge_content_sources_visible(tenant_id,category_id,product_id,source_basis) AND '
 'public.knowledge_result_sources_visible(tenant_id,category_id,product_id,source_basis) AND '
 'EXISTS(SELECT 1 FROM public.field_feedback_versions parent WHERE '
 'parent.tenant_id=field_response_records.tenant_id AND '
 'parent.category_id=field_response_records.category_id AND '
 'parent.feedback_id=field_response_records.feedback_id AND '
 'parent.id=field_response_records.feedback_version_id AND '
 'parent.revision=field_response_records.feedback_revision AND '
 'ROW(parent.product_id,parent.project_id) IS NOT DISTINCT FROM '
 'ROW(field_response_records.product_id,field_response_records.project_id)))',
 'CREATE POLICY field_insert ON public."field_response_records" FOR INSERT TO pdos_next_app WITH '
 'CHECK(public.category_access(tenant_id,category_id,true) AND '
 "public.category_access(tenant_id,category_id) AND (visibility='category' OR "
 'owner_id=public.scope_requester()) AND (field_response_records.product_id IS NULL OR EXISTS(SELECT 1 '
 'FROM public.products p WHERE p.tenant_id=field_response_records.tenant_id AND '
 'p.category_id=field_response_records.category_id AND p.id=field_response_records.product_id)) AND '
 '(field_response_records.project_id IS NULL OR EXISTS(SELECT 1 FROM public.projects p WHERE '
 'p.tenant_id=field_response_records.tenant_id AND p.category_id=field_response_records.category_id '
 'AND p.product_id=field_response_records.product_id AND p.id=field_response_records.project_id)))',
 'REVOKE ALL ON public."field_response_records" FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'GRANT SELECT,INSERT ON public."field_response_records" TO pdos_next_app',
 'CREATE TRIGGER field_feedback_immutable BEFORE UPDATE OR DELETE ON public.field_feedback_versions '
 'FOR EACH ROW EXECUTE FUNCTION public.reject_field_mutation()',
 'CREATE CONSTRAINT TRIGGER field_feedback_atom AFTER INSERT ON public.field_feedback_versions '
 'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_field_feedback()',
 'CREATE TRIGGER field_response_immutable BEFORE UPDATE OR DELETE ON public.field_response_records FOR '
 'EACH ROW EXECUTE FUNCTION public.reject_field_mutation()',
 'CREATE CONSTRAINT TRIGGER field_response_atom AFTER INSERT ON public.field_response_records '
 'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_field_response()',
 'CREATE TRIGGER field_current_guard BEFORE INSERT OR UPDATE OR DELETE ON '
 'public.field_feedback_currents FOR EACH ROW EXECUTE FUNCTION public.protect_field_current()',
 'CREATE CONSTRAINT TRIGGER field_current_atom AFTER INSERT OR UPDATE ON '
 'public.field_feedback_currents DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION '
 'public.require_field_current()',
 'CREATE TRIGGER protect_field_receipt BEFORE UPDATE OR DELETE ON public.action_receipts FOR EACH ROW '
 'EXECUTE FUNCTION public.protect_field_receipt()',
 'CREATE TRIGGER protect_field_confirmation BEFORE INSERT OR UPDATE OR DELETE ON public.confirmations '
 'FOR EACH ROW EXECUTE FUNCTION public.protect_field_confirmation()',
 'CREATE CONSTRAINT TRIGGER require_field_confirmation AFTER UPDATE ON public.confirmations DEFERRABLE '
 'INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_field_confirmation()',
 'CREATE CONSTRAINT TRIGGER require_field_member AFTER INSERT ON public.action_receipts DEFERRABLE '
 'INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_field_member()',
 'CREATE TRIGGER protect_field_member BEFORE UPDATE OR DELETE ON public.audit_entries FOR EACH ROW '
 'EXECUTE FUNCTION public.protect_field_member()',
 'CREATE CONSTRAINT TRIGGER require_field_member AFTER INSERT ON public.audit_entries DEFERRABLE '
 'INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_field_member()',
 'CREATE TRIGGER protect_field_member BEFORE UPDATE OR DELETE ON public.outbox_events FOR EACH ROW '
 'EXECUTE FUNCTION public.protect_field_member()',
 'CREATE CONSTRAINT TRIGGER require_field_member AFTER INSERT ON public.outbox_events DEFERRABLE '
 'INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_field_member()',
 'CREATE TRIGGER protect_field_member BEFORE UPDATE OR DELETE ON public.request_keys FOR EACH ROW '
 'EXECUTE FUNCTION public.protect_field_member()',
 'CREATE CONSTRAINT TRIGGER require_field_member AFTER INSERT ON public.request_keys DEFERRABLE '
 'INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_field_member()',
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
 "  WHEN 'field_feedback_versions' THEN ARRAY['project_id']\n"
 "  WHEN 'field_feedback_currents' THEN ARRAY['project_id']\n"
 "  WHEN 'field_response_records' THEN ARRAY['project_id']\n"
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
 '\n'
 " IF table_name IN ('field_feedback_versions','field_feedback_currents','field_response_records') "
 'THEN\n'
 "  FOREACH key IN ARRAY ARRAY['previous_id','version_id','feedback_version_id'] LOOP\n"
 '   IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n'
 '  END LOOP;\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  FOREACH key IN ARRAY ARRAY['engineering_configuration','manufacturing_configuration','batch'] "
 'LOOP\n'
 "   IF payload#>>ARRAY['body','location',key,'id'] IS NOT NULL THEN "
 "links=array_append(links,(payload#>>ARRAY['body','location',key,'id'])::uuid); END IF;\n"
 '  END LOOP;\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,result_receipts}','[]')) LOOP\n"
 "   IF item->>'receipt_id' IS NOT NULL THEN links=array_append(links,(item->>'receipt_id')::uuid); "
 'END IF;\n'
 "   IF item->>'row_id' IS NOT NULL THEN links=array_append(links,(item->>'row_id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 " IF table_name IN ('change_request_versions','change_graph_captures') THEN\n"
 "  FOR container IN SELECT value FROM jsonb_each(coalesce(payload#>'{source_basis,owners}','{}')) "
 'LOOP\n'
 "   IF container->>'feedback_version_id' IS NOT NULL THEN "
 "links=array_append(links,(container->>'feedback_version_id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
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
 "ARRAY['agent_runs','action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','project_risk_followups','project_risk_followup_currents','knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents','field_feedback_versions','field_feedback_currents','field_response_records'] "
 'ELSE ARRAY[\n'
 "  'artifact_versions','claims','definition_revisions','definition_sources','definition_specs',\n"
 '  '
 "'proposals','proposal_items','proposal_item_versions','proposal_submissions','proposal_decisions',\n"
 '  '
 "'category_knowledge_entries','category_knowledge_current','parameter_versions','parameter_current',\n"
 '  '
 "'evidence_links','promotion_proofs','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','project_risk_followups','project_risk_followup_currents','knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents','field_feedback_versions','field_feedback_currents','field_response_records'] "
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
 "name<>ALL(ARRAY['native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','project_risk_followups','project_risk_followup_currents','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents','field_feedback_versions','field_feedback_currents','field_response_records']) "
 'THEN\n'
 '    links=links || public.kernel_lifecycle_links(name,payload);\n'
 '   END IF;\n'
 '   RETURN NEXT;\n'
 '  END LOOP;\n'
 ' END LOOP;\n'
 'END;\n'
 '$function$\n',
 'CREATE POLICY field_receipt_content ON public.action_receipts AS RESTRICTIVE FOR SELECT TO '
 'pdos_next_app '
 'USING(public.field_receipt_visible(tenant_id,category_id,product_id,subject_type::text,subject_id,subject_revision,id,actor_id))',
 'CREATE POLICY field_receipt_owner ON public.action_receipts FOR SELECT TO pdos_next_app '
 "USING(subject_type IN ('field_feedback','field_response') AND "
 'public.field_receipt_visible(tenant_id,category_id,product_id,subject_type::text,subject_id,subject_revision,id,actor_id))',
 'CREATE TRIGGER field_change_clock_insert AFTER INSERT ON public.field_feedback_versions FOR EACH ROW '
 'WHEN (NEW.product_id IS NOT NULL) EXECUTE FUNCTION public.advance_change_dependency_clock()',
 'CREATE TRIGGER field_change_clock_update AFTER UPDATE ON public.field_feedback_versions FOR EACH ROW '
 'WHEN (NEW.product_id IS NOT NULL OR OLD.product_id IS NOT NULL) EXECUTE FUNCTION '
 'public.advance_change_dependency_clock()',
 'CREATE TRIGGER field_change_clock_delete AFTER DELETE ON public.field_feedback_versions FOR EACH ROW '
 'WHEN (OLD.product_id IS NOT NULL) EXECUTE FUNCTION public.advance_change_dependency_clock()',
 'CREATE TRIGGER field_change_clock_insert AFTER INSERT ON public.field_feedback_currents FOR EACH ROW '
 'WHEN (NEW.product_id IS NOT NULL) EXECUTE FUNCTION public.advance_change_dependency_clock()',
 'CREATE TRIGGER field_change_clock_update AFTER UPDATE ON public.field_feedback_currents FOR EACH ROW '
 'WHEN (NEW.product_id IS NOT NULL OR OLD.product_id IS NOT NULL) EXECUTE FUNCTION '
 'public.advance_change_dependency_clock()',
 'CREATE TRIGGER field_change_clock_delete AFTER DELETE ON public.field_feedback_currents FOR EACH ROW '
 'WHEN (OLD.product_id IS NOT NULL) EXECUTE FUNCTION public.advance_change_dependency_clock()')

DOWNGRADE_SQL = ('LOCK TABLE '
 'public.field_feedback_versions,public.field_feedback_currents,public.field_response_records,public.action_receipts,public.confirmations '
 'IN ACCESS EXCLUSIVE MODE',
 'DO $field$ BEGIN IF EXISTS(SELECT 1 FROM public.field_feedback_versions) OR EXISTS(SELECT 1 FROM '
 'public.field_feedback_currents) OR EXISTS(SELECT 1 FROM public.field_response_records) OR '
 'EXISTS(SELECT 1 FROM public.action_receipts WHERE operation IN '
 "('field.feedback.create','field.feedback.locate','field.feedback.action.record','field.feedback.followup.link') "
 "OR subject_type IN ('field_feedback','field_response')) OR EXISTS(SELECT 1 FROM public.confirmations "
 'WHERE operation IN '
 "('field.feedback.locate','field.feedback.action.record','field.feedback.followup.link')) THEN RAISE "
 "EXCEPTION 'Field history retained; downgrade refused' USING ERRCODE='23514'; END IF; END; $field$",
 'DROP POLICY field_receipt_owner ON public.action_receipts',
 'DROP POLICY field_receipt_content ON public.action_receipts',
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
 'DROP TRIGGER protect_field_receipt ON public.action_receipts',
 'DROP TRIGGER protect_field_confirmation ON public.confirmations',
 'DROP TRIGGER require_field_confirmation ON public.confirmations',
 'DROP TRIGGER require_field_member ON public.action_receipts',
 'DROP TRIGGER protect_field_member ON public.audit_entries',
 'DROP TRIGGER require_field_member ON public.audit_entries',
 'DROP TRIGGER protect_field_member ON public.outbox_events',
 'DROP TRIGGER require_field_member ON public.outbox_events',
 'DROP TRIGGER protect_field_member ON public.request_keys',
 'DROP TRIGGER require_field_member ON public.request_keys',
 'DROP TABLE public.field_response_records',
 'DROP TABLE public.field_feedback_currents',
 'DROP TABLE public.field_feedback_versions',
 'DROP FUNCTION public.field_receipt_visible(uuid,uuid,uuid,text,uuid,integer,uuid,uuid)',
 'DROP FUNCTION public.require_field_confirmation()',
 'DROP FUNCTION public.protect_field_confirmation()',
 'DROP FUNCTION public.require_field_member()',
 'DROP FUNCTION public.protect_field_member()',
 'DROP FUNCTION public.protect_field_receipt()',
 'DROP FUNCTION public.require_field_response()',
 'DROP FUNCTION public.require_field_feedback()',
 'DROP FUNCTION public.assert_field_response(uuid,uuid)',
 'DROP FUNCTION public.assert_field_feedback(uuid,uuid)',
 'DROP FUNCTION public.assert_field_common(uuid,uuid,text)',
 'DROP FUNCTION public.assert_field_members(uuid,uuid,text)',
 'DROP FUNCTION public.require_field_current()',
 'DROP FUNCTION public.protect_field_current()',
 'DROP FUNCTION public.reject_field_mutation()')

