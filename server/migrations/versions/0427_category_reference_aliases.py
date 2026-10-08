"""Old unbound shared records reference the same unified category dictionary."""

# ruff: noqa: E501
from alembic import op
from sqlalchemy import text

revision = "0427_category_reference_aliases"
down_revision = "0426_unified_categories"
branch_labels = None
depends_on = None

PRIOR = r"""CREATE OR REPLACE FUNCTION cehub_product.guard_category_references() RETURNS trigger
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
"""
UPDATED = r"""CREATE OR REPLACE FUNCTION cehub_product.guard_category_references() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE items jsonb; i jsonb; p cehub_product.category_parameters%ROWTYPE; k text; cond text; category_line uuid;
BEGIN
 IF TG_TABLE_NAME='product_proposals' THEN
  IF TG_OP='UPDATE' AND (NEW.category_context,NEW.target_regions) IS DISTINCT FROM (OLD.category_context,OLD.target_regions) THEN RAISE EXCEPTION 'Proposal category origin is immutable'; END IF;
  IF TG_OP='INSERT' AND NEW.product_line_id IS NULL THEN RAISE EXCEPTION 'New proposal starts from a category'; END IF;
  items:=NEW.document->'specifications';
 ELSIF TG_TABLE_NAME='competitor_observations' THEN items:=NEW.metrics;
 ELSE items:=NEW.content->'items'; END IF;
 category_line:=NEW.product_line_id;
 IF category_line IS NULL THEN SELECT id INTO STRICT category_line FROM cehub_product.product_nodes WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND level='line'; END IF;
 FOR i IN SELECT value FROM jsonb_array_elements(coalesce(items,'[]'::jsonb)) LOOP
  k:=coalesce(i->>'item_key',i->>'key',i->>'id');
  IF coalesce(i->>'parameter_id','')='' THEN
   IF coalesce(i->>'parameter_version','')<>'' THEN RAISE EXCEPTION 'Parameter version requires identity'; END IF;
   CONTINUE;
  END IF;
  SELECT * INTO p FROM cehub_product.category_parameters WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND product_line_id=category_line AND parameter_id::text=i->>'parameter_id' AND version::text=i->>'parameter_version';
  IF NOT FOUND THEN RAISE EXCEPTION 'Parameter belongs to another category or unavailable version'; END IF;
  cond:=i->>'conditions';
  IF jsonb_typeof(i->'conditions')='array' THEN SELECT string_agg(value,E'\n' ORDER BY ordinal) INTO cond FROM jsonb_array_elements_text(i->'conditions') WITH ORDINALITY AS a(value,ordinal); END IF;
  IF (k,i->>'unit',cond) IS DISTINCT FROM (p.key,p.unit,p.conditions) THEN RAISE EXCEPTION 'Parameter key, unit and conditions must match shared dictionary'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
"""


def upgrade():
    op.execute(UPDATED)
    op.execute(
        "REVOKE ALL ON FUNCTION cehub_product.guard_category_references() FROM PUBLIC,pdos_agent"
    )


def downgrade():
    c = op.get_bind()
    for table, column in (
        ("product_proposals", "document->'specifications'"),
        ("competitor_observations", "metrics"),
        ("product_definitions", "content->'items'"),
    ):
        if c.execute(
            text(
                f"SELECT EXISTS(SELECT 1 FROM cehub_product.{table} t CROSS JOIN LATERAL jsonb_array_elements(coalesce({column},'[]'::jsonb)) i WHERE t.product_line_id IS NULL AND coalesce(i->>'parameter_id','')<>'')"
            )
        ).scalar_one():
            raise RuntimeError(
                "Old category parameter references must be retained; downgrade refused"
            )
    op.execute(PRIOR)
    op.execute(
        "REVOKE ALL ON FUNCTION cehub_product.guard_category_references() FROM PUBLIC,pdos_agent"
    )
