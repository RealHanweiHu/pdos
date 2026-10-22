"""Category-root baseline after the approved one-time migration reset (P1)."""

from alembic import op

from migrations.schema_s0_0001 import FUNCTIONS, SCHEMA_SQL, TABLES

revision = "s0_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    for statement in SCHEMA_SQL:
        op.execute(statement)


def downgrade():
    for name in reversed(TABLES):
        op.execute(f'DROP TABLE IF EXISTS "{name}" CASCADE')
    for signature in FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {signature} CASCADE")
    for signature in (
        "scope_actor()",
        "scope_requester()",
        "category_access(uuid,uuid,boolean)",
        "category_bootstrap(uuid,uuid)",
        "category_owner(uuid,uuid)",
        "category_for_product(uuid)",
        "bind_model_category()",
        "bind_receipt_category()",
        "protect_category_binding()",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {signature} CASCADE")
