"""Fence complete dependency enumeration without counting a Change's own receipts."""

from alembic import op
from sqlalchemy import text

revision = "next_0030"
down_revision = "next_0029"
branch_labels = None
depends_on = None

# Frozen actual owner/source/Current ledgers. Graph captures, Change successors,
# approvals, selections and common confirmation/receipt tails are deliberately
# outside this clock; their current proofs are rechecked by their domain owners.
DEPENDENCY_TABLES = (
    "artifact_versions",
    "uploaded_originals",
    "original_security",
    "original_scan_requests",
    "original_scan_results",
    "lifecycle_objects",
    "lifecycle_candidates",
    "lifecycle_intents",
    "lifecycle_requests",
    "projects",
    "project_product_links",
    "definition_revisions",
    "definition_specs",
    "definition_sources",
    "parts",
    "bom_revisions",
    "bom_lines",
    "engineering_configurations",
    "process_revisions",
    "actual_configurations",
    "build_authorization_decisions",
    "build_current_authorizations",
    "build_current_execution_assessments",
    "build_execution_assessments",
    "build_lots",
    "build_operational_current",
    "build_operational_facts",
    "build_readiness",
    "build_starts",
    "builds",
    "operational_asset_sentinels",
    "operational_material_holds",
    "operational_resource_occupancies",
    "professional_authority_current",
    "professional_authority_facts",
    "quality_current_issues",
    "quality_current_policies",
    "quality_event_failure_links",
    "quality_failure_maps",
    "quality_issue_versions",
    "quality_policy_facts",
    "sample_allocations",
    "sample_current_readiness",
    "sample_readiness_facts",
    "sample_run_usages",
    "sample_units",
    "sample_usage_sentinels",
    "test_measurements",
    "test_resource_current",
    "test_resource_facts",
    "test_resource_reservations",
    "test_result_actions",
    "test_result_projections",
    "verification_actual_method_applicabilities",
    "verification_actual_method_batches",
    "verification_current_actual_methods",
    "verification_current_formal_requests",
    "verification_current_preparations",
    "verification_current_runs",
    "verification_formal_requests",
    "verification_handoff_facts",
    "verification_launch_facts",
    "verification_method_applicabilities",
    "verification_preparations",
    "verification_run_identities",
    "verification_run_versions",
    "verification_window_proposals",
    "manufacturing_preparation_versions",
    "manufacturing_preparation_currents",
    "manufacturing_baseline_document_links",
)

