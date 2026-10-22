# ruff: noqa: E501 -- frozen SQL scopes/policies are kept literal
"""B4 fixed audience dependencies, maintained by the fact owner at write time.

No reader traverses fixed history. Dependencies contain identities only; every
reader still checks live scope, object audience and direct sources.
"""

from alembic import op

revision = "s0_0411"
down_revision = "s0_0410"
branch_labels = None
depends_on = None

TABLES = (
    "actual_configurations",
    "build_authorization_decisions",
    "build_execution_assessments",
    "build_lots",
    "build_operational_facts",
    "build_readiness",
    "build_starts",
    "builds",
    "measurement_import_captures",
    "professional_authority_facts",
    "sample_allocations",
    "sample_readiness_facts",
    "sample_run_usages",
    "sample_units",
    "test_measurements",
    "test_resource_facts",
    "test_resource_reservations",
    "test_result_actions",
    "test_result_projections",
    "verification_actual_method_applicabilities",
    "verification_actual_method_batches",
    "verification_formal_requests",
    "verification_handoff_facts",
    "verification_launch_facts",
    "verification_method_applicabilities",
    "verification_preparations",
    "verification_run_identities",
    "verification_run_versions",
    "verification_window_proposals",
)
OLD_POLICIES = {
    "actual_configurations": (
        "(((actual_engineering_configuration_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, "
        "'engineering_configurations'::text, actual_engineering_configuration_id)) AND "
        "((actual_manufacturing_configuration_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, "
        "'process_revisions'::text, actual_manufacturing_configuration_id)) AND ((build_id IS "
        "NULL) OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'builds'::text, build_id)) AND ((planned_manufacturing_configuration_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, "
        "'process_revisions'::text, planned_manufacturing_configuration_id)))"
    ),
    "build_authorization_decisions": (
        "(((assessment_id IS NULL) OR business_upstream_visible(tenant_id, category_id, "
        "product_id, 'build_execution_assessments'::text, assessment_id)) AND ((build_id IS "
        "NULL) OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'builds'::text, build_id)))"
    ),
    "build_execution_assessments": (
        "((build_id IS NULL) OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'builds'::text, build_id))"
    ),
    "build_lots": (
        "(((actual_configuration_id IS NULL) OR business_upstream_visible(tenant_id, "
        "category_id, product_id, 'actual_configurations'::text, actual_configuration_id)) AND "
        "((build_id IS NULL) OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'builds'::text, build_id)))"
    ),
    "build_operational_facts": (
        "((build_id IS NULL) OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'builds'::text, build_id))"
    ),
    "build_readiness": (
        "((build_id IS NULL) OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'builds'::text, build_id))"
    ),
    "build_starts": (
        "(((assessment_id IS NULL) OR business_upstream_visible(tenant_id, category_id, "
        "product_id, 'build_execution_assessments'::text, assessment_id)) AND ((build_id IS "
        "NULL) OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'builds'::text, build_id)) AND ((engineering_authorization_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, "
        "'build_authorization_decisions'::text, engineering_authorization_id)) AND "
        "((manufacturing_authorization_id IS NULL) OR business_upstream_visible(tenant_id, "
        "category_id, product_id, 'build_authorization_decisions'::text, "
        "manufacturing_authorization_id)))"
    ),
    "builds": (
        "(((engineering_configuration_id IS NULL) OR business_upstream_visible(tenant_id, "
        "category_id, product_id, 'engineering_configurations'::text, "
        "engineering_configuration_id)) AND ((manufacturing_configuration_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, "
        "'process_revisions'::text, manufacturing_configuration_id)) AND ((project_id IS NULL) "
        "OR business_upstream_visible(tenant_id, category_id, product_id, 'projects'::text, "
        "project_id)))"
    ),
    "measurement_import_captures": (
        "(((request_version_id IS NULL) OR business_upstream_visible(tenant_id, category_id, "
        "product_id, 'verification_formal_requests'::text, request_version_id)) AND ((run_id "
        "IS NULL) OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'verification_run_identities'::text, run_id)) AND ((run_version_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, "
        "'verification_run_versions'::text, run_version_id)))"
    ),
    "professional_authority_facts": (
        "((project_id IS NULL) OR business_upstream_visible(tenant_id, category_id, "
        "product_id, 'projects'::text, project_id))"
    ),
    "sample_allocations": (
        "(((build_id IS NULL) OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'builds'::text, build_id)) AND ((lot_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, 'build_lots'::text, "
        "lot_id)))"
    ),
    "sample_readiness_facts": (
        "(((lot_id IS NULL) OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'build_lots'::text, lot_id)) AND ((sample_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, 'sample_units'::text, "
        "sample_id)))"
    ),
    "sample_run_usages": (
        "(((run_id IS NULL) OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'verification_run_identities'::text, run_id)) AND ((sample_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, 'sample_units'::text, "
        "sample_id)))"
    ),
    "sample_units": (
        "(((allocation_id IS NULL) OR business_upstream_visible(tenant_id, category_id, "
        "product_id, 'sample_allocations'::text, allocation_id)) AND ((build_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, 'builds'::text, "
        "build_id)) AND ((lot_id IS NULL) OR business_upstream_visible(tenant_id, category_id, "
        "product_id, 'build_lots'::text, lot_id)))"
    ),
    "test_measurements": (
        "(((actual_configuration_id IS NULL) OR business_upstream_visible(tenant_id, "
        "category_id, product_id, 'actual_configurations'::text, actual_configuration_id)) AND "
        "((capture_id IS NULL) OR business_upstream_visible(tenant_id, category_id, "
        "product_id, 'measurement_import_captures'::text, capture_id)) AND ((run_id IS NULL) "
        "OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'verification_run_identities'::text, run_id)) AND ((run_version_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, "
        "'verification_run_versions'::text, run_version_id)) AND ((sample_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, 'sample_units'::text, "
        "sample_id)))"
    ),
    "test_resource_facts": (
        "(((accepted_request_id IS NULL) OR business_upstream_visible(tenant_id, category_id, "
        "product_id, 'verification_formal_requests'::text, accepted_request_id)) AND "
        "((build_id IS NULL) OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'builds'::text, build_id)))"
    ),
    "test_resource_reservations": (
        "(((fact_id IS NULL) OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'test_resource_facts'::text, fact_id)) AND ((run_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, "
        "'verification_run_identities'::text, run_id)))"
    ),
    "test_result_actions": (
        "(((capture_id IS NULL) OR business_upstream_visible(tenant_id, category_id, "
        "product_id, 'measurement_import_captures'::text, capture_id)) AND "
        "((next_request_version_id IS NULL) OR business_upstream_visible(tenant_id, "
        "category_id, product_id, 'verification_formal_requests'::text, "
        "next_request_version_id)) AND ((next_run_version_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, "
        "'verification_run_versions'::text, next_run_version_id)) AND ((projection_id IS NULL) "
        "OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'test_result_projections'::text, projection_id)) AND ((request_version_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, "
        "'verification_formal_requests'::text, request_version_id)) AND ((run_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, "
        "'verification_run_identities'::text, run_id)) AND ((run_version_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, "
        "'verification_run_versions'::text, run_version_id)))"
    ),
    "test_result_projections": (
        "(((run_id IS NULL) OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'verification_run_identities'::text, run_id)) AND ((run_version_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, "
        "'verification_run_versions'::text, run_version_id)))"
    ),
    "verification_actual_method_applicabilities": (
        "(((actual_configuration_id IS NULL) OR business_upstream_visible(tenant_id, "
        "category_id, product_id, 'actual_configurations'::text, actual_configuration_id)) AND "
        "((batch_id IS NULL) OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'verification_actual_method_batches'::text, batch_id)) AND ((request_version_id IS "
        "NULL) OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'verification_formal_requests'::text, request_version_id)) AND ((sample_id IS NULL) "
        "OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'sample_units'::text, sample_id)))"
    ),
    "verification_actual_method_batches": (
        "((request_version_id IS NULL) OR business_upstream_visible(tenant_id, category_id, "
        "product_id, 'verification_formal_requests'::text, request_version_id))"
    ),
    "verification_formal_requests": (
        "(((build_id IS NULL) OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'builds'::text, build_id)) AND ((preparation_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, "
        "'verification_preparations'::text, preparation_id)))"
    ),
    "verification_handoff_facts": (
        "(((next_request_version_id IS NULL) OR business_upstream_visible(tenant_id, "
        "category_id, product_id, 'verification_formal_requests'::text, "
        "next_request_version_id)) AND ((request_version_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, "
        "'verification_formal_requests'::text, request_version_id)))"
    ),
    "verification_launch_facts": (
        "(((next_request_version_id IS NULL) OR business_upstream_visible(tenant_id, "
        "category_id, product_id, 'verification_formal_requests'::text, "
        "next_request_version_id)) AND ((request_version_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, "
        "'verification_formal_requests'::text, request_version_id)) AND ((run_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, "
        "'verification_run_identities'::text, run_id)) AND ((run_version_id IS NULL) OR "
        "business_upstream_visible(tenant_id, category_id, product_id, "
        "'verification_run_versions'::text, run_version_id)))"
    ),
    "verification_method_applicabilities": (
        "((request_version_id IS NULL) OR business_upstream_visible(tenant_id, category_id, "
        "product_id, 'verification_formal_requests'::text, request_version_id))"
    ),
    "verification_preparations": (
        "((build_id IS NULL) OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'builds'::text, build_id))"
    ),
    "verification_run_identities": (
        "((build_id IS NULL) OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'builds'::text, build_id))"
    ),
    "verification_run_versions": (
        "(((request_version_id IS NULL) OR business_upstream_visible(tenant_id, category_id, "
        "product_id, 'verification_formal_requests'::text, request_version_id)) AND ((run_id "
        "IS NULL) OR business_upstream_visible(tenant_id, category_id, product_id, "
        "'verification_run_identities'::text, run_id)))"
    ),
    "verification_window_proposals": (
        "((request_version_id IS NULL) OR business_upstream_visible(tenant_id, category_id, "
        "product_id, 'verification_formal_requests'::text, request_version_id))"
    ),
}
FUNCTIONS = """
CREATE FUNCTION business_audience_collect(t uuid,c uuid,p uuid,typ text,body jsonb,path text[])
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE spec jsonb; parent_body jsonb; parent_type text; sid uuid; dep jsonb;
 all_deps jsonb='[]'::jsonb; actual_product uuid; marker text;
BEGIN
 IF NOT typ=ANY(ARRAY['actual_configurations','bom_revisions','build_authorization_decisions','build_execution_assessments','build_lots','build_operational_facts','build_readiness','build_starts','builds','definition_revisions','engineering_configurations','measurement_import_captures','process_revisions','professional_authority_facts','projects','sample_allocations','sample_readiness_facts','sample_run_usages','sample_units','test_measurements','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','verification_actual_method_applicabilities','verification_actual_method_batches','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals']) THEN RAISE EXCEPTION 'Unregistered audience type'; END IF;
 FOR spec IN SELECT value FROM jsonb_array_elements(COALESCE('{"definition_revisions":[["parent_definition_id","definition_revisions"]],"engineering_configurations":[["definition_id","definition_revisions"],["bom_id","bom_revisions"]],"process_revisions":[["engineering_configuration_id","engineering_configurations"]],"actual_configurations":[["actual_engineering_configuration_id","engineering_configurations"],["actual_manufacturing_configuration_id","process_revisions"],["build_id","builds"],["planned_manufacturing_configuration_id","process_revisions"]],"build_authorization_decisions":[["assessment_id","build_execution_assessments"],["build_id","builds"]],"build_execution_assessments":[["build_id","builds"]],"build_lots":[["actual_configuration_id","actual_configurations"],["build_id","builds"]],"build_operational_facts":[["build_id","builds"]],"build_readiness":[["build_id","builds"]],"build_starts":[["assessment_id","build_execution_assessments"],["build_id","builds"],["engineering_authorization_id","build_authorization_decisions"],["manufacturing_authorization_id","build_authorization_decisions"]],"builds":[["engineering_configuration_id","engineering_configurations"],["manufacturing_configuration_id","process_revisions"],["project_id","projects"]],"measurement_import_captures":[["request_version_id","verification_formal_requests"],["run_id","verification_run_identities"],["run_version_id","verification_run_versions"]],"professional_authority_facts":[["project_id","projects"]],"sample_allocations":[["build_id","builds"],["lot_id","build_lots"]],"sample_readiness_facts":[["lot_id","build_lots"],["sample_id","sample_units"]],"sample_run_usages":[["run_id","verification_run_identities"],["sample_id","sample_units"]],"sample_units":[["allocation_id","sample_allocations"],["build_id","builds"],["lot_id","build_lots"]],"test_measurements":[["actual_configuration_id","actual_configurations"],["capture_id","measurement_import_captures"],["run_id","verification_run_identities"],["run_version_id","verification_run_versions"],["sample_id","sample_units"]],"test_resource_facts":[["accepted_request_id","verification_formal_requests"],["build_id","builds"]],"test_resource_reservations":[["fact_id","test_resource_facts"],["run_id","verification_run_identities"]],"test_result_actions":[["capture_id","measurement_import_captures"],["next_request_version_id","verification_formal_requests"],["next_run_version_id","verification_run_versions"],["projection_id","test_result_projections"],["request_version_id","verification_formal_requests"],["run_id","verification_run_identities"],["run_version_id","verification_run_versions"]],"test_result_projections":[["run_id","verification_run_identities"],["run_version_id","verification_run_versions"]],"verification_actual_method_applicabilities":[["actual_configuration_id","actual_configurations"],["batch_id","verification_actual_method_batches"],["request_version_id","verification_formal_requests"],["sample_id","sample_units"]],"verification_actual_method_batches":[["request_version_id","verification_formal_requests"]],"verification_formal_requests":[["build_id","builds"],["preparation_id","verification_preparations"]],"verification_handoff_facts":[["next_request_version_id","verification_formal_requests"],["request_version_id","verification_formal_requests"]],"verification_launch_facts":[["next_request_version_id","verification_formal_requests"],["request_version_id","verification_formal_requests"],["run_id","verification_run_identities"],["run_version_id","verification_run_versions"]],"verification_method_applicabilities":[["request_version_id","verification_formal_requests"]],"verification_preparations":[["build_id","builds"]],"verification_run_identities":[["build_id","builds"]],"verification_run_versions":[["request_version_id","verification_formal_requests"],["run_id","verification_run_identities"]],"verification_window_proposals":[["request_version_id","verification_formal_requests"]]}'::jsonb->typ,'[]'::jsonb)) LOOP
  sid=(body->>(spec->>0))::uuid; parent_type=spec->>1;
  IF sid IS NULL THEN CONTINUE; END IF;
  marker=parent_type||':'||sid::text;
  IF marker=ANY(path) THEN RAISE EXCEPTION 'Cyclic fixed audience dependency'; END IF;
  EXECUTE format('SELECT to_jsonb(r) FROM public.%I r WHERE tenant_id=$1 AND category_id=$2 AND id=$3',parent_type)
   INTO parent_body USING t,c,sid;
  IF parent_body IS NULL THEN RAISE EXCEPTION 'Missing fixed audience parent'; END IF;
  actual_product=(parent_body->>'product_id')::uuid;
  IF actual_product IS DISTINCT FROM p AND NOT
    (actual_product IS NULL AND parent_type=ANY(ARRAY['artifact_versions','uploaded_originals']))
  THEN RAISE EXCEPTION 'Fixed audience parent scope mismatch'; END IF;
  dep=jsonb_build_object('type',parent_type,'id',sid,'product_id',actual_product);
  all_deps=all_deps||jsonb_build_array(dep);
  IF jsonb_typeof(parent_body->'audience_dependencies')='array' THEN
   all_deps=all_deps||(parent_body->'audience_dependencies');
  ELSE
   all_deps=all_deps||business_audience_collect(t,c,actual_product,parent_type,parent_body,path||marker);
  END IF;
 END LOOP;
 SELECT COALESCE(jsonb_agg(value ORDER BY value::text),'[]'::jsonb) INTO all_deps
  FROM (SELECT DISTINCT value FROM jsonb_array_elements(all_deps)) refs;
 RETURN all_deps;
END $$;
REVOKE ALL ON FUNCTION business_audience_collect(uuid,uuid,uuid,text,jsonb,text[]) FROM PUBLIC,pdos_agent,pdos_next_app;
CREATE FUNCTION maintain_business_audience_summary() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
BEGIN
 IF TG_OP='UPDATE' THEN NEW.audience_dependencies=OLD.audience_dependencies; RETURN NEW; END IF;
 NEW.audience_dependencies=business_audience_collect(NEW.tenant_id,NEW.category_id,NEW.product_id,
  TG_TABLE_NAME,to_jsonb(NEW),ARRAY[TG_TABLE_NAME||':'||NEW.id::text]);
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION maintain_business_audience_summary() FROM PUBLIC,pdos_agent,pdos_next_app;
CREATE FUNCTION business_audience_summary_visible(t uuid,c uuid,p uuid,deps jsonb) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE ref jsonb; body jsonb; typ text; sid uuid; expected_product uuid;
BEGIN
 IF NOT category_access(t,c,false) OR jsonb_typeof(deps) IS DISTINCT FROM 'array'
 THEN RETURN false; END IF;
 IF p IS NOT NULL AND NOT EXISTS(SELECT 1 FROM products r WHERE r.tenant_id=t AND r.category_id=c
  AND r.id=p AND source_object_audience(t,c,'products',r.id,r.owner_id,r.visibility))
 THEN RETURN false; END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(deps) LOOP
  IF jsonb_typeof(ref) IS DISTINCT FROM 'object' OR
    (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(ref) key)
      IS DISTINCT FROM ARRAY['id','product_id','type'] THEN RETURN false; END IF;
  typ=ref->>'type';sid=(ref->>'id')::uuid;expected_product=(ref->>'product_id')::uuid;
  IF NOT typ=ANY(ARRAY['actual_configurations','bom_revisions','build_authorization_decisions','build_execution_assessments','build_lots','build_operational_facts','build_readiness','build_starts','builds','definition_revisions','engineering_configurations','measurement_import_captures','process_revisions','professional_authority_facts','projects','sample_allocations','sample_readiness_facts','sample_run_usages','sample_units','test_measurements','test_resource_facts','test_resource_reservations','test_result_actions','test_result_projections','verification_actual_method_applicabilities','verification_actual_method_batches','verification_formal_requests','verification_handoff_facts','verification_launch_facts','verification_method_applicabilities','verification_preparations','verification_run_identities','verification_run_versions','verification_window_proposals']) OR sid IS NULL THEN RETURN false; END IF;
  EXECUTE format('SELECT to_jsonb(r) FROM public.%I r WHERE tenant_id=$1 AND category_id=$2 AND id=$3',typ)
   INTO body USING t,c,sid;
  IF body IS NULL OR (body->>'product_id')::uuid IS DISTINCT FROM expected_product OR
   (expected_product IS DISTINCT FROM p AND NOT(expected_product IS NULL AND
    typ=ANY(ARRAY['artifact_versions','uploaded_originals']))) THEN RETURN false; END IF;
  IF NOT source_object_audience(t,c,typ,sid,(body->>'owner_id')::uuid,body->>'visibility')
  THEN RETURN false; END IF;
  IF body ? 'required_source_read_set' AND NOT direct_source_set_visible(t,c,expected_product,body->'required_source_read_set')
  THEN RETURN false; END IF;
  -- These B3 owners keep live links/sources outside required_source_read_set.
  IF typ='projects' AND NOT project_definition_visible(t,c,expected_product,sid)
  THEN RETURN false; END IF;
  IF typ='definition_revisions' AND NOT definition_sources_visible(t,c,expected_product,sid)
  THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION business_audience_summary_visible(uuid,uuid,uuid,jsonb) FROM PUBLIC,pdos_agent;
GRANT EXECUTE ON FUNCTION business_audience_summary_visible(uuid,uuid,uuid,jsonb) TO pdos_next_app;
"""


