"""Keep the business version reviewed while preparing each agenda item."""

import sqlalchemy as sa
from alembic import op

revision = "0167_meeting_preparation"
down_revision = "0166_knowledge_classification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meeting_agenda_items", sa.Column("source_digest", sa.String(64)), schema="cehub_project"
    )
    op.create_check_constraint(
        op.f("ck_meeting_agenda_items_source_digest_consistent"),
        "meeting_agenda_items",
        "source_digest IS NULL OR (source_kind IS NOT NULL AND source_digest ~ '^[0-9a-f]{64}$')",
        schema="cehub_project",
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM "
                "cehub_project.meeting_agenda_items WHERE source_digest IS NOT NULL)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard meeting source review versions")
    op.drop_constraint(
        op.f("ck_meeting_agenda_items_source_digest_consistent"),
        "meeting_agenda_items",
        schema="cehub_project",
    )
    op.drop_column("meeting_agenda_items", "source_digest", schema="cehub_project")
