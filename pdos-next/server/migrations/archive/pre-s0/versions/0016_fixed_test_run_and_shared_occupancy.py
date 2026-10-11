"""Fixed accepted Run plan, independent promise and atomic test start."""
# ruff: noqa: E501

from alembic import op
from sqlalchemy import inspect, text

from migrations.schema_0016 import NEW_FORMAL_CHECKS, OLD_FORMAL_CHECKS, SCHEMA_SQL, TABLES

revision = "next_0016"
down_revision = "next_0015"
branch_labels = None
depends_on = None


def formal_checks(checks, prefix):
    for constraint in inspect(op.get_bind()).get_check_constraints("verification_formal_requests"):
        op.drop_constraint(constraint["name"], "verification_formal_requests", type_="check")
    for index, expression in enumerate(checks):
        op.create_check_constraint(f"{prefix}_{index}", "verification_formal_requests", expression)


def resource_owner_constraints(*, old=False):
    table = "operational_resource_occupancies"
    info = inspect(op.get_bind())
    for constraint in info.get_foreign_keys(table):
        if any(key in constraint["constrained_columns"] for key in ("owner_execution_id", "build_start_id", "test_run_id")):
            op.drop_constraint(constraint["name"], table, type_="foreignkey")
    for constraint in info.get_unique_constraints(table):
        if "asset_id" in constraint["column_names"]:
            op.drop_constraint(constraint["name"], table, type_="unique")
    if old:
        op.create_unique_constraint("operational_resource_build_asset", table, ["tenant_id", "build_id", "asset_id"])
        op.create_foreign_key("operational_resource_build_owner", table, "build_starts", ["tenant_id", "product_id", "project_id", "build_id", "owner_execution_id"], ["tenant_id", "product_id", "project_id", "build_id", "id"], deferrable=True, initially="DEFERRED")
        return
    op.create_unique_constraint("operational_resource_physical_owner", table, ["tenant_id", "owner_kind", "owner_execution_id", "asset_id"])
    for column, target in (("build_start_id", "build_starts"), ("test_run_id", "verification_run_identities")):
        op.create_foreign_key(f"operational_resource_{column}_owner", table, target, ["tenant_id", "product_id", "project_id", "build_id", column], ["tenant_id", "product_id", "project_id", "build_id", "id"], deferrable=True, initially="DEFERRED")


