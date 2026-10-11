"""Bind a nullable-model scan to its actual category and protection epoch."""
from alembic import op
from migrations.schema_s0_0409 import SQL, OLD_SQL
revision = "s0_0409"
down_revision = "s0_0408"
branch_labels = None
depends_on = None

def upgrade():
    op.execute(SQL)

def downgrade():
    op.execute(OLD_SQL)
