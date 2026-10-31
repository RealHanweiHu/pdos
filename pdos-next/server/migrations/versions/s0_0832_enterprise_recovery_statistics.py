"""Tenant-bound metadata-only statistics repair, without business source privileges."""

from alembic import op
from sqlalchemy import text

from migrations.schema_s0_0832 import CREATE_ROLE, DOWNGRADE_SQL, SCHEMA_SQL, TRANSFER_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0832"
down_revision = "s0_0831"
branch_labels = depends_on = None


def upgrade():
    connection = op.get_bind()
    # A pre-existing cluster role can carry unreviewed grants or memberships.
    # Provisioning fails closed instead of silently inheriting those powers.
    if connection.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_enterprise_index_maintainer')"
        )
    ):
        raise RuntimeError(
            "Dedicated index maintainer role already exists; review it before migration"
        )
    connection.exec_driver_sql(CREATE_ROLE, execution_options={"no_parameters": True})
    ordinary_owner()
    for sql in SCHEMA_SQL:
        connection.exec_driver_sql(sql, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")
    for sql in TRANSFER_SQL:
        connection.exec_driver_sql(sql, execution_options={"no_parameters": True})


def downgrade():
    # The trusted migrator owns role administration. Runtime roles never become
    # members of this NOLOGIN role, even during an upgrade or downgrade.
    op.execute("DROP FUNCTION public.enterprise_index_statistics_repair()")
    ordinary_owner()
    for sql in DOWNGRADE_SQL:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")
    op.execute("DROP ROLE pdos_enterprise_index_maintainer")
