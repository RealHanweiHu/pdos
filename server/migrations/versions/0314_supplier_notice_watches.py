"""Explicit in-use manufacturer part and public subscription mapping revisions."""

from alembic import op

revision = "0314_supplier_notice_watches"
down_revision = "0313_supplier_recovery_reviews"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_supplier.supplier_notice_watches (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
subscription_id UUID NOT NULL,
bom_id UUID NOT NULL,
bom_item_id UUID NOT NULL,
manufacturer VARCHAR(128) NOT NULL,
manufacturer_part_number VARCHAR(128) NOT NULL,
manufacturer_part_key VARCHAR(128) NOT NULL,
active BOOLEAN NOT NULL,
version INTEGER NOT NULL,
owner_user_id UUID NOT NULL,
command JSONB NOT NULL,
snapshot JSONB NOT NULL,
source_digest VARCHAR(64) NOT NULL,
created_at TIMESTAMP WITH TIME ZONE NOT NULL,
updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
CONSTRAINT pk_supplier_notice_watches PRIMARY KEY (id),
CONSTRAINT uq_supplier_notice_watch_scope UNIQUE (tenant_id, project_id, id),
CONSTRAINT uq_supplier_notice_watch_mapping UNIQUE (tenant_id, project_id, subscription_id,
bom_item_id, manufacturer_part_key),
CONSTRAINT fk_supplier_notice_watches_tenant_id_research_subscriptions FOREIGN KEY(tenant_id,
subscription_id) REFERENCES cehub_evidence.research_subscriptions (tenant_id, id) ON DELETE
RESTRICT,
CONSTRAINT fk_supplier_notice_watches_tenant_id_development_boms FOREIGN KEY(tenant_id,
project_id, bom_id) REFERENCES cehub_product.development_boms (tenant_id, project_id, id) ON
DELETE RESTRICT,
CONSTRAINT fk_supplier_notice_watches_tenant_id_development_bom_items FOREIGN KEY(tenant_id,
bom_id, bom_item_id) REFERENCES cehub_product.development_bom_items (tenant_id, bom_id, id) ON
DELETE RESTRICT,
CONSTRAINT fk_supplier_notice_watches_tenant_id_users FOREIGN KEY(tenant_id, owner_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_supplier_notice_watches_shape CHECK (version>0 AND btrim(manufacturer)<>'' AND
btrim(manufacturer_part_number)<>'' AND source_digest ~ '^[a-f0-9]{64}$' AND
jsonb_typeof(command)='object' AND jsonb_typeof(snapshot)='object')
)

;

CREATE TABLE cehub_supplier.supplier_notice_watch_revisions (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
watch_id UUID NOT NULL,
version INTEGER NOT NULL,
command JSONB NOT NULL,
snapshot JSONB NOT NULL,
source_digest VARCHAR(64) NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
created_by_user_id UUID NOT NULL,
created_at TIMESTAMP WITH TIME ZONE NOT NULL,
CONSTRAINT pk_supplier_notice_watch_revisions PRIMARY KEY (id),
CONSTRAINT uq_supplier_notice_revision_scope UNIQUE (tenant_id, project_id, id),
CONSTRAINT uq_supplier_notice_watch_version UNIQUE (watch_id, version),
CONSTRAINT uq_supplier_watch_request UNIQUE (tenant_id, created_by_user_id, request_id),
CONSTRAINT fk_supplier_notice_watch_revisions_tenant_id_supplier_n_c060 FOREIGN KEY(tenant_id,
project_id, watch_id) REFERENCES cehub_supplier.supplier_notice_watches (tenant_id, project_id,
id) ON DELETE RESTRICT,
CONSTRAINT fk_supplier_notice_watch_revisions_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_supplier_notice_watch_revisions_shape CHECK (version>0 AND source_digest ~
'^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$' AND jsonb_typeof(command)='object' AND
jsonb_typeof(snapshot)='object')
)

;
"""
GUARDS = """
CREATE FUNCTION cehub_supplier.guard_notice_watch() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Pause watches; retain their source history'; END IF;
IF TG_OP='UPDATE' AND (NEW.id<>OLD.id OR NEW.tenant_id<>OLD.tenant_id
OR NEW.project_id<>OLD.project_id OR NEW.owner_user_id<>OLD.owner_user_id
OR NEW.created_at<>OLD.created_at OR NEW.version<>OLD.version+1) THEN
RAISE EXCEPTION 'Watch identity and owner are fixed; revisions advance once'; END IF;
IF (TG_OP='INSERT' AND NEW.version<>1)
OR NEW.command->>'subscription_id' IS DISTINCT FROM NEW.subscription_id::text
OR NEW.command->>'bom_item_id' IS DISTINCT FROM NEW.bom_item_id::text
OR NEW.command->>'manufacturer' IS DISTINCT FROM NEW.manufacturer
OR NEW.command->>'manufacturer_part_number' IS DISTINCT FROM NEW.manufacturer_part_number
OR NEW.command->'active' IS DISTINCT FROM to_jsonb(NEW.active)
OR NEW.snapshot->'bom_item'->>'id' IS DISTINCT FROM NEW.bom_item_id::text
OR NEW.snapshot->'bom_item'->>'project_id' IS DISTINCT FROM NEW.project_id::text
OR NEW.snapshot->'bom_item'->>'bom_id' IS DISTINCT FROM NEW.bom_id::text
OR NEW.snapshot->'subscription'->>'id' IS DISTINCT FROM NEW.subscription_id::text
OR (NEW.active AND NOT EXISTS(SELECT 1 FROM cehub_project.documents d
WHERE d.tenant_id=NEW.tenant_id
AND d.project_id=NEW.project_id AND d.id::text=NEW.command->>'evidence_id')) THEN
RAISE EXCEPTION 'Watch requires exact project BOM and original mapping evidence'; END IF;
RETURN NEW;
END $$;
CREATE TRIGGER guard_notice_watch BEFORE INSERT OR UPDATE OR DELETE ON
cehub_supplier.supplier_notice_watches FOR EACH ROW
EXECUTE FUNCTION cehub_supplier.guard_notice_watch();

CREATE FUNCTION cehub_supplier.guard_notice_watch_revision() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE w cehub_supplier.supplier_notice_watches%ROWTYPE;
DECLARE previous integer;
BEGIN
SELECT * INTO w FROM cehub_supplier.supplier_notice_watches WHERE id=NEW.watch_id
AND tenant_id=NEW.tenant_id AND project_id=NEW.project_id;
SELECT coalesce(max(version),0) INTO previous FROM cehub_supplier.supplier_notice_watch_revisions
WHERE watch_id=NEW.watch_id;
IF w.id IS NULL OR NEW.version<>previous+1 OR w.version<>NEW.version
OR NEW.created_by_user_id<>w.owner_user_id OR NEW.command IS DISTINCT FROM w.command
OR NEW.snapshot IS DISTINCT FROM w.snapshot OR NEW.source_digest<>w.source_digest
OR NEW.command->>'request_id' IS DISTINCT FROM NEW.request_id::text
OR NEW.command->>'expected_version' IS DISTINCT FROM previous::text THEN
RAISE EXCEPTION 'Watch change requires original owner and consecutive source receipt'; END IF;
RETURN NEW;
END $$;
CREATE TRIGGER guard_notice_watch_revision BEFORE INSERT ON
cehub_supplier.supplier_notice_watch_revisions FOR EACH ROW
EXECUTE FUNCTION cehub_supplier.guard_notice_watch_revision();
CREATE TRIGGER protect_notice_watch_revisions BEFORE UPDATE OR DELETE ON
cehub_supplier.supplier_notice_watch_revisions FOR EACH ROW
EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();

CREATE FUNCTION cehub_supplier.require_notice_watch_revision() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
IF NOT EXISTS(SELECT 1 FROM cehub_supplier.supplier_notice_watch_revisions r
WHERE r.watch_id=NEW.id AND r.tenant_id=NEW.tenant_id AND r.project_id=NEW.project_id
AND r.version=NEW.version AND r.command=NEW.command AND r.snapshot=NEW.snapshot
AND r.source_digest=NEW.source_digest AND r.created_by_user_id=NEW.owner_user_id) THEN
RAISE EXCEPTION 'Watch configuration must commit with immutable revision'; END IF;
RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER require_notice_watch_revision AFTER INSERT OR UPDATE ON
cehub_supplier.supplier_notice_watches DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION cehub_supplier.require_notice_watch_revision();
REVOKE ALL ON cehub_supplier.supplier_notice_watches FROM PUBLIC;
REVOKE ALL ON cehub_supplier.supplier_notice_watch_revisions FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_supplier.guard_notice_watch() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_supplier.guard_notice_watch_revision() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_supplier.require_notice_watch_revision() FROM PUBLIC;

"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute("""
DO $$ BEGIN
IF EXISTS(SELECT 1 FROM cehub_supplier.supplier_notice_watch_revisions) THEN
RAISE EXCEPTION 'In-use mapping history requires retention'; END IF;
END $$;
DROP TABLE cehub_supplier.supplier_notice_watch_revisions;
DROP TABLE cehub_supplier.supplier_notice_watches;
DROP FUNCTION cehub_supplier.require_notice_watch_revision();
DROP FUNCTION cehub_supplier.guard_notice_watch_revision();
DROP FUNCTION cehub_supplier.guard_notice_watch();
""")
