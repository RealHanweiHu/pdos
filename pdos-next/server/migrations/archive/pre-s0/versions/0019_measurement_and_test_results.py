"""Exact source measurements and results on the existing Request/Run chains."""
# ruff: noqa: E501

from alembic import op
from sqlalchemy import inspect, text

from migrations.schema_0019 import NEW_CHECKS, OLD_CHECKS, OLD_FUNCTION_SQL, SCHEMA_SQL, TABLES

revision = "next_0019"
down_revision = "next_0018"
branch_labels = None
depends_on = None


def checks(values, prefix):
    for table, expressions in values.items():
        for constraint in inspect(op.get_bind()).get_check_constraints(table):
            op.drop_constraint(constraint["name"], table, type_="check")
        for index, expression in enumerate(expressions):
            op.create_check_constraint(f"{prefix}_{table}_{index}", table, expression)


def upgrade():
    checks(NEW_CHECKS, "result")
    for statement in SCHEMA_SQL:
        op.execute(statement)
    binding = OLD_FUNCTION_SQL["protect_verification_run_binding"]
    anchor = "OR NEW.run_snapshot->'samples' IS DISTINCT FROM prior.run_snapshot->'samples'"
    assert binding.count(anchor) == 1
    binding = binding.replace(
        anchor,
        anchor
        + """
            OR NEW.previous_revision<>prior.revision OR NEW.revision<>prior.revision+1
            OR NEW.run_snapshot->'scope' IS DISTINCT FROM prior.run_snapshot->'scope'
            OR NEW.run_snapshot->'build' IS DISTINCT FROM prior.run_snapshot->'build'
            OR NEW.run_snapshot->>'request_id' IS DISTINCT FROM prior.run_snapshot->>'request_id'
            OR NEW.input_snapshot->'plan_binding' IS DISTINCT FROM prior.input_snapshot->'plan_binding'
            OR (NEW.revision>2 AND (
              NEW.run_snapshot->'actual_start' IS DISTINCT FROM prior.run_snapshot->'actual_start'
              OR NEW.run_snapshot->'execution' IS DISTINCT FROM prior.run_snapshot->'execution'
              OR NEW.input_snapshot->'reservation' IS DISTINCT FROM prior.input_snapshot->'reservation'
              OR NOT COALESCE(NEW.run_snapshot->'measurements' @> prior.run_snapshot->'measurements',false)))
    """,
    )
    op.execute(binding)
    atom = OLD_FUNCTION_SQL["assert_test_run_atom"]
    anchor = "AND status='running'"
    assert atom.count(anchor) == 1
    # Exactly the immutable original Start, never an ambiguous partial result row.
    op.execute(
        atom.replace(anchor, "AND revision=2 AND operation='test.run.start' AND status='running'")
    )
    op.execute("""
      CREATE FUNCTION assert_test_result_atom(tid uuid, version_id uuid) RETURNS void LANGUAGE plpgsql AS $$
      DECLARE target verification_run_versions%ROWTYPE; prior verification_run_versions%ROWTYPE;
              fact test_result_actions%ROWTYPE; report test_result_projections%ROWTYPE;
              request_before verification_formal_requests%ROWTYPE; request_after verification_formal_requests%ROWTYPE;
      BEGIN
        SELECT * INTO target FROM verification_run_versions WHERE tenant_id=tid AND id=version_id;
        SELECT * INTO prior FROM verification_run_versions WHERE tenant_id=tid AND id=target.previous_run_version_id;
        SELECT * INTO fact FROM test_result_actions WHERE tenant_id=tid AND next_run_version_id=target.id;
        IF target.id IS NULL OR prior.id IS NULL OR fact.id IS NULL OR target.revision<3
          OR ROW(fact.product_id,fact.project_id,fact.build_id,fact.request_id,fact.run_id,fact.operation,
                 fact.run_version_id,fact.run_revision,fact.next_run_revision,fact.actor_id)
            IS DISTINCT FROM ROW(target.product_id,target.project_id,target.build_id,target.request_id,
                 target.run_id,target.operation,prior.id,prior.revision,target.revision,target.writer_id)
          OR fact.intent_digest IS DISTINCT FROM target.intent_digest THEN
          RAISE EXCEPTION 'Result successor requires its exact named action and previous Run'; END IF;
        SELECT * INTO request_before FROM verification_formal_requests WHERE tenant_id=tid AND id=fact.request_version_id;
        SELECT * INTO request_after FROM verification_formal_requests WHERE tenant_id=tid AND id=fact.next_request_version_id;
        IF request_before.id IS NULL OR request_after.id IS NULL
          OR ROW(request_before.product_id,request_before.project_id,request_before.build_id,request_before.request_id,request_before.revision)
            IS DISTINCT FROM ROW(target.product_id,target.project_id,target.build_id,target.request_id,fact.request_revision)
          OR ROW(request_after.product_id,request_after.project_id,request_after.build_id,request_after.request_id,request_after.revision)
            IS DISTINCT FROM ROW(target.product_id,target.project_id,target.build_id,target.request_id,fact.next_request_revision)
          OR (request_after.id<>request_before.id AND (
            request_after.previous_request_id IS DISTINCT FROM request_before.id
            OR request_after.previous_revision<>request_before.revision OR request_after.operation<>target.operation)) THEN
          RAISE EXCEPTION 'Result action must retain its exact request transition'; END IF;
        IF (target.operation='test.results.import' AND (prior.status<>'running' OR target.status NOT IN ('running','results_pending')))
          OR (target.operation='test.run.review' AND (prior.status<>'results_pending' OR target.status<>'reviewed'))
          OR (target.operation='test.disposition.decide' AND (prior.status<>'reviewed' OR target.status<>'disposed')) THEN
          RAISE EXCEPTION 'Result action must preserve import/review/disposition order'; END IF;
        IF target.operation<>'test.results.import' AND (
          (target.run_snapshot - 'revision' - 'status' - 'professional_conclusion' - 'disposition')
            IS DISTINCT FROM (prior.run_snapshot - 'revision' - 'status' - 'professional_conclusion' - 'disposition')
          OR (target.operation='test.disposition.decide' AND target.run_snapshot->'professional_conclusion'
            IS DISTINCT FROM prior.run_snapshot->'professional_conclusion')) THEN
          RAISE EXCEPTION 'Professional text cannot rewrite raw measurements or numerical results'; END IF;
        SELECT * INTO report FROM test_result_projections WHERE tenant_id=tid AND id=fact.projection_id;
        IF report.id IS NULL OR ROW(report.product_id,report.project_id,report.build_id,report.request_id,report.run_id)
            IS DISTINCT FROM ROW(target.product_id,target.project_id,target.build_id,target.request_id,target.run_id)
          OR report.result IS DISTINCT FROM target.run_snapshot->>'result'
          OR report.computed_results IS DISTINCT FROM target.run_snapshot->'computed_results'
          OR (target.operation='test.results.import' AND report.run_version_id IS DISTINCT FROM target.id) THEN
          RAISE EXCEPTION 'Result action requires its exact immutable computed projection'; END IF;
        IF (SELECT count(*) FROM test_measurements m WHERE m.tenant_id=tid AND m.run_id=target.run_id)
            <>jsonb_array_length(target.run_snapshot->'measurements') OR EXISTS (
          SELECT 1 FROM jsonb_array_elements(target.run_snapshot->'measurements') value WHERE NOT EXISTS (
            SELECT 1 FROM test_measurements m WHERE m.tenant_id=tid AND m.run_id=target.run_id
              AND m.id::text=value->>'id' AND m.measurement=value)) THEN
          RAISE EXCEPTION 'Run measurements must equal the exact immutable physical pair records'; END IF;
        IF NOT EXISTS (SELECT 1 FROM action_receipts r WHERE r.tenant_id=tid
          AND r.product_id=target.product_id AND r.operation=target.operation
          AND r.subject_id=target.id AND r.subject_revision=target.revision AND r.actor_id=fact.actor_id) THEN
          RAISE EXCEPTION 'Result action requires its exact common receipt'; END IF;
        PERFORM assert_test_run_atom(tid,target.run_id);
      END $$;
      CREATE FUNCTION protect_test_result_binding() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE target verification_run_versions%ROWTYPE; capture measurement_import_captures%ROWTYPE;
      BEGIN
        SELECT * INTO target FROM verification_run_versions WHERE tenant_id=NEW.tenant_id AND id=NEW.run_version_id;
        IF target.id IS NULL OR ROW(NEW.product_id,NEW.project_id,NEW.build_id,NEW.request_id,NEW.run_id,NEW.run_revision)
          IS DISTINCT FROM ROW(target.product_id,target.project_id,target.build_id,target.request_id,target.run_id,target.revision) THEN
          RAISE EXCEPTION 'Result object must bind exact fixed Run scope'; END IF;
        IF TG_TABLE_NAME='test_measurements' THEN
          SELECT * INTO capture FROM measurement_import_captures WHERE tenant_id=NEW.tenant_id AND id=NEW.capture_id;
          IF capture.id IS NULL OR capture.product_id<>NEW.product_id OR capture.run_id<>NEW.run_id
            OR capture.run_version_id IS DISTINCT FROM target.previous_run_version_id
            OR NEW.measurement->>'id' IS DISTINCT FROM NEW.id::text
            OR NEW.measurement->'coverage'->>'sample_id' IS DISTINCT FROM NEW.sample_id::text
            OR NEW.measurement->'coverage'->>'item_id' IS DISTINCT FROM NEW.item_id
            OR NEW.verified_observation->'measurement' IS DISTINCT FROM NEW.measurement
            OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(target.run_snapshot->'measurements') v WHERE v=NEW.measurement)
            OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(target.run_snapshot->'samples') v WHERE
              v->>'id'=NEW.sample_id::text AND (v->>'revision')::int=NEW.sample_revision
              AND v->'actual_configuration'->>'id'=NEW.actual_configuration_id::text
              AND (v->'actual_configuration'->>'revision')::int=NEW.actual_configuration_revision) THEN
            RAISE EXCEPTION 'Measurement must bind exact capture, original values and physical configuration'; END IF;
        ELSIF TG_TABLE_NAME='test_result_projections' THEN
          IF NEW.run_sha256 IS DISTINCT FROM target.snapshot_sha256 THEN
            RAISE EXCEPTION 'Projection must bind exact immutable Run snapshot'; END IF;
        ELSIF TG_TABLE_NAME='measurement_import_captures' THEN
          IF NEW.run_sha256 IS DISTINCT FROM target.snapshot_sha256 OR target.status<>'running' THEN
            RAISE EXCEPTION 'Capture must bind exact running Run snapshot'; END IF;
        END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION require_test_result_atom() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_TABLE_NAME='test_result_actions' THEN
          PERFORM assert_test_result_atom(NEW.tenant_id,NEW.next_run_version_id);
        ELSE
          PERFORM assert_test_result_atom(NEW.tenant_id,NEW.run_version_id);
        END IF;
        RETURN NULL;
      END $$;
      CREATE OR REPLACE FUNCTION require_test_launch_atom() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_TABLE_NAME='verification_formal_requests' THEN
          IF NEW.operation IN ('test.results.import','test.run.review','test.disposition.decide') THEN
            IF NOT EXISTS (SELECT 1 FROM test_result_actions f WHERE f.tenant_id=NEW.tenant_id
              AND f.next_request_version_id=NEW.id AND f.operation=NEW.operation) THEN
              RAISE EXCEPTION 'Result request successor requires its exact named action'; END IF;
          ELSIF NEW.operation IN ('verification.schedule.promise','test.run.start') THEN
            IF NOT EXISTS (SELECT 1 FROM verification_launch_facts f WHERE f.tenant_id=NEW.tenant_id
              AND f.next_request_version_id=NEW.id AND f.operation=NEW.operation) THEN
              RAISE EXCEPTION 'Request launch successor requires its named fact'; END IF;
          END IF;
        ELSIF TG_TABLE_NAME='operational_resource_occupancies' THEN
          IF NEW.owner_kind='test_run' THEN PERFORM assert_test_run_atom(NEW.tenant_id,NEW.test_run_id); END IF;
        ELSIF TG_TABLE_NAME IN ('sample_run_usages','test_resource_reservations') THEN
          PERFORM assert_test_run_atom(NEW.tenant_id,NEW.run_id);
        ELSIF NEW.operation IN ('test.results.import','test.run.review','test.disposition.decide') THEN
          PERFORM assert_test_result_atom(NEW.tenant_id,NEW.id);
        ELSE
          IF NOT EXISTS (SELECT 1 FROM verification_launch_facts f WHERE f.tenant_id=NEW.tenant_id
              AND f.run_version_id=NEW.id AND f.operation=NEW.operation) THEN
            RAISE EXCEPTION 'Run version requires its launch fact'; END IF;
          IF NEW.status='running' THEN PERFORM assert_test_run_atom(NEW.tenant_id,NEW.run_id); END IF;
        END IF;
        RETURN NULL;
      END $$;
    """)
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f"CREATE POLICY tenant_scope ON \"{table}\" USING (tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid) WITH CHECK (tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid)"
        )
        op.execute(f'GRANT SELECT,INSERT ON "{table}" TO pdos_next_app')
        op.execute(
            f'CREATE TRIGGER retained_record BEFORE UPDATE OR DELETE ON "{table}" FOR EACH ROW EXECUTE FUNCTION protect_next_snapshot()'
        )
        op.execute(
            f'CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON "{table}" FOR EACH ROW EXECUTE FUNCTION lifecycle_reference_gate()'
        )
        if table != "test_result_actions":
            op.execute(
                f'CREATE TRIGGER fixed_binding BEFORE INSERT ON "{table}" FOR EACH ROW EXECUTE FUNCTION protect_test_result_binding()'
            )
        if table in {"test_measurements", "test_result_actions"}:
            op.execute(
                f'CREATE CONSTRAINT TRIGGER test_result_required AFTER INSERT ON "{table}" DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION require_test_result_atom()'
            )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM pdos_agent")


def downgrade():
    count = op.get_bind().scalar(
        text(
            "SELECT (SELECT count(*) FROM measurement_import_captures)+(SELECT count(*) FROM test_measurements)+(SELECT count(*) FROM test_result_projections)+(SELECT count(*) FROM test_result_actions)+(SELECT count(*) FROM verification_run_versions WHERE revision>2)"
        )
    )
    if count:
        raise RuntimeError("Retained results/candidates must not be deleted by downgrade")
    for statement in OLD_FUNCTION_SQL.values():
        op.execute(statement)
    for table in reversed(TABLES):
        op.drop_table(table)
    for function in (
        "require_test_result_atom()",
        "protect_test_result_binding()",
        "assert_test_result_atom(uuid,uuid)",
    ):
        op.execute(f"DROP FUNCTION {function}")
    checks(OLD_CHECKS, "pre_result")
