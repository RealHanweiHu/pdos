"""Evidence-bound returns and scrap after consumption, retaining original issue lineage."""

from alembic import op

revision = "0301_material_consumption_dispositions"
down_revision = "0300_material_movements"
branch_labels = None
depends_on = None

OLD_FUNCTIONS = """
CREATE OR REPLACE FUNCTION cehub_supplier.material_issue_return_ids(tenant uuid, movement uuid)
RETURNS jsonb LANGUAGE sql AS $$
SELECT coalesce(jsonb_agg(id::text ORDER BY id),'[]'::jsonb)
FROM cehub_supplier.material_movements WHERE tenant_id=tenant
AND (id=movement OR (parent_id=movement AND kind='returned'))
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
"""

FUNCTIONS = """
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


def upgrade() -> None:
    op.execute(FUNCTIONS)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
    IF EXISTS (
      SELECT 1 FROM cehub_supplier.material_movements child
      JOIN cehub_supplier.material_movements parent
        ON parent.tenant_id=child.tenant_id AND parent.id=child.parent_id
      WHERE parent.kind='consumed'
    ) THEN
      RAISE EXCEPTION 'Post-consumption disposition evidence requires retention';
    END IF;
    END $$;
    """)
    op.execute(OLD_FUNCTIONS)