CLOCK_SQL = """
CREATE TABLE change_dependency_clocks (
 product_id uuid NOT NULL, epoch bigint NOT NULL,
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, created_at timestamptz NOT NULL,
 UNIQUE(tenant_id,product_id),
 FOREIGN KEY(tenant_id,product_id) REFERENCES products(tenant_id,id),
 CONSTRAINT change_dependency_epoch_positive CHECK(epoch>0)
);
CREATE INDEX ix_change_dependency_clocks_tenant_id ON change_dependency_clocks(tenant_id);
INSERT INTO change_dependency_clocks(product_id,epoch,id,tenant_id,created_at)
 SELECT id,1,id,tenant_id,created_at FROM products;
ALTER TABLE change_dependency_clocks ENABLE ROW LEVEL SECURITY;
ALTER TABLE change_dependency_clocks FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON change_dependency_clocks
 USING(tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid)
 WITH CHECK(tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid);
REVOKE ALL ON change_dependency_clocks FROM PUBLIC,pdos_next_app,pdos_next_auth,pdos_agent;
GRANT SELECT ON change_dependency_clocks TO pdos_next_app;

CREATE FUNCTION protect_change_dependency_clock() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 IF pg_trigger_depth()<2 OR TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Dependency clock is maintained only by actual owner triggers';
 END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.epoch<>1 OR NEW.id<>NEW.product_id THEN
   RAISE EXCEPTION 'Dependency clock must start at its product identity'; END IF;
  RETURN NEW;
 END IF;
 IF (to_jsonb(NEW)-'epoch') IS DISTINCT FROM (to_jsonb(OLD)-'epoch')
  OR NEW.epoch<>OLD.epoch+1 THEN
  RAISE EXCEPTION 'Dependency clock scope is fixed and epoch is monotonic'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER exact_dependency_clock BEFORE INSERT OR UPDATE OR DELETE
 ON change_dependency_clocks FOR EACH ROW EXECUTE FUNCTION protect_change_dependency_clock();

CREATE FUNCTION initialize_change_dependency_clock() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 INSERT INTO public.change_dependency_clocks(product_id,epoch,id,tenant_id,created_at)
  VALUES(NEW.id,1,NEW.id,NEW.tenant_id,NEW.created_at);
 RETURN NULL;
END $$;
CREATE TRIGGER initialize_change_dependencies AFTER INSERT ON products
 FOR EACH ROW EXECUTE FUNCTION initialize_change_dependency_clock();

CREATE FUNCTION advance_product_change_dependencies() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF ROW(NEW.id,NEW.tenant_id,NEW.created_at) IS DISTINCT FROM
  ROW(OLD.id,OLD.tenant_id,OLD.created_at) THEN
  RAISE EXCEPTION 'Dependency product identity is fixed'; END IF;
 IF (to_jsonb(NEW)-'lifecycle_epoch') IS DISTINCT FROM
  (to_jsonb(OLD)-'lifecycle_epoch') THEN
  UPDATE public.change_dependency_clocks SET epoch=epoch+1
   WHERE tenant_id=NEW.tenant_id AND product_id=NEW.id;
  IF NOT FOUND THEN RAISE EXCEPTION 'Product dependency clock is missing'; END IF;
 END IF;
 RETURN NULL;
END $$;
CREATE TRIGGER change_product_dependencies AFTER UPDATE ON products
 FOR EACH ROW EXECUTE FUNCTION advance_product_change_dependencies();

CREATE FUNCTION advance_change_dependency_clock() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE v jsonb; t uuid; p uuid;
BEGIN
 IF TG_OP='DELETE' THEN v=to_jsonb(OLD); ELSE v=to_jsonb(NEW); END IF;
 t=(v->>'tenant_id')::uuid; p=(v->>'product_id')::uuid;
 IF TG_TABLE_NAME='operational_asset_sentinels' THEN
  -- Shared physical assets have no product_id. Conservatively fence every
  -- product of their actual tenant, including references not yet consumed.
  -- Only clock rows are locked here: taking other Product locks after a
  -- command's own Product would invert the existing common lock order.
  IF t IS NULL THEN RAISE EXCEPTION 'Shared dependency tenant is missing'; END IF;
  FOR p IN SELECT product_id FROM public.change_dependency_clocks
   WHERE tenant_id=t ORDER BY product_id LOOP
   UPDATE public.change_dependency_clocks SET epoch=epoch+1
    WHERE tenant_id=t AND product_id=p;
  END LOOP;
  RETURN NULL;
 END IF;
 IF TG_OP='UPDATE' AND ROW(t,p) IS DISTINCT FROM
  ROW((to_jsonb(OLD)->>'tenant_id')::uuid,(to_jsonb(OLD)->>'product_id')::uuid) THEN
  RAISE EXCEPTION 'Dependency scope cannot be reassigned'; END IF;
 PERFORM 1 FROM public.products WHERE tenant_id=t AND id=p FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Actual dependency Product is missing'; END IF;
 UPDATE public.change_dependency_clocks SET epoch=epoch+1
  WHERE tenant_id=t AND product_id=p;
 IF NOT FOUND THEN RAISE EXCEPTION 'Actual product dependency clock is missing'; END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION lock_change_dependency_clock(t uuid,p uuid) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE result bigint;
BEGIN
 IF t IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid THEN
  RAISE EXCEPTION 'Dependency fence is outside the actual tenant'; END IF;
 SELECT epoch INTO STRICT result FROM public.change_dependency_clocks
  WHERE tenant_id=t AND product_id=p FOR SHARE;
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION protect_change_dependency_clock() FROM PUBLIC,pdos_next_app,pdos_agent;
REVOKE ALL ON FUNCTION initialize_change_dependency_clock() FROM PUBLIC,pdos_next_app,pdos_agent;
REVOKE ALL ON FUNCTION advance_product_change_dependencies() FROM PUBLIC,pdos_next_app,pdos_agent;
REVOKE ALL ON FUNCTION advance_change_dependency_clock() FROM PUBLIC,pdos_next_app,pdos_agent;
REVOKE ALL ON FUNCTION lock_change_dependency_clock(uuid,uuid)
 FROM PUBLIC,pdos_next_app,pdos_next_auth,pdos_agent;
GRANT EXECUTE ON FUNCTION lock_change_dependency_clock(uuid,uuid) TO pdos_next_app;
"""


def upgrade():
    op.execute("LOCK TABLE products IN SHARE ROW EXCLUSIVE MODE")
    if op.get_bind().scalar(text("SELECT version_num FROM alembic_version")) != down_revision:
        raise RuntimeError("Dependency watermark requires the actual head29")
    op.execute(CLOCK_SQL)
    for table in DEPENDENCY_TABLES:
        op.execute(
            f'CREATE TRIGGER change_dependencies AFTER INSERT OR UPDATE OR DELETE ON "{table}" '
            "FOR EACH ROW EXECUTE FUNCTION advance_change_dependency_clock()"
        )


def downgrade():
    op.execute("LOCK TABLE products,change_graph_captures IN SHARE ROW EXCLUSIVE MODE")
    used = op.get_bind().scalar(
        text("SELECT EXISTS(SELECT 1 FROM change_graph_captures WHERE source_basis ? 'closure')")
    )
    if used:
        raise RuntimeError("Saved dependency closure proof prevents destructive downgrade")
    for table in reversed(DEPENDENCY_TABLES):
        op.execute(f'DROP TRIGGER change_dependencies ON "{table}"')
    op.execute("DROP TRIGGER initialize_change_dependencies ON products")
    op.execute("DROP TRIGGER change_product_dependencies ON products")
    op.execute("DROP FUNCTION advance_change_dependency_clock()")
    op.execute("DROP FUNCTION lock_change_dependency_clock(uuid,uuid)")
    op.execute("DROP FUNCTION initialize_change_dependency_clock()")
    op.execute("DROP FUNCTION advance_product_change_dependencies()")
    op.execute("DROP TABLE change_dependency_clocks")
    op.execute("DROP FUNCTION protect_change_dependency_clock()")
