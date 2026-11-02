# ruff: noqa: E501 -- frozen PostgreSQL definitions preserve their original SQL text
"""Track model consumption of category originals and preserve their actual fence."""

from alembic import op

revision = "s0_0421"
down_revision = "s0_0420"
branch_labels = None
depends_on = None
PREVIOUS_CLOCK = "CREATE FUNCTION public.category_lifecycle_clock() RETURNS trigger\nLANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$\nDECLARE payload jsonb; affected integer;\nBEGIN\n IF TG_OP='DELETE' THEN payload=to_jsonb(OLD); ELSE payload=to_jsonb(NEW); END IF;\n IF TG_TABLE_NAME='action_receipts' AND payload->>'operation' LIKE 'evidence.lifecycle.%' THEN\n  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n END IF;\n UPDATE public.categories SET lifecycle_epoch=lifecycle_epoch+1\n WHERE id=(payload->>'category_id')::uuid AND tenant_id=(payload->>'tenant_id')::uuid;\n GET DIAGNOSTICS affected = ROW_COUNT;\n IF affected<>1 THEN RAISE EXCEPTION 'Reference category gate unavailable' USING ERRCODE='23514'; END IF;\n IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\nEND $$"
CLOCK = "CREATE OR REPLACE FUNCTION public.category_lifecycle_clock() RETURNS trigger\nLANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$\nDECLARE payload jsonb; affected integer; links uuid[]; original_ids uuid[]; p uuid; t uuid; c uuid;\nBEGIN\n IF TG_OP='DELETE' THEN payload=to_jsonb(OLD); ELSE payload=to_jsonb(NEW); END IF;\n IF TG_TABLE_NAME='action_receipts' AND payload->>'operation' LIKE 'evidence.lifecycle.%' THEN\n  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n END IF;\n p=(payload->>'product_id')::uuid; t=(payload->>'tenant_id')::uuid;\n c=(payload->>'category_id')::uuid;\n IF p IS NOT NULL AND NOT EXISTS (\n  SELECT 1 FROM public.artifact_versions a WHERE a.tenant_id=t AND a.category_id=c AND a.product_id IS NULL\n ) AND NOT EXISTS (\n  SELECT 1 FROM public.uploaded_originals o WHERE o.tenant_id=t AND o.category_id=c AND o.product_id IS NULL\n ) THEN\n  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n END IF;\n links=public.lifecycle_payload_links(payload);\n SELECT COALESCE(array_agg(a.original_id) FILTER (WHERE a.original_id IS NOT NULL),'{}')\n INTO original_ids FROM public.artifact_versions a\n WHERE a.tenant_id=t AND a.category_id=c AND a.product_id IS NULL AND a.id=ANY(links);\n IF p IS NOT NULL AND NOT EXISTS (\n  SELECT 1 FROM public.artifact_versions a WHERE a.tenant_id=t AND a.category_id=c\n   AND a.product_id IS NULL AND a.id=ANY(links)\n ) AND NOT EXISTS (\n  SELECT 1 FROM public.uploaded_originals o WHERE o.tenant_id=t AND o.category_id=c\n   AND o.product_id IS NULL AND o.id=ANY(links)\n ) THEN\n  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n END IF;\n UPDATE public.categories SET lifecycle_epoch=lifecycle_epoch+1 WHERE id=c AND tenant_id=t;\n GET DIAGNOSTICS affected = ROW_COUNT;\n IF affected<>1 THEN RAISE EXCEPTION 'Reference category gate unavailable' USING ERRCODE='23514'; END IF;\n IF TG_OP<>'DELETE' AND EXISTS (\n  SELECT 1 FROM public.lifecycle_objects o WHERE o.tenant_id=t AND o.category_id=c\n   AND o.product_id IS NULL AND o.id=ANY(links || original_ids)\n   AND ((o.state->'value'->>'pending_intent_id') IS NOT NULL\n    OR o.state->'value'->>'disposition' IN ('quarantined','unknown','purged'))\n ) THEN RAISE EXCEPTION 'Pending category original prohibits new references' USING ERRCODE='23514', CONSTRAINT='category_source_reference_fence'; END IF;\n IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\nEND $$"
PREVIOUS_SUMMARY = "CREATE OR REPLACE FUNCTION public.lifecycle_reference_summary(t uuid, c uuid, p uuid, roots uuid[])\n RETURNS TABLE(object_id uuid, reference_count integer, formal_history boolean, read_version bigint)\n LANGUAGE plpgsql\n STABLE SECURITY DEFINER\n SET search_path TO 'public', 'pg_temp'\nAS $function$\nDECLARE tables text[]=ARRAY['action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests']; table_name text; payload jsonb;\n graph jsonb[]='{}'; controls uuid[]; reached uuid[]='{}'; selected integer[]='{}';\n node jsonb; links uuid[]; row_id uuid; oid uuid; i integer; changed boolean;\nBEGIN\n IF NOT category_access(t,c,false) OR (p IS NOT NULL AND NOT EXISTS(\n  SELECT 1 FROM products WHERE id=p AND tenant_id=t AND category_id=c\n )) THEN RETURN; END IF;\n SELECT COALESCE(array_agg(id),'{}') INTO controls FROM action_receipts\n  WHERE tenant_id=t AND category_id=c AND product_id IS NOT DISTINCT FROM p AND operation LIKE 'evidence.lifecycle.%';\n FOREACH table_name IN ARRAY tables LOOP\n  FOR payload IN EXECUTE CASE WHEN table_name=ANY(ARRAY['audit_entries','outbox_events','request_keys'])\n   THEN format('SELECT to_jsonb(x) FROM public.%I x JOIN action_receipts r ON r.id=x.receipt_id AND r.tenant_id=x.tenant_id WHERE x.tenant_id=$1 AND r.product_id IS NOT DISTINCT FROM $2 AND r.category_id=$3',table_name)\n   ELSE format('SELECT to_jsonb(x) FROM public.%I x WHERE tenant_id=$1 AND product_id IS NOT DISTINCT FROM $2 AND category_id=$3',table_name)\n   END USING t,p,c LOOP\n   IF (payload->>'receipt_id')::uuid=ANY(controls) OR\n     (table_name='action_receipts' AND payload->>'operation' LIKE 'evidence.lifecycle.%') THEN CONTINUE; END IF;\n   graph=array_append(graph,jsonb_build_object('table',table_name,'id',payload->>'id',\n     'links',to_jsonb(lifecycle_payload_links(payload))));\n  END LOOP;\n END LOOP;\n SELECT lifecycle_epoch INTO read_version FROM products WHERE id=p AND tenant_id=t AND category_id=c;\n FOREACH oid IN ARRAY roots LOOP\n  IF NOT (\n   EXISTS(SELECT 1 FROM upload_attempts WHERE id=oid AND tenant_id=t AND category_id=c AND product_id IS NOT DISTINCT FROM p AND owner_id=scope_requester()) OR\n   EXISTS(SELECT 1 FROM uploaded_originals WHERE id=oid AND tenant_id=t AND category_id=c AND product_id IS NOT DISTINCT FROM p AND owner_id=scope_requester()) OR\n   EXISTS(SELECT 1 FROM lifecycle_objects WHERE id=oid AND tenant_id=t AND category_id=c AND product_id IS NOT DISTINCT FROM p AND owner_id=scope_requester())\n  ) THEN CONTINUE; END IF;\n  object_id=oid; reached=ARRAY[oid]; selected='{}'; changed=true;\n WHILE changed LOOP\n  changed=false;\n  IF cardinality(graph)>0 THEN\n   FOR i IN 1..cardinality(graph) LOOP\n    IF i=ANY(selected) THEN CONTINUE; END IF;\n    node=graph[i]; row_id=(node->>'id')::uuid;\n    SELECT COALESCE(array_agg(v::uuid),'{}') INTO links FROM jsonb_array_elements_text(node->'links') AS x(v);\n    IF row_id=oid OR links && reached THEN\n     selected=array_append(selected,i);\n     IF row_id IS NOT NULL AND NOT row_id=ANY(reached) THEN reached=array_append(reached,row_id); END IF;\n     changed=true;\n    END IF;\n   END LOOP;\n  END IF;\n END LOOP;\n reference_count=cardinality(selected); formal_history=false;\n FOREACH i IN ARRAY selected LOOP\n  IF NOT (graph[i]->>'table'=ANY(ARRAY['uploaded_originals','artifact_versions','original_security',\n    'original_scan_requests','original_scan_results','outbox_events','audit_entries'])) THEN\n   formal_history=true; EXIT;\n  END IF;\n END LOOP;\n RETURN NEXT;\n END LOOP;\nEND $function$\n"
SUMMARY = "CREATE OR REPLACE FUNCTION public.lifecycle_reference_summary(t uuid, c uuid, p uuid, roots uuid[])\n RETURNS TABLE(object_id uuid, reference_count integer, formal_history boolean, read_version bigint)\n LANGUAGE plpgsql\n STABLE SECURITY DEFINER\n SET search_path TO 'public', 'pg_temp'\nAS $function$\nDECLARE tables text[]=ARRAY['action_receipts','actual_configurations','artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decisions','build_current_authorizations','build_current_execution_assessments','build_execution_assessments','build_lots','build_operational_current','build_operational_facts','build_readiness','build_starts','builds','capa_current_observations','capa_current_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_remediation_links','capa_verification_evidence','capa_verification_rule_facts','change_approval_records','change_dependency_clocks','change_graph_captures','change_implementation_captures','change_implementation_records','change_order_records','change_request_currents','change_request_versions','claim_consumptions','claims','controlled_change_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts','controlled_change_selection_currents','controlled_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_revisions','definition_sources','definition_specs','engineering_configurations','manufacturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_preparation_versions','measurement_import_captures','operational_material_holds','operational_resource_occupancies','original_scan_requests','original_scan_results','original_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisions','product_variants','professional_authority_current','professional_authority_facts','project_product_links','project_tasks','project_work_packages','projects','quality_current_issues','quality_current_policies','quality_event_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','task_dependencies','test_measurements','test_resource_current','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','uploaded_originals','variant_revisions','verification_actual_method_applicabilities','verification_actual_method_batches','verification_current_actual_methods','verification_current_formal_requests','verification_current_preparations','verification_current_runs','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals','work_requests']; table_name text; payload jsonb;\n graph jsonb[]='{}'; controls uuid[]; reached uuid[]='{}'; selected integer[]='{}';\n node jsonb; links uuid[]; row_id uuid; oid uuid; i integer; changed boolean;\nBEGIN\n IF NOT category_access(t,c,false) OR (p IS NOT NULL AND NOT EXISTS(\n  SELECT 1 FROM products WHERE id=p AND tenant_id=t AND category_id=c\n )) THEN RETURN; END IF;\n SELECT COALESCE(array_agg(id),'{}') INTO controls FROM action_receipts\n  WHERE tenant_id=t AND category_id=c AND product_id IS NOT DISTINCT FROM p AND operation LIKE 'evidence.lifecycle.%';\n FOREACH table_name IN ARRAY tables LOOP\n  FOR payload IN EXECUTE CASE WHEN table_name=ANY(ARRAY['audit_entries','outbox_events','request_keys'])\n   THEN format('SELECT to_jsonb(x) FROM public.%I x JOIN action_receipts r ON r.id=x.receipt_id AND r.tenant_id=x.tenant_id WHERE x.tenant_id=$1 AND ( $2 IS NULL OR r.product_id=$2 ) AND r.category_id=$3',table_name)\n   ELSE format('SELECT to_jsonb(x) FROM public.%I x WHERE tenant_id=$1 AND ( $2 IS NULL OR product_id=$2 ) AND category_id=$3',table_name)\n   END USING t,p,c LOOP\n   IF (payload->>'receipt_id')::uuid=ANY(controls) OR\n     (table_name='action_receipts' AND payload->>'operation' LIKE 'evidence.lifecycle.%') THEN CONTINUE; END IF;\n   graph=array_append(graph,jsonb_build_object('table',table_name,'id',payload->>'id',\n     'links',to_jsonb(lifecycle_payload_links(payload))));\n  END LOOP;\n END LOOP;\n IF p IS NULL THEN\n  SELECT lifecycle_epoch INTO read_version FROM categories WHERE id=c AND tenant_id=t;\n ELSE\n  SELECT lifecycle_epoch INTO read_version FROM products WHERE id=p AND tenant_id=t AND category_id=c;\n END IF;\n FOREACH oid IN ARRAY roots LOOP\n  IF NOT (\n   EXISTS(SELECT 1 FROM upload_attempts WHERE id=oid AND tenant_id=t AND category_id=c AND product_id IS NOT DISTINCT FROM p AND owner_id=scope_requester()) OR\n   EXISTS(SELECT 1 FROM uploaded_originals WHERE id=oid AND tenant_id=t AND category_id=c AND product_id IS NOT DISTINCT FROM p AND owner_id=scope_requester()) OR\n   EXISTS(SELECT 1 FROM lifecycle_objects WHERE id=oid AND tenant_id=t AND category_id=c AND product_id IS NOT DISTINCT FROM p AND owner_id=scope_requester())\n  ) THEN CONTINUE; END IF;\n  object_id=oid; reached=ARRAY[oid]; selected='{}'; changed=true;\n WHILE changed LOOP\n  changed=false;\n  IF cardinality(graph)>0 THEN\n   FOR i IN 1..cardinality(graph) LOOP\n    IF i=ANY(selected) THEN CONTINUE; END IF;\n    node=graph[i]; row_id=(node->>'id')::uuid;\n    SELECT COALESCE(array_agg(v::uuid),'{}') INTO links FROM jsonb_array_elements_text(node->'links') AS x(v);\n    IF row_id=oid OR links && reached THEN\n     selected=array_append(selected,i);\n     IF row_id IS NOT NULL AND NOT row_id=ANY(reached) THEN reached=array_append(reached,row_id); END IF;\n     changed=true;\n    END IF;\n   END LOOP;\n  END IF;\n END LOOP;\n reference_count=cardinality(selected); formal_history=false;\n FOREACH i IN ARRAY selected LOOP\n  IF NOT (graph[i]->>'table'=ANY(ARRAY['uploaded_originals','artifact_versions','original_security',\n    'original_scan_requests','original_scan_results','outbox_events','audit_entries'])) THEN\n   formal_history=true; EXIT;\n  END IF;\n END LOOP;\n RETURN NEXT;\n END LOOP;\nEND $function$\n"
EXISTING_TABLES = (
    "action_receipts",
    "artifact_versions",
    "original_scan_requests",
    "original_scan_results",
    "original_security",
    "uploaded_originals",
    "upload_attempts",
)
NEW_TABLES = (
    "actual_configurations",
    "bom_lines",
    "bom_revisions",
    "build_lots",
    "build_readiness",
    "builds",
    "claim_consumptions",
    "claims",
    "cost_current_inputs",
    "cost_estimates",
    "cost_input_snapshots",
    "cost_source_captures",
    "definition_revisions",
    "definition_sources",
    "definition_specs",
    "engineering_configurations",
    "parts",
    "plan_proposals",
    "plan_revisions",
    "process_revisions",
    "product_variants",
    "project_product_links",
    "project_tasks",
    "project_work_packages",
    "projects",
    "runs",
    "sample_allocations",
    "sample_units",
    "supply_current_snapshots",
    "supply_kit_projections",
    "supply_snapshots",
    "supply_source_captures",
    "task_dependencies",
    "variant_revisions",
    "verification_current_preparations",
    "verification_preparations",
    "work_requests",
    "professional_authority_facts",
    "professional_authority_current",
    "verification_formal_requests",
    "verification_current_formal_requests",
    "verification_method_applicabilities",
    "verification_window_proposals",
    "build_execution_assessments",
    "build_operational_facts",
    "build_authorization_decisions",
    "build_current_execution_assessments",
    "build_operational_current",
    "build_current_authorizations",
    "build_starts",
    "operational_material_holds",
    "operational_resource_occupancies",
    "verification_actual_method_batches",
    "verification_handoff_facts",
    "sample_readiness_facts",
    "verification_actual_method_applicabilities",
    "sample_current_readiness",
    "verification_current_actual_methods",
    "verification_run_identities",
    "test_resource_facts",
    "verification_run_versions",
    "test_resource_current",
    "test_resource_reservations",
    "verification_current_runs",
    "verification_launch_facts",
    "sample_usage_sentinels",
    "sample_run_usages",
    "measurement_import_captures",
    "test_measurements",
    "test_result_projections",
    "test_result_actions",
    "change_request_versions",
    "quality_issue_versions",
    "quality_policy_facts",
    "change_graph_captures",
    "change_request_currents",
    "quality_current_issues",
    "quality_current_policies",
    "quality_failure_maps",
    "quality_event_failure_links",
    "capa_remediation_links",
    "capa_verification_evidence",
    "capa_verification_rule_facts",
    "capa_observation_facts",
    "capa_named_verification_reviews",
    "capa_current_verification_rules",
    "capa_current_observations",
    "change_order_records",
    "change_approval_records",
    "change_implementation_captures",
    "change_implementation_records",
    "controlled_change_policy_facts",
    "controlled_change_policy_currents",
    "controlled_change_selection_facts",
    "controlled_change_selection_currents",
    "manufacturing_preparation_versions",
    "manufacturing_preparation_currents",
    "manufacturing_baseline_document_links",
    "controlled_change_coverage_facts",
    "controlled_change_coverage_currents",
)


