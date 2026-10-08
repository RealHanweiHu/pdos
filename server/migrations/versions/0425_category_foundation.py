# ruff: noqa: E501
"""Product lines as categories, common parameter versions and cross-category platforms."""

from alembic import op
from sqlalchemy import text

revision = "0425_category_foundation"
down_revision = "0424_product_proposals"
branch_labels = None
depends_on = None

DDL = "\nCREATE TABLE cehub_product.category_parameters (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tmarket_space_id UUID NOT NULL, \n\tproduct_line_id UUID NOT NULL, \n\tactor_user_id UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tparameter_id UUID NOT NULL, \n\tversion INTEGER NOT NULL, \n\tkey VARCHAR(64) NOT NULL, \n\tlabel VARCHAR(128) NOT NULL, \n\tunit VARCHAR(64) NOT NULL, \n\tconditions TEXT NOT NULL, \n\tdirection VARCHAR(32) NOT NULL, \n\tverification_method TEXT NOT NULL, \n\tacceptance_criterion TEXT NOT NULL, \n\treason TEXT NOT NULL, \n\tCONSTRAINT pk_category_parameters PRIMARY KEY (id), \n\tCONSTRAINT uq_category_parameters_request UNIQUE (tenant_id, request_id), \n\tCONSTRAINT uq_category_parameters_identity UNIQUE (tenant_id, id), \n\tCONSTRAINT fk_category_parameters_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_category_parameters_line FOREIGN KEY(tenant_id, market_space_id, product_line_id) REFERENCES cehub_product.product_nodes (tenant_id, market_space_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_category_parameters_revision UNIQUE (tenant_id, parameter_id, version), \n\tCONSTRAINT uq_category_parameters_key_version UNIQUE (tenant_id, product_line_id, key, version), \n\tCONSTRAINT ck_category_parameters_parameter_bounds CHECK (version>0 AND direction IN ('higher','lower','target','neutral') AND btrim(key)<>'' AND btrim(label)<>'' AND btrim(unit)<>'' AND btrim(conditions)<>'')\n)\n\n\n;\n\nCREATE TABLE cehub_product.category_knowledge (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tmarket_space_id UUID NOT NULL, \n\tproduct_line_id UUID NOT NULL, \n\tactor_user_id UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tkind VARCHAR(32) NOT NULL, \n\ttitle VARCHAR(256) NOT NULL, \n\tbody TEXT NOT NULL, \n\tregions JSONB NOT NULL, \n\tsource_refs JSONB NOT NULL, \n\torigin VARCHAR(32) NOT NULL, \n\tCONSTRAINT pk_category_knowledge PRIMARY KEY (id), \n\tCONSTRAINT uq_category_knowledge_request UNIQUE (tenant_id, request_id), \n\tCONSTRAINT uq_category_knowledge_identity UNIQUE (tenant_id, id), \n\tCONSTRAINT fk_category_knowledge_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_category_knowledge_line FOREIGN KEY(tenant_id, market_space_id, product_line_id) REFERENCES cehub_product.product_nodes (tenant_id, market_space_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_category_knowledge_knowledge_shape CHECK (kind IN ('scene','voice','regulation','general_requirement') AND origin IN ('human_shared','human_anonymized') AND btrim(title)<>'' AND btrim(body)<>'' AND jsonb_typeof(regions)='array' AND jsonb_typeof(source_refs)='array')\n)\n\n\n;\n\nCREATE TABLE cehub_product.category_promotion_proofs (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tknowledge_id UUID NOT NULL, \n\tproposal_id UUID NOT NULL, \n\tproposal_version INTEGER NOT NULL, \n\tsource_digest VARCHAR(64) NOT NULL, \n\tactor_user_id UUID NOT NULL, \n\tCONSTRAINT pk_category_promotion_proofs PRIMARY KEY (id), \n\tCONSTRAINT fk_category_promotion_proofs_tenant_id_category_knowledge FOREIGN KEY(tenant_id, knowledge_id) REFERENCES cehub_product.category_knowledge (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_category_promotion_proofs_tenant_id_product_proposals FOREIGN KEY(tenant_id, proposal_id) REFERENCES cehub_product.product_proposals (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_category_promotion_proofs_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT\n)\n\n\n;\n\nCREATE TABLE cehub_product.technical_platforms (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tactor_user_id UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tcode VARCHAR(128) NOT NULL, \n\tname VARCHAR(256) NOT NULL, \n\tdescription TEXT NOT NULL, \n\tCONSTRAINT pk_technical_platforms PRIMARY KEY (id), \n\tCONSTRAINT uq_category_platforms_request UNIQUE (tenant_id, request_id), \n\tCONSTRAINT uq_category_platforms_identity UNIQUE (tenant_id, id), \n\tCONSTRAINT fk_technical_platforms_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_technical_platforms_code UNIQUE (tenant_id, code)\n)\n\n\n;\n\nCREATE TABLE cehub_product.product_platform_links (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tmarket_space_id UUID NOT NULL, \n\tproduct_line_id UUID NOT NULL, \n\tactor_user_id UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tproduct_id UUID NOT NULL, \n\tplatform_id UUID NOT NULL, \n\tversion INTEGER NOT NULL, \n\taction VARCHAR(16) NOT NULL, \n\treason TEXT NOT NULL, \n\tCONSTRAINT pk_product_platform_links PRIMARY KEY (id), \n\tCONSTRAINT uq_category_links_request UNIQUE (tenant_id, request_id), \n\tCONSTRAINT uq_category_links_identity UNIQUE (tenant_id, id), \n\tCONSTRAINT fk_product_platform_links_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_category_links_line FOREIGN KEY(tenant_id, market_space_id, product_line_id) REFERENCES cehub_product.product_nodes (tenant_id, market_space_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_product_platform_links_link_shape CHECK (version>0 AND action IN ('attach','detach') AND btrim(reason)<>''), \n\tCONSTRAINT uq_product_platform_links_revision UNIQUE (tenant_id, product_id, platform_id, version), \n\tCONSTRAINT fk_product_platform_links_tenant_id_product_nodes FOREIGN KEY(tenant_id, market_space_id, product_id) REFERENCES cehub_product.product_nodes (tenant_id, market_space_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_product_platform_links_tenant_id_technical_platforms FOREIGN KEY(tenant_id, platform_id) REFERENCES cehub_product.technical_platforms (tenant_id, id) ON DELETE RESTRICT\n)\n\n;"
PRIOR_NODE_GUARD = "CREATE OR REPLACE FUNCTION cehub_product.protect_product_identity() RETURNS trigger\n    LANGUAGE plpgsql SET search_path=pg_catalog AS $$\n    DECLARE parent cehub_product.product_nodes%ROWTYPE; required_level text;\n    BEGIN\n      IF TG_OP='DELETE' THEN\n        RAISE EXCEPTION 'Product identity history cannot be deleted' USING ERRCODE='42501';\n      END IF;\n      IF TG_OP='UPDATE' THEN\n        IF (NEW.id,NEW.tenant_id,NEW.market_space_id,NEW.product_line_id,NEW.parent_id,NEW.level,NEW.code,NEW.request_id,NEW.request_digest,NEW.created_at)\n          IS DISTINCT FROM (OLD.id,OLD.tenant_id,OLD.market_space_id,OLD.product_line_id,OLD.parent_id,OLD.level,OLD.code,OLD.request_id,OLD.request_digest,OLD.created_at) THEN\n          RAISE EXCEPTION 'Product identity and hierarchy are immutable' USING ERRCODE='42501';\n        END IF;\n        IF NEW IS DISTINCT FROM OLD AND NEW.version<>OLD.version+1 THEN\n          RAISE EXCEPTION 'Product version must advance once' USING ERRCODE='22023';\n        END IF;\n      END IF;\n      IF NEW.level<>'line' THEN\n        SELECT * INTO parent FROM cehub_product.product_nodes WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.parent_id;\n        required_level := CASE NEW.level WHEN 'family' THEN 'line' WHEN 'platform' THEN 'family' WHEN 'series' THEN 'platform' WHEN 'model' THEN 'series' WHEN 'variant' THEN 'model' END;\n        IF NOT FOUND OR parent.level<>required_level OR parent.product_line_id<>NEW.product_line_id THEN\n          RAISE EXCEPTION 'Product parent level or scope mismatch' USING ERRCODE='23514';\n        END IF;\n      END IF;\n      RETURN NEW;\n    END $$;"
NODE_GUARD = "CREATE OR REPLACE FUNCTION cehub_product.protect_product_identity() RETURNS trigger\n    LANGUAGE plpgsql SET search_path=pg_catalog AS $$\n    DECLARE parent cehub_product.product_nodes%ROWTYPE; required_level text;\n    BEGIN\n      IF TG_OP='DELETE' THEN\n        RAISE EXCEPTION 'Product identity history cannot be deleted' USING ERRCODE='42501';\n      END IF;\n      IF TG_OP='UPDATE' THEN\n        IF (NEW.id,NEW.tenant_id,NEW.market_space_id,NEW.product_line_id,NEW.parent_id,NEW.level,NEW.code,NEW.request_id,NEW.request_digest,NEW.created_at)\n          IS DISTINCT FROM (OLD.id,OLD.tenant_id,OLD.market_space_id,OLD.product_line_id,OLD.parent_id,OLD.level,OLD.code,OLD.request_id,OLD.request_digest,OLD.created_at) THEN\n          RAISE EXCEPTION 'Product identity and hierarchy are immutable' USING ERRCODE='42501';\n        END IF;\n        IF NEW IS DISTINCT FROM OLD AND NEW.version<>OLD.version+1 THEN\n          RAISE EXCEPTION 'Product version must advance once' USING ERRCODE='22023';\n        END IF;\n      END IF;\n      IF NEW.level<>'line' THEN\n        SELECT * INTO parent FROM cehub_product.product_nodes WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.parent_id;\n        required_level := CASE NEW.level WHEN 'family' THEN 'line' WHEN 'platform' THEN 'family' WHEN 'series' THEN 'platform' WHEN 'model' THEN 'series' WHEN 'variant' THEN 'model' END;\n        IF NOT FOUND OR (parent.level<>required_level AND NOT (NEW.level='model' AND parent.level='line')) OR parent.product_line_id<>NEW.product_line_id THEN\n          RAISE EXCEPTION 'Product parent level or scope mismatch' USING ERRCODE='23514';\n        END IF;\n      END IF;\n      RETURN NEW;\n    END $$;"

