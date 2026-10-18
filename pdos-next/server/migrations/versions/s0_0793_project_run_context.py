"""Immutable explicit project context for conversation and relative-service Runs."""

from alembic import op

from migrations.schema_s0_0793 import DOWNGRADE_SQL, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0793"
down_revision = "s0_0792"
branch_labels = None
depends_on = None


def _apply(statements):
    ordinary_owner()
    for statement in statements:
        op.get_bind().exec_driver_sql(statement, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")


def upgrade():
    _apply(SCHEMA_SQL)


def downgrade():
    # Nullable history is not inferred. Refuse to discard an actual binding.
    if op.get_bind().exec_driver_sql(
        "SELECT EXISTS(SELECT 1 FROM agent_runs WHERE project_id IS NOT NULL) "
        "OR EXISTS(SELECT 1 FROM agent_sessions WHERE project_id IS NOT NULL)"
    ).scalar():
        raise RuntimeError("Project-bound Runs exist; downgrade would discard their scope")
    _apply(DOWNGRADE_SQL)
