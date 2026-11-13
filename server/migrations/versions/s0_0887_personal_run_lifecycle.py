"""D274: personal Runs' pinned sources count in each source category's lifecycle graph.

Assigned s0_0887 on s0_0886 at the 11-11 integration (placeholder s0_0915 on head
s0_0869; revision, down_revision and the snapshot file name moved together).
"""

from alembic import op

from migrations.schema_s0_0887 import DOWN_SQL, PERSONAL_FUNCTIONS, PREVIOUS_FUNCTIONS, UP_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner, require_functions

revision = "s0_0887"
down_revision = "s0_0886"
branch_labels = depends_on = None


def _execute(statements):
    for sql in statements:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})


def upgrade():
    ordinary_owner()
    require_functions(op.get_bind(), PREVIOUS_FUNCTIONS)
    _execute(UP_SQL)
    require_functions(op.get_bind(), PERSONAL_FUNCTIONS)
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    require_functions(op.get_bind(), PERSONAL_FUNCTIONS)
    _execute(DOWN_SQL)
    require_functions(op.get_bind(), PREVIOUS_FUNCTIONS)
    op.execute("SET LOCAL ROLE NONE")
