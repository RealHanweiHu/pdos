"""Bind a private conversation to its actually saved proposal."""
from alembic import op

from migrations.schema_s0_0823 import DOWNGRADE_GUARD_SQL, DOWNGRADE_SQL, GUARD_SQL, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0823"
down_revision = "s0_0822"
branch_labels = depends_on = None


def upgrade():
    ordinary_owner()
    for sql in SCHEMA_SQL:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE postgres")
    for sql in GUARD_SQL:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    op.execute("SET LOCAL ROLE postgres")
    for sql in DOWNGRADE_GUARD_SQL:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})
    ordinary_owner()
    for sql in DOWNGRADE_SQL:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")
