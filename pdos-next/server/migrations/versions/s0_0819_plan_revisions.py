"""Plan alternatives, explicit predecessor and immutable successive applications."""
from alembic import op
from migrations.schema_s0_0819 import SCHEMA_SQL, DOWNGRADE_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner
revision = "s0_0819"
down_revision = "s0_0818"
branch_labels = depends_on = None

def upgrade():
    ordinary_owner()
    for sql in SCHEMA_SQL:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")

def downgrade():
    ordinary_owner()
    if op.get_bind().exec_driver_sql("SELECT EXISTS(SELECT 1 FROM plan_proposals WHERE base_plan_id IS NOT NULL OR resource_demands<>'[]'::jsonb)").scalar():
        raise RuntimeError("Preserve plan revision and resource demand history before downgrade")
    for sql in DOWNGRADE_SQL:
        op.get_bind().exec_driver_sql(sql)
    op.execute("SET LOCAL ROLE NONE")
