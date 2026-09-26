"""Versioned human mapping corrections and retained import draft ancestry.
Revision ID: 0180_report_mapping_revisions
Revises: 0179_test_configuration_facts
"""

import sqlalchemy as sa
from alembic import op

revision = "0180_report_mapping_revisions"
down_revision = "0179_test_configuration_facts"
branch_labels = None
depends_on = None
DDL = [
    """
ALTER TABLE cehub_quality.test_report_import_batches
 ADD COLUMN mapping_snapshot jsonb, ADD COLUMN parser_version varchar(64),
 ADD COLUMN workbook_layout varchar(32), ADD COLUMN parent_batch_id uuid,
 ADD COLUMN superseded_by_batch_id uuid, ADD COLUMN remap_request_id uuid,
 ADD COLUMN remap_request_digest varchar(64), ADD COLUMN remap_reason text,
 DROP CONSTRAINT ck_test_report_import_batches_mapping_source_allowed
""",
    """
ALTER TABLE cehub_quality.test_report_import_batches ADD CONSTRAINT
ck_test_report_import_batches_mapping_snapshot_object CHECK (mapping_snapshot IS NULL OR
jsonb_typeof(mapping_snapshot) = 'object')
""",
    """
ALTER TABLE cehub_quality.test_report_import_batches ADD CONSTRAINT
ck_test_report_import_batches_mapping_source_allowed CHECK (mapping_source IN ('mapping',
'model', 'human'))
""",
    """
ALTER TABLE cehub_quality.test_report_import_batches ADD CONSTRAINT
ck_test_report_import_batches_remap_receipt CHECK ((parent_batch_id IS NULL AND remap_request_id
IS NULL AND remap_request_digest IS NULL AND remap_reason IS NULL) OR (parent_batch_id IS NOT
NULL AND remap_request_id IS NOT NULL AND remap_request_digest IS NOT NULL AND remap_reason IS
NOT NULL AND remap_request_digest ~ '^[0-9a-f]{64}$' AND length(trim(remap_reason)) BETWEEN 1
AND 2000))
""",
    """
ALTER TABLE cehub_quality.test_report_import_batches ADD CONSTRAINT fk_import_parent_batch
FOREIGN KEY(tenant_id, parent_batch_id) REFERENCES cehub_quality.test_report_import_batches
(tenant_id, id) ON DELETE RESTRICT
""",
    """
ALTER TABLE cehub_quality.test_report_import_batches ADD CONSTRAINT fk_import_successor_batch
FOREIGN KEY(tenant_id, superseded_by_batch_id) REFERENCES
cehub_quality.test_report_import_batches (tenant_id, id) ON DELETE RESTRICT
""",
    """
ALTER TABLE cehub_quality.test_report_import_batches ADD CONSTRAINT uq_import_remap_request
UNIQUE (tenant_id, parent_batch_id, remap_request_id)
""",
]


