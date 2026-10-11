"""Install the root-owned Receipt FK after M2 AgentRun tables exist."""

from alembic import op

revision = "s0_0714"
down_revision = "s0_0713"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_agent_runs_category_identity", "agent_runs", ["tenant_id", "category_id", "id"]
    )
    op.create_foreign_key(
        "fk_action_receipts_agent_run", "action_receipts", "agent_runs",
        ["tenant_id", "category_id", "agent_run_id"], ["tenant_id", "category_id", "id"],
    )


def downgrade():
    op.drop_constraint("fk_action_receipts_agent_run", "action_receipts", type_="foreignkey")
    op.drop_constraint("uq_agent_runs_category_identity", "agent_runs", type_="unique")
