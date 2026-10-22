"""Opaque current admin authorization locks actual fact without granting DML."""

from alembic import op

revision = "s0_0702"
down_revision = "s0_0701"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE FUNCTION kernel_admin_authorized() RETURNS boolean LANGUAGE plpgsql
      SECURITY DEFINER SET search_path=public,pg_temp AS $$ DECLARE permitted uuid; BEGIN
      IF scope_actor() IS DISTINCT FROM scope_requester() THEN RETURN false; END IF;
      SELECT a.id INTO permitted FROM tenant_administrators a
      JOIN principals p ON p.tenant_id=a.tenant_id AND p.id=a.principal_id
      WHERE a.tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
      AND a.principal_id=scope_actor() AND a.active AND p.active AND p.kind='human'
      FOR SHARE OF a,p;
      RETURN permitted IS NOT NULL; END $$""")
    op.execute("REVOKE ALL ON FUNCTION kernel_admin_authorized() FROM PUBLIC,pdos_agent")
    op.execute("GRANT EXECUTE ON FUNCTION kernel_admin_authorized() TO pdos_next_app")


def downgrade():
    op.execute("DROP FUNCTION kernel_admin_authorized()")
