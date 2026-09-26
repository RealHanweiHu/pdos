"""Keep manual existing-Issue reuse distinct from original Issue creation."""

import sqlalchemy as sa
from alembic import op

revision = "0235_issue_intake_reuse"
down_revision = "0234_issue_intake_confirm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE cehub_project.issue_intake_rows
          ADD COLUMN link_kind varchar(16) NOT NULL DEFAULT 'created',
          ADD COLUMN reuse_reason text,
          ADD CONSTRAINT ck_issue_intake_rows_link_kind CHECK (
            (link_kind='created' AND reuse_reason IS NULL) OR
            (link_kind='linked' AND btrim(reuse_reason)<>'' AND reuse_reason IS NOT NULL)
          );
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""
        SELECT EXISTS(SELECT 1 FROM cehub_project.issue_intake_rows WHERE link_kind='linked')
    """)
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to erase manual Issue reuse provenance")
    op.execute("""
        ALTER TABLE cehub_project.issue_intake_rows
          DROP CONSTRAINT ck_issue_intake_rows_link_kind,
          DROP COLUMN reuse_reason,
          DROP COLUMN link_kind;
    """)
