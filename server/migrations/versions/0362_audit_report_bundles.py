"""Retained internal audit report and verified original-file bundles."""

# ruff: noqa: E501
from alembic import op

revision = "0362_audit_report_bundles"
down_revision = "0361_audit_report_evidence"
branch_labels = None
depends_on = None

DDL = "\nCREATE TABLE cehub_project.audit_report_bundles (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\treport_id UUID NOT NULL, \n\tfilename VARCHAR(255) NOT NULL, \n\tbyte_size INTEGER NOT NULL, \n\tcontent BYTEA NOT NULL, \n\tcontent_digest VARCHAR(64) NOT NULL, \n\tmanifest JSONB NOT NULL, \n\tsource_digest VARCHAR(64) NOT NULL, \n\treason TEXT NOT NULL, \n\tactor_user_id UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_audit_report_bundles PRIMARY KEY (id), \n\tCONSTRAINT uq_audit_bundle_request UNIQUE (tenant_id, actor_user_id, request_id), \n\tCONSTRAINT uq_audit_bundle_scope UNIQUE (tenant_id, project_id, id), \n\tCONSTRAINT fk_audit_report_bundles_tenant_id_project_report_exports FOREIGN KEY(tenant_id, project_id, report_id) REFERENCES cehub_project.project_report_exports (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_audit_report_bundles_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_audit_report_bundles_shape CHECK (byte_size BETWEEN 1 AND 54525952 AND octet_length(content)=byte_size AND btrim(reason)<>'' AND btrim(filename)<>'' AND jsonb_typeof(manifest)='object' AND manifest->>'audience'='internal' AND manifest->>'template_version'='internal-audit-bundle.v1' AND content_digest ~ '^[a-f0-9]{64}$' AND source_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$')\n)\n\n;\nCREATE INDEX ix_audit_bundle_report_history ON cehub_project.audit_report_bundles (tenant_id, project_id, report_id, created_at, id);"

GUARD = """
CREATE FUNCTION cehub_project.guard_audit_bundle() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r cehub_project.project_report_exports; item jsonb; d cehub_project.documents;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;
 SELECT * INTO r FROM cehub_project.project_report_exports WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.report_id;
 IF r.id IS NULL OR r.kind<>'audit'
 OR EXISTS(SELECT 1 FROM cehub_project.project_report_withdrawals WHERE tenant_id=NEW.tenant_id AND report_id=NEW.report_id)
 OR NEW.manifest->>'project_id' IS DISTINCT FROM NEW.project_id::text
 OR NEW.manifest->>'bundle_id' IS DISTINCT FROM NEW.id::text
 OR NEW.manifest->>'generated_by_user_id' IS DISTINCT FROM NEW.actor_user_id::text
 OR NEW.manifest->>'reason' IS DISTINCT FROM NEW.reason
 OR NEW.manifest->>'digest' IS DISTINCT FROM NEW.source_digest
 OR NEW.manifest->'report'->>'id' IS DISTINCT FROM r.id::text
 OR NEW.manifest->'report'->>'sha256' IS DISTINCT FROM r.content_digest
 OR NEW.manifest->'report'->>'source_digest' IS DISTINCT FROM r.source_digest
 OR jsonb_typeof(NEW.manifest->'documents') IS DISTINCT FROM 'array'
 THEN RAISE EXCEPTION 'Bundle requires current scoped report and fixed original-file manifest'; END IF;
 IF jsonb_array_length(NEW.manifest->'documents') IS DISTINCT FROM (SELECT count(*)::integer FROM cehub_project.project_report_sources WHERE tenant_id=NEW.tenant_id AND report_id=NEW.report_id AND kind='document')
 OR jsonb_array_length(NEW.manifest->'documents') IS DISTINCT FROM (SELECT count(DISTINCT value->>'id')::integer FROM jsonb_array_elements(NEW.manifest->'documents'))
 THEN RAISE EXCEPTION 'Bundle must include each explicitly selected original once'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(NEW.manifest->'documents') LOOP
  SELECT * INTO d FROM cehub_project.documents WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=(item->>'id')::uuid;
  IF d.id IS NULL OR item->>'sha256' IS DISTINCT FROM d.sha256 OR (item->>'size_bytes')::bigint IS DISTINCT FROM d.size_bytes
  OR NOT EXISTS(SELECT 1 FROM cehub_project.project_report_sources WHERE tenant_id=NEW.tenant_id AND report_id=NEW.report_id AND document_id=d.id)
  THEN RAISE EXCEPTION 'Bundle original must match source bytes and project scope'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_audit_bundle BEFORE INSERT ON cehub_project.audit_report_bundles FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_audit_bundle();
CREATE TRIGGER immutable_audit_bundle BEFORE UPDATE OR DELETE ON cehub_project.audit_report_bundles FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_project.audit_report_bundles FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_project.guard_audit_bundle() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_project.audit_report_bundles) THEN RAISE EXCEPTION 'Retain original-file audit bundle history'; END IF; END $$;"
    )
    op.execute("DROP TABLE cehub_project.audit_report_bundles")
    op.execute("DROP FUNCTION cehub_project.guard_audit_bundle()")
