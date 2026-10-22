"""Bind professional authority, fixed verification requests and tentative windows."""

from alembic import op

from migrations.schema_0013 import SCHEMA_SQL, TABLES

revision = "next_0013"
down_revision = "next_0012"
branch_labels = None
depends_on = None


def upgrade():
    for statement in SCHEMA_SQL:
        op.execute(statement)
    op.execute("""
      CREATE FUNCTION protect_professional_fact_binding() RETURNS trigger
      LANGUAGE plpgsql AS $$
      DECLARE old_fact professional_authority_facts%ROWTYPE;
      BEGIN
        IF NEW.revision > 1 THEN
          SELECT * INTO old_fact FROM professional_authority_facts
            WHERE id=NEW.previous_id AND tenant_id=NEW.tenant_id
              AND product_id=NEW.product_id;
          IF NOT FOUND OR ROW(NEW.project_id,NEW.subject_id,NEW.kind,NEW.series_id,
              NEW.owner_id,NEW.visibility,NEW.role,NEW.nature,NEW.issuer_key,
              NEW.external_id,NEW.operations,NEW.purposes,NEW.previous_revision)
            IS DISTINCT FROM ROW(old_fact.project_id,old_fact.subject_id,old_fact.kind,
              old_fact.series_id,old_fact.owner_id,old_fact.visibility,old_fact.role,
              old_fact.nature,old_fact.issuer_key,old_fact.external_id,
              old_fact.operations,old_fact.purposes,old_fact.revision) THEN
            RAISE EXCEPTION 'Professional fact identity and scope cannot be rebound';
          END IF;
        END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION protect_professional_pointer() RETURNS trigger
      LANGUAGE plpgsql AS $$
      DECLARE target professional_authority_facts%ROWTYPE;
      BEGIN
        IF TG_OP='DELETE' THEN
          RAISE EXCEPTION 'Professional authority history is retained';
        END IF;
        SELECT * INTO target FROM professional_authority_facts WHERE id=NEW.fact_id
          AND tenant_id=NEW.tenant_id AND product_id=NEW.product_id;
        IF NOT FOUND OR ROW(NEW.project_id,NEW.subject_id,NEW.kind,NEW.series_id,
            NEW.issuer_key,NEW.external_id,NEW.fact_revision)
          IS DISTINCT FROM ROW(target.project_id,target.subject_id,target.kind,
            target.series_id,target.issuer_key,target.external_id,target.revision) THEN
          RAISE EXCEPTION 'Authority pointer must bind its exact fact';
        END IF;
        IF TG_OP='INSERT' THEN
          IF NEW.epoch<>1 OR NEW.fact_revision<>1 OR target.previous_id IS NOT NULL THEN
            RAISE EXCEPTION 'Authority pointer must begin at the first version';
          END IF;
        ELSIF ROW(NEW.id,NEW.tenant_id,NEW.product_id,NEW.project_id,NEW.subject_id,
            NEW.kind,NEW.issuer_key,NEW.external_id,NEW.series_id,NEW.created_at)
          IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.product_id,OLD.project_id,
            OLD.subject_id,OLD.kind,OLD.issuer_key,OLD.external_id,OLD.series_id,OLD.created_at)
          OR NEW.epoch<>OLD.epoch+1 OR NEW.fact_revision<>OLD.fact_revision+1
          OR target.previous_id IS DISTINCT FROM OLD.fact_id
          OR target.previous_revision IS DISTINCT FROM OLD.fact_revision THEN
          RAISE EXCEPTION 'Authority pointer and epoch must advance to the exact successor';
        END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION protect_formal_verification_binding() RETURNS trigger
      LANGUAGE plpgsql AS $$
      DECLARE prep verification_preparations%ROWTYPE;
              previous verification_formal_requests%ROWTYPE;
      BEGIN
        SELECT * INTO prep FROM verification_preparations WHERE id=NEW.preparation_id
          AND tenant_id=NEW.tenant_id AND product_id=NEW.product_id;
        IF NOT FOUND OR ROW(NEW.project_id,NEW.build_id,NEW.build_revision,
            NEW.preparation_revision,NEW.preparation_sha256)
          IS DISTINCT FROM ROW(prep.project_id,prep.build_id,prep.build_revision,
            prep.revision,prep.snapshot_sha256) THEN
          RAISE EXCEPTION 'Formal request must bind the exact preparation';
        END IF;
        IF ROW(NEW.request_snapshot->>'id',NEW.request_snapshot->>'revision',
            NEW.request_snapshot->'scope'->>'tenant_id',
            NEW.request_snapshot->'scope'->>'product_id',
            NEW.request_snapshot->'scope'->>'project_id')
          IS DISTINCT FROM ROW(NEW.request_id::text,NEW.revision::text,
            NEW.tenant_id::text,NEW.product_id::text,NEW.project_id::text)
          OR NEW.request_snapshot->'build' IS DISTINCT FROM prep.request_snapshot->'build'
          OR jsonb_typeof(NEW.request_snapshot->'timeline'->'request_created')
            IS DISTINCT FROM 'object' THEN
          RAISE EXCEPTION 'Formal request snapshot must preserve exact identity and configuration';
        END IF;
        IF NEW.revision=1 THEN
          IF NEW.operation<>'verification.request.create' THEN
            RAISE EXCEPTION 'First formal request requires creation';
          END IF;
        ELSE
          SELECT * INTO previous FROM verification_formal_requests
            WHERE id=NEW.previous_request_id AND tenant_id=NEW.tenant_id
              AND product_id=NEW.product_id;
          IF NOT FOUND OR ROW(NEW.project_id,NEW.build_id,NEW.build_revision,
              NEW.request_id,NEW.owner_id,NEW.visibility,NEW.preparation_id,
              NEW.preparation_revision,NEW.preparation_sha256,NEW.purpose,NEW.previous_revision)
            IS DISTINCT FROM ROW(previous.project_id,previous.build_id,previous.build_revision,
              previous.request_id,previous.owner_id,previous.visibility,previous.preparation_id,
              previous.preparation_revision,previous.preparation_sha256,
              previous.purpose,previous.revision)
            OR NEW.request_snapshot->'timeline'->'request_created' IS DISTINCT FROM
              previous.request_snapshot->'timeline'->'request_created'
            OR NEW.operation='verification.request.create' THEN
            RAISE EXCEPTION 'Formal request successor must retain its fixed history';
          END IF;
        END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION protect_formal_verification_pointer() RETURNS trigger
      LANGUAGE plpgsql AS $$
      DECLARE target verification_formal_requests%ROWTYPE;
      BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Formal request history is retained'; END IF;
        SELECT * INTO target FROM verification_formal_requests
          WHERE id=NEW.request_version_id AND tenant_id=NEW.tenant_id
            AND product_id=NEW.product_id AND request_id=NEW.request_id;
        IF NOT FOUND OR target.revision<>NEW.request_revision THEN
          RAISE EXCEPTION 'Formal pointer must identify its exact request';
        END IF;
        IF TG_OP='INSERT' THEN
          IF NEW.request_revision<>1 OR target.previous_request_id IS NOT NULL THEN
            RAISE EXCEPTION 'Formal pointer must begin at first version';
          END IF;
        ELSIF ROW(NEW.id,NEW.tenant_id,NEW.product_id,NEW.request_id,NEW.created_at)
          IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.product_id,OLD.request_id,OLD.created_at)
          OR NEW.request_revision<>OLD.request_revision+1
          OR target.previous_request_id IS DISTINCT FROM OLD.request_version_id
          OR target.previous_revision IS DISTINCT FROM OLD.request_revision THEN
          RAISE EXCEPTION 'Formal pointer must advance to exact successor';
        END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION protect_method_applicability_binding() RETURNS trigger
      LANGUAGE plpgsql AS $$
      DECLARE parent verification_formal_requests%ROWTYPE; item JSONB;
      BEGIN
        SELECT * INTO parent FROM verification_formal_requests
          WHERE id=NEW.request_version_id AND tenant_id=NEW.tenant_id
            AND product_id=NEW.product_id;
        IF NOT FOUND THEN RAISE EXCEPTION 'Reviewed request is unavailable'; END IF;
        SELECT v INTO item FROM jsonb_array_elements(parent.request_snapshot->'items') v
          WHERE v->>'id'=NEW.item_id;
        IF item IS NULL OR NEW.method_ref IS DISTINCT FROM item->'method'
          OR ROW(NEW.engineering_configuration_id::text,
              NEW.engineering_configuration_revision::text,
              NEW.manufacturing_configuration_id::text,
              NEW.manufacturing_configuration_revision::text)
            IS DISTINCT FROM ROW(
              parent.request_snapshot->'build'->'engineering_configuration'->>'id',
              parent.request_snapshot->'build'->'engineering_configuration'->>'revision',
              parent.request_snapshot->'build'->'manufacturing_configuration'->>'id',
              parent.request_snapshot->'build'->'manufacturing_configuration'->>'revision') THEN
          RAISE EXCEPTION 'Method assessment must retain its item and planned configuration';
        END IF;
        RETURN NEW;
      END $$;
    """)
    pointers = {
        "professional_authority_current": "protect_professional_pointer",
        "verification_current_formal_requests": "protect_formal_verification_pointer",
    }
    inserts = {
        "professional_authority_facts": "protect_professional_fact_binding",
        "verification_formal_requests": "protect_formal_verification_binding",
        "verification_method_applicabilities": "protect_method_applicability_binding",
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
            f'CREATE TRIGGER retained_record BEFORE {actions} ON "{name}" '
            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
        )
        if name in inserts:
            op.execute(
                f'CREATE TRIGGER fixed_binding BEFORE INSERT ON "{name}" '
                f"FOR EACH ROW EXECUTE FUNCTION {inserts[name]}()"
            )
        op.execute(
            f"CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE "
            f'ON "{name}" FOR EACH ROW EXECUTE FUNCTION lifecycle_reference_gate()'
        )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM pdos_agent")


def downgrade():
    for name in reversed(TABLES):
        op.drop_table(name)
    for function in (
        "protect_professional_fact_binding",
        "protect_professional_pointer",
        "protect_formal_verification_binding",
        "protect_formal_verification_pointer",
        "protect_method_applicability_binding",
    ):
        op.execute(f'DROP FUNCTION "{function}"()')
