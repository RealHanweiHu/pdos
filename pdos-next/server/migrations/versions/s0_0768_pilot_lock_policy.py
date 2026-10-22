"""Allow the trusted owner function to hold a shared pilot-admission lock under FORCE RLS."""

from alembic import op

from migrations.versions.s0_0762_category_source_consumers import ordinary_owner

revision = "s0_0768"
down_revision = "s0_0767"
branch_labels = None
depends_on = None


def upgrade():
    ordinary_owner()
    op.execute("""CREATE POLICY pilot_owner_lock ON tenant_pilot_admissions FOR UPDATE
      TO pdos_next_owner USING(tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid)
      WITH CHECK(tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid)""")
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    op.execute("DROP POLICY pilot_owner_lock ON tenant_pilot_admissions")
    op.execute("SET LOCAL ROLE NONE")
