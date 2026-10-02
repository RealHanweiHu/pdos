"""Disambiguate JSON extraction before removing the disposition timestamp."""

from alembic import op
from sqlalchemy import text

revision = "0406_matrix_outcome_guard"
down_revision = "0405_matrix_scoring_context"
branch_labels = None
depends_on = None

OLD = "(NEW.source_snapshot->'disposition' - 'created_at')"
NEW = "((NEW.source_snapshot->'disposition') - 'created_at')"


def replace_guard(old: str, new: str) -> None:
    ddl = (
        op.get_bind()
        .execute(
            text("SELECT pg_get_functiondef('cehub_product.guard_matrix_outcome()'::regprocedure)")
        )
        .scalar_one()
    )
    if ddl.count(old) != 1:
        raise ValueError("Unexpected matrix outcome guard; preserve original provenance checks")
    op.execute(ddl.replace(old, new, 1))


def upgrade() -> None:
    replace_guard(OLD, NEW)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM cehub_product.product_matrix_outcomes)
      THEN RAISE EXCEPTION 'Retain usable matrix outcome history'; END IF;
    END $$;""")
    replace_guard(NEW, OLD)
