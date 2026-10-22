"""Atomic occupancy insertion and opaque actual-configuration completeness."""

from alembic import op

revision = "s0_0402"
down_revision = "s0_0401"
branch_labels = None
depends_on = None

TABLES = ("operational_material_holds", "operational_resource_occupancies")


def upgrade():
    # The existing exact composite execution FK remains deferred to transaction end.
    # A staged occupancy is not readable before its final parent exists.
    for table in TABLES:
        op.execute(f"DROP POLICY category_scope ON {table}")
        base = (
            f"category_access(tenant_id,category_id,true) AND EXISTS(SELECT 1 FROM builds b "
            f"WHERE b.tenant_id={table}.tenant_id AND b.category_id={table}.category_id "
            f"AND b.product_id={table}.product_id AND b.project_id={table}.project_id "
            f"AND b.id={table}.build_id)"
        )
        op.execute(
            f"CREATE POLICY category_insert ON {table} FOR INSERT TO pdos_next_app WITH CHECK ({base})"
        )
        if table == "operational_material_holds":
            parent = (
                f"EXISTS(SELECT 1 FROM build_starts b WHERE b.tenant_id={table}.tenant_id "
                f"AND b.product_id={table}.product_id AND b.project_id={table}.project_id "
                f"AND b.build_id={table}.build_id AND b.id={table}.owner_execution_id)"
            )
        else:
            parent = (
                f"((owner_kind='build' AND EXISTS(SELECT 1 FROM build_starts b "
                f"WHERE b.tenant_id={table}.tenant_id AND b.product_id={table}.product_id "
                f"AND b.project_id={table}.project_id AND b.build_id={table}.build_id "
                f"AND b.id={table}.build_start_id)) OR (owner_kind='test_run' AND EXISTS("
                f"SELECT 1 FROM verification_run_identities b WHERE b.tenant_id={table}.tenant_id "
                f"AND b.product_id={table}.product_id AND b.project_id={table}.project_id "
                f"AND b.build_id={table}.build_id AND b.id={table}.test_run_id)))"
            )
        op.execute(
            f"CREATE POLICY category_read ON {table} FOR SELECT TO pdos_next_app USING (category_access(tenant_id,category_id,false) AND {parent})"
        )
    op.execute("""
CREATE FUNCTION build_actual_count(t uuid,c uuid,p uuid,b uuid) RETURNS bigint
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
BEGIN
 IF NOT category_access(t,c,false) OR NOT EXISTS(
   SELECT 1 FROM builds x JOIN products m ON m.id=x.product_id AND m.tenant_id=t
   WHERE x.tenant_id=t AND x.category_id=c AND x.product_id=p AND x.id=b
    AND source_object_audience(t,c,'products',m.id,m.owner_id,m.visibility)
    AND source_object_audience(t,c,'builds',x.id,x.owner_id,x.visibility)
    AND project_definition_visible(t,c,p,x.project_id)
 ) THEN RETURN NULL; END IF;
 RETURN (SELECT count(*) FROM actual_configurations x
         WHERE x.tenant_id=t AND x.category_id=c AND x.product_id=p AND x.build_id=b);
END $$;
REVOKE ALL ON FUNCTION build_actual_count(uuid,uuid,uuid,uuid) FROM PUBLIC,pdos_agent;
GRANT EXECUTE ON FUNCTION build_actual_count(uuid,uuid,uuid,uuid) TO pdos_next_app;
""")


def downgrade():
    op.execute("DROP FUNCTION build_actual_count(uuid,uuid,uuid,uuid)")
    # Restore the frozen original policies exactly, including their earlier insertion boundary.
    from migrations.schema_s0_0001 import SCHEMA_SQL

    for table in TABLES:
        op.execute(f"DROP POLICY category_insert ON {table}")
        op.execute(f"DROP POLICY category_read ON {table}")
        for statement in SCHEMA_SQL:
            if statement.startswith(f'CREATE POLICY category_scope ON "{table}" '):
                op.execute(statement)
