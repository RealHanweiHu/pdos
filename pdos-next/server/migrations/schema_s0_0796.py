"""Actual 0795 ordinary-owner functions extended for bounded external waits."""

PREVIOUS_FUNCTIONS = {'assert_work_management_members(uuid,uuid,text)': 'CREATE OR REPLACE FUNCTION '
                                                   'public.assert_work_management_members(t uuid, '
                                                   'target uuid, kind text)\n'
                                                   ' RETURNS void\n'
                                                   ' LANGUAGE plpgsql\n'
                                                   ' SECURITY DEFINER\n'
                                                   " SET search_path TO 'pg_catalog', 'public', "
                                                   "'pg_temp'\n"
                                                   'AS $function$\n'
                                                   '\n'
                                                   'DECLARE v record; r public.action_receipts; c '
                                                   'public.confirmations; expected_status text; '
                                                   'event_name text; expected_result jsonb;\n'
                                                   'BEGIN\n'
                                                   '\n'
                                                   " IF kind='work_task' THEN SELECT * INTO STRICT "
                                                   'v FROM public.work_task_versions WHERE '
                                                   'tenant_id=t AND id=target;\n'
                                                   " ELSIF kind='work_commitment' THEN SELECT * "
                                                   'INTO STRICT v FROM '
                                                   'public.work_commitment_versions WHERE '
                                                   'tenant_id=t AND id=target;\n'
                                                   " ELSIF kind='project_status_update' THEN "
                                                   'SELECT * INTO STRICT v FROM '
                                                   'public.project_status_updates WHERE '
                                                   'tenant_id=t AND id=target;\n'
                                                   " ELSE RAISE EXCEPTION 'Unknown work subject' "
                                                   "USING ERRCODE='23514'; END IF;\n"
                                                   '\n'
                                                   " expected_status=CASE WHEN kind='work_task' "
                                                   "THEN v.body->>'state' ELSE 'recorded' END;\n"
                                                   ' '
                                                   "expected_result=jsonb_build_object('id',v.id,'revision',v.revision,'status',expected_status);\n"
                                                   " IF kind='work_task' THEN "
                                                   "expected_result=expected_result||jsonb_build_object('task_id',v.task_id,'state',v.state,'project_id',v.project_id);\n"
                                                   " ELSIF kind='work_commitment' THEN "
                                                   "expected_result=expected_result||jsonb_build_object('task_id',v.task_id,'recipient_id',v.recipient_id);\n"
                                                   ' ELSE '
                                                   "expected_result=expected_result||jsonb_build_object('project_id',v.project_id); "
                                                   'END IF;\n'
                                                   ' event_name=CASE v.operation WHEN '
                                                   "'work.task.create' THEN 'task.created' WHEN "
                                                   "'work.task.assign' THEN 'task.assigned'\n"
                                                   "  WHEN 'work.task.accept' THEN 'task.accepted' "
                                                   "WHEN 'work.task.start' THEN 'task.started'\n"
                                                   "  WHEN 'work.task.submit' THEN "
                                                   "'task.submitted' WHEN 'work.task.review' THEN "
                                                   "'task.reviewed'\n"
                                                   "  WHEN 'work.commitment.accept' THEN "
                                                   "'commitment.accepted' WHEN "
                                                   "'work.status_update.create' THEN "
                                                   "'project.status_updated' END;\n"
                                                   ' SELECT * INTO STRICT r FROM '
                                                   'public.action_receipts WHERE tenant_id=t AND '
                                                   'id=v.receipt_id;\n'
                                                   ' IF '
                                                   'ROW(r.category_id,r.product_id,r.command_id,r.confirmation_id,r.actor_id,r.requester_id,r.operation,r.subject_type,r.subject_id,r.subject_revision,r.visibility,r.request_digest,r.intent_digest)\n'
                                                   '  IS DISTINCT FROM '
                                                   'ROW(v.category_id,v.product_id,v.command_id,v.confirmation_id,v.actor_id,v.requester_id,v.operation,kind::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)\n'
                                                   '  OR r.result IS DISTINCT FROM '
                                                   'expected_result\n'
                                                   '  OR r.created_at<v.created_at OR event_name '
                                                   'IS NULL\n'
                                                   '  OR (SELECT count(*) FROM '
                                                   'public.action_receipts x WHERE x.tenant_id=t '
                                                   'AND x.operation=v.operation AND '
                                                   'x.subject_type=kind AND x.subject_id=v.id AND '
                                                   'x.subject_revision=v.revision)<>1\n'
                                                   '  OR (SELECT count(*) FROM '
                                                   'public.audit_entries a WHERE a.tenant_id=t AND '
                                                   'a.receipt_id=r.id)<>1\n'
                                                   '  OR NOT EXISTS(SELECT 1 FROM '
                                                   'public.audit_entries a WHERE a.tenant_id=t AND '
                                                   'a.receipt_id=r.id AND '
                                                   'a.category_id=v.category_id AND '
                                                   'a.actor_id=v.actor_id AND '
                                                   'a.operation=v.operation AND '
                                                   'a.created_at>=v.created_at)\n'
                                                   '  OR (SELECT count(*) FROM '
                                                   'public.outbox_events e WHERE e.tenant_id=t AND '
                                                   'e.receipt_id=r.id)<>1\n'
                                                   '  OR NOT EXISTS(SELECT 1 FROM '
                                                   'public.outbox_events e WHERE e.tenant_id=t AND '
                                                   'e.receipt_id=r.id AND '
                                                   'e.category_id=v.category_id AND '
                                                   'e.actor_id=v.actor_id AND e.type=event_name '
                                                   'AND e.subject_id=v.id AND '
                                                   'e.subject_revision=v.revision AND '
                                                   'e.schema_version=1 AND '
                                                   'e.correlation_id=coalesce(r.agent_run_id,r.run_id,v.command_id) '
                                                   'AND e.created_at>=v.created_at)\n'
                                                   "  OR v.command->>'original_key_sha256' IS NULL "
                                                   "OR v.command->>'original_key_sha256' !~ "
                                                   "'^[a-f0-9]{64}$'\n"
                                                   "  OR v.command->'envelope' ? 'idempotency_key' "
                                                   "OR v.command->'envelope'->'payload' ? "
                                                   "'confirmation_token'\n"
                                                   '  OR NOT EXISTS(SELECT 1 FROM '
                                                   'public.request_keys k WHERE k.tenant_id=t AND '
                                                   'k.category_id=v.category_id AND '
                                                   'k.actor_id=v.actor_id AND k.receipt_id=r.id '
                                                   'AND k.digest=v.request_digest AND '
                                                   "encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.command->>'original_key_sha256') "
                                                   'THEN\n'
                                                   "  RAISE EXCEPTION 'Work fact original common "
                                                   "group mismatch' USING ERRCODE='23514'; END "
                                                   'IF;\n'
                                                   " IF v.operation<>'work.task.create' THEN\n"
                                                   '  SELECT * INTO STRICT c FROM '
                                                   'public.confirmations WHERE tenant_id=t AND '
                                                   'id=v.confirmation_id;\n'
                                                   '  IF c.consumed IS DISTINCT FROM true OR '
                                                   'ROW(c.category_id,c.product_id,c.actor_id,c.operation)\n'
                                                   '   IS DISTINCT FROM '
                                                   'ROW(v.category_id,v.product_id,v.actor_id,v.operation)\n'
                                                   '   OR c.subject_type IS DISTINCT FROM '
                                                   "'product' OR c.subject_id IS DISTINCT FROM "
                                                   'v.product_id\n'
                                                   '   OR c.revision::text IS DISTINCT FROM '
                                                   "v.command->'envelope'->>'expected_revision'\n"
                                                   '   OR c.snapshot IS DISTINCT FROM '
                                                   "v.command->'review' OR "
                                                   'c.created_at>v.created_at\n'
                                                   '   OR c.expires_at IS NULL OR '
                                                   'v.created_at>=c.expires_at OR '
                                                   'r.created_at>=c.expires_at\n'
                                                   '   OR r.run_id IS NOT NULL OR r.agent_run_id '
                                                   'IS NOT NULL THEN\n'
                                                   "   RAISE EXCEPTION 'Work T1 needs its actual "
                                                   "consumed confirmation' USING ERRCODE='23514'; "
                                                   'END IF;\n'
                                                   ' END IF;\n'
                                                   'END;\n'
                                                   '$function$\n',
 'assert_work_management_write(uuid,uuid,text)': 'CREATE OR REPLACE FUNCTION '
                                                 'public.assert_work_management_write(t uuid, '
                                                 'target uuid, kind text)\n'
                                                 ' RETURNS void\n'
                                                 ' LANGUAGE plpgsql\n'
                                                 ' SECURITY DEFINER\n'
                                                 " SET search_path TO 'pg_catalog', 'public', "
                                                 "'pg_temp'\n"
                                                 'AS $function$\n'
                                                 '\n'
                                                 'DECLARE v record; p public.projects; envelope '
                                                 'jsonb; ref jsonb; basis jsonb; vx xid; rx xid; '
                                                 'cx xid;\n'
                                                 'BEGIN\n'
                                                 '\n'
                                                 " IF kind='work_task' THEN SELECT * INTO STRICT v "
                                                 'FROM public.work_task_versions WHERE tenant_id=t '
                                                 'AND id=target;\n'
                                                 " ELSIF kind='work_commitment' THEN SELECT * INTO "
                                                 'STRICT v FROM public.work_commitment_versions '
                                                 'WHERE tenant_id=t AND id=target;\n'
                                                 " ELSIF kind='project_status_update' THEN SELECT "
                                                 '* INTO STRICT v FROM '
                                                 'public.project_status_updates WHERE tenant_id=t '
                                                 'AND id=target;\n'
                                                 " ELSE RAISE EXCEPTION 'Unknown work subject' "
                                                 "USING ERRCODE='23514'; END IF;\n"
                                                 '\n'
                                                 " IF kind='work_task' THEN SELECT xmin INTO vx "
                                                 'FROM public.work_task_versions WHERE tenant_id=t '
                                                 'AND id=target;\n'
                                                 " ELSIF kind='work_commitment' THEN SELECT xmin "
                                                 'INTO vx FROM public.work_commitment_versions '
                                                 'WHERE tenant_id=t AND id=target;\n'
                                                 ' ELSE SELECT xmin INTO vx FROM '
                                                 'public.project_status_updates WHERE tenant_id=t '
                                                 'AND id=target; END IF;\n'
                                                 ' SELECT * INTO STRICT p FROM public.projects '
                                                 'WHERE tenant_id=t AND id=v.project_id;\n'
                                                 ' SELECT xmin INTO rx FROM public.action_receipts '
                                                 'WHERE tenant_id=t AND id=v.receipt_id;\n'
                                                 ' PERFORM '
                                                 'public.assert_work_management_members(t,target,kind);\n'
                                                 " envelope=v.command->'envelope';\n"
                                                 '\n'
                                                 " IF kind='work_task' THEN PERFORM "
                                                 'public.assert_work_task_g0_source(t,target);\n'
                                                 " ELSIF v.source_basis ? 'g0_open_item' THEN\n"
                                                 "  RAISE EXCEPTION 'Only a task may use a native "
                                                 "G0 source basis' USING ERRCODE='23514'; END IF;\n"
                                                 ' IF '
                                                 'ROW(p.category_id,p.product_id,p.owner_id,p.visibility) '
                                                 'IS DISTINCT FROM '
                                                 'ROW(v.category_id,v.product_id,v.owner_id,v.visibility)\n'
                                                 '  OR v.actor_id IS DISTINCT FROM '
                                                 'public.scope_actor() OR v.requester_id IS '
                                                 'DISTINCT FROM public.scope_requester()\n'
                                                 '  OR v.writer_id<>v.actor_id OR vx IS DISTINCT '
                                                 'FROM rx OR NOT '
                                                 'public.category_access(t,v.category_id,true)\n'
                                                 '  OR NOT EXISTS(SELECT 1 FROM public.principals '
                                                 'a WHERE a.tenant_id=t AND a.id=v.actor_id AND '
                                                 'a.active)\n'
                                                 '  OR NOT EXISTS(SELECT 1 FROM public.principals '
                                                 'a WHERE a.tenant_id=t AND a.id=v.requester_id '
                                                 "AND a.kind='human' AND a.active)\n"
                                                 "  OR envelope->>'operation' IS DISTINCT FROM "
                                                 "v.operation OR envelope->>'command_id' IS "
                                                 'DISTINCT FROM v.command_id::text\n'
                                                 "  OR envelope->>'category_id' IS DISTINCT FROM "
                                                 "v.category_id::text OR envelope->>'product_id' "
                                                 'IS DISTINCT FROM v.product_id::text\n'
                                                 "  OR envelope->'payload'->>'project_id' IS "
                                                 'DISTINCT FROM v.project_id::text\n'
                                                 "  OR v.command->'review'->'declaration' IS "
                                                 "DISTINCT FROM envelope->'payload'\n"
                                                 "  OR v.command->'review'->>'operation' IS "
                                                 'DISTINCT FROM v.operation\n'
                                                 "  OR v.command->'review'->'sources' IS DISTINCT "
                                                 'FROM v.sources\n'
                                                 "  OR v.command->'review'->'source_basis' IS "
                                                 'DISTINCT FROM v.source_basis\n'
                                                 "  OR (v.body #- '{recorded_at}' #- "
                                                 "'{actual_start,recorded_at}' #- "
                                                 "'{submission,time,recorded_at}' #- "
                                                 "'{review,time,recorded_at}') IS DISTINCT FROM "
                                                 "v.command->'review'->'after'\n"
                                                 '  OR NOT EXISTS(SELECT 1 FROM public.products x '
                                                 'WHERE x.tenant_id=t AND '
                                                 'x.category_id=v.category_id AND '
                                                 'x.id=v.product_id AND '
                                                 "x.revision::text=envelope->>'expected_revision')\n"
                                                 "  OR NOT COALESCE(envelope->'source_read_set' @> "
                                                 'v.reads,false) OR NOT COALESCE(v.reads @> '
                                                 "(envelope->'source_read_set'),false)\n"
                                                 '  OR '
                                                 "jsonb_array_length(envelope->'source_read_set')<>jsonb_array_length(v.reads)\n"
                                                 '  OR NOT '
                                                 'public.direct_source_set_visible(t,v.category_id,v.product_id,v.reads)\n'
                                                 "  OR (v.operation<>'work.task.create' AND "
                                                 '(v.actor_id<>v.requester_id OR NOT EXISTS(SELECT '
                                                 '1 FROM public.principals a WHERE a.tenant_id=t '
                                                 "AND a.id=v.actor_id AND a.kind='human')))\n"
                                                 "  OR (v.operation='work.task.create' AND "
                                                 'v.actor_id<>v.requester_id AND NOT EXISTS(SELECT '
                                                 '1 FROM public.action_receipts r WHERE '
                                                 'r.tenant_id=t AND r.id=v.receipt_id AND '
                                                 'coalesce(r.agent_run_id,r.run_id) IS NOT NULL))\n'
                                                 '  OR EXISTS(SELECT 1 FROM public.audit_entries x '
                                                 'WHERE x.tenant_id=t AND '
                                                 'x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT '
                                                 'FROM vx)\n'
                                                 '  OR EXISTS(SELECT 1 FROM public.outbox_events x '
                                                 'WHERE x.tenant_id=t AND '
                                                 'x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT '
                                                 'FROM vx)\n'
                                                 '  OR NOT EXISTS(SELECT 1 FROM '
                                                 'public.request_keys k WHERE k.tenant_id=t AND '
                                                 'k.receipt_id=v.receipt_id AND '
                                                 'k.actor_id=v.actor_id AND '
                                                 'k.digest=v.request_digest AND k.xmin=vx AND '
                                                 "encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.command->>'original_key_sha256') "
                                                 'THEN\n'
                                                 "  RAISE EXCEPTION 'Work fact requires actual "
                                                 "project actor and one transaction' USING "
                                                 "ERRCODE='23514'; END IF;\n"
                                                 ' IF v.confirmation_id IS NOT NULL THEN\n'
                                                 '  SELECT xmin INTO cx FROM public.confirmations '
                                                 'WHERE tenant_id=t AND id=v.confirmation_id;\n'
                                                 '  IF cx IS DISTINCT FROM vx THEN RAISE EXCEPTION '
                                                 "'Work confirmation consumption must share its "
                                                 "new fact transaction' USING ERRCODE='23514'; END "
                                                 'IF;\n'
                                                 ' END IF;\n'
                                                 " IF jsonb_typeof(v.source_basis->'artifacts') IS "
                                                 "DISTINCT FROM 'array' THEN\n"
                                                 "  RAISE EXCEPTION 'Work direct source metadata "
                                                 "required' USING ERRCODE='23514'; END IF;\n"
                                                 ' FOR basis IN SELECT value FROM '
                                                 "jsonb_array_elements(v.source_basis->'artifacts') "
                                                 'LOOP\n'
                                                 '  IF NOT EXISTS(SELECT 1 FROM '
                                                 'public.artifact_versions a WHERE a.tenant_id=t '
                                                 'AND a.category_id=v.category_id\n'
                                                 '   AND (a.product_id IS NULL OR '
                                                 'a.product_id=v.product_id) AND '
                                                 "a.id::text=basis->>'id'\n"
                                                 "   AND a.revision::text=basis->>'revision' AND "
                                                 "a.content_hash=basis->>'hash' AND "
                                                 "a.status='active'\n"
                                                 "   AND a.status=basis->>'status' AND "
                                                 "a.owner_id::text=basis->>'owner_id' AND "
                                                 "a.visibility=basis->>'visibility'\n"
                                                 "   AND (v.visibility='private' OR "
                                                 "a.visibility<>'private')\n"
                                                 "   AND (NOT(basis ? 'original') OR EXISTS(SELECT "
                                                 '1 FROM public.original_security sec\n'
                                                 '    WHERE sec.tenant_id=t AND '
                                                 'sec.original_id=a.original_id AND '
                                                 "sec.original_id::text=basis->'original'->>'id'\n"
                                                 '     AND '
                                                 "sec.epoch::text=basis->'original'->>'epoch' AND "
                                                 "sec.source_state='active' AND "
                                                 "sec.disposition='active'))) THEN\n"
                                                 "   RAISE EXCEPTION 'Retained work source "
                                                 "metadata changed' USING ERRCODE='23514'; END "
                                                 'IF;\n'
                                                 ' END LOOP;\n'
                                                 ' FOR ref IN SELECT value FROM '
                                                 'jsonb_array_elements(v.sources) LOOP\n'
                                                 '  SELECT value INTO STRICT basis FROM '
                                                 "jsonb_array_elements(v.source_basis->'artifacts') "
                                                 "WHERE value->>'id'=ref->>'id';\n"
                                                 "  IF ref->>'kind' IS DISTINCT FROM 'artifact' OR "
                                                 'NOT EXISTS(SELECT 1 FROM '
                                                 'jsonb_array_elements(v.reads) rd WHERE '
                                                 "rd->>'artifact_id'=ref->>'id' AND "
                                                 "rd->'expected_revision'=ref->'revision')\n"
                                                 '   OR NOT EXISTS(SELECT 1 FROM '
                                                 'public.artifact_versions a WHERE a.tenant_id=t '
                                                 'AND a.category_id=v.category_id\n'
                                                 "    AND a.id::text=ref->>'id' AND "
                                                 "a.revision::text=ref->>'revision' AND "
                                                 "a.status='active'\n"
                                                 "    AND a.revision::text=basis->>'revision' AND "
                                                 "a.content_hash=basis->>'hash' AND "
                                                 "a.status=basis->>'status'\n"
                                                 "    AND a.owner_id::text=basis->>'owner_id' AND "
                                                 "a.visibility=basis->>'visibility'\n"
                                                 "    AND (v.visibility='private' OR "
                                                 "a.visibility<>'private')\n"
                                                 '    AND ((a.original_id IS NULL AND '
                                                 "basis->>'source_kind'='registered_native_text' "
                                                 'AND EXISTS(\n'
                                                 '      SELECT 1 FROM public.action_receipts r '
                                                 'WHERE r.tenant_id=t AND r.subject_id=a.id AND '
                                                 'r.subject_revision=a.revision\n'
                                                 "       AND r.subject_type='artifact' AND "
                                                 "r.operation='evidence.artifact.register' AND "
                                                 "r.id::text=basis->'registration'->>'receipt_id'\n"
                                                 '       AND '
                                                 "r.actor_id::text=basis->'registration'->>'actor_id' "
                                                 'AND '
                                                 "r.requester_id::text=basis->'registration'->>'requester_id'\n"
                                                 '       AND r.run_id::text IS NOT DISTINCT FROM '
                                                 "basis->'registration'->>'run_id'))\n"
                                                 '     OR (a.original_id IS NOT NULL AND '
                                                 "basis->>'source_kind'='uploaded_original' AND "
                                                 'EXISTS(\n'
                                                 '      SELECT 1 FROM public.uploaded_originals o '
                                                 'JOIN public.original_security sec ON '
                                                 'sec.tenant_id=o.tenant_id AND '
                                                 'sec.original_id=o.id\n'
                                                 '       WHERE o.tenant_id=t AND '
                                                 'o.category_id=v.category_id AND '
                                                 'o.id=a.original_id AND '
                                                 "o.id::text=basis->'original'->>'id'\n"
                                                 "        AND o.status='parsed' AND "
                                                 "sec.epoch::text=basis->'original'->>'epoch' AND "
                                                 "sec.source_state='active' AND "
                                                 "sec.disposition='active'\n"
                                                 '        AND '
                                                 "sec.source_state=basis->'original'->>'source_state' "
                                                 'AND '
                                                 "sec.disposition=basis->'original'->>'disposition'\n"
                                                 "        AND (v.visibility='private' OR "
                                                 "o.visibility<>'private'))))) THEN\n"
                                                 "   RAISE EXCEPTION 'Work source metadata "
                                                 "security or audience changed' USING "
                                                 "ERRCODE='23514'; END IF;\n"
                                                 ' END LOOP;\n'
                                                 'END;\n'
                                                 '$function$\n',
 'm3_lifecycle_nodes(uuid,uuid,uuid[])': 'CREATE OR REPLACE FUNCTION public.m3_lifecycle_nodes(t '
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
                                         "ARRAY['agent_runs','action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates'] "
                                         'ELSE ARRAY[\n'
                                         '  '
                                         "'artifact_versions','claims','definition_revisions','definition_sources','definition_specs',\n"
                                         '  '
                                         "'proposals','proposal_items','proposal_item_versions','proposal_submissions','proposal_decisions',\n"
                                         '  '
                                         "'category_knowledge_entries','category_knowledge_current','parameter_versions','parameter_current',\n"
                                         '  '
                                         "'evidence_links','promotion_proofs','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates'] "
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
                                         "name<>ALL(ARRAY['native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals']) "
                                         'THEN\n'
                                         '    links=links || '
                                         'public.kernel_lifecycle_links(name,payload);\n'
                                         '   END IF;\n'
                                         '   RETURN NEXT;\n'
                                         '  END LOOP;\n'
                                         ' END LOOP;\n'
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
                                                 "  WHEN 'external_handoff_authorizations' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'external_delivery_intents' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'external_receipts' THEN "
                                                 "ARRAY['project_id']\n"
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
                                                 'links=array_append(links,(payload->>key)::uuid); '
                                                 'END IF;\n'
                                                 ' END LOOP;\n'
                                                 ' RETURN links;\n'
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
                                                    ' -- Do not scan its declaration, body, reason '
                                                    'or arbitrary JSON UUID values.\n'
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
                                                    ' IF table_name IN '
                                                    "('external_handoff_authorizations','external_delivery_intents') "
                                                    'THEN\n'
                                                    '  -- Only closed, owner-verified mapping and '
                                                    'manifest references are source edges.\n'
                                                    '  container=CASE WHEN '
                                                    "table_name='external_handoff_authorizations' "
                                                    "THEN payload#>'{body,declaration}' ELSE "
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
                                                    "   IF item->'artifact'->>'id' IS NOT NULL "
                                                    'THEN '
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
                                                    "payload#>>'{body,plan_task,id}' IS NOT NULL "
                                                    'THEN\n'
                                                    '   '
                                                    "links=array_append(links,(payload#>>'{body,plan_task,id}')::uuid);\n"
                                                    '  END IF;\n'
                                                    "  IF table_name='work_commitment_versions' "
                                                    'THEN\n'
                                                    "   SELECT coalesce(array_agg(id),'{}') INTO "
                                                    'extra FROM public.work_task_versions\n'
                                                    '    WHERE tenant_id=t AND category_id=c AND '
                                                    "task_id=(payload->>'task_id')::uuid AND "
                                                    "revision=(payload->>'task_revision')::integer;\n"
                                                    '   links=links||extra;\n'
                                                    "  ELSIF table_name='project_status_updates' "
                                                    'THEN\n'
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
                                                    " IF table_name='work_commitment_reviews' "
                                                    'THEN\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload->'reads','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'artifact_id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'artifact_id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    ' RETURN links;\n'
                                                    'END;\n'
                                                    '$function$\n',
 'protect_work_member()': 'CREATE OR REPLACE FUNCTION public.protect_work_member()\n'
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
                          "('work.task.create','work.task.assign','work.task.accept','work.commitment.accept','work.task.start','work.task.submit','work.task.review','work.status_update.create') "
                          'OR r.subject_type IN '
                          "('work_task','work_commitment','project_status_update'))) INTO scoped; "
                          'END IF;\n'
                          " IF TG_OP<>'INSERT' THEN SELECT EXISTS(SELECT 1 FROM "
                          'public.action_receipts r WHERE r.tenant_id=OLD.tenant_id AND '
                          'r.id=OLD.receipt_id AND (r.operation IN '
                          "('work.task.create','work.task.assign','work.task.accept','work.commitment.accept','work.task.start','work.task.submit','work.task.review','work.status_update.create') "
                          'OR r.subject_type IN '
                          "('work_task','work_commitment','project_status_update'))) INTO "
                          'old_scoped; END IF;\n'
                          " IF TG_OP<>'INSERT' AND (scoped OR old_scoped) THEN\n"
                          "  IF TG_OP='UPDATE' AND TG_TABLE_NAME='outbox_events' AND "
                          "(to_jsonb(NEW)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) "
                          'IS NOT DISTINCT FROM '
                          "(to_jsonb(OLD)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) "
                          'THEN RETURN NEW; END IF;\n'
                          "  RAISE EXCEPTION 'Work audit event or original key immutable' USING "
                          "ERRCODE='23514'; END IF;\n"
                          " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
                          'END;\n'
                          '$function$\n',
 'protect_work_receipt()': 'CREATE OR REPLACE FUNCTION public.protect_work_receipt()\n'
                           ' RETURNS trigger\n'
                           ' LANGUAGE plpgsql\n'
                           ' SECURITY DEFINER\n'
                           " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                           'AS $function$\n'
                           '\n'
                           'DECLARE scoped boolean=false;\n'
                           'BEGIN\n'
                           " IF TG_OP<>'INSERT' THEN scoped=OLD.operation IN "
                           "('work.task.create','work.task.assign','work.task.accept','work.commitment.accept','work.task.start','work.task.submit','work.task.review','work.status_update.create') "
                           'OR OLD.subject_type IN '
                           "('work_task','work_commitment','project_status_update'); END IF;\n"
                           " IF TG_OP<>'DELETE' THEN scoped=scoped OR NEW.operation IN "
                           "('work.task.create','work.task.assign','work.task.accept','work.commitment.accept','work.task.start','work.task.submit','work.task.review','work.status_update.create') "
                           'OR NEW.subject_type IN '
                           "('work_task','work_commitment','project_status_update'); END IF;\n"
                           " IF scoped AND TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Work receipt "
                           "immutable' USING ERRCODE='23514'; END IF;\n"
                           " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
                           'END;\n'
                           '$function$\n',
 'require_work_member()': 'CREATE OR REPLACE FUNCTION public.require_work_member()\n'
                          ' RETURNS trigger\n'
                          ' LANGUAGE plpgsql\n'
                          ' SECURITY DEFINER\n'
                          " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                          'AS $function$\n'
                          '\n'
                          'DECLARE r public.action_receipts;\n'
                          'BEGIN\n'
                          " IF TG_TABLE_NAME='action_receipts' THEN r=NEW; ELSE SELECT * INTO r "
                          'FROM public.action_receipts WHERE tenant_id=NEW.tenant_id AND '
                          'id=NEW.receipt_id; END IF;\n'
                          ' IF r.operation IN '
                          "('work.task.create','work.task.assign','work.task.accept','work.commitment.accept','work.task.start','work.task.submit','work.task.review','work.status_update.create') "
                          'OR r.subject_type IN '
                          "('work_task','work_commitment','project_status_update') THEN PERFORM "
                          'public.assert_work_management_members(r.tenant_id,r.subject_id,r.subject_type::text); '
                          'END IF;\n'
                          ' RETURN NULL;\n'
                          'END;\n'
                          '$function$\n',
 'work_receipt_project_visible(uuid,uuid,uuid,text,uuid,integer,uuid,uuid)': 'CREATE OR REPLACE '
                                                                             'FUNCTION '
                                                                             'public.work_receipt_project_visible(t '
                                                                             'uuid, c uuid, p '
                                                                             'uuid, kind text, '
                                                                             'target uuid, rev '
                                                                             'integer, receipt '
                                                                             'uuid, actor uuid)\n'
                                                                             ' RETURNS boolean\n'
                                                                             ' LANGUAGE plpgsql\n'
                                                                             ' STABLE STRICT '
                                                                             'SECURITY DEFINER\n'
                                                                             ' SET search_path TO '
                                                                             "'pg_catalog', "
                                                                             "'public', 'pg_temp'\n"
                                                                             'AS $function$\n'
                                                                             'DECLARE project_id '
                                                                             'uuid; project_owner '
                                                                             'uuid; '
                                                                             'project_visibility '
                                                                             'text; actual_project '
                                                                             'public.projects;\n'
                                                                             'BEGIN\n'
                                                                             ' IF NOT '
                                                                             'public.category_access(t,c) '
                                                                             'THEN RETURN false; '
                                                                             'END IF;\n'
                                                                             " IF kind='work_task' "
                                                                             'THEN\n'
                                                                             '  SELECT '
                                                                             'x.project_id,x.owner_id,x.visibility '
                                                                             'INTO '
                                                                             'project_id,project_owner,project_visibility\n'
                                                                             '   FROM '
                                                                             'public.work_task_versions '
                                                                             'x WHERE '
                                                                             'x.tenant_id=t AND '
                                                                             'x.category_id=c AND '
                                                                             'x.product_id=p AND '
                                                                             'x.id=target AND '
                                                                             'x.revision=rev AND '
                                                                             'x.receipt_id=receipt '
                                                                             'AND '
                                                                             'x.actor_id=actor;\n'
                                                                             ' ELSIF '
                                                                             "kind='work_commitment' "
                                                                             'THEN\n'
                                                                             '  SELECT '
                                                                             'x.project_id,x.owner_id,x.visibility '
                                                                             'INTO '
                                                                             'project_id,project_owner,project_visibility\n'
                                                                             '   FROM '
                                                                             'public.work_commitment_versions '
                                                                             'x WHERE '
                                                                             'x.tenant_id=t AND '
                                                                             'x.category_id=c AND '
                                                                             'x.product_id=p AND '
                                                                             'x.id=target AND '
                                                                             'x.revision=rev AND '
                                                                             'x.receipt_id=receipt '
                                                                             'AND '
                                                                             'x.actor_id=actor;\n'
                                                                             ' ELSIF '
                                                                             "kind='project_status_update' "
                                                                             'THEN\n'
                                                                             '  SELECT '
                                                                             'x.project_id,x.owner_id,x.visibility '
                                                                             'INTO '
                                                                             'project_id,project_owner,project_visibility\n'
                                                                             '   FROM '
                                                                             'public.project_status_updates '
                                                                             'x WHERE '
                                                                             'x.tenant_id=t AND '
                                                                             'x.category_id=c AND '
                                                                             'x.product_id=p AND '
                                                                             'x.id=target AND '
                                                                             'x.revision=rev AND '
                                                                             'x.receipt_id=receipt '
                                                                             'AND '
                                                                             'x.actor_id=actor;\n'
                                                                             ' ELSIF '
                                                                             "kind='work_commitment_review' "
                                                                             'THEN\n'
                                                                             '  SELECT '
                                                                             'x.project_id,x.owner_id,x.visibility '
                                                                             'INTO '
                                                                             'project_id,project_owner,project_visibility\n'
                                                                             '   FROM '
                                                                             'public.work_commitment_reviews '
                                                                             'x WHERE '
                                                                             'x.tenant_id=t AND '
                                                                             'x.category_id=c AND '
                                                                             'x.product_id=p AND '
                                                                             'x.id=target AND '
                                                                             'x.revision=rev AND '
                                                                             'x.receipt_id=receipt '
                                                                             'AND '
                                                                             'x.actor_id=actor;\n'
                                                                             ' ELSE RETURN false; '
                                                                             'END IF;\n'
                                                                             ' IF project_id IS '
                                                                             'NULL THEN RETURN '
                                                                             'false; END IF;\n'
                                                                             ' SELECT * INTO '
                                                                             'actual_project FROM '
                                                                             'public.projects x '
                                                                             'WHERE x.tenant_id=t '
                                                                             'AND x.category_id=c '
                                                                             'AND x.product_id=p '
                                                                             'AND x.id=project_id '
                                                                             'AND '
                                                                             'x.owner_id=project_owner '
                                                                             'AND '
                                                                             'x.visibility=project_visibility;\n'
                                                                             ' RETURN '
                                                                             'actual_project.id IS '
                                                                             'NOT NULL AND '
                                                                             "(actual_project.visibility='category' "
                                                                             'OR '
                                                                             'actual_project.owner_id=public.scope_requester() '
                                                                             'OR EXISTS(\n'
                                                                             '  SELECT 1 FROM '
                                                                             'public.object_audiences '
                                                                             'a WHERE '
                                                                             'a.tenant_id=t AND '
                                                                             'a.category_id=c AND '
                                                                             "a.object_type='projects'\n"
                                                                             '   AND '
                                                                             'a.subject_id=actual_project.id '
                                                                             'AND '
                                                                             'a.owner_id=actual_project.owner_id '
                                                                             'AND '
                                                                             'a.principal_id=public.scope_requester()));\n'
                                                                             'END;\n'
                                                                             '$function$\n'}

