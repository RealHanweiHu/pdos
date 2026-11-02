"""B4 direct source/upstream audience and version-pinned measurement captures."""

from alembic import op

revision = "s0_0401"
down_revision = "s0_0400"
branch_labels = None
depends_on = None

READ_SETS = (
    "actual_configurations",
    "build_authorization_decisions",
    "build_execution_assessments",
    "build_lots",
    "build_operational_facts",
    "build_starts",
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
    "verification_run_versions",
    "verification_window_proposals",
)
EDGES = {
    "actual_configurations": (
        ("actual_engineering_configuration_id", "engineering_configurations"),
        ("actual_manufacturing_configuration_id", "process_revisions"),
        ("build_id", "builds"),
        ("planned_manufacturing_configuration_id", "process_revisions"),
    ),
    "build_authorization_decisions": (
        ("assessment_id", "build_execution_assessments"),
        ("build_id", "builds"),
    ),
    "build_execution_assessments": (("build_id", "builds"),),
    "build_lots": (("actual_configuration_id", "actual_configurations"), ("build_id", "builds")),
    "build_operational_facts": (("build_id", "builds"),),
    "build_readiness": (("build_id", "builds"),),
    "build_starts": (
        ("assessment_id", "build_execution_assessments"),
        ("build_id", "builds"),
        ("engineering_authorization_id", "build_authorization_decisions"),
        ("manufacturing_authorization_id", "build_authorization_decisions"),
    ),
    "builds": (
        ("engineering_configuration_id", "engineering_configurations"),
        ("manufacturing_configuration_id", "process_revisions"),
        ("project_id", "projects"),
    ),
    "measurement_import_captures": (
        ("request_version_id", "verification_formal_requests"),
        ("run_id", "verification_run_identities"),
        ("run_version_id", "verification_run_versions"),
    ),
    "professional_authority_facts": (("project_id", "projects"),),
    "sample_allocations": (("build_id", "builds"), ("lot_id", "build_lots")),
    "sample_readiness_facts": (("lot_id", "build_lots"), ("sample_id", "sample_units")),
    "sample_run_usages": (("run_id", "verification_run_identities"), ("sample_id", "sample_units")),
    "sample_units": (
        ("allocation_id", "sample_allocations"),
        ("build_id", "builds"),
        ("lot_id", "build_lots"),
    ),
    "test_measurements": (
        ("actual_configuration_id", "actual_configurations"),
        ("capture_id", "measurement_import_captures"),
        ("run_id", "verification_run_identities"),
        ("run_version_id", "verification_run_versions"),
        ("sample_id", "sample_units"),
    ),
    "test_resource_facts": (
        ("accepted_request_id", "verification_formal_requests"),
        ("build_id", "builds"),
    ),
    "test_resource_reservations": (
        ("fact_id", "test_resource_facts"),
        ("run_id", "verification_run_identities"),
    ),
    "test_result_actions": (
        ("capture_id", "measurement_import_captures"),
        ("next_request_version_id", "verification_formal_requests"),
        ("next_run_version_id", "verification_run_versions"),
        ("projection_id", "test_result_projections"),
        ("request_version_id", "verification_formal_requests"),
        ("run_id", "verification_run_identities"),
        ("run_version_id", "verification_run_versions"),
    ),
    "test_result_projections": (
        ("run_id", "verification_run_identities"),
        ("run_version_id", "verification_run_versions"),
    ),
    "verification_actual_method_applicabilities": (
        ("actual_configuration_id", "actual_configurations"),
        ("batch_id", "verification_actual_method_batches"),
        ("request_version_id", "verification_formal_requests"),
        ("sample_id", "sample_units"),
    ),
    "verification_actual_method_batches": (("request_version_id", "verification_formal_requests"),),
    "verification_formal_requests": (
        ("build_id", "builds"),
        ("preparation_id", "verification_preparations"),
    ),
    "verification_handoff_facts": (
        ("next_request_version_id", "verification_formal_requests"),
        ("request_version_id", "verification_formal_requests"),
    ),
    "verification_launch_facts": (
        ("next_request_version_id", "verification_formal_requests"),
        ("request_version_id", "verification_formal_requests"),
        ("run_id", "verification_run_identities"),
        ("run_version_id", "verification_run_versions"),
    ),
    "verification_method_applicabilities": (
        ("request_version_id", "verification_formal_requests"),
    ),
    "verification_preparations": (("build_id", "builds"),),
    "verification_run_identities": (("build_id", "builds"),),
    "verification_run_versions": (
        ("request_version_id", "verification_formal_requests"),
        ("run_id", "verification_run_identities"),
    ),
    "verification_window_proposals": (("request_version_id", "verification_formal_requests"),),
}


