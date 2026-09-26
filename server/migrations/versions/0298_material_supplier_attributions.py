"""Human supplier attribution to exact immutable supply source versions."""

from alembic import op

revision = "0298_material_supplier_attributions"
down_revision = "0297_material_admission"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_supplier.material_supplier_attributions (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
supply_snapshot_id UUID NOT NULL,
version INTEGER NOT NULL,
supplier_id UUID,
evidence_id UUID NOT NULL,
snapshot JSONB NOT NULL,
reason TEXT NOT NULL,
created_by_user_id UUID NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
CONSTRAINT pk_material_supplier_attributions PRIMARY KEY (id),
CONSTRAINT fk_material_supplier_attributions_tenant_id_supply_snapshots FOREIGN KEY(tenant_id,
project_id, supply_snapshot_id) REFERENCES cehub_supplier.supply_snapshots (tenant_id,
project_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_material_supplier_attributions_tenant_id_suppliers FOREIGN KEY(tenant_id,
supplier_id) REFERENCES cehub_supplier.suppliers (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_material_supplier_attributions_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_material_supplier_attributions_tenant_id_documents FOREIGN KEY(tenant_id,
project_id, evidence_id) REFERENCES cehub_project.documents (tenant_id, project_id, id) ON
DELETE RESTRICT,
CONSTRAINT uq_material_supplier_version UNIQUE (tenant_id, supply_snapshot_id, version),
CONSTRAINT uq_material_supplier_request UNIQUE (tenant_id, created_by_user_id, request_id),
CONSTRAINT ck_material_supplier_attributions_attribution_valid CHECK (version>0 AND
btrim(reason)<>'' AND jsonb_typeof(snapshot)='object' AND request_digest ~ '^[0-9a-f]{64}$')
)

;
"""

GUARD = """
CREATE FUNCTION cehub_supplier.material_supplier_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source cehub_supplier.supply_snapshots%ROWTYPE;
batch cehub_supplier.supply_import_batches%ROWTYPE; latest integer; old_supplier uuid;
BEGIN
PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR
UPDATE;
SELECT * INTO STRICT source FROM cehub_supplier.supply_snapshots WHERE
id=NEW.supply_snapshot_id;
SELECT * INTO STRICT batch FROM cehub_supplier.supply_import_batches WHERE id=source.batch_id;
PERFORM pg_advisory_xact_lock(hashtextextended(jsonb_build_array(NEW.tenant_id::text,
batch.source_system,source.external_pool_id,source.external_item_id)::text,0));
SELECT coalesce(max(version),0) INTO latest FROM cehub_supplier.material_supplier_attributions
WHERE tenant_id=NEW.tenant_id AND supply_snapshot_id=NEW.supply_snapshot_id;
SELECT supplier_id INTO old_supplier FROM cehub_supplier.material_supplier_attributions
WHERE tenant_id=NEW.tenant_id AND supply_snapshot_id=NEW.supply_snapshot_id AND version=latest;
IF source.tenant_id<>NEW.tenant_id OR source.project_id<>NEW.project_id OR NEW.version<>latest+1
OR (NEW.supplier_id IS NULL AND old_supplier IS NULL)
OR NEW.snapshot#>>'{original,source,id}' IS DISTINCT FROM source.id::text
OR NEW.snapshot#>>'{evidence,id}' IS DISTINCT FROM NEW.evidence_id::text
OR NEW.snapshot#>>'{supplier,id}' IS DISTINCT FROM NEW.supplier_id::text THEN
RAISE EXCEPTION 'Supplier attribution requires consecutive scoped source and evidence'; END IF;
IF NEW.supplier_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM cehub_supplier.suppliers
WHERE tenant_id=NEW.tenant_id AND id=NEW.supplier_id AND status='active') THEN
RAISE EXCEPTION 'Supplier attribution requires an active actual supplier'; END IF;
IF EXISTS (SELECT 1 FROM cehub_supplier.supply_snapshots s JOIN
cehub_supplier.supply_import_batches b
ON b.tenant_id=s.tenant_id AND b.id=s.batch_id WHERE s.tenant_id=NEW.tenant_id
AND b.source_system=batch.source_system AND s.external_pool_id=source.external_pool_id
AND s.external_item_id=source.external_item_id
AND (b.as_of,b.captured_at,s.id)>(batch.as_of,batch.captured_at,source.id)) THEN
RAISE EXCEPTION 'New supplier attribution must refer to the current supply source version'; END
IF;
IF NOT EXISTS (SELECT 1 FROM cehub_project.documents WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=NEW.evidence_id
AND sha256=NEW.snapshot#>>'{evidence,sha256}'
AND size_bytes=(NEW.snapshot#>>'{evidence,size_bytes}')::bigint) THEN
RAISE EXCEPTION 'Supplier evidence original must match its fixed hash and size'; END IF;
RETURN NEW;
END $$;
CREATE TRIGGER material_supplier_insert BEFORE INSERT ON
cehub_supplier.material_supplier_attributions
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_supplier_guard();
CREATE TRIGGER material_supplier_immutable BEFORE UPDATE OR DELETE
ON cehub_supplier.material_supplier_attributions
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_supplier.material_supplier_attributions) THEN
    RAISE EXCEPTION 'Supplier attribution history requires retention; downgrade refused'; END IF;
    END $$;
    DROP TABLE cehub_supplier.material_supplier_attributions;
    DROP FUNCTION cehub_supplier.material_supplier_guard();
    """)
