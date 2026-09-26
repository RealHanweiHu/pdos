"""Clause-scoped signature evidence and withdrawal receipts."""

# ruff: noqa: E501
from alembic import op

revision = "0361_audit_report_evidence"
down_revision = "0360_customer_report_packages"
branch_labels = None
depends_on = None

DDL = "\nCREATE TABLE cehub_project.project_report_sources (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\treport_id UUID NOT NULL, \n\tkind VARCHAR(16) NOT NULL, \n\tsource_id UUID NOT NULL, \n\tgate_id UUID, \n\tecn_id UUID, \n\tdocument_id UUID, \n\tCONSTRAINT pk_project_report_sources PRIMARY KEY (id), \n\tCONSTRAINT uq_project_report_source UNIQUE (tenant_id, report_id, kind, source_id), \n\tCONSTRAINT fk_project_report_sources_tenant_id_project_report_exports FOREIGN KEY(tenant_id, project_id, report_id) REFERENCES cehub_project.project_report_exports (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_project_report_sources_tenant_id_gates FOREIGN KEY(tenant_id, project_id, gate_id) REFERENCES cehub_project.gates (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_project_report_sources_tenant_id_engineering_change_notices FOREIGN KEY(tenant_id, project_id, ecn_id) REFERENCES cehub_product.engineering_change_notices (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_project_report_sources_tenant_id_documents FOREIGN KEY(tenant_id, project_id, document_id) REFERENCES cehub_project.documents (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_project_report_sources_shape CHECK ((kind='gate' AND gate_id IS NOT NULL AND gate_id=source_id AND ecn_id IS NULL AND document_id IS NULL) OR (kind='ecn' AND ecn_id IS NOT NULL AND ecn_id=source_id AND gate_id IS NULL AND document_id IS NULL) OR (kind='document' AND document_id IS NOT NULL AND document_id=source_id AND gate_id IS NULL AND ecn_id IS NULL))\n)\n\n;\n\n\nCREATE TABLE cehub_project.project_report_withdrawals (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\treport_id UUID NOT NULL, \n\tactor_user_id UUID NOT NULL, \n\treason TEXT NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_project_report_withdrawals PRIMARY KEY (id), \n\tCONSTRAINT uq_project_report_withdrawal UNIQUE (tenant_id, report_id), \n\tCONSTRAINT uq_project_report_withdrawal_request UNIQUE (tenant_id, actor_user_id, request_id), \n\tCONSTRAINT fk_project_report_withdrawals_tenant_id_project_report_exports FOREIGN KEY(tenant_id, project_id, report_id) REFERENCES cehub_project.project_report_exports (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_project_report_withdrawals_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_project_report_withdrawals_shape CHECK (btrim(reason)<>'' AND request_digest ~ '^[a-f0-9]{64}$')\n)\n\n;\n"
SHAPE = "format IN ('docx','xlsx','pptx','pdf') AND btrim(reason)<>'' AND btrim(filename)<>'' AND ((kind='audit' AND template_version='internal-audit-evidence.v1') OR (kind<>'audit' AND template_version='internal-project-reports.v1')) AND byte_size BETWEEN 1 AND 12582912 AND octet_length(content)=byte_size AND jsonb_typeof(snapshot)='object' AND snapshot->>'audience'='internal' AND jsonb_typeof(scope)='object' AND scope->>'kind'=kind AND ((kind='8d' AND ncr_id IS NOT NULL AND gate_id IS NULL) OR (kind='gate' AND gate_id IS NOT NULL AND ncr_id IS NULL) OR (kind IN ('dfmea','weekly','audit') AND ncr_id IS NULL AND gate_id IS NULL)) AND content_digest ~ '^[a-f0-9]{64}$' AND source_digest ~ '^[a-f0-9]{64}$' AND preview_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$'"

