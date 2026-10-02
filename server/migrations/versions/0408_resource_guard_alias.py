"""Disambiguate legacy occupancy aliases from the trigger OLD record."""

from alembic import op
from sqlalchemy import text

revision = "0408_resource_guard_alias"
down_revision = "0407_product_shadow_evaluation"
branch_labels = None
depends_on = None


def rewrite_guard(*, forward: bool) -> None:
    definition = (
        op.get_bind()
        .execute(
            text(
                "SELECT pg_get_functiondef("
                "'cehub_project.guard_resource_reservation()'::regprocedure)"
            )
        )
        .scalar_one()
    )
    source, target = ("old", "legacy_occupancy") if forward else ("legacy_occupancy", "old")
    alias = f"current_legacy_resource_allocations {source}"
    if definition.count(alias) != 2 or f"{source}.start" not in definition:
        raise RuntimeError("Expected resource reservation occupancy guard is unavailable")
    op.execute(
        definition.replace(alias, f"current_legacy_resource_allocations {target}")
        .replace(f"{source}.", f"{target}.")
    )


def upgrade() -> None:
    rewrite_guard(forward=True)


def downgrade() -> None:
    rewrite_guard(forward=False)