GUARDS = r"""
CREATE FUNCTION cehub_product.guard_category_record() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE p cehub_product.category_parameters%ROWTYPE; v integer;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Category and platform history is immutable'; END IF;
 IF TG_TABLE_NAME IN ('category_parameters','category_knowledge','product_platform_links') THEN
 IF NOT EXISTS
 (SELECT 1 FROM cehub_product.product_nodes WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.product_line_id AND level='line')
 THEN RAISE EXCEPTION 'Category must be a real product line'; END IF;
 END IF;
 IF TG_TABLE_NAME='category_parameters' THEN
  PERFORM pg_advisory_xact_lock(hashtextextended('category:'||NEW.tenant_id::text||':'||NEW.product_line_id::text,0));
  SELECT * INTO p FROM cehub_product.category_parameters WHERE tenant_id=NEW.tenant_id AND parameter_id=NEW.parameter_id ORDER BY version DESC LIMIT 1;
  IF FOUND THEN
   IF (NEW.market_space_id,NEW.product_line_id,NEW.key,NEW.version) IS DISTINCT FROM (p.market_space_id,p.product_line_id,p.key,p.version+1) THEN RAISE EXCEPTION 'Parameter identity is fixed and revisions advance once'; END IF;
  ELSIF NEW.version<>1 OR EXISTS(SELECT 1 FROM cehub_product.category_parameters WHERE tenant_id=NEW.tenant_id AND product_line_id=NEW.product_line_id AND key=NEW.key) THEN RAISE EXCEPTION 'Parameter starts at one unique category key'; END IF;
 ELSIF TG_TABLE_NAME='product_platform_links' THEN
  PERFORM pg_advisory_xact_lock(hashtextextended('category:'||NEW.tenant_id::text||':'||NEW.product_line_id::text,0));
  IF NOT EXISTS(SELECT 1 FROM cehub_product.product_nodes WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.product_id AND product_line_id=NEW.product_line_id AND level='model') THEN RAISE EXCEPTION 'Platform links belong to a model in this category'; END IF;
  SELECT coalesce(max(version),0) INTO v FROM cehub_product.product_platform_links WHERE tenant_id=NEW.tenant_id AND product_id=NEW.product_id AND platform_id=NEW.platform_id;
  IF NEW.version<>v+1 OR (v=0 AND NEW.action<>'attach') THEN RAISE EXCEPTION 'Platform link version is stale'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_product.guard_category_references() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE items jsonb; i jsonb; p cehub_product.category_parameters%ROWTYPE; k text; cond text;
BEGIN
 IF TG_TABLE_NAME='product_proposals' THEN
  IF TG_OP='UPDATE' AND (NEW.category_context,NEW.target_regions) IS DISTINCT FROM (OLD.category_context,OLD.target_regions) THEN RAISE EXCEPTION 'Proposal category origin is immutable'; END IF;
  IF TG_OP='INSERT' AND NEW.product_line_id IS NULL THEN RAISE EXCEPTION 'New proposal starts from a category'; END IF;
  items:=NEW.document->'specifications';
 ELSIF TG_TABLE_NAME='competitor_observations' THEN items:=NEW.metrics;
 ELSE items:=NEW.content->'items'; END IF;
 FOR i IN SELECT value FROM jsonb_array_elements(coalesce(items,'[]'::jsonb)) LOOP
  k:=coalesce(i->>'item_key',i->>'key',i->>'id');
  IF coalesce(i->>'parameter_id','')='' THEN
   IF coalesce(i->>'parameter_version','')<>'' THEN RAISE EXCEPTION 'Parameter version requires identity'; END IF;
   CONTINUE;
  END IF;
  SELECT * INTO p FROM cehub_product.category_parameters WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND product_line_id=NEW.product_line_id AND parameter_id::text=i->>'parameter_id' AND version::text=i->>'parameter_version';
  IF NOT FOUND THEN RAISE EXCEPTION 'Parameter belongs to another category or unavailable version'; END IF;
  cond:=i->>'conditions';
  IF jsonb_typeof(i->'conditions')='array' THEN SELECT string_agg(value,E'\n' ORDER BY ordinal) INTO cond FROM jsonb_array_elements_text(i->'conditions') WITH ORDINALITY AS a(value,ordinal); END IF;
  IF (k,i->>'unit',cond) IS DISTINCT FROM (p.key,p.unit,p.conditions) THEN RAISE EXCEPTION 'Parameter key, unit and conditions must match shared dictionary'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER category_proposal_refs BEFORE INSERT OR UPDATE ON cehub_product.product_proposals FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_category_references();
CREATE TRIGGER category_competitor_refs BEFORE INSERT OR UPDATE ON cehub_product.competitor_observations FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_category_references();
CREATE TRIGGER category_definition_refs BEFORE INSERT OR UPDATE ON cehub_product.product_definitions FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_category_references();
REVOKE ALL ON FUNCTION cehub_product.guard_category_record(),cehub_product.guard_category_references() FROM PUBLIC,pdos_agent;
"""

