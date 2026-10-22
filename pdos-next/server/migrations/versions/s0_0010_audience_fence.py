"""Serialize audience changes with commands using the affected model and source.

Target identity and owner must be real; grants cannot be moved between objects.
The model lock matches command lock order, preventing revocation during a new write.
"""

import json

from alembic import op

revision = "s0_0010"
down_revision = "s0_0009"
branch_labels = None
depends_on = None

OWNERS = {
    "action_receipts": "requester_id",
    "actual_configurations": "owner_id",
    "artifact_versions": "owner_id",
    "bom_revisions": "owner_id",
    "build_authorization_decisions": "owner_id",
    "build_execution_assessments": "owner_id",
    "build_lots": "owner_id",
    "build_operational_facts": "owner_id",
    "build_readiness": "owner_id",
    "build_starts": "owner_id",
    "builds": "owner_id",
    "capa_current_observations": "owner_id",
    "capa_current_verification_rules": "owner_id",
    "capa_named_verification_reviews": "owner_id",
    "capa_observation_facts": "owner_id",
    "capa_remediation_links": "owner_id",
    "capa_verification_evidence": "owner_id",
    "capa_verification_rule_facts": "owner_id",
    "change_approval_records": "owner_id",
    "change_graph_captures": "owner_id",
    "change_implementation_captures": "owner_id",
    "change_implementation_records": "owner_id",
    "change_order_records": "owner_id",
    "change_request_versions": "owner_id",
    "controlled_change_coverage_currents": "owner_id",
    "controlled_change_coverage_facts": "owner_id",
    "controlled_change_policy_currents": "owner_id",
    "controlled_change_policy_facts": "owner_id",
    "controlled_change_selection_currents": "owner_id",
    "controlled_change_selection_facts": "owner_id",
    "cost_estimates": "owner_id",
    "cost_input_snapshots": "owner_id",
    "cost_source_captures": "owner_id",
    "definition_revisions": "owner_id",
    "engineering_configurations": "owner_id",
    "manufacturing_preparation_currents": "owner_id",
    "manufacturing_preparation_versions": "owner_id",
    "measurement_import_captures": "owner_id",
    "parts": "owner_id",
    "plan_proposals": "owner_id",
    "plan_revisions": "owner_id",
    "process_revisions": "owner_id",
    "product_variants": "owner_id",
    "products": "owner_id",
    "professional_authority_facts": "owner_id",
    "projects": "owner_id",
    "quality_issue_versions": "owner_id",
    "quality_policy_facts": "owner_id",
    "sample_allocations": "owner_id",
    "sample_readiness_facts": "owner_id",
    "sample_run_usages": "owner_id",
    "sample_units": "owner_id",
    "supply_kit_projections": "owner_id",
    "supply_snapshots": "owner_id",
    "supply_source_captures": "owner_id",
    "test_measurements": "owner_id",
    "test_resource_facts": "owner_id",
    "test_resource_reservations": "owner_id",
    "test_result_actions": "owner_id",
    "test_result_projections": "owner_id",
    "uploaded_originals": "owner_id",
    "variant_revisions": "owner_id",
    "verification_actual_method_applicabilities": "owner_id",
    "verification_actual_method_batches": "owner_id",
    "verification_formal_requests": "owner_id",
    "verification_handoff_facts": "owner_id",
    "verification_launch_facts": "owner_id",
    "verification_method_applicabilities": "owner_id",
    "verification_preparations": "owner_id",
    "verification_run_identities": "owner_id",
    "verification_run_versions": "owner_id",
    "verification_window_proposals": "owner_id",
}

SQL = """
CREATE FUNCTION protect_object_audience_target() RETURNS trigger
LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE value jsonb; typ text; own_col text; model_col text;
 t uuid; c uuid; sid uuid; expected_owner uuid; actual_owner uuid; model uuid;
 owners jsonb='__OWNERS__'::jsonb;
BEGIN
 IF TG_OP='DELETE' THEN value=to_jsonb(OLD); ELSE value=to_jsonb(NEW); END IF;
 IF TG_OP='UPDATE' AND
   ROW(NEW.tenant_id,NEW.category_id,NEW.object_type,NEW.subject_id,NEW.owner_id)
   IS DISTINCT FROM ROW(OLD.tenant_id,OLD.category_id,OLD.object_type,OLD.subject_id,OLD.owner_id)
 THEN RAISE EXCEPTION 'audience identity cannot be reassigned' USING ERRCODE='23514'; END IF;
 typ=value->>'object_type'; own_col=owners->>typ;
 t=(value->>'tenant_id')::uuid; c=(value->>'category_id')::uuid;
 sid=(value->>'subject_id')::uuid; expected_owner=(value->>'owner_id')::uuid;
 IF own_col IS NULL THEN
  RAISE EXCEPTION 'audience target unavailable' USING ERRCODE='23514';
 END IF;
 model_col=CASE WHEN typ='products' THEN 'id' ELSE 'product_id' END;
 EXECUTE format('SELECT %I,%I FROM public.%I WHERE tenant_id=$1 AND category_id=$2 AND id=$3',
                own_col,model_col,typ) INTO actual_owner,model USING t,c,sid;
 IF actual_owner IS DISTINCT FROM expected_owner THEN
  RAISE EXCEPTION 'audience target unavailable' USING ERRCODE='23514';
 END IF;
 IF model IS NOT NULL THEN
  PERFORM 1 FROM products WHERE tenant_id=t AND category_id=c AND id=model FOR UPDATE;
  IF NOT FOUND THEN
   RAISE EXCEPTION 'audience model unavailable' USING ERRCODE='23514';
  END IF;
 END IF;
 EXECUTE format('SELECT %I FROM public.%I
  WHERE tenant_id=$1 AND category_id=$2 AND id=$3 FOR UPDATE',
                own_col,typ) INTO actual_owner USING t,c,sid;
 IF actual_owner IS DISTINCT FROM expected_owner THEN
  RAISE EXCEPTION 'audience target unavailable' USING ERRCODE='23514';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;
CREATE TRIGGER audience_reference_fence BEFORE INSERT OR UPDATE OR DELETE ON object_audiences
FOR EACH ROW EXECUTE FUNCTION protect_object_audience_target();
REVOKE ALL ON FUNCTION protect_object_audience_target() FROM PUBLIC,pdos_agent;
"""


def upgrade():
    op.execute(SQL.replace("__OWNERS__", json.dumps(OWNERS)))


def downgrade():
    op.execute("DROP TRIGGER audience_reference_fence ON object_audiences")
    op.execute("DROP FUNCTION protect_object_audience_target()")
