"""BOM designators, declared alternates and import provenance (D98, P113).

Assigned s0_0876 on s0_0875 at the 11-10 integration (placeholder s0_0900 from the W9
range s0_0900–s0_0904, written on top of s0_0869): file name, revision,
down_revision, the snapshot module name and the downgrade guard text moved together.
"""

from alembic import op

from migrations.schema_s0_0876 import DOWN_SQL, UP_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0876"
down_revision = "s0_0875"
branch_labels = depends_on = None


def _apply(statements):
    ordinary_owner()
    connection = op.get_bind()
    for statement in statements:
        connection.exec_driver_sql(statement, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")


def upgrade():
    _apply(UP_SQL)


def downgrade():
    _apply(DOWN_SQL)
