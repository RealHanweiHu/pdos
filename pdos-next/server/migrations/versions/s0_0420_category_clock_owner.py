# ruff: noqa: E501 -- frozen PostgreSQL definitions preserve their original SQL text
"""Maintain only the derived category source clock under its actual row gate."""

from alembic import op

revision = "s0_0420"
down_revision = "s0_0419"
branch_labels = None
depends_on = None
PREVIOUS_FUNCTION = "CREATE OR REPLACE FUNCTION public.lifecycle_reference_gate()\n RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n      DECLARE payload JSONB; old_payload JSONB; p UUID; t UUID; c UUID;\n      BEGIN\n        IF TG_OP='DELETE' THEN payload=to_jsonb(OLD); ELSE payload=to_jsonb(NEW); END IF;\n        IF TG_OP='UPDATE' THEN\n          old_payload=to_jsonb(OLD);\n          IF ROW(payload->>'product_id',payload->>'tenant_id') IS DISTINCT FROM\n             ROW(old_payload->>'product_id',old_payload->>'tenant_id') THEN\n            RAISE EXCEPTION 'Reference scope cannot be reassigned';\n          END IF;\n        END IF;\n        -- Lifecycle receipts document retention decisions, not consuming business references.\n        IF TG_TABLE_NAME='action_receipts' AND payload->>'operation' LIKE 'evidence.lifecycle.%' THEN\n          IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n        END IF;\n        p=(payload->>'product_id')::uuid; t=(payload->>'tenant_id')::uuid;\n        c=(payload->>'category_id')::uuid;\n        IF p IS NULL THEN\n          PERFORM 1 FROM categories WHERE id=c AND tenant_id=t FOR UPDATE;\n          IF NOT FOUND THEN RAISE EXCEPTION 'Reference category gate unavailable'; END IF;\n          IF TG_OP<>'DELETE' AND EXISTS (\n            SELECT 1 FROM lifecycle_objects o WHERE o.product_id IS NULL AND o.category_id=c AND o.tenant_id=t\n            AND ((o.state->'value'->>'pending_intent_id') IS NOT NULL\n              OR o.state->'value'->>'disposition' IN ('quarantined','unknown','purged'))\n            AND position(o.id::text in payload::text)>0\n          ) THEN RAISE EXCEPTION 'Pending or isolated original prohibits new references'; END IF;\n          UPDATE categories SET lifecycle_epoch=lifecycle_epoch+1 WHERE id=c AND tenant_id=t;\n          IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n        END IF;\n        PERFORM 1 FROM products WHERE id=p AND tenant_id=t FOR UPDATE;\n        IF NOT FOUND THEN RAISE EXCEPTION 'Reference product gate unavailable'; END IF;\n        IF TG_OP<>'DELETE' AND EXISTS (\n          SELECT 1 FROM lifecycle_objects o WHERE o.product_id=p AND o.tenant_id=t\n          AND ((o.state->'value'->>'pending_intent_id') IS NOT NULL\n               OR o.state->'value'->>'disposition' IN ('quarantined','unknown','purged'))\n          AND position(o.id::text in payload::text)>0\n        ) THEN RAISE EXCEPTION 'Pending or isolated original prohibits new references'; END IF;\n        UPDATE products SET lifecycle_epoch=lifecycle_epoch+1 WHERE id=p AND tenant_id=t;\n        IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n      END $function$\n"
FUNCTION = "CREATE OR REPLACE FUNCTION public.lifecycle_reference_gate()\n RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n      DECLARE payload JSONB; old_payload JSONB; p UUID; t UUID; c UUID;\n      BEGIN\n        IF TG_OP='DELETE' THEN payload=to_jsonb(OLD); ELSE payload=to_jsonb(NEW); END IF;\n        IF TG_OP='UPDATE' THEN\n          old_payload=to_jsonb(OLD);\n          IF ROW(payload->>'product_id',payload->>'tenant_id',payload->>'category_id') IS DISTINCT FROM\n             ROW(old_payload->>'product_id',old_payload->>'tenant_id',old_payload->>'category_id') THEN\n            RAISE EXCEPTION 'Reference scope cannot be reassigned';\n          END IF;\n        END IF;\n        -- Lifecycle receipts document retention decisions, not consuming business references.\n        IF TG_TABLE_NAME='action_receipts' AND payload->>'operation' LIKE 'evidence.lifecycle.%' THEN\n          IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n        END IF;\n        p=(payload->>'product_id')::uuid; t=(payload->>'tenant_id')::uuid;\n        c=(payload->>'category_id')::uuid;\n        IF p IS NULL THEN\n          IF TG_OP<>'DELETE' AND EXISTS (\n            SELECT 1 FROM lifecycle_objects o WHERE o.product_id IS NULL AND o.category_id=c AND o.tenant_id=t\n            AND ((o.state->'value'->>'pending_intent_id') IS NOT NULL\n              OR o.state->'value'->>'disposition' IN ('quarantined','unknown','purged'))\n            AND position(o.id::text in payload::text)>0\n          ) THEN RAISE EXCEPTION 'Pending or isolated original prohibits new references'; END IF;\n          IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n        END IF;\n        PERFORM 1 FROM products WHERE id=p AND tenant_id=t FOR UPDATE;\n        IF NOT FOUND THEN RAISE EXCEPTION 'Reference product gate unavailable'; END IF;\n        IF TG_OP<>'DELETE' AND EXISTS (\n          SELECT 1 FROM lifecycle_objects o WHERE o.product_id=p AND o.tenant_id=t\n          AND ((o.state->'value'->>'pending_intent_id') IS NOT NULL\n               OR o.state->'value'->>'disposition' IN ('quarantined','unknown','purged'))\n          AND position(o.id::text in payload::text)>0\n        ) THEN RAISE EXCEPTION 'Pending or isolated original prohibits new references'; END IF;\n        UPDATE products SET lifecycle_epoch=lifecycle_epoch+1 WHERE id=p AND tenant_id=t;\n        IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n      END $function$\n"
CLOCK_FUNCTION = "CREATE FUNCTION public.category_lifecycle_clock() RETURNS trigger\nLANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$\nDECLARE payload jsonb; affected integer;\nBEGIN\n IF TG_OP='DELETE' THEN payload=to_jsonb(OLD); ELSE payload=to_jsonb(NEW); END IF;\n IF TG_TABLE_NAME='action_receipts' AND payload->>'operation' LIKE 'evidence.lifecycle.%' THEN\n  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n END IF;\n UPDATE public.categories SET lifecycle_epoch=lifecycle_epoch+1\n WHERE id=(payload->>'category_id')::uuid AND tenant_id=(payload->>'tenant_id')::uuid;\n GET DIAGNOSTICS affected = ROW_COUNT;\n IF affected<>1 THEN RAISE EXCEPTION 'Reference category gate unavailable' USING ERRCODE='23514'; END IF;\n IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\nEND $$"
TABLES = (
    "action_receipts",
    "artifact_versions",
    "original_scan_requests",
    "original_scan_results",
    "original_security",
    "uploaded_originals",
    "upload_attempts",
)


def upgrade():
    op.execute(CLOCK_FUNCTION)
    op.execute("REVOKE ALL ON FUNCTION public.category_lifecycle_clock() FROM PUBLIC")
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER category_lifecycle_clock_write BEFORE INSERT OR UPDATE ON {table} "
            "FOR EACH ROW WHEN (NEW.product_id IS NULL) "
            "EXECUTE FUNCTION public.category_lifecycle_clock()"
        )
        op.execute(
            f"CREATE TRIGGER category_lifecycle_clock_delete BEFORE DELETE ON {table} "
            "FOR EACH ROW WHEN (OLD.product_id IS NULL) "
            "EXECUTE FUNCTION public.category_lifecycle_clock()"
        )
    op.execute(FUNCTION)


def downgrade():
    op.execute(PREVIOUS_FUNCTION)
    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER category_lifecycle_clock_write ON {table}")
        op.execute(f"DROP TRIGGER category_lifecycle_clock_delete ON {table}")
    op.execute("DROP FUNCTION public.category_lifecycle_clock()")
