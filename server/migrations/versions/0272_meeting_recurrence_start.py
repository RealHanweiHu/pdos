"""Fix recurrence phase to an explicit local start date; retain legacy meetings."""

import sqlalchemy as sa
from alembic import op

revision = "0272_meeting_recurrence_start"
down_revision = "0271_id_handoff_receiver"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy rows use their local creation date until explicitly replaced.
    op.add_column("meeting_recurrences", sa.Column("start_date", sa.Date()), schema="cehub_project")


def downgrade() -> None:
    op.drop_column("meeting_recurrences", "start_date", schema="cehub_project")
