"""Resolve missing report samples with named receipts and original NPI creation.
Revision ID: 0181_report_sample_resolution
Revises: 0180_report_mapping_revisions
"""

import sqlalchemy as sa
from alembic import op

revision = "0181_report_sample_resolution"
down_revision = "0180_report_mapping_revisions"
branch_labels = None
depends_on = None
DDL = [
    """
ALTER TABLE cehub_product.samples ADD COLUMN built_at_precision varchar(16) NOT NULL DEFAULT
'unknown'
""",
    """
CREATE TABLE cehub_quality.test_import_sample_resolutions (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    batch_id UUID NOT NULL,
    request_id UUID NOT NULL,
    request_digest VARCHAR(64) NOT NULL,
    sample_id UUID NOT NULL,
    run_ids JSONB NOT NULL,
    created_sample BOOLEAN NOT NULL,
    reason TEXT NOT NULL,
    created_by_user_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_test_import_sample_resolutions PRIMARY KEY (id),
    CONSTRAINT uq_import_sample_resolution_request UNIQUE (tenant_id, batch_id, request_id),
    CONSTRAINT uq_import_sample_resolution_scope UNIQUE (tenant_id, project_id, id),
    CONSTRAINT fk_test_import_sample_resolutions_tenant_id_test_report_fafc FOREIGN
KEY(tenant_id, batch_id) REFERENCES cehub_quality.test_report_import_batches (tenant_id, id) ON
DELETE RESTRICT,
    CONSTRAINT fk_test_import_sample_resolutions_tenant_id_samples FOREIGN KEY(tenant_id,
project_id, sample_id) REFERENCES cehub_product.samples (tenant_id, project_id, id) ON DELETE
RESTRICT,
    CONSTRAINT fk_test_import_sample_resolutions_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_test_import_sample_resolutions_run_ids_valid CHECK (jsonb_typeof(run_ids) =
'array' AND jsonb_array_length(run_ids) BETWEEN 1 AND 100),
    CONSTRAINT ck_test_import_sample_resolutions_input_valid CHECK (request_digest ~
'^[0-9a-f]{64}$' AND length(trim(reason)) BETWEEN 1 AND 2000)
)
""",
    """
ALTER TABLE cehub_product.samples ADD CONSTRAINT ck_samples_built_at_precision_allowed CHECK
(built_at_precision IN ('unknown', 'day', 'instant'))
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
      SELECT EXISTS(SELECT 1 FROM cehub_quality.test_import_sample_resolutions)
       OR EXISTS(SELECT 1 FROM cehub_product.samples WHERE built_at_precision<>'unknown')
    """)
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard sample resolution and actual build-date evidence")
    op.execute("""
      DROP TRIGGER guard_report_sample_source ON cehub_quality.test_runs;
      DROP FUNCTION cehub_quality.guard_report_sample_source();
      DROP TABLE cehub_quality.test_import_sample_resolutions;
      DROP FUNCTION cehub_quality.guard_import_sample_resolution();
      ALTER TABLE cehub_product.samples DROP CONSTRAINT ck_samples_built_at_precision_allowed,
       DROP COLUMN built_at_precision;
    """)
    op.execute(PREVIOUS_GUARD)


