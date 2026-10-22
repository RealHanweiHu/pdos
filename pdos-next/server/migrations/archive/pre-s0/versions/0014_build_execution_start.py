"""Bind controlled operations, fixed assessments, separate named approvals and start."""

# SQL guard expressions retain comparable row shapes on one line.
# ruff: noqa: E501

from alembic import op

from migrations.schema_0014 import SCHEMA_SQL, TABLES

revision = "next_0014"
down_revision = "next_0013"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE professional_authority_facts DROP CONSTRAINT professional_authority_facts_check"
    )
    op.execute("""ALTER TABLE professional_authority_facts ADD CONSTRAINT professional_authority_facts_check
        CHECK (kind IN ('duty','qualification') AND role IN ('engineering','quality','manufacturing')
        AND nature IN ('real','synthetic'))""")
    for statement in SCHEMA_SQL:
        op.execute(statement)
    op.execute("""
      CREATE FUNCTION protect_build_operational_fact() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE prior build_operational_facts%ROWTYPE; plan builds%ROWTYPE;
      BEGIN
        SELECT * INTO plan FROM builds WHERE tenant_id=NEW.tenant_id AND id=NEW.build_id;
        IF NOT FOUND OR NEW.build_revision<>plan.revision THEN
          RAISE EXCEPTION 'Operational fact must bind exact Build revision'; END IF;
        IF NEW.revision>1 THEN
          SELECT * INTO prior FROM build_operational_facts WHERE id=NEW.previous_id
            AND tenant_id=NEW.tenant_id AND product_id=NEW.product_id;
          IF NOT FOUND OR ROW(NEW.project_id,NEW.build_id,NEW.build_revision,NEW.owner_id,
              NEW.visibility,NEW.issuer_key,NEW.nature,NEW.external_id,NEW.series_id,NEW.previous_revision)
            IS DISTINCT FROM ROW(prior.project_id,prior.build_id,prior.build_revision,prior.owner_id,
              prior.visibility,prior.issuer_key,prior.nature,prior.external_id,prior.series_id,prior.revision)
          THEN RAISE EXCEPTION 'Operational identity cannot be rebound'; END IF;
        END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION protect_build_operational_pointer() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE target build_operational_facts%ROWTYPE;
      BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Operational history is retained'; END IF;
        SELECT * INTO target FROM build_operational_facts WHERE id=NEW.fact_id
          AND tenant_id=NEW.tenant_id AND product_id=NEW.product_id;
        IF NOT FOUND OR ROW(NEW.project_id,NEW.build_id,NEW.fact_revision)
          IS DISTINCT FROM ROW(target.project_id,target.build_id,target.revision)
          THEN RAISE EXCEPTION 'Operational pointer must match exact scope'; END IF;
        IF TG_OP='INSERT' THEN
          IF NEW.epoch<>1 OR NEW.fact_revision<>1 OR target.previous_id IS NOT NULL
            THEN RAISE EXCEPTION 'Operational pointer must begin at first version'; END IF;
        ELSIF ROW(NEW.id,NEW.tenant_id,NEW.product_id,NEW.project_id,NEW.build_id,NEW.created_at)
          IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.product_id,OLD.project_id,OLD.build_id,OLD.created_at)
          OR NEW.epoch<>OLD.epoch+1 OR NEW.fact_revision<>OLD.fact_revision+1
          OR target.previous_id IS DISTINCT FROM OLD.fact_id
          OR target.previous_revision IS DISTINCT FROM OLD.fact_revision
          THEN RAISE EXCEPTION 'Operational pointer must advance to exact successor'; END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION protect_operational_asset() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Shared asset sentinel is retained'; END IF;
        IF ROW(NEW.id,NEW.tenant_id,NEW.kind,NEW.external_key,NEW.identity,NEW.created_at)
          IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.kind,OLD.external_key,OLD.identity,OLD.created_at)
          OR NEW.revision<OLD.revision OR NEW.occupancy_epoch<>OLD.occupancy_epoch+1
          OR (NEW.revision=OLD.revision AND NEW.data_sha256<>OLD.data_sha256)
          THEN RAISE EXCEPTION 'Shared asset identity/version/occupancy must remain monotonic'; END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION protect_build_assessment_pointer() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE target build_execution_assessments%ROWTYPE;
      BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Assessment history is retained'; END IF;
        SELECT * INTO target FROM build_execution_assessments WHERE id=NEW.assessment_id
          AND tenant_id=NEW.tenant_id AND product_id=NEW.product_id;
        IF NOT FOUND OR ROW(NEW.project_id,NEW.build_id,NEW.assessment_revision)
          IS DISTINCT FROM ROW(target.project_id,target.build_id,target.revision)
          THEN RAISE EXCEPTION 'Assessment pointer must match exact scope'; END IF;
        IF TG_OP='INSERT' THEN
          IF NEW.assessment_revision<>1 OR target.previous_assessment_id IS NOT NULL
            THEN RAISE EXCEPTION 'Assessment pointer must begin at first version'; END IF;
        ELSIF ROW(NEW.id,NEW.tenant_id,NEW.product_id,NEW.project_id,NEW.build_id,NEW.created_at)
          IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.product_id,OLD.project_id,OLD.build_id,OLD.created_at)
          OR NEW.assessment_revision<>OLD.assessment_revision+1
          OR target.previous_assessment_id IS DISTINCT FROM OLD.assessment_id
          OR target.previous_revision IS DISTINCT FROM OLD.assessment_revision
          THEN RAISE EXCEPTION 'Assessment pointer must advance to exact successor'; END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION protect_build_authorization_pointer() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE target build_authorization_decisions%ROWTYPE;
      BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Named authorization history is retained'; END IF;
        SELECT * INTO target FROM build_authorization_decisions WHERE id=NEW.decision_id
          AND tenant_id=NEW.tenant_id AND product_id=NEW.product_id;
        IF NOT FOUND OR ROW(NEW.project_id,NEW.build_id,NEW.role,NEW.decision_revision)
          IS DISTINCT FROM ROW(target.project_id,target.build_id,target.role,target.revision)
          THEN RAISE EXCEPTION 'Authorization pointer must match exact scope'; END IF;
        IF TG_OP='INSERT' THEN
          IF NEW.decision_revision<>1 OR target.previous_decision_id IS NOT NULL
            THEN RAISE EXCEPTION 'Authorization pointer must begin at first version'; END IF;
        ELSIF ROW(NEW.id,NEW.tenant_id,NEW.product_id,NEW.project_id,NEW.build_id,NEW.role,NEW.created_at)
          IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.product_id,OLD.project_id,OLD.build_id,OLD.role,OLD.created_at)
          OR NEW.decision_revision<>OLD.decision_revision+1
          OR target.previous_decision_id IS DISTINCT FROM OLD.decision_id
          OR target.previous_revision IS DISTINCT FROM OLD.decision_revision
          THEN RAISE EXCEPTION 'Authorization pointer must advance to exact successor'; END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION protect_build_assessment_binding() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE plan builds%ROWTYPE; prior build_execution_assessments%ROWTYPE;
      BEGIN
        SELECT * INTO plan FROM builds WHERE id=NEW.build_id AND tenant_id=NEW.tenant_id;
        IF NOT FOUND OR NEW.build_revision<>plan.revision
          OR (NEW.execution_scope->>'quantity')::numeric<>plan.planned_quantity
          OR NEW.execution_scope->>'unit'<>plan.unit OR NEW.execution_scope->>'purpose'<>plan.purpose
          THEN RAISE EXCEPTION 'Assessment must bind the fixed Build'; END IF;
        IF NEW.revision>1 THEN
          SELECT * INTO prior FROM build_execution_assessments WHERE id=NEW.previous_assessment_id
            AND tenant_id=NEW.tenant_id AND product_id=NEW.product_id;
          IF NOT FOUND OR ROW(NEW.owner_id,NEW.visibility,NEW.build_revision)
            IS DISTINCT FROM ROW(prior.owner_id,prior.visibility,prior.build_revision)
            THEN RAISE EXCEPTION 'Assessment owner and fixed Build cannot change'; END IF;
        END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION protect_build_authorization_binding() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE assessment build_execution_assessments%ROWTYPE;
      BEGIN
        SELECT * INTO assessment FROM build_execution_assessments WHERE id=NEW.assessment_id
          AND tenant_id=NEW.tenant_id AND product_id=NEW.product_id;
        IF NOT FOUND OR ROW(NEW.assessment_revision,NEW.assessment_sha256,
            NEW.engineering_configuration_id,NEW.manufacturing_configuration_id)
          IS DISTINCT FROM ROW(assessment.revision,assessment.snapshot_sha256,
            assessment.engineering_configuration_id,assessment.manufacturing_configuration_id)
          THEN RAISE EXCEPTION 'Authorization must bind exact assessment/configuration'; END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION protect_build_start_binding() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE assessment build_execution_assessments%ROWTYPE;
              eng build_authorization_decisions%ROWTYPE; mfg build_authorization_decisions%ROWTYPE;
      BEGIN
        SELECT * INTO assessment FROM build_execution_assessments WHERE id=NEW.assessment_id
          AND tenant_id=NEW.tenant_id AND product_id=NEW.product_id;
        SELECT * INTO eng FROM build_authorization_decisions WHERE id=NEW.engineering_authorization_id
          AND tenant_id=NEW.tenant_id AND product_id=NEW.product_id;
        SELECT * INTO mfg FROM build_authorization_decisions WHERE id=NEW.manufacturing_authorization_id
          AND tenant_id=NEW.tenant_id AND product_id=NEW.product_id;
        IF assessment.id IS NULL OR eng.id IS NULL OR mfg.id IS NULL
          OR NEW.assessment_sha256<>assessment.snapshot_sha256
          OR NEW.build_revision<>assessment.build_revision
          OR NEW.execution_scope IS DISTINCT FROM assessment.execution_scope
          OR eng.assessment_id<>assessment.id OR mfg.assessment_id<>assessment.id
          OR eng.status<>'approved' OR mfg.status<>'approved'
          OR NEW.occurred_at>clock_timestamp()
          OR NEW.occurred_at<eng.created_at OR NEW.occurred_at<mfg.created_at
          OR NEW.occurred_at<(NEW.execution_scope->>'window_start')::timestamptz
          OR NEW.occurred_at>=(NEW.execution_scope->>'window_end')::timestamptz
          OR LEAST(eng.valid_until,mfg.valid_until)<(NEW.execution_scope->>'window_end')::timestamptz
          OR NOT EXISTS (SELECT 1 FROM build_current_execution_assessments p
            WHERE p.tenant_id=NEW.tenant_id AND p.build_id=NEW.build_id AND p.assessment_id=assessment.id)
          OR NOT EXISTS (SELECT 1 FROM build_current_authorizations p
            WHERE p.tenant_id=NEW.tenant_id AND p.build_id=NEW.build_id AND p.role='engineering' AND p.decision_id=eng.id)
          OR NOT EXISTS (SELECT 1 FROM build_current_authorizations p
            WHERE p.tenant_id=NEW.tenant_id AND p.build_id=NEW.build_id AND p.role='manufacturing' AND p.decision_id=mfg.id)
          THEN RAISE EXCEPTION 'Start requires current matching approvals and actual occurrence'; END IF;
        RETURN NEW;
      END $$;
    """)
    pointers = {
        "build_operational_current": "protect_build_operational_pointer",
        "build_current_execution_assessments": "protect_build_assessment_pointer",
        "build_current_authorizations": "protect_build_authorization_pointer",
    }
    inserts = {
        "build_operational_facts": "protect_build_operational_fact",
        "build_execution_assessments": "protect_build_assessment_binding",
        "build_authorization_decisions": "protect_build_authorization_binding",
        "build_starts": "protect_build_start_binding",
    }
    for name in TABLES:
        op.execute(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{name}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_scope ON "{name}" '
            "USING (tenant_id = nullif(current_setting('pdos.tenant_id',true),'')::uuid) "
            "WITH CHECK (tenant_id = nullif(current_setting('pdos.tenant_id',true),'')::uuid)"
        )
        mutable = name in pointers or name == "operational_asset_sentinels"
        permissions = "SELECT, INSERT, UPDATE" if mutable else "SELECT, INSERT"
        op.execute(f'GRANT {permissions} ON "{name}" TO pdos_next_app')
        function = pointers.get(
            name, "protect_operational_asset" if mutable else "protect_next_snapshot"
        )
        actions = "INSERT OR UPDATE OR DELETE" if name in pointers else "UPDATE OR DELETE"
        op.execute(
            f'CREATE TRIGGER retained_record BEFORE {actions} ON "{name}" '
            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
        )
        if name in inserts:
            op.execute(
                f'CREATE TRIGGER fixed_binding BEFORE INSERT ON "{name}" '
                f"FOR EACH ROW EXECUTE FUNCTION {inserts[name]}()"
            )
        if name != "operational_asset_sentinels":
            op.execute(
                f'CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON "{name}" '
                "FOR EACH ROW EXECUTE FUNCTION lifecycle_reference_gate()"
            )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM pdos_agent")


def downgrade():
    for name in reversed(TABLES):
        op.drop_table(name)
    for function in (
        "protect_build_operational_fact",
        "protect_build_operational_pointer",
        "protect_operational_asset",
        "protect_build_assessment_pointer",
        "protect_build_authorization_pointer",
        "protect_build_assessment_binding",
        "protect_build_authorization_binding",
        "protect_build_start_binding",
    ):
        op.execute(f'DROP FUNCTION "{function}"()')
    op.execute(
        "ALTER TABLE professional_authority_facts DROP CONSTRAINT professional_authority_facts_check"
    )
    op.execute("""ALTER TABLE professional_authority_facts ADD CONSTRAINT professional_authority_facts_check
        CHECK (kind IN ('duty','qualification') AND role IN ('engineering','quality')
        AND nature IN ('real','synthetic'))""")
