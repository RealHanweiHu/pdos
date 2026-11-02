"""Direct upstream audience checks remain in PostgreSQL for derived bodies.

Opaque invoker queries preserve RLS without expanding nested policies in the
outer query plan. Current pointers are excluded to avoid ownership cycles.
"""

from alembic import op

revision = "s0_0011"
down_revision = "s0_0010"
branch_labels = None
depends_on = None

EDGES = {
    "artifact_versions": (("original_id", "uploaded_originals"),),
    "claims": (("artifact_id", "artifact_versions"),),
    "definition_revisions": (("parent_definition_id", "definition_revisions"),),
    "variant_revisions": (
        ("parent_definition_id", "definition_revisions"),
        ("variant_id", "product_variants"),
    ),
    "plan_proposals": (("project_id", "projects"),),
    "plan_revisions": (("project_id", "projects"), ("proposal_id", "plan_proposals")),
    "engineering_configurations": (
        ("definition_id", "definition_revisions"),
        ("bom_id", "bom_revisions"),
    ),
    "process_revisions": (("engineering_configuration_id", "engineering_configurations"),),
}

SQL = """
CREATE FUNCTION upstream_row_visible(t uuid,c uuid,p uuid,typ text,sid uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=public,pg_temp AS $$
DECLARE visible boolean;
BEGIN
 IF NOT typ=ANY(ARRAY['uploaded_originals','artifact_versions','definition_revisions',
  'product_variants','projects','plan_proposals','bom_revisions','engineering_configurations'])
 THEN RETURN false; END IF;
 EXECUTE format('SELECT EXISTS(SELECT 1 FROM public.%I
  WHERE tenant_id=$1 AND category_id=$2 AND product_id=$3 AND id=$4)',typ)
 INTO visible USING t,c,p,sid;
 RETURN visible;
END $$;
CREATE FUNCTION project_definition_visible(t uuid,c uuid,p uuid,sid uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT category_access(t,c,false) AND NOT EXISTS(
  SELECT 1 FROM project_product_links l JOIN projects x ON x.id=l.project_id AND x.tenant_id=t
  LEFT JOIN definition_revisions d ON d.id=l.definition_id AND d.tenant_id=t
   AND d.category_id=c AND d.product_id=p
  WHERE l.tenant_id=t AND l.category_id=c AND l.product_id=p AND l.project_id=sid
   AND (d.id IS NULL OR NOT source_object_audience(t,c,'projects',x.id,x.owner_id,x.visibility)
    OR NOT source_object_audience(t,c,'definition_revisions',d.id,d.owner_id,d.visibility)
    OR NOT definition_sources_visible(t,c,p,d.id))
 )
$$;
REVOKE ALL ON FUNCTION upstream_row_visible(uuid,uuid,uuid,text,uuid) FROM PUBLIC,pdos_agent;
REVOKE ALL ON FUNCTION project_definition_visible(uuid,uuid,uuid,uuid) FROM PUBLIC,pdos_agent;
GRANT EXECUTE ON FUNCTION upstream_row_visible(uuid,uuid,uuid,text,uuid) TO pdos_next_app;
GRANT EXECUTE ON FUNCTION project_definition_visible(uuid,uuid,uuid,uuid) TO pdos_next_app;
"""


def upgrade():
    op.execute(SQL)
    for table, parents in EDGES.items():
        clauses = [
            f"({column} IS NULL OR upstream_row_visible(tenant_id,category_id,"
            f"product_id,'{parent}',{column}))"
            for column, parent in parents
        ]
        op.execute(
            f"CREATE POLICY upstream_audience ON {table} AS RESTRICTIVE "
            f"FOR SELECT TO pdos_next_app USING ({' AND '.join(clauses)})"
        )
    op.execute(
        "CREATE POLICY upstream_audience ON projects AS RESTRICTIVE "
        "FOR SELECT TO pdos_next_app USING "
        "(project_definition_visible(tenant_id,category_id,product_id,id))"
    )


def downgrade():
    for table in (*EDGES, "projects"):
        op.execute(f"DROP POLICY upstream_audience ON {table}")
    op.execute("DROP FUNCTION project_definition_visible(uuid,uuid,uuid,uuid)")
    op.execute("DROP FUNCTION upstream_row_visible(uuid,uuid,uuid,text,uuid)")
