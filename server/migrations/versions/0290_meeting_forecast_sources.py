"""Allow meeting agendas to retain immutable schedule forecast references."""

import sqlalchemy as sa
from alembic import op

revision = "0290_meeting_forecast_sources"
down_revision = "0289_template_generation_v9"
branch_labels = None
depends_on = None

KINDS = (
    "'task', 'issue', 'risk', 'decision', 'gate', "
    "'requirement', 'change_request', 'finding', 'test_run'"
)


def _constraint(kinds: str) -> None:
    op.drop_constraint(
        op.f("ck_meeting_agenda_items_source_kind_allowed"),
        "meeting_agenda_items",
        schema="cehub_project",
    )
    op.create_check_constraint(
        op.f("ck_meeting_agenda_items_source_kind_allowed"),
        "meeting_agenda_items",
        f"source_kind IN ({kinds}) OR source_kind IS NULL",
        schema="cehub_project",
    )


def upgrade() -> None:
    _constraint(KINDS + ", 'forecast'")


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_project.meeting_agenda_items "
                "WHERE source_kind='forecast')"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard meeting forecast references")
    _constraint(KINDS)
