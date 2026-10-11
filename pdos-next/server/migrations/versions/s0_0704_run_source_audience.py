"""Run bodies and events retain actual model and direct-source read audiences."""

from alembic import op

revision = "s0_0704"
down_revision = "s0_0703"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE agent_runs ADD COLUMN read_sources jsonb NOT NULL DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE agent_runs ALTER COLUMN read_sources DROP DEFAULT")
    op.execute("""CREATE FUNCTION kernel_read_set_visible(t uuid,c uuid,refs jsonb)
      RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
      SELECT jsonb_typeof(refs)='array' AND NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(refs) r WHERE
        NOT COALESCE(direct_source_set_visible(t,c,(r->>'product_id')::uuid,
          jsonb_build_array(r)),false)) $$""")
    op.execute("REVOKE ALL ON FUNCTION kernel_read_set_visible(uuid,uuid,jsonb) FROM PUBLIC,pdos_agent")
    op.execute("GRANT EXECUTE ON FUNCTION kernel_read_set_visible(uuid,uuid,jsonb) TO pdos_next_app")
    for table in ("agent_sessions", "agent_runs"):
        op.execute(f"""CREATE POLICY kernel_model_audience ON {table} AS RESTRICTIVE
          USING(product_id IS NULL OR EXISTS(SELECT 1 FROM products p
            WHERE p.tenant_id={table}.tenant_id AND p.category_id={table}.category_id
            AND p.id={table}.product_id))""")
    op.execute("""CREATE POLICY kernel_source_audience ON agent_runs AS RESTRICTIVE
      FOR SELECT USING(kernel_read_set_visible(tenant_id,category_id,read_sources))""")
    op.execute("""CREATE FUNCTION kernel_read_set_guard() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN IF NEW.read_sources IS DISTINCT FROM OLD.read_sources THEN
      RAISE EXCEPTION 'Run source binding immutable'; END IF; RETURN NEW; END $$""")
    op.execute("REVOKE ALL ON FUNCTION kernel_read_set_guard() FROM PUBLIC,pdos_agent")
    op.execute("""CREATE TRIGGER kernel_read_set BEFORE UPDATE ON agent_runs
      FOR EACH ROW EXECUTE FUNCTION kernel_read_set_guard()""")


def downgrade():
    op.execute("DROP TRIGGER kernel_read_set ON agent_runs")
    op.execute("DROP FUNCTION kernel_read_set_guard()")
    op.execute("DROP POLICY kernel_source_audience ON agent_runs")
    for table in ("agent_sessions", "agent_runs"):
        op.execute(f"DROP POLICY kernel_model_audience ON {table}")
    op.execute("DROP FUNCTION kernel_read_set_visible(uuid,uuid,jsonb)")
    op.execute("ALTER TABLE agent_runs DROP COLUMN read_sources")
