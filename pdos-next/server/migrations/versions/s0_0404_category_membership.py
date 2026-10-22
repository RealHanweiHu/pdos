"""Optional member expiry, explicit manager capability, and null-safe scoped intent."""

from alembic import op

from migrations.schema_s0_0404 import GRANT_FUNCTIONS, OLD_INTENT_CONSTRAINTS

revision = "s0_0404"
down_revision = "s0_0403"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE grants ALTER COLUMN expires_at DROP NOT NULL")
    op.execute("ALTER TABLE grants ADD COLUMN product_manager BOOLEAN NOT NULL DEFAULT false")
    for _, _, statement in GRANT_FUNCTIONS:
        op.execute(statement)
    for table, constraint in OLD_INTENT_CONSTRAINTS.items():
        op.drop_constraint(constraint, table, type_="unique")
    op.execute(
        "ALTER TABLE action_receipts ADD CONSTRAINT uq_action_receipts_scope_intent "
        "UNIQUE NULLS NOT DISTINCT (tenant_id,category_id,product_id,intent_digest)"
    )
    op.execute(
        "ALTER TABLE lifecycle_intents ADD CONSTRAINT uq_lifecycle_intents_scope_intent "
        "UNIQUE (tenant_id,category_id,object_id,intent_digest)"
    )


def downgrade():
    op.drop_constraint("uq_lifecycle_intents_scope_intent", "lifecycle_intents", type_="unique")
    op.drop_constraint("uq_action_receipts_scope_intent", "action_receipts", type_="unique")
    for table, constraint in OLD_INTENT_CONSTRAINTS.items():
        op.create_unique_constraint(constraint, table, ["tenant_id", "product_id", "intent_digest"])
    for _, statement, _ in GRANT_FUNCTIONS:
        op.execute(statement)
    # Schema reversal on an isolated empty checkpoint only; never invent member deadlines.
    op.execute("ALTER TABLE grants DROP COLUMN product_manager")
    op.execute("ALTER TABLE grants ALTER COLUMN expires_at SET NOT NULL")
