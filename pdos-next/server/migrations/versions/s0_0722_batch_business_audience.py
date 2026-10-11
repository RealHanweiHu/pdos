"""Batch exact upstream audience rows and their complete source read sets."""

from alembic import op

from migrations.schema_s0_0722 import FUNCTION, PREVIOUS

revision = "s0_0722"
down_revision = "s0_0721"
branch_labels = None
depends_on = None


def upgrade():
    # Replacing the same signature retains the trusted ordinary owner and ACL.
    op.execute(FUNCTION)


def downgrade():
    op.execute(PREVIOUS)
