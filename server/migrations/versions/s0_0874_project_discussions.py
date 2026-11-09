"""Project discussions, object comments, follows and notifications (D37 ⑤; P34-2/3/7).

Placeholder revision in the D37 ⑤ range (s0_0873-s0_0877); renumber revision,
down_revision and the snapshot file to the real head at integration.
"""

from alembic import op

from migrations.schema_s0_0874 import DOWNGRADE_SQL, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0874"
down_revision = "s0_0873"
branch_labels = depends_on = None


def _execute(statements):
    for sql in statements:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})


def upgrade():
    ordinary_owner()
    _execute(SCHEMA_SQL)
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    _execute(DOWNGRADE_SQL)
    op.execute("SET LOCAL ROLE NONE")
