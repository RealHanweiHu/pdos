"""Immutable planned supply allocation and partial release ledger."""

from alembic import op

revision = "0294_material_allocations"
down_revision = "0293_supply_file_capture"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE cehub_supplier.material_allocation_batches (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    build_id UUID NOT NULL,
    action VARCHAR(16) NOT NULL,
    created_by_user_id UUID NOT NULL,
    request_id UUID NOT NULL,
    request_digest VARCHAR(64) NOT NULL,
    basis_digest VARCHAR(64) NOT NULL,
    snapshot JSONB NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_material_allocation_batches PRIMARY KEY (id),
    CONSTRAINT uq_material_allocation_batch_project UNIQUE (tenant_id, project_id, id),
    CONSTRAINT uq_material_allocation_request UNIQUE (tenant_id, created_by_user_id, request_id),
        CONSTRAINT fk_material_allocation_batches_tenant_id_build_batches FOREIGN KEY(tenant_id,
project_id, build_id) REFERENCES cehub_product.build_batches (tenant_id, project_id, id) ON DELETE
RESTRICT,
        CONSTRAINT fk_material_allocation_batches_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_material_allocation_batches_action_reason CHECK (action IN
('allocate','release') AND btrim(reason)<>''),
        CONSTRAINT ck_material_allocation_batches_snapshot_object CHECK
(jsonb_typeof(snapshot)='object'),
        CONSTRAINT ck_material_allocation_batches_digests_valid CHECK (request_digest ~
'^[0-9a-f]{64}$' AND basis_digest ~ '^[0-9a-f]{64}$')
);

CREATE TABLE cehub_supplier.material_supply_allocations (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    build_id UUID NOT NULL,
    batch_id UUID NOT NULL,
    revision_id UUID NOT NULL,
    bom_item_id UUID NOT NULL,
    supply_snapshot_id UUID NOT NULL,
    source_system VARCHAR(128) NOT NULL,
    external_pool_id VARCHAR(256) NOT NULL,
    external_item_id VARCHAR(256) NOT NULL,
    unit VARCHAR(64) NOT NULL,
    quantity NUMERIC(24, 8) NOT NULL,
    CONSTRAINT pk_material_supply_allocations PRIMARY KEY (id),
    CONSTRAINT uq_material_allocation_project UNIQUE (tenant_id, project_id, id),
    CONSTRAINT uq_material_allocation_batch_source UNIQUE
    (tenant_id, batch_id, bom_item_id, supply_snapshot_id),
        CONSTRAINT fk_material_supply_allocations_tenant_id_material_alloc_da14 FOREIGN
KEY(tenant_id, project_id, batch_id) REFERENCES cehub_supplier.material_allocation_batches
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_material_supply_allocations_tenant_id_build_material_4167 FOREIGN
KEY(tenant_id, project_id, revision_id) REFERENCES cehub_product.build_material_revisions
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_material_supply_allocations_tenant_id_supply_snapshots FOREIGN
KEY(tenant_id, project_id, supply_snapshot_id) REFERENCES cehub_supplier.supply_snapshots
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_material_supply_allocations_quantity_positive CHECK (quantity>0 AND
quantity::text NOT IN ('NaN','Infinity','-Infinity'))
);
CREATE INDEX ix_material_allocation_pool ON cehub_supplier.material_supply_allocations (tenant_id,
source_system, external_pool_id, external_item_id);
CREATE TABLE cehub_supplier.material_allocation_releases (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    batch_id UUID NOT NULL,
    allocation_id UUID NOT NULL,
    quantity NUMERIC(24, 8) NOT NULL,
    CONSTRAINT pk_material_allocation_releases PRIMARY KEY (id),
    CONSTRAINT uq_material_release_batch_item UNIQUE (tenant_id, batch_id, allocation_id),
        CONSTRAINT fk_material_allocation_releases_tenant_id_material_allo_60a4 FOREIGN
KEY(tenant_id, project_id, batch_id) REFERENCES cehub_supplier.material_allocation_batches
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_material_allocation_releases_tenant_id_material_supp_d7fb FOREIGN
KEY(tenant_id, project_id, allocation_id) REFERENCES cehub_supplier.material_supply_allocations
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_material_allocation_releases_quantity_positive CHECK (quantity>0 AND
quantity::text NOT IN ('NaN','Infinity','-Infinity'))
);
"""

GUARDS = """
CREATE FUNCTION cehub_supplier.lock_material_pool(
 tenant uuid, source text, pool text, item text
) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(
 jsonb_build_array(tenant::text,source,pool,item)::text,0));
END $$;
CREATE FUNCTION cehub_supplier.lock_supply_snapshot_pool() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE system_name text;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id
 AND id=NEW.project_id FOR UPDATE;
 SELECT source_system INTO STRICT system_name FROM cehub_supplier.supply_import_batches
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.batch_id;
 PERFORM cehub_supplier.lock_material_pool(
 NEW.tenant_id,system_name,NEW.external_pool_id,NEW.external_item_id);
 RETURN NEW;
