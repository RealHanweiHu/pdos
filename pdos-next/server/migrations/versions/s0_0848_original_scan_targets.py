"""Cache possible original IDs in rebuildable search metadata, never scan authority."""

from alembic import op
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0848"
down_revision = "s0_0847"
branch_labels = depends_on = None


def upgrade():
    ordinary_owner()
    op.execute("ALTER TABLE public.enterprise_search_sources ADD COLUMN original_ids uuid[]")
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    op.execute("ALTER TABLE public.enterprise_search_sources DROP COLUMN original_ids")
    op.execute("SET LOCAL ROLE NONE")
