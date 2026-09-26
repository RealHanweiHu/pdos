"""Immutable ECR scope to compliance matrix human review receipts."""

from alembic import op

revision = "0305_change_compliance_reviews"
down_revision = "0304_supplier_compliance_records"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_supplier.change_compliance_reviews (
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
	ecr_id UUID NOT NULL,
	record_id UUID NOT NULL,
	matrix_version_id UUID NOT NULL,
	version INTEGER NOT NULL,
	outcome VARCHAR(32) NOT NULL,
	CONSTRAINT pk_change_compliance_reviews PRIMARY KEY (id),
        CONSTRAINT fk_change_compliance_reviews_tenant_id_documents FOREIGN KEY(tenant_id,
project_id, evidence_id) REFERENCES cehub_project.documents (tenant_id, project_id, id) ON DELETE
RESTRICT,
        CONSTRAINT fk_change_compliance_reviews_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_change_compliance_reviews_record_valid CHECK (btrim(reason)<>'' AND
request_digest ~ '^[0-9a-f]{64}$' AND jsonb_typeof(snapshot)='object'),
        CONSTRAINT fk_change_compliance_reviews_tenant_id_engineering_chan_7ac9 FOREIGN
KEY(tenant_id, project_id, ecr_id) REFERENCES cehub_product.engineering_change_requests
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_change_compliance_reviews_matrix_version_id_supplier_28d3 FOREIGN
KEY(matrix_version_id) REFERENCES cehub_supplier.supplier_compliance_records (id) ON DELETE
RESTRICT,
        CONSTRAINT uq_change_compliance_version UNIQUE (tenant_id, project_id, ecr_id, record_id,
version),
	CONSTRAINT uq_change_compliance_request UNIQUE (tenant_id, created_by_user_id, request_id),
        CONSTRAINT ck_change_compliance_reviews_change_compliance_review_valid CHECK (version>0
AND outcome IN ('needs_recheck','not_affected','reviewed'))
)

;
"""
GUARDS = """
CREATE FUNCTION cehub_supplier.change_compliance_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous integer; matrix cehub_supplier.supplier_compliance_records%ROWTYPE;
scope_id uuid;
BEGIN
PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id
AND id=NEW.project_id FOR UPDATE;
SELECT coalesce(max(version),0) INTO previous FROM cehub_supplier.change_compliance_reviews
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND ecr_id=NEW.ecr_id
AND record_id=NEW.record_id;
SELECT * INTO STRICT matrix FROM cehub_supplier.supplier_compliance_records
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.matrix_version_id;
IF matrix.record_id<>NEW.record_id OR NEW.version<>previous+1 OR EXISTS (
SELECT 1 FROM cehub_supplier.supplier_compliance_records WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND record_id=NEW.record_id AND version>matrix.version) THEN
RAISE EXCEPTION 'Change compliance review requires the latest matrix and consecutive receipt';
END IF;
SELECT id INTO scope_id FROM cehub_product.change_impact_scope_versions
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND ecr_id=NEW.ecr_id
ORDER BY revision_number DESC LIMIT 1;
IF scope_id IS NULL OR NEW.snapshot#>>'{basis,scope_id}' IS DISTINCT FROM scope_id::text
OR NEW.snapshot#>>'{basis,matrix,id}' IS DISTINCT FROM matrix.id::text
OR NEW.snapshot#>>'{evidence,id}' IS DISTINCT FROM NEW.evidence_id::text THEN
RAISE EXCEPTION 'Change compliance review must retain its current scope and actual evidence';
END IF;
RETURN NEW;
END $$;
CREATE TRIGGER change_compliance_insert BEFORE INSERT ON cehub_supplier.change_compliance_reviews
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.change_compliance_guard();
CREATE TRIGGER change_compliance_immutable BEFORE UPDATE OR DELETE
ON cehub_supplier.change_compliance_reviews
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_supplier.change_compliance_reviews) THEN
    RAISE EXCEPTION 'Change compliance review history requires retention'; END IF;
    END $$;
    DROP TABLE cehub_supplier.change_compliance_reviews;
    DROP FUNCTION cehub_supplier.change_compliance_guard();
    """)
