"""Member-only conversations and private read/archive/follow state."""

from alembic import op

from migrations.schema_s0_0817 import DOWNGRADE_SQL, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0817"
down_revision = "s0_0816"
branch_labels = None
depends_on = None


def upgrade():
    ordinary_owner()
    for sql in SCHEMA_SQL:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    for table in ("inbox_states", "inbox_messages", "inbox_conversations"):
        if op.get_bind().exec_driver_sql(f"SELECT EXISTS(SELECT 1 FROM public.{table})").scalar():
            raise RuntimeError("Inbox history exists; downgrade would discard it")
    for sql in DOWNGRADE_SQL:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")
