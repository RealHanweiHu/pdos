"""Retained internal definition export bytes and source receipts."""

# ruff: noqa: E501
from alembic import op

revision = "0358_definition_exports"
down_revision = "0357_product_result_followups"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_product.definition_exports (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	market_space_id UUID NOT NULL, 
	definition_id UUID NOT NULL, 
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
	CONSTRAINT pk_definition_exports PRIMARY KEY (id), 
	CONSTRAINT uq_definition_export_request UNIQUE (tenant_id, actor_user_id, request_id), 
	CONSTRAINT fk_definition_exports_tenant_id_product_definitions FOREIGN KEY(tenant_id, market_space_id, definition_id) REFERENCES cehub_product.product_definitions (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_definition_exports_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_definition_exports_shape CHECK (format IN ('docx','xlsx','pptx','pdf') AND btrim(reason)<>'' AND btrim(filename)<>'' AND template_version='internal-definition.v1' AND byte_size BETWEEN 1 AND 12582912 AND octet_length(content)=byte_size AND jsonb_typeof(snapshot)='object' AND snapshot->>'audience'='internal' AND content_digest ~ '^[a-f0-9]{64}$' AND source_digest ~ '^[a-f0-9]{64}$' AND preview_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$')
)

;
CREATE INDEX ix_definition_export_history ON cehub_product.definition_exports (tenant_id, market_space_id, definition_id, id);
"""
GUARDS = """
CREATE FUNCTION cehub_product.guard_definition_export() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$
DECLARE d cehub_product.product_definitions;
BEGIN
 PERFORM 1 FROM cehub_product.market_spaces WHERE tenant_id=NEW.tenant_id AND id=NEW.market_space_id FOR UPDATE;
 SELECT * INTO d FROM cehub_product.product_definitions WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.definition_id;
 IF d.id IS NULL OR NEW.snapshot->'definition'->>'id' IS DISTINCT FROM d.id::text
 OR NEW.snapshot->'definition'->>'version' IS DISTINCT FROM d.version::text
 OR NEW.snapshot->'definition'->>'state' IS DISTINCT FROM d.state
 OR NEW.snapshot->'definition'->'content' IS DISTINCT FROM d.content
 OR NEW.snapshot->'definition'->'approval' IS DISTINCT FROM coalesce(d.approval,'null'::jsonb)
 OR NEW.snapshot->>'digest' IS DISTINCT FROM NEW.source_digest
 OR NEW.snapshot->>'template_version' IS DISTINCT FROM NEW.template_version
 OR NEW.snapshot->>'audience' IS DISTINCT FROM 'internal'
 THEN RAISE EXCEPTION 'Definition export requires actual version, state and explicit internal template'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_definition_export BEFORE INSERT ON cehub_product.definition_exports
FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_definition_export();
CREATE TRIGGER immutable_definition_export BEFORE UPDATE OR DELETE ON cehub_product.definition_exports
FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_product.definition_exports FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_product.guard_definition_export() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_product.definition_exports) THEN RAISE EXCEPTION 'Retain definition export history'; END IF; END $$;"
    )
    op.execute("DROP TABLE cehub_product.definition_exports")
    op.execute("DROP FUNCTION cehub_product.guard_definition_export()")
