"""Do not silently omit private consumers from whole-run revert."""
from alembic import op
from migrations.schema_s0_0408 import SQL
revision = "s0_0408"
down_revision = "s0_0407"
branch_labels = None
depends_on = None

def upgrade():
    op.execute(SQL)
    op.execute("REVOKE ALL ON FUNCTION revert_subjects_consumed(uuid,uuid,jsonb,uuid[]) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION revert_subjects_consumed(uuid,uuid,jsonb,uuid[]) TO pdos_next_app")

def downgrade():
    op.execute("DROP FUNCTION revert_subjects_consumed(uuid,uuid,jsonb,uuid[])")
