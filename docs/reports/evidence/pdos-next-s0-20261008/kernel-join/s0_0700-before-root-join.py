"""小Pai run metadata, provider agreements, skills, MCP and public snapshots."""

from alembic import op

from migrations.schema_s0_0700 import SQL, TABLES

revision = "s0_0700"
down_revision = "s0_0011"
branch_labels = ("m2",)
depends_on = None


def upgrade():
    for statement in SQL:
        op.execute(statement)


def downgrade():
    for table in reversed(TABLES):
        op.execute(f'DROP TABLE "{table}" CASCADE')
    for function in (
        "kernel_identity_guard",
        "kernel_run_guard",
        "kernel_session_guard",
        "kernel_call_guard",
        "kernel_snapshot_guard",
        "kernel_append_only",
    ):
        op.execute(f"DROP FUNCTION {function}()")
