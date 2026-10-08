"""Fence all reviewed product writers and persist reversible original decisions."""
# ruff: noqa: E501

from alembic import op

from migrations.schema_0011 import GUARDED, SCHEMA_SQL, TABLES

revision = "next_0011"
down_revision = "next_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE products ADD COLUMN lifecycle_epoch INTEGER NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE products ALTER COLUMN lifecycle_epoch DROP DEFAULT")
    for statement in SCHEMA_SQL:
        op.execute(statement)
    op.execute("CREATE UNIQUE INDEX lifecycle_candidate_once ON lifecycle_intents "
               "(tenant_id, ((document->'value'->>'candidate_id')))")
    op.execute("""
      CREATE FUNCTION lifecycle_product_epoch() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN NEW.lifecycle_epoch = OLD.lifecycle_epoch + 1; RETURN NEW; END $$;
      CREATE TRIGGER lifecycle_epoch BEFORE UPDATE ON products
        FOR EACH ROW EXECUTE FUNCTION lifecycle_product_epoch();
      CREATE FUNCTION lifecycle_reference_gate() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE payload JSONB; old_payload JSONB; p UUID; t UUID;
      BEGIN
        IF TG_OP='DELETE' THEN payload=to_jsonb(OLD); ELSE payload=to_jsonb(NEW); END IF;
        IF TG_OP='UPDATE' THEN
          old_payload=to_jsonb(OLD);
          IF ROW(payload->>'product_id',payload->>'tenant_id') IS DISTINCT FROM
             ROW(old_payload->>'product_id',old_payload->>'tenant_id') THEN
            RAISE EXCEPTION 'Reference scope cannot be reassigned';
          END IF;
        END IF;
        -- Lifecycle receipts document retention decisions, not consuming business references.
        IF TG_TABLE_NAME='action_receipts' AND payload->>'operation' LIKE 'evidence.lifecycle.%' THEN
          IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
        END IF;
        p=(payload->>'product_id')::uuid; t=(payload->>'tenant_id')::uuid;
        PERFORM 1 FROM products WHERE id=p AND tenant_id=t FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'Reference product gate unavailable'; END IF;
        IF TG_OP<>'DELETE' AND EXISTS (
          SELECT 1 FROM lifecycle_objects o WHERE o.product_id=p AND o.tenant_id=t
          AND ((o.state->'value'->>'pending_intent_id') IS NOT NULL
               OR o.state->'value'->>'disposition' IN ('quarantined','unknown','purged'))
          AND position(o.id::text in payload::text)>0
        ) THEN RAISE EXCEPTION 'Pending or isolated original prohibits new references'; END IF;
        UPDATE products SET lifecycle_epoch=lifecycle_epoch+1 WHERE id=p AND tenant_id=t;
        IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
      END $$;
    """)
    for name in (*GUARDED, "upload_attempts"):
        op.execute(f'CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON "{name}" '
                   'FOR EACH ROW EXECUTE FUNCTION lifecycle_reference_gate()')
    op.execute("""
      CREATE FUNCTION protect_lifecycle_record() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Lifecycle history is retained'; END IF;
        IF ROW(NEW.id,NEW.tenant_id,NEW.product_id,NEW.created_at) IS DISTINCT FROM
           ROW(OLD.id,OLD.tenant_id,OLD.product_id,OLD.created_at)
           OR NEW.revision<>OLD.revision+1 THEN
          RAISE EXCEPTION 'Lifecycle identity and monotonic revision required';
        END IF;
        IF TG_TABLE_NAME='lifecycle_objects' THEN
          IF ROW(NEW.owner_id,NEW.reference) IS DISTINCT FROM ROW(OLD.owner_id,OLD.reference) THEN
            RAISE EXCEPTION 'Exact original binding cannot change'; END IF;
          IF ROW(NEW.manual_hold,NEW.retention_until) IS DISTINCT FROM ROW(OLD.manual_hold,OLD.retention_until)
             AND NEW.protection_revision<>OLD.protection_revision+1 THEN
            RAISE EXCEPTION 'Retention protection must advance'; END IF;
          IF NEW.protection_revision<OLD.protection_revision OR
             NEW.protection_revision>OLD.protection_revision+1 THEN
            RAISE EXCEPTION 'Invalid protection revision'; END IF;
        ELSIF TG_TABLE_NAME='upload_attempts' THEN
          IF ROW(NEW.owner_id,NEW.reference,NEW.request_key,NEW.request_digest,NEW.title,NEW.filename)
             IS DISTINCT FROM ROW(OLD.owner_id,OLD.reference,OLD.request_key,OLD.request_digest,OLD.title,OLD.filename)
             OR OLD.status<>'reserved' OR NEW.status NOT IN ('committed','abandoned') THEN
            RAISE EXCEPTION 'Upload terminal evidence cannot be reversed'; END IF;
          IF NEW.status='abandoned' AND EXISTS(SELECT 1 FROM uploaded_originals
                 WHERE id=NEW.id AND tenant_id=NEW.tenant_id) THEN
            RAISE EXCEPTION 'Registered original cannot be abandoned'; END IF;
        ELSIF TG_TABLE_NAME='lifecycle_intents' THEN
          IF ROW(NEW.object_id,NEW.actor_id,NEW.intent_digest,NEW.reason) IS DISTINCT FROM
             ROW(OLD.object_id,OLD.actor_id,OLD.intent_digest,OLD.reason) THEN
            RAISE EXCEPTION 'Named decision binding cannot change'; END IF;
        END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION protect_upload_registration() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF EXISTS (SELECT 1 FROM upload_attempts a WHERE a.id=NEW.id
          AND a.tenant_id=NEW.tenant_id AND (a.product_id<>NEW.product_id OR a.status<>'reserved'))
          THEN RAISE EXCEPTION 'Closed upload cannot register late'; END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER upload_registration BEFORE INSERT ON uploaded_originals
        FOR EACH ROW EXECUTE FUNCTION protect_upload_registration();
    """)
    for name in TABLES:
        op.execute(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{name}" FORCE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY tenant_scope ON "{name}" '
                   "USING (tenant_id = nullif(current_setting('pdos.tenant_id', true), '')::uuid) "
                   "WITH CHECK (tenant_id = nullif(current_setting('pdos.tenant_id', true), '')::uuid)")
        immutable = name in {"lifecycle_candidates", "lifecycle_requests"}
        grants = "SELECT, INSERT" if immutable else "SELECT, INSERT, UPDATE"
        op.execute(f'GRANT {grants} ON "{name}" TO pdos_next_app')
        function = "protect_next_snapshot" if immutable else "protect_lifecycle_record"
        op.execute(f'CREATE TRIGGER retained_record BEFORE UPDATE OR DELETE ON "{name}" '
                   f'FOR EACH ROW EXECUTE FUNCTION {function}()')
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM pdos_agent")


def downgrade():
    op.execute("DROP TRIGGER upload_registration ON uploaded_originals")
    op.execute("DROP FUNCTION protect_upload_registration()")
    for name in (*GUARDED, "upload_attempts"):
        op.execute(f'DROP TRIGGER lifecycle_reference ON "{name}"')
    op.execute("DROP FUNCTION lifecycle_reference_gate()")
    op.execute("DROP TRIGGER lifecycle_epoch ON products")
    op.execute("DROP FUNCTION lifecycle_product_epoch()")
    for name in reversed(TABLES):
        op.drop_table(name)
    op.execute("DROP FUNCTION protect_lifecycle_record()")
    op.drop_column("products", "lifecycle_epoch")
