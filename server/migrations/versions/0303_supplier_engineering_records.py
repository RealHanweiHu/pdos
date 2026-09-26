"""Supplier engineering evidence records, immutable revisions and original commitments."""

from alembic import op

revision = "0303_supplier_engineering_records"
down_revision = "0302_material_movement_corrections"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_supplier.supplier_engineering_records (
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
	supplier_id UUID NOT NULL,
	record_id UUID NOT NULL,
	version INTEGER NOT NULL,
	kind VARCHAR(32) NOT NULL,
	source_reference VARCHAR(256) NOT NULL,
	status VARCHAR(16) NOT NULL,
	payload JSONB NOT NULL,
	CONSTRAINT pk_supplier_engineering_records PRIMARY KEY (id),
        CONSTRAINT fk_supplier_engineering_records_tenant_id_documents FOREIGN KEY(tenant_id,
project_id, evidence_id) REFERENCES cehub_project.documents (tenant_id, project_id, id) ON DELETE
RESTRICT,
        CONSTRAINT fk_supplier_engineering_records_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_supplier_engineering_records_record_valid CHECK (btrim(reason)<>'' AND
request_digest ~ '^[0-9a-f]{64}$' AND jsonb_typeof(snapshot)='object'),
        CONSTRAINT fk_supplier_engineering_records_tenant_id_suppliers FOREIGN KEY(tenant_id,
supplier_id) REFERENCES cehub_supplier.suppliers (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_supplier_engineering_version UNIQUE (tenant_id, project_id, record_id, version),
	CONSTRAINT uq_supplier_engineering_request UNIQUE (tenant_id, created_by_user_id, request_id),
        CONSTRAINT ck_supplier_engineering_records_engineering_record_valid CHECK (version>0 AND
kind IN ('sample_delivery','technical_response','engineering_failure') AND status IN
('active','withdrawn') AND btrim(source_reference)<>'' AND jsonb_typeof(payload)='object')
)

;
CREATE INDEX ix_supplier_engineering_profile ON cehub_supplier.supplier_engineering_records
(tenant_id, project_id, supplier_id, record_id, version);
"""
GUARDS = """
CREATE FUNCTION cehub_supplier.supplier_engineering_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous cehub_supplier.supplier_engineering_records%ROWTYPE;
key text; fact jsonb; expected_first jsonb;
BEGIN
PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id
AND id=NEW.project_id FOR UPDATE;
SELECT * INTO previous FROM cehub_supplier.supplier_engineering_records
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND record_id=NEW.record_id
ORDER BY version DESC LIMIT 1;
IF NEW.version<>coalesce(previous.version,0)+1 OR
(previous.id IS NOT NULL AND (previous.supplier_id<>NEW.supplier_id OR
previous.kind<>NEW.kind OR previous.source_reference<>NEW.source_reference)) THEN
RAISE EXCEPTION 'Supplier engineering revision must retain original supplier and source'; END IF;
IF EXISTS (SELECT 1 FROM cehub_supplier.supplier_engineering_records
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND supplier_id=NEW.supplier_id
AND kind=NEW.kind AND source_reference=NEW.source_reference AND record_id<>NEW.record_id) THEN
RAISE EXCEPTION 'Original source already has a supplier engineering record'; END IF;
IF NEW.snapshot#>>'{sources,evidence,id}' IS DISTINCT FROM NEW.evidence_id::text
OR NEW.snapshot#>>'{supplier,id}' IS DISTINCT FROM NEW.supplier_id::text
OR NEW.snapshot->'command' IS DISTINCT FROM NEW.payload THEN
RAISE EXCEPTION 'Supplier record must match its original source preview'; END IF;
FOREACH key IN ARRAY ARRAY['requested','promised','responded','received','detected'] LOOP
fact := NEW.payload->key;
IF fact IS NOT NULL AND fact<>'null'::jsonb THEN
IF NOT EXISTS (SELECT 1 FROM cehub_project.documents WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=(fact->>'evidence_id')::uuid)
OR (key<>'promised' AND (fact->>'at')::timestamptz>clock_timestamp()) THEN
RAISE EXCEPTION 'Engineering milestones require actual project evidence and time'; END IF;
END IF;
END LOOP;
IF NEW.payload->>'build_id' IS NOT NULL AND NOT EXISTS (
SELECT 1 FROM cehub_product.build_batches WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=(NEW.payload->>'build_id')::uuid) THEN
RAISE EXCEPTION 'Sample build must be in the current project'; END IF;
IF NEW.payload->>'issue_id' IS NOT NULL AND NOT EXISTS (
SELECT 1 FROM cehub_project.issues WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=(NEW.payload->>'issue_id')::uuid) THEN
RAISE EXCEPTION 'Engineering issue must be in the current project'; END IF;
IF NEW.payload->>'test_run_id' IS NOT NULL AND NOT EXISTS (
SELECT 1 FROM cehub_quality.test_runs WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=(NEW.payload->>'test_run_id')::uuid) THEN
RAISE EXCEPTION 'Engineering test must be in the current project'; END IF;
expected_first := coalesce(nullif(previous.snapshot->'first_promise','null'::jsonb),
NEW.snapshot#>'{sources,promised}', 'null'::jsonb);
IF NEW.snapshot->'first_promise' IS DISTINCT FROM expected_first THEN
RAISE EXCEPTION 'Original commitment must remain available across revisions'; END IF;
RETURN NEW;
END $$;
CREATE TRIGGER supplier_engineering_insert BEFORE INSERT
ON cehub_supplier.supplier_engineering_records
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.supplier_engineering_guard();
CREATE TRIGGER supplier_engineering_immutable BEFORE UPDATE OR DELETE
ON cehub_supplier.supplier_engineering_records
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_supplier.supplier_engineering_records) THEN
    RAISE EXCEPTION 'Supplier engineering history requires retention'; END IF;
    END $$;
    DROP TABLE cehub_supplier.supplier_engineering_records;
    DROP FUNCTION cehub_supplier.supplier_engineering_guard();
    """)
