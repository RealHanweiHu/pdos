"""Freeze organization process requirements and bind manual candidate provenance."""

import sqlalchemy as sa
from alembic import op

revision = "0222_process_template_briefs"
down_revision = "0221_process_templates"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_core.process_template_briefs (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	template_id VARCHAR(128) NOT NULL,
	request_id UUID NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	base_template_id VARCHAR(128) NOT NULL,
	base_version INTEGER NOT NULL,
	base_digest VARCHAR(64) NOT NULL,
	base_release_id UUID,
	previous_brief_id UUID,
	instruction TEXT NOT NULL,
	acceptance_criteria TEXT NOT NULL,
	source_snapshot JSONB NOT NULL,
	source_digest VARCHAR(64) NOT NULL,
	created_by_user_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT pk_process_template_briefs PRIMARY KEY (id),
	CONSTRAINT uq_process_brief_scope UNIQUE (tenant_id, template_id, id),
	CONSTRAINT uq_process_brief_request UNIQUE (tenant_id, request_id),
        CONSTRAINT fk_process_template_briefs_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_process_brief_parent FOREIGN KEY(tenant_id, template_id,
previous_brief_id) REFERENCES cehub_core.process_template_briefs (tenant_id, template_id, id) ON
DELETE RESTRICT,
        CONSTRAINT fk_process_brief_release FOREIGN KEY(tenant_id, template_id, base_release_id)
REFERENCES cehub_core.process_template_releases (tenant_id, template_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_process_template_briefs_input CHECK (base_version>0 AND template_id ~
'^org-[a-z0-9-]+$' AND length(btrim(instruction)) BETWEEN 1 AND 16000 AND
length(btrim(acceptance_criteria)) BETWEEN 1 AND 8000 AND jsonb_typeof(source_snapshot)='object'
AND source_digest ~ '^[a-f0-9]{64}$' AND id IS DISTINCT FROM previous_brief_id)
)

;
CREATE INDEX ix_process_brief_recent ON cehub_core.process_template_briefs (tenant_id,
created_at, id);

ALTER TABLE cehub_core.process_template_revisions ADD COLUMN source_brief_id uuid;
ALTER TABLE cehub_core.process_template_revisions ADD CONSTRAINT fk_process_revision_brief
 FOREIGN KEY(tenant_id,template_id,source_brief_id)
 REFERENCES cehub_core.process_template_briefs(tenant_id,template_id,id) ON DELETE RESTRICT;
REVOKE ALL ON cehub_core.process_template_briefs FROM PUBLIC;
CREATE FUNCTION cehub_core.guard_process_template_brief() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE original cehub_core.process_template_briefs;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Process template briefs and their source anchors are immutable';
 END IF;
 IF TG_TABLE_NAME='process_template_briefs' THEN
  IF NOT EXISTS(SELECT 1 FROM cehub_core.users u JOIN cehub_core.tenants t ON t.id=u.tenant_id
    WHERE u.tenant_id=NEW.tenant_id AND u.id=NEW.created_by_user_id AND u.is_active
    AND u.role IN ('owner','admin') AND t.status='active') THEN
   RAISE EXCEPTION 'Template requirements need a current named organization administrator';
  END IF;
  IF NEW.source_snapshot->>'id' IS DISTINCT FROM NEW.id::text OR
   NEW.source_snapshot->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text OR
   NEW.source_snapshot->'scope'->>'kind' IS DISTINCT FROM 'tenant' OR
   NEW.source_snapshot->'scope'->>'ref_id' IS DISTINCT FROM NEW.tenant_id::text OR
   NEW.source_snapshot->>'template_id' IS DISTINCT FROM NEW.template_id OR
   NEW.source_snapshot->>'instruction' IS DISTINCT FROM NEW.instruction OR
   NEW.source_snapshot->>'acceptance_criteria' IS DISTINCT FROM NEW.acceptance_criteria OR
   NEW.source_snapshot->>'base_template_id' IS DISTINCT FROM NEW.base_template_id OR
   NEW.source_snapshot->>'base_version' IS DISTINCT FROM NEW.base_version::text OR
   NEW.source_snapshot->>'base_digest' IS DISTINCT FROM NEW.base_digest OR
   NEW.source_snapshot->>'base_release_id' IS DISTINCT FROM NEW.base_release_id::text OR
   NEW.source_snapshot->>'previous_brief_id' IS DISTINCT FROM NEW.previous_brief_id::text OR
   jsonb_typeof(NEW.source_snapshot->'base_snapshot') IS DISTINCT FROM 'object' THEN
   RAISE EXCEPTION 'Template requirements must keep their exact original source anchors';
  END IF;
 ELSIF NEW.source_brief_id IS NOT NULL THEN
  SELECT * INTO original FROM cehub_core.process_template_briefs WHERE tenant_id=NEW.tenant_id
   AND template_id=NEW.template_id AND id=NEW.source_brief_id;
  IF original.id IS NULL OR NEW.base_template_id IS DISTINCT FROM original.base_template_id OR
   NEW.base_version IS DISTINCT FROM original.base_version OR
   NEW.base_digest IS DISTINCT FROM original.base_digest OR
   NEW.base_release_id IS DISTINCT FROM original.base_release_id OR
   NEW.base_snapshot IS DISTINCT FROM original.source_snapshot->'base_snapshot' THEN
   RAISE EXCEPTION 'Template candidate and management requirements must share source anchors';
  END IF;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_core.guard_process_template_brief() FROM PUBLIC;
CREATE TRIGGER guard_process_template_brief BEFORE INSERT OR UPDATE OR DELETE ON
 cehub_core.process_template_briefs FOR EACH ROW EXECUTE FUNCTION
cehub_core.guard_process_template_brief();
CREATE TRIGGER guard_process_template_brief_source BEFORE INSERT ON
 cehub_core.process_template_revisions FOR EACH ROW EXECUTE FUNCTION
cehub_core.guard_process_template_brief();
"""


def upgrade() -> None:
    op.execute(sa.text(DDL))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_core.process_template_briefs)"))
        .scalar()
    ):
        raise RuntimeError("Refusing to discard process template requirements")
    op.execute(
        "DROP TRIGGER guard_process_template_brief_source ON cehub_core.process_template_revisions"
    )
    op.drop_constraint(
        "fk_process_revision_brief",
        "process_template_revisions",
        schema="cehub_core",
        type_="foreignkey",
    )
    op.drop_column("process_template_revisions", "source_brief_id", schema="cehub_core")
    op.drop_table("process_template_briefs", schema="cehub_core")
    op.execute("DROP FUNCTION cehub_core.guard_process_template_brief()")
