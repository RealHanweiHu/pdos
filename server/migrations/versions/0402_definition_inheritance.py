"""Pinned parent definition references, sparse overlays and derived product identity."""

# ruff: noqa: E501 -- SQL remains readable as one migration contract.

import json

from alembic import op
from sqlalchemy import String, literal, text

revision = "0402_definition_inheritance"
down_revision = "0401_product_planning_findings"
branch_labels = None
depends_on = None

FUNCTIONS = (
    "cehub_product.protect_product_definition",
    "cehub_product.protect_definition_review",
    "cehub_product.guard_planning_finding_origin",
)

SQL = r"""
ALTER TABLE cehub_product.product_nodes ADD COLUMN derived_from uuid,
 ADD CONSTRAINT ck_product_nodes_derivation_not_self CHECK(derived_from IS NULL OR derived_from<>id),
 ADD CONSTRAINT fk_product_nodes_derived_from FOREIGN KEY(tenant_id,market_space_id,derived_from)
 REFERENCES cehub_product.product_nodes(tenant_id,market_space_id,id) ON DELETE RESTRICT;
ALTER TABLE cehub_product.product_definitions ADD COLUMN base_definition_id uuid,
 ADD COLUMN base_definition_ref jsonb,
 ADD COLUMN parent_updates jsonb NOT NULL DEFAULT '[]'::jsonb,
 ADD CONSTRAINT ck_product_definitions_base_shape CHECK((base_definition_id IS NULL)=(base_definition_ref IS NULL)),
 ADD CONSTRAINT fk_product_definitions_base FOREIGN KEY(tenant_id,market_space_id,base_definition_id)
 REFERENCES cehub_product.product_definitions(tenant_id,market_space_id,id) ON DELETE RESTRICT;
CREATE FUNCTION cehub_product.resolve_definition_content(tenant uuid,base uuid,local_content jsonb,depth integer DEFAULT 0)
RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
DECLARE parent cehub_product.product_definitions; prior jsonb; items jsonb;
BEGIN
 IF base IS NULL THEN RETURN local_content; END IF;
 IF depth>=32 THEN RAISE EXCEPTION 'Definition inheritance depth exceeded'; END IF;
 SELECT * INTO parent FROM cehub_product.product_definitions WHERE tenant_id=tenant AND id=base AND state='published';
 IF parent.id IS NULL THEN RAISE EXCEPTION 'Inheritance requires a pinned published definition'; END IF;
 prior=cehub_product.resolve_definition_content(tenant,parent.base_definition_id,parent.content,depth+1);
 SELECT coalesce(jsonb_agg(coalesce(b.item,a.item) ORDER BY coalesce(a.pos,100000+b.pos)), '[]'::jsonb)
 INTO items FROM jsonb_array_elements(prior->'items') WITH ORDINALITY a(item,pos)
 FULL JOIN jsonb_array_elements(coalesce(local_content->'items','[]'::jsonb)) WITH ORDINALITY b(item,pos)
 ON a.item->>'item_key'=b.item->>'item_key';
 RETURN (prior || local_content) || jsonb_build_object('items',items);
END $$;
CREATE FUNCTION cehub_product.guard_product_derivation() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE source cehub_product.product_nodes;
BEGIN
 IF TG_OP='UPDATE' AND NEW.derived_from IS DISTINCT FROM OLD.derived_from THEN
  RAISE EXCEPTION 'Product derivation origin is immutable'; END IF;
 IF TG_OP='INSERT' AND NEW.derived_from IS NOT NULL THEN
  SELECT * INTO source FROM cehub_product.product_nodes WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.derived_from;
  IF source.id IS NULL OR source.id=NEW.id OR source.product_line_id<>NEW.product_line_id OR source.level<>NEW.level
   OR source.level='line' OR source.lifecycle='retired' OR NOT EXISTS(
    SELECT 1 FROM cehub_product.definition_releases r WHERE r.tenant_id=NEW.tenant_id AND r.product_id=source.id AND r.action='publish'
    AND NOT EXISTS(SELECT 1 FROM cehub_product.definition_releases n WHERE n.tenant_id=r.tenant_id AND n.product_id=r.product_id AND n.sequence>r.sequence))
  THEN RAISE EXCEPTION 'Derived product requires a current released product in the same line and level'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER product_derivation_guard BEFORE INSERT OR UPDATE ON cehub_product.product_nodes
 FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_product_derivation();
CREATE FUNCTION cehub_product.guard_definition_base() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE product cehub_product.product_nodes; parent cehub_product.product_definitions; content jsonb; accepted jsonb; update_source cehub_product.product_definitions;
BEGIN
 SELECT * INTO product FROM cehub_product.product_nodes WHERE tenant_id=NEW.tenant_id AND id=NEW.product_id;
 IF (NEW.base_definition_id IS NULL) IS DISTINCT FROM (product.derived_from IS NULL) THEN
  RAISE EXCEPTION 'Derived product definitions must retain their pinned parent'; END IF;
 IF TG_OP='UPDATE' AND (NEW.base_definition_id,NEW.base_definition_ref) IS DISTINCT FROM (OLD.base_definition_id,OLD.base_definition_ref)
  THEN RAISE EXCEPTION 'Pinned base is immutable; accepted parent changes remain local overlays'; END IF;
 IF jsonb_typeof(NEW.parent_updates) IS DISTINCT FROM 'array' OR
  (TG_OP='INSERT' AND NEW.parent_updates IS DISTINCT FROM coalesce((SELECT parent_updates FROM cehub_product.product_definitions WHERE tenant_id=NEW.tenant_id AND id=NEW.supersedes_id),'[]'::jsonb)) THEN RAISE EXCEPTION 'Parent updates start with an empty history'; END IF;
 IF TG_OP='UPDATE' AND NEW.parent_updates IS DISTINCT FROM OLD.parent_updates THEN
  IF NEW.base_definition_id IS NULL OR OLD.state<>'draft' OR NEW.state<>'draft'
   OR jsonb_array_length(NEW.parent_updates)<>jsonb_array_length(OLD.parent_updates)+1
   OR NEW.parent_updates - (jsonb_array_length(NEW.parent_updates)-1) IS DISTINCT FROM OLD.parent_updates
  THEN RAISE EXCEPTION 'Parent update history must append once on a derived draft'; END IF;
  accepted=NEW.parent_updates->-1;
  SELECT * INTO update_source FROM cehub_product.product_definitions WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=(accepted->'source'->>'ref_id')::uuid;
  IF update_source.id IS NULL OR update_source.state<>'published' OR update_source.product_id<>product.derived_from
   OR accepted->'source'->>'kind' IS DISTINCT FROM 'product_definition'
   OR accepted->'source'->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text
   OR accepted->'source'->>'version' IS DISTINCT FROM update_source.version::text
   OR accepted->'source'->>'digest' IS DISTINCT FROM update_source.review_digest
   OR jsonb_typeof(accepted->'accepted_paths') IS DISTINCT FROM 'array' OR jsonb_array_length(accepted->'accepted_paths')<1
  THEN RAISE EXCEPTION 'Accepted parent updates must preserve the actual published source'; END IF;
 END IF;
 IF NEW.base_definition_id IS NOT NULL THEN
  SELECT * INTO parent FROM cehub_product.product_definitions WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.base_definition_id;
  IF parent.id IS NULL OR parent.id=NEW.id OR parent.product_id<>product.derived_from OR parent.product_line_id<>NEW.product_line_id
   OR parent.state<>'published' OR NEW.base_definition_ref->>'ref_id' IS DISTINCT FROM parent.id::text
   OR NEW.base_definition_ref->>'kind' IS DISTINCT FROM 'product_definition'
   OR NEW.base_definition_ref->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text
   OR NEW.base_definition_ref->>'version' IS DISTINCT FROM parent.version::text
   OR NEW.base_definition_ref->>'digest' IS DISTINCT FROM parent.review_digest
  THEN RAISE EXCEPTION 'Definition base must pin the derived product parent publication'; END IF;
  content=cehub_product.resolve_definition_content(NEW.tenant_id,NEW.base_definition_id,NEW.content);
  IF jsonb_typeof(NEW.content->'items') IS DISTINCT FROM 'array' OR jsonb_typeof(NEW.content->'reviewers') IS DISTINCT FROM 'object'
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(content->'items') i GROUP BY i->>'item_key' HAVING count(*)>1)
  THEN RAISE EXCEPTION 'Derived definition local_content must preserve unique specification keys and local reviewers'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER definition_base_guard BEFORE INSERT OR UPDATE ON cehub_product.product_definitions
 FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_definition_base();
REVOKE ALL ON FUNCTION cehub_product.resolve_definition_content(uuid,uuid,jsonb,integer),
 cehub_product.guard_product_derivation(),cehub_product.guard_definition_base() FROM PUBLIC,pdos_agent;
"""


