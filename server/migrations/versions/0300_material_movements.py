"""Actual evidence-bound material movements and current snapshot reconciliation."""

from alembic import op

revision = "0300_material_movements"
down_revision = "0299_supply_sharing"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_supplier.material_movements (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
created_by_user_id UUID NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
reason TEXT NOT NULL,
snapshot JSONB NOT NULL,
evidence_id UUID NOT NULL,
created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
build_id UUID NOT NULL,
allocation_id UUID NOT NULL,
parent_id UUID,
kind VARCHAR(16) NOT NULL,
quantity NUMERIC(24, 8) NOT NULL,
occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
source_system VARCHAR(128) NOT NULL,
transaction_reference VARCHAR(256) NOT NULL,
qualified BOOLEAN NOT NULL,
share_with_source BOOLEAN NOT NULL,
CONSTRAINT pk_material_movements PRIMARY KEY (id),
CONSTRAINT fk_material_movements_tenant_id_documents FOREIGN KEY(tenant_id, project_id,
evidence_id) REFERENCES cehub_project.documents (tenant_id, project_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_material_movements_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_material_movements_record_valid CHECK (btrim(reason)<>'' AND request_digest ~
'^[0-9a-f]{64}$' AND jsonb_typeof(snapshot)='object'),
CONSTRAINT fk_material_movements_tenant_id_material_supply_allocations FOREIGN KEY(tenant_id,
project_id, allocation_id) REFERENCES cehub_supplier.material_supply_allocations (tenant_id,
project_id, id) ON DELETE RESTRICT,
CONSTRAINT uq_material_movement_transaction UNIQUE (tenant_id, source_system, kind,
transaction_reference),
CONSTRAINT uq_material_movement_request UNIQUE (tenant_id, created_by_user_id, request_id),
CONSTRAINT ck_material_movements_movement_valid CHECK (kind IN
('issued','consumed','returned','scrapped') AND ((kind='issued' AND parent_id IS NULL) OR
(kind<>'issued' AND parent_id IS NOT NULL)) AND quantity>0 AND quantity::text NOT IN
('NaN','Infinity','-Infinity') AND btrim(transaction_reference)<>''),
CONSTRAINT fk_material_movements_parent_id_material_movements FOREIGN KEY(parent_id) REFERENCES
cehub_supplier.material_movements (id) ON DELETE RESTRICT
)

;

CREATE TABLE cehub_supplier.material_movement_reconciliations (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
created_by_user_id UUID NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
reason TEXT NOT NULL,
snapshot JSONB NOT NULL,
evidence_id UUID NOT NULL,
created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
movement_id UUID NOT NULL,
supply_snapshot_id UUID NOT NULL,
version INTEGER NOT NULL,
outcome VARCHAR(16) NOT NULL,
CONSTRAINT pk_material_movement_reconciliations PRIMARY KEY (id),
CONSTRAINT fk_material_movement_reconciliations_tenant_id_documents FOREIGN KEY(tenant_id,
project_id, evidence_id) REFERENCES cehub_project.documents (tenant_id, project_id, id) ON
DELETE RESTRICT,
CONSTRAINT fk_material_movement_reconciliations_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_material_movement_reconciliations_record_valid CHECK (btrim(reason)<>'' AND
request_digest ~ '^[0-9a-f]{64}$' AND jsonb_typeof(snapshot)='object'),
CONSTRAINT fk_material_movement_reconciliations_tenant_id_supply_snapshots FOREIGN
KEY(tenant_id, project_id, supply_snapshot_id) REFERENCES cehub_supplier.supply_snapshots
(tenant_id, project_id, id) ON DELETE RESTRICT,
CONSTRAINT uq_material_reconciliation_version UNIQUE (tenant_id, movement_id, version),
CONSTRAINT uq_material_reconciliation_request UNIQUE (tenant_id, created_by_user_id,
request_id),
CONSTRAINT ck_material_movement_reconciliations_reconciliation_valid CHECK (version>0 AND
outcome IN ('confirmed','withdrawn')),
CONSTRAINT fk_material_movement_reconciliations_movement_id_materi_66f4 FOREIGN KEY(movement_id)
REFERENCES cehub_supplier.material_movements (id) ON DELETE RESTRICT
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

OLD_RELEASE_GUARD = """
CREATE OR REPLACE FUNCTION cehub_supplier.material_release_guard() RETURNS trigger LANGUAGE
plpgsql AS $$
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
SELECT
coalesce(sum(cehub_supplier.material_allocation_stock_hold(a.tenant_id,a.id,NEW.supply_snapshot_id)),0)
INTO grant_held FROM cehub_supplier.material_supply_allocations
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
FROM (SELECT
a.unit,cehub_supplier.material_allocation_stock_hold(a.tenant_id,a.id,NEW.supply_snapshot_id) AS
amount
FROM cehub_supplier.material_supply_allocations a
WHERE a.tenant_id=NEW.tenant_id AND a.source_system=NEW.source_system
AND a.external_pool_id=NEW.external_pool_id AND a.external_item_id=NEW.external_item_id) held
WHERE amount>0;
IF conflicting OR reserved+NEW.quantity>supply.quantity THEN
RAISE EXCEPTION 'Supply pool quantity or unit conflict'; END IF;
SELECT coalesce(sum(cehub_supplier.material_allocation_demand_hold(a.tenant_id,a.id)),0) INTO
line_reserved
FROM cehub_supplier.material_supply_allocations a WHERE a.tenant_id=NEW.tenant_id
AND a.revision_id=NEW.revision_id AND a.bom_item_id=NEW.bom_item_id;
IF line_reserved+NEW.quantity>(line->>'required_quantity')::numeric THEN
RAISE EXCEPTION 'Allocation exceeds frozen demand'; END IF;
RETURN NEW;
END $$;
"""

RELEASE_GUARD = """
CREATE OR REPLACE FUNCTION cehub_supplier.material_release_guard() RETURNS trigger LANGUAGE
plpgsql AS $$
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
IF
released+NEW.quantity+
cehub_supplier.material_issued_quantity(NEW.tenant_id,allocation.id)>allocation.quantity
THEN
RAISE EXCEPTION 'Release exceeds outstanding allocation'; END IF;
RETURN NEW;
END $$;
"""


MOVEMENT_FUNCTIONS = """
CREATE FUNCTION cehub_supplier.material_issued_quantity(tenant uuid, allocation uuid)
RETURNS numeric LANGUAGE sql AS $$
SELECT coalesce(sum(quantity),0) FROM cehub_supplier.material_movements
WHERE tenant_id=tenant AND allocation_id=allocation AND kind='issued'
$$;
CREATE FUNCTION cehub_supplier.material_issue_return_ids(tenant uuid, movement uuid)
RETURNS jsonb LANGUAGE sql AS $$
SELECT coalesce(jsonb_agg(id::text ORDER BY id),'[]'::jsonb)
FROM cehub_supplier.material_movements WHERE tenant_id=tenant
AND (id=movement OR (parent_id=movement AND kind='returned'))
$$;
CREATE FUNCTION cehub_supplier.material_allocation_stock_hold(
tenant uuid, allocation uuid, supply uuid) RETURNS numeric LANGUAGE sql AS $$
SELECT a.quantity
-coalesce((SELECT sum(r.quantity) FROM cehub_supplier.material_allocation_releases r
WHERE r.tenant_id=tenant AND r.allocation_id=a.id),0)
-coalesce((SELECT sum(m.quantity) FROM cehub_supplier.material_movements m
WHERE m.tenant_id=tenant AND m.allocation_id=a.id AND m.kind='issued'
AND EXISTS (SELECT 1 FROM cehub_supplier.material_movement_reconciliations rec
WHERE rec.tenant_id=tenant AND rec.movement_id=m.id AND rec.outcome='confirmed'
AND rec.supply_snapshot_id=supply
AND rec.snapshot->'movement_ids'=cehub_supplier.material_issue_return_ids(tenant,m.id)
AND NOT EXISTS (SELECT 1 FROM cehub_supplier.material_movement_reconciliations newer
WHERE newer.tenant_id=tenant AND newer.movement_id=m.id AND newer.version>rec.version))),0)
FROM cehub_supplier.material_supply_allocations a WHERE a.tenant_id=tenant AND a.id=allocation
$$;
CREATE FUNCTION cehub_supplier.material_allocation_demand_hold(tenant uuid, allocation uuid)
RETURNS numeric LANGUAGE sql AS $$
SELECT a.quantity
-coalesce((SELECT sum(r.quantity) FROM cehub_supplier.material_allocation_releases r
WHERE r.tenant_id=tenant AND r.allocation_id=a.id),0)
-coalesce((SELECT sum(m.quantity) FROM cehub_supplier.material_movements m
WHERE m.tenant_id=tenant AND m.allocation_id=a.id AND m.kind IN ('returned','scrapped')),0)
FROM cehub_supplier.material_supply_allocations a WHERE a.tenant_id=tenant AND a.id=allocation
$$;
CREATE FUNCTION cehub_supplier.material_movement_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE a cehub_supplier.material_supply_allocations%ROWTYPE;
parent cehub_supplier.material_movements%ROWTYPE; original_project uuid;
current_source cehub_supplier.supply_snapshots%ROWTYPE;
batch cehub_supplier.supply_import_batches%ROWTYPE;
remaining numeric; latest_id uuid; current_grant cehub_supplier.supply_share_grants%ROWTYPE;
BEGIN
PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR
UPDATE;
SELECT * INTO STRICT a FROM cehub_supplier.material_supply_allocations WHERE
tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=NEW.allocation_id;
PERFORM cehub_supplier.lock_material_pool(NEW.tenant_id,a.source_system,
a.external_pool_id,a.external_item_id);
SELECT project_id INTO STRICT original_project FROM cehub_supplier.supply_snapshots
WHERE tenant_id=NEW.tenant_id AND id=a.supply_snapshot_id;
IF a.build_id<>NEW.build_id OR a.source_system<>NEW.source_system
OR NEW.occurred_at>clock_timestamp()
OR NEW.snapshot#>>'{allocation,id}' IS DISTINCT FROM a.id::text
OR NEW.snapshot#>>'{evidence,id}' IS DISTINCT FROM NEW.evidence_id::text THEN
RAISE EXCEPTION 'Material movement requires actual scoped allocation, evidence and time'; END
IF;
IF original_project<>NEW.project_id AND NEW.kind IN ('issued','returned')
AND NOT NEW.share_with_source THEN
RAISE EXCEPTION 'Foreign material movement needs explicit normalized source reconciliation
sharing'; END IF;
IF NEW.kind='issued' THEN
IF NOT EXISTS (SELECT 1 FROM cehub_product.build_batches WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=NEW.build_id AND status IN ('planned','in_progress')) THEN
RAISE EXCEPTION 'New material issuance requires an active build'; END IF;
SELECT a.quantity-coalesce(sum(r.quantity),0)
-cehub_supplier.material_issued_quantity(NEW.tenant_id,a.id) INTO remaining
FROM cehub_supplier.material_allocation_releases r WHERE r.tenant_id=NEW.tenant_id
AND r.allocation_id=a.id;
IF NEW.quantity>remaining THEN RAISE EXCEPTION 'Material issuance exceeds undrawn allocation';
END IF;
IF NEW.qualified THEN
SELECT * INTO STRICT current_source FROM cehub_supplier.supply_snapshots
WHERE tenant_id=NEW.tenant_id AND id=(NEW.snapshot#>>'{source,source,id}')::uuid;
SELECT * INTO STRICT batch FROM cehub_supplier.supply_import_batches
WHERE tenant_id=NEW.tenant_id AND id=current_source.batch_id;
SELECT s.id INTO latest_id FROM cehub_supplier.supply_snapshots s
JOIN cehub_supplier.supply_import_batches b ON b.tenant_id=s.tenant_id AND b.id=s.batch_id
WHERE s.tenant_id=NEW.tenant_id AND b.source_system=a.source_system
AND s.external_pool_id=a.external_pool_id AND s.external_item_id=a.external_item_id
ORDER BY b.as_of DESC,b.captured_at DESC,s.id DESC LIMIT 1;
IF latest_id IS DISTINCT FROM current_source.id OR current_source.unit<>a.unit
OR current_source.supply_kind<>'on_hand' OR current_source.quality_status<>'released'
OR batch.fresh_until<=clock_timestamp() OR NEW.occurred_at<batch.as_of
OR NEW.occurred_at>batch.fresh_until OR NEW.snapshot#>>'{source,state}' IS DISTINCT FROM
'current' THEN
RAISE EXCEPTION 'Qualified issuance requires current released on-hand evidence at actual time';
END IF;
IF a.supply_grant_id IS NOT NULL THEN
SELECT * INTO STRICT current_grant FROM cehub_supplier.supply_share_grants WHERE
tenant_id=NEW.tenant_id
AND id=a.supply_grant_id;
IF current_grant.supply_snapshot_id<>current_source.id OR
current_grant.expires_at<=clock_timestamp()
OR (SELECT outcome FROM cehub_supplier.supply_share_actions WHERE tenant_id=NEW.tenant_id
AND grant_id=current_grant.id ORDER BY version DESC LIMIT 1) IS DISTINCT FROM 'accepted' THEN
RAISE EXCEPTION 'Qualified shared issuance requires the original effective grant'; END IF;
ELSIF current_source.project_id<>NEW.project_id THEN
RAISE EXCEPTION 'Qualified local issuance requires the local source'; END IF;
END IF;
ELSE
SELECT * INTO STRICT parent FROM cehub_supplier.material_movements WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=NEW.parent_id AND kind='issued';
IF parent.allocation_id<>NEW.allocation_id OR parent.build_id<>NEW.build_id
OR NEW.occurred_at<parent.occurred_at OR NEW.qualified<>parent.qualified THEN
RAISE EXCEPTION 'Disposition must retain the original issue, time and qualification basis'; END
IF;
SELECT parent.quantity-coalesce(sum(quantity),0) INTO remaining
FROM cehub_supplier.material_movements WHERE tenant_id=NEW.tenant_id AND parent_id=parent.id;
IF NEW.quantity>remaining THEN RAISE EXCEPTION 'Disposition exceeds remaining issued material';
END IF;
END IF;
RETURN NEW;
END $$;
CREATE FUNCTION cehub_supplier.material_reconciliation_guard() RETURNS trigger LANGUAGE plpgsql
AS $$
DECLARE m cehub_supplier.material_movements%ROWTYPE;
a cehub_supplier.material_supply_allocations%ROWTYPE;
s cehub_supplier.supply_snapshots%ROWTYPE; b cehub_supplier.supply_import_batches%ROWTYPE;
original_project uuid; latest_version integer; latest_id uuid; occurred timestamptz;
BEGIN
SELECT * INTO STRICT m FROM cehub_supplier.material_movements WHERE tenant_id=NEW.tenant_id
AND id=NEW.movement_id AND kind='issued';
SELECT * INTO STRICT a FROM cehub_supplier.material_supply_allocations WHERE
tenant_id=NEW.tenant_id
AND id=m.allocation_id;
SELECT project_id INTO STRICT original_project FROM cehub_supplier.supply_snapshots
WHERE tenant_id=NEW.tenant_id AND id=a.supply_snapshot_id;
PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id
AND id IN (original_project,m.project_id) ORDER BY id FOR UPDATE;
PERFORM cehub_supplier.lock_material_pool(NEW.tenant_id,a.source_system,
a.external_pool_id,a.external_item_id);
IF original_project<>NEW.project_id OR (m.project_id<>NEW.project_id AND NOT
m.share_with_source)
THEN RAISE EXCEPTION 'Only the actual source project may reconcile a shared normalized
movement'; END IF;
SELECT coalesce(max(version),0) INTO latest_version FROM
cehub_supplier.material_movement_reconciliations
WHERE tenant_id=NEW.tenant_id AND movement_id=m.id;
IF NEW.version<>latest_version+1 OR (NEW.outcome='withdrawn' AND latest_version=0)
OR NEW.snapshot->'movement_ids' IS DISTINCT FROM
cehub_supplier.material_issue_return_ids(NEW.tenant_id,m.id)
OR NEW.snapshot#>>'{source,id}' IS DISTINCT FROM NEW.supply_snapshot_id::text
OR NEW.snapshot#>>'{evidence,id}' IS DISTINCT FROM NEW.evidence_id::text THEN
RAISE EXCEPTION 'Balance reconciliation requires consecutive original movement/source evidence';
END IF;
SELECT * INTO STRICT s FROM cehub_supplier.supply_snapshots WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=NEW.supply_snapshot_id;
SELECT * INTO STRICT b FROM cehub_supplier.supply_import_batches WHERE tenant_id=NEW.tenant_id
AND id=s.batch_id;
IF s.external_pool_id<>a.external_pool_id OR s.external_item_id<>a.external_item_id
OR s.unit<>a.unit OR b.source_system<>a.source_system THEN
RAISE EXCEPTION 'Reconciliation balance must refer to the same original pool/material/unit'; END
IF;
IF NEW.outcome='confirmed' THEN
SELECT max(occurred_at) INTO occurred FROM cehub_supplier.material_movements
WHERE tenant_id=NEW.tenant_id AND (id=m.id OR (parent_id=m.id AND kind='returned'));
SELECT ss.id INTO latest_id FROM cehub_supplier.supply_snapshots ss
JOIN cehub_supplier.supply_import_batches bb ON bb.tenant_id=ss.tenant_id AND bb.id=ss.batch_id
WHERE ss.tenant_id=NEW.tenant_id AND bb.source_system=a.source_system
AND ss.external_pool_id=a.external_pool_id AND ss.external_item_id=a.external_item_id
ORDER BY bb.as_of DESC,bb.captured_at DESC,ss.id DESC LIMIT 1;
IF latest_id IS DISTINCT FROM s.id OR b.as_of<occurred OR s.quantity IS NULL
OR s.supply_kind<>'on_hand' THEN
RAISE EXCEPTION 'Confirmed balance must be current and include the latest physical movements';
END IF;
END IF;
RETURN NEW;
END $$;
CREATE TRIGGER material_movement_insert BEFORE INSERT ON cehub_supplier.material_movements
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_movement_guard();
CREATE TRIGGER material_reconciliation_insert BEFORE INSERT ON
cehub_supplier.material_movement_reconciliations
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_reconciliation_guard();
CREATE TRIGGER material_movement_immutable BEFORE UPDATE OR DELETE ON
cehub_supplier.material_movements
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
CREATE TRIGGER material_reconciliation_immutable BEFORE UPDATE OR DELETE ON
cehub_supplier.material_movement_reconciliations
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(MOVEMENT_FUNCTIONS)
    op.execute(ALLOCATION_GUARD)
    op.execute(RELEASE_GUARD)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_supplier.material_movements) THEN
    RAISE EXCEPTION 'Physical material evidence requires retention; downgrade refused'; END IF;
    END $$;
    """)
    op.execute(OLD_ALLOCATION_GUARD)
    op.execute(OLD_RELEASE_GUARD)
    op.execute("""
    DROP FUNCTION cehub_supplier.material_allocation_stock_hold(uuid,uuid,uuid);
    DROP FUNCTION cehub_supplier.material_allocation_demand_hold(uuid,uuid);
    DROP TABLE cehub_supplier.material_movement_reconciliations;
    DROP TABLE cehub_supplier.material_movements;
    DROP FUNCTION cehub_supplier.material_reconciliation_guard();
    DROP FUNCTION cehub_supplier.material_movement_guard();
    DROP FUNCTION cehub_supplier.material_issue_return_ids(uuid,uuid);
    DROP FUNCTION cehub_supplier.material_issued_quantity(uuid,uuid);
    """)