def upgrade():
    # PostgreSQL removes only checks depending on this retired deadline column.
    op.execute("ALTER TABLE measurement_import_captures DROP COLUMN expires_at")
    allowed = sorted(
        {parent for parents in EDGES.values() for _, parent in parents}
        | {"professional_authority_facts"}
    )
    literals = ",".join("'" + name + "'" for name in allowed)
    op.execute(f"""
CREATE FUNCTION business_upstream_visible(t uuid,c uuid,p uuid,typ text,sid uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=public,pg_temp AS $$
DECLARE visible boolean;
BEGIN
 IF NOT typ=ANY(ARRAY[{literals}]) THEN RETURN false; END IF;
 EXECUTE format('SELECT EXISTS(SELECT 1 FROM public.%I
  WHERE tenant_id=$1 AND category_id=$2 AND product_id=$3 AND id=$4)',typ)
 INTO visible USING t,c,p,sid;
 RETURN visible;
END $$;
REVOKE ALL ON FUNCTION business_upstream_visible(uuid,uuid,uuid,text,uuid) FROM PUBLIC,pdos_agent;
GRANT EXECUTE ON FUNCTION business_upstream_visible(uuid,uuid,uuid,text,uuid) TO pdos_next_app;
""")
    for table in READ_SETS:
        op.execute(
            f"CREATE POLICY direct_source_audience ON {table} AS RESTRICTIVE "
            "FOR SELECT TO pdos_next_app USING "
            "(direct_source_set_visible(tenant_id,category_id,product_id,required_source_read_set))"
        )
    for table, parents in EDGES.items():
        clauses = [
            f"({column} IS NULL OR business_upstream_visible(tenant_id,category_id,"
            f"product_id,'{parent}',{column}))"
            for column, parent in parents
        ]
        op.execute(
            f"CREATE POLICY upstream_audience ON {table} AS RESTRICTIVE "
            f"FOR SELECT TO pdos_next_app USING ({' AND '.join(clauses)})"
        )
    op.execute(
        "CREATE POLICY upstream_audience ON professional_authority_current AS RESTRICTIVE "
        "FOR SELECT TO pdos_next_app USING (business_upstream_visible("
        "tenant_id,category_id,product_id,'professional_authority_facts',fact_id))"
    )


def downgrade():
    op.execute("DROP POLICY upstream_audience ON professional_authority_current")
    for table in EDGES:
        op.execute(f"DROP POLICY upstream_audience ON {table}")
    for table in READ_SETS:
        op.execute(f"DROP POLICY direct_source_audience ON {table}")
    op.execute("DROP FUNCTION business_upstream_visible(uuid,uuid,uuid,text,uuid)")
    op.execute(
        "ALTER TABLE measurement_import_captures ADD COLUMN expires_at timestamptz "
        "NOT NULL DEFAULT 'infinity'::timestamptz"
    )
    op.execute("ALTER TABLE measurement_import_captures ALTER COLUMN expires_at DROP DEFAULT")
    op.execute("ALTER TABLE measurement_import_captures ADD CHECK (expires_at>created_at)")
