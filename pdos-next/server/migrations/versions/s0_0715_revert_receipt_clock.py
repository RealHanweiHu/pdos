"""Bind reverted_at exactly to the actual Human receipt's saved timestamp."""

from alembic import op

from migrations.schema_s0_0715 import OLD_REVERT_GUARD, REVERT_GUARD

revision = "s0_0715"
down_revision = "s0_0714"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(REVERT_GUARD)


def downgrade():
    op.execute(OLD_REVERT_GUARD)
