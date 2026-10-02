"""Internal append-only ERP/PLM reference receipts, never master data synchronization."""

# ruff: noqa: E501
from alembic import op

revision = "0409_product_master_references"
down_revision = "0408_resource_guard_alias"
branch_labels = None
depends_on = None

DDL = "\nCREATE TABLE cehub_product.product_master_references (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tmarket_space_id UUID NOT NULL, \n\tproduct_id UUID NOT NULL, \n\tprevious_id UUID, \n\tcreated_by_user_id UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcontext_digest VARCHAR(64) NOT NULL, \n\taction VARCHAR(16) NOT NULL, \n\tsystem_kind VARCHAR(8) NOT NULL, \n\tsource_system VARCHAR(128) NOT NULL, \n\tmaster_kind VARCHAR(16) NOT NULL, \n\texternal_id TEXT NOT NULL, \n\texternal_revision TEXT NOT NULL, \n\texternal_as_of TIMESTAMP WITH TIME ZONE NOT NULL, \n\tsources JSONB NOT NULL, \n\treason TEXT NOT NULL, \n\tdefinition_ref JSONB NOT NULL, \n\tproduct_snapshot JSONB NOT NULL, \n\tversion INTEGER DEFAULT 1 NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT pk_product_master_references PRIMARY KEY (id), \n\tCONSTRAINT uq_master_reference_scope UNIQUE (tenant_id, market_space_id, product_id, id), \n\tCONSTRAINT uq_master_reference_request UNIQUE (tenant_id, market_space_id, product_id, request_id), \n\tCONSTRAINT uq_master_reference_successor UNIQUE (tenant_id, previous_id), \n\tCONSTRAINT fk_product_master_references_tenant_id_product_nodes FOREIGN KEY(tenant_id, market_space_id, product_id) REFERENCES cehub_product.product_nodes (tenant_id, market_space_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_product_master_references_tenant_id_product_master_r_34d1 FOREIGN KEY(tenant_id, market_space_id, product_id, previous_id) REFERENCES cehub_product.product_master_references (tenant_id, market_space_id, product_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_product_master_references_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_product_master_references_master_reference_action CHECK (action IN ('register','correct','withdraw') AND ((action='register' AND previous_id IS NULL) OR (action<>'register' AND previous_id IS NOT NULL)) AND previous_id IS DISTINCT FROM id), \n\tCONSTRAINT ck_product_master_references_master_reference_kind CHECK ((master_kind='material' AND system_kind='erp') OR (master_kind='cad_revision' AND system_kind='plm') OR (master_kind='product' AND system_kind IN ('erp','plm'))), \n\tCONSTRAINT ck_product_master_references_master_reference_bounds CHECK (version=1 AND btrim(source_system)<>'' AND btrim(external_id)<>'' AND btrim(external_revision)<>'' AND btrim(reason)<>''), \n\tCONSTRAINT ck_product_master_references_master_reference_digests CHECK (request_digest ~ '^[a-f0-9]{64}$' AND context_digest ~ '^[a-f0-9]{64}$'), \n\tCONSTRAINT ck_product_master_references_master_reference_json CHECK (jsonb_typeof(sources)='array' AND jsonb_array_length(sources)>0 AND jsonb_typeof(definition_ref)='object' AND jsonb_typeof(product_snapshot)='object'), \n\tCONSTRAINT ck_product_master_references_master_reference_identity CHECK (source_system ~ '^[a-zA-Z0-9_.:-]+$' AND length(external_id)<=2048 AND length(external_revision)<=2048 AND length(reason)<=2048 AND definition_ref ?& ARRAY['id','version','revision','digest','release_id'] AND definition_ref->>'digest' ~ '^[a-f0-9]{64}$' AND product_snapshot ?& ARRAY['id','version','code','name','level','lifecycle'])\n)\n\n"

GUARD = r"""
CREATE FUNCTION cehub_product.guard_product_master_reference() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE prior cehub_product.product_master_references%ROWTYPE;
 latest cehub_product.definition_releases%ROWTYPE;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Master reference receipts are append-only'; END IF;
 IF NOT EXISTS(SELECT 1 FROM cehub_product.product_nodes WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.product_id AND level IN ('model','variant'))
 THEN RAISE EXCEPTION 'Master references require model or variant'; END IF;
 IF NEW.external_as_of>CURRENT_TIMESTAMP THEN RAISE EXCEPTION 'External reference time cannot be in the future'; END IF;
 IF NEW.action IN ('register','correct') THEN
  SELECT * INTO latest FROM cehub_product.definition_releases
   WHERE tenant_id=NEW.tenant_id AND product_id=NEW.product_id ORDER BY sequence DESC LIMIT 1;
  IF NOT FOUND OR latest.action<>'publish' OR latest.market_space_id<>NEW.market_space_id
   OR latest.id::text IS DISTINCT FROM NEW.definition_ref->>'release_id'
   OR latest.definition_id::text IS DISTINCT FROM NEW.definition_ref->>'id'
   OR NOT EXISTS(SELECT 1 FROM cehub_product.product_definitions d WHERE d.tenant_id=NEW.tenant_id
    AND d.market_space_id=NEW.market_space_id AND d.product_id=NEW.product_id AND d.id=latest.definition_id
    AND d.state='published' AND d.version::text=NEW.definition_ref->>'version'
    AND d.revision_number::text=NEW.definition_ref->>'revision')
   OR NOT EXISTS(SELECT 1 FROM cehub_product.product_nodes n WHERE n.tenant_id=NEW.tenant_id
    AND n.market_space_id=NEW.market_space_id AND n.id=NEW.product_id AND n.lifecycle<>'retired'
    AND n.id::text=NEW.product_snapshot->>'id' AND n.version::text=NEW.product_snapshot->>'version')
  THEN RAISE EXCEPTION 'Registration requires the actual current published definition and product'; END IF;
 END IF;

 IF NEW.previous_id IS NOT NULL THEN
  SELECT * INTO prior FROM cehub_product.product_master_references WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND product_id=NEW.product_id AND id=NEW.previous_id;
  IF NOT FOUND OR prior.action='withdraw' THEN RAISE EXCEPTION 'Previous reference must be active and in the same product'; END IF;
  IF NEW.action='withdraw' AND (NEW.system_kind,NEW.source_system,NEW.master_kind,NEW.external_id,NEW.external_revision,NEW.external_as_of,NEW.sources,NEW.definition_ref,NEW.product_snapshot,NEW.context_digest)
   IS DISTINCT FROM (prior.system_kind,prior.source_system,prior.master_kind,prior.external_id,prior.external_revision,prior.external_as_of,prior.sources,prior.definition_ref,prior.product_snapshot,prior.context_digest)
  THEN RAISE EXCEPTION 'Withdrawal must preserve reference identity and frozen context'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER product_master_reference_guard BEFORE INSERT OR UPDATE OR DELETE ON cehub_product.product_master_references
 FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_product_master_reference();
REVOKE ALL ON cehub_product.product_master_references FROM PUBLIC,pdos_agent;
REVOKE ALL ON FUNCTION cehub_product.guard_product_master_reference() FROM PUBLIC,pdos_agent;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_product.product_master_references) THEN RAISE EXCEPTION 'Cannot discard master reference history'; END IF; END $$;"
    )
    op.execute(
        "DROP TABLE cehub_product.product_master_references; DROP FUNCTION cehub_product.guard_product_master_reference();"
    )
