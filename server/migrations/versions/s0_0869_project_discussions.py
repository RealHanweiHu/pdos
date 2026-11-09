"""Project discussions, object comments, follows and notifications (D37 ⑤; P34-2/3/7).

Written as placeholder s0_0874; renumbered to s0_0869 after s0_0868 at the 11-09
integration (revision, down_revision and snapshot file together).
"""

from alembic import op

from migrations.schema_s0_0869 import DOWNGRADE_SQL, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0869"
down_revision = "s0_0868"
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
