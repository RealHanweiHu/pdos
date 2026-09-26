"""Project-scoped external credential grants, revocations and call receipts."""

# ruff: noqa: E501
from alembic import op

revision = "0364_controlled_open_api"
down_revision = "0363_customer_audit_disclosures"
branch_labels = None
depends_on = None

DDL = "\nCREATE TABLE cehub_project.open_api_credentials (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tprincipal_user_id UUID NOT NULL, \n\tprincipal_auth_version INTEGER NOT NULL, \n\tlabel VARCHAR(128) NOT NULL, \n\taudience VARCHAR(16) NOT NULL, \n\tcustomer_id UUID, \n\tscopes JSONB NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tpurpose TEXT NOT NULL, \n\tverifier VARCHAR(64) NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_open_api_credentials PRIMARY KEY (id), \n\tCONSTRAINT uq_open_api_credential_scope UNIQUE (tenant_id, project_id, id), \n\tCONSTRAINT uq_open_api_credential_request UNIQUE (tenant_id, principal_user_id, request_id), \n\tCONSTRAINT fk_open_api_credentials_tenant_id_projects FOREIGN KEY(tenant_id, project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_open_api_credentials_tenant_id_users FOREIGN KEY(tenant_id, principal_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_open_api_credentials_tenant_id_customers FOREIGN KEY(tenant_id, customer_id) REFERENCES cehub_core.customers (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_open_api_credentials_shape CHECK (principal_auth_version>0 AND btrim(label)<>'' AND btrim(purpose)<>'' AND expires_at>created_at AND expires_at<=created_at+interval '365 days' AND verifier ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$' AND jsonb_typeof(scopes)='array' AND ((audience='internal' AND customer_id IS NULL AND scopes='[\"work.read\"]'::jsonb) OR (audience='customer' AND customer_id IS NOT NULL AND scopes ? 'customer_reports.read' AND scopes <@ '[\"customer_reports.read\",\"customer_receipts.write\"]'::jsonb)))\n)\n\n;\nCREATE INDEX ix_open_api_credential_project ON cehub_project.open_api_credentials (tenant_id, project_id, id);\n\nCREATE TABLE cehub_project.open_api_revocations (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tcredential_id UUID NOT NULL, \n\tactor_user_id UUID NOT NULL, \n\treason TEXT NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_open_api_revocations PRIMARY KEY (id), \n\tCONSTRAINT uq_open_api_revocation UNIQUE (tenant_id, credential_id), \n\tCONSTRAINT uq_open_api_revocation_request UNIQUE (tenant_id, actor_user_id, request_id), \n\tCONSTRAINT fk_open_api_revocations_tenant_id_open_api_credentials FOREIGN KEY(tenant_id, project_id, credential_id) REFERENCES cehub_project.open_api_credentials (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_open_api_revocations_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_open_api_revocations_shape CHECK (btrim(reason)<>'' AND request_digest ~ '^[a-f0-9]{64}$')\n)\n\n;\n\n\nCREATE TABLE cehub_project.open_api_calls (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tcredential_id UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\toperation VARCHAR(64) NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tstatus_code INTEGER NOT NULL, \n\tresponse JSONB NOT NULL, \n\tresponse_digest VARCHAR(64) NOT NULL, \n\tresource_refs JSONB NOT NULL, \n\tfile_id UUID, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_open_api_calls PRIMARY KEY (id), \n\tCONSTRAINT uq_open_api_call_request UNIQUE (tenant_id, credential_id, request_id), \n\tCONSTRAINT fk_open_api_calls_tenant_id_open_api_credentials FOREIGN KEY(tenant_id, project_id, credential_id) REFERENCES cehub_project.open_api_credentials (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_open_api_calls_tenant_id_customer_report_files FOREIGN KEY(tenant_id, project_id, file_id) REFERENCES cehub_project.customer_report_files (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_open_api_calls_shape CHECK (operation IN ('work.query','customer_reports.query','customer_reports.read','customer_files.read','customer_receipts.record') AND status_code IN (200,403,409) AND jsonb_typeof(response)='object' AND jsonb_typeof(resource_refs)='array' AND request_digest ~ '^[a-f0-9]{64}$' AND response_digest ~ '^[a-f0-9]{64}$' AND ((status_code=200 AND operation IN ('customer_files.read','customer_receipts.record') AND file_id IS NOT NULL) OR ((status_code<>200 OR operation NOT IN ('customer_files.read','customer_receipts.record')) AND file_id IS NULL)))\n)\n\n;\nCREATE INDEX ix_open_api_call_window ON cehub_project.open_api_calls (credential_id, created_at);\nCREATE INDEX ix_open_api_call_history ON cehub_project.open_api_calls (tenant_id, credential_id, id);"

