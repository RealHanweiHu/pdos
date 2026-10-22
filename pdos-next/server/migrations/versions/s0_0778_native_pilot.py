"""Native fixed Pilot creation and append-only original observations."""

from alembic import op
from sqlalchemy import text

from migrations.schema_s0_0778 import (
    DOWNGRADE_SQL,
    NATIVE_FUNCTIONS,
    PREVIOUS_FUNCTIONS,
    SCHEMA_SQL,
)

revision = "s0_0778"
down_revision = "s0_0777"
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


def require_functions(connection, expected):
    for signature, definition in expected.items():
        actual = connection.scalar(
            text("SELECT pg_get_functiondef(to_regprocedure(:signature))"),
            {"signature": f"public.{signature}"},
        )
        if actual != definition:
            raise RuntimeError(f"Pilot migration requires reviewed function: {signature}")


def upgrade():
    ordinary_owner()
    connection = op.get_bind()
    require_functions(connection, PREVIOUS_FUNCTIONS)
    for statement in SCHEMA_SQL:
        connection.exec_driver_sql(statement, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    connection = op.get_bind()
    require_functions(connection, NATIVE_FUNCTIONS)
    for statement in DOWNGRADE_SQL:
        connection.exec_driver_sql(statement, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")
