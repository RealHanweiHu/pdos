"""Typed category/proposal confirmations and the shared Agent receipt binding."""

from alembic import op

revision = "s0_0405"
down_revision = "s0_0404"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE action_receipts ADD COLUMN agent_run_id UUID")
    op.execute(
        "ALTER TABLE action_receipts ADD CONSTRAINT receipt_one_run_identity "
        "CHECK (run_id IS NULL OR agent_run_id IS NULL)"
    )
    op.execute(
        "ALTER TABLE confirmations ADD COLUMN subject_type VARCHAR(32) NOT NULL DEFAULT 'product'"
    )
    # The exact AgentRun FK is installed by the M2 migration after its table exists.


def downgrade():
    op.execute("ALTER TABLE action_receipts DROP CONSTRAINT IF EXISTS fk_action_receipts_agent_run")
    op.execute("ALTER TABLE action_receipts DROP CONSTRAINT receipt_one_run_identity")
    op.execute("ALTER TABLE action_receipts DROP COLUMN agent_run_id")
    op.execute("ALTER TABLE confirmations DROP COLUMN subject_type")
