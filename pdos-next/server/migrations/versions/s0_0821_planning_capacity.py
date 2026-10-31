"""Expose shared capacity without exposing hidden projects or reservation owners."""
from alembic import op
from migrations.schema_s0_0821 import SCHEMA_SQL, DOWNGRADE_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner
revision='s0_0821'
down_revision='s0_0820'
branch_labels=depends_on=None

def upgrade():
    ordinary_owner()
    for sql in SCHEMA_SQL: op.get_bind().exec_driver_sql(sql,execution_options={'no_parameters':True})
    op.execute('SET LOCAL ROLE NONE')

def downgrade():
    ordinary_owner()
    for sql in DOWNGRADE_SQL: op.get_bind().exec_driver_sql(sql)
    op.execute('SET LOCAL ROLE NONE')
