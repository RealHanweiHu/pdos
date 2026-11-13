"""Quality holds, spot checks and evaluation sets for pilot T0 (P41-8, P42, P109–P110).

Assigned s0_0875 on s0_0874 at the 11-10 integration (AGENTS.md rule 3); placeholder
s0_0891 (allocated to W6 D37 ⑧ / W8 D117) on top of s0_0890 on the branch.
"""

from alembic import op
from sqlalchemy import text

from migrations.schema_s0_0875 import DOWN_SQL, UP_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0875"
down_revision = "s0_0874"
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
    if op.get_bind().scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM agent_skill_spot_checks UNION ALL "
            "SELECT 1 FROM agent_skill_quality_holds UNION ALL SELECT 1 FROM agent_skill_eval_sets)"
        )
    ):
        raise RuntimeError(
            "Preserve spot checks, quality holds and evaluation sets; destructive downgrade refused"
        )
    _apply(DOWN_SQL)
