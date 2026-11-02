"""Allow private retrieval feedback to retain its real Change fixed-version origin."""

from alembic import op
from migrations.schema_s0_0851 import DOWNGRADE_SQL, SCHEMA_SQL
from migrations.versions.s0_0843_dingtalk import administrative_migrator

revision = "s0_0851"
down_revision = "s0_0850"
branch_labels = depends_on = None


def execute(statements):
    for statement in statements:
        op.get_bind().exec_driver_sql(statement, execution_options={"no_parameters": True})


def upgrade():
    administrative_migrator()
    op.execute("LOCK TABLE public.similar_history_feedback IN ACCESS EXCLUSIVE MODE")
    execute(SCHEMA_SQL)


def downgrade():
    administrative_migrator()
    execute(DOWNGRADE_SQL)
