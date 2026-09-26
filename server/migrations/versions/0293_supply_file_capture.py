"""Immutable, source-bound supply file batches and common SupplySnapshot records."""

from alembic import op

revision = "0293_supply_file_capture"
down_revision = "0292_build_material_revisions"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE cehub_supplier.supply_import_batches (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
document_id UUID NOT NULL,
document_digest VARCHAR(64) NOT NULL,
source_system VARCHAR(128) NOT NULL,
source_version VARCHAR(256) NOT NULL,
as_of TIMESTAMP WITH TIME ZONE NOT NULL,
fresh_until TIMESTAMP WITH TIME ZONE NOT NULL,
captured_at TIMESTAMP WITH TIME ZONE NOT NULL,
configuration JSONB NOT NULL,
content_digest VARCHAR(64) NOT NULL,
created_by_user_id UUID NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
reason TEXT NOT NULL,
row_count INTEGER NOT NULL,
ignored_rows JSONB NOT NULL,
CONSTRAINT pk_supply_import_batches PRIMARY KEY (id),
CONSTRAINT uq_supply_import_batch_project UNIQUE (tenant_id, project_id, id),
CONSTRAINT uq_supply_import_source_version UNIQUE (tenant_id, source_system, source_version),
CONSTRAINT uq_supply_import_request UNIQUE (tenant_id, created_by_user_id, request_id),
CONSTRAINT fk_supply_import_batches_tenant_id_documents FOREIGN KEY(tenant_id, project_id,
document_id) REFERENCES cehub_project.documents (tenant_id, project_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_supply_import_batches_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_supply_import_batches_capture_limits CHECK (row_count BETWEEN 1 AND 2000 AND
fresh_until>as_of AND captured_at>=as_of),
CONSTRAINT ck_supply_import_batches_capture_objects CHECK (jsonb_typeof(configuration)='object'
AND jsonb_typeof(ignored_rows)='array'),
CONSTRAINT ck_supply_import_batches_source_nonblank CHECK (btrim(source_system)<>'' AND
btrim(source_version)<>'' AND btrim(reason)<>''),
CONSTRAINT ck_supply_import_batches_digests_valid CHECK (document_digest ~ '^[0-9a-f]{64}$' AND
content_digest ~ '^[0-9a-f]{64}$' AND request_digest ~ '^[0-9a-f]{64}$')
);
CREATE TABLE cehub_supplier.supply_snapshots (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
batch_id UUID NOT NULL,
external_pool_id VARCHAR(256) NOT NULL,
external_item_id VARCHAR(256) NOT NULL,
quantity NUMERIC(24, 8),
unit VARCHAR(64) NOT NULL,
availability VARCHAR(16) NOT NULL,
supply_kind VARCHAR(24) NOT NULL,
quality_status VARCHAR(16) NOT NULL,
expected_date DATE,
lead_time_days INTEGER,
source_row INTEGER NOT NULL,
raw_cells JSONB NOT NULL,
contract JSONB NOT NULL,
CONSTRAINT pk_supply_snapshots PRIMARY KEY (id),
CONSTRAINT uq_supply_snapshot_project UNIQUE (tenant_id, project_id, id),
CONSTRAINT uq_supply_snapshot_pool_row UNIQUE (tenant_id, batch_id, external_pool_id,
external_item_id),
CONSTRAINT uq_supply_snapshot_source_row UNIQUE (tenant_id, batch_id, source_row),
CONSTRAINT fk_supply_snapshots_tenant_id_supply_import_batches FOREIGN KEY(tenant_id, project_id,
batch_id) REFERENCES cehub_supplier.supply_import_batches (tenant_id, project_id, id) ON DELETE
RESTRICT,
CONSTRAINT ck_supply_snapshots_quantity_known CHECK ((availability='unknown' AND quantity IS NULL)
OR (availability='known' AND quantity>=0 AND quantity IS NOT NULL)),
CONSTRAINT ck_supply_snapshots_source_states CHECK (supply_kind IN ('on_hand','expected_receipt')
AND quality_status IN ('released','frozen','unknown')),
CONSTRAINT ck_supply_snapshots_row_lead_time CHECK (source_row>1 AND (lead_time_days IS NULL OR
lead_time_days BETWEEN 0 AND 36600)),
CONSTRAINT ck_supply_snapshots_arrival_kind CHECK (supply_kind<>'on_hand' OR expected_date IS
NULL),
CONSTRAINT ck_supply_snapshots_source_objects CHECK (jsonb_typeof(raw_cells)='object' AND
jsonb_typeof(contract)='object')
);
"""
GUARD = """
CREATE FUNCTION cehub_supplier.guard_supply_capture() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Supply source captures are immutable'; END IF;
 IF TG_TABLE_NAME='supply_import_batches' THEN
  IF NOT EXISTS (SELECT 1 FROM cehub_project.documents d
   WHERE d.tenant_id=NEW.tenant_id AND d.project_id=NEW.project_id
    AND d.id=NEW.document_id AND d.sha256=NEW.document_digest)
  THEN RAISE EXCEPTION 'Supply capture must retain the actual project source'; END IF;
 ELSE
  IF NOT EXISTS (SELECT 1 FROM cehub_supplier.supply_import_batches b
   WHERE b.tenant_id=NEW.tenant_id AND b.project_id=NEW.project_id AND b.id=NEW.batch_id
   AND (SELECT count(*) FROM cehub_supplier.supply_snapshots s
    WHERE s.tenant_id=b.tenant_id AND s.batch_id=b.id)<b.row_count
   AND NEW.contract->>'id'=NEW.id::text
   AND NEW.contract->>'tenant_id'=NEW.tenant_id::text
   AND NEW.contract->'scope'->>'kind'='project'
   AND NEW.contract->'scope'->>'ref_id'=NEW.project_id::text
   AND NEW.contract->>'source_system'=b.source_system
   AND NEW.contract->>'external_item_id'=NEW.external_item_id
   AND NEW.contract->>'unit'=NEW.unit
   AND NEW.contract->>'availability'=NEW.availability
   AND (NEW.contract->>'quantity')::numeric IS NOT DISTINCT FROM NEW.quantity
   AND (NEW.contract->>'as_of')::timestamptz=b.as_of
   AND (NEW.contract->>'fresh_until')::timestamptz=b.fresh_until
   AND NEW.contract->'sources'->0->>'ref_id'=b.document_id::text
   AND NEW.contract->'sources'->0->>'digest'=b.document_digest)
  THEN RAISE EXCEPTION 'Supply contract must match captured source and values'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_supply_import_batch BEFORE INSERT OR UPDATE OR DELETE
ON cehub_supplier.supply_import_batches
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.guard_supply_capture();
CREATE TRIGGER guard_supply_snapshot BEFORE INSERT OR UPDATE OR DELETE
ON cehub_supplier.supply_snapshots
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.guard_supply_capture();
CREATE FUNCTION cehub_supplier.require_supply_capture_rows() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF (SELECT count(*) FROM cehub_supplier.supply_snapshots s
   WHERE s.tenant_id=NEW.tenant_id AND s.batch_id=NEW.id)<>NEW.row_count
 THEN RAISE EXCEPTION 'Supply capture must include every reviewed source row'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER require_supply_capture_rows AFTER INSERT
ON cehub_supplier.supply_import_batches DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.require_supply_capture_rows();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_supplier.supply_import_batches) THEN
      RAISE EXCEPTION 'Retain immutable supply import provenance';
    END IF;
    END $$;
    DROP TABLE cehub_supplier.supply_snapshots;
    DROP TABLE cehub_supplier.supply_import_batches;
    DROP FUNCTION cehub_supplier.guard_supply_capture();
    DROP FUNCTION cehub_supplier.require_supply_capture_rows();
    """)
