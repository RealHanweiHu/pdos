"""Shared physical capacity aggregates never disclose foreign business identities."""

from alembic import op

revision = "s0_0403"
down_revision = "s0_0402"
branch_labels = None
depends_on = None

SQL = """
CREATE FUNCTION physical_capacity_summary(t uuid,c uuid,p uuid,typ text,ids uuid[],own uuid,exclude_kind text)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE result jsonb;
BEGIN
 IF NOT category_access(t,c,false) OR NOT EXISTS(
  SELECT 1 FROM products m WHERE m.tenant_id=t AND m.category_id=c AND m.id=p
   AND source_object_audience(t,c,'products',m.id,m.owner_id,m.visibility)
 ) OR typ NOT IN ('resource','material','sample') OR exclude_kind NOT IN ('build','test_run') THEN RETURN NULL; END IF;
 IF cardinality(ids)=0 THEN RETURN '[]'::jsonb; END IF;
 IF typ IN ('resource','material') AND EXISTS(
  SELECT 1 FROM unnest(ids) a(id) WHERE NOT EXISTS(SELECT 1 FROM operational_asset_sentinels x
   WHERE x.tenant_id=t AND x.id=a.id AND x.kind=typ)
 ) THEN RETURN NULL; END IF;
 IF typ='sample' AND EXISTS(
  SELECT 1 FROM unnest(ids) a(id) WHERE NOT EXISTS(SELECT 1 FROM sample_units x
   WHERE x.tenant_id=t AND x.category_id=c AND x.product_id=p AND x.id=a.id
    AND source_object_audience(t,c,'sample_units',x.id,x.owner_id,x.visibility)
    AND direct_source_set_visible(t,c,p,x.required_source_read_set))
 ) THEN RETURN NULL; END IF;
 IF typ='resource' THEN
  SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]'::jsonb) INTO result FROM (
   SELECT resource_id,window_start,window_finish,sum(units) AS units,
    md5(resource_id::text||window_start::text||window_finish::text)::uuid AS id
   FROM operational_resource_occupancies
   WHERE tenant_id=t AND resource_id=ANY(ids)
    AND NOT (own IS NOT NULL AND owner_execution_id=own AND owner_kind=exclude_kind AND product_id=p AND category_id=c)
   GROUP BY resource_id,window_start,window_finish
   ORDER BY resource_id,window_start,window_finish
  ) x;
 ELSIF typ='material' THEN
  SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]'::jsonb) INTO result FROM (
   SELECT asset_id,unit,sum(quantity) AS quantity
   FROM operational_material_holds
   WHERE tenant_id=t AND asset_id=ANY(ids)
    AND NOT (own IS NOT NULL AND owner_execution_id=own AND product_id=p AND category_id=c)
   GROUP BY asset_id,unit ORDER BY asset_id,unit
  ) x;
 ELSE
  SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]'::jsonb) INTO result FROM (
   SELECT sample_id,destructive,window_start,window_finish
   FROM sample_run_usages
   WHERE tenant_id=t AND category_id=c AND product_id=p AND sample_id=ANY(ids)
    AND NOT (own IS NOT NULL AND run_id=own)
   GROUP BY sample_id,destructive,window_start,window_finish
   ORDER BY sample_id,window_start,window_finish,destructive
  ) x;
 END IF;
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION physical_capacity_summary(uuid,uuid,uuid,text,uuid[],uuid,text) FROM PUBLIC,pdos_agent;
GRANT EXECUTE ON FUNCTION physical_capacity_summary(uuid,uuid,uuid,text,uuid[],uuid,text) TO pdos_next_app;
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    op.execute("DROP FUNCTION physical_capacity_summary(uuid,uuid,uuid,text,uuid[],uuid,text)")