EXTERNAL_WAIT_FUNCTIONS = {'assert_work_management_members(uuid,uuid,text)': 'CREATE OR REPLACE FUNCTION '
                                                   'public.assert_work_management_members(t uuid, '
                                                   'target uuid, kind text)\n'
                                                   ' RETURNS void\n'
                                                   ' LANGUAGE plpgsql\n'
                                                   ' SECURITY DEFINER\n'
                                                   " SET search_path TO 'pg_catalog', 'public', "
                                                   "'pg_temp'\n"
                                                   'AS $function$\n'
                                                   '\n'
                                                   'DECLARE v record; r public.action_receipts; c '
                                                   'public.confirmations; expected_status text; '
                                                   'event_name text; expected_result jsonb;\n'
                                                   'BEGIN\n'
                                                   '\n'
                                                   " IF kind='work_task' THEN SELECT * INTO STRICT "
                                                   'v FROM public.work_task_versions WHERE '
                                                   'tenant_id=t AND id=target;\n'
                                                   " ELSIF kind='work_commitment' THEN SELECT * "
                                                   'INTO STRICT v FROM '
                                                   'public.work_commitment_versions WHERE '
                                                   'tenant_id=t AND id=target;\n'
                                                   " ELSIF kind='project_status_update' THEN "
                                                   'SELECT * INTO STRICT v FROM '
                                                   'public.project_status_updates WHERE '
                                                   'tenant_id=t AND id=target;\n'
                                                   " ELSIF kind='external_wait' THEN SELECT * INTO "
                                                   'STRICT v FROM public.external_wait_versions '
                                                   'WHERE tenant_id=t AND id=target;\n'
                                                   " ELSE RAISE EXCEPTION 'Unknown work subject' "
                                                   "USING ERRCODE='23514'; END IF;\n"
                                                   '\n'
                                                   ' expected_status=CASE WHEN kind IN '
                                                   "('work_task','external_wait') THEN "
                                                   "v.body->>'state' ELSE 'recorded' END;\n"
                                                   ' '
                                                   "expected_result=jsonb_build_object('id',v.id,'revision',v.revision,'status',expected_status);\n"
                                                   " IF kind='work_task' THEN "
                                                   "expected_result=expected_result||jsonb_build_object('task_id',v.task_id,'state',v.state,'project_id',v.project_id);\n"
                                                   " ELSIF kind='work_commitment' THEN "
                                                   "expected_result=expected_result||jsonb_build_object('task_id',v.task_id,'recipient_id',v.recipient_id);\n"
                                                   " ELSIF kind='external_wait' THEN "
                                                   "expected_result=expected_result||jsonb_build_object('wait_id',v.wait_id,'state',v.state,'project_id',v.project_id);\n"
                                                   ' ELSE '
                                                   "expected_result=expected_result||jsonb_build_object('project_id',v.project_id); "
                                                   'END IF;\n'
                                                   ' event_name=CASE v.operation WHEN '
                                                   "'work.task.create' THEN 'task.created' WHEN "
                                                   "'work.task.assign' THEN 'task.assigned'\n"
                                                   "  WHEN 'work.task.accept' THEN 'task.accepted' "
                                                   "WHEN 'work.task.start' THEN 'task.started'\n"
                                                   "  WHEN 'work.task.submit' THEN "
                                                   "'task.submitted' WHEN 'work.task.review' THEN "
                                                   "'task.reviewed'\n"
                                                   "  WHEN 'work.commitment.accept' THEN "
                                                   "'commitment.accepted' WHEN "
                                                   "'work.status_update.create' THEN "
                                                   "'project.status_updated' WHEN "
                                                   "'work.external_wait.record' THEN "
                                                   "'external_wait.recorded' END;\n"
                                                   ' SELECT * INTO STRICT r FROM '
                                                   'public.action_receipts WHERE tenant_id=t AND '
                                                   'id=v.receipt_id;\n'
                                                   ' IF '
                                                   'ROW(r.category_id,r.product_id,r.command_id,r.confirmation_id,r.actor_id,r.requester_id,r.operation,r.subject_type,r.subject_id,r.subject_revision,r.visibility,r.request_digest,r.intent_digest)\n'
                                                   '  IS DISTINCT FROM '
                                                   'ROW(v.category_id,v.product_id,v.command_id,v.confirmation_id,v.actor_id,v.requester_id,v.operation,kind::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)\n'
                                                   '  OR r.result IS DISTINCT FROM '
                                                   'expected_result\n'
                                                   '  OR r.created_at<v.created_at OR event_name '
                                                   'IS NULL\n'
                                                   '  OR (SELECT count(*) FROM '
                                                   'public.action_receipts x WHERE x.tenant_id=t '
                                                   'AND x.operation=v.operation AND '
                                                   'x.subject_type=kind AND x.subject_id=v.id AND '
                                                   'x.subject_revision=v.revision)<>1\n'
                                                   '  OR (SELECT count(*) FROM '
                                                   'public.audit_entries a WHERE a.tenant_id=t AND '
                                                   'a.receipt_id=r.id)<>1\n'
                                                   '  OR NOT EXISTS(SELECT 1 FROM '
                                                   'public.audit_entries a WHERE a.tenant_id=t AND '
                                                   'a.receipt_id=r.id AND '
                                                   'a.category_id=v.category_id AND '
                                                   'a.actor_id=v.actor_id AND '
                                                   'a.operation=v.operation AND '
                                                   'a.created_at>=v.created_at)\n'
                                                   '  OR (SELECT count(*) FROM '
                                                   'public.outbox_events e WHERE e.tenant_id=t AND '
                                                   'e.receipt_id=r.id)<>1\n'
                                                   '  OR NOT EXISTS(SELECT 1 FROM '
                                                   'public.outbox_events e WHERE e.tenant_id=t AND '
                                                   'e.receipt_id=r.id AND '
                                                   'e.category_id=v.category_id AND '
                                                   'e.actor_id=v.actor_id AND e.type=event_name '
                                                   'AND e.subject_id=v.id AND '
                                                   'e.subject_revision=v.revision AND '
                                                   'e.schema_version=1 AND '
                                                   'e.correlation_id=coalesce(r.agent_run_id,r.run_id,v.command_id) '
                                                   'AND e.created_at>=v.created_at)\n'
                                                   "  OR v.command->>'original_key_sha256' IS NULL "
                                                   "OR v.command->>'original_key_sha256' !~ "
                                                   "'^[a-f0-9]{64}$'\n"
                                                   "  OR v.command->'envelope' ? 'idempotency_key' "
                                                   "OR v.command->'envelope'->'payload' ? "
                                                   "'confirmation_token'\n"
                                                   '  OR NOT EXISTS(SELECT 1 FROM '
                                                   'public.request_keys k WHERE k.tenant_id=t AND '
                                                   'k.category_id=v.category_id AND '
                                                   'k.actor_id=v.actor_id AND k.receipt_id=r.id '
                                                   'AND k.digest=v.request_digest AND '
                                                   "encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.command->>'original_key_sha256') "
                                                   'THEN\n'
                                                   "  RAISE EXCEPTION 'Work fact original common "
                                                   "group mismatch' USING ERRCODE='23514'; END "
                                                   'IF;\n'
                                                   ' IF v.operation NOT IN '
                                                   "('work.task.create','work.external_wait.record') "
                                                   'THEN\n'
                                                   '  SELECT * INTO STRICT c FROM '
                                                   'public.confirmations WHERE tenant_id=t AND '
                                                   'id=v.confirmation_id;\n'
                                                   '  IF c.consumed IS DISTINCT FROM true OR '
                                                   'ROW(c.category_id,c.product_id,c.actor_id,c.operation)\n'
                                                   '   IS DISTINCT FROM '
                                                   'ROW(v.category_id,v.product_id,v.actor_id,v.operation)\n'
                                                   '   OR c.subject_type IS DISTINCT FROM '
                                                   "'product' OR c.subject_id IS DISTINCT FROM "
                                                   'v.product_id\n'
                                                   '   OR c.revision::text IS DISTINCT FROM '
                                                   "v.command->'envelope'->>'expected_revision'\n"
                                                   '   OR c.snapshot IS DISTINCT FROM '
                                                   "v.command->'review' OR "
                                                   'c.created_at>v.created_at\n'
                                                   '   OR c.expires_at IS NULL OR '
                                                   'v.created_at>=c.expires_at OR '
                                                   'r.created_at>=c.expires_at\n'
                                                   '   OR r.run_id IS NOT NULL OR r.agent_run_id '
                                                   'IS NOT NULL THEN\n'
                                                   "   RAISE EXCEPTION 'Work T1 needs its actual "
                                                   "consumed confirmation' USING ERRCODE='23514'; "
                                                   'END IF;\n'
                                                   ' END IF;\n'
                                                   'END;\n'
                                                   '$function$\n',
 'assert_work_management_write(uuid,uuid,text)': 'CREATE OR REPLACE FUNCTION '
                                                 'public.assert_work_management_write(t uuid, '
                                                 'target uuid, kind text)\n'
                                                 ' RETURNS void\n'
                                                 ' LANGUAGE plpgsql\n'
                                                 ' SECURITY DEFINER\n'
                                                 " SET search_path TO 'pg_catalog', 'public', "
                                                 "'pg_temp'\n"
                                                 'AS $function$\n'
                                                 '\n'
                                                 'DECLARE v record; p public.projects; envelope '
                                                 'jsonb; ref jsonb; basis jsonb; vx xid; rx xid; '
                                                 'cx xid;\n'
                                                 'BEGIN\n'
                                                 '\n'
                                                 " IF kind='work_task' THEN SELECT * INTO STRICT v "
                                                 'FROM public.work_task_versions WHERE tenant_id=t '
                                                 'AND id=target;\n'
                                                 " ELSIF kind='work_commitment' THEN SELECT * INTO "
                                                 'STRICT v FROM public.work_commitment_versions '
                                                 'WHERE tenant_id=t AND id=target;\n'
                                                 " ELSIF kind='project_status_update' THEN SELECT "
                                                 '* INTO STRICT v FROM '
                                                 'public.project_status_updates WHERE tenant_id=t '
                                                 'AND id=target;\n'
                                                 " ELSIF kind='external_wait' THEN SELECT * INTO "
                                                 'STRICT v FROM public.external_wait_versions '
                                                 'WHERE tenant_id=t AND id=target;\n'
                                                 " ELSE RAISE EXCEPTION 'Unknown work subject' "
                                                 "USING ERRCODE='23514'; END IF;\n"
                                                 '\n'
                                                 " IF kind='work_task' THEN SELECT xmin INTO vx "
                                                 'FROM public.work_task_versions WHERE tenant_id=t '
                                                 'AND id=target;\n'
                                                 " ELSIF kind='work_commitment' THEN SELECT xmin "
                                                 'INTO vx FROM public.work_commitment_versions '
                                                 'WHERE tenant_id=t AND id=target;\n'
                                                 " ELSIF kind='external_wait' THEN SELECT xmin "
                                                 'INTO vx FROM public.external_wait_versions WHERE '
                                                 'tenant_id=t AND id=target;\n'
                                                 ' ELSE SELECT xmin INTO vx FROM '
                                                 'public.project_status_updates WHERE tenant_id=t '
                                                 'AND id=target; END IF;\n'
                                                 ' SELECT * INTO STRICT p FROM public.projects '
                                                 'WHERE tenant_id=t AND id=v.project_id;\n'
                                                 ' SELECT xmin INTO rx FROM public.action_receipts '
                                                 'WHERE tenant_id=t AND id=v.receipt_id;\n'
                                                 ' PERFORM '
                                                 'public.assert_work_management_members(t,target,kind);\n'
                                                 " envelope=v.command->'envelope';\n"
                                                 '\n'
                                                 " IF kind='work_task' THEN PERFORM "
                                                 'public.assert_work_task_g0_source(t,target);\n'
                                                 " ELSIF v.source_basis ? 'g0_open_item' THEN\n"
                                                 "  RAISE EXCEPTION 'Only a task may use a native "
                                                 "G0 source basis' USING ERRCODE='23514'; END IF;\n"
                                                 ' IF '
                                                 'ROW(p.category_id,p.product_id,p.owner_id,p.visibility) '
                                                 'IS DISTINCT FROM '
                                                 'ROW(v.category_id,v.product_id,v.owner_id,v.visibility)\n'
                                                 '  OR v.actor_id IS DISTINCT FROM '
                                                 'public.scope_actor() OR v.requester_id IS '
                                                 'DISTINCT FROM public.scope_requester()\n'
                                                 '  OR v.writer_id<>v.actor_id OR vx IS DISTINCT '
                                                 'FROM rx OR NOT '
                                                 'public.category_access(t,v.category_id,true)\n'
                                                 '  OR NOT EXISTS(SELECT 1 FROM public.principals '
                                                 'a WHERE a.tenant_id=t AND a.id=v.actor_id AND '
                                                 'a.active)\n'
                                                 '  OR NOT EXISTS(SELECT 1 FROM public.principals '
                                                 'a WHERE a.tenant_id=t AND a.id=v.requester_id '
                                                 "AND a.kind='human' AND a.active)\n"
                                                 "  OR envelope->>'operation' IS DISTINCT FROM "
                                                 "v.operation OR envelope->>'command_id' IS "
                                                 'DISTINCT FROM v.command_id::text\n'
                                                 "  OR envelope->>'category_id' IS DISTINCT FROM "
                                                 "v.category_id::text OR envelope->>'product_id' "
                                                 'IS DISTINCT FROM v.product_id::text\n'
                                                 "  OR envelope->'payload'->>'project_id' IS "
                                                 'DISTINCT FROM v.project_id::text\n'
                                                 "  OR v.command->'review'->'declaration' IS "
                                                 "DISTINCT FROM envelope->'payload'\n"
                                                 "  OR v.command->'review'->>'operation' IS "
                                                 'DISTINCT FROM v.operation\n'
                                                 "  OR v.command->'review'->'sources' IS DISTINCT "
                                                 'FROM v.sources\n'
                                                 "  OR v.command->'review'->'source_basis' IS "
                                                 'DISTINCT FROM v.source_basis\n'
                                                 "  OR (v.body #- '{recorded_at}' #- "
                                                 "'{actual_start,recorded_at}' #- "
                                                 "'{submission,time,recorded_at}' #- "
                                                 "'{review,time,recorded_at}') IS DISTINCT FROM "
                                                 "v.command->'review'->'after'\n"
                                                 '  OR NOT EXISTS(SELECT 1 FROM public.products x '
                                                 'WHERE x.tenant_id=t AND '
                                                 'x.category_id=v.category_id AND '
                                                 'x.id=v.product_id AND '
                                                 "x.revision::text=envelope->>'expected_revision')\n"
                                                 "  OR NOT COALESCE(envelope->'source_read_set' @> "
                                                 'v.reads,false) OR NOT COALESCE(v.reads @> '
                                                 "(envelope->'source_read_set'),false)\n"
                                                 '  OR '
                                                 "jsonb_array_length(envelope->'source_read_set')<>jsonb_array_length(v.reads)\n"
                                                 '  OR NOT '
                                                 'public.direct_source_set_visible(t,v.category_id,v.product_id,v.reads)\n'
                                                 '  OR (v.operation NOT IN '
                                                 "('work.task.create','work.external_wait.record') "
                                                 'AND (v.actor_id<>v.requester_id OR NOT '
                                                 'EXISTS(SELECT 1 FROM public.principals a WHERE '
                                                 'a.tenant_id=t AND a.id=v.actor_id AND '
                                                 "a.kind='human')))\n"
                                                 '  OR (v.operation IN '
                                                 "('work.task.create','work.external_wait.record') "
                                                 'AND v.actor_id<>v.requester_id AND NOT '
                                                 'EXISTS(SELECT 1 FROM public.action_receipts r '
                                                 'WHERE r.tenant_id=t AND r.id=v.receipt_id AND '
                                                 'coalesce(r.agent_run_id,r.run_id) IS NOT NULL))\n'
                                                 '  OR EXISTS(SELECT 1 FROM public.audit_entries x '
                                                 'WHERE x.tenant_id=t AND '
                                                 'x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT '
                                                 'FROM vx)\n'
                                                 '  OR EXISTS(SELECT 1 FROM public.outbox_events x '
                                                 'WHERE x.tenant_id=t AND '
                                                 'x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT '
                                                 'FROM vx)\n'
                                                 '  OR NOT EXISTS(SELECT 1 FROM '
                                                 'public.request_keys k WHERE k.tenant_id=t AND '
                                                 'k.receipt_id=v.receipt_id AND '
                                                 'k.actor_id=v.actor_id AND '
                                                 'k.digest=v.request_digest AND k.xmin=vx AND '
                                                 "encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.command->>'original_key_sha256') "
                                                 'THEN\n'
                                                 "  RAISE EXCEPTION 'Work fact requires actual "
                                                 "project actor and one transaction' USING "
                                                 "ERRCODE='23514'; END IF;\n"
                                                 ' IF v.confirmation_id IS NOT NULL THEN\n'
                                                 '  SELECT xmin INTO cx FROM public.confirmations '
                                                 'WHERE tenant_id=t AND id=v.confirmation_id;\n'
                                                 '  IF cx IS DISTINCT FROM vx THEN RAISE EXCEPTION '
                                                 "'Work confirmation consumption must share its "
                                                 "new fact transaction' USING ERRCODE='23514'; END "
                                                 'IF;\n'
                                                 ' END IF;\n'
                                                 " IF jsonb_typeof(v.source_basis->'artifacts') IS "
                                                 "DISTINCT FROM 'array' THEN\n"
                                                 "  RAISE EXCEPTION 'Work direct source metadata "
                                                 "required' USING ERRCODE='23514'; END IF;\n"
                                                 ' FOR basis IN SELECT value FROM '
                                                 "jsonb_array_elements(v.source_basis->'artifacts') "
                                                 'LOOP\n'
                                                 '  IF NOT EXISTS(SELECT 1 FROM '
                                                 'public.artifact_versions a WHERE a.tenant_id=t '
                                                 'AND a.category_id=v.category_id\n'
                                                 '   AND (a.product_id IS NULL OR '
                                                 'a.product_id=v.product_id) AND '
                                                 "a.id::text=basis->>'id'\n"
                                                 "   AND a.revision::text=basis->>'revision' AND "
                                                 "a.content_hash=basis->>'hash' AND "
                                                 "a.status='active'\n"
                                                 "   AND a.status=basis->>'status' AND "
                                                 "a.owner_id::text=basis->>'owner_id' AND "
                                                 "a.visibility=basis->>'visibility'\n"
                                                 "   AND (v.visibility='private' OR "
                                                 "a.visibility<>'private')\n"
                                                 "   AND (NOT(basis ? 'original') OR EXISTS(SELECT "
                                                 '1 FROM public.original_security sec\n'
                                                 '    WHERE sec.tenant_id=t AND '
                                                 'sec.original_id=a.original_id AND '
                                                 "sec.original_id::text=basis->'original'->>'id'\n"
                                                 '     AND '
                                                 "sec.epoch::text=basis->'original'->>'epoch' AND "
                                                 "sec.source_state='active' AND "
                                                 "sec.disposition='active'))) THEN\n"
                                                 "   RAISE EXCEPTION 'Retained work source "
                                                 "metadata changed' USING ERRCODE='23514'; END "
                                                 'IF;\n'
                                                 ' END LOOP;\n'
                                                 ' FOR ref IN SELECT value FROM '
                                                 'jsonb_array_elements(v.sources) LOOP\n'
                                                 '  SELECT value INTO STRICT basis FROM '
                                                 "jsonb_array_elements(v.source_basis->'artifacts') "
                                                 "WHERE value->>'id'=ref->>'id';\n"
                                                 "  IF ref->>'kind' IS DISTINCT FROM 'artifact' OR "
                                                 'NOT EXISTS(SELECT 1 FROM '
                                                 'jsonb_array_elements(v.reads) rd WHERE '
                                                 "rd->>'artifact_id'=ref->>'id' AND "
                                                 "rd->'expected_revision'=ref->'revision')\n"
                                                 '   OR NOT EXISTS(SELECT 1 FROM '
                                                 'public.artifact_versions a WHERE a.tenant_id=t '
                                                 'AND a.category_id=v.category_id\n'
                                                 "    AND a.id::text=ref->>'id' AND "
                                                 "a.revision::text=ref->>'revision' AND "
                                                 "a.status='active'\n"
                                                 "    AND a.revision::text=basis->>'revision' AND "
                                                 "a.content_hash=basis->>'hash' AND "
                                                 "a.status=basis->>'status'\n"
                                                 "    AND a.owner_id::text=basis->>'owner_id' AND "
                                                 "a.visibility=basis->>'visibility'\n"
                                                 "    AND (v.visibility='private' OR "
                                                 "a.visibility<>'private')\n"
                                                 '    AND ((a.original_id IS NULL AND '
                                                 "basis->>'source_kind'='registered_native_text' "
                                                 'AND EXISTS(\n'
                                                 '      SELECT 1 FROM public.action_receipts r '
                                                 'WHERE r.tenant_id=t AND r.subject_id=a.id AND '
                                                 'r.subject_revision=a.revision\n'
                                                 "       AND r.subject_type='artifact' AND "
                                                 "r.operation='evidence.artifact.register' AND "
                                                 "r.id::text=basis->'registration'->>'receipt_id'\n"
                                                 '       AND '
                                                 "r.actor_id::text=basis->'registration'->>'actor_id' "
                                                 'AND '
                                                 "r.requester_id::text=basis->'registration'->>'requester_id'\n"
                                                 '       AND r.run_id::text IS NOT DISTINCT FROM '
                                                 "basis->'registration'->>'run_id'))\n"
                                                 '     OR (a.original_id IS NOT NULL AND '
                                                 "basis->>'source_kind'='uploaded_original' AND "
                                                 'EXISTS(\n'
                                                 '      SELECT 1 FROM public.uploaded_originals o '
                                                 'JOIN public.original_security sec ON '
                                                 'sec.tenant_id=o.tenant_id AND '
                                                 'sec.original_id=o.id\n'
                                                 '       WHERE o.tenant_id=t AND '
                                                 'o.category_id=v.category_id AND '
                                                 'o.id=a.original_id AND '
                                                 "o.id::text=basis->'original'->>'id'\n"
                                                 "        AND o.status='parsed' AND "
                                                 "sec.epoch::text=basis->'original'->>'epoch' AND "
                                                 "sec.source_state='active' AND "
                                                 "sec.disposition='active'\n"
                                                 '        AND '
                                                 "sec.source_state=basis->'original'->>'source_state' "
                                                 'AND '
                                                 "sec.disposition=basis->'original'->>'disposition'\n"
                                                 "        AND (v.visibility='private' OR "
                                                 "o.visibility<>'private'))))) THEN\n"
                                                 "   RAISE EXCEPTION 'Work source metadata "
                                                 "security or audience changed' USING "
                                                 "ERRCODE='23514'; END IF;\n"
                                                 ' END LOOP;\n'
                                                 'END;\n'
                                                 '$function$\n',
 'm3_lifecycle_nodes(uuid,uuid,uuid[])': 'CREATE OR REPLACE FUNCTION public.m3_lifecycle_nodes(t '
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
                                         "ARRAY['agent_runs','action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents'] "
                                         'ELSE ARRAY[\n'
                                         '  '
                                         "'artifact_versions','claims','definition_revisions','definition_sources','definition_specs',\n"
                                         '  '
                                         "'proposals','proposal_items','proposal_item_versions','proposal_submissions','proposal_decisions',\n"
                                         '  '
                                         "'category_knowledge_entries','category_knowledge_current','parameter_versions','parameter_current',\n"
                                         '  '
                                         "'evidence_links','promotion_proofs','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents'] "
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
                                         "name<>ALL(ARRAY['native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals']) "
                                         'THEN\n'
                                         '    links=links || '
                                         'public.kernel_lifecycle_links(name,payload);\n'
                                         '   END IF;\n'
                                         '   RETURN NEXT;\n'
                                         '  END LOOP;\n'
                                         ' END LOOP;\n'
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
                                                 "  WHEN 'external_handoff_authorizations' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'external_delivery_intents' THEN "
                                                 "ARRAY['project_id']\n"
                                                 "  WHEN 'external_receipts' THEN "
                                                 "ARRAY['project_id']\n"
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
                                                 'links=array_append(links,(payload->>key)::uuid); '
                                                 'END IF;\n'
                                                 ' END LOOP;\n'
                                                 ' RETURN links;\n'
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
                                                    ' -- Do not scan its declaration, body, reason '
                                                    'or arbitrary JSON UUID values.\n'
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
                                                    ' IF table_name IN '
                                                    "('external_handoff_authorizations','external_delivery_intents') "
                                                    'THEN\n'
                                                    '  -- Only closed, owner-verified mapping and '
                                                    'manifest references are source edges.\n'
                                                    '  container=CASE WHEN '
                                                    "table_name='external_handoff_authorizations' "
                                                    "THEN payload#>'{body,declaration}' ELSE "
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
                                                    "   IF item->'artifact'->>'id' IS NOT NULL "
                                                    'THEN '
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
                                                    "payload#>>'{body,plan_task,id}' IS NOT NULL "
                                                    'THEN\n'
                                                    '   '
                                                    "links=array_append(links,(payload#>>'{body,plan_task,id}')::uuid);\n"
                                                    '  END IF;\n'
                                                    "  IF table_name='work_commitment_versions' "
                                                    'THEN\n'
                                                    "   SELECT coalesce(array_agg(id),'{}') INTO "
                                                    'extra FROM public.work_task_versions\n'
                                                    '    WHERE tenant_id=t AND category_id=c AND '
                                                    "task_id=(payload->>'task_id')::uuid AND "
                                                    "revision=(payload->>'task_revision')::integer;\n"
                                                    '   links=links||extra;\n'
                                                    "  ELSIF table_name='project_status_updates' "
                                                    'THEN\n'
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
                                                    " IF table_name='work_commitment_reviews' "
                                                    'THEN\n'
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
                                                    "   SELECT coalesce(array_agg(id),'{}') INTO "
                                                    'extra FROM public.external_wait_versions\n'
                                                    '    WHERE tenant_id=t AND category_id=c AND '
                                                    "wait_id=(container->>'id')::uuid AND "
                                                    "revision=(container->>'revision')::integer;\n"
                                                    '   links=links||extra;\n'
                                                    '  END IF;\n'
                                                    ' END IF;\n'
                                                    ' RETURN links;\n'
                                                    'END;\n'
                                                    '$function$\n',
 'protect_work_member()': 'CREATE OR REPLACE FUNCTION public.protect_work_member()\n'
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
                          "('work.task.create','work.task.assign','work.task.accept','work.commitment.accept','work.task.start','work.task.submit','work.task.review','work.status_update.create','work.external_wait.record') "
                          'OR r.subject_type IN '
                          "('work_task','work_commitment','project_status_update','external_wait'))) "
                          'INTO scoped; END IF;\n'
                          " IF TG_OP<>'INSERT' THEN SELECT EXISTS(SELECT 1 FROM "
                          'public.action_receipts r WHERE r.tenant_id=OLD.tenant_id AND '
                          'r.id=OLD.receipt_id AND (r.operation IN '
                          "('work.task.create','work.task.assign','work.task.accept','work.commitment.accept','work.task.start','work.task.submit','work.task.review','work.status_update.create','work.external_wait.record') "
                          'OR r.subject_type IN '
                          "('work_task','work_commitment','project_status_update','external_wait'))) "
                          'INTO old_scoped; END IF;\n'
                          " IF TG_OP<>'INSERT' AND (scoped OR old_scoped) THEN\n"
                          "  IF TG_OP='UPDATE' AND TG_TABLE_NAME='outbox_events' AND "
                          "(to_jsonb(NEW)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) "
                          'IS NOT DISTINCT FROM '
                          "(to_jsonb(OLD)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) "
                          'THEN RETURN NEW; END IF;\n'
                          "  RAISE EXCEPTION 'Work audit event or original key immutable' USING "
                          "ERRCODE='23514'; END IF;\n"
                          " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
                          'END;\n'
                          '$function$\n',
 'protect_work_receipt()': 'CREATE OR REPLACE FUNCTION public.protect_work_receipt()\n'
                           ' RETURNS trigger\n'
                           ' LANGUAGE plpgsql\n'
                           ' SECURITY DEFINER\n'
                           " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                           'AS $function$\n'
                           '\n'
                           'DECLARE scoped boolean=false;\n'
                           'BEGIN\n'
                           " IF TG_OP<>'INSERT' THEN scoped=OLD.operation IN "
                           "('work.task.create','work.task.assign','work.task.accept','work.commitment.accept','work.task.start','work.task.submit','work.task.review','work.status_update.create','work.external_wait.record') "
                           'OR OLD.subject_type IN '
                           "('work_task','work_commitment','project_status_update','external_wait'); "
                           'END IF;\n'
                           " IF TG_OP<>'DELETE' THEN scoped=scoped OR NEW.operation IN "
                           "('work.task.create','work.task.assign','work.task.accept','work.commitment.accept','work.task.start','work.task.submit','work.task.review','work.status_update.create','work.external_wait.record') "
                           'OR NEW.subject_type IN '
                           "('work_task','work_commitment','project_status_update','external_wait'); "
                           'END IF;\n'
                           " IF scoped AND TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Work receipt "
                           "immutable' USING ERRCODE='23514'; END IF;\n"
                           " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
                           'END;\n'
                           '$function$\n',
 'require_work_member()': 'CREATE OR REPLACE FUNCTION public.require_work_member()\n'
                          ' RETURNS trigger\n'
                          ' LANGUAGE plpgsql\n'
                          ' SECURITY DEFINER\n'
                          " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                          'AS $function$\n'
                          '\n'
                          'DECLARE r public.action_receipts;\n'
                          'BEGIN\n'
                          " IF TG_TABLE_NAME='action_receipts' THEN r=NEW; ELSE SELECT * INTO r "
                          'FROM public.action_receipts WHERE tenant_id=NEW.tenant_id AND '
                          'id=NEW.receipt_id; END IF;\n'
                          ' IF r.operation IN '
                          "('work.task.create','work.task.assign','work.task.accept','work.commitment.accept','work.task.start','work.task.submit','work.task.review','work.status_update.create','work.external_wait.record') "
                          'OR r.subject_type IN '
                          "('work_task','work_commitment','project_status_update','external_wait') "
                          'THEN PERFORM '
                          'public.assert_work_management_members(r.tenant_id,r.subject_id,r.subject_type::text); '
                          'END IF;\n'
                          ' RETURN NULL;\n'
                          'END;\n'
                          '$function$\n',
 'work_receipt_project_visible(uuid,uuid,uuid,text,uuid,integer,uuid,uuid)': 'CREATE OR REPLACE '
                                                                             'FUNCTION '
                                                                             'public.work_receipt_project_visible(t '
                                                                             'uuid, c uuid, p '
                                                                             'uuid, kind text, '
                                                                             'target uuid, rev '
                                                                             'integer, receipt '
                                                                             'uuid, actor uuid)\n'
                                                                             ' RETURNS boolean\n'
                                                                             ' LANGUAGE plpgsql\n'
                                                                             ' STABLE STRICT '
                                                                             'SECURITY DEFINER\n'
                                                                             ' SET search_path TO '
                                                                             "'pg_catalog', "
                                                                             "'public', 'pg_temp'\n"
                                                                             'AS $function$\n'
                                                                             'DECLARE project_id '
                                                                             'uuid; project_owner '
                                                                             'uuid; '
                                                                             'project_visibility '
                                                                             'text; actual_project '
                                                                             'public.projects;\n'
                                                                             'BEGIN\n'
                                                                             ' IF NOT '
                                                                             'public.category_access(t,c) '
                                                                             'THEN RETURN false; '
                                                                             'END IF;\n'
                                                                             " IF kind='work_task' "
                                                                             'THEN\n'
                                                                             '  SELECT '
                                                                             'x.project_id,x.owner_id,x.visibility '
                                                                             'INTO '
                                                                             'project_id,project_owner,project_visibility\n'
                                                                             '   FROM '
                                                                             'public.work_task_versions '
                                                                             'x WHERE '
                                                                             'x.tenant_id=t AND '
                                                                             'x.category_id=c AND '
                                                                             'x.product_id=p AND '
                                                                             'x.id=target AND '
                                                                             'x.revision=rev AND '
                                                                             'x.receipt_id=receipt '
                                                                             'AND '
                                                                             'x.actor_id=actor;\n'
                                                                             ' ELSIF '
                                                                             "kind='work_commitment' "
                                                                             'THEN\n'
                                                                             '  SELECT '
                                                                             'x.project_id,x.owner_id,x.visibility '
                                                                             'INTO '
                                                                             'project_id,project_owner,project_visibility\n'
                                                                             '   FROM '
                                                                             'public.work_commitment_versions '
                                                                             'x WHERE '
                                                                             'x.tenant_id=t AND '
                                                                             'x.category_id=c AND '
                                                                             'x.product_id=p AND '
                                                                             'x.id=target AND '
                                                                             'x.revision=rev AND '
                                                                             'x.receipt_id=receipt '
                                                                             'AND '
                                                                             'x.actor_id=actor;\n'
                                                                             ' ELSIF '
                                                                             "kind='project_status_update' "
                                                                             'THEN\n'
                                                                             '  SELECT '
                                                                             'x.project_id,x.owner_id,x.visibility '
                                                                             'INTO '
                                                                             'project_id,project_owner,project_visibility\n'
                                                                             '   FROM '
                                                                             'public.project_status_updates '
                                                                             'x WHERE '
                                                                             'x.tenant_id=t AND '
                                                                             'x.category_id=c AND '
                                                                             'x.product_id=p AND '
                                                                             'x.id=target AND '
                                                                             'x.revision=rev AND '
                                                                             'x.receipt_id=receipt '
                                                                             'AND '
                                                                             'x.actor_id=actor;\n'
                                                                             ' ELSIF '
                                                                             "kind='work_commitment_review' "
                                                                             'THEN\n'
                                                                             '  SELECT '
                                                                             'x.project_id,x.owner_id,x.visibility '
                                                                             'INTO '
                                                                             'project_id,project_owner,project_visibility\n'
                                                                             '   FROM '
                                                                             'public.work_commitment_reviews '
                                                                             'x WHERE '
                                                                             'x.tenant_id=t AND '
                                                                             'x.category_id=c AND '
                                                                             'x.product_id=p AND '
                                                                             'x.id=target AND '
                                                                             'x.revision=rev AND '
                                                                             'x.receipt_id=receipt '
                                                                             'AND '
                                                                             'x.actor_id=actor;\n'
                                                                             ' ELSIF '
                                                                             "kind='external_wait' "
                                                                             'THEN\n'
                                                                             '  SELECT '
                                                                             'x.project_id,x.owner_id,x.visibility '
                                                                             'INTO '
                                                                             'project_id,project_owner,project_visibility '
                                                                             'FROM '
                                                                             'public.external_wait_versions '
                                                                             'x WHERE '
                                                                             'x.tenant_id=t AND '
                                                                             'x.category_id=c AND '
                                                                             'x.product_id=p AND '
                                                                             'x.id=target AND '
                                                                             'x.revision=rev AND '
                                                                             'x.receipt_id=receipt '
                                                                             'AND '
                                                                             'x.actor_id=actor;\n'
                                                                             ' ELSE RETURN false; '
                                                                             'END IF;\n'
                                                                             ' IF project_id IS '
                                                                             'NULL THEN RETURN '
                                                                             'false; END IF;\n'
                                                                             ' SELECT * INTO '
                                                                             'actual_project FROM '
                                                                             'public.projects x '
                                                                             'WHERE x.tenant_id=t '
                                                                             'AND x.category_id=c '
                                                                             'AND x.product_id=p '
                                                                             'AND x.id=project_id '
                                                                             'AND '
                                                                             'x.owner_id=project_owner '
                                                                             'AND '
                                                                             'x.visibility=project_visibility;\n'
                                                                             ' RETURN '
                                                                             'actual_project.id IS '
                                                                             'NOT NULL AND '
                                                                             "(actual_project.visibility='category' "
                                                                             'OR '
                                                                             'actual_project.owner_id=public.scope_requester() '
                                                                             'OR EXISTS(\n'
                                                                             '  SELECT 1 FROM '
                                                                             'public.object_audiences '
                                                                             'a WHERE '
                                                                             'a.tenant_id=t AND '
                                                                             'a.category_id=c AND '
                                                                             "a.object_type='projects'\n"
                                                                             '   AND '
                                                                             'a.subject_id=actual_project.id '
                                                                             'AND '
                                                                             'a.owner_id=actual_project.owner_id '
                                                                             'AND '
                                                                             'a.principal_id=public.scope_requester()));\n'
                                                                             'END;\n'
                                                                             '$function$\n'}

