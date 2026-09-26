"""Preserve separately sourced targets, estimates, quotes, actuals and exchange rates."""

from alembic import op

revision = "0322_cost_inputs"
down_revision = "0321_notice_discussions"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_cost.cost_inputs (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    record_id UUID NOT NULL,
    version INTEGER NOT NULL,
    kind VARCHAR(24) NOT NULL,
    stage VARCHAR(16),
    source_key VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL,
    payload JSONB NOT NULL,
    snapshot JSONB NOT NULL,
    evidence_id UUID NOT NULL,
    bom_item_id UUID,
    supplier_id UUID,
    reason TEXT NOT NULL,
    created_by_user_id UUID NOT NULL,
    request_id UUID NOT NULL,
    request_digest VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_cost_inputs PRIMARY KEY (id),
    CONSTRAINT fk_cost_inputs_tenant_id_projects FOREIGN KEY(tenant_id, project_id) REFERENCES
cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_cost_inputs_tenant_id_documents FOREIGN KEY(tenant_id, project_id,
evidence_id) REFERENCES cehub_project.documents (tenant_id, project_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_cost_inputs_tenant_id_development_bom_items FOREIGN KEY(tenant_id,
bom_item_id) REFERENCES cehub_product.development_bom_items (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_cost_inputs_tenant_id_suppliers FOREIGN KEY(tenant_id, supplier_id) REFERENCES
cehub_supplier.suppliers (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_cost_inputs_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT uq_cost_input_scope UNIQUE (tenant_id, project_id, id),
    CONSTRAINT uq_cost_input_version UNIQUE (tenant_id, project_id, record_id, version),
    CONSTRAINT uq_cost_input_request UNIQUE (tenant_id, created_by_user_id, request_id),
    CONSTRAINT ck_cost_inputs_state CHECK (version>0 AND status IN ('active','withdrawn') AND
btrim(reason)<>''),
    CONSTRAINT ck_cost_inputs_kind CHECK (((kind='price' AND stage IN
('target','estimate','quote','actual')) OR (kind='exchange_rate' AND stage IS NULL AND
bom_item_id IS NULL AND supplier_id IS NULL)) IS TRUE),
    CONSTRAINT ck_cost_inputs_shape CHECK (source_key ~ '^[0-9a-f]{64}$' AND request_digest ~
'^[0-9a-f]{64}$' AND jsonb_typeof(payload)='object' AND jsonb_typeof(snapshot)='object')
)

;
CREATE INDEX ix_cost_inputs_source ON cehub_cost.cost_inputs (tenant_id, project_id,
source_key);
CREATE INDEX ix_cost_inputs_current ON cehub_cost.cost_inputs (tenant_id, project_id, record_id,
version);
"""

GUARD = """
CREATE FUNCTION cehub_cost.guard_cost_input() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE previous cehub_cost.cost_inputs; p jsonb:=NEW.payload;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id
 FOR UPDATE;
 SELECT * INTO previous FROM cehub_cost.cost_inputs
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND record_id=NEW.record_id
 ORDER BY version DESC LIMIT 1;
 IF NEW.version<>coalesce(previous.version,0)+1 OR
 (previous.id IS NOT NULL AND (previous.source_key<>NEW.source_key OR previous.kind<>NEW.kind
 OR previous.stage IS DISTINCT FROM NEW.stage
 OR previous.payload->'source_reference' IS DISTINCT FROM p->'source_reference'
 OR previous.payload->'source_line' IS DISTINCT FROM p->'source_line')) THEN
 RAISE EXCEPTION 'Cost input revision must retain source identity and stage'; END IF;
 IF EXISTS (SELECT 1 FROM cehub_cost.cost_inputs WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND record_id<>NEW.record_id AND
 (source_key=NEW.source_key OR (kind=NEW.kind AND stage IS NOT DISTINCT FROM NEW.stage
 AND payload->'source_reference'=p->'source_reference'
 AND payload->'source_line'=p->'source_line')))
 THEN RAISE EXCEPTION 'Original cost evidence line already has a record'; END IF;
 IF (p->>'kind'=NEW.kind AND p->>'status'=NEW.status AND p->>'reason'=NEW.reason
 AND p->>'evidence_id'=NEW.evidence_id::text
 AND coalesce(length(btrim(p->>'source_reference')),0)>0
 AND coalesce(length(btrim(p->>'source_line')),0)>0
 AND coalesce(length(btrim(p->>'location')),0)>0
 AND (p->>'as_of')::date <= (clock_timestamp() AT TIME ZONE 'UTC')::date
 AND NEW.snapshot->'command'=p
 AND NEW.snapshot#>>'{sources,document,id}'=NEW.evidence_id::text
 AND (NEW.snapshot->>'previous_version')::integer=NEW.version-1) IS NOT TRUE THEN
 RAISE EXCEPTION 'Cost input requires its actual preview and dated original evidence'; END IF;
 IF NEW.status='withdrawn' AND (previous.id IS NULL OR
 (p-'status'-'reason') IS DISTINCT FROM (previous.payload-'status'-'reason')) THEN
 RAISE EXCEPTION 'Withdrawal preserves the original cost values'; END IF;
 IF NEW.kind='price' THEN
  IF (p->>'stage'=NEW.stage AND p->>'currency' ~ '^[A-Z]{3}$'
  AND (p->>'amount')::numeric>=0 AND (p->>'price_quantity')::numeric>0
  AND p->>'basis' IN ('unit','nre') AND p->>'tax_basis' IN ('inclusive','exclusive','unknown')
  AND p->>'freight_basis' IN ('included','excluded','unknown')
  AND coalesce(length(btrim(p->>'scope_basis')),0)>0
  AND p->>'bom_item_id' IS NOT DISTINCT FROM NEW.bom_item_id::text
  AND p->>'supplier_id' IS NOT DISTINCT FROM NEW.supplier_id::text) IS NOT TRUE THEN
  RAISE EXCEPTION 'Price must retain quantity, currency, scope and tax/freight basis'; END IF;
  IF p->>'basis'='nre' AND
    ((p->>'price_quantity')::numeric<>1 OR p->>'unit'<>'项') THEN
    RAISE EXCEPTION 'NRE records keep their whole-charge amount'; END IF;
  IF p->>'category'='material' AND p->>'basis'='unit' AND NEW.stage<>'target'
   AND NEW.bom_item_id IS NULL THEN RAISE EXCEPTION 'Material price requires Cost BOM item'; END IF;
  IF NEW.bom_item_id IS NOT NULL AND NOT EXISTS (
   SELECT 1 FROM cehub_product.development_bom_items i JOIN cehub_product.development_boms b
   ON b.tenant_id=i.tenant_id AND b.id=i.bom_id
   WHERE i.tenant_id=NEW.tenant_id AND i.project_id=NEW.project_id AND i.id=NEW.bom_item_id
   AND b.bom_type='cost' AND b.project_id=NEW.project_id
   AND (p->>'basis'='nre' OR i.unit=p->>'unit')
  ) AND NEW.status<>'withdrawn' THEN
   RAISE EXCEPTION 'Price requires current project Cost BOM'; END IF;
  IF NEW.stage='actual' AND (p->>'actual_source'='erp_snapshot'
    AND (p->>'actual_quantity')::numeric>0
    AND (p->>'basis'<>'nre' OR (p->>'actual_quantity')::numeric=1)
    AND (p->>'basis'<>'unit' OR (p->>'actual_quantity')::numeric=
         (p->>'price_quantity')::numeric)) IS NOT TRUE THEN
    RAISE EXCEPTION 'Actual cost requires ERP evidence and quantity'; END IF;
  IF NEW.stage<>'actual' AND (p->>'actual_source' IS NOT NULL OR
     p->>'actual_quantity' IS NOT NULL) THEN
     RAISE EXCEPTION 'Targets estimates and quotes are not actual costs'; END IF;
  IF NEW.stage='quote' AND (NEW.supplier_id IS NOT NULL
    AND (p->>'valid_until')::date >= (p->>'valid_from')::date
    AND (p->>'minimum_order_quantity')::numeric>0
    AND (p->>'maximum_order_quantity' IS NULL OR
       (p->>'maximum_order_quantity')::numeric >= (p->>'minimum_order_quantity')::numeric))
    IS NOT TRUE THEN RAISE EXCEPTION 'Quote requires supplier, validity and quantity range'; END IF;
 ELSE
  IF (p->>'from_currency' ~ '^[A-Z]{3}$' AND p->>'to_currency' ~ '^[A-Z]{3}$'
    AND p->>'from_currency'<>p->>'to_currency' AND (p->>'rate')::numeric>0
    AND p->>'rate_type' IN ('spot','budget','erp_actual')) IS NOT TRUE THEN
    RAISE EXCEPTION 'Exchange rate requires explicit direction, date and policy'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER cost_input_guard BEFORE INSERT ON cehub_cost.cost_inputs
FOR EACH ROW EXECUTE FUNCTION cehub_cost.guard_cost_input();
CREATE TRIGGER cost_input_immutable BEFORE UPDATE OR DELETE ON cehub_cost.cost_inputs
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
REVOKE ALL ON cehub_cost.cost_inputs FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_cost.guard_cost_input() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM cehub_cost.cost_inputs) THEN
      RAISE EXCEPTION 'Retain cost source history'; END IF;
    END $$;
    DROP TABLE cehub_cost.cost_inputs;
    DROP FUNCTION cehub_cost.guard_cost_input();
    """)
