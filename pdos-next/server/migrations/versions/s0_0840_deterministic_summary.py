"""Deterministic personal summaries retain native T1 service authority without model wallets.

ROOT: assign the next actual monotonic revision and its actual current head;
place this wrapper in migrations/versions/ under that assigned name.
"""

from alembic import op
from migrations.schema_summary_walletless import DOWNGRADE_SQL, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0840"
down_revision = "s0_0839"
branch_labels = depends_on = None


def upgrade():
    ordinary_owner()
    for sql in SCHEMA_SQL:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    for sql in DOWNGRADE_SQL:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")
