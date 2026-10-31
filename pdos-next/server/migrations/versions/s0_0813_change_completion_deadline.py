"""Allow the two registered named Change decisions to retain unbounded proofs."""

from alembic import op

from migrations.schema_s0_0813 import OLD_CHECK
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0813"
down_revision = "s0_0812"
branch_labels = None
depends_on = None

ADDED = ("change.verification.record", "change.close")
NAME = "ck_confirmations_decision_deadline"


def _expression():
    return op.get_bind().exec_driver_sql(
        "SELECT pg_get_expr(conbin,conrelid) FROM pg_constraint "
        "WHERE conrelid='public.confirmations'::regclass "
        f"AND conname='{NAME}'"
    ).scalar_one()


def _replace(expression):
    op.execute(f"ALTER TABLE public.confirmations DROP CONSTRAINT {NAME}")
    op.execute(f"ALTER TABLE public.confirmations ADD CONSTRAINT {NAME} CHECK ({expression})")


def upgrade():
    ordinary_owner()
    previous = _expression()
    if previous != OLD_CHECK:
        raise RuntimeError("Inspect the existing named-decision constraint before upgrading")
    _replace(f"({previous}) OR operation IN ('change.verification.record','change.close')")
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    if op.get_bind().exec_driver_sql(
        "SELECT EXISTS(SELECT 1 FROM public.confirmations WHERE expires_at IS NULL "
        "AND operation IN ('change.verification.record','change.close'))"
    ).scalar_one():
        raise RuntimeError("Named Change proof history exists; preserve it instead of downgrading")
    _replace(OLD_CHECK)
    op.execute("SET LOCAL ROLE NONE")
