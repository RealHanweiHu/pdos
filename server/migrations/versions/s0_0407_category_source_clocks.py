"""Root source changes retain actual category/reference fences without a model."""
from alembic import op
from migrations.schema_s0_0407 import UPGRADE_SQL, DOWNGRADE_SQL
revision = "s0_0407"
down_revision = "s0_0406"
branch_labels = None
depends_on = None

def upgrade():
    for statement in UPGRADE_SQL:
        op.execute(statement)

def downgrade():
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
