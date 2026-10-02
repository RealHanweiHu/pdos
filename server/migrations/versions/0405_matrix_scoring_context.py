"""Allow versioned matrix scoring context while retaining old read-only runs."""

from alembic import op
from sqlalchemy import text

revision = "0405_matrix_scoring_context"
down_revision = "0404_product_rfq_requirements"
branch_labels = None
depends_on = None

OLD = """NEW.run_context->'matrix_source'->>'projection_version'
    IS DISTINCT FROM 'product-matrix-context.v1'"""
NEW = """(NEW.run_context->'matrix_source'->>'projection_version'
    IN ('product-matrix-context.v1','product-matrix-context.v2')) IS NOT TRUE"""


def replace_guard(old: str, new: str) -> None:
    ddl = (
        op.get_bind()
        .execute(
            text("SELECT pg_get_functiondef('cehub_ai.guard_market_matrix_run()'::regprocedure)")
        )
        .scalar_one()
    )
    if ddl.count(old) != 1:
        raise ValueError("Unexpected matrix guard; retain existing scope and identity checks")
    op.execute(ddl.replace(old, new, 1))


def upgrade() -> None:
    replace_guard(OLD, NEW)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM cehub_ai.agent_runs
        WHERE run_context->'matrix_source'->>'projection_version'='product-matrix-context.v2')
      THEN RAISE EXCEPTION 'Retain matrix scoring context history'; END IF;
    END $$;""")
    replace_guard(NEW, OLD)
