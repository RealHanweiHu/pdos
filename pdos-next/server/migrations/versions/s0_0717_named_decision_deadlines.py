"""B7 named T2 decisions do not require a confirmation time window."""

import hashlib

from alembic import op
from sqlalchemy import text

from migrations.schema_s0_0717 import CONFIRMATION_DEADLINE, CONSTRAINTS, FUNCTIONS

revision = "s0_0717"
down_revision = "s0_0716"
branch_labels = None
depends_on = None

NULLABLE = (
    ("confirmations", "expires_at"),
    ("change_approval_records", "proof_expires_at"),
    ("controlled_change_selection_facts", "proof_expires_at"),
)


def functions(reverse=False):
    for name, old_hash, new_hash, before, after in FUNCTIONS:
        actual = (
            op.get_bind()
            .execute(
                text(
                    "SELECT pg_get_functiondef(p.oid) FROM pg_proc p "
                    "JOIN pg_namespace n ON p.pronamespace=n.oid "
                    "WHERE n.nspname='public' AND p.proname=:name"
                ),
                {"name": name},
            )
            .scalar_one()
        )
        expected = new_hash if reverse else old_hash
        if hashlib.sha256(actual.encode()).hexdigest() != expected:
            raise RuntimeError(f"Unreviewed B7 shared proof function {name}")
        op.execute(before if reverse else after)


def constraints(reverse=False):
    for table, name, before, after in CONSTRAINTS:
        if not reverse:
            actual = (
                op.get_bind()
                .execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conrelid=to_regclass(:table) AND conname=:name"
                    ),
                    {"table": table, "name": name},
                )
                .scalar_one()
            )
            if actual != before:
                raise RuntimeError(f"Unreviewed B7 proof constraint {table}.{name}")
        op.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT "{name}"')
        op.execute(f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" {before if reverse else after}')


def upgrade():
    for table, column in NULLABLE:
        op.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" DROP NOT NULL')
    op.execute(
        "ALTER TABLE confirmations ADD CONSTRAINT ck_confirmations_decision_deadline "
        f"CHECK ({CONFIRMATION_DEADLINE})"
    )
    constraints()
    functions()


def downgrade():
    # Retained named decisions cannot be given invented deadlines or removed.
    for table, column in NULLABLE:
        if (
            op.get_bind()
            .execute(text(f'SELECT EXISTS(SELECT 1 FROM "{table}" WHERE "{column}" IS NULL)'))
            .scalar_one()
        ):
            raise RuntimeError("Retained T2 decisions without deadlines prevent downgrade")
    functions(reverse=True)
    constraints(reverse=True)
    op.execute("ALTER TABLE confirmations DROP CONSTRAINT ck_confirmations_decision_deadline")
    for table, column in NULLABLE:
        op.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" SET NOT NULL')
