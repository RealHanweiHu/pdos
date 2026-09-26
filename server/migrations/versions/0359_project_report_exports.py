"""Retained internal project report artifacts and explicit scope receipts."""

# ruff: noqa: E501
from alembic import op

revision = "0359_project_report_exports"
down_revision = "0358_definition_exports"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_project.project_report_exports (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	scope JSONB NOT NULL, 
	ncr_id UUID, 
	gate_id UUID, 
	format VARCHAR(8) NOT NULL, 
	template_version VARCHAR(64) NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	mime_type VARCHAR(128) NOT NULL, 
	byte_size INTEGER NOT NULL, 
	content BYTEA NOT NULL, 
	content_digest VARCHAR(64) NOT NULL, 
	snapshot JSONB NOT NULL, 
	source_digest VARCHAR(64) NOT NULL, 
	preview_digest VARCHAR(64) NOT NULL, 
	reason TEXT NOT NULL, 
	actor_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_project_report_exports PRIMARY KEY (id), 
	CONSTRAINT uq_project_report_export_request UNIQUE (tenant_id, actor_user_id, request_id), 
	CONSTRAINT fk_project_report_exports_tenant_id_projects FOREIGN KEY(tenant_id, project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_project_report_exports_tenant_id_nonconformance_reports FOREIGN KEY(tenant_id, project_id, ncr_id) REFERENCES cehub_quality.nonconformance_reports (tenant_id, project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_project_report_exports_tenant_id_gates FOREIGN KEY(tenant_id, project_id, gate_id) REFERENCES cehub_project.gates (tenant_id, project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_project_report_exports_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_project_report_exports_shape CHECK (format IN ('docx','xlsx','pptx','pdf') AND btrim(reason)<>'' AND btrim(filename)<>'' AND template_version='internal-project-reports.v1' AND byte_size BETWEEN 1 AND 12582912 AND octet_length(content)=byte_size AND jsonb_typeof(snapshot)='object' AND snapshot->>'audience'='internal' AND jsonb_typeof(scope)='object' AND scope->>'kind'=kind AND ((kind='8d' AND ncr_id IS NOT NULL AND gate_id IS NULL) OR (kind='gate' AND gate_id IS NOT NULL AND ncr_id IS NULL) OR (kind IN ('dfmea','weekly') AND ncr_id IS NULL AND gate_id IS NULL)) AND content_digest ~ '^[a-f0-9]{64}$' AND source_digest ~ '^[a-f0-9]{64}$' AND preview_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$')
)

;
CREATE INDEX ix_project_report_export_history ON cehub_project.project_report_exports (tenant_id, project_id, kind, id);
"""
GUARDS = """
CREATE FUNCTION cehub_project.guard_project_report_export() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;
 IF NEW.snapshot->'project'->>'id' IS DISTINCT FROM NEW.project_id::text
 OR NEW.snapshot->'scope' IS DISTINCT FROM NEW.scope
 OR NEW.snapshot->>'digest' IS DISTINCT FROM NEW.source_digest
 OR NEW.snapshot->>'template_version' IS DISTINCT FROM NEW.template_version
 OR NEW.snapshot->>'audience' IS DISTINCT FROM 'internal'
 OR (NEW.kind='8d' AND (NEW.scope->>'object_id' IS DISTINCT FROM NEW.ncr_id::text OR NEW.snapshot->'actual'->'record'->>'id' IS DISTINCT FROM NEW.ncr_id::text))
 OR (NEW.kind='gate' AND (NEW.scope->>'object_id' IS DISTINCT FROM NEW.gate_id::text OR NEW.snapshot->'actual'->'gate'->>'id' IS DISTINCT FROM NEW.gate_id::text))
 OR jsonb_typeof(NEW.snapshot->'sections') IS DISTINCT FROM 'array'
 THEN RAISE EXCEPTION 'Project report exports require actual scoped inputs and explicit internal template'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_project_report_export BEFORE INSERT ON cehub_project.project_report_exports
FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_project_report_export();
CREATE TRIGGER immutable_project_report_export BEFORE UPDATE OR DELETE ON cehub_project.project_report_exports
FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_project.project_report_exports FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_project.guard_project_report_export() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_project.project_report_exports) THEN RAISE EXCEPTION 'Retain project report export history'; END IF; END $$;"
    )
    op.execute("DROP TABLE cehub_project.project_report_exports")
    op.execute("DROP FUNCTION cehub_project.guard_project_report_export()")
