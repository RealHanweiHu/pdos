"""Append-only material corrections and linked source-transaction registration versions."""

from alembic import op

revision = "0302_material_movement_corrections"
down_revision = "0301_material_consumption_dispositions"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_supplier.material_movement_corrections (
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
	CONSTRAINT pk_material_movement_corrections PRIMARY KEY (id), 
        CONSTRAINT fk_material_movement_corrections_tenant_id_documents FOREIGN KEY(tenant_id,
project_id, evidence_id) REFERENCES cehub_project.documents (tenant_id, project_id, id) ON DELETE
RESTRICT,
        CONSTRAINT fk_material_movement_corrections_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_material_movement_corrections_record_valid CHECK (btrim(reason)<>'' AND
request_digest ~ '^[0-9a-f]{64}$' AND jsonb_typeof(snapshot)='object'),
	CONSTRAINT uq_material_correction_movement UNIQUE (tenant_id, movement_id), 
	CONSTRAINT uq_material_correction_request UNIQUE (tenant_id, created_by_user_id, request_id), 
        CONSTRAINT fk_material_movement_corrections_movement_id_material_movements FOREIGN
KEY(movement_id) REFERENCES cehub_supplier.material_movements (id) ON DELETE RESTRICT
)

;
ALTER TABLE cehub_supplier.material_movements
ADD COLUMN transaction_version integer NOT NULL DEFAULT 1,
ADD COLUMN replacement_of_id uuid,
DROP CONSTRAINT uq_material_movement_transaction;
ALTER TABLE cehub_supplier.material_movements ADD CONSTRAINT
fk_material_movements_replacement_of_id_material_movements FOREIGN KEY(replacement_of_id)
REFERENCES cehub_supplier.material_movements (id) ON DELETE RESTRICT;
ALTER TABLE cehub_supplier.material_movements ADD CONSTRAINT uq_material_movement_transaction
UNIQUE (tenant_id, source_system, kind, transaction_reference, transaction_version);
ALTER TABLE cehub_supplier.material_movements ADD CONSTRAINT
uq_material_movements_replacement_of_id UNIQUE (replacement_of_id);
ALTER TABLE cehub_supplier.material_movements ADD CONSTRAINT
ck_material_movements_transaction_version_valid CHECK (transaction_version>0);
"""

OLD_FUNCTIONS = """
CREATE OR REPLACE FUNCTION cehub_supplier.material_issued_quantity(tenant uuid, allocation uuid)
RETURNS numeric LANGUAGE sql AS $$
SELECT coalesce(sum(quantity),0) FROM cehub_supplier.material_movements
WHERE tenant_id=tenant AND allocation_id=allocation AND kind='issued'
$$;
CREATE OR REPLACE FUNCTION cehub_supplier.material_allocation_stock_hold(
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
CREATE OR REPLACE FUNCTION cehub_supplier.material_allocation_demand_hold(tenant uuid, allocation
uuid)
RETURNS numeric LANGUAGE sql AS $$
SELECT a.quantity
-coalesce((SELECT sum(r.quantity) FROM cehub_supplier.material_allocation_releases r
WHERE r.tenant_id=tenant AND r.allocation_id=a.id),0)
-coalesce((SELECT sum(m.quantity) FROM cehub_supplier.material_movements m
WHERE m.tenant_id=tenant AND m.allocation_id=a.id AND m.kind IN ('returned','scrapped')),0)
FROM cehub_supplier.material_supply_allocations a WHERE a.tenant_id=tenant AND a.id=allocation
$$;
CREATE OR REPLACE FUNCTION cehub_supplier.material_issue_return_ids(tenant uuid, movement uuid)
RETURNS jsonb LANGUAGE sql AS $$
SELECT coalesce(jsonb_agg(id::text ORDER BY id),'[]'::jsonb)
FROM cehub_supplier.material_movements WHERE tenant_id=tenant
AND (id=movement OR (kind='returned' AND (parent_id=movement OR parent_id IN (
SELECT consumed.id FROM cehub_supplier.material_movements consumed
WHERE consumed.tenant_id=tenant AND consumed.parent_id=movement AND consumed.kind='consumed'
))))
$$;
CREATE OR REPLACE FUNCTION cehub_supplier.material_movement_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
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
AND project_id=NEW.project_id AND id=NEW.parent_id
AND (kind='issued' OR (NEW.kind IN ('returned','scrapped') AND kind='consumed'));
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
CREATE OR REPLACE FUNCTION cehub_supplier.material_reconciliation_guard() RETURNS trigger
LANGUAGE plpgsql
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
WHERE tenant_id=NEW.tenant_id AND id::text IN (
SELECT jsonb_array_elements_text(cehub_supplier.material_issue_return_ids(NEW.tenant_id,m.id))
);
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
"""

HELPERS = """
CREATE FUNCTION cehub_supplier.material_movement_effective(tenant uuid, movement uuid)
RETURNS boolean LANGUAGE sql STABLE AS $$
SELECT NOT EXISTS (SELECT 1 FROM cehub_supplier.material_movement_corrections
WHERE tenant_id=tenant AND movement_id=movement)
$$;
CREATE FUNCTION cehub_supplier.lock_material_transaction(
tenant uuid, source text, action text, reference text) RETURNS void LANGUAGE sql AS $$
SELECT pg_advisory_xact_lock(hashtextextended(jsonb_build_array(
'material_transaction',tenant,source,action,reference)::text,0))
$$;
CREATE FUNCTION cehub_supplier.material_correction_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE original cehub_supplier.material_movements%ROWTYPE;
a cehub_supplier.material_supply_allocations%ROWTYPE;
BEGIN
PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id
AND id=NEW.project_id FOR UPDATE;
SELECT * INTO STRICT original FROM cehub_supplier.material_movements
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.movement_id;
SELECT * INTO STRICT a FROM cehub_supplier.material_supply_allocations
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=original.allocation_id;
PERFORM cehub_supplier.lock_material_pool(NEW.tenant_id,a.source_system,
a.external_pool_id,a.external_item_id);
PERFORM cehub_supplier.lock_material_transaction(NEW.tenant_id,original.source_system,
original.kind,original.transaction_reference);
IF NOT cehub_supplier.material_movement_effective(NEW.tenant_id,original.id)
OR EXISTS (SELECT 1 FROM cehub_supplier.material_movements child
WHERE child.tenant_id=NEW.tenant_id AND child.parent_id=original.id
AND cehub_supplier.material_movement_effective(NEW.tenant_id,child.id)) THEN
RAISE EXCEPTION 'Correct effective children before correcting their original material record';
END IF;
IF NEW.snapshot#>>'{original,id}' IS DISTINCT FROM original.id::text
OR NEW.snapshot#>>'{evidence,id}' IS DISTINCT FROM NEW.evidence_id::text THEN
RAISE EXCEPTION 'Correction must retain original identity and actual evidence'; END IF;
RETURN NEW;
END $$;
CREATE TRIGGER material_correction_insert BEFORE INSERT
ON cehub_supplier.material_movement_corrections
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_correction_guard();
CREATE TRIGGER material_correction_immutable BEFORE UPDATE OR DELETE
ON cehub_supplier.material_movement_corrections
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
"""

FUNCTIONS = """
CREATE OR REPLACE FUNCTION cehub_supplier.material_issued_quantity(tenant uuid, allocation uuid)
RETURNS numeric LANGUAGE sql AS $$
SELECT coalesce(sum(quantity),0) FROM cehub_supplier.material_movements
WHERE tenant_id=tenant AND allocation_id=allocation AND kind='issued'
AND cehub_supplier.material_movement_effective(tenant,id)
$$;
CREATE OR REPLACE FUNCTION cehub_supplier.material_allocation_stock_hold(
tenant uuid, allocation uuid, supply uuid) RETURNS numeric LANGUAGE sql AS $$
SELECT a.quantity
-coalesce((SELECT sum(r.quantity) FROM cehub_supplier.material_allocation_releases r
WHERE r.tenant_id=tenant AND r.allocation_id=a.id),0)
-coalesce((SELECT sum(m.quantity) FROM cehub_supplier.material_movements m
WHERE m.tenant_id=tenant AND m.allocation_id=a.id AND m.kind='issued'
AND cehub_supplier.material_movement_effective(tenant,m.id)
AND EXISTS (SELECT 1 FROM cehub_supplier.material_movement_reconciliations rec
WHERE rec.tenant_id=tenant AND rec.movement_id=m.id AND rec.outcome='confirmed'
AND rec.supply_snapshot_id=supply
AND rec.snapshot->'movement_ids'=cehub_supplier.material_issue_return_ids(tenant,m.id)
AND NOT EXISTS (SELECT 1 FROM cehub_supplier.material_movement_reconciliations newer
WHERE newer.tenant_id=tenant AND newer.movement_id=m.id AND newer.version>rec.version))),0)
FROM cehub_supplier.material_supply_allocations a WHERE a.tenant_id=tenant AND a.id=allocation
$$;
CREATE OR REPLACE FUNCTION cehub_supplier.material_allocation_demand_hold(tenant uuid, allocation
uuid)
RETURNS numeric LANGUAGE sql AS $$
SELECT a.quantity
-coalesce((SELECT sum(r.quantity) FROM cehub_supplier.material_allocation_releases r
WHERE r.tenant_id=tenant AND r.allocation_id=a.id),0)
-coalesce((SELECT sum(m.quantity) FROM cehub_supplier.material_movements m
WHERE m.tenant_id=tenant AND m.allocation_id=a.id AND m.kind IN ('returned','scrapped')
AND cehub_supplier.material_movement_effective(tenant,m.id)),0)
FROM cehub_supplier.material_supply_allocations a WHERE a.tenant_id=tenant AND a.id=allocation
$$;
CREATE OR REPLACE FUNCTION cehub_supplier.material_issue_return_ids(tenant uuid, movement uuid)
RETURNS jsonb LANGUAGE sql AS $$
WITH source_rows AS (
 SELECT id FROM cehub_supplier.material_movements WHERE tenant_id=tenant
 AND (id=movement OR (kind='returned' AND (parent_id=movement OR parent_id IN (
  SELECT consumed.id FROM cehub_supplier.material_movements consumed
  WHERE consumed.tenant_id=tenant AND consumed.parent_id=movement AND consumed.kind='consumed'
 ))))
), identities AS (
 SELECT id FROM source_rows UNION ALL
 SELECT c.id FROM cehub_supplier.material_movement_corrections c
 WHERE c.tenant_id=tenant AND c.movement_id IN (SELECT id FROM source_rows)
)
SELECT coalesce(jsonb_agg(id::text ORDER BY id),'[]'::jsonb) FROM identities
$$;
CREATE OR REPLACE FUNCTION cehub_supplier.material_movement_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
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
PERFORM cehub_supplier.lock_material_transaction(NEW.tenant_id,NEW.source_system,
NEW.kind,NEW.transaction_reference);
IF EXISTS (SELECT 1 FROM cehub_supplier.material_movements existing
WHERE existing.tenant_id=NEW.tenant_id AND existing.source_system=NEW.source_system
AND existing.kind=NEW.kind AND existing.transaction_reference=NEW.transaction_reference
AND cehub_supplier.material_movement_effective(NEW.tenant_id,existing.id)) THEN
RAISE EXCEPTION 'The source transaction line already has an effective registration'; END IF;
SELECT coalesce(max(transaction_version),0)+1 INTO NEW.transaction_version
FROM cehub_supplier.material_movements WHERE tenant_id=NEW.tenant_id
AND source_system=NEW.source_system AND kind=NEW.kind
AND transaction_reference=NEW.transaction_reference;
IF NEW.replacement_of_id IS NOT NULL AND NOT EXISTS (
SELECT 1 FROM cehub_supplier.material_movements original
JOIN cehub_supplier.material_movement_corrections correction
ON correction.tenant_id=original.tenant_id AND correction.movement_id=original.id
WHERE original.tenant_id=NEW.tenant_id AND original.project_id=NEW.project_id
AND original.build_id=NEW.build_id AND original.id=NEW.replacement_of_id
) THEN RAISE EXCEPTION 'Replacement requires an original corrected record in the same build';
END IF;
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
IF NEW.replacement_of_id IS NULL AND NOT EXISTS (SELECT 1 FROM cehub_product.build_batches WHERE
tenant_id=NEW.tenant_id
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
AND project_id=NEW.project_id AND id=NEW.parent_id
AND cehub_supplier.material_movement_effective(NEW.tenant_id,id)
AND (kind='issued' OR (NEW.kind IN ('returned','scrapped') AND kind='consumed'));
IF parent.allocation_id<>NEW.allocation_id OR parent.build_id<>NEW.build_id
OR NEW.occurred_at<parent.occurred_at OR NEW.qualified<>parent.qualified THEN
RAISE EXCEPTION 'Disposition must retain the original issue, time and qualification basis'; END
IF;
SELECT parent.quantity-coalesce(sum(quantity),0) INTO remaining
FROM cehub_supplier.material_movements WHERE tenant_id=NEW.tenant_id AND parent_id=parent.id
AND cehub_supplier.material_movement_effective(NEW.tenant_id,id);
IF NEW.quantity>remaining THEN RAISE EXCEPTION 'Disposition exceeds remaining issued material';
END IF;
END IF;
RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION cehub_supplier.material_reconciliation_guard() RETURNS trigger
LANGUAGE plpgsql
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
IF NOT cehub_supplier.material_movement_effective(NEW.tenant_id,m.id) THEN
RAISE EXCEPTION 'Corrected issuance is historical and cannot be reconciled as effective'; END IF;
SELECT max(occurred_at) INTO occurred FROM cehub_supplier.material_movements
WHERE tenant_id=NEW.tenant_id AND id::text IN (
SELECT jsonb_array_elements_text(cehub_supplier.material_issue_return_ids(NEW.tenant_id,m.id))
);
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
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(HELPERS)
    op.execute(FUNCTIONS)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_supplier.material_movement_corrections) THEN
      RAISE EXCEPTION 'Historical correction evidence requires retention';
    END IF;
    END $$;
    """)
    op.execute(OLD_FUNCTIONS)
    op.execute("""
    ALTER TABLE cehub_supplier.material_movements
    DROP COLUMN replacement_of_id, DROP COLUMN transaction_version;
    ALTER TABLE cehub_supplier.material_movements ADD CONSTRAINT uq_material_movement_transaction
    UNIQUE (tenant_id,source_system,kind,transaction_reference);
    DROP TABLE cehub_supplier.material_movement_corrections;
    DROP FUNCTION cehub_supplier.material_correction_guard();
    DROP FUNCTION cehub_supplier.material_movement_effective(uuid,uuid);
    DROP FUNCTION cehub_supplier.lock_material_transaction(uuid,text,text,text);
    """)
