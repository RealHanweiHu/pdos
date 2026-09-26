"""Add supplemental Issue values, interpreted against the creation template."""

import sqlalchemy as sa
from alembic import op

revision = "0231_issue_template_fields"
down_revision = "0230_template_generation_v5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE cehub_project.issues ADD COLUMN template_fields jsonb NOT NULL DEFAULT '{}'::jsonb;
    ALTER TABLE cehub_project.issues ADD CONSTRAINT ck_issues_template_fields_object
      CHECK(jsonb_typeof(template_fields)='object');
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""
        SELECT EXISTS(SELECT 1 FROM cehub_project.issues WHERE template_fields <> '{}'::jsonb)
    """)
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard supplemental Issue field values")
    op.execute("""
        ALTER TABLE cehub_project.issues DROP CONSTRAINT ck_issues_template_fields_object,
        DROP COLUMN template_fields;
    """)
