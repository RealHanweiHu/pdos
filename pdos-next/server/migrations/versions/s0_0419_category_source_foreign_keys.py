"""Model consumers bind category sources without accepting other models' evidence."""

from alembic import op

revision = "s0_0419"
down_revision = "s0_0418"
branch_labels = None
depends_on = None

CONSUMERS = ("claims", "definition_sources", "work_requests")
SCOPE_GUARD = """
CREATE FUNCTION public.assert_category_source_consumer() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM public.artifact_versions a
  WHERE a.tenant_id=NEW.tenant_id AND a.category_id=NEW.category_id
    AND a.id=NEW.artifact_id AND (a.product_id IS NULL OR a.product_id=NEW.product_id))
 THEN RAISE EXCEPTION 'source consumer scope mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$
"""


def upgrade():
    op.execute(SCOPE_GUARD)
    op.execute("REVOKE ALL ON FUNCTION public.assert_category_source_consumer() FROM PUBLIC")
    for table in CONSUMERS:
        op.drop_constraint(f"fk_{table}_22fb3d9d", table, type_="foreignkey")
        op.create_foreign_key(
            f"fk_{table}_category_artifact_id",
            table,
            "artifact_versions",
            ["tenant_id", "category_id", "artifact_id"],
            ["tenant_id", "category_id", "id"],
        )
        op.execute(
            f"CREATE TRIGGER category_source_consumer BEFORE INSERT OR UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION public.assert_category_source_consumer()"
        )


def downgrade():
    for table in reversed(CONSUMERS):
        op.execute(f"DROP TRIGGER category_source_consumer ON {table}")
        op.drop_constraint(f"fk_{table}_category_artifact_id", table, type_="foreignkey")
        op.create_foreign_key(
            f"fk_{table}_22fb3d9d",
            table,
            "artifact_versions",
            ["tenant_id", "product_id", "artifact_id"],
            ["tenant_id", "product_id", "id"],
        )
    op.execute("DROP FUNCTION public.assert_category_source_consumer()")