END $$;
CREATE TRIGGER supply_snapshot_pool_lock BEFORE INSERT ON cehub_supplier.supply_snapshots
 FOR EACH ROW EXECUTE FUNCTION cehub_supplier.lock_supply_snapshot_pool();
CREATE FUNCTION cehub_supplier.material_ledger_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Material allocation history is immutable'; END $$;
CREATE FUNCTION cehub_supplier.material_allocation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
 batch cehub_supplier.material_allocation_batches%ROWTYPE;
 demand cehub_product.build_material_revisions%ROWTYPE;
 supply cehub_supplier.supply_snapshots%ROWTYPE;
 source cehub_supplier.supply_import_batches%ROWTYPE;
 latest_id uuid;
 line jsonb;
 reserved numeric;
 line_reserved numeric;
 conflicting boolean;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id
 AND id=NEW.project_id FOR UPDATE;
 PERFORM cehub_supplier.lock_material_pool(
 NEW.tenant_id,NEW.source_system,NEW.external_pool_id,NEW.external_item_id);
 SELECT * INTO STRICT batch FROM cehub_supplier.material_allocation_batches
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.batch_id;
 IF batch.action<>'allocate' OR batch.build_id<>NEW.build_id THEN
 RAISE EXCEPTION 'Allocation must match its batch'; END IF;
 IF batch.snapshot->>'revision_id' IS DISTINCT FROM NEW.revision_id::text OR NOT EXISTS (
 SELECT 1 FROM jsonb_array_elements(batch.snapshot->'proposed') item
 WHERE item->>'bom_item_id'=NEW.bom_item_id::text
 AND item->>'supply_snapshot_id'=NEW.supply_snapshot_id::text
 AND (item->>'quantity')::numeric=NEW.quantity) THEN
 RAISE EXCEPTION 'Allocation must match immutable batch preview'; END IF;
 SELECT * INTO STRICT demand FROM cehub_product.build_material_revisions
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.revision_id;
 IF demand.build_id<>NEW.build_id OR EXISTS (
 SELECT 1 FROM cehub_product.build_material_revisions r WHERE r.tenant_id=NEW.tenant_id
 AND r.build_id=NEW.build_id AND r.version>demand.version) OR NOT EXISTS (
 SELECT 1 FROM cehub_product.build_batches b WHERE b.tenant_id=NEW.tenant_id
 AND b.project_id=NEW.project_id AND b.id=NEW.build_id
 AND b.status IN ('planned','in_progress')) THEN
 RAISE EXCEPTION 'Allocation requires current demand and active build'; END IF;
 SELECT value INTO line FROM jsonb_array_elements(demand.lines)
 WHERE value->>'bom_item_id'=NEW.bom_item_id::text;
 IF line IS NULL OR line->>'material_reference' IS DISTINCT FROM NEW.external_item_id
 OR line->>'unit' IS DISTINCT FROM NEW.unit THEN
 RAISE EXCEPTION 'Allocation material and unit must match frozen demand'; END IF;
 SELECT * INTO STRICT supply FROM cehub_supplier.supply_snapshots
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.supply_snapshot_id;
 SELECT * INTO STRICT source FROM cehub_supplier.supply_import_batches
 WHERE tenant_id=NEW.tenant_id AND id=supply.batch_id;
 IF source.source_system<>NEW.source_system OR supply.external_pool_id<>NEW.external_pool_id
 OR supply.external_item_id<>NEW.external_item_id OR supply.unit<>NEW.unit
 OR source.fresh_until<=clock_timestamp() OR supply.quantity IS NULL
 OR supply.quality_status='frozen' THEN
 RAISE EXCEPTION 'Allocation requires current eligible supply'; END IF;
 SELECT s.id INTO latest_id FROM cehub_supplier.supply_snapshots s
 JOIN cehub_supplier.supply_import_batches b ON b.tenant_id=s.tenant_id AND b.id=s.batch_id
 WHERE s.tenant_id=NEW.tenant_id AND b.source_system=NEW.source_system
 AND s.external_pool_id=NEW.external_pool_id AND s.external_item_id=NEW.external_item_id
 ORDER BY b.as_of DESC,b.captured_at DESC,s.id DESC LIMIT 1;
 IF latest_id IS DISTINCT FROM NEW.supply_snapshot_id THEN
 RAISE EXCEPTION 'Supply pool has a newer snapshot'; END IF;
 SELECT coalesce(sum(amount),0),coalesce(bool_or(unit<>NEW.unit),false) INTO reserved,conflicting
 FROM (SELECT a.unit,a.quantity-coalesce((SELECT sum(r.quantity)
 FROM cehub_supplier.material_allocation_releases r
 WHERE r.tenant_id=a.tenant_id AND r.allocation_id=a.id),0) AS amount
 FROM cehub_supplier.material_supply_allocations a
 WHERE a.tenant_id=NEW.tenant_id AND a.source_system=NEW.source_system
 AND a.external_pool_id=NEW.external_pool_id AND a.external_item_id=NEW.external_item_id) held
 WHERE amount>0;
 IF conflicting OR reserved+NEW.quantity>supply.quantity THEN
 RAISE EXCEPTION 'Supply pool quantity or unit conflict'; END IF;
 SELECT coalesce(sum(a.quantity-coalesce((SELECT sum(r.quantity)
 FROM cehub_supplier.material_allocation_releases r
 WHERE r.tenant_id=a.tenant_id AND r.allocation_id=a.id),0)),0) INTO line_reserved
 FROM cehub_supplier.material_supply_allocations a WHERE a.tenant_id=NEW.tenant_id
 AND a.revision_id=NEW.revision_id AND a.bom_item_id=NEW.bom_item_id;
 IF line_reserved+NEW.quantity>(line->>'required_quantity')::numeric THEN
 RAISE EXCEPTION 'Allocation exceeds frozen demand'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_supplier.material_release_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
 allocation cehub_supplier.material_supply_allocations%ROWTYPE;
 batch cehub_supplier.material_allocation_batches%ROWTYPE;
 released numeric;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id
 AND id=NEW.project_id FOR UPDATE;
 SELECT * INTO STRICT allocation FROM cehub_supplier.material_supply_allocations
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.allocation_id;
 SELECT * INTO STRICT batch FROM cehub_supplier.material_allocation_batches
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.batch_id;
 IF batch.action<>'release' OR batch.build_id<>allocation.build_id THEN
 RAISE EXCEPTION 'Release must match its original allocation'; END IF;
 IF NOT EXISTS (SELECT 1 FROM jsonb_array_elements(batch.snapshot->'releases') item
 WHERE item->>'allocation_id'=NEW.allocation_id::text
 AND (item->>'quantity')::numeric=NEW.quantity) THEN
 RAISE EXCEPTION 'Release must match immutable batch preview'; END IF;
 PERFORM cehub_supplier.lock_material_pool(NEW.tenant_id,allocation.source_system,
 allocation.external_pool_id,allocation.external_item_id);
 SELECT coalesce(sum(quantity),0) INTO released FROM cehub_supplier.material_allocation_releases
 WHERE tenant_id=NEW.tenant_id AND allocation_id=NEW.allocation_id;
 IF released+NEW.quantity>allocation.quantity THEN
 RAISE EXCEPTION 'Release exceeds outstanding allocation'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_supplier.material_batch_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected integer; actual integer;
