"""Explicit two-party supply row sharing with bounded shared allocation."""

from alembic import op

revision = "0299_supply_sharing"
down_revision = "0298_material_supplier_attributions"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_supplier.supply_share_grants (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
created_by_user_id UUID NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
reason TEXT NOT NULL,
snapshot JSONB NOT NULL,
created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
source_project_id UUID NOT NULL,
recipient_project_id UUID NOT NULL,
recipient_user_id UUID NOT NULL,
supply_snapshot_id UUID NOT NULL,
quantity_limit NUMERIC(24, 8) NOT NULL,
expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
CONSTRAINT pk_supply_share_grants PRIMARY KEY (id),
CONSTRAINT fk_supply_share_grants_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_supply_share_grants_request_valid CHECK (btrim(reason)<>'' AND request_digest ~
'^[0-9a-f]{64}$' AND jsonb_typeof(snapshot)='object'),
CONSTRAINT uq_supply_share_tenant UNIQUE (tenant_id, id),
CONSTRAINT uq_supply_share_request UNIQUE (tenant_id, created_by_user_id, request_id),
CONSTRAINT fk_supply_share_grants_tenant_id_supply_snapshots FOREIGN KEY(tenant_id,
source_project_id, supply_snapshot_id) REFERENCES cehub_supplier.supply_snapshots (tenant_id,
project_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_supply_share_grants_tenant_id_projects FOREIGN KEY(tenant_id,
recipient_project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_supply_share_recipient FOREIGN KEY(tenant_id, recipient_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_supply_share_grants_share_scope CHECK (source_project_id<>recipient_project_id AND
created_by_user_id<>recipient_user_id AND quantity_limit>=0 AND quantity_limit::text NOT IN
('NaN','Infinity','-Infinity') AND expires_at>created_at)
)

;

CREATE TABLE cehub_supplier.supply_share_actions (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
created_by_user_id UUID NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
reason TEXT NOT NULL,
snapshot JSONB NOT NULL,
created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
grant_id UUID NOT NULL,
project_id UUID NOT NULL,
version INTEGER NOT NULL,
outcome VARCHAR(16) NOT NULL,
CONSTRAINT pk_supply_share_actions PRIMARY KEY (id),
CONSTRAINT fk_supply_share_actions_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_supply_share_actions_request_valid CHECK (btrim(reason)<>'' AND request_digest ~
'^[0-9a-f]{64}$' AND jsonb_typeof(snapshot)='object'),
CONSTRAINT uq_supply_share_action_version UNIQUE (tenant_id, grant_id, version),
CONSTRAINT uq_supply_share_action_request UNIQUE (tenant_id, created_by_user_id, request_id),
CONSTRAINT fk_supply_share_actions_tenant_id_supply_share_grants FOREIGN KEY(tenant_id,
grant_id) REFERENCES cehub_supplier.supply_share_grants (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_supply_share_actions_tenant_id_projects FOREIGN KEY(tenant_id, project_id)
REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_supply_share_actions_action_valid CHECK (version>0 AND outcome IN
('accepted','rejected','revoked'))
)

;
"""

OLD_ALLOCATION_GUARD = """
CREATE OR REPLACE FUNCTION cehub_supplier.material_allocation_guard() RETURNS trigger LANGUAGE
plpgsql AS $$
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
"""

ALLOCATION_GUARD = """
CREATE OR REPLACE FUNCTION cehub_supplier.material_allocation_guard() RETURNS trigger LANGUAGE
plpgsql AS $$
DECLARE
batch cehub_supplier.material_allocation_batches%ROWTYPE;
demand cehub_product.build_material_revisions%ROWTYPE;
supply cehub_supplier.supply_snapshots%ROWTYPE;
source cehub_supplier.supply_import_batches%ROWTYPE;
grant_row cehub_supplier.supply_share_grants%ROWTYPE;
grant_held numeric;
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
AND item->>'supply_grant_id' IS NOT DISTINCT FROM NEW.supply_grant_id::text
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
WHERE tenant_id=NEW.tenant_id AND id=NEW.supply_snapshot_id;
IF supply.project_id=NEW.project_id THEN
IF NEW.supply_grant_id IS NOT NULL THEN RAISE EXCEPTION 'Local supply does not use a foreign
grant'; END IF;
ELSE
SELECT * INTO STRICT grant_row FROM cehub_supplier.supply_share_grants
WHERE tenant_id=NEW.tenant_id AND id=NEW.supply_grant_id;
IF grant_row.supply_snapshot_id<>supply.id OR grant_row.recipient_project_id<>NEW.project_id
OR grant_row.source_project_id<>supply.project_id OR grant_row.expires_at<=clock_timestamp()
OR (SELECT outcome FROM cehub_supplier.supply_share_actions WHERE tenant_id=NEW.tenant_id
AND grant_id=grant_row.id ORDER BY version DESC LIMIT 1) IS DISTINCT FROM 'accepted' THEN
RAISE EXCEPTION 'Foreign allocation requires its exact active accepted supply grant'; END IF;
SELECT coalesce(sum(a.quantity-coalesce((SELECT sum(r.quantity)
FROM cehub_supplier.material_allocation_releases r WHERE r.tenant_id=a.tenant_id
AND r.allocation_id=a.id),0)),0) INTO grant_held FROM cehub_supplier.material_supply_allocations
a
WHERE a.tenant_id=NEW.tenant_id AND a.supply_grant_id=grant_row.id;
IF grant_held+NEW.quantity>grant_row.quantity_limit THEN
RAISE EXCEPTION 'Foreign allocation exceeds its grant limit'; END IF;
END IF;
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
"""

SHARE_GUARDS = """
CREATE FUNCTION cehub_supplier.supply_share_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE s cehub_supplier.supply_snapshots%ROWTYPE;
b cehub_supplier.supply_import_batches%ROWTYPE;
BEGIN
PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id
AND id IN (NEW.source_project_id,NEW.recipient_project_id) ORDER BY id FOR UPDATE;
SELECT * INTO STRICT s FROM cehub_supplier.supply_snapshots WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.source_project_id AND id=NEW.supply_snapshot_id;
SELECT * INTO STRICT b FROM cehub_supplier.supply_import_batches WHERE tenant_id=s.tenant_id
AND id=s.batch_id;
PERFORM cehub_supplier.lock_material_pool(NEW.tenant_id,b.source_system,
s.external_pool_id,s.external_item_id);
IF NEW.expires_at<=clock_timestamp() OR (s.quantity IS NULL AND NEW.quantity_limit<>0)
OR (s.quantity IS NOT NULL AND NEW.quantity_limit>s.quantity)
OR NEW.snapshot#>>'{source,id}' IS DISTINCT FROM s.id::text
OR NEW.snapshot#>>'{source,project_id}' IS DISTINCT FROM s.project_id::text
OR NEW.snapshot#>>'{source,document_id}' IS NOT NULL
OR NEW.snapshot->>'scope' IS DISTINCT FROM 'normalized_supply_row_read_and_allocate'
OR NEW.snapshot->>'whole_file_access' IS DISTINCT FROM 'false' THEN
RAISE EXCEPTION 'Supply sharing requires a bounded normalized current source row'; END IF;
IF EXISTS (SELECT 1 FROM cehub_supplier.supply_snapshots newer
JOIN cehub_supplier.supply_import_batches nb ON nb.tenant_id=newer.tenant_id AND
nb.id=newer.batch_id
WHERE newer.tenant_id=NEW.tenant_id AND nb.source_system=b.source_system
AND newer.external_pool_id=s.external_pool_id AND newer.external_item_id=s.external_item_id
AND (nb.as_of,nb.captured_at,newer.id)>(b.as_of,b.captured_at,s.id)) THEN
RAISE EXCEPTION 'Supply sharing source was superseded'; END IF;
IF EXISTS (SELECT 1 FROM cehub_supplier.supply_share_grants g WHERE g.tenant_id=NEW.tenant_id
AND g.supply_snapshot_id=NEW.supply_snapshot_id AND
g.recipient_project_id=NEW.recipient_project_id
AND g.expires_at>clock_timestamp() AND coalesce((SELECT a.outcome
FROM cehub_supplier.supply_share_actions a WHERE a.tenant_id=g.tenant_id AND a.grant_id=g.id
ORDER BY a.version DESC LIMIT 1),'pending') IN ('pending','accepted')) THEN
RAISE EXCEPTION 'A pending or accepted supply share already exists'; END IF;
RETURN NEW;
END $$;
CREATE FUNCTION cehub_supplier.supply_share_action_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE g cehub_supplier.supply_share_grants%ROWTYPE;
prior cehub_supplier.supply_share_actions%ROWTYPE; current_id uuid;
BEGIN
SELECT * INTO STRICT g FROM cehub_supplier.supply_share_grants
WHERE tenant_id=NEW.tenant_id AND id=NEW.grant_id;
PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id
AND id IN (g.source_project_id,g.recipient_project_id) ORDER BY id FOR UPDATE;
PERFORM cehub_supplier.lock_material_pool(NEW.tenant_id,g.snapshot#>>'{source,source_system}',
g.snapshot#>>'{source,external_pool_id}',g.snapshot#>>'{source,external_item_id}');
SELECT * INTO prior FROM cehub_supplier.supply_share_actions WHERE tenant_id=NEW.tenant_id
AND grant_id=g.id ORDER BY version DESC LIMIT 1;
IF NEW.version<>coalesce(prior.version,0)+1 OR prior.outcome IN ('rejected','revoked')
OR NEW.project_id NOT IN (g.source_project_id,g.recipient_project_id)
OR NEW.snapshot->>'grant_id' IS DISTINCT FROM g.id::text
OR NEW.snapshot->>'source_digest' IS DISTINCT FROM g.snapshot->>'digest' THEN
RAISE EXCEPTION 'Supply share action must follow its current scoped grant'; END IF;
IF NEW.outcome IN ('accepted','rejected') AND (prior.id IS NOT NULL
OR NEW.project_id<>g.recipient_project_id OR NEW.created_by_user_id<>g.recipient_user_id
OR NEW.created_by_user_id=g.created_by_user_id) THEN
RAISE EXCEPTION 'Only the named independent recipient may first accept or reject'; END IF;
IF NEW.outcome='accepted' THEN
SELECT s.id INTO current_id FROM cehub_supplier.supply_snapshots s
JOIN cehub_supplier.supply_import_batches b ON b.tenant_id=s.tenant_id AND b.id=s.batch_id
WHERE s.tenant_id=NEW.tenant_id AND b.source_system=g.snapshot#>>'{source,source_system}'
AND s.external_pool_id=g.snapshot#>>'{source,external_pool_id}'
AND s.external_item_id=g.snapshot#>>'{source,external_item_id}'
ORDER BY b.as_of DESC,b.captured_at DESC,s.id DESC LIMIT 1;
IF current_id IS DISTINCT FROM g.supply_snapshot_id OR g.expires_at<=clock_timestamp() THEN
RAISE EXCEPTION 'Accepted supply share must retain its current unexpired source'; END IF;
END IF;
RETURN NEW;
END $$;
CREATE TRIGGER supply_share_insert BEFORE INSERT ON cehub_supplier.supply_share_grants
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.supply_share_guard();
CREATE TRIGGER supply_share_action_insert BEFORE INSERT ON cehub_supplier.supply_share_actions
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.supply_share_action_guard();
CREATE TRIGGER supply_share_immutable BEFORE UPDATE OR DELETE ON
cehub_supplier.supply_share_grants
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
CREATE TRIGGER supply_share_action_immutable BEFORE UPDATE OR DELETE ON
cehub_supplier.supply_share_actions
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute("""
    ALTER TABLE cehub_supplier.supply_snapshots ADD CONSTRAINT uq_supply_snapshot_tenant
      UNIQUE (tenant_id,id);
    ALTER TABLE cehub_supplier.material_supply_allocations ADD COLUMN supply_grant_id uuid;
    ALTER TABLE cehub_supplier.material_supply_allocations
      ADD CONSTRAINT fk_material_allocation_supply_grant FOREIGN KEY (tenant_id,supply_grant_id)
      REFERENCES cehub_supplier.supply_share_grants (tenant_id,id) ON DELETE RESTRICT;
    ALTER TABLE cehub_supplier.material_supply_allocations
      DROP CONSTRAINT fk_material_supply_allocations_tenant_id_supply_snapshots;
    ALTER TABLE cehub_supplier.material_supply_allocations
      ADD CONSTRAINT fk_material_supply_allocations_tenant_id_supply_snapshots
      FOREIGN KEY (tenant_id,supply_snapshot_id)
      REFERENCES cehub_supplier.supply_snapshots (tenant_id,id) ON DELETE RESTRICT;
    """)
    op.execute(SHARE_GUARDS)
    op.execute(ALLOCATION_GUARD)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_supplier.supply_share_grants) THEN
    RAISE EXCEPTION 'Supply share history requires retention; downgrade refused'; END IF;
    END $$;
    """)
    op.execute(OLD_ALLOCATION_GUARD)
    op.execute("""
    ALTER TABLE cehub_supplier.material_supply_allocations
      DROP CONSTRAINT fk_material_supply_allocations_tenant_id_supply_snapshots;
    ALTER TABLE cehub_supplier.material_supply_allocations
      ADD CONSTRAINT fk_material_supply_allocations_tenant_id_supply_snapshots
      FOREIGN KEY (tenant_id,project_id,supply_snapshot_id)
      REFERENCES cehub_supplier.supply_snapshots (tenant_id,project_id,id) ON DELETE RESTRICT;
    ALTER TABLE cehub_supplier.material_supply_allocations
      DROP CONSTRAINT fk_material_allocation_supply_grant;
    ALTER TABLE cehub_supplier.material_supply_allocations DROP COLUMN supply_grant_id;
    ALTER TABLE cehub_supplier.supply_snapshots DROP CONSTRAINT uq_supply_snapshot_tenant;
    DROP TABLE cehub_supplier.supply_share_actions;
    DROP TABLE cehub_supplier.supply_share_grants;
    DROP FUNCTION cehub_supplier.supply_share_action_guard();
    DROP FUNCTION cehub_supplier.supply_share_guard();
    """)
