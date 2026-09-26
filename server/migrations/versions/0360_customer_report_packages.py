"""Independently approved customer-visible report projection and retained files."""

# ruff: noqa: E501
from alembic import op

revision = "0360_customer_report_packages"
down_revision = "0359_project_report_exports"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_project.customer_report_packages (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	customer_id UUID NOT NULL, 
	draft JSONB NOT NULL, 
	snapshot JSONB NOT NULL, 
	source_digest VARCHAR(64) NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_customer_report_packages PRIMARY KEY (id), 
	CONSTRAINT uq_customer_report_package_scope UNIQUE (tenant_id, project_id, id), 
	CONSTRAINT uq_customer_report_package_request UNIQUE (tenant_id, created_by_user_id, request_id), 
	CONSTRAINT fk_customer_report_packages_tenant_id_projects FOREIGN KEY(tenant_id, project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_customer_report_packages_tenant_id_customers FOREIGN KEY(tenant_id, customer_id) REFERENCES cehub_core.customers (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_customer_report_packages_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_customer_report_packages_shape CHECK (jsonb_typeof(draft)='object' AND jsonb_typeof(snapshot)='object' AND source_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$')
)

;
CREATE INDEX ix_customer_report_package_history ON cehub_project.customer_report_packages (tenant_id, project_id, id);

CREATE TABLE cehub_project.customer_report_decisions (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	package_id UUID NOT NULL, 
	version INTEGER NOT NULL, 
	action VARCHAR(16) NOT NULL, 
	reason TEXT NOT NULL, 
	actor_user_id UUID NOT NULL, 
	source_digest VARCHAR(64) NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_customer_report_decisions PRIMARY KEY (id), 
	CONSTRAINT uq_customer_report_decision_scope UNIQUE (tenant_id, project_id, id), 
	CONSTRAINT uq_customer_report_decision_version UNIQUE (tenant_id, package_id, version), 
	CONSTRAINT uq_customer_report_decision_request UNIQUE (tenant_id, actor_user_id, request_id), 
	CONSTRAINT fk_customer_report_decisions_tenant_id_customer_report_packages FOREIGN KEY(tenant_id, project_id, package_id) REFERENCES cehub_project.customer_report_packages (tenant_id, project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_customer_report_decisions_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_customer_report_decisions_shape CHECK (version>0 AND action IN ('approved','returned','withdrawn') AND btrim(reason)<>'' AND source_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$')
)

;

CREATE TABLE cehub_project.customer_report_files (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	package_id UUID NOT NULL, 
	decision_id UUID NOT NULL, 
	format VARCHAR(8) NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	mime_type VARCHAR(128) NOT NULL, 
	content BYTEA NOT NULL, 
	byte_size INTEGER NOT NULL, 
	content_digest VARCHAR(64) NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_customer_report_files PRIMARY KEY (id), 
	CONSTRAINT uq_customer_report_file_format UNIQUE (tenant_id, package_id, decision_id, format), 
	CONSTRAINT fk_customer_report_file_package FOREIGN KEY(tenant_id, project_id, package_id) REFERENCES cehub_project.customer_report_packages (tenant_id, project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_customer_report_file_decision FOREIGN KEY(tenant_id, project_id, decision_id) REFERENCES cehub_project.customer_report_decisions (tenant_id, project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_customer_report_files_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_customer_report_files_shape CHECK (format IN ('docx','xlsx','pptx','pdf') AND btrim(filename)<>'' AND byte_size BETWEEN 1 AND 12582912 AND octet_length(content)=byte_size AND content_digest ~ '^[a-f0-9]{64}$')
)

;
"""
GUARDS = """
CREATE FUNCTION cehub_project.guard_customer_report_package() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$
DECLARE projection jsonb;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;
 projection=NEW.snapshot->'projection';
 IF NEW.snapshot->'draft' IS DISTINCT FROM NEW.draft
 OR NEW.draft->>'customer_id' IS DISTINCT FROM NEW.customer_id::text
 OR NEW.snapshot->>'customer_id' IS DISTINCT FROM NEW.customer_id::text
 OR NEW.snapshot->>'digest' IS DISTINCT FROM NEW.source_digest
 OR projection->>'template_version' IS DISTINCT FROM 'customer-reply-commitment.v1'
 OR projection->>'title' IS DISTINCT FROM NEW.draft->>'title'
 OR jsonb_typeof(projection) IS DISTINCT FROM 'object'
 OR projection - ARRAY['template_version','title','customer_name','approved_replies','commitments','interpretation'] <> '{}'::jsonb
 OR jsonb_typeof(projection->'approved_replies') IS DISTINCT FROM 'array'
 OR jsonb_typeof(projection->'commitments') IS DISTINCT FROM 'array'
 OR jsonb_array_length(projection->'approved_replies')<>jsonb_array_length(NEW.draft->'reply_ids')
 OR jsonb_array_length(projection->'commitments')<>jsonb_array_length(NEW.draft->'milestones')
 OR EXISTS (SELECT 1 FROM jsonb_array_elements(projection->'approved_replies') r WHERE r - ARRAY['reference','approved_reply','lead_time_days','reply_approved_at'] <> '{}'::jsonb)
 OR EXISTS (SELECT 1 FROM jsonb_array_elements(projection->'commitments') r WHERE r - ARRAY['milestone','committed_finish','confirmed_at'] <> '{}'::jsonb)
 THEN RAISE EXCEPTION 'Customer report requires explicit customer-visible whitelist and actual input scope'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_project.guard_customer_report_decision() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$
DECLARE p cehub_project.customer_report_packages; d cehub_project.customer_report_decisions;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;
 SELECT * INTO p FROM cehub_project.customer_report_packages WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.package_id;
 SELECT * INTO d FROM cehub_project.customer_report_decisions WHERE tenant_id=NEW.tenant_id AND package_id=NEW.package_id ORDER BY version DESC LIMIT 1;
 IF p.id IS NULL OR NEW.version<>coalesce(d.version,0)+1 OR NEW.source_digest IS DISTINCT FROM p.source_digest
 OR (NEW.action IN ('approved','returned') AND d.id IS NOT NULL)
 OR (NEW.action='approved' AND NEW.actor_user_id=p.created_by_user_id)
 OR (NEW.action='withdrawn' AND coalesce(d.action,'')<>'approved')
 THEN RAISE EXCEPTION 'Customer report approval requires independent actor, fixed projection and sequential decisions'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_project.guard_customer_report_file() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$
DECLARE d cehub_project.customer_report_decisions;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;
 SELECT * INTO d FROM cehub_project.customer_report_decisions WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND package_id=NEW.package_id ORDER BY version DESC LIMIT 1;
 IF d.id IS DISTINCT FROM NEW.decision_id OR d.action IS DISTINCT FROM 'approved'
 THEN RAISE EXCEPTION 'Customer report files require the current approved projection'; END IF;
 RETURN NEW;
END $$;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)
    for suffix in ("package", "decision", "file"):
        table = {"package": "packages", "decision": "decisions", "file": "files"}[suffix]
        op.execute(
            f"CREATE TRIGGER guard_customer_report_{suffix} BEFORE INSERT ON cehub_project.customer_report_{table} FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_customer_report_{suffix}()"
        )
        op.execute(
            f"CREATE TRIGGER immutable_customer_report_{suffix} BEFORE UPDATE OR DELETE ON cehub_project.customer_report_{table} FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history()"
        )
        op.execute(f"REVOKE ALL ON cehub_project.customer_report_{table} FROM PUBLIC")
        op.execute(
            f"REVOKE ALL ON FUNCTION cehub_project.guard_customer_report_{suffix}() FROM PUBLIC"
        )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_project.customer_report_packages) THEN RAISE EXCEPTION 'Retain customer report approval history'; END IF; END $$;"
    )
    for suffix in ("file", "decision", "package"):
        table = {"package": "packages", "decision": "decisions", "file": "files"}[suffix]
        op.execute(f"DROP TABLE cehub_project.customer_report_{table}")
        op.execute(f"DROP FUNCTION cehub_project.guard_customer_report_{suffix}()")
