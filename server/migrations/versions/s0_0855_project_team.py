"""Project team (P34-1): tenant role catalog, named members, one lead per role."""

from alembic import op

from migrations.schema_s0_0855 import DOWNGRADE_SQL, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0855"
down_revision = "s0_0854"
branch_labels = None
depends_on = None


def _execute(statements):
    for sql in statements:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})


def upgrade():
    ordinary_owner()
    _execute(SCHEMA_SQL)
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    # Only migration backfill may be discarded; any team or catalog written since
    # is a named record that must be preserved before stepping back.
    if (
        op.get_bind()
        .exec_driver_sql(
            "SELECT EXISTS(SELECT 1 FROM project_team_changes WHERE source<>'backfill') "
            "OR EXISTS(SELECT 1 FROM project_role_catalog_versions)"
        )
        .scalar()
    ):
        raise RuntimeError("Project team history exists; preserve it before downgrade")
    _execute(DOWNGRADE_SQL)
    op.execute("SET LOCAL ROLE NONE")
