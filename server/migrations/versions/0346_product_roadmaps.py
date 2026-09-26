"""Immutable, named product roadmap revisions linked to published definitions."""

# ruff: noqa: E501
from alembic import op

revision = "0346_product_roadmaps"
down_revision = "0345_executive_brief_runs"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_product.product_roadmap_revisions (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	market_space_id UUID NOT NULL, 
	product_line_id UUID NOT NULL, 
	product_id UUID NOT NULL, 
	definition_id UUID NOT NULL, 
	release_id UUID NOT NULL, 
	version INTEGER NOT NULL, 
	state VARCHAR(20) NOT NULL, 
	body JSONB NOT NULL, 
	source_snapshot JSONB NOT NULL, 
	source_digest VARCHAR(64) NOT NULL, 
	reason TEXT NOT NULL, 
	actor_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_product_roadmap_revisions PRIMARY KEY (id), 
	CONSTRAINT uq_product_roadmap_version UNIQUE (tenant_id, product_id, version), 
	CONSTRAINT uq_product_roadmap_scope UNIQUE (tenant_id, market_space_id, id),
	CONSTRAINT uq_product_roadmap_request UNIQUE (tenant_id, actor_user_id, request_id), 
	CONSTRAINT fk_product_roadmap_product FOREIGN KEY(tenant_id, market_space_id, product_id) REFERENCES cehub_product.product_nodes (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_roadmap_line FOREIGN KEY(tenant_id, market_space_id, product_line_id) REFERENCES cehub_product.product_nodes (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_roadmap_definition FOREIGN KEY(tenant_id, market_space_id, definition_id) REFERENCES cehub_product.product_definitions (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_roadmap_release FOREIGN KEY(tenant_id, market_space_id, release_id) REFERENCES cehub_product.definition_releases (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_roadmap_actor FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_product_roadmap_revisions_shape CHECK (version>0 AND state IN ('published','withdrawn') AND btrim(reason)<>'' AND jsonb_typeof(body)='object' AND jsonb_typeof(source_snapshot)='object' AND source_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$')
)

;
"""
GUARDS = """
CREATE FUNCTION cehub_product.guard_product_roadmap() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prior cehub_product.product_roadmap_revisions%ROWTYPE;
BEGIN
 PERFORM 1 FROM cehub_product.market_spaces WHERE tenant_id=NEW.tenant_id AND id=NEW.market_space_id FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM cehub_product.product_nodes n JOIN cehub_product.definition_releases r ON r.tenant_id=n.tenant_id AND r.market_space_id=n.market_space_id AND r.product_id=n.id WHERE n.tenant_id=NEW.tenant_id AND n.market_space_id=NEW.market_space_id AND n.id=NEW.product_id AND n.product_line_id=NEW.product_line_id AND r.id=NEW.release_id AND r.definition_id=NEW.definition_id AND r.action='publish') THEN
  RAISE EXCEPTION 'Roadmap must reference its actual product and published definition';
 END IF;
 SELECT * INTO prior FROM cehub_product.product_roadmap_revisions WHERE tenant_id=NEW.tenant_id AND product_id=NEW.product_id ORDER BY version DESC LIMIT 1;
 IF NEW.version<>COALESCE(prior.version,0)+1 OR (prior.created_at IS NOT NULL AND NEW.created_at<prior.created_at) THEN
  RAISE EXCEPTION 'Roadmap versions must be sequential';
 END IF;
 IF NEW.state='withdrawn' AND (prior.id IS NULL OR prior.state<>'published' OR NEW.body IS DISTINCT FROM prior.body OR NEW.source_snapshot IS DISTINCT FROM prior.source_snapshot OR NEW.release_id<>prior.release_id OR NEW.definition_id<>prior.definition_id OR NEW.source_digest<>prior.source_digest) THEN
  RAISE EXCEPTION 'Withdrawal must retain the original roadmap and sources';
 END IF;
 IF NEW.state='published' AND NEW.release_id<>(SELECT id FROM cehub_product.definition_releases WHERE tenant_id=NEW.tenant_id AND product_id=NEW.product_id ORDER BY sequence DESC LIMIT 1) THEN
  RAISE EXCEPTION 'New roadmap must use the current definition release';
 END IF;
 IF NEW.source_snapshot->>'release_id' IS DISTINCT FROM NEW.release_id::text OR NEW.source_snapshot->>'definition_id' IS DISTINCT FROM NEW.definition_id::text OR NEW.source_snapshot->'product'->>'id' IS DISTINCT FROM NEW.product_id::text THEN
  RAISE EXCEPTION 'Roadmap source identity does not match references';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_product_roadmap BEFORE INSERT ON cehub_product.product_roadmap_revisions FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_product_roadmap();
CREATE TRIGGER immutable_product_roadmap BEFORE UPDATE OR DELETE ON cehub_product.product_roadmap_revisions FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)
    op.execute("REVOKE ALL ON cehub_product.product_roadmap_revisions FROM PUBLIC")


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_product.product_roadmap_revisions) THEN RAISE EXCEPTION 'Retain product roadmap history'; END IF; END $$;"
    )
    op.execute("DROP TABLE cehub_product.product_roadmap_revisions")
    op.execute("DROP FUNCTION cehub_product.guard_product_roadmap()")