def upgrade():
    op.execute(CLOCK)
    for table in EXISTING_TABLES:
        op.execute(f"DROP TRIGGER category_lifecycle_clock_write ON {table}")
        op.execute(f"DROP TRIGGER category_lifecycle_clock_delete ON {table}")
    for table in (*EXISTING_TABLES, *NEW_TABLES):
        op.execute(
            f"CREATE TRIGGER category_lifecycle_clock BEFORE INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION public.category_lifecycle_clock()"
        )
    op.execute(SUMMARY)


def downgrade():
    op.execute(PREVIOUS_SUMMARY)
    for table in (*EXISTING_TABLES, *NEW_TABLES):
        op.execute(f"DROP TRIGGER category_lifecycle_clock ON {table}")
    op.execute(PREVIOUS_CLOCK.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
    for table in EXISTING_TABLES:
        op.execute(
            f"CREATE TRIGGER category_lifecycle_clock_write BEFORE INSERT OR UPDATE ON {table} "
            "FOR EACH ROW WHEN (NEW.product_id IS NULL) EXECUTE FUNCTION public.category_lifecycle_clock()"
        )
        op.execute(
            f"CREATE TRIGGER category_lifecycle_clock_delete BEFORE DELETE ON {table} "
            "FOR EACH ROW WHEN (OLD.product_id IS NULL) EXECUTE FUNCTION public.category_lifecycle_clock()"
        )