def upgrade() -> None:
    for statement in DDL:
        op.execute(statement)
    op.execute(GUARDS)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""
      SELECT EXISTS(SELECT 1 FROM cehub_quality.test_report_import_batches
        WHERE mapping_snapshot IS NOT NULL OR parent_batch_id IS NOT NULL)
    """)
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard import mapping versions and provenance")
    op.execute("""
      DROP TRIGGER guard_retired_import_run ON cehub_quality.test_runs;
      DROP FUNCTION cehub_quality.guard_retired_import_run();
      DROP TRIGGER guard_import_revision ON cehub_quality.test_report_import_batches;
      DROP FUNCTION cehub_quality.guard_import_revision();
      ALTER TABLE cehub_quality.test_report_import_batches
       DROP CONSTRAINT fk_import_parent_batch, DROP CONSTRAINT fk_import_successor_batch,
       DROP CONSTRAINT uq_import_remap_request,
       DROP CONSTRAINT ck_test_report_import_batches_remap_receipt,
       DROP CONSTRAINT ck_test_report_import_batches_mapping_snapshot_object,
       DROP CONSTRAINT ck_test_report_import_batches_mapping_source_allowed,
       DROP COLUMN mapping_snapshot, DROP COLUMN parser_version, DROP COLUMN workbook_layout,
       DROP COLUMN parent_batch_id, DROP COLUMN superseded_by_batch_id,
       DROP COLUMN remap_request_id, DROP COLUMN remap_request_digest, DROP COLUMN remap_reason,
       ADD CONSTRAINT ck_test_report_import_batches_mapping_source_allowed
         CHECK (mapping_source IN ('mapping','model'));
    """)


GUARDS = r"""
CREATE FUNCTION cehub_quality.guard_import_revision() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE p cehub_quality.test_report_import_batches%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Import batch history is retained' USING ERRCODE='23514';
 END IF;
 IF TG_OP='UPDATE' THEN
  IF ROW(NEW.tenant_id,NEW.project_id,NEW.plan_id,NEW.document_id,NEW.parent_batch_id,
         NEW.remap_request_id,NEW.remap_request_digest,NEW.remap_reason,NEW.mapping_snapshot,
         NEW.parser_version,NEW.workbook_layout,NEW.created_run_ids,NEW.skipped_rows,
         NEW.proposed_mapping,NEW.mapping_source,NEW.template_fingerprint,NEW.created_by_user_id)
    IS DISTINCT FROM
     ROW(OLD.tenant_id,OLD.project_id,OLD.plan_id,OLD.document_id,OLD.parent_batch_id,
         OLD.remap_request_id,OLD.remap_request_digest,OLD.remap_reason,OLD.mapping_snapshot,
         OLD.parser_version,OLD.workbook_layout,OLD.created_run_ids,OLD.skipped_rows,
         OLD.proposed_mapping,OLD.mapping_source,OLD.template_fingerprint,OLD.created_by_user_id)
   OR (OLD.superseded_by_batch_id IS NOT NULL AND
       NEW.superseded_by_batch_id IS DISTINCT FROM OLD.superseded_by_batch_id) THEN
   RAISE EXCEPTION 'Reparse creates a new batch; old inputs stay fixed' USING ERRCODE='23514';
  END IF;
 END IF;
 IF TG_OP='INSERT' AND NEW.parent_batch_id IS NOT NULL THEN
  SELECT * INTO p FROM cehub_quality.test_report_import_batches WHERE tenant_id=NEW.tenant_id
   AND project_id=NEW.project_id AND plan_id=NEW.plan_id AND document_id=NEW.document_id
   AND id=NEW.parent_batch_id;
  IF p.id IS NULL OR p.status<>'parsed' OR p.superseded_by_batch_id IS NOT NULL
    OR p.id=NEW.id OR NEW.mapping_source<>'human' OR NEW.mapping_snapshot IS NULL
    OR NEW.workbook_layout<>'flat_v1' THEN
   RAISE EXCEPTION 'Mapping revision requires its current unconfirmed source' USING ERRCODE='23514';
  END IF;
 END IF;
 IF NEW.superseded_by_batch_id IS NOT NULL AND
  (NEW.status<>'parsed' OR NOT EXISTS(SELECT 1 FROM cehub_quality.test_report_import_batches n
   WHERE n.tenant_id=NEW.tenant_id AND n.project_id=NEW.project_id AND n.plan_id=NEW.plan_id
    AND n.document_id=NEW.document_id AND n.parent_batch_id=NEW.id AND
n.id=NEW.superseded_by_batch_id)) THEN
  RAISE EXCEPTION 'Retired draft requires its actual successor and cannot be confirmed' USING
ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_import_revision BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_quality.test_report_import_batches FOR EACH ROW
 EXECUTE FUNCTION cehub_quality.guard_import_revision();

CREATE FUNCTION cehub_quality.guard_retired_import_run() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM cehub_quality.test_report_import_batches b WHERE b.tenant_id=OLD.tenant_id
   AND b.project_id=OLD.project_id AND b.superseded_by_batch_id IS NOT NULL
   AND b.created_run_ids ? OLD.id::text) THEN
  RAISE EXCEPTION 'Superseded import runs are retained for comparison' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_retired_import_run BEFORE UPDATE ON cehub_quality.test_runs
 FOR EACH ROW EXECUTE FUNCTION cehub_quality.guard_retired_import_run();
"""
