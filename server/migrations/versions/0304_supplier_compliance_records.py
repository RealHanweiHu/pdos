"""Versioned supplier/project market regulation evidence matrix."""

from alembic import op

revision = "0304_supplier_compliance_records"
down_revision = "0303_supplier_engineering_records"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_supplier.supplier_compliance_records (
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
	record_id UUID NOT NULL,
	version INTEGER NOT NULL,
	supplier_id UUID,
	payload JSONB NOT NULL,
	status VARCHAR(16) NOT NULL,
	CONSTRAINT pk_supplier_compliance_records PRIMARY KEY (id),
        CONSTRAINT fk_supplier_compliance_records_tenant_id_documents FOREIGN KEY(tenant_id,
project_id, evidence_id) REFERENCES cehub_project.documents (tenant_id, project_id, id) ON DELETE
RESTRICT,
        CONSTRAINT fk_supplier_compliance_records_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_supplier_compliance_records_record_valid CHECK (btrim(reason)<>'' AND
request_digest ~ '^[0-9a-f]{64}$' AND jsonb_typeof(snapshot)='object'),
        CONSTRAINT fk_supplier_compliance_records_tenant_id_suppliers FOREIGN KEY(tenant_id,
supplier_id) REFERENCES cehub_supplier.suppliers (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_supplier_compliance_version UNIQUE (tenant_id, project_id, record_id, version),
	CONSTRAINT uq_supplier_compliance_request UNIQUE (tenant_id, created_by_user_id, request_id),
        CONSTRAINT ck_supplier_compliance_records_compliance_record_valid CHECK (version>0 AND
status IN ('active','withdrawn') AND jsonb_typeof(payload)='object')
)

;
CREATE INDEX ix_supplier_compliance_project ON cehub_supplier.supplier_compliance_records
(tenant_id, project_id, record_id, version);
"""

GUARDS = """
CREATE FUNCTION cehub_supplier.supplier_compliance_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous integer; key text; identity uuid;
BEGIN
PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id
AND id=NEW.project_id FOR UPDATE;
SELECT coalesce(max(version),0) INTO previous FROM cehub_supplier.supplier_compliance_records
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND record_id=NEW.record_id;
IF NEW.version<>previous+1 OR (previous=0 AND NEW.status='withdrawn') THEN
RAISE EXCEPTION 'Compliance records require consecutive original revisions'; END IF;
IF NEW.snapshot->'command' IS DISTINCT FROM NEW.payload
OR NEW.snapshot#>>'{sources,evidence_id,id}' IS DISTINCT FROM NEW.evidence_id::text
OR NEW.payload->>'supplier_id' IS DISTINCT FROM NEW.supplier_id::text THEN
RAISE EXCEPTION 'Compliance matrix must retain the actual preview and evidence'; END IF;
FOREACH key IN ARRAY ARRAY['regulation_evidence_id','conclusion_evidence_id'] LOOP
IF NEW.payload->>key IS NOT NULL AND NOT EXISTS (
SELECT 1 FROM cehub_project.documents WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=(NEW.payload->>key)::uuid) THEN
RAISE EXCEPTION 'Compliance evidence must belong to the actual project'; END IF;
END LOOP;
FOR identity IN SELECT value::uuid FROM jsonb_array_elements_text(NEW.payload->'certification_ids')
LOOP
IF NOT EXISTS (SELECT 1 FROM cehub_quality.certifications WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=identity) THEN
RAISE EXCEPTION 'Compliance relationship must belong to the actual project'; END IF;
END LOOP;
FOR identity IN SELECT value::uuid FROM jsonb_array_elements_text(NEW.payload->'build_ids') LOOP
IF NOT EXISTS (SELECT 1 FROM cehub_product.build_batches WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=identity) THEN
RAISE EXCEPTION 'Compliance relationship must belong to the actual project'; END IF;
END LOOP;
FOR identity IN SELECT value::uuid FROM jsonb_array_elements_text(NEW.payload->'sample_ids') LOOP
IF NOT EXISTS (SELECT 1 FROM cehub_product.samples WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=identity) THEN
RAISE EXCEPTION 'Compliance relationship must belong to the actual project'; END IF;
END LOOP;
FOR identity IN SELECT value::uuid FROM jsonb_array_elements_text(NEW.payload->'bom_item_ids') LOOP
IF NOT EXISTS (SELECT 1 FROM cehub_product.development_bom_items WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=identity) THEN
RAISE EXCEPTION 'Compliance relationship must belong to the actual project'; END IF;
END LOOP;
FOR identity IN SELECT value::uuid FROM jsonb_array_elements_text(NEW.payload->'specification_ids')
LOOP
IF NOT EXISTS (SELECT 1 FROM cehub_product.specifications WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=identity) THEN
RAISE EXCEPTION 'Compliance relationship must belong to the actual project'; END IF;
END LOOP;
RETURN NEW;
END $$;
CREATE TRIGGER supplier_compliance_insert BEFORE INSERT
ON cehub_supplier.supplier_compliance_records
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.supplier_compliance_guard();
CREATE TRIGGER supplier_compliance_immutable BEFORE UPDATE OR DELETE
ON cehub_supplier.supplier_compliance_records
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();

"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_supplier.supplier_compliance_records) THEN
    RAISE EXCEPTION 'Compliance evidence history requires retention'; END IF;
    END $$;
    DROP TABLE cehub_supplier.supplier_compliance_records;
    DROP FUNCTION cehub_supplier.supplier_compliance_guard();
    """)
