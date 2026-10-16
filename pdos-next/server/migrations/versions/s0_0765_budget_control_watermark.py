"""Index the owner budget control version and current wallets without rescanning history."""

from alembic import op

from migrations.versions.s0_0762_category_source_consumers import ordinary_owner

revision = "s0_0765"
down_revision = "s0_0764"
branch_labels = None
depends_on = None


def upgrade():
    ordinary_owner()
    op.execute("""CREATE INDEX ix_agent_budget_control_revision
        ON agent_validation_budgets(tenant_id,requester_id,revision)""")
    op.execute("""CREATE INDEX ix_agent_budget_active
        ON agent_validation_budgets(tenant_id,requester_id,id) WHERE active IS TRUE""")
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    op.execute("DROP INDEX ix_agent_budget_active")
    op.execute("DROP INDEX ix_agent_budget_control_revision")
    op.execute("SET LOCAL ROLE NONE")
