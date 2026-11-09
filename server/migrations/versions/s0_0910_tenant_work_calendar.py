"""Tenant working calendars and the working-day SQL twin (D221).

Placeholder s0_0910 in W11's assigned range s0_0910–s0_0914, on head s0_0869;
renumbered to the real head at integration (不可协商项 3).
"""

from alembic import op

from migrations.schema_s0_0910 import DOWNGRADE_SQL, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0910"
down_revision = "s0_0869"
branch_labels = depends_on = None


def upgrade():
    ordinary_owner()
    for sql in SCHEMA_SQL:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    for sql in DOWNGRADE_SQL:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")
