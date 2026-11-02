"""Derived content cannot outlive its direct sources' audience permission."""

from alembic import op

revision = "s0_0008"
down_revision = "s0_0007"
branch_labels = None
depends_on = None

READ_SETS = (
    "parts",
    "bom_revisions",
    "engineering_configurations",
    "process_revisions",
    "supply_source_captures",
    "supply_snapshots",
    "supply_kit_projections",
    "cost_source_captures",
    "cost_input_snapshots",
    "cost_estimates",
)

SQL = """
CREATE FUNCTION source_object_audience(t uuid, c uuid, typ text, sid uuid, own uuid, vis text)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT category_access(t,c,false) AND (
   vis='category' OR own=scope_requester() OR EXISTS (
     SELECT 1 FROM object_audiences a
     WHERE a.tenant_id=t AND a.category_id=c AND a.object_type=typ
       AND a.subject_id=sid AND a.owner_id=own AND a.principal_id=scope_requester()
   )
 )
$$;
CREATE FUNCTION direct_source_set_visible(t uuid, c uuid, p uuid, refs jsonb)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT category_access(t,c,false) AND jsonb_typeof(refs)='array' AND NOT EXISTS (
   SELECT 1 FROM jsonb_array_elements(refs) r
   LEFT JOIN artifact_versions a ON a.id=(r->>'artifact_id')::uuid
     AND a.tenant_id=t AND a.category_id=c AND a.product_id=p
   LEFT JOIN products m ON m.id=a.product_id AND m.tenant_id=t AND m.category_id=c
   LEFT JOIN uploaded_originals o ON o.id=a.original_id AND o.tenant_id=t AND o.category_id=c
   WHERE a.id IS NULL OR m.id IS NULL
     OR NOT source_object_audience(t,c,'products',m.id,m.owner_id,m.visibility)
     OR NOT source_object_audience(t,c,'artifact_versions',a.id,a.owner_id,a.visibility)
     OR (a.original_id IS NOT NULL AND (o.id IS NULL
       OR NOT source_object_audience(t,c,'uploaded_originals',o.id,o.owner_id,o.visibility)))
 )
$$;
CREATE FUNCTION definition_sources_visible(t uuid, c uuid, p uuid, d uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT direct_source_set_visible(t,c,p,COALESCE(
   (SELECT jsonb_agg(jsonb_build_object('artifact_id',artifact_id))
    FROM definition_sources WHERE tenant_id=t AND category_id=c AND product_id=p
      AND definition_id=d), '[]'::jsonb))
$$;
REVOKE ALL ON FUNCTION source_object_audience(uuid,uuid,text,uuid,uuid,text) FROM PUBLIC,pdos_agent;
REVOKE ALL ON FUNCTION direct_source_set_visible(uuid,uuid,uuid,jsonb) FROM PUBLIC,pdos_agent;
REVOKE ALL ON FUNCTION definition_sources_visible(uuid,uuid,uuid,uuid) FROM PUBLIC,pdos_agent;
GRANT EXECUTE ON FUNCTION direct_source_set_visible(uuid,uuid,uuid,jsonb) TO pdos_next_app;
GRANT EXECUTE ON FUNCTION definition_sources_visible(uuid,uuid,uuid,uuid) TO pdos_next_app;
"""


def upgrade():
    op.execute(SQL)
    op.execute(
        "CREATE POLICY direct_source_audience ON definition_revisions AS RESTRICTIVE "
        "FOR SELECT TO pdos_next_app USING "
        "(definition_sources_visible(tenant_id,category_id,product_id,id))"
    )
    for table in READ_SETS:
        op.execute(
            f"CREATE POLICY direct_source_audience ON {table} AS RESTRICTIVE "
            "FOR SELECT TO pdos_next_app USING "
            "(direct_source_set_visible(tenant_id,category_id,product_id,required_source_read_set))"
        )
    op.execute(
        "CREATE POLICY direct_source_audience ON variant_revisions AS RESTRICTIVE "
        "FOR SELECT TO pdos_next_app USING "
        "(direct_source_set_visible(tenant_id,category_id,product_id,effective_definition->'sources'))"
    )


def downgrade():
    for table in (*READ_SETS, "definition_revisions", "variant_revisions"):
        op.execute(f"DROP POLICY direct_source_audience ON {table}")
    op.execute("DROP FUNCTION definition_sources_visible(uuid,uuid,uuid,uuid)")
    op.execute("DROP FUNCTION direct_source_set_visible(uuid,uuid,uuid,jsonb)")
    op.execute("DROP FUNCTION source_object_audience(uuid,uuid,text,uuid,uuid,text)")