GUARDS = r"""
CREATE OR REPLACE FUNCTION cehub_quality.guard_test_run_facts() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='UPDATE' AND
  (OLD.sample_configuration_revision_id IS DISTINCT FROM NEW.sample_configuration_revision_id
   OR OLD.sample_id IS DISTINCT FROM NEW.sample_id) THEN
  IF NOT (OLD.draft_state='draft' AND NEW.draft_state='draft' AND OLD.sample_id IS NULL
    AND OLD.sample_configuration_revision_id IS NULL AND NEW.sample_id IS NOT NULL
    AND EXISTS(SELECT 1 FROM cehub_quality.test_import_sample_resolutions x
      JOIN cehub_quality.test_report_import_batches b ON b.tenant_id=x.tenant_id AND b.id=x.batch_id
      WHERE x.tenant_id=NEW.tenant_id AND x.project_id=NEW.project_id AND x.sample_id=NEW.sample_id
       AND x.id::text=NEW.conditions->>'sample_resolution_id' AND x.run_ids ? OLD.id::text
       AND b.project_id=NEW.project_id AND b.document_id=NEW.evidence_document_id
       AND b.status='parsed' AND b.superseded_by_batch_id IS NULL AND b.created_run_ids ?
OLD.id::text)
    AND (NEW.sample_configuration_revision_id IS NULL OR EXISTS(
      SELECT 1 FROM cehub_product.sample_configuration_revisions r WHERE r.tenant_id=NEW.tenant_id
       AND r.id=NEW.sample_configuration_revision_id AND r.source='report_extract'
       AND r.snapshot=OLD.conditions->'report_configuration'))) THEN
   RAISE EXCEPTION 'Only unresolved report drafts may bind a human-resolved sample' USING
ERRCODE='23514';
  END IF;
 END IF;
 IF NEW.sample_configuration_revision_id IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM cehub_product.sample_configuration_revisions r WHERE r.tenant_id=NEW.tenant_id
   AND r.project_id=NEW.project_id AND r.sample_id=NEW.sample_id AND
r.id=NEW.sample_configuration_revision_id
   AND (r.source <> 'report_extract' OR r.source_document_id IS NOT DISTINCT FROM
NEW.evidence_document_id)) THEN
  RAISE EXCEPTION 'Test configuration must belong to this sample and report' USING ERRCODE='23514';
 END IF;
 IF NEW.draft_state='confirmed' AND NEW.status IN ('passed','failed','aborted')
  AND (TG_OP='INSERT' OR OLD.draft_state='draft')
  AND (NEW.executed_at IS NULL OR NEW.execution_time_precision='unknown'
       OR NEW.execution_time_source NOT IN ('report','human','system_completion')) THEN
  RAISE EXCEPTION 'Formal test results require an actual execution date' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION cehub_quality.guard_import_sample_resolution() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE b cehub_quality.test_report_import_batches%ROWTYPE;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Sample resolution receipts are immutable' USING ERRCODE='23514';
 END IF;
 SELECT * INTO b FROM cehub_quality.test_report_import_batches WHERE tenant_id=NEW.tenant_id
  AND project_id=NEW.project_id AND id=NEW.batch_id;
 IF b.id IS NULL OR b.status<>'parsed' OR b.superseded_by_batch_id IS NOT NULL
  OR (SELECT count(DISTINCT x.value) FROM jsonb_array_elements_text(NEW.run_ids) x)
       <>jsonb_array_length(NEW.run_ids)
  OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(NEW.run_ids) x WHERE NOT EXISTS(
    SELECT 1 FROM cehub_quality.test_runs r WHERE r.tenant_id=NEW.tenant_id
     AND r.project_id=NEW.project_id AND r.id=x.value::uuid AND b.created_run_ids ? x.value
     AND r.evidence_document_id=b.document_id AND r.draft_state='draft' AND r.sample_id IS NULL
     AND r.sample_configuration_revision_id IS NULL)) THEN
  RAISE EXCEPTION 'Sample resolution must use current unresolved draft runs' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_import_sample_resolution BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_quality.test_import_sample_resolutions FOR EACH ROW
 EXECUTE FUNCTION cehub_quality.guard_import_sample_resolution();

CREATE FUNCTION cehub_quality.guard_report_sample_source() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM cehub_quality.test_report_import_batches b WHERE b.tenant_id=OLD.tenant_id
   AND b.project_id=OLD.project_id AND b.created_run_ids ? OLD.id::text) THEN
  IF (NEW.conditions->'report_configuration') IS DISTINCT FROM
(OLD.conditions->'report_configuration')
   OR (NEW.conditions->'report_sample_serial') IS DISTINCT FROM
(OLD.conditions->'report_sample_serial')
   OR (NEW.conditions->'report_source') IS DISTINCT FROM (OLD.conditions->'report_source')
   OR (OLD.conditions->>'sample_resolution_id' IS NOT NULL AND
       (NEW.conditions->>'sample_resolution_id') IS DISTINCT FROM
(OLD.conditions->>'sample_resolution_id')) THEN
   RAISE EXCEPTION 'Original report sample and configuration facts are retained' USING
ERRCODE='23514';
  END IF;
  IF OLD.draft_state='draft' AND NEW.draft_state='confirmed' AND NEW.sample_id IS NULL THEN
   RAISE EXCEPTION 'Resolve the report sample before confirming results' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_report_sample_source BEFORE UPDATE ON cehub_quality.test_runs
 FOR EACH ROW EXECUTE FUNCTION cehub_quality.guard_report_sample_source();
"""

PREVIOUS_GUARD = r"""
CREATE OR REPLACE FUNCTION cehub_quality.guard_test_run_facts() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='UPDATE' AND OLD.sample_configuration_revision_id IS DISTINCT FROM
NEW.sample_configuration_revision_id THEN
  RAISE EXCEPTION 'A test keeps its initial configuration; old unknowns stay unknown' USING
ERRCODE='23514';
 END IF;
 IF NEW.sample_configuration_revision_id IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM cehub_product.sample_configuration_revisions r WHERE r.tenant_id=NEW.tenant_id
   AND r.project_id=NEW.project_id AND r.sample_id=NEW.sample_id AND
r.id=NEW.sample_configuration_revision_id
   AND (r.source <> 'report_extract' OR r.source_document_id IS NOT DISTINCT FROM
NEW.evidence_document_id)) THEN
  RAISE EXCEPTION 'Test configuration must belong to this sample and report' USING ERRCODE='23514';
 END IF;
 IF NEW.draft_state='confirmed' AND NEW.status IN ('passed','failed','aborted')
  AND (TG_OP='INSERT' OR OLD.draft_state='draft')
  AND (NEW.executed_at IS NULL OR NEW.execution_time_precision='unknown'
       OR NEW.execution_time_source NOT IN ('report','human','system_completion')) THEN
  RAISE EXCEPTION 'Formal test results require an actual execution date' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
"""
