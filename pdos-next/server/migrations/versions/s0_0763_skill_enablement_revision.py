"""Version tenant skill toggles without changing any recorded T0 qualifications."""

from alembic import op

from migrations.versions.s0_0762_category_source_consumers import ordinary_owner

revision = "s0_0763"
down_revision = "s0_0762"
branch_labels = None
depends_on = None


def upgrade():
    ordinary_owner()
    op.execute(
        "ALTER TABLE tenant_skill_enablements ADD COLUMN revision integer NOT NULL DEFAULT 0"
    )
    op.execute("ALTER TABLE tenant_skill_enablements ADD COLUMN receipt_id uuid")
    op.execute("""ALTER TABLE tenant_skill_enablements ADD CONSTRAINT skill_enablement_receipt_fk
        FOREIGN KEY (tenant_id,receipt_id) REFERENCES action_receipts(tenant_id,id)
        DEFERRABLE INITIALLY DEFERRED""")
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    op.execute("ALTER TABLE tenant_skill_enablements DROP CONSTRAINT skill_enablement_receipt_fk")
    op.execute("ALTER TABLE tenant_skill_enablements DROP COLUMN receipt_id")
    op.execute("ALTER TABLE tenant_skill_enablements DROP COLUMN revision")
    op.execute("SET LOCAL ROLE NONE")
