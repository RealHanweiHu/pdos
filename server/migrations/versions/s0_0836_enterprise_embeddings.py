"""Independent embedding profile T1 and recoverable derived projection."""

from alembic import op

from migrations.schema_s0_0836 import (
    DOWNGRADE_SQL,
    EMPTY_HISTORY_SQL,
    EXTENSION_SQL,
    RESTORE_SQL,
    SCHEMA_SQL,
    TRANSFER_SQL,
)
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0836"
down_revision = "s0_0835"
branch_labels = depends_on = None


def execute(statements):
    for sql in statements:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})


def upgrade():
    # Installing the extension requires the existing migration identity. All
    # application tables/policies/triggers remain owned by the ordinary owner.
    execute(EXTENSION_SQL)
    ordinary_owner()
    execute(SCHEMA_SQL)
    op.execute("SET LOCAL ROLE NONE")
    execute(TRANSFER_SQL)


def downgrade():
    # No tenant scope is set during migrations. Inspect retained accounting
    # before switching to the forced-RLS owner, which cannot see all tenants.
    execute(EMPTY_HISTORY_SQL)
    execute(RESTORE_SQL)
    ordinary_owner()
    execute(DOWNGRADE_SQL)
    op.execute("SET LOCAL ROLE NONE")