def upgrade():
    formal_checks(NEW_FORMAL_CHECKS, "verification_formal_launch_check")
    for statement in SCHEMA_SQL:
        op.execute(statement)
    op.execute("""
      ALTER TABLE operational_resource_occupancies ADD COLUMN owner_kind varchar(16) NOT NULL DEFAULT 'build';
      ALTER TABLE operational_resource_occupancies ADD COLUMN build_start_id uuid;
      ALTER TABLE operational_resource_occupancies ADD COLUMN test_run_id uuid;
      DROP TRIGGER retained_record ON operational_resource_occupancies;
      UPDATE operational_resource_occupancies SET build_start_id=owner_execution_id;
      CREATE TRIGGER retained_record BEFORE UPDATE OR DELETE ON operational_resource_occupancies FOR EACH ROW EXECUTE FUNCTION protect_next_snapshot();
    """)
    resource_owner_constraints()
    op.create_check_constraint("operational_resource_owner_kind", "operational_resource_occupancies", "(owner_kind='build' AND build_start_id=owner_execution_id AND build_start_id IS NOT NULL AND test_run_id IS NULL) OR (owner_kind='test_run' AND test_run_id=owner_execution_id AND test_run_id IS NOT NULL AND build_start_id IS NULL)")
    op.execute("""
      CREATE FUNCTION protect_test_resource_fact() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE prior test_resource_facts%ROWTYPE; parent verification_formal_requests%ROWTYPE;
      BEGIN
        SELECT * INTO parent FROM verification_formal_requests WHERE tenant_id=NEW.tenant_id AND id=NEW.accepted_request_id;
        IF parent.id IS NULL OR parent.status<>'accepted' OR ROW(NEW.product_id,NEW.project_id,NEW.build_id,NEW.request_id,NEW.accepted_request_revision)
          IS DISTINCT FROM ROW(parent.product_id,parent.project_id,parent.build_id,parent.request_id,parent.revision)
          OR NEW.binding->>'run_id'<>NEW.run_id::text OR NEW.binding->>'purpose'<>parent.purpose THEN
          RAISE EXCEPTION 'Test fact must bind exact accepted request and Run intent'; END IF;
        IF NEW.revision>1 THEN
          SELECT * INTO prior FROM test_resource_facts WHERE tenant_id=NEW.tenant_id AND id=NEW.previous_id;
          IF prior.id IS NULL OR ROW(NEW.product_id,NEW.project_id,NEW.build_id,NEW.run_id,NEW.request_id,NEW.accepted_request_id,NEW.accepted_request_revision,NEW.series_id,NEW.owner_id,NEW.visibility,NEW.issuer_key,NEW.nature,NEW.previous_revision)
            IS DISTINCT FROM ROW(prior.product_id,prior.project_id,prior.build_id,prior.run_id,prior.request_id,prior.accepted_request_id,prior.accepted_request_revision,prior.series_id,prior.owner_id,prior.visibility,prior.issuer_key,prior.nature,prior.revision)
            OR NEW.binding IS DISTINCT FROM prior.binding THEN RAISE EXCEPTION 'Test fact lineage cannot change fixed intent'; END IF;
        END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION protect_test_resource_pointer() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE target test_resource_facts%ROWTYPE;
      BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Test fact history is retained'; END IF;
        SELECT * INTO target FROM test_resource_facts WHERE tenant_id=NEW.tenant_id AND id=NEW.fact_id;
        IF target.id IS NULL OR ROW(NEW.product_id,NEW.project_id,NEW.build_id,NEW.run_id,NEW.request_id,NEW.fact_revision)
          IS DISTINCT FROM ROW(target.product_id,target.project_id,target.build_id,target.run_id,target.request_id,target.revision) THEN
          RAISE EXCEPTION 'Test current must match complete scope'; END IF;
        IF TG_OP='INSERT' THEN
          IF NEW.epoch<>1 OR NEW.fact_revision<>1 OR target.previous_id IS NOT NULL THEN RAISE EXCEPTION 'Test pointer starts at first version'; END IF;
        ELSIF ROW(NEW.id,NEW.tenant_id,NEW.product_id,NEW.project_id,NEW.build_id,NEW.run_id,NEW.request_id,NEW.created_at)
          IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.product_id,OLD.project_id,OLD.build_id,OLD.run_id,OLD.request_id,OLD.created_at)
          OR NEW.epoch<>OLD.epoch+1 OR NEW.fact_revision<>OLD.fact_revision+1 OR target.previous_id IS DISTINCT FROM OLD.fact_id THEN
          RAISE EXCEPTION 'Test pointer advances to exact successor'; END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION protect_sample_use_epoch() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP='DELETE' OR ROW(NEW.id,NEW.tenant_id,NEW.product_id,NEW.sample_id,NEW.created_at)
          IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.product_id,OLD.sample_id,OLD.created_at) OR NEW.epoch<>OLD.epoch+1 THEN
          RAISE EXCEPTION 'Physical sample use gate must remain monotonic'; END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION protect_verification_run_pointer() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE target verification_run_versions%ROWTYPE;
      BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Run history is retained'; END IF;
        SELECT * INTO target FROM verification_run_versions WHERE tenant_id=NEW.tenant_id AND id=NEW.run_version_id;
        IF target.id IS NULL OR ROW(NEW.product_id,NEW.request_id,NEW.run_id,NEW.run_revision)
          IS DISTINCT FROM ROW(target.product_id,target.request_id,target.run_id,target.revision) THEN RAISE EXCEPTION 'Run current must match fixed version'; END IF;
        IF TG_OP='INSERT' THEN
          IF NEW.run_revision<>1 OR target.previous_run_version_id IS NOT NULL THEN RAISE EXCEPTION 'Run starts at first version'; END IF;
        ELSIF ROW(NEW.id,NEW.tenant_id,NEW.product_id,NEW.request_id,NEW.run_id,NEW.created_at)
          IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.product_id,OLD.request_id,OLD.run_id,OLD.created_at)
          OR NEW.run_revision<>OLD.run_revision+1 OR target.previous_run_version_id IS DISTINCT FROM OLD.run_version_id THEN
          RAISE EXCEPTION 'Run pointer advances to exact successor'; END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION protect_verification_run_binding() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE identity verification_run_identities%ROWTYPE; prior verification_run_versions%ROWTYPE;
      BEGIN
        SELECT * INTO identity FROM verification_run_identities WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;
        IF identity.id IS NULL OR ROW(NEW.product_id,NEW.project_id,NEW.build_id,NEW.request_id,NEW.owner_id,NEW.visibility)
          IS DISTINCT FROM ROW(identity.product_id,identity.project_id,identity.build_id,identity.request_id,identity.owner_id,identity.visibility)
          OR NEW.run_snapshot->>'id'<>NEW.run_id::text OR (NEW.run_snapshot->>'revision')::int<>NEW.revision OR NEW.run_snapshot->>'status'<>NEW.status THEN
          RAISE EXCEPTION 'Run version must retain exact identity and snapshot'; END IF;
        IF NEW.revision>1 THEN
          SELECT * INTO prior FROM verification_run_versions WHERE tenant_id=NEW.tenant_id AND id=NEW.previous_run_version_id;
          IF prior.id IS NULL OR ROW(NEW.request_version_id,NEW.request_revision,NEW.plan_sha256,NEW.execution_plan)
            IS DISTINCT FROM ROW(prior.request_version_id,prior.request_revision,prior.plan_sha256,prior.execution_plan)
            OR NEW.run_snapshot->'coverage' IS DISTINCT FROM prior.run_snapshot->'coverage'
            OR NEW.run_snapshot->'items' IS DISTINCT FROM prior.run_snapshot->'items'
            OR NEW.run_snapshot->'samples' IS DISTINCT FROM prior.run_snapshot->'samples' THEN RAISE EXCEPTION 'Started Run cannot rewrite fixed plan or coverage'; END IF;
        END IF;
        IF NEW.status='running' AND ((NEW.run_snapshot->'actual_start'->>'occurred_at')::timestamptz>clock_timestamp()
          OR (NEW.run_snapshot->'actual_start'->>'occurred_at')::timestamptz<(NEW.execution_plan->'window'->>'start')::timestamptz
          OR (NEW.run_snapshot->'actual_start'->>'occurred_at')::timestamptz>=(NEW.execution_plan->'window'->>'finish')::timestamptz) THEN
          RAISE EXCEPTION 'Actual test start must lie within fixed resource window'; END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION protect_sample_run_usage() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE sample sample_units%ROWTYPE; actual actual_configurations%ROWTYPE;
      BEGIN
        SELECT * INTO sample FROM sample_units WHERE tenant_id=NEW.tenant_id AND id=NEW.sample_id;
        SELECT * INTO actual FROM actual_configurations WHERE tenant_id=NEW.tenant_id AND id=NEW.actual_configuration_id;
        IF sample.id IS NULL OR actual.id IS NULL OR ROW(NEW.product_id,NEW.project_id,NEW.build_id,NEW.sample_revision,NEW.actual_configuration_id)
          IS DISTINCT FROM ROW(sample.product_id,sample.project_id,sample.build_id,sample.revision,sample.actual_configuration_id)
          OR NEW.actual_configuration_revision<>actual.revision THEN RAISE EXCEPTION 'Sample use must bind exact physical actual configuration'; END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION assert_test_run_atom(tid uuid, rid uuid) RETURNS void LANGUAGE plpgsql AS $$
      DECLARE run verification_run_versions%ROWTYPE; reservation test_resource_reservations%ROWTYPE;
      BEGIN
        SELECT * INTO run FROM verification_run_versions WHERE tenant_id=tid AND run_id=rid AND status='running';
        IF run.id IS NULL OR NOT EXISTS (SELECT 1 FROM verification_launch_facts f
          JOIN verification_formal_requests q ON q.tenant_id=f.tenant_id AND q.id=f.next_request_version_id
          WHERE f.tenant_id=tid AND f.run_version_id=run.id AND f.operation='test.run.start'
          AND q.status='executing' AND q.request_id=run.request_id) THEN
          RAISE EXCEPTION 'Every test use requires its exact actual Run and request start'; END IF;
        SELECT * INTO reservation FROM test_resource_reservations WHERE tenant_id=tid AND run_id=rid;
        IF reservation.id IS NULL OR ROW(reservation.product_id,reservation.project_id,reservation.build_id,reservation.intent_digest)
          IS DISTINCT FROM ROW(run.product_id,run.project_id,run.build_id,run.intent_digest)
          OR reservation.binding IS DISTINCT FROM run.input_snapshot->'plan_binding' THEN
          RAISE EXCEPTION 'Actual Run must retain exact resource reservation binding'; END IF;
        IF (SELECT array_agg(u.sample_id::text ORDER BY u.sample_id::text) FROM sample_run_usages u WHERE u.tenant_id=tid AND u.run_id=rid)
          IS DISTINCT FROM (SELECT array_agg(v->>'id' ORDER BY v->>'id') FROM jsonb_array_elements(run.run_snapshot->'samples') v) THEN
          RAISE EXCEPTION 'Actual Run requires its exact complete physical sample set'; END IF;
        IF EXISTS (SELECT 1 FROM sample_run_usages u WHERE u.tenant_id=tid AND u.run_id=rid AND (
          ROW(u.product_id,u.project_id,u.build_id,u.intent_digest,u.window_start,u.window_finish)
            IS DISTINCT FROM ROW(run.product_id,run.project_id,run.build_id,run.intent_digest,
              (run.execution_plan->'window'->>'start')::timestamptz,(run.execution_plan->'window'->>'finish')::timestamptz)
          OR (SELECT jsonb_agg(c ORDER BY c->>'sample_id',c->>'item_id') FROM jsonb_array_elements(u.coverage) c)
            IS DISTINCT FROM (SELECT jsonb_agg(c ORDER BY c->>'sample_id',c->>'item_id') FROM jsonb_array_elements(run.run_snapshot->'coverage') c WHERE c->>'sample_id'=u.sample_id::text)
          OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(run.run_snapshot->'samples') v WHERE
            v->>'id'=u.sample_id::text AND (v->>'revision')::int=u.sample_revision
            AND v->'actual_configuration'->>'id'=u.actual_configuration_id::text
            AND (v->'actual_configuration'->>'revision')::int=u.actual_configuration_revision)
          OR u.destructive IS DISTINCT FROM EXISTS (SELECT 1 FROM jsonb_array_elements(run.run_snapshot->'items') i
            JOIN jsonb_array_elements(u.coverage) c ON c->>'item_id'=i->>'id' WHERE (i->>'destructive')::boolean)
          OR u.source_basis->'actual_start'->'source' IS DISTINCT FROM run.run_snapshot->'actual_start'->'source'
          OR (u.source_basis->'actual_start'->>'occurred_at')::timestamptz IS DISTINCT FROM (run.run_snapshot->'actual_start'->>'occurred_at')::timestamptz)) THEN
          RAISE EXCEPTION 'Sample use must match exact Run coverage, configuration, event and window'; END IF;
        IF (SELECT count(*) FROM operational_resource_occupancies o WHERE o.tenant_id=tid AND o.test_run_id=rid)
          <>jsonb_array_length(reservation.reservation->'request'->'uses') OR EXISTS (
          SELECT 1 FROM operational_resource_occupancies o WHERE o.tenant_id=tid AND o.test_run_id=rid AND (
            ROW(o.product_id,o.project_id,o.build_id,o.intent_digest,o.window_start,o.window_finish)
              IS DISTINCT FROM ROW(run.product_id,run.project_id,run.build_id,run.intent_digest,
                (run.execution_plan->'window'->>'start')::timestamptz,(run.execution_plan->'window'->>'finish')::timestamptz)
            OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(reservation.reservation->'request'->'uses') v WHERE
              v->'resource'->>'id'=o.resource_id::text AND (v->'resource'->>'revision')::int=o.resource_revision
              AND (v->>'units')::numeric=o.units))) THEN
          RAISE EXCEPTION 'Every test resource occupancy must match its exact full-window use'; END IF;
      END $$;
      CREATE FUNCTION require_test_launch_atom() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_TABLE_NAME='verification_formal_requests' THEN
          IF NEW.operation NOT IN ('verification.schedule.promise','test.run.start') THEN RETURN NULL; END IF;
          IF NOT EXISTS (SELECT 1 FROM verification_launch_facts f WHERE f.tenant_id=NEW.tenant_id AND f.next_request_version_id=NEW.id AND f.operation=NEW.operation) THEN
            RAISE EXCEPTION 'Request launch successor requires its named fact'; END IF;
          RETURN NULL;
        ELSIF TG_TABLE_NAME='operational_resource_occupancies' THEN
          IF NEW.owner_kind<>'test_run' THEN RETURN NULL; END IF;
          PERFORM assert_test_run_atom(NEW.tenant_id,NEW.test_run_id);
        ELSIF TG_TABLE_NAME IN ('sample_run_usages','test_resource_reservations') THEN
          PERFORM assert_test_run_atom(NEW.tenant_id,NEW.run_id);
        ELSE
          IF NOT EXISTS (SELECT 1 FROM verification_launch_facts f WHERE f.tenant_id=NEW.tenant_id AND f.run_version_id=NEW.id AND f.operation=NEW.operation) THEN
            RAISE EXCEPTION 'Run version requires its launch fact'; END IF;
          IF NEW.status='running' THEN PERFORM assert_test_run_atom(NEW.tenant_id,NEW.run_id); END IF;
        END IF;
        RETURN NULL;
      END $$;
    """)
    pointers = {"test_resource_current": "protect_test_resource_pointer", "verification_current_runs": "protect_verification_run_pointer"}
    inserts = {"test_resource_facts": "protect_test_resource_fact", "verification_run_versions": "protect_verification_run_binding", "sample_run_usages": "protect_sample_run_usage"}
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY tenant_scope ON "{table}" USING (tenant_id=nullif(current_setting(\'pdos.tenant_id\',true),\'\')::uuid) WITH CHECK (tenant_id=nullif(current_setting(\'pdos.tenant_id\',true),\'\')::uuid)')
        mutable = table in pointers or table == "sample_usage_sentinels"
        op.execute(f'GRANT SELECT, INSERT{", UPDATE" if mutable else ""} ON "{table}" TO pdos_next_app')
        function = pointers.get(table, "protect_sample_use_epoch" if mutable else "protect_next_snapshot")
        actions = "INSERT OR UPDATE OR DELETE" if table in pointers else "UPDATE OR DELETE"
        op.execute(f'CREATE TRIGGER retained_record BEFORE {actions} ON "{table}" FOR EACH ROW EXECUTE FUNCTION {function}()')
        if table in inserts:
            op.execute(f'CREATE TRIGGER fixed_binding BEFORE INSERT ON "{table}" FOR EACH ROW EXECUTE FUNCTION {inserts[table]}()')
        op.execute(f'CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON "{table}" FOR EACH ROW EXECUTE FUNCTION lifecycle_reference_gate()')
    op.execute("GRANT UPDATE(id) ON verification_run_identities TO pdos_next_app")
    for table in ("verification_formal_requests", "verification_run_versions", "operational_resource_occupancies", "sample_run_usages", "test_resource_reservations"):
        op.execute(f'CREATE CONSTRAINT TRIGGER test_launch_required AFTER INSERT ON "{table}" DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION require_test_launch_atom()')
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM pdos_agent")


def downgrade():
    if op.get_bind().scalar(text("SELECT EXISTS(SELECT 1 FROM verification_run_identities) OR EXISTS(SELECT 1 FROM test_resource_facts)")):
        raise RuntimeError("Wave13 facts require preserved recovery; destructive downgrade is unavailable after business writes")
    for table in ("verification_formal_requests", "verification_run_versions", "operational_resource_occupancies", "sample_run_usages", "test_resource_reservations"):
        op.execute(f'DROP TRIGGER IF EXISTS test_launch_required ON "{table}"')
    resource_owner_constraints(old=True)
    op.drop_constraint("operational_resource_owner_kind", "operational_resource_occupancies", type_="check")
    for column in ("test_run_id", "build_start_id", "owner_kind"):
        op.drop_column("operational_resource_occupancies", column)
    for table in reversed(TABLES):
        op.drop_table(table)
    for function in ("protect_test_resource_fact", "protect_test_resource_pointer", "protect_sample_use_epoch", "protect_verification_run_pointer", "protect_verification_run_binding", "protect_sample_run_usage", "require_test_launch_atom", "assert_test_run_atom"):
        op.execute(f'DROP FUNCTION IF EXISTS "{function}"{ "(uuid,uuid)" if function == "assert_test_run_atom" else "()"}')
    formal_checks(OLD_FORMAL_CHECKS, "verification_formal_handoff_check")
