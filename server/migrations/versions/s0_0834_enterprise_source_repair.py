"""Tenant-bound derived-source cleanup after an ordinary authorized source read."""

from alembic import op

from migrations.schema_s0_0834 import DOWNGRADE_SQL, SCHEMA_SQL, SIGNATURE, TRANSFER_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0834"
down_revision = "s0_0833"
branch_labels = depends_on = None


def upgrade():
    ordinary_owner()
    connection = op.get_bind()
    for sql in SCHEMA_SQL:
        connection.exec_driver_sql(sql, execution_options={"no_parameters": True})
    # Only the migration identity can change function ownership. Runtime roles
    # remain non-members of the dedicated NOLOGIN derived-maintenance role.
    op.execute("SET LOCAL ROLE NONE")
    for sql in TRANSFER_SQL:
        connection.exec_driver_sql(sql, execution_options={"no_parameters": True})


def downgrade():
    op.execute(f"DROP FUNCTION {SIGNATURE}")
    ordinary_owner()
    for sql in DOWNGRADE_SQL:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")
