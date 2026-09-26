"""Immutable sample observations and human-confirmed test execution dates.
Revision ID: 0179_test_configuration_facts
Revises: 0178_conversation_report_imports
"""

import sqlalchemy as sa
from alembic import op

revision = "0179_test_configuration_facts"
down_revision = "0178_conversation_report_imports"
branch_labels = None
depends_on = None

DDL = [
    """
CREATE TABLE cehub_product.sample_configuration_revisions (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    sample_id UUID NOT NULL,
    revision_number INTEGER NOT NULL,
    source VARCHAR(32) NOT NULL,
    source_document_id UUID,
    created_by_user_id UUID NOT NULL,
    snapshot JSONB NOT NULL,
    content_digest VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_sample_configuration_revisions PRIMARY KEY (id),
    CONSTRAINT uq_sample_revision_scope UNIQUE (tenant_id, project_id, sample_id, id),
    CONSTRAINT uq_sample_revision_number UNIQUE (tenant_id, sample_id, revision_number),
    CONSTRAINT fk_sample_configuration_revisions_tenant_id_projects FOREIGN KEY(tenant_id,
project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_sample_configuration_revisions_tenant_id_samples FOREIGN KEY(tenant_id,
sample_id) REFERENCES cehub_product.samples (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_sample_configuration_revisions_tenant_id_documents FOREIGN KEY(tenant_id,
source_document_id) REFERENCES cehub_project.documents (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_sample_configuration_revisions_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_sample_configuration_revisions_content_valid CHECK (revision_number > 0 AND
jsonb_typeof(snapshot) = 'object' AND content_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_sample_configuration_revisions_source_allowed CHECK (source IN ('manual',
'report_extract', 'current_observation')),
    CONSTRAINT ck_sample_configuration_revisions_report_source_required CHECK (source <>
'report_extract' OR source_document_id IS NOT NULL)
)
""",
    """
ALTER TABLE cehub_product.sample_build_configurations ADD COLUMN current_revision_id uuid
""",
    """
ALTER TABLE cehub_quality.test_runs
 ADD COLUMN sample_configuration_revision_id uuid,
 ADD COLUMN execution_time_precision varchar(16) NOT NULL DEFAULT 'unknown',
 ADD COLUMN execution_time_source varchar(32) NOT NULL DEFAULT 'legacy_unknown',
 DROP CONSTRAINT ck_test_runs_executed_at_consistent
""",
    """
ALTER TABLE cehub_product.sample_build_configurations ADD CONSTRAINT
fk_sample_configuration_current_revision FOREIGN KEY(tenant_id, project_id, sample_id,
current_revision_id) REFERENCES cehub_product.sample_configuration_revisions (tenant_id,
project_id, sample_id, id) ON DELETE RESTRICT
""",
    """
ALTER TABLE cehub_quality.test_runs ADD CONSTRAINT ck_test_runs_executed_at_consistent CHECK
((status IN ('passed', 'failed', 'aborted') AND (executed_at IS NOT NULL OR draft_state =
'draft')) OR (status IN ('planned', 'in_progress') AND executed_at IS NULL))
""",
    """
ALTER TABLE cehub_quality.test_runs ADD CONSTRAINT ck_test_runs_execution_time_known CHECK
(execution_time_precision = 'unknown' OR executed_at IS NOT NULL)
""",
    """
ALTER TABLE cehub_quality.test_runs ADD CONSTRAINT ck_test_runs_execution_time_provenance CHECK
(execution_time_precision IN ('unknown', 'day', 'instant') AND execution_time_source IN
('legacy_unknown', 'unknown', 'report', 'human', 'system_completion'))
""",
    """
ALTER TABLE cehub_quality.test_runs ADD CONSTRAINT ck_test_runs_revision_sample_required CHECK
(sample_configuration_revision_id IS NULL OR sample_id IS NOT NULL)
""",
    """
ALTER TABLE cehub_quality.test_runs ADD CONSTRAINT fk_test_run_configuration_revision FOREIGN
KEY(tenant_id, project_id, sample_id, sample_configuration_revision_id) REFERENCES
cehub_product.sample_configuration_revisions (tenant_id, project_id, sample_id, id) ON DELETE
RESTRICT
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
        SELECT EXISTS(SELECT 1 FROM cehub_product.sample_configuration_revisions)
          OR EXISTS(SELECT 1 FROM cehub_quality.test_runs
            WHERE execution_time_source <> 'legacy_unknown' OR execution_time_precision <>
'unknown')
    """)
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard test configuration or execution-time evidence")
    op.execute("""
      DROP TRIGGER guard_test_run_facts ON cehub_quality.test_runs;
      DROP FUNCTION cehub_quality.guard_test_run_facts();
      DROP TRIGGER guard_sample_current_revision ON cehub_product.sample_build_configurations;
      DROP FUNCTION cehub_product.guard_sample_current_revision();
      ALTER TABLE cehub_quality.test_runs
        DROP CONSTRAINT fk_test_run_configuration_revision,
        DROP CONSTRAINT ck_test_runs_revision_sample_required,
        DROP CONSTRAINT ck_test_runs_execution_time_provenance,
        DROP CONSTRAINT ck_test_runs_execution_time_known,
        DROP CONSTRAINT ck_test_runs_executed_at_consistent,
        DROP COLUMN sample_configuration_revision_id,
        DROP COLUMN execution_time_precision,
        DROP COLUMN execution_time_source,
        ADD CONSTRAINT ck_test_runs_executed_at_consistent CHECK (
          (status IN ('passed', 'failed', 'aborted') AND executed_at IS NOT NULL)
          OR (status IN ('planned', 'in_progress') AND executed_at IS NULL));
      ALTER TABLE cehub_product.sample_build_configurations
        DROP CONSTRAINT fk_sample_configuration_current_revision, DROP COLUMN current_revision_id;
      DROP TABLE cehub_product.sample_configuration_revisions;
      DROP FUNCTION cehub_product.guard_sample_configuration_revision();
    """)


