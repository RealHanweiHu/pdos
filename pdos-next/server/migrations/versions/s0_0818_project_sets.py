"""Organization project sets and private project following."""

from alembic import op

from migrations.schema_s0_0818 import DOWNGRADE_SQL, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0818"
down_revision = "s0_0817"
branch_labels = None
depends_on = None


def upgrade():
    ordinary_owner()
    for sql in SCHEMA_SQL:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    for query in (
        "SELECT EXISTS(SELECT 1 FROM project_set_versions)",
        "SELECT EXISTS(SELECT 1 FROM inbox_states WHERE kind='project')",
    ):
        if op.get_bind().exec_driver_sql(query).scalar():
            raise RuntimeError(
                "Shared grouping or following history exists; preserve before downgrade"
            )
    for sql in DOWNGRADE_SQL:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")
