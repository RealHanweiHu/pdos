"""Deterministic T0 quality facts, counts and spot-check sample (D117; P41-8, P42).

Assigned s0_0874 on s0_0873 at the 11-10 integration (AGENTS.md rule 3); placeholder
s0_0890 (allocated to W6 D37 ⑧ / W8 D117) on the branch, written on top of s0_0869.
"""

from alembic import op

from migrations.schema_s0_0874 import DOWN_SQL, UP_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0874"
down_revision = "s0_0873"
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