GUARDS = """
CREATE FUNCTION cehub_project.guard_report_source() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r cehub_project.project_report_exports;
BEGIN
 SELECT * INTO r FROM cehub_project.project_report_exports WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.report_id;
 IF r.id IS NULL OR r.kind<>'audit' OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(r.snapshot->'actual'->'sources') item WHERE item->>'kind'=NEW.kind AND item->>'id'=NEW.source_id::text)
 THEN RAISE EXCEPTION 'Report source must match the actual fixed package'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_project.guard_report_withdrawal() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM cehub_project.project_report_exports WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.report_id AND kind='audit')
 THEN RAISE EXCEPTION 'Withdrawal requires an actual audit package'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_project.guard_audit_report_references() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.kind='audit' THEN
  IF jsonb_typeof(NEW.scope->'audit_clauses') IS DISTINCT FROM 'array'
  OR jsonb_array_length(NEW.scope->'audit_clauses') NOT BETWEEN 1 AND 30
  OR jsonb_typeof(NEW.snapshot->'actual'->'sources') IS DISTINCT FROM 'array'
  OR (SELECT count(*) FROM cehub_project.project_report_sources WHERE tenant_id=NEW.tenant_id AND report_id=NEW.id) IS DISTINCT FROM jsonb_array_length(NEW.snapshot->'actual'->'sources')::bigint
  THEN RAISE EXCEPTION 'Audit package requires clause scope and complete actual source foreign keys'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_report_source BEFORE INSERT ON cehub_project.project_report_sources FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_report_source();
CREATE TRIGGER guard_report_withdrawal BEFORE INSERT ON cehub_project.project_report_withdrawals FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_report_withdrawal();
CREATE CONSTRAINT TRIGGER guard_audit_report_references AFTER INSERT ON cehub_project.project_report_exports DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_audit_report_references();
CREATE TRIGGER immutable_report_source BEFORE UPDATE OR DELETE ON cehub_project.project_report_sources FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
CREATE TRIGGER immutable_report_withdrawal BEFORE UPDATE OR DELETE ON cehub_project.project_report_withdrawals FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_project.project_report_sources, cehub_project.project_report_withdrawals FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_project.guard_report_source(), cehub_project.guard_report_withdrawal(), cehub_project.guard_audit_report_references() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cehub_project.project_report_exports ADD CONSTRAINT uq_project_report_export_scope UNIQUE(tenant_id,project_id,id)"
    )
    op.execute(
        "ALTER TABLE cehub_project.project_report_exports DROP CONSTRAINT ck_project_report_exports_shape"
    )
    op.execute(
        "ALTER TABLE cehub_project.project_report_exports ADD CONSTRAINT ck_project_report_exports_shape CHECK ("
        + SHAPE
        + ")"
    )
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_project.project_report_exports WHERE kind='audit') OR EXISTS(SELECT 1 FROM cehub_project.project_report_withdrawals) THEN RAISE EXCEPTION 'Retain audit package and withdrawal history'; END IF; END $$;"
    )
    op.execute("DROP TRIGGER guard_audit_report_references ON cehub_project.project_report_exports")
    op.execute(
        "DROP TABLE cehub_project.project_report_sources, cehub_project.project_report_withdrawals"
    )
    op.execute(
        "DROP FUNCTION cehub_project.guard_report_source(), cehub_project.guard_report_withdrawal(), cehub_project.guard_audit_report_references()"
    )
    op.execute(
        "ALTER TABLE cehub_project.project_report_exports DROP CONSTRAINT uq_project_report_export_scope"
    )
    op.execute(
        "ALTER TABLE cehub_project.project_report_exports DROP CONSTRAINT ck_project_report_exports_shape"
    )
    old_shape = SHAPE.replace(
        "((kind='audit' AND template_version='internal-audit-evidence.v1') OR (kind<>'audit' AND template_version='internal-project-reports.v1'))",
        "template_version='internal-project-reports.v1'",
    ).replace("kind IN ('dfmea','weekly','audit')", "kind IN ('dfmea','weekly')")
    op.execute(
        "ALTER TABLE cehub_project.project_report_exports ADD CONSTRAINT ck_project_report_exports_shape CHECK ("
        + old_shape
        + ")"
    )