SCHEMA_SQL = ('\n'
 'CREATE TABLE external_wait_versions (\n'
 '\twait_id UUID NOT NULL, \n'
 '\tprevious_id UUID, \n'
 '\tprevious_revision INTEGER, \n'
 '\taction VARCHAR(32) NOT NULL, \n'
 '\tstate VARCHAR(16) NOT NULL, \n'
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
 '\tproduct_id UUID NOT NULL, \n'
 '\tproject_id UUID NOT NULL, \n'
 '\towner_id UUID NOT NULL, \n'
 '\tvisibility VARCHAR(16) NOT NULL, \n'
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
 '\tUNIQUE (tenant_id, id), \n'
 '\tUNIQUE (tenant_id, receipt_id), \n'
 '\tUNIQUE (tenant_id, command_id), \n'
 '\tUNIQUE (tenant_id, product_id, actor_id, operation, intent_digest), \n'
 '\tFOREIGN KEY(tenant_id, writer_id) REFERENCES principals (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, actor_id) REFERENCES principals (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, requester_id) REFERENCES principals (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, receipt_id) REFERENCES action_receipts (tenant_id, id) DEFERRABLE '
 'INITIALLY DEFERRED, \n'
 '\tFOREIGN KEY(tenant_id, confirmation_id) REFERENCES confirmations (tenant_id, id) DEFERRABLE '
 'INITIALLY DEFERRED, \n'
 '\tCHECK (writer_id=actor_id AND revision>0), \n'
 "\tCHECK (jsonb_typeof(command)='object' AND jsonb_typeof(body)='object' AND "
 "jsonb_typeof(source_basis)='object' AND jsonb_typeof(sources)='array' AND "
 "jsonb_typeof(reads)='array' AND jsonb_array_length(sources)>0 AND "
 'jsonb_array_length(reads)>0), \n'
 "\tCHECK (body_sha256 ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$' AND intent_digest "
 "~ '^[a-f0-9]{64}$'), \n"
 '\tUNIQUE (tenant_id, product_id, wait_id, revision), \n'
 '\tUNIQUE (tenant_id, category_id, product_id, project_id, owner_id, visibility, wait_id, id, '
 'revision), \n'
 '\tFOREIGN KEY(tenant_id, category_id, product_id, project_id, owner_id, visibility, wait_id, '
 'previous_id, previous_revision) REFERENCES external_wait_versions (tenant_id, category_id, '
 'product_id, project_id, owner_id, visibility, wait_id, id, revision), \n'
 "\tCONSTRAINT external_wait_version_chain CHECK ((revision=1 AND wait_id=id AND action='create' "
 "AND state='open' AND previous_id IS NULL AND previous_revision IS NULL) OR (revision>1 AND "
 "action<>'create' AND previous_id IS NOT NULL AND previous_id<>id AND "
 'previous_revision=revision-1)), \n'
 "\tCONSTRAINT external_wait_t0_only CHECK (operation='work.external_wait.record' AND "
 'confirmation_id IS NULL), \n'
 "\tCONSTRAINT external_wait_state CHECK (state IN ('open','closed')), \n"
 '\tCONSTRAINT external_wait_action CHECK (action IN '
 "('create','details','initiate','delivery','commitment','reply','close','reopen','transfer_request','transfer_accept','transfer_cancel'))\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_external_wait_versions_category_id ON external_wait_versions (category_id)',
 'CREATE INDEX ix_external_wait_versions_tenant_id ON external_wait_versions (tenant_id)',
 '\n'
 'CREATE TABLE external_wait_currents (\n'
 '\twait_id UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\trevision INTEGER NOT NULL, \n'
 '\tstate VARCHAR(16) NOT NULL, \n'
 '\tproduct_id UUID NOT NULL, \n'
 '\tproject_id UUID NOT NULL, \n'
 '\towner_id UUID NOT NULL, \n'
 '\tvisibility VARCHAR(16) NOT NULL, \n'
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
 '\tUNIQUE (tenant_id, product_id, wait_id), \n'
 '\tFOREIGN KEY(tenant_id, category_id, product_id, project_id, owner_id, visibility, wait_id, '
 'version_id, revision) REFERENCES external_wait_versions (tenant_id, category_id, product_id, '
 'project_id, owner_id, visibility, wait_id, id, revision), \n'
 "\tCONSTRAINT external_wait_current_state CHECK (revision>0 AND state IN ('open','closed'))\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_external_wait_currents_category_id ON external_wait_currents (category_id)',
 'CREATE INDEX ix_external_wait_currents_tenant_id ON external_wait_currents (tenant_id)',
 'CREATE OR REPLACE FUNCTION public.assert_work_management_members(t uuid, target uuid, kind '
 'text)\n'
 ' RETURNS void\n'
 ' LANGUAGE plpgsql\n'
 ' SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 '\n'
 'DECLARE v record; r public.action_receipts; c public.confirmations; expected_status text; '
 'event_name text; expected_result jsonb;\n'
 'BEGIN\n'
 '\n'
 " IF kind='work_task' THEN SELECT * INTO STRICT v FROM public.work_task_versions WHERE "
 'tenant_id=t AND id=target;\n'
 " ELSIF kind='work_commitment' THEN SELECT * INTO STRICT v FROM public.work_commitment_versions "
 'WHERE tenant_id=t AND id=target;\n'
 " ELSIF kind='project_status_update' THEN SELECT * INTO STRICT v FROM "
 'public.project_status_updates WHERE tenant_id=t AND id=target;\n'
 " ELSIF kind='external_wait' THEN SELECT * INTO STRICT v FROM public.external_wait_versions WHERE "
 'tenant_id=t AND id=target;\n'
 " ELSE RAISE EXCEPTION 'Unknown work subject' USING ERRCODE='23514'; END IF;\n"
 '\n'
 " expected_status=CASE WHEN kind IN ('work_task','external_wait') THEN v.body->>'state' ELSE "
 "'recorded' END;\n"
 " expected_result=jsonb_build_object('id',v.id,'revision',v.revision,'status',expected_status);\n"
 " IF kind='work_task' THEN "
 "expected_result=expected_result||jsonb_build_object('task_id',v.task_id,'state',v.state,'project_id',v.project_id);\n"
 " ELSIF kind='work_commitment' THEN "
 "expected_result=expected_result||jsonb_build_object('task_id',v.task_id,'recipient_id',v.recipient_id);\n"
 " ELSIF kind='external_wait' THEN "
 "expected_result=expected_result||jsonb_build_object('wait_id',v.wait_id,'state',v.state,'project_id',v.project_id);\n"
 " ELSE expected_result=expected_result||jsonb_build_object('project_id',v.project_id); END IF;\n"
 " event_name=CASE v.operation WHEN 'work.task.create' THEN 'task.created' WHEN 'work.task.assign' "
 "THEN 'task.assigned'\n"
 "  WHEN 'work.task.accept' THEN 'task.accepted' WHEN 'work.task.start' THEN 'task.started'\n"
 "  WHEN 'work.task.submit' THEN 'task.submitted' WHEN 'work.task.review' THEN 'task.reviewed'\n"
 "  WHEN 'work.commitment.accept' THEN 'commitment.accepted' WHEN 'work.status_update.create' THEN "
 "'project.status_updated' WHEN 'work.external_wait.record' THEN 'external_wait.recorded' END;\n"
 ' SELECT * INTO STRICT r FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;\n'
 ' IF '
 'ROW(r.category_id,r.product_id,r.command_id,r.confirmation_id,r.actor_id,r.requester_id,r.operation,r.subject_type,r.subject_id,r.subject_revision,r.visibility,r.request_digest,r.intent_digest)\n'
 '  IS DISTINCT FROM '
 'ROW(v.category_id,v.product_id,v.command_id,v.confirmation_id,v.actor_id,v.requester_id,v.operation,kind::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)\n'
 '  OR r.result IS DISTINCT FROM expected_result\n'
 '  OR r.created_at<v.created_at OR event_name IS NULL\n'
 '  OR (SELECT count(*) FROM public.action_receipts x WHERE x.tenant_id=t AND '
 'x.operation=v.operation AND x.subject_type=kind AND x.subject_id=v.id AND '
 'x.subject_revision=v.revision)<>1\n'
 '  OR (SELECT count(*) FROM public.audit_entries a WHERE a.tenant_id=t AND a.receipt_id=r.id)<>1\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.audit_entries a WHERE a.tenant_id=t AND a.receipt_id=r.id '
 'AND a.category_id=v.category_id AND a.actor_id=v.actor_id AND a.operation=v.operation AND '
 'a.created_at>=v.created_at)\n'
 '  OR (SELECT count(*) FROM public.outbox_events e WHERE e.tenant_id=t AND e.receipt_id=r.id)<>1\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.outbox_events e WHERE e.tenant_id=t AND e.receipt_id=r.id '
 'AND e.category_id=v.category_id AND e.actor_id=v.actor_id AND e.type=event_name AND '
 'e.subject_id=v.id AND e.subject_revision=v.revision AND e.schema_version=1 AND '
 'e.correlation_id=coalesce(r.agent_run_id,r.run_id,v.command_id) AND e.created_at>=v.created_at)\n'
 "  OR v.command->>'original_key_sha256' IS NULL OR v.command->>'original_key_sha256' !~ "
 "'^[a-f0-9]{64}$'\n"
 "  OR v.command->'envelope' ? 'idempotency_key' OR v.command->'envelope'->'payload' ? "
 "'confirmation_token'\n"
 '  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND '
 'k.category_id=v.category_id AND k.actor_id=v.actor_id AND k.receipt_id=r.id AND '
 'k.digest=v.request_digest AND '
 "encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.command->>'original_key_sha256') THEN\n"
 "  RAISE EXCEPTION 'Work fact original common group mismatch' USING ERRCODE='23514'; END IF;\n"
 " IF v.operation NOT IN ('work.task.create','work.external_wait.record') THEN\n"
 '  SELECT * INTO STRICT c FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;\n'
 '  IF c.consumed IS DISTINCT FROM true OR ROW(c.category_id,c.product_id,c.actor_id,c.operation)\n'
 '   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.actor_id,v.operation)\n'
 "   OR c.subject_type IS DISTINCT FROM 'product' OR c.subject_id IS DISTINCT FROM v.product_id\n"
 "   OR c.revision::text IS DISTINCT FROM v.command->'envelope'->>'expected_revision'\n"
 "   OR c.snapshot IS DISTINCT FROM v.command->'review' OR c.created_at>v.created_at\n"
 '   OR c.expires_at IS NULL OR v.created_at>=c.expires_at OR r.created_at>=c.expires_at\n'
 '   OR r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL THEN\n'
 "   RAISE EXCEPTION 'Work T1 needs its actual consumed confirmation' USING ERRCODE='23514'; END "
 'IF;\n'
 ' END IF;\n'
 'END;\n'
 '$function$\n',
 'CREATE OR REPLACE FUNCTION public.assert_work_management_write(t uuid, target uuid, kind text)\n'
 ' RETURNS void\n'
 ' LANGUAGE plpgsql\n'
 ' SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 '\n'
 'DECLARE v record; p public.projects; envelope jsonb; ref jsonb; basis jsonb; vx xid; rx xid; cx '
 'xid;\n'
 'BEGIN\n'
 '\n'
 " IF kind='work_task' THEN SELECT * INTO STRICT v FROM public.work_task_versions WHERE "
 'tenant_id=t AND id=target;\n'
 " ELSIF kind='work_commitment' THEN SELECT * INTO STRICT v FROM public.work_commitment_versions "
 'WHERE tenant_id=t AND id=target;\n'
 " ELSIF kind='project_status_update' THEN SELECT * INTO STRICT v FROM "
 'public.project_status_updates WHERE tenant_id=t AND id=target;\n'
 " ELSIF kind='external_wait' THEN SELECT * INTO STRICT v FROM public.external_wait_versions WHERE "
 'tenant_id=t AND id=target;\n'
 " ELSE RAISE EXCEPTION 'Unknown work subject' USING ERRCODE='23514'; END IF;\n"
 '\n'
 " IF kind='work_task' THEN SELECT xmin INTO vx FROM public.work_task_versions WHERE tenant_id=t "
 'AND id=target;\n'
 " ELSIF kind='work_commitment' THEN SELECT xmin INTO vx FROM public.work_commitment_versions "
 'WHERE tenant_id=t AND id=target;\n'
 " ELSIF kind='external_wait' THEN SELECT xmin INTO vx FROM public.external_wait_versions WHERE "
 'tenant_id=t AND id=target;\n'
 ' ELSE SELECT xmin INTO vx FROM public.project_status_updates WHERE tenant_id=t AND id=target; '
 'END IF;\n'
 ' SELECT * INTO STRICT p FROM public.projects WHERE tenant_id=t AND id=v.project_id;\n'
 ' SELECT xmin INTO rx FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;\n'
 ' PERFORM public.assert_work_management_members(t,target,kind);\n'
 " envelope=v.command->'envelope';\n"
 '\n'
 " IF kind='work_task' THEN PERFORM public.assert_work_task_g0_source(t,target);\n"
 " ELSIF v.source_basis ? 'g0_open_item' THEN\n"
 "  RAISE EXCEPTION 'Only a task may use a native G0 source basis' USING ERRCODE='23514'; END IF;\n"
 ' IF ROW(p.category_id,p.product_id,p.owner_id,p.visibility) IS DISTINCT FROM '
 'ROW(v.category_id,v.product_id,v.owner_id,v.visibility)\n'
 '  OR v.actor_id IS DISTINCT FROM public.scope_actor() OR v.requester_id IS DISTINCT FROM '
 'public.scope_requester()\n'
 '  OR v.writer_id<>v.actor_id OR vx IS DISTINCT FROM rx OR NOT '
 'public.category_access(t,v.category_id,true)\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.principals a WHERE a.tenant_id=t AND a.id=v.actor_id AND '
 'a.active)\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.principals a WHERE a.tenant_id=t AND a.id=v.requester_id '
 "AND a.kind='human' AND a.active)\n"
 "  OR envelope->>'operation' IS DISTINCT FROM v.operation OR envelope->>'command_id' IS DISTINCT "
 'FROM v.command_id::text\n'
 "  OR envelope->>'category_id' IS DISTINCT FROM v.category_id::text OR envelope->>'product_id' IS "
 'DISTINCT FROM v.product_id::text\n'
 "  OR envelope->'payload'->>'project_id' IS DISTINCT FROM v.project_id::text\n"
 "  OR v.command->'review'->'declaration' IS DISTINCT FROM envelope->'payload'\n"
 "  OR v.command->'review'->>'operation' IS DISTINCT FROM v.operation\n"
 "  OR v.command->'review'->'sources' IS DISTINCT FROM v.sources\n"
 "  OR v.command->'review'->'source_basis' IS DISTINCT FROM v.source_basis\n"
 "  OR (v.body #- '{recorded_at}' #- '{actual_start,recorded_at}' #- "
 "'{submission,time,recorded_at}' #- '{review,time,recorded_at}') IS DISTINCT FROM "
 "v.command->'review'->'after'\n"
 '  OR NOT EXISTS(SELECT 1 FROM public.products x WHERE x.tenant_id=t AND '
 'x.category_id=v.category_id AND x.id=v.product_id AND '
 "x.revision::text=envelope->>'expected_revision')\n"
 "  OR NOT COALESCE(envelope->'source_read_set' @> v.reads,false) OR NOT COALESCE(v.reads @> "
 "(envelope->'source_read_set'),false)\n"
 "  OR jsonb_array_length(envelope->'source_read_set')<>jsonb_array_length(v.reads)\n"
 '  OR NOT public.direct_source_set_visible(t,v.category_id,v.product_id,v.reads)\n'
 "  OR (v.operation NOT IN ('work.task.create','work.external_wait.record') AND "
 '(v.actor_id<>v.requester_id OR NOT EXISTS(SELECT 1 FROM public.principals a WHERE a.tenant_id=t '
 "AND a.id=v.actor_id AND a.kind='human')))\n"
 "  OR (v.operation IN ('work.task.create','work.external_wait.record') AND "
 'v.actor_id<>v.requester_id AND NOT EXISTS(SELECT 1 FROM public.action_receipts r WHERE '
 'r.tenant_id=t AND r.id=v.receipt_id AND coalesce(r.agent_run_id,r.run_id) IS NOT NULL))\n'
 '  OR EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)\n'
 '  OR EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND '
 'k.receipt_id=v.receipt_id AND k.actor_id=v.actor_id AND k.digest=v.request_digest AND k.xmin=vx '
 "AND encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.command->>'original_key_sha256') THEN\n"
 "  RAISE EXCEPTION 'Work fact requires actual project actor and one transaction' USING "
 "ERRCODE='23514'; END IF;\n"
 ' IF v.confirmation_id IS NOT NULL THEN\n'
 '  SELECT xmin INTO cx FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;\n'
 "  IF cx IS DISTINCT FROM vx THEN RAISE EXCEPTION 'Work confirmation consumption must share its "
 "new fact transaction' USING ERRCODE='23514'; END IF;\n"
 ' END IF;\n'
 " IF jsonb_typeof(v.source_basis->'artifacts') IS DISTINCT FROM 'array' THEN\n"
 "  RAISE EXCEPTION 'Work direct source metadata required' USING ERRCODE='23514'; END IF;\n"
 " FOR basis IN SELECT value FROM jsonb_array_elements(v.source_basis->'artifacts') LOOP\n"
 '  IF NOT EXISTS(SELECT 1 FROM public.artifact_versions a WHERE a.tenant_id=t AND '
 'a.category_id=v.category_id\n'
 "   AND (a.product_id IS NULL OR a.product_id=v.product_id) AND a.id::text=basis->>'id'\n"
 "   AND a.revision::text=basis->>'revision' AND a.content_hash=basis->>'hash' AND "
 "a.status='active'\n"
 "   AND a.status=basis->>'status' AND a.owner_id::text=basis->>'owner_id' AND "
 "a.visibility=basis->>'visibility'\n"
 "   AND (v.visibility='private' OR a.visibility<>'private')\n"
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
 "    AND (v.visibility='private' OR a.visibility<>'private')\n"
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
 "        AND (v.visibility='private' OR o.visibility<>'private'))))) THEN\n"
 "   RAISE EXCEPTION 'Work source metadata security or audience changed' USING ERRCODE='23514'; "
 'END IF;\n'
 ' END LOOP;\n'
 'END;\n'
 '$function$\n',
 'CREATE OR REPLACE FUNCTION public.protect_work_receipt()\n'
 ' RETURNS trigger\n'
 ' LANGUAGE plpgsql\n'
 ' SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 '\n'
 'DECLARE scoped boolean=false;\n'
 'BEGIN\n'
 " IF TG_OP<>'INSERT' THEN scoped=OLD.operation IN "
 "('work.task.create','work.task.assign','work.task.accept','work.commitment.accept','work.task.start','work.task.submit','work.task.review','work.status_update.create','work.external_wait.record') "
 "OR OLD.subject_type IN ('work_task','work_commitment','project_status_update','external_wait'); "
 'END IF;\n'
 " IF TG_OP<>'DELETE' THEN scoped=scoped OR NEW.operation IN "
 "('work.task.create','work.task.assign','work.task.accept','work.commitment.accept','work.task.start','work.task.submit','work.task.review','work.status_update.create','work.external_wait.record') "
 "OR NEW.subject_type IN ('work_task','work_commitment','project_status_update','external_wait'); "
 'END IF;\n'
 " IF scoped AND TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Work receipt immutable' USING "
 "ERRCODE='23514'; END IF;\n"
 " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
 'END;\n'
 '$function$\n',
 'CREATE OR REPLACE FUNCTION public.protect_work_member()\n'
 ' RETURNS trigger\n'
 ' LANGUAGE plpgsql\n'
 ' SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 '\n'
 'DECLARE scoped boolean=false; old_scoped boolean=false;\n'
 'BEGIN\n'
 " IF TG_OP<>'DELETE' THEN SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE "
 'r.tenant_id=NEW.tenant_id AND r.id=NEW.receipt_id AND (r.operation IN '
 "('work.task.create','work.task.assign','work.task.accept','work.commitment.accept','work.task.start','work.task.submit','work.task.review','work.status_update.create','work.external_wait.record') "
 "OR r.subject_type IN ('work_task','work_commitment','project_status_update','external_wait'))) "
 'INTO scoped; END IF;\n'
 " IF TG_OP<>'INSERT' THEN SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE "
 'r.tenant_id=OLD.tenant_id AND r.id=OLD.receipt_id AND (r.operation IN '
 "('work.task.create','work.task.assign','work.task.accept','work.commitment.accept','work.task.start','work.task.submit','work.task.review','work.status_update.create','work.external_wait.record') "
 "OR r.subject_type IN ('work_task','work_commitment','project_status_update','external_wait'))) "
 'INTO old_scoped; END IF;\n'
 " IF TG_OP<>'INSERT' AND (scoped OR old_scoped) THEN\n"
 "  IF TG_OP='UPDATE' AND TG_TABLE_NAME='outbox_events' AND "
 "(to_jsonb(NEW)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) IS NOT "
 'DISTINCT FROM '
 "(to_jsonb(OLD)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) THEN "
 'RETURN NEW; END IF;\n'
 "  RAISE EXCEPTION 'Work audit event or original key immutable' USING ERRCODE='23514'; END IF;\n"
 " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
 'END;\n'
 '$function$\n',
 'CREATE OR REPLACE FUNCTION public.require_work_member()\n'
 ' RETURNS trigger\n'
 ' LANGUAGE plpgsql\n'
 ' SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 '\n'
 'DECLARE r public.action_receipts;\n'
 'BEGIN\n'
 " IF TG_TABLE_NAME='action_receipts' THEN r=NEW; ELSE SELECT * INTO r FROM public.action_receipts "
 'WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id; END IF;\n'
 ' IF r.operation IN '
 "('work.task.create','work.task.assign','work.task.accept','work.commitment.accept','work.task.start','work.task.submit','work.task.review','work.status_update.create','work.external_wait.record') "
 "OR r.subject_type IN ('work_task','work_commitment','project_status_update','external_wait') "
 'THEN PERFORM '
 'public.assert_work_management_members(r.tenant_id,r.subject_id,r.subject_type::text); END IF;\n'
 ' RETURN NULL;\n'
 'END;\n'
 '$function$\n',
 'CREATE FUNCTION public.assert_external_wait_calendar(t uuid,target uuid) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS '
 '$work_management$\n'
 '\n'
 'DECLARE v public.external_wait_versions; cal jsonb; ref jsonb;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT v FROM public.external_wait_versions WHERE tenant_id=t AND id=target;\n'
 " cal=v.source_basis->'calendar'; ref=v.body->'calendar';\n"
 " IF coalesce(ref,'null'::jsonb)='null'::jsonb THEN\n"
 "  IF coalesce(cal,'null'::jsonb)<>'null'::jsonb THEN\n"
 "   RAISE EXCEPTION 'No inline calendar or detached calendar basis may be supplied' USING "
 "ERRCODE='23514'; END IF;\n"
 '  RETURN;\n'
 ' END IF;\n'
 " IF jsonb_typeof(cal) IS DISTINCT FROM 'object' OR cal->'ref' IS DISTINCT FROM ref\n"
 "  OR cal->'scope' IS DISTINCT FROM "
 "jsonb_build_object('tenant_id',t,'category_id',v.category_id,'product_id',v.product_id,'project_id',v.project_id)\n"
 "  OR jsonb_typeof(cal->'source_calendar') IS DISTINCT FROM 'object'\n"
 "  OR cal->>'digest' IS NULL OR cal->>'digest' !~ '^[a-f0-9]{64}$'\n"
 "  OR cal->>'calendar_sha256' IS NULL OR cal->>'calendar_sha256' !~ '^[a-f0-9]{64}$'\n"
 "  OR jsonb_typeof(cal->'material'->'source_basis'->'artifacts') IS DISTINCT FROM 'array'\n"
 "  OR NOT coalesce(v.source_basis->'artifacts' @> "
 "cal->'material'->'source_basis'->'artifacts',false) THEN\n"
 "  RAISE EXCEPTION 'Calendar requires the exact native reference and retained direct sources' "
 "USING ERRCODE='23514'; END IF;\n"
 " IF ref->>'kind'='project_plan' THEN\n"
 '  IF NOT EXISTS(SELECT 1 FROM public.plan_revisions pl JOIN public.plan_proposals pp\n'
 '   ON pp.tenant_id=pl.tenant_id AND pp.category_id=pl.category_id AND '
 'pp.product_id=pl.product_id\n'
 '    AND pp.project_id=pl.project_id AND pp.id=pl.proposal_id\n'
 '   JOIN public.project_product_links link ON link.tenant_id=pl.tenant_id AND '
 'link.category_id=pl.category_id\n'
 '    AND link.product_id=pl.product_id AND link.project_id=pl.project_id\n'
 '   WHERE pl.tenant_id=t AND pl.category_id=v.category_id AND pl.product_id=v.product_id AND '
 'pl.project_id=v.project_id\n'
 "    AND pl.id::text=ref->>'id' AND pl.revision::text=ref->>'revision' AND pl.status='applied'\n"
 "    AND pl.id::text=cal->'material'->>'plan_id' AND "
 "pl.revision::text=cal->'material'->>'plan_revision'\n"
 "    AND pp.id::text=cal->'material'->>'proposal_id' AND "
 "pp.revision::text=cal->'material'->>'proposal_revision'\n"
 '    AND '
 "cal->'material'->'definition_ref'=jsonb_build_object('id',link.definition_id,'revision',link.definition_revision)\n"
 "    AND pp.input_snapshot->'calendar'=cal->'source_calendar'\n"
 "    AND ref->>'calendar_key'=pp.input_snapshot->'calendar'->>'key'\n"
 "    AND ref->>'calendar_version'=pp.input_snapshot->'calendar'->>'version'\n"
 "    AND coalesce(ref->'resource_id','null'::jsonb)='null'::jsonb) THEN\n"
 "   RAISE EXCEPTION 'Calendar is not the selected actual project plan calendar' USING "
 "ERRCODE='23514'; END IF;\n"
 " ELSIF ref->>'kind'='build_resource' THEN\n"
 '  IF NOT EXISTS(SELECT 1 FROM public.build_operational_facts fixed\n'
 '   JOIN public.build_operational_current ptr ON ptr.tenant_id=fixed.tenant_id AND '
 'ptr.category_id=fixed.category_id\n'
 '    AND ptr.product_id=fixed.product_id AND ptr.project_id=fixed.project_id AND '
 'ptr.build_id=fixed.build_id\n'
 '   JOIN public.build_operational_facts live ON live.tenant_id=ptr.tenant_id AND '
 'live.category_id=ptr.category_id\n'
 '    AND live.product_id=ptr.product_id AND live.project_id=ptr.project_id AND '
 'live.build_id=ptr.build_id\n'
 '    AND live.id=ptr.fact_id AND live.revision=ptr.fact_revision AND '
 'live.series_id=fixed.series_id\n'
 "   JOIN LATERAL jsonb_array_elements(fixed.data->'resources') res ON true\n"
 "   JOIN LATERAL jsonb_array_elements(live.data->'resources') actual ON true\n"
 '   JOIN public.operational_asset_sentinels asset ON asset.tenant_id=fixed.tenant_id\n'
 "    AND asset.id::text=actual->'resource'->>'id' AND "
 "asset.revision::text=actual->'resource'->>'revision'\n"
 '   WHERE fixed.tenant_id=t AND fixed.category_id=v.category_id AND fixed.product_id=v.product_id '
 'AND fixed.project_id=v.project_id\n'
 "    AND fixed.id::text=ref->>'id' AND fixed.revision::text=ref->>'revision'\n"
 "    AND fixed.id::text=cal->'material'->>'fact_id' AND "
 "fixed.revision::text=cal->'material'->>'fact_revision'\n"
 "    AND fixed.fact_sha256=cal->'material'->>'fact_sha256' AND "
 "fixed.build_id::text=cal->'material'->>'build_id'\n"
 "    AND fixed.state='active' AND fixed.valid_from<=v.created_at AND (fixed.valid_until IS NULL "
 'OR v.created_at<fixed.valid_until)\n'
 "    AND live.state='active' AND live.valid_from<=v.created_at AND (live.valid_until IS NULL OR "
 'v.created_at<live.valid_until)\n'
 "    AND res->'resource'->>'id'=ref->>'resource_id' AND "
 "actual->'resource'->>'id'=ref->>'resource_id'\n"
 "    AND cal->'material'->>'resource_id'=ref->>'resource_id' AND "
 "res->'resource'->>'revision'=cal->'material'->>'resource_revision'\n"
 "    AND res->>'lifecycle'='active' AND actual->>'lifecycle'='active'\n"
 "    AND res->'calendar'=cal->'source_calendar' AND "
 "actual->'calendar'->>'calendar_id'=res->'calendar'->>'calendar_id'\n"
 "    AND ref->>'calendar_key'=res->'calendar'->>'calendar_id' AND "
 "ref->>'calendar_version'=res->'calendar'->>'version'\n"
 "    AND asset.kind='resource' AND asset.data->>'state'='active') THEN\n"
 "   RAISE EXCEPTION 'Calendar is not a retained native resource with a currently usable source' "
 "USING ERRCODE='23514'; END IF;\n"
 " ELSE RAISE EXCEPTION 'Unknown native calendar source' USING ERRCODE='23514'; END IF;\n"
 'END;\n'
 '$work_management$',
 'CREATE FUNCTION public.assert_external_wait(t uuid,target uuid) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS '
 '$work_management$\n'
 '\n'
 'DECLARE v public.external_wait_versions; prior public.external_wait_versions;\n'
 ' cur public.external_wait_currents; p public.projects; receipt public.action_receipts;\n'
 ' payload jsonb; record jsonb; expected jsonb; entry jsonb; expected_entry jsonb;\n'
 ' leaf text; human_actor boolean; vx xid; cx xid;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT v FROM public.external_wait_versions WHERE tenant_id=t AND id=target;\n'
 ' SELECT xmin INTO vx FROM public.external_wait_versions WHERE tenant_id=t AND id=target;\n'
 ' SELECT * INTO STRICT cur FROM public.external_wait_currents WHERE tenant_id=t AND '
 'product_id=v.product_id AND wait_id=v.wait_id;\n'
 ' SELECT xmin INTO cx FROM public.external_wait_currents WHERE tenant_id=t AND id=cur.id;\n'
 " PERFORM public.assert_work_management_write(t,target,'external_wait');\n"
 ' PERFORM public.assert_external_wait_calendar(t,target);\n'
 ' SELECT * INTO STRICT p FROM public.projects WHERE tenant_id=t AND id=v.project_id;\n'
 ' SELECT * INTO STRICT receipt FROM public.action_receipts WHERE tenant_id=t AND '
 'id=v.receipt_id;\n'
 " payload=v.command->'envelope'->'payload'; record=payload->'record';\n"
 ' human_actor=v.actor_id=v.requester_id AND receipt.run_id IS NULL AND receipt.agent_run_id IS '
 'NULL\n'
 '  AND EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=t AND h.id=v.actor_id AND '
 "h.kind='human' AND h.active);\n"
 ' IF vx IS DISTINCT FROM cx\n'
 '  OR '
 'ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.wait_id,cur.version_id,cur.revision,cur.state)\n'
 '   IS DISTINCT FROM '
 'ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.wait_id,v.id,v.revision,v.state)\n'
 "  OR v.body->>'wait_id' IS DISTINCT FROM v.wait_id::text OR v.body->>'revision' IS DISTINCT FROM "
 'v.revision::text\n'
 "  OR v.body->>'state' IS DISTINCT FROM v.state OR record->>'action' IS DISTINCT FROM v.action\n"
 "  OR v.operation<>'work.external_wait.record' OR v.confirmation_id IS NOT NULL THEN\n"
 "  RAISE EXCEPTION 'External wait requires its exact same-transaction version and Current' USING "
 "ERRCODE='23514'; END IF;\n"
 ' IF v.revision=1 THEN\n'
 "  IF v.action<>'create' OR v.state<>'open' OR v.wait_id<>v.id\n"
 "   OR coalesce(payload->'wait','null'::jsonb)<>'null'::jsonb\n"
 "   OR v.body->>'responsible_id' IS DISTINCT FROM v.requester_id::text\n"
 "   OR (v.body->>'created_at')::timestamptz IS DISTINCT FROM v.created_at THEN\n"
 "   RAISE EXCEPTION 'New external wait has the actual requester as responsible person' USING "
 "ERRCODE='23514'; END IF;\n"
 "  IF coalesce(record->'milestone','null'::jsonb)<>'null'::jsonb AND NOT EXISTS(\n"
 '   SELECT 1 FROM public.project_tasks m JOIN public.plan_revisions pl ON '
 'pl.tenant_id=m.tenant_id\n'
 '    AND pl.category_id=m.category_id AND pl.product_id=m.product_id AND '
 'pl.project_id=m.project_id AND pl.id=m.plan_id\n'
 '   WHERE m.tenant_id=t AND m.category_id=v.category_id AND m.product_id=v.product_id AND '
 'm.project_id=v.project_id\n'
 "    AND m.id::text=record->'milestone'->>'id' AND "
 "pl.revision::text=record->'milestone'->>'revision') THEN\n"
 "   RAISE EXCEPTION 'Waiting milestone must bind an actual task in the fixed project plan' USING "
 "ERRCODE='23514'; END IF;\n"
 "  IF coalesce(record->'build','null'::jsonb)<>'null'::jsonb AND NOT EXISTS(\n"
 '   SELECT 1 FROM public.builds b WHERE b.tenant_id=t AND b.category_id=v.category_id\n'
 '    AND b.product_id=v.product_id AND b.project_id=v.project_id AND '
 "b.id::text=record->'build'->>'id'\n"
 "    AND b.revision::text=record->'build'->>'revision') THEN\n"
 "   RAISE EXCEPTION 'Waiting Build must bind its actual project and version' USING "
 "ERRCODE='23514'; END IF;\n"
 '  '
 "expected=jsonb_build_object('title',record->'title','target',record->'target','request_content',record->'request_content',\n"
 '   '
 "'closure_condition',record->'closure_condition','blocking',record->'blocking','next_check_at',record->'next_check_at',\n"
 '   '
 "'original_timezone',record->'original_timezone','wait_id',v.wait_id,'revision',1,'state','open',\n"
 "   'responsible_id',v.requester_id,'created_at',v.body->'created_at',\n"
 '   '
 "'milestone',coalesce(record->'milestone','null'::jsonb),'build',coalesce(record->'build','null'::jsonb),\n"
 '   '
 "'replaces',coalesce(record->'replaces','null'::jsonb),'calendar',coalesce(record->'calendar','null'::jsonb),\n"
 '   '
 "'initiation',NULL,'delivery',NULL,'counterparty_commitment',NULL,'reply',NULL,'last_closure',NULL,'transfer',NULL);\n"
 ' ELSE\n'
 '  SELECT * INTO STRICT prior FROM public.external_wait_versions WHERE tenant_id=t AND '
 'id=v.previous_id;\n'
 "  IF payload->'wait' IS DISTINCT FROM "
 "jsonb_build_object('id',v.wait_id,'revision',prior.revision)\n"
 '   OR v.previous_revision<>prior.revision OR v.revision<>prior.revision+1\n'
 '   OR '
 'ROW(prior.category_id,prior.product_id,prior.project_id,prior.owner_id,prior.visibility,prior.wait_id)\n'
 '    IS DISTINCT FROM '
 'ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.wait_id) THEN\n'
 "   RAISE EXCEPTION 'External wait action requires its exact stable identity and prior revision' "
 "USING ERRCODE='23514'; END IF;\n"
 "  IF v.action<>'transfer_accept' AND v.requester_id::text NOT IN "
 "(prior.body->>'responsible_id',p.owner_id::text) THEN\n"
 "   RAISE EXCEPTION 'Only current responsible person or project owner may record waiting facts' "
 "USING ERRCODE='23514'; END IF;\n"
 "  IF NOT ((prior.state='closed' AND v.action='reopen') OR (prior.state='open' AND "
 "v.action<>'reopen')) THEN\n"
 "   RAISE EXCEPTION 'Closed waiting must be explicitly reopened before recording more progress' "
 "USING ERRCODE='23514'; END IF;\n"
 "  expected=prior.body||jsonb_build_object('revision',v.revision);\n"
 "  IF v.action='details' THEN\n"
 '   '
 "expected=expected||jsonb_build_object('title',record->'title','closure_condition',record->'closure_condition',\n"
 "    'blocking',record->'blocking','next_check_at',record->'next_check_at',\n"
 '    '
 "'original_timezone',record->'original_timezone','calendar',coalesce(record->'calendar','null'::jsonb));\n"
 "  ELSIF v.action IN ('initiate','delivery','commitment','reply','close') THEN\n"
 "   leaf=CASE v.action WHEN 'initiate' THEN 'initiation' WHEN 'delivery' THEN 'delivery'\n"
 "    WHEN 'commitment' THEN 'counterparty_commitment' WHEN 'reply' THEN 'reply' ELSE "
 "'last_closure' END;\n"
 '   entry=v.body->leaf;\n'
 "   IF jsonb_typeof(entry) IS DISTINCT FROM 'object'\n"
 "    OR (entry->>'recorded_at')::timestamptz IS DISTINCT FROM v.created_at THEN\n"
 "    RAISE EXCEPTION 'New waiting entry requires its server recording time' USING "
 "ERRCODE='23514'; END IF;\n"
 "   expected_entry=jsonb_build_object('actor_id',v.actor_id,'requester_id',v.requester_id,\n"
 "    'recorded_at',entry->'recorded_at','sources',payload->'sources');\n"
 "   IF v.action='close' THEN "
 "expected_entry=expected_entry||jsonb_build_object('result',record->'result');\n"
 '   ELSE '
 "expected_entry=expected_entry||jsonb_build_object('text',record->'text','original_timezone',record->'original_timezone'); "
 'END IF;\n'
 "   IF v.action IN ('initiate','delivery','reply') THEN\n"
 "    expected_entry=(expected_entry-'at')||jsonb_build_object('at',entry->'at',\n"
 "     'time_basis',CASE WHEN human_actor THEN 'human_recorded' ELSE 'source_claim' END);\n"
 "    IF v.action IN ('delivery','reply') THEN "
 "expected_entry=expected_entry||jsonb_build_object('status',record->'status'); END IF;\n"
 "    IF (entry->>'at')::timestamptz IS DISTINCT FROM (record->>'at')::timestamptz\n"
 "     OR (entry->>'at')::timestamptz>(entry->>'recorded_at')::timestamptz THEN\n"
 "     RAISE EXCEPTION 'Waiting event time differs from its declared source' USING "
 "ERRCODE='23514'; END IF;\n"
 "   ELSIF v.action='commitment' THEN\n"
 '    '
 "expected_entry=(expected_entry-'promised_at')||jsonb_build_object('promised_at',entry->'promised_at');\n"
 "    IF (entry->>'promised_at')::timestamptz IS DISTINCT FROM "
 "(record->>'promised_at')::timestamptz THEN\n"
 "     RAISE EXCEPTION 'Counterparty stated date differs from its recorded source' USING "
 "ERRCODE='23514'; END IF;\n"
 '   END IF;\n'
 '   IF entry IS DISTINCT FROM expected_entry THEN\n'
 "    RAISE EXCEPTION 'Waiting entry must retain the actual command authors and sources' USING "
 "ERRCODE='23514'; END IF;\n"
 "   IF (v.action='delivery' AND entry->>'status' NOT IN ('effective','unverified','conflict'))\n"
 "    OR (v.action='reply' AND entry->>'status' NOT IN "
 "('partial','received','conflict','unknown')) THEN\n"
 "    RAISE EXCEPTION 'Waiting entry has an unknown delivery or reply state' USING "
 "ERRCODE='23514'; END IF;\n"
 "   IF v.action='delivery' AND (entry->>'status'='effective' OR "
 "prior.body->'delivery'->>'status'='effective') THEN\n"
 "    IF NOT human_actor OR entry->>'time_basis' IS DISTINCT FROM 'human_recorded'\n"
 "     OR (entry->>'status'='effective' AND (entry->>'at')::timestamptz IS NULL) THEN\n"
 "     RAISE EXCEPTION 'Effective delivery and its correction require a real human record' USING "
 "ERRCODE='23514'; END IF;\n"
 '   END IF;\n'
 "   IF v.action='initiate' AND entry->>'time_basis'='human_recorded' AND entry->>'at' IS NOT "
 'NULL\n'
 "    AND prior.body->'delivery'->>'status'='effective'\n"
 "    AND (entry->>'at')::timestamptz>(prior.body->'delivery'->>'at')::timestamptz THEN\n"
 "    RAISE EXCEPTION 'Human initiation conflicts with the previously verified delivery time' "
 "USING ERRCODE='23514'; END IF;\n"
 "   IF v.action='delivery' AND entry->>'status'='effective'\n"
 "    AND prior.body->'initiation'->>'time_basis'='human_recorded'\n"
 "    AND (entry->>'at')::timestamptz<(prior.body->'initiation'->>'at')::timestamptz THEN\n"
 "    RAISE EXCEPTION 'Verified delivery cannot precede its actual recorded initiation' USING "
 "ERRCODE='23514'; END IF;\n"
 '   expected=jsonb_set(expected,ARRAY[leaf],entry);\n'
 "   IF v.action='close' THEN expected=expected||jsonb_build_object('state','closed'); END IF;\n"
 "  ELSIF v.action='reopen' THEN\n"
 "   IF prior.state<>'closed' THEN RAISE EXCEPTION 'Only closed waiting can be reopened' USING "
 "ERRCODE='23514'; END IF;\n"
 "   expected=expected||jsonb_build_object('state','open');\n"
 "  ELSIF v.action='transfer_request' THEN\n"
 "   entry=v.body->'transfer';\n"
 "   IF coalesce(prior.body->'transfer','null'::jsonb)<>'null'::jsonb\n"
 "    OR jsonb_typeof(entry) IS DISTINCT FROM 'object' OR (entry->>'request_id')::uuid IS NULL\n"
 "    OR record->>'to_id' IS NOT DISTINCT FROM prior.body->>'responsible_id'\n"
 "    OR (entry->>'requested_at')::timestamptz IS DISTINCT FROM v.created_at THEN\n"
 "    RAISE EXCEPTION 'Responsibility transfer requires a new explicit pending request' USING "
 "ERRCODE='23514'; END IF;\n"
 '   '
 "expected_entry=jsonb_build_object('request_id',entry->'request_id','from_id',prior.body->'responsible_id',\n"
 '    '
 "'to_id',record->'to_id','actor_id',v.actor_id,'requested_at',entry->'requested_at','sources',payload->'sources');\n"
 '   IF entry IS DISTINCT FROM expected_entry OR NOT EXISTS(SELECT 1 FROM public.principals h\n'
 '    JOIN public.grants g ON g.tenant_id=h.tenant_id AND g.principal_id=h.id\n'
 "    WHERE h.tenant_id=t AND h.id::text=record->>'to_id' AND h.kind='human' AND h.active\n"
 '     AND g.category_id=v.category_id AND g.can_write AND (g.expires_at IS NULL OR '
 'v.created_at<g.expires_at)) THEN\n'
 "    RAISE EXCEPTION 'Transfer must name one actual eligible human target' USING ERRCODE='23514'; "
 'END IF;\n'
 "   expected=jsonb_set(expected,'{transfer}',entry);\n"
 "  ELSIF v.action IN ('transfer_accept','transfer_cancel') THEN\n"
 "   entry=prior.body->'transfer';\n"
 "   IF jsonb_typeof(entry) IS DISTINCT FROM 'object'\n"
 "    OR record->'request_id' IS DISTINCT FROM entry->'request_id'\n"
 "    OR entry->'from_id' IS DISTINCT FROM prior.body->'responsible_id' THEN\n"
 "    RAISE EXCEPTION 'Transfer action requires its exact outstanding request' USING "
 "ERRCODE='23514'; END IF;\n"
 "   expected=expected||jsonb_build_object('transfer',NULL);\n"
 "   IF v.action='transfer_accept' THEN\n"
 "    IF NOT human_actor OR entry->>'to_id' IS DISTINCT FROM v.requester_id::text THEN\n"
 "     RAISE EXCEPTION 'Only the named target can personally accept responsibility' USING "
 "ERRCODE='23514'; END IF;\n"
 "    expected=expected||jsonb_build_object('responsible_id',entry->'to_id');\n"
 '   END IF;\n'
 "  ELSE RAISE EXCEPTION 'Unknown external wait transition' USING ERRCODE='23514'; END IF;\n"
 ' END IF;\n'
 ' IF v.body IS DISTINCT FROM expected THEN\n'
 "  RAISE EXCEPTION 'External wait action cannot replace other fixed facts or responsibility' "
 "USING ERRCODE='23514'; END IF;\n"
 'END;\n'
 '$work_management$',
 'CREATE FUNCTION public.require_external_wait() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS '
 '$work_management$\n'
 'BEGIN PERFORM public.assert_external_wait(NEW.tenant_id,NEW.id); RETURN NULL; END;\n'
 '$work_management$',
 'CREATE FUNCTION public.protect_external_wait_current() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS '
 '$work_management$\n'
 '\n'
 'BEGIN\n'
 " IF TG_OP='INSERT' AND NEW.revision=1 THEN RETURN NEW;\n"
 " ELSIF TG_OP='UPDATE' AND (to_jsonb(NEW)-ARRAY['version_id','revision','state']) IS NOT DISTINCT "
 "FROM (to_jsonb(OLD)-ARRAY['version_id','revision','state'])\n"
 '  AND NEW.revision=OLD.revision+1 AND EXISTS(SELECT 1 FROM public.external_wait_versions v WHERE '
 'v.tenant_id=NEW.tenant_id\n'
 '   AND v.id=NEW.version_id AND v.revision=NEW.revision AND v.previous_id=OLD.version_id AND '
 'v.previous_revision=OLD.revision) THEN RETURN NEW;\n'
 ' END IF;\n'
 " RAISE EXCEPTION 'external_wait_currents requires one exact Current CAS' USING ERRCODE='23514';\n"
 'END;\n'
 '$work_management$',
 'CREATE FUNCTION public.require_external_wait_current() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS '
 '$work_management$\n'
 '\n'
 'DECLARE cur public.external_wait_currents; cx xid; vx xid;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT cur FROM public.external_wait_currents WHERE tenant_id=NEW.tenant_id AND '
 'id=NEW.id;\n'
 ' SELECT xmin INTO cx FROM public.external_wait_currents WHERE tenant_id=NEW.tenant_id AND '
 'id=NEW.id;\n'
 ' SELECT xmin INTO vx FROM public.external_wait_versions WHERE tenant_id=NEW.tenant_id AND '
 'id=cur.version_id;\n'
 " IF vx IS DISTINCT FROM cx THEN RAISE EXCEPTION 'Work Current requires its new same-transaction "
 "immutable version' USING ERRCODE='23514'; END IF;\n"
 ' RETURN NULL;\n'
 'END;\n'
 '$work_management$',
 'REVOKE ALL ON FUNCTION public.assert_external_wait_calendar(uuid,uuid) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.assert_external_wait(uuid,uuid) FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.require_external_wait() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.protect_external_wait_current() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.require_external_wait_current() FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'ALTER TABLE public."external_wait_versions" ENABLE ROW LEVEL SECURITY',
 'ALTER TABLE public."external_wait_versions" FORCE ROW LEVEL SECURITY',
 'CREATE POLICY owner_internal ON public."external_wait_versions" TO pdos_next_owner USING(true) '
 'WITH CHECK(true)',
 'CREATE POLICY external_wait_read ON public."external_wait_versions" FOR SELECT TO pdos_next_app '
 'USING(public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM public.projects p '
 'WHERE p.tenant_id=external_wait_versions.tenant_id AND '
 'p.category_id=external_wait_versions.category_id AND '
 'p.product_id=external_wait_versions.product_id AND p.id=external_wait_versions.project_id AND '
 'p.owner_id=external_wait_versions.owner_id AND p.visibility=external_wait_versions.visibility))',
 'CREATE POLICY external_wait_insert ON public."external_wait_versions" FOR INSERT TO '
 'pdos_next_app WITH CHECK(public.category_access(tenant_id,category_id,true) AND '
 'public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM public.projects p WHERE '
 'p.tenant_id=external_wait_versions.tenant_id AND '
 'p.category_id=external_wait_versions.category_id AND '
 'p.product_id=external_wait_versions.product_id AND p.id=external_wait_versions.project_id AND '
 'p.owner_id=external_wait_versions.owner_id AND p.visibility=external_wait_versions.visibility))',
 'REVOKE ALL ON public."external_wait_versions" FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'GRANT SELECT,INSERT ON public."external_wait_versions" TO pdos_next_app',
 'ALTER TABLE public."external_wait_currents" ENABLE ROW LEVEL SECURITY',
 'ALTER TABLE public."external_wait_currents" FORCE ROW LEVEL SECURITY',
 'CREATE POLICY owner_internal ON public."external_wait_currents" TO pdos_next_owner USING(true) '
 'WITH CHECK(true)',
 'CREATE POLICY external_wait_read ON public."external_wait_currents" FOR SELECT TO pdos_next_app '
 'USING(public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM public.projects p '
 'WHERE p.tenant_id=external_wait_currents.tenant_id AND '
 'p.category_id=external_wait_currents.category_id AND '
 'p.product_id=external_wait_currents.product_id AND p.id=external_wait_currents.project_id AND '
 'p.owner_id=external_wait_currents.owner_id AND p.visibility=external_wait_currents.visibility))',
 'CREATE POLICY external_wait_insert ON public."external_wait_currents" FOR INSERT TO '
 'pdos_next_app WITH CHECK(public.category_access(tenant_id,category_id,true) AND '
 'public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM public.projects p WHERE '
 'p.tenant_id=external_wait_currents.tenant_id AND '
 'p.category_id=external_wait_currents.category_id AND '
 'p.product_id=external_wait_currents.product_id AND p.id=external_wait_currents.project_id AND '
 'p.owner_id=external_wait_currents.owner_id AND p.visibility=external_wait_currents.visibility))',
 'REVOKE ALL ON public."external_wait_currents" FROM '
 'PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'GRANT SELECT,INSERT ON public."external_wait_currents" TO pdos_next_app',
 'CREATE POLICY external_wait_advance ON public."external_wait_currents" FOR UPDATE TO '
 'pdos_next_app USING(public.category_access(tenant_id,category_id,true) AND '
 'public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM public.projects p WHERE '
 'p.tenant_id=external_wait_currents.tenant_id AND '
 'p.category_id=external_wait_currents.category_id AND '
 'p.product_id=external_wait_currents.product_id AND p.id=external_wait_currents.project_id AND '
 'p.owner_id=external_wait_currents.owner_id AND p.visibility=external_wait_currents.visibility)) '
 'WITH CHECK(public.category_access(tenant_id,category_id,true) AND '
 'public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM public.projects p WHERE '
 'p.tenant_id=external_wait_currents.tenant_id AND '
 'p.category_id=external_wait_currents.category_id AND '
 'p.product_id=external_wait_currents.product_id AND p.id=external_wait_currents.project_id AND '
 'p.owner_id=external_wait_currents.owner_id AND p.visibility=external_wait_currents.visibility))',
 'GRANT UPDATE(version_id,revision,state) ON public."external_wait_currents" TO pdos_next_app',
 'CREATE TRIGGER external_wait_immutable BEFORE UPDATE OR DELETE ON public.external_wait_versions '
 'FOR EACH ROW EXECUTE FUNCTION public.reject_work_mutation()',
 'CREATE CONSTRAINT TRIGGER external_wait_atom AFTER INSERT ON public.external_wait_versions '
 'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_external_wait()',
 'CREATE TRIGGER external_wait_current_guard BEFORE INSERT OR UPDATE OR DELETE ON '
 'public.external_wait_currents FOR EACH ROW EXECUTE FUNCTION '
 'public.protect_external_wait_current()',
 'CREATE CONSTRAINT TRIGGER external_wait_current_atom AFTER INSERT OR UPDATE ON '
 'public.external_wait_currents DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION '
 'public.require_external_wait_current()',
 'CREATE OR REPLACE FUNCTION public.work_receipt_project_visible(t uuid, c uuid, p uuid, kind '
 'text, target uuid, rev integer, receipt uuid, actor uuid)\n'
 ' RETURNS boolean\n'
 ' LANGUAGE plpgsql\n'
 ' STABLE STRICT SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 'DECLARE project_id uuid; project_owner uuid; project_visibility text; actual_project '
 'public.projects;\n'
 'BEGIN\n'
 ' IF NOT public.category_access(t,c) THEN RETURN false; END IF;\n'
 " IF kind='work_task' THEN\n"
 '  SELECT x.project_id,x.owner_id,x.visibility INTO project_id,project_owner,project_visibility\n'
 '   FROM public.work_task_versions x WHERE x.tenant_id=t AND x.category_id=c AND x.product_id=p '
 'AND x.id=target AND x.revision=rev AND x.receipt_id=receipt AND x.actor_id=actor;\n'
 " ELSIF kind='work_commitment' THEN\n"
 '  SELECT x.project_id,x.owner_id,x.visibility INTO project_id,project_owner,project_visibility\n'
 '   FROM public.work_commitment_versions x WHERE x.tenant_id=t AND x.category_id=c AND '
 'x.product_id=p AND x.id=target AND x.revision=rev AND x.receipt_id=receipt AND '
 'x.actor_id=actor;\n'
 " ELSIF kind='project_status_update' THEN\n"
 '  SELECT x.project_id,x.owner_id,x.visibility INTO project_id,project_owner,project_visibility\n'
 '   FROM public.project_status_updates x WHERE x.tenant_id=t AND x.category_id=c AND '
 'x.product_id=p AND x.id=target AND x.revision=rev AND x.receipt_id=receipt AND '
 'x.actor_id=actor;\n'
 " ELSIF kind='work_commitment_review' THEN\n"
 '  SELECT x.project_id,x.owner_id,x.visibility INTO project_id,project_owner,project_visibility\n'
 '   FROM public.work_commitment_reviews x WHERE x.tenant_id=t AND x.category_id=c AND '
 'x.product_id=p AND x.id=target AND x.revision=rev AND x.receipt_id=receipt AND '
 'x.actor_id=actor;\n'
 " ELSIF kind='external_wait' THEN\n"
 '  SELECT x.project_id,x.owner_id,x.visibility INTO project_id,project_owner,project_visibility '
 'FROM public.external_wait_versions x WHERE x.tenant_id=t AND x.category_id=c AND x.product_id=p '
 'AND x.id=target AND x.revision=rev AND x.receipt_id=receipt AND x.actor_id=actor;\n'
 ' ELSE RETURN false; END IF;\n'
 ' IF project_id IS NULL THEN RETURN false; END IF;\n'
 ' SELECT * INTO actual_project FROM public.projects x WHERE x.tenant_id=t AND x.category_id=c AND '
 'x.product_id=p AND x.id=project_id AND x.owner_id=project_owner AND '
 'x.visibility=project_visibility;\n'
 " RETURN actual_project.id IS NOT NULL AND (actual_project.visibility='category' OR "
 'actual_project.owner_id=public.scope_requester() OR EXISTS(\n'
 '  SELECT 1 FROM public.object_audiences a WHERE a.tenant_id=t AND a.category_id=c AND '
 "a.object_type='projects'\n"
 '   AND a.subject_id=actual_project.id AND a.owner_id=actual_project.owner_id AND '
 'a.principal_id=public.scope_requester()));\n'
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
 "ARRAY['agent_runs','action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents'] "
 'ELSE ARRAY[\n'
 "  'artifact_versions','claims','definition_revisions','definition_sources','definition_specs',\n"
 '  '
 "'proposals','proposal_items','proposal_item_versions','proposal_submissions','proposal_decisions',\n"
 '  '
 "'category_knowledge_entries','category_knowledge_current','parameter_versions','parameter_current',\n"
 '  '
 "'evidence_links','promotion_proofs','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents'] "
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
 "name<>ALL(ARRAY['native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','external_wait_versions','external_wait_currents','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals']) "
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
 "  WHEN 'external_handoff_authorizations' THEN "
 "ARRAY['package_id','engineering_decision_id','manufacturing_decision_id']\n"
 "  WHEN 'external_delivery_intents' THEN ARRAY['handoff_id']\n"
 "  WHEN 'external_receipts' THEN "
 "ARRAY['handoff_id','intent_id','previous_receipt_id','reconciles_id']\n"
 "  WHEN 'external_handoff_currents' THEN ARRAY['handoff_id','intent_id','latest_receipt_id']\n"
 "  WHEN 'release_exception_decisions' THEN "
 "ARRAY['basis_package_id','policy_fact_id','previous_id']\n"
 "  WHEN 'release_exception_currents' THEN "
 "ARRAY['basis_package_id','policy_fact_id','decision_id']\n"
 "  WHEN 'work_commitment_reviews' THEN "
 "ARRAY['commitment_id','task_version_id','submission_id','previous_id']\n"
 "  WHEN 'work_commitment_review_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'external_wait_versions' THEN ARRAY['previous_id']\n"
 "  WHEN 'external_wait_currents' THEN ARRAY['version_id']\n"
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
 " IF table_name IN ('external_handoff_authorizations','external_delivery_intents') THEN\n"
 '  -- Only closed, owner-verified mapping and manifest references are source edges.\n'
 "  container=CASE WHEN table_name='external_handoff_authorizations' THEN "
 "payload#>'{body,declaration}' ELSE payload->'body' END;\n"
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'mappings','[]')) LOOP\n"
 '   IF '
 "item->'ref'->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','part','bom_revision','artifact','work_instruction','control_plan'])\n"
 "    AND item->'ref'->>'id' IS NOT NULL THEN "
 "links=array_append(links,(item->'ref'->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'manifest','[]')) LOOP\n"
 "   IF item->'artifact'->>'id' IS NOT NULL THEN "
 "links=array_append(links,(item->'artifact'->>'id')::uuid); END IF;\n"
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
 '\n'
 " IF table_name IN ('work_task_versions','work_commitment_versions','project_status_updates') "
 'THEN\n'
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP\n"
 "   IF item->>'artifact_id' IS NOT NULL THEN "
 "links=array_append(links,(item->>'artifact_id')::uuid); END IF;\n"
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
 "   IF item->>'artifact_id' IS NOT NULL THEN "
 "links=array_append(links,(item->>'artifact_id')::uuid); END IF;\n"
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
 "   IF container->>'id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); END "
 'IF;\n'
 '  END LOOP;\n'
 "  container=payload#>'{body,replaces}';\n"
 "  IF container->>'id' IS NOT NULL THEN\n"
 "   SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.external_wait_versions\n"
 "    WHERE tenant_id=t AND category_id=c AND wait_id=(container->>'id')::uuid AND "
 "revision=(container->>'revision')::integer;\n"
 '   links=links||extra;\n'
 '  END IF;\n'
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
 '$function$\n')

