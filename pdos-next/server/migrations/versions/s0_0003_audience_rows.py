"""Protect audience assignments themselves from leaking private object identifiers."""

from alembic import op

revision = "s0_0003"
down_revision = "s0_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE POLICY audience_assignment ON object_audiences AS RESTRICTIVE "
        "USING (owner_id=scope_requester() OR principal_id=scope_requester()) "
        "WITH CHECK (owner_id=scope_requester())"
    )


def downgrade():
    op.execute("DROP POLICY audience_assignment ON object_audiences")