BEGIN
 IF NEW.action='allocate' THEN
 expected:=jsonb_array_length(NEW.snapshot->'proposed');
 SELECT count(*) INTO actual FROM cehub_supplier.material_supply_allocations
 WHERE tenant_id=NEW.tenant_id AND batch_id=NEW.id;
 ELSE
 expected:=jsonb_array_length(NEW.snapshot->'releases');
 SELECT count(*) INTO actual FROM cehub_supplier.material_allocation_releases
 WHERE tenant_id=NEW.tenant_id AND batch_id=NEW.id;
 END IF;
 IF expected IS NULL OR expected NOT BETWEEN 1 AND 200 OR actual<>expected THEN
 RAISE EXCEPTION 'Allocation batch must contain exactly its fixed rows'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER material_batch_complete
 AFTER INSERT ON cehub_supplier.material_allocation_batches
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
 EXECUTE FUNCTION cehub_supplier.material_batch_complete();
CREATE TRIGGER material_allocation_guard BEFORE INSERT ON cehub_supplier.material_supply_allocations
 FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_allocation_guard();
CREATE TRIGGER material_release_guard BEFORE INSERT ON cehub_supplier.material_allocation_releases
 FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_release_guard();
CREATE TRIGGER material_allocation_batches_immutable
 BEFORE UPDATE OR DELETE ON cehub_supplier.material_allocation_batches
 FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
CREATE TRIGGER material_supply_allocations_immutable
 BEFORE UPDATE OR DELETE ON cehub_supplier.material_supply_allocations
 FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
CREATE TRIGGER material_allocation_releases_immutable
 BEFORE UPDATE OR DELETE ON cehub_supplier.material_allocation_releases
 FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM cehub_supplier.material_allocation_batches) THEN
        RAISE EXCEPTION 'Allocation history requires retention; downgrade refused';
      END IF;
    END $$;
    DROP TRIGGER supply_snapshot_pool_lock ON cehub_supplier.supply_snapshots;
    DROP FUNCTION cehub_supplier.lock_supply_snapshot_pool();
    DROP TABLE cehub_supplier.material_allocation_releases;
    DROP TABLE cehub_supplier.material_supply_allocations;
    DROP TABLE cehub_supplier.material_allocation_batches;
    DROP FUNCTION cehub_supplier.material_allocation_guard();
    DROP FUNCTION cehub_supplier.material_release_guard();
    DROP FUNCTION cehub_supplier.material_ledger_immutable();
    DROP FUNCTION cehub_supplier.material_batch_complete();
    DROP FUNCTION cehub_supplier.lock_material_pool(uuid,text,text,text);
    """)