DOWNGRADE_SQL = ('LOCK TABLE public.external_wait_versions,public.external_wait_currents,public.action_receipts IN '
 'ACCESS EXCLUSIVE MODE',
 'DO $external_wait$ BEGIN IF EXISTS(SELECT 1 FROM public.external_wait_versions) OR EXISTS(SELECT '
 '1 FROM public.external_wait_currents) OR EXISTS(SELECT 1 FROM public.action_receipts WHERE '
 "operation='work.external_wait.record' OR subject_type='external_wait') THEN RAISE EXCEPTION "
 "'External waiting history retained; downgrade refused' USING ERRCODE='23514'; END IF; END; "
 '$external_wait$',
 'CREATE OR REPLACE FUNCTION public.work_receipt_project_visible(t uuid, c uuid, p uuid, kind '
 'text, target uuid, rev integer, receipt uuid, actor uuid)\n'
 ' RETURNS boolean\n'
 ' LANGUAGE plpgsql\n'
 ' STABLE STRICT SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 'DECLARE project_id uuid; project_owner uuid; project_visibility text; actual_project '
 'public.projects;\n'
 'BEGIN\n'
 ' IF NOT public.category_access(t,c) THEN RETURN false; END IF;\n'
 " IF kind='work_task' THEN\n"
 '  SELECT x.project_id,x.owner_id,x.visibility INTO project_id,project_owner,project_visibility\n'
 '   FROM public.work_task_versions x WHERE x.tenant_id=t AND x.category_id=c AND x.product_id=p '
 'AND x.id=target AND x.revision=rev AND x.receipt_id=receipt AND x.actor_id=actor;\n'
 " ELSIF kind='work_commitment' THEN\n"
 '  SELECT x.project_id,x.owner_id,x.visibility INTO project_id,project_owner,project_visibility\n'
 '   FROM public.work_commitment_versions x WHERE x.tenant_id=t AND x.category_id=c AND '
 'x.product_id=p AND x.id=target AND x.revision=rev AND x.receipt_id=receipt AND '
 'x.actor_id=actor;\n'
 " ELSIF kind='project_status_update' THEN\n"
 '  SELECT x.project_id,x.owner_id,x.visibility INTO project_id,project_owner,project_visibility\n'
 '   FROM public.project_status_updates x WHERE x.tenant_id=t AND x.category_id=c AND '
 'x.product_id=p AND x.id=target AND x.revision=rev AND x.receipt_id=receipt AND '
 'x.actor_id=actor;\n'
 " ELSIF kind='work_commitment_review' THEN\n"
 '  SELECT x.project_id,x.owner_id,x.visibility INTO project_id,project_owner,project_visibility\n'
 '   FROM public.work_commitment_reviews x WHERE x.tenant_id=t AND x.category_id=c AND '
 'x.product_id=p AND x.id=target AND x.revision=rev AND x.receipt_id=receipt AND '
 'x.actor_id=actor;\n'
 ' ELSE RETURN false; END IF;\n'
 ' IF project_id IS NULL THEN RETURN false; END IF;\n'
 ' SELECT * INTO actual_project FROM public.projects x WHERE x.tenant_id=t AND x.category_id=c AND '
 'x.product_id=p AND x.id=project_id AND x.owner_id=project_owner AND '
 'x.visibility=project_visibility;\n'
 " RETURN actual_project.id IS NOT NULL AND (actual_project.visibility='category' OR "
 'actual_project.owner_id=public.scope_requester() OR EXISTS(\n'
 '  SELECT 1 FROM public.object_audiences a WHERE a.tenant_id=t AND a.category_id=c AND '
 "a.object_type='projects'\n"
 '   AND a.subject_id=actual_project.id AND a.owner_id=actual_project.owner_id AND '
 'a.principal_id=public.scope_requester()));\n'
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
 "ARRAY['agent_runs','action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates'] "
 'ELSE ARRAY[\n'
 "  'artifact_versions','claims','definition_revisions','definition_sources','definition_specs',\n"
 '  '
 "'proposals','proposal_items','proposal_item_versions','proposal_submissions','proposal_decisions',\n"
 '  '
 "'category_knowledge_entries','category_knowledge_current','parameter_versions','parameter_current',\n"
 '  '
 "'evidence_links','promotion_proofs','native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates'] "
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
 "name<>ALL(ARRAY['native_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages','release_package_currents','release_decisions','release_policy_facts','release_policy_currents','external_handoff_authorizations','external_delivery_intents','external_receipts','external_handoff_currents','release_exception_decisions','release_exception_currents','work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_task_currents','work_commitment_versions','work_commitment_currents','project_status_updates','manufacturing_baseline_publications','manufacturing_publication_currents','manufacturing_publication_documents','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_submissions','proposal_decisions','project_open_items','category_knowledge_entries','category_knowledge_current','product_target_segments','parameter_versions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals']) "
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
 "  WHEN 'external_handoff_authorizations' THEN "
 "ARRAY['package_id','engineering_decision_id','manufacturing_decision_id']\n"
 "  WHEN 'external_delivery_intents' THEN ARRAY['handoff_id']\n"
 "  WHEN 'external_receipts' THEN "
 "ARRAY['handoff_id','intent_id','previous_receipt_id','reconciles_id']\n"
 "  WHEN 'external_handoff_currents' THEN ARRAY['handoff_id','intent_id','latest_receipt_id']\n"
 "  WHEN 'release_exception_decisions' THEN "
 "ARRAY['basis_package_id','policy_fact_id','previous_id']\n"
 "  WHEN 'release_exception_currents' THEN "
 "ARRAY['basis_package_id','policy_fact_id','decision_id']\n"
 "  WHEN 'work_commitment_reviews' THEN "
 "ARRAY['commitment_id','task_version_id','submission_id','previous_id']\n"
 "  WHEN 'work_commitment_review_currents' THEN ARRAY['version_id']\n"
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
 " IF table_name IN ('external_handoff_authorizations','external_delivery_intents') THEN\n"
 '  -- Only closed, owner-verified mapping and manifest references are source edges.\n'
 "  container=CASE WHEN table_name='external_handoff_authorizations' THEN "
 "payload#>'{body,declaration}' ELSE payload->'body' END;\n"
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'mappings','[]')) LOOP\n"
 '   IF '
 "item->'ref'->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','part','bom_revision','artifact','work_instruction','control_plan'])\n"
 "    AND item->'ref'->>'id' IS NOT NULL THEN "
 "links=array_append(links,(item->'ref'->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'manifest','[]')) LOOP\n"
 "   IF item->'artifact'->>'id' IS NOT NULL THEN "
 "links=array_append(links,(item->'artifact'->>'id')::uuid); END IF;\n"
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
 '\n'
 " IF table_name IN ('work_task_versions','work_commitment_versions','project_status_updates') "
 'THEN\n'
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP\n"
 "   IF item->>'artifact_id' IS NOT NULL THEN "
 "links=array_append(links,(item->>'artifact_id')::uuid); END IF;\n"
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
 "   IF item->>'artifact_id' IS NOT NULL THEN "
 "links=array_append(links,(item->>'artifact_id')::uuid); END IF;\n"
 '  END LOOP;\n'
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
 "  WHEN 'external_handoff_authorizations' THEN ARRAY['project_id']\n"
 "  WHEN 'external_delivery_intents' THEN ARRAY['project_id']\n"
 "  WHEN 'external_receipts' THEN ARRAY['project_id']\n"
 "  WHEN 'external_handoff_currents' THEN ARRAY['project_id']\n"
 "  WHEN 'release_exception_decisions' THEN ARRAY['project_id','series_id']\n"
 "  WHEN 'release_exception_currents' THEN ARRAY['project_id','series_id']\n"
 "  WHEN 'work_commitment_reviews' THEN ARRAY['project_id']\n"
 "  WHEN 'work_commitment_review_currents' THEN ARRAY['project_id']\n"
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
 'CREATE OR REPLACE FUNCTION public.assert_work_management_members(t uuid, target uuid, kind '
 'text)\n'
 ' RETURNS void\n'
 ' LANGUAGE plpgsql\n'
 ' SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 '\n'
 'DECLARE v record; r public.action_receipts; c public.confirmations; expected_status text; '
 'event_name text; expected_result jsonb;\n'
 'BEGIN\n'
 '\n'
 " IF kind='work_task' THEN SELECT * INTO STRICT v FROM public.work_task_versions WHERE "
 'tenant_id=t AND id=target;\n'
 " ELSIF kind='work_commitment' THEN SELECT * INTO STRICT v FROM public.work_commitment_versions "
 'WHERE tenant_id=t AND id=target;\n'
 " ELSIF kind='project_status_update' THEN SELECT * INTO STRICT v FROM "
 'public.project_status_updates WHERE tenant_id=t AND id=target;\n'
 " ELSE RAISE EXCEPTION 'Unknown work subject' USING ERRCODE='23514'; END IF;\n"
 '\n'
 " expected_status=CASE WHEN kind='work_task' THEN v.body->>'state' ELSE 'recorded' END;\n"
 " expected_result=jsonb_build_object('id',v.id,'revision',v.revision,'status',expected_status);\n"
 " IF kind='work_task' THEN "
 "expected_result=expected_result||jsonb_build_object('task_id',v.task_id,'state',v.state,'project_id',v.project_id);\n"
 " ELSIF kind='work_commitment' THEN "
 "expected_result=expected_result||jsonb_build_object('task_id',v.task_id,'recipient_id',v.recipient_id);\n"
 " ELSE expected_result=expected_result||jsonb_build_object('project_id',v.project_id); END IF;\n"
 " event_name=CASE v.operation WHEN 'work.task.create' THEN 'task.created' WHEN 'work.task.assign' "
 "THEN 'task.assigned'\n"
 "  WHEN 'work.task.accept' THEN 'task.accepted' WHEN 'work.task.start' THEN 'task.started'\n"
 "  WHEN 'work.task.submit' THEN 'task.submitted' WHEN 'work.task.review' THEN 'task.reviewed'\n"
 "  WHEN 'work.commitment.accept' THEN 'commitment.accepted' WHEN 'work.status_update.create' THEN "
 "'project.status_updated' END;\n"
 ' SELECT * INTO STRICT r FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;\n'
 ' IF '
 'ROW(r.category_id,r.product_id,r.command_id,r.confirmation_id,r.actor_id,r.requester_id,r.operation,r.subject_type,r.subject_id,r.subject_revision,r.visibility,r.request_digest,r.intent_digest)\n'
 '  IS DISTINCT FROM '
 'ROW(v.category_id,v.product_id,v.command_id,v.confirmation_id,v.actor_id,v.requester_id,v.operation,kind::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)\n'
 '  OR r.result IS DISTINCT FROM expected_result\n'
 '  OR r.created_at<v.created_at OR event_name IS NULL\n'
 '  OR (SELECT count(*) FROM public.action_receipts x WHERE x.tenant_id=t AND '
 'x.operation=v.operation AND x.subject_type=kind AND x.subject_id=v.id AND '
 'x.subject_revision=v.revision)<>1\n'
 '  OR (SELECT count(*) FROM public.audit_entries a WHERE a.tenant_id=t AND a.receipt_id=r.id)<>1\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.audit_entries a WHERE a.tenant_id=t AND a.receipt_id=r.id '
 'AND a.category_id=v.category_id AND a.actor_id=v.actor_id AND a.operation=v.operation AND '
 'a.created_at>=v.created_at)\n'
 '  OR (SELECT count(*) FROM public.outbox_events e WHERE e.tenant_id=t AND e.receipt_id=r.id)<>1\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.outbox_events e WHERE e.tenant_id=t AND e.receipt_id=r.id '
 'AND e.category_id=v.category_id AND e.actor_id=v.actor_id AND e.type=event_name AND '
 'e.subject_id=v.id AND e.subject_revision=v.revision AND e.schema_version=1 AND '
 'e.correlation_id=coalesce(r.agent_run_id,r.run_id,v.command_id) AND e.created_at>=v.created_at)\n'
 "  OR v.command->>'original_key_sha256' IS NULL OR v.command->>'original_key_sha256' !~ "
 "'^[a-f0-9]{64}$'\n"
 "  OR v.command->'envelope' ? 'idempotency_key' OR v.command->'envelope'->'payload' ? "
 "'confirmation_token'\n"
 '  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND '
 'k.category_id=v.category_id AND k.actor_id=v.actor_id AND k.receipt_id=r.id AND '
 'k.digest=v.request_digest AND '
 "encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.command->>'original_key_sha256') THEN\n"
 "  RAISE EXCEPTION 'Work fact original common group mismatch' USING ERRCODE='23514'; END IF;\n"
 " IF v.operation<>'work.task.create' THEN\n"
 '  SELECT * INTO STRICT c FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;\n'
 '  IF c.consumed IS DISTINCT FROM true OR ROW(c.category_id,c.product_id,c.actor_id,c.operation)\n'
 '   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.actor_id,v.operation)\n'
 "   OR c.subject_type IS DISTINCT FROM 'product' OR c.subject_id IS DISTINCT FROM v.product_id\n"
 "   OR c.revision::text IS DISTINCT FROM v.command->'envelope'->>'expected_revision'\n"
 "   OR c.snapshot IS DISTINCT FROM v.command->'review' OR c.created_at>v.created_at\n"
 '   OR c.expires_at IS NULL OR v.created_at>=c.expires_at OR r.created_at>=c.expires_at\n'
 '   OR r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL THEN\n'
 "   RAISE EXCEPTION 'Work T1 needs its actual consumed confirmation' USING ERRCODE='23514'; END "
 'IF;\n'
 ' END IF;\n'
 'END;\n'
 '$function$\n',
 'CREATE OR REPLACE FUNCTION public.assert_work_management_write(t uuid, target uuid, kind text)\n'
 ' RETURNS void\n'
 ' LANGUAGE plpgsql\n'
 ' SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 '\n'
 'DECLARE v record; p public.projects; envelope jsonb; ref jsonb; basis jsonb; vx xid; rx xid; cx '
 'xid;\n'
 'BEGIN\n'
 '\n'
 " IF kind='work_task' THEN SELECT * INTO STRICT v FROM public.work_task_versions WHERE "
 'tenant_id=t AND id=target;\n'
 " ELSIF kind='work_commitment' THEN SELECT * INTO STRICT v FROM public.work_commitment_versions "
 'WHERE tenant_id=t AND id=target;\n'
 " ELSIF kind='project_status_update' THEN SELECT * INTO STRICT v FROM "
 'public.project_status_updates WHERE tenant_id=t AND id=target;\n'
 " ELSE RAISE EXCEPTION 'Unknown work subject' USING ERRCODE='23514'; END IF;\n"
 '\n'
 " IF kind='work_task' THEN SELECT xmin INTO vx FROM public.work_task_versions WHERE tenant_id=t "
 'AND id=target;\n'
 " ELSIF kind='work_commitment' THEN SELECT xmin INTO vx FROM public.work_commitment_versions "
 'WHERE tenant_id=t AND id=target;\n'
 ' ELSE SELECT xmin INTO vx FROM public.project_status_updates WHERE tenant_id=t AND id=target; '
 'END IF;\n'
 ' SELECT * INTO STRICT p FROM public.projects WHERE tenant_id=t AND id=v.project_id;\n'
 ' SELECT xmin INTO rx FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;\n'
 ' PERFORM public.assert_work_management_members(t,target,kind);\n'
 " envelope=v.command->'envelope';\n"
 '\n'
 " IF kind='work_task' THEN PERFORM public.assert_work_task_g0_source(t,target);\n"
 " ELSIF v.source_basis ? 'g0_open_item' THEN\n"
 "  RAISE EXCEPTION 'Only a task may use a native G0 source basis' USING ERRCODE='23514'; END IF;\n"
 ' IF ROW(p.category_id,p.product_id,p.owner_id,p.visibility) IS DISTINCT FROM '
 'ROW(v.category_id,v.product_id,v.owner_id,v.visibility)\n'
 '  OR v.actor_id IS DISTINCT FROM public.scope_actor() OR v.requester_id IS DISTINCT FROM '
 'public.scope_requester()\n'
 '  OR v.writer_id<>v.actor_id OR vx IS DISTINCT FROM rx OR NOT '
 'public.category_access(t,v.category_id,true)\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.principals a WHERE a.tenant_id=t AND a.id=v.actor_id AND '
 'a.active)\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.principals a WHERE a.tenant_id=t AND a.id=v.requester_id '
 "AND a.kind='human' AND a.active)\n"
 "  OR envelope->>'operation' IS DISTINCT FROM v.operation OR envelope->>'command_id' IS DISTINCT "
 'FROM v.command_id::text\n'
 "  OR envelope->>'category_id' IS DISTINCT FROM v.category_id::text OR envelope->>'product_id' IS "
 'DISTINCT FROM v.product_id::text\n'
 "  OR envelope->'payload'->>'project_id' IS DISTINCT FROM v.project_id::text\n"
 "  OR v.command->'review'->'declaration' IS DISTINCT FROM envelope->'payload'\n"
 "  OR v.command->'review'->>'operation' IS DISTINCT FROM v.operation\n"
 "  OR v.command->'review'->'sources' IS DISTINCT FROM v.sources\n"
 "  OR v.command->'review'->'source_basis' IS DISTINCT FROM v.source_basis\n"
 "  OR (v.body #- '{recorded_at}' #- '{actual_start,recorded_at}' #- "
 "'{submission,time,recorded_at}' #- '{review,time,recorded_at}') IS DISTINCT FROM "
 "v.command->'review'->'after'\n"
 '  OR NOT EXISTS(SELECT 1 FROM public.products x WHERE x.tenant_id=t AND '
 'x.category_id=v.category_id AND x.id=v.product_id AND '
 "x.revision::text=envelope->>'expected_revision')\n"
 "  OR NOT COALESCE(envelope->'source_read_set' @> v.reads,false) OR NOT COALESCE(v.reads @> "
 "(envelope->'source_read_set'),false)\n"
 "  OR jsonb_array_length(envelope->'source_read_set')<>jsonb_array_length(v.reads)\n"
 '  OR NOT public.direct_source_set_visible(t,v.category_id,v.product_id,v.reads)\n'
 "  OR (v.operation<>'work.task.create' AND (v.actor_id<>v.requester_id OR NOT EXISTS(SELECT 1 "
 "FROM public.principals a WHERE a.tenant_id=t AND a.id=v.actor_id AND a.kind='human')))\n"
 "  OR (v.operation='work.task.create' AND v.actor_id<>v.requester_id AND NOT EXISTS(SELECT 1 FROM "
 'public.action_receipts r WHERE r.tenant_id=t AND r.id=v.receipt_id AND '
 'coalesce(r.agent_run_id,r.run_id) IS NOT NULL))\n'
 '  OR EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)\n'
 '  OR EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND '
 'k.receipt_id=v.receipt_id AND k.actor_id=v.actor_id AND k.digest=v.request_digest AND k.xmin=vx '
 "AND encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.command->>'original_key_sha256') THEN\n"
 "  RAISE EXCEPTION 'Work fact requires actual project actor and one transaction' USING "
 "ERRCODE='23514'; END IF;\n"
 ' IF v.confirmation_id IS NOT NULL THEN\n'
 '  SELECT xmin INTO cx FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;\n'
 "  IF cx IS DISTINCT FROM vx THEN RAISE EXCEPTION 'Work confirmation consumption must share its "
 "new fact transaction' USING ERRCODE='23514'; END IF;\n"
 ' END IF;\n'
 " IF jsonb_typeof(v.source_basis->'artifacts') IS DISTINCT FROM 'array' THEN\n"
 "  RAISE EXCEPTION 'Work direct source metadata required' USING ERRCODE='23514'; END IF;\n"
 " FOR basis IN SELECT value FROM jsonb_array_elements(v.source_basis->'artifacts') LOOP\n"
 '  IF NOT EXISTS(SELECT 1 FROM public.artifact_versions a WHERE a.tenant_id=t AND '
 'a.category_id=v.category_id\n'
 "   AND (a.product_id IS NULL OR a.product_id=v.product_id) AND a.id::text=basis->>'id'\n"
 "   AND a.revision::text=basis->>'revision' AND a.content_hash=basis->>'hash' AND "
 "a.status='active'\n"
 "   AND a.status=basis->>'status' AND a.owner_id::text=basis->>'owner_id' AND "
 "a.visibility=basis->>'visibility'\n"
 "   AND (v.visibility='private' OR a.visibility<>'private')\n"
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
 "    AND (v.visibility='private' OR a.visibility<>'private')\n"
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
 "        AND (v.visibility='private' OR o.visibility<>'private'))))) THEN\n"
 "   RAISE EXCEPTION 'Work source metadata security or audience changed' USING ERRCODE='23514'; "
 'END IF;\n'
 ' END LOOP;\n'
 'END;\n'
 '$function$\n',
 'CREATE OR REPLACE FUNCTION public.protect_work_receipt()\n'
 ' RETURNS trigger\n'
 ' LANGUAGE plpgsql\n'
 ' SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 '\n'
 'DECLARE scoped boolean=false;\n'
 'BEGIN\n'
 " IF TG_OP<>'INSERT' THEN scoped=OLD.operation IN "
 "('work.task.create','work.task.assign','work.task.accept','work.commitment.accept','work.task.start','work.task.submit','work.task.review','work.status_update.create') "
 "OR OLD.subject_type IN ('work_task','work_commitment','project_status_update'); END IF;\n"
 " IF TG_OP<>'DELETE' THEN scoped=scoped OR NEW.operation IN "
 "('work.task.create','work.task.assign','work.task.accept','work.commitment.accept','work.task.start','work.task.submit','work.task.review','work.status_update.create') "
 "OR NEW.subject_type IN ('work_task','work_commitment','project_status_update'); END IF;\n"
 " IF scoped AND TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Work receipt immutable' USING "
 "ERRCODE='23514'; END IF;\n"
 " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
 'END;\n'
 '$function$\n',
 'CREATE OR REPLACE FUNCTION public.protect_work_member()\n'
 ' RETURNS trigger\n'
 ' LANGUAGE plpgsql\n'
 ' SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 '\n'
 'DECLARE scoped boolean=false; old_scoped boolean=false;\n'
 'BEGIN\n'
 " IF TG_OP<>'DELETE' THEN SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE "
 'r.tenant_id=NEW.tenant_id AND r.id=NEW.receipt_id AND (r.operation IN '
 "('work.task.create','work.task.assign','work.task.accept','work.commitment.accept','work.task.start','work.task.submit','work.task.review','work.status_update.create') "
 "OR r.subject_type IN ('work_task','work_commitment','project_status_update'))) INTO scoped; END "
 'IF;\n'
 " IF TG_OP<>'INSERT' THEN SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE "
 'r.tenant_id=OLD.tenant_id AND r.id=OLD.receipt_id AND (r.operation IN '
 "('work.task.create','work.task.assign','work.task.accept','work.commitment.accept','work.task.start','work.task.submit','work.task.review','work.status_update.create') "
 "OR r.subject_type IN ('work_task','work_commitment','project_status_update'))) INTO old_scoped; "
 'END IF;\n'
 " IF TG_OP<>'INSERT' AND (scoped OR old_scoped) THEN\n"
 "  IF TG_OP='UPDATE' AND TG_TABLE_NAME='outbox_events' AND "
 "(to_jsonb(NEW)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) IS NOT "
 'DISTINCT FROM '
 "(to_jsonb(OLD)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) THEN "
 'RETURN NEW; END IF;\n'
 "  RAISE EXCEPTION 'Work audit event or original key immutable' USING ERRCODE='23514'; END IF;\n"
 " IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;\n"
 'END;\n'
 '$function$\n',
 'CREATE OR REPLACE FUNCTION public.require_work_member()\n'
 ' RETURNS trigger\n'
 ' LANGUAGE plpgsql\n'
 ' SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 '\n'
 'DECLARE r public.action_receipts;\n'
 'BEGIN\n'
 " IF TG_TABLE_NAME='action_receipts' THEN r=NEW; ELSE SELECT * INTO r FROM public.action_receipts "
 'WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id; END IF;\n'
 ' IF r.operation IN '
 "('work.task.create','work.task.assign','work.task.accept','work.commitment.accept','work.task.start','work.task.submit','work.task.review','work.status_update.create') "
 "OR r.subject_type IN ('work_task','work_commitment','project_status_update') THEN PERFORM "
 'public.assert_work_management_members(r.tenant_id,r.subject_id,r.subject_type::text); END IF;\n'
 ' RETURN NULL;\n'
 'END;\n'
 '$function$\n',
 'DROP TABLE public.external_wait_currents',
 'DROP TABLE public.external_wait_versions',
 'DROP FUNCTION public.require_external_wait_current()',
 'DROP FUNCTION public.protect_external_wait_current()',
 'DROP FUNCTION public.require_external_wait()',
 'DROP FUNCTION public.assert_external_wait(uuid,uuid)',
 'DROP FUNCTION public.assert_external_wait_calendar(uuid,uuid)')

