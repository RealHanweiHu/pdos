"""Organization template revisions, rehearsed publication and rollback history."""

import sqlalchemy as sa
from alembic import op

revision = "0221_process_templates"
down_revision = "0220_field_recognitions"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_core.process_template_revisions (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	template_id VARCHAR(128) NOT NULL,
	version INTEGER NOT NULL,
	request_id UUID NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	base_template_id VARCHAR(128) NOT NULL,
	base_version INTEGER NOT NULL,
	base_digest VARCHAR(64) NOT NULL,
	base_release_id UUID,
	base_snapshot JSONB NOT NULL,
	snapshot JSONB NOT NULL,
	digest VARCHAR(64) NOT NULL,
	configuration JSONB NOT NULL,
	difference JSONB NOT NULL,
	reason TEXT NOT NULL,
	created_by_user_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT pk_process_template_revisions PRIMARY KEY (id),
	CONSTRAINT uq_process_template_version UNIQUE (tenant_id, template_id, version),
	CONSTRAINT uq_process_template_request UNIQUE (tenant_id, request_id),
	CONSTRAINT uq_process_template_scope UNIQUE (tenant_id, template_id, id),
        CONSTRAINT fk_process_template_revisions_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_process_template_revisions_input CHECK (version>0 AND base_version>0 AND
template_id ~ '^org-[a-z0-9-]+$' AND length(btrim(reason))>0 AND jsonb_typeof(snapshot)='object'
AND jsonb_typeof(base_snapshot)='object' AND jsonb_typeof(configuration)='object')
)

;

CREATE TABLE cehub_core.process_template_releases (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	template_id VARCHAR(128) NOT NULL,
	revision_id UUID NOT NULL,
	sequence INTEGER NOT NULL,
	previous_release_id UUID,
	request_id UUID NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	action VARCHAR(16) NOT NULL,
	reason TEXT NOT NULL,
	preview JSONB NOT NULL,
	preview_digest VARCHAR(64) NOT NULL,
	created_by_user_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT pk_process_template_releases PRIMARY KEY (id),
	CONSTRAINT uq_process_release_sequence UNIQUE (tenant_id, template_id, sequence),
	CONSTRAINT uq_process_release_request UNIQUE (tenant_id, request_id),
	CONSTRAINT uq_process_release_scope UNIQUE (tenant_id, template_id, id),
        CONSTRAINT fk_process_template_releases_tenant_id_process_template_5ea5 FOREIGN
KEY(tenant_id, template_id, revision_id) REFERENCES cehub_core.process_template_revisions
(tenant_id, template_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_process_template_releases_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_process_template_releases_tenant_id_process_template_ee8d FOREIGN
KEY(tenant_id, template_id, previous_release_id) REFERENCES cehub_core.process_template_releases
(tenant_id, template_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_process_template_releases_input CHECK (sequence>0 AND action IN
('publish','rollback') AND length(btrim(reason))>0 AND jsonb_typeof(preview)='object')
)

;

REVOKE ALL ON cehub_core.process_template_revisions,cehub_core.process_template_releases FROM
PUBLIC;
CREATE FUNCTION cehub_core.guard_process_template_history() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE prior cehub_core.process_template_releases;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Template configuration and releases are immutable';
END IF;
 IF NOT EXISTS(SELECT 1 FROM cehub_core.users WHERE tenant_id=NEW.tenant_id
  AND id=NEW.created_by_user_id AND is_active AND role IN ('owner','admin')) THEN
  RAISE EXCEPTION 'Organization template requires a named authorized administrator';
 END IF;
 IF TG_TABLE_NAME='process_template_revisions' THEN
  IF NEW.snapshot->>'id' IS DISTINCT FROM NEW.template_id OR
    (NEW.snapshot->>'version')::integer IS DISTINCT FROM NEW.version THEN
   RAISE EXCEPTION 'Template snapshot identity mismatch';
  END IF;
 ELSE
  PERFORM pg_advisory_xact_lock(hashtextextended(
   'process-template:'||NEW.tenant_id::text||':'||NEW.template_id,0));
  SELECT * INTO prior FROM cehub_core.process_template_releases WHERE tenant_id=NEW.tenant_id
   AND template_id=NEW.template_id ORDER BY sequence DESC LIMIT 1;
  IF NEW.previous_release_id IS DISTINCT FROM prior.id OR
   NEW.sequence<>coalesce(prior.sequence,0)+1 OR
   NEW.preview->>'revision_id' IS DISTINCT FROM NEW.revision_id::text OR
   NEW.preview->>'preview_digest' IS DISTINCT FROM NEW.preview_digest OR
   NEW.preview->>(CASE WHEN NEW.action='publish' THEN 'can_publish' ELSE 'can_rollback' END)
    IS DISTINCT FROM 'true' THEN
   RAISE EXCEPTION 'Release requires the current head and matching successful rehearsal';
  END IF;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_core.guard_process_template_history() FROM PUBLIC;
CREATE TRIGGER guard_process_template_revision BEFORE INSERT OR UPDATE OR DELETE ON
cehub_core.process_template_revisions FOR EACH ROW EXECUTE FUNCTION
cehub_core.guard_process_template_history();
CREATE TRIGGER guard_process_template_release BEFORE INSERT OR UPDATE OR DELETE ON
cehub_core.process_template_releases FOR EACH ROW EXECUTE FUNCTION
cehub_core.guard_process_template_history();
"""


def upgrade() -> None:
    op.execute(sa.text(DDL))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_core.process_template_revisions)"))
        .scalar()
    ):
        raise RuntimeError("Refusing to discard organization template history")
    op.drop_table("process_template_releases", schema="cehub_core")
    op.drop_table("process_template_revisions", schema="cehub_core")
    op.execute("DROP FUNCTION cehub_core.guard_process_template_history()")
