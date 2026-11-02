"""Register the new named skill qualification with the existing T2 proof deadline rule."""

from alembic import op
from sqlalchemy import text

from migrations.schema_s0_0717 import CONFIRMATION_DEADLINE
from migrations.versions.s0_0762_category_source_consumers import ordinary_owner

revision = "s0_0769"
down_revision = "s0_0768"
branch_labels = None
depends_on = None


def constraint(expression):
    op.execute("ALTER TABLE confirmations DROP CONSTRAINT ck_confirmations_decision_deadline")
    op.execute(
        "ALTER TABLE confirmations ADD CONSTRAINT ck_confirmations_decision_deadline "
        f"CHECK ({expression})"
    )


def upgrade():
    ordinary_owner()
    constraint(CONFIRMATION_DEADLINE.replace("operation IN (", "operation IN ('ai.skill.qualify',"))
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    if op.get_bind().scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM confirmations "
            "WHERE operation='ai.skill.qualify' AND expires_at IS NULL)"
        )
    ):
        raise RuntimeError("Preserve named qualification proofs; downgrade refused")
    ordinary_owner()
    constraint(CONFIRMATION_DEADLINE)
    op.execute("SET LOCAL ROLE NONE")
