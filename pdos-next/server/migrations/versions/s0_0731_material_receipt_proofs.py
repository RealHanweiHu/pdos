"""Bind material content and single-use confirmations to their actual receipts."""

from alembic import op
from sqlalchemy import text

from migrations.schema_s0_0731 import DOWNGRADE_SQL, SCHEMA_SQL

revision = "s0_0731"
down_revision = "s0_0730"
branch_labels = None
depends_on = None


def ordinary_owner():
    connection = op.get_bind()
    role = connection.execute(
        text(
            "SELECT rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolcanlogin FROM pg_roles "
            "WHERE rolname='pdos_next_owner'"
        )
    ).one_or_none()
    if role is None or any(role):
        raise RuntimeError("Pre-provisioned ordinary pdos_next_owner is required")
    if connection.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname IN "
            "('pdos_next_app','pdos_next_auth','pdos_next_dispatch','pdos_agent') "
            "AND pg_has_role(rolname,'pdos_next_owner','MEMBER'))"
        )
    ):
        raise RuntimeError("Runtime roles must not inherit the schema owner")
    op.execute("SET LOCAL ROLE pdos_next_owner")


def upgrade():
    ordinary_owner()
    for statement in SCHEMA_SQL:
        op.execute(statement)
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    connection = op.get_bind()
    op.execute("LOCK TABLE action_receipts, confirmations IN ACCESS EXCLUSIVE MODE")
    if connection.scalar(
        text("SELECT EXISTS(SELECT 1 FROM action_receipts WHERE confirmation_id IS NOT NULL)")
    ):
        raise RuntimeError(
            "Material proof downgrade refuses persisted confirmation links; "
            "preserve receipt metadata"
        )
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
    op.execute("SET LOCAL ROLE NONE")
