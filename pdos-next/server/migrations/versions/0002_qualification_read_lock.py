"""Lock trusted eligibility without granting application qualification write access."""

from alembic import op

revision = "next_0002"
down_revision = "next_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
      CREATE FUNCTION public.lock_qualification(qualification_id uuid)
      RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
      SET search_path = pg_catalog, public AS $$
      BEGIN
        PERFORM 1 FROM public.qualifications
          WHERE id = qualification_id
            AND tenant_id = nullif(current_setting('pdos.tenant_id', true), '')::uuid
          FOR SHARE;
        RETURN FOUND;
      END $$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.lock_qualification(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.lock_qualification(uuid) TO pdos_next_app")


def downgrade():
    op.execute("DROP FUNCTION public.lock_qualification(uuid)")
