"""Preserve ERP XLSX source rows with atomic actual cost ledger receipts."""

from alembic import op

revision = "0326_cost_imports"
down_revision = "0325_cost_backtests"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_cost.cost_import_batches (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        document_id UUID NOT NULL,
        source_system VARCHAR(128) NOT NULL,
        source_version VARCHAR(120) NOT NULL,
        algorithm VARCHAR(64) NOT NULL,
        payload JSONB NOT NULL,
        snapshot JSONB NOT NULL,
        receipts JSONB NOT NULL,
        created_by_user_id UUID NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT pk_cost_import_batches PRIMARY KEY (id),
        CONSTRAINT fk_cost_import_batches_tenant_id_documents FOREIGN KEY(tenant_id,
project_id, document_id) REFERENCES cehub_project.documents (tenant_id, project_id, id) ON
DELETE RESTRICT,
        CONSTRAINT fk_cost_import_batches_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT uq_cost_import_scope UNIQUE (tenant_id, project_id, id),
        CONSTRAINT uq_cost_import_source UNIQUE (tenant_id, project_id, source_system,
source_version),
        CONSTRAINT uq_cost_import_replay UNIQUE (tenant_id, created_by_user_id, request_id),
        CONSTRAINT ck_cost_import_batches_shape CHECK (request_digest ~ '^[0-9a-f]{64}$' AND
btrim(source_system)<>'' AND btrim(source_version)<>'' AND jsonb_typeof(payload)='object' AND
jsonb_typeof(snapshot)='object' AND jsonb_typeof(receipts)='array')
)

;
CREATE INDEX ix_cost_import_history ON cehub_cost.cost_import_batches (tenant_id, project_id,
created_at, id);
CREATE TABLE cehub_cost.cost_import_rows (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        batch_id UUID NOT NULL,
        row_number INTEGER NOT NULL,
        input_id UUID NOT NULL,
        CONSTRAINT pk_cost_import_rows PRIMARY KEY (id),
        CONSTRAINT fk_cost_import_rows_tenant_id_cost_import_batches FOREIGN KEY(tenant_id,
project_id, batch_id) REFERENCES cehub_cost.cost_import_batches (tenant_id, project_id, id) ON
DELETE RESTRICT,
        CONSTRAINT fk_cost_import_rows_tenant_id_cost_inputs FOREIGN KEY(tenant_id,
project_id, input_id) REFERENCES cehub_cost.cost_inputs (tenant_id, project_id, id) ON DELETE
RESTRICT,
        CONSTRAINT uq_cost_import_row UNIQUE (tenant_id, batch_id, row_number),
        CONSTRAINT uq_cost_import_input UNIQUE (tenant_id, input_id),
        CONSTRAINT ck_cost_import_rows_row_number CHECK (row_number BETWEEN 2 AND 600)
)