def upgrade():
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN audience_dependencies jsonb")
    op.execute(FUNCTIONS)
    for table in TABLES:
        # Do not change historical facts, revisions, clocks or outbox on backfill.
        op.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
        op.execute(
            f"UPDATE {table} r SET audience_dependencies=business_audience_collect("
            "tenant_id,category_id,product_id,"
            f"'{table}',to_jsonb(r),ARRAY['{table}:'||r.id::text])"
        )
        op.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN audience_dependencies SET NOT NULL")
        op.execute(
            f"CREATE TRIGGER zz_business_audience_summary BEFORE INSERT OR UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION maintain_business_audience_summary()"
        )
        op.execute(f"DROP POLICY upstream_audience ON {table}")
        op.execute(
            f"CREATE POLICY upstream_audience ON {table} AS RESTRICTIVE FOR SELECT TO pdos_next_app "
            "USING (business_audience_summary_visible(tenant_id,category_id,product_id,audience_dependencies))"
        )


def downgrade():
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY upstream_audience ON {table}")
        op.execute(
            f"CREATE POLICY upstream_audience ON {table} AS RESTRICTIVE FOR SELECT TO pdos_next_app "
            f"USING ({OLD_POLICIES[table]})"
        )
        op.execute(f"DROP TRIGGER zz_business_audience_summary ON {table}")
        op.execute(f"ALTER TABLE {table} DROP COLUMN audience_dependencies")
    op.execute("DROP FUNCTION business_audience_summary_visible(uuid,uuid,uuid,jsonb)")
    op.execute("DROP FUNCTION maintain_business_audience_summary()")
    op.execute("DROP FUNCTION business_audience_collect(uuid,uuid,uuid,text,jsonb,text[])")
