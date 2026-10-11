"""Keep actual readiness and quality handoff on existing sample/request identities."""
# ruff: noqa: E501

from alembic import op
from sqlalchemy import text

from migrations.schema_0015 import NEW_FORMAL_CHECKS, OLD_FORMAL_CHECKS, SCHEMA_SQL, TABLES

revision = "next_0015"
down_revision = "next_0014"
branch_labels = None
depends_on = None


def replace_formal_checks(checks):
    names = (
        op.get_bind()
        .execute(
            text(
                "SELECT conname FROM pg_constraint WHERE conrelid='verification_formal_requests'::regclass AND contype='c'"
            )
        )
        .scalars()
        .all()
    )
    for name in names:
        op.drop_constraint(name, "verification_formal_requests", type_="check")
    for name, expression in checks:
        op.create_check_constraint(name, "verification_formal_requests", expression)


def upgrade():
    replace_formal_checks(
        tuple(
            (f"verification_formal_handoff_check_{i}", expression)
            for i, expression in enumerate(NEW_FORMAL_CHECKS)
        )
    )
    for statement in SCHEMA_SQL:
        op.execute(statement)
    op.execute("""
      CREATE FUNCTION protect_sample_readiness_binding() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE sample sample_units%ROWTYPE; lot build_lots%ROWTYPE;
              actual actual_configurations%ROWTYPE; prior sample_readiness_facts%ROWTYPE;
              started build_starts%ROWTYPE;
      BEGIN
        SELECT * INTO sample FROM sample_units WHERE tenant_id=NEW.tenant_id AND id=NEW.sample_id;
        SELECT * INTO lot FROM build_lots WHERE tenant_id=NEW.tenant_id AND id=NEW.lot_id;
        SELECT * INTO actual FROM actual_configurations WHERE tenant_id=NEW.tenant_id AND id=NEW.actual_configuration_id;
        IF sample.id IS NULL OR lot.id IS NULL OR actual.id IS NULL
          OR ROW(NEW.sample_revision,NEW.lot_id,NEW.actual_configuration_id,NEW.build_revision)
            IS DISTINCT FROM ROW(sample.revision,sample.lot_id,sample.actual_configuration_id,sample.build_revision)
          OR NEW.lot_revision<>lot.revision OR NEW.actual_configuration_revision<>actual.revision
          OR NEW.occurred_at<lot.occurred_at OR NEW.occurred_at<actual.observed_at
          OR NEW.received_at>clock_timestamp() OR (lot.observation_nature='synthetic' AND NEW.nature<>'synthetic')
          THEN RAISE EXCEPTION 'Readiness must retain exact sample/lot/actual identity and event times'; END IF;
        IF NEW.status='ready' THEN
          SELECT * INTO started FROM build_starts WHERE tenant_id=NEW.tenant_id
            AND product_id=NEW.product_id AND build_id=NEW.build_id;
          IF started.id IS NULL OR NEW.occurred_at<started.occurred_at THEN
            RAISE EXCEPTION 'Ready requires a prior actual start for the same Build'; END IF;
        END IF;
        IF NEW.revision>1 THEN
          SELECT * INTO prior FROM sample_readiness_facts WHERE tenant_id=NEW.tenant_id AND id=NEW.previous_readiness_id;
          IF NOT FOUND OR ROW(NEW.project_id,NEW.build_id,NEW.build_revision,NEW.sample_id,NEW.sample_revision,
                NEW.lot_id,NEW.lot_revision,NEW.actual_configuration_id,NEW.actual_configuration_revision,NEW.previous_revision)
            IS DISTINCT FROM ROW(prior.project_id,prior.build_id,prior.build_revision,prior.sample_id,prior.sample_revision,
                prior.lot_id,prior.lot_revision,prior.actual_configuration_id,prior.actual_configuration_revision,prior.revision)
            OR NEW.occurred_at<=prior.occurred_at THEN
            RAISE EXCEPTION 'Readiness history cannot change physical identity or rewind event time'; END IF;
        END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION protect_sample_readiness_pointer() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE target sample_readiness_facts%ROWTYPE;
      BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Sample readiness history is retained'; END IF;
        SELECT * INTO target FROM sample_readiness_facts WHERE tenant_id=NEW.tenant_id AND id=NEW.readiness_id;
        IF NOT FOUND OR ROW(NEW.product_id,NEW.project_id,NEW.build_id,NEW.sample_id,NEW.readiness_revision)
          IS DISTINCT FROM ROW(target.product_id,target.project_id,target.build_id,target.sample_id,target.revision)
          THEN RAISE EXCEPTION 'Readiness pointer must bind exact scope'; END IF;
        IF TG_OP='INSERT' THEN
          IF NEW.readiness_revision<>1 OR target.previous_readiness_id IS NOT NULL THEN
            RAISE EXCEPTION 'Readiness pointer begins at first version'; END IF;
        ELSIF ROW(NEW.id,NEW.tenant_id,NEW.product_id,NEW.project_id,NEW.build_id,NEW.sample_id,NEW.created_at)
          IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.product_id,OLD.project_id,OLD.build_id,OLD.sample_id,OLD.created_at)
          OR NEW.readiness_revision<>OLD.readiness_revision+1
          OR target.previous_readiness_id IS DISTINCT FROM OLD.readiness_id
          OR target.previous_revision IS DISTINCT FROM OLD.readiness_revision THEN
          RAISE EXCEPTION 'Readiness pointer must advance to exact successor'; END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION protect_actual_method_binding() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE sample sample_units%ROWTYPE; actual actual_configurations%ROWTYPE;
              parent verification_formal_requests%ROWTYPE; batch verification_actual_method_batches%ROWTYPE;
              prior verification_actual_method_applicabilities%ROWTYPE;
      BEGIN
        SELECT * INTO sample FROM sample_units WHERE tenant_id=NEW.tenant_id AND id=NEW.sample_id;
        SELECT * INTO actual FROM actual_configurations WHERE tenant_id=NEW.tenant_id AND id=NEW.actual_configuration_id;
        SELECT * INTO parent FROM verification_formal_requests WHERE tenant_id=NEW.tenant_id AND id=NEW.request_version_id;
        SELECT * INTO batch FROM verification_actual_method_batches WHERE tenant_id=NEW.tenant_id AND id=NEW.batch_id;
        IF sample.id IS NULL OR actual.id IS NULL OR parent.id IS NULL OR batch.id IS NULL
          OR ROW(NEW.sample_revision,NEW.actual_configuration_id,NEW.build_id,NEW.project_id)
            IS DISTINCT FROM ROW(sample.revision,sample.actual_configuration_id,sample.build_id,sample.project_id)
          OR NEW.actual_configuration_revision<>actual.revision OR NEW.build_id<>parent.build_id
          OR ROW(NEW.request_version_id,NEW.request_revision,NEW.owner_id,NEW.visibility)
            IS DISTINCT FROM ROW(batch.request_version_id,batch.request_revision,batch.owner_id,batch.visibility)
          OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(parent.request_snapshot->'items') item WHERE item->>'id'=NEW.item_id)
          THEN RAISE EXCEPTION 'Actual method must bind the exact sample/item/request/batch'; END IF;
        IF NEW.revision>1 THEN
          SELECT * INTO prior FROM verification_actual_method_applicabilities WHERE tenant_id=NEW.tenant_id AND id=NEW.previous_assessment_id;
          IF NOT FOUND OR ROW(NEW.project_id,NEW.request_id,NEW.sample_id,NEW.sample_revision,NEW.build_id,
                NEW.actual_configuration_id,NEW.actual_configuration_revision,NEW.item_id,NEW.previous_revision)
            IS DISTINCT FROM ROW(prior.project_id,prior.request_id,prior.sample_id,prior.sample_revision,prior.build_id,
                prior.actual_configuration_id,prior.actual_configuration_revision,prior.item_id,prior.revision) THEN
            RAISE EXCEPTION 'Actual applicability cannot rebind its physical sample/item'; END IF;
        END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION protect_actual_method_pointer() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE target verification_actual_method_applicabilities%ROWTYPE;
      BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Actual method history is retained'; END IF;
        SELECT * INTO target FROM verification_actual_method_applicabilities WHERE tenant_id=NEW.tenant_id AND id=NEW.assessment_id;
        IF NOT FOUND OR ROW(NEW.product_id,NEW.request_id,NEW.sample_id,NEW.item_id,NEW.assessment_revision)
          IS DISTINCT FROM ROW(target.product_id,target.request_id,target.sample_id,target.item_id,target.revision)
          THEN RAISE EXCEPTION 'Actual method pointer must bind exact pair'; END IF;
        IF TG_OP='INSERT' THEN
          IF NEW.assessment_revision<>1 OR target.previous_assessment_id IS NOT NULL THEN
            RAISE EXCEPTION 'Actual method pointer begins at first version'; END IF;
        ELSIF ROW(NEW.id,NEW.tenant_id,NEW.product_id,NEW.request_id,NEW.sample_id,NEW.item_id,NEW.created_at)
          IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.product_id,OLD.request_id,OLD.sample_id,OLD.item_id,OLD.created_at)
          OR NEW.assessment_revision<>OLD.assessment_revision+1
          OR target.previous_assessment_id IS DISTINCT FROM OLD.assessment_id
          OR target.previous_revision IS DISTINCT FROM OLD.assessment_revision THEN
          RAISE EXCEPTION 'Actual method pointer must advance to exact successor'; END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION protect_quality_handoff_binding() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE target verification_formal_requests%ROWTYPE;
      BEGIN
        SELECT * INTO target FROM verification_formal_requests WHERE tenant_id=NEW.tenant_id AND id=NEW.next_request_version_id;
        IF NOT FOUND OR ROW(NEW.request_version_id,NEW.request_revision,NEW.operation,NEW.status,
            NEW.product_id,NEW.project_id,NEW.request_id,NEW.next_request_revision)
          IS DISTINCT FROM ROW(target.previous_request_id,target.previous_revision,target.operation,target.status,
            target.product_id,target.project_id,target.request_id,target.revision)
          THEN RAISE EXCEPTION 'Handoff must bind exact previous and resulting request versions'; END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION require_quality_handoff_fact() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF NEW.operation IN ('verification.handoff.offer','verification.handoff.accept','verification.handoff.return')
          AND NOT EXISTS (SELECT 1 FROM verification_handoff_facts f WHERE f.tenant_id=NEW.tenant_id
            AND f.product_id=NEW.product_id AND f.next_request_version_id=NEW.id AND f.operation=NEW.operation) THEN
          RAISE EXCEPTION 'Physical request successor and named handoff fact must commit together'; END IF;
        RETURN NULL;
      END $$;
      CREATE CONSTRAINT TRIGGER handoff_fact_required AFTER INSERT ON verification_formal_requests
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION require_quality_handoff_fact();
    """)
    pointers = {
        "sample_current_readiness": "protect_sample_readiness_pointer",
        "verification_current_actual_methods": "protect_actual_method_pointer",
    }
    bindings = {
        "sample_readiness_facts": "protect_sample_readiness_binding",
        "verification_actual_method_applicabilities": "protect_actual_method_binding",
        "verification_handoff_facts": "protect_quality_handoff_binding",
    }
    for name in TABLES:
        op.execute(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{name}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_scope ON "{name}" '
            "USING (tenant_id = nullif(current_setting('pdos.tenant_id',true),'')::uuid) "
            "WITH CHECK (tenant_id = nullif(current_setting('pdos.tenant_id',true),'')::uuid)"
        )
        permissions = "SELECT, INSERT, UPDATE" if name in pointers else "SELECT, INSERT"
        op.execute(f'GRANT {permissions} ON "{name}" TO pdos_next_app')
        function = pointers.get(name, "protect_next_snapshot")
        actions = "INSERT OR UPDATE OR DELETE" if name in pointers else "UPDATE OR DELETE"
        op.execute(
            f'CREATE TRIGGER retained_record BEFORE {actions} ON "{name}" FOR EACH ROW EXECUTE FUNCTION {function}()'
        )
        if name in bindings:
            op.execute(
                f'CREATE TRIGGER fixed_binding BEFORE INSERT ON "{name}" FOR EACH ROW EXECUTE FUNCTION {bindings[name]}()'
            )
        op.execute(
            f'CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON "{name}" FOR EACH ROW EXECUTE FUNCTION lifecycle_reference_gate()'
        )


def downgrade():
    op.execute("DROP TRIGGER handoff_fact_required ON verification_formal_requests")
    op.execute("DROP FUNCTION require_quality_handoff_fact()")
    for name in reversed(TABLES):
        op.drop_table(name)
    for name in (
        "protect_quality_handoff_binding",
        "protect_actual_method_pointer",
        "protect_actual_method_binding",
        "protect_sample_readiness_pointer",
        "protect_sample_readiness_binding",
    ):
        op.execute(f"DROP FUNCTION {name}()")
    replace_formal_checks(OLD_FORMAL_CHECKS)
