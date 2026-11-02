"""Pin critical-review time and repair the deferred receipt operation predicate."""

from alembic import op
from sqlalchemy import text

from migrations.schema_s0_0767 import ATOM_SQL, GUARD_SQL, PREVIOUS_GUARD_SQL
from migrations.versions.s0_0762_category_source_consumers import ordinary_owner

revision = "s0_0767"
down_revision = "s0_0766"
branch_labels = None
depends_on = None


def upgrade():
    ordinary_owner()
    op.execute("ALTER TABLE tenant_skill_enablements ADD COLUMN quality_paused_at timestamptz")
    op.execute("""UPDATE tenant_skill_enablements s SET quality_paused_at=b.created_at
      FROM agent_skill_review_batches b WHERE s.quality_review_id=b.id AND s.tenant_id=b.tenant_id
      AND s.quality_paused""")
    op.execute(ATOM_SQL)
    op.execute(GUARD_SQL)
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    if op.get_bind().scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM tenant_skill_enablements "
            "WHERE quality_paused_at IS NOT NULL)"
        )
    ):
        raise RuntimeError("Preserve recorded critical review watermarks; downgrade refused")
    ordinary_owner()
    op.execute(PREVIOUS_GUARD_SQL)
    op.execute("ALTER TABLE tenant_skill_enablements DROP COLUMN quality_paused_at")
    op.execute("SET LOCAL ROLE NONE")