def _quote(value: str) -> str:
    return str(literal(value, type_=String).compile(compile_kwargs={"literal_binds": True}))


def upgrade() -> None:
    op.execute(SQL)
    c = op.get_bind()
    for name in FUNCTIONS:
        original, comment = c.execute(
            text(
                "SELECT pg_get_functiondef(p.oid),obj_description(p.oid,'pg_proc') "
                "FROM pg_proc p WHERE p.oid=CAST(:signature AS regprocedure)"
            ),
            {"signature": name + "()"},
        ).one()
        updated = original
        for alias in ("NEW", "OLD", "previous", "definition"):
            updated = updated.replace(
                f"{alias}.content",
                f"(cehub_product.resolve_definition_content({alias}.tenant_id,{alias}.base_definition_id,{alias}.content))",
            )
        op.execute(updated)
        op.execute(
            f"COMMENT ON FUNCTION {name}() IS "
            + _quote(json.dumps({"definition": original, "comment": comment}))
        )


def downgrade() -> None:
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_product.product_nodes WHERE derived_from IS NOT NULL)
     OR EXISTS(SELECT 1 FROM cehub_product.product_definitions WHERE base_definition_id IS NOT NULL)
     THEN RAISE EXCEPTION 'Cannot remove definition inheritance history'; END IF; END $$;""")
    c = op.get_bind()
    for name in FUNCTIONS:
        prior = json.loads(
            c.execute(
                text("SELECT obj_description(CAST(:signature AS regprocedure),'pg_proc')"),
                {"signature": name + "()"},
            ).scalar_one()
        )
        op.execute(prior["definition"])
        op.execute(
            f"COMMENT ON FUNCTION {name}() IS "
            + (_quote(prior["comment"]) if prior["comment"] is not None else "NULL")
        )
    op.execute("""
DROP TRIGGER definition_base_guard ON cehub_product.product_definitions;
DROP TRIGGER product_derivation_guard ON cehub_product.product_nodes;
DROP FUNCTION cehub_product.guard_definition_base(),cehub_product.guard_product_derivation();
DROP FUNCTION cehub_product.resolve_definition_content(uuid,uuid,jsonb,integer);
ALTER TABLE cehub_product.product_definitions DROP CONSTRAINT fk_product_definitions_base,
 DROP CONSTRAINT ck_product_definitions_base_shape,DROP COLUMN base_definition_id,DROP COLUMN base_definition_ref,DROP COLUMN parent_updates;
ALTER TABLE cehub_product.product_nodes DROP CONSTRAINT fk_product_nodes_derived_from,
 DROP CONSTRAINT ck_product_nodes_derivation_not_self,DROP COLUMN derived_from;
""")
