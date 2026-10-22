"""Keep run execution terminal and reverted metadata irreversible."""

from alembic import op

from migrations.schema_s0_0712 import RUN_GUARD as OLD_RUN_GUARD
from migrations.schema_s0_0713 import OLD_SCOPE_FAILED, RUN_GUARD, SCOPE_FAILED

revision = "s0_0713"
down_revision = "s0_0712"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(RUN_GUARD)
    op.execute(SCOPE_FAILED)


def downgrade():
    op.execute(OLD_RUN_GUARD)
    op.execute(OLD_SCOPE_FAILED)