GUARDS = """
CREATE FUNCTION cehub_project.guard_open_api_credential() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM cehub_core.users WHERE tenant_id=NEW.tenant_id AND id=NEW.principal_user_id AND is_active AND auth_version=NEW.principal_auth_version) THEN RAISE EXCEPTION 'External API grant requires current named principal'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_project.guard_open_api_revocation() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 PERFORM 1 FROM cehub_project.open_api_credentials WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.credential_id FOR UPDATE;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_project.guard_open_api_call() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE k cehub_project.open_api_credentials;
BEGIN
 SELECT * INTO k FROM cehub_project.open_api_credentials WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.credential_id FOR UPDATE;
 IF k.id IS NULL OR k.expires_at<=NEW.created_at OR EXISTS(SELECT 1 FROM cehub_project.open_api_revocations WHERE tenant_id=NEW.tenant_id AND credential_id=k.id)
 OR NEW.response->>'call_id' IS DISTINCT FROM NEW.id::text OR NEW.response->>'request_id' IS DISTINCT FROM NEW.request_id::text
 THEN RAISE EXCEPTION 'API call requires live scoped grant and matching receipt'; END IF;
 IF NEW.file_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM cehub_project.customer_report_files f JOIN cehub_project.customer_report_packages p ON p.tenant_id=f.tenant_id AND p.project_id=f.project_id AND p.id=f.package_id WHERE f.tenant_id=NEW.tenant_id AND f.project_id=NEW.project_id AND f.id=NEW.file_id AND p.customer_id=k.customer_id)
 THEN RAISE EXCEPTION 'External receipt must use a file from the granted customer'; END IF;
 RETURN NEW;
END $$;
"""


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cehub_project.customer_report_files ADD CONSTRAINT uq_customer_report_file_scope UNIQUE(tenant_id,project_id,id)"
    )
    op.execute(DDL)
    op.execute(GUARDS)
    for table, suffix in (
        ("open_api_credentials", "credential"),
        ("open_api_revocations", "revocation"),
        ("open_api_calls", "call"),
    ):
        op.execute(
            f"CREATE TRIGGER guard_{table} BEFORE INSERT ON cehub_project.{table} FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_open_api_{suffix}()"
        )
        op.execute(
            f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON cehub_project.{table} FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history()"
        )
        op.execute(f"REVOKE ALL ON cehub_project.{table} FROM PUBLIC")
        op.execute(f"REVOKE ALL ON FUNCTION cehub_project.guard_open_api_{suffix}() FROM PUBLIC")


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_project.open_api_credentials) THEN RAISE EXCEPTION 'Retain external credential and call history'; END IF; END $$;"
    )
    for table in ("open_api_calls", "open_api_revocations", "open_api_credentials"):
        op.execute(f"DROP TABLE cehub_project.{table}")
    for suffix in ("call", "revocation", "credential"):
        op.execute(f"DROP FUNCTION cehub_project.guard_open_api_{suffix}()")
    op.execute(
        "ALTER TABLE cehub_project.customer_report_files DROP CONSTRAINT uq_customer_report_file_scope"
    )