GUARDS = r"""
CREATE FUNCTION cehub_product.guard_sample_configuration_revision() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'Sample configuration revisions are immutable' USING ERRCODE='23514';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM cehub_product.samples s WHERE s.tenant_id=NEW.tenant_id
   AND s.project_id=NEW.project_id AND s.id=NEW.sample_id)
 OR (NEW.source_document_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM cehub_project.documents d
   WHERE d.tenant_id=NEW.tenant_id AND d.project_id=NEW.project_id AND d.id=NEW.source_document_id))
 OR (NEW.snapshot->>'fw_release_id' IS NOT NULL AND NOT EXISTS(SELECT 1 FROM
cehub_product.fw_releases f
   WHERE f.tenant_id=NEW.tenant_id AND f.project_id=NEW.project_id AND
f.id=(NEW.snapshot->>'fw_release_id')::uuid))
 OR (NEW.snapshot->>'development_bom_id' IS NOT NULL AND NOT EXISTS(SELECT 1 FROM
cehub_product.development_boms b
   WHERE b.tenant_id=NEW.tenant_id AND b.project_id=NEW.project_id AND
b.id=(NEW.snapshot->>'development_bom_id')::uuid)) THEN
  RAISE EXCEPTION 'Configuration revision must use project-scoped sources' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_sample_configuration_revision BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_product.sample_configuration_revisions FOR EACH ROW
 EXECUTE FUNCTION cehub_product.guard_sample_configuration_revision();

CREATE FUNCTION cehub_product.guard_sample_current_revision() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.current_revision_id IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM cehub_product.sample_configuration_revisions r WHERE r.tenant_id=NEW.tenant_id
   AND r.project_id=NEW.project_id AND r.sample_id=NEW.sample_id AND r.id=NEW.current_revision_id
   AND r.source IN ('manual', 'current_observation')) THEN
  RAISE EXCEPTION 'Current configuration requires its own observation' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_sample_current_revision BEFORE INSERT OR UPDATE
 ON cehub_product.sample_build_configurations FOR EACH ROW
 EXECUTE FUNCTION cehub_product.guard_sample_current_revision();

CREATE FUNCTION cehub_quality.guard_test_run_facts() RETURNS trigger
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
CREATE TRIGGER guard_test_run_facts BEFORE INSERT OR UPDATE ON cehub_quality.test_runs
 FOR EACH ROW EXECUTE FUNCTION cehub_quality.guard_test_run_facts();
"""
