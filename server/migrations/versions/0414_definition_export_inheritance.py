"""Compare retained definition exports with the actual expanded inherited content."""

from alembic import op
from sqlalchemy import text

revision = "0414_definition_export_inheritance"
down_revision = "0413_conversation_matrix_runs"
branch_labels = None
depends_on = None

FUNCTION = "cehub_product.guard_definition_export()"
OLD_CONTENT = "NEW.snapshot->'definition'->'content' IS DISTINCT FROM d.content"
NEW_CONTENT = (
    "NEW.snapshot->'definition'->'content' IS DISTINCT FROM "
    "cehub_product.resolve_definition_content(d.tenant_id,d.base_definition_id,d.content)"
)


def rewrite(*, forward: bool) -> None:
    definition = str(
        op.get_bind()
        .execute(text("SELECT pg_get_functiondef(CAST(:name AS regprocedure))"), {"name": FUNCTION})
        .scalar_one()
    )
    source, target = (OLD_CONTENT, NEW_CONTENT) if forward else (NEW_CONTENT, OLD_CONTENT)
    if definition.count(source) != 1 or target in definition:
        raise RuntimeError("Expected definition export content guard is unavailable")
    # Rewrite only the content comparison. The selected row supplies every resolver
    # argument; CREATE OR REPLACE retains the function owner, ACL and other guards.
    op.execute(definition.replace(source, target))


def upgrade() -> None:
    rewrite(forward=True)


def downgrade() -> None:
    rewrite(forward=False)