;
"""

GUARD = """
CREATE FUNCTION cehub_cost.guard_cost_import_batch() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE receipt jsonb; line jsonb; input cehub_cost.cost_inputs;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id
 FOR UPDATE;
 IF (NEW.algorithm='cost-actual.xlsx.v1' AND NEW.snapshot->>'algorithm'=NEW.algorithm
  AND NEW.snapshot->>'ready'='true' AND NEW.payload->'draft'=NEW.snapshot->'command'
  AND NEW.payload->>'expected_digest'=NEW.snapshot->>'digest'
  AND NEW.payload->>'evidence_checked'='true' AND NEW.payload->>'mapping_checked'='true'
  AND NEW.payload->>'exclusions_checked'='true'
  AND NEW.snapshot#>>'{document,id}'=NEW.document_id::text
  AND NEW.snapshot#>>'{command,document_id}'=NEW.document_id::text
  AND NEW.snapshot#>>'{command,source_system}'=NEW.source_system
  AND NEW.snapshot#>>'{command,source_version}'=NEW.source_version
  AND NEW.snapshot#>>'{author,id}'=NEW.created_by_user_id::text
  AND jsonb_array_length(NEW.receipts)>0
  AND jsonb_array_length(NEW.receipts)=(SELECT count(*) FROM
   jsonb_array_elements(NEW.snapshot->'lines') l WHERE l->>'excluded'='false')
  AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.snapshot->'lines') l
   WHERE l->>'error' IS NOT NULL)) IS NOT TRUE THEN
  RAISE EXCEPTION 'Cost import requires checked original rows and complete actual receipts';
 END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.receipts) v GROUP BY v->>'row'
  HAVING count(*)>1) OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.receipts) v
  GROUP BY v->>'input_id' HAVING count(*)>1) THEN
  RAISE EXCEPTION 'Cost import rows and ledger versions cannot be repeated'; END IF;
 FOR receipt IN SELECT * FROM jsonb_array_elements(NEW.receipts) LOOP
  SELECT v INTO line FROM jsonb_array_elements(NEW.snapshot->'lines') v
   WHERE v->>'row'=receipt->>'row';
  SELECT * INTO input FROM cehub_cost.cost_inputs WHERE tenant_id=NEW.tenant_id
   AND project_id=NEW.project_id AND id::text=receipt->>'input_id';
  IF (input.stage='actual' AND input.kind='price' AND input.version=1
   AND input.evidence_id=NEW.document_id AND input.created_by_user_id=NEW.created_by_user_id
   AND input.payload=line->'draft' AND input.snapshot=line#>'{preview,basis}'
   AND input.record_id::text=receipt->>'record_id' AND line->>'excluded'='false'
   AND input.payload->>'source_line'=receipt->>'source_line'
   AND input.payload->>'source_reference'=NEW.source_system||'/'||NEW.source_version
   AND line->>'record_id'=input.record_id::text) IS NOT TRUE THEN
   RAISE EXCEPTION 'Cost import must point to the actual original ledger version'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_cost.guard_cost_import_row() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_cost.cost_import_batches b,
  LATERAL jsonb_array_elements(b.receipts) r WHERE b.tenant_id=NEW.tenant_id
  AND b.project_id=NEW.project_id AND b.id=NEW.batch_id
  AND (r->>'row')::integer=NEW.row_number AND r->>'input_id'=NEW.input_id::text) THEN
  RAISE EXCEPTION 'Imported row must belong to the original receipt'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_cost.require_cost_import_rows() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF (SELECT count(*) FROM cehub_cost.cost_import_rows WHERE tenant_id=NEW.tenant_id
  AND project_id=NEW.project_id AND batch_id=NEW.id)<>jsonb_array_length(NEW.receipts) THEN
  RAISE EXCEPTION 'Cost import and all scoped source row links must commit together'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER cost_import_batch_guard BEFORE INSERT ON cehub_cost.cost_import_batches
FOR EACH ROW EXECUTE FUNCTION cehub_cost.guard_cost_import_batch();
CREATE TRIGGER cost_import_row_guard BEFORE INSERT ON cehub_cost.cost_import_rows
FOR EACH ROW EXECUTE FUNCTION cehub_cost.guard_cost_import_row();
CREATE CONSTRAINT TRIGGER cost_import_complete AFTER INSERT ON cehub_cost.cost_import_batches
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION cehub_cost.require_cost_import_rows();
CREATE TRIGGER cost_import_batch_immutable BEFORE UPDATE OR DELETE ON cehub_cost.cost_import_batches
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
CREATE TRIGGER cost_import_row_immutable BEFORE UPDATE OR DELETE ON cehub_cost.cost_import_rows
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
REVOKE ALL ON cehub_cost.cost_import_batches, cehub_cost.cost_import_rows FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_cost.guard_cost_import_batch(),
cehub_cost.guard_cost_import_row(), cehub_cost.require_cost_import_rows() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
     IF EXISTS(SELECT 1 FROM cehub_cost.cost_import_batches) THEN
      RAISE EXCEPTION 'Retain ERP cost originals and import receipts'; END IF;
    END $$;
    DROP TABLE cehub_cost.cost_import_rows;
    DROP TABLE cehub_cost.cost_import_batches;
    DROP FUNCTION cehub_cost.require_cost_import_rows();
    DROP FUNCTION cehub_cost.guard_cost_import_row();
    DROP FUNCTION cehub_cost.guard_cost_import_batch();
    """)
