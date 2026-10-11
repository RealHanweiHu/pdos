"""Category retention bookkeeping does not require an invented Product clock."""
from alembic import op

from migrations.schema_s0_0410 import OLD_SQL, SQL

revision = "s0_0410"
down_revision = "s0_0409"
branch_labels = None
depends_on = None

def upgrade():
    op.execute(SQL)

def downgrade():
    op.execute(OLD_SQL)
