"""Owner-only reference summary sees private consumers without exposing their bodies.

The reviewed table whitelist is frozen. Application RLS remains authoritative for
business reads; this function emits only a count, history flag and model watermark.
"""

from alembic import op

revision = "s0_0009"
down_revision = "s0_0008"
branch_labels = None
depends_on = None

CONSUMING = (
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
)
IDENTITY_KEYS = (
    "accountable_owner_id",
    "actor_id",
    "category_id",
    "human_owner_id",
    "id",
    "named_decider_id",
    "owner_id",
    "principal_id",
    "product_id",
    "requester_id",
    "tenant_id",
    "writer_id",
)

SQL = """
CREATE FUNCTION lifecycle_payload_links(value jsonb) RETURNS uuid[]
LANGUAGE plpgsql IMMUTABLE SET search_path=public,pg_temp AS $$
DECLARE answer uuid[]='{}'; child record; item jsonb; parsed uuid; identity_keys
 text[]=ARRAY[__IDENTITY_KEYS__];
BEGIN
 IF jsonb_typeof(value)='object' THEN
  FOR child IN SELECT key,v FROM jsonb_each(value) AS x(key,v) LOOP
   IF NOT child.key=ANY(identity_keys) THEN
    answer=answer || lifecycle_payload_links(child.v);
   END IF;
  END LOOP;
 ELSIF jsonb_typeof(value)='array' THEN
  FOR item IN SELECT v FROM jsonb_array_elements(value) AS x(v) LOOP
   answer=answer || lifecycle_payload_links(item);
  END LOOP;
 ELSIF jsonb_typeof(value)='string' THEN
  BEGIN
   parsed=(value #>> '{}')::uuid;
   answer=array_append(answer,parsed);
  EXCEPTION WHEN invalid_text_representation THEN NULL;
  END;
 END IF;
 RETURN answer;
END $$;
CREATE FUNCTION lifecycle_reference_summary(t uuid,c uuid,p uuid,roots uuid[])
RETURNS TABLE(object_id uuid,reference_count integer,formal_history boolean,read_version bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE tables text[]=ARRAY[__CONSUMING__]; table_name text; payload jsonb;
 graph jsonb[]='{}'; controls uuid[]; reached uuid[]='{}'; selected integer[]='{}';
 node jsonb; links uuid[]; row_id uuid; oid uuid; i integer; changed boolean;
BEGIN
 IF NOT category_access(t,c,false) OR NOT EXISTS(
  SELECT 1 FROM products WHERE id=p AND tenant_id=t AND category_id=c
 ) THEN RETURN; END IF;
 SELECT COALESCE(array_agg(id),'{}') INTO controls FROM action_receipts
  WHERE tenant_id=t AND category_id=c AND product_id=p AND operation LIKE 'evidence.lifecycle.%';
 FOREACH table_name IN ARRAY tables LOOP
  FOR payload IN EXECUTE CASE WHEN
 table_name=ANY(ARRAY['audit_entries','outbox_events','request_keys'])
   THEN format('SELECT to_jsonb(x) FROM public.%I x JOIN action_receipts r ON
 r.id=x.receipt_id AND r.tenant_id=x.tenant_id WHERE x.tenant_id=$1 AND r.product_id=$2',table_name)
   ELSE format('SELECT to_jsonb(x) FROM public.%I x WHERE tenant_id=$1 AND
 product_id=$2',table_name)
   END USING t,p LOOP
   IF (payload->>'receipt_id')::uuid=ANY(controls) OR
     (table_name='action_receipts' AND payload->>'operation' LIKE 'evidence.lifecycle.%') THEN
 CONTINUE; END IF;
   graph=array_append(graph,jsonb_build_object('table',table_name,'id',payload->>'id',
     'links',to_jsonb(lifecycle_payload_links(payload))));
  END LOOP;
 END LOOP;
 SELECT lifecycle_epoch INTO read_version FROM products WHERE id=p AND tenant_id=t AND
 category_id=c;
 FOREACH oid IN ARRAY roots LOOP
  IF NOT (
   EXISTS(SELECT 1 FROM upload_attempts WHERE id=oid AND tenant_id=t AND category_id=c AND
 product_id=p AND owner_id=scope_requester()) OR
   EXISTS(SELECT 1 FROM uploaded_originals WHERE id=oid AND tenant_id=t AND category_id=c AND
 product_id=p AND owner_id=scope_requester()) OR
   EXISTS(SELECT 1 FROM lifecycle_objects WHERE id=oid AND tenant_id=t AND category_id=c AND
 product_id=p AND owner_id=scope_requester())
  ) THEN CONTINUE; END IF;
  object_id=oid; reached=ARRAY[oid]; selected='{}'; changed=true;
 WHILE changed LOOP
  changed=false;
  IF cardinality(graph)>0 THEN
   FOR i IN 1..cardinality(graph) LOOP
    IF i=ANY(selected) THEN CONTINUE; END IF;
    node=graph[i]; row_id=(node->>'id')::uuid;
    SELECT COALESCE(array_agg(v::uuid),'{}') INTO links FROM
 jsonb_array_elements_text(node->'links') AS x(v);
    IF row_id=oid OR links && reached THEN
     selected=array_append(selected,i);
     IF row_id IS NOT NULL AND NOT row_id=ANY(reached) THEN
 reached=array_append(reached,row_id); END IF;
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
END $$;
REVOKE ALL ON FUNCTION lifecycle_payload_links(jsonb) FROM PUBLIC,pdos_agent;
REVOKE ALL ON FUNCTION lifecycle_reference_summary(uuid,uuid,uuid,uuid[]) FROM PUBLIC,pdos_agent;
GRANT EXECUTE ON FUNCTION lifecycle_reference_summary(uuid,uuid,uuid,uuid[]) TO pdos_next_app;
"""


def upgrade():
    def literals(items):
        return ",".join("'" + value.replace("'", "''") + "'" for value in items)

    op.execute(
        SQL.replace("__IDENTITY_KEYS__", literals(IDENTITY_KEYS)).replace(
            "__CONSUMING__", literals(CONSUMING)
        )
    )


def downgrade():
    op.execute("DROP FUNCTION lifecycle_reference_summary(uuid,uuid,uuid,uuid[])")
    op.execute("DROP FUNCTION lifecycle_payload_links(jsonb)")
