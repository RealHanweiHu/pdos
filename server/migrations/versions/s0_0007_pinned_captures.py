"""Pinned source captures use versions, not a uniform material deadline."""

from alembic import op

revision = "s0_0007"
down_revision = "s0_0006"
branch_labels = None
depends_on = None

TABLES = ("supply_source_captures", "cost_source_captures")


def upgrade():
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {table}_check1")
        op.execute(f"ALTER TABLE {table} DROP COLUMN expires_at")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {table}_check1 "
            "CHECK (revision=1 AND status='unapplied')"
        )


def downgrade():
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {table}_check1")
        # The retired material deadline has no business meaning in this chain.
        # Recreate it for schema reversal without modifying immutable captures.
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN expires_at timestamptz "
            "NOT NULL DEFAULT 'infinity'::timestamptz"
        )
        op.execute(f"ALTER TABLE {table} ALTER COLUMN expires_at DROP DEFAULT")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {table}_check1 "
            "CHECK (revision=1 AND status='unapplied' AND expires_at>created_at)"
        )