NAMES = (
    "category_parameters",
    "category_knowledge",
    "category_promotion_proofs",
    "technical_platforms",
    "product_platform_links",
)


def upgrade():
    op.execute(DDL)
    op.execute(
        "ALTER TABLE cehub_product.product_nodes ADD COLUMN tags jsonb NOT NULL DEFAULT '[]'::jsonb"
    )
    op.execute(
        "ALTER TABLE cehub_product.product_nodes ADD CONSTRAINT ck_product_nodes_tags CHECK (jsonb_typeof(tags)='array' AND jsonb_array_length(tags)<=30)"
    )
    op.execute(
        "ALTER TABLE cehub_product.product_proposals ADD COLUMN category_context jsonb NOT NULL DEFAULT '{}'::jsonb, ADD COLUMN target_regions jsonb NOT NULL DEFAULT '[]'::jsonb"
    )
    op.execute(NODE_GUARD)
    op.execute(GUARDS)
    for name in NAMES:
        op.execute(
            f"CREATE TRIGGER category_history_guard BEFORE INSERT OR UPDATE OR DELETE ON cehub_product.{name} FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_category_record()"
        )
        op.execute(f"REVOKE ALL ON cehub_product.{name} FROM PUBLIC,pdos_agent")


def downgrade():
    connection = op.get_bind()
    if (
        any(
            connection.execute(
                text(f"SELECT EXISTS(SELECT 1 FROM cehub_product.{name})")
            ).scalar_one()
            for name in NAMES
        )
        or connection.execute(
            text(
                "SELECT EXISTS(SELECT 1 FROM cehub_product.product_nodes n JOIN cehub_product.product_nodes p ON p.tenant_id=n.tenant_id AND p.id=n.parent_id WHERE n.level='model' AND p.level='line') OR EXISTS(SELECT 1 FROM cehub_product.product_nodes WHERE tags<>'[]'::jsonb) OR EXISTS(SELECT 1 FROM cehub_product.product_proposals WHERE category_context<>'{}'::jsonb OR target_regions<>'[]'::jsonb)"
            )
        ).scalar_one()
    ):
        raise RuntimeError(
            "Category references and platform history must be retained; downgrade refused"
        )
    for table, name in [
        ("product_proposals", "category_proposal_refs"),
        ("competitor_observations", "category_competitor_refs"),
        ("product_definitions", "category_definition_refs"),
    ]:
        op.execute(f"DROP TRIGGER {name} ON cehub_product.{table}")
    op.execute("DROP FUNCTION cehub_product.guard_category_references()")
    op.execute(PRIOR_NODE_GUARD)
    op.execute("ALTER TABLE cehub_product.product_nodes DROP COLUMN tags")
    op.execute(
        "ALTER TABLE cehub_product.product_proposals DROP COLUMN category_context, DROP COLUMN target_regions"
    )
    for name in reversed(NAMES):
        op.drop_table(name, schema="cehub_product")
    op.execute("DROP FUNCTION cehub_product.guard_category_record()")
