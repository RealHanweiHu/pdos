"""Allow application constraint triggers to call their existing RLS validators."""

from alembic import op

revision = "s0_0412"
down_revision = "s0_0411"
branch_labels = None
depends_on = None

SIGNATURES = ("assert_test_run_atom(uuid,uuid)", "assert_test_result_atom(uuid,uuid)")


def upgrade():
    for signature in SIGNATURES:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO pdos_next_app")


def downgrade():
    for signature in SIGNATURES:
        op.execute(f"REVOKE EXECUTE ON FUNCTION {signature} FROM pdos_next_app")
