"""Delivery acknowledgement is transport state, never a new original reference."""

from alembic import op

revision = "next_0012"
down_revision = "next_0011"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DROP TRIGGER lifecycle_reference ON inbox_deliveries")


def downgrade():
    op.execute(
        "CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE "
        "ON inbox_deliveries FOR EACH ROW EXECUTE FUNCTION lifecycle_reference_gate()"
    )
