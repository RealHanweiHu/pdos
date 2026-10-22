"""Permit the two release decisions' explicit nullable T2 deadline."""

from alembic import op
from sqlalchemy import text

from migrations.schema_s0_0782 import (
    APPLIED_DEFINITION,
    CONSTRAINT,
    PREVIOUS_DEFINITION,
    PREVIOUS_STATEMENT,
    REPLACEMENT_DEFINITION,
)
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0782"
down_revision = "s0_0781"
branch_labels = None
depends_on = None


def _replace(expected, replacement, *, preserve=False):
    ordinary_owner()
    connection = op.get_bind()
    connection.exec_driver_sql("LOCK TABLE public.confirmations IN ACCESS EXCLUSIVE MODE")
    if preserve and connection.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM public.confirmations WHERE expires_at IS NULL "
            "AND operation IN ('release.engineering.approve','release.manufacturing.approve'))"
        )
    ):
        raise RuntimeError("Preserve original release decision proof history; downgrade refused")
    actual = connection.scalar(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid='public.confirmations'::regclass AND conname=:name"
        ),
        {"name": CONSTRAINT},
    )
    if actual != expected:
        raise RuntimeError("Release deadline correction requires its exact reviewed predecessor")
    connection.exec_driver_sql(f"ALTER TABLE public.confirmations DROP CONSTRAINT {CONSTRAINT}")
    connection.exec_driver_sql(
        f"ALTER TABLE public.confirmations ADD CONSTRAINT {CONSTRAINT} {replacement}"
    )
    op.execute("SET LOCAL ROLE NONE")


def upgrade():
    _replace(PREVIOUS_DEFINITION, REPLACEMENT_DEFINITION)


def downgrade():
    _replace(APPLIED_DEFINITION, PREVIOUS_STATEMENT, preserve=True)
