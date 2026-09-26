"""Add supplemental Risk values, interpreted against the creation template."""

import sqlalchemy as sa
from alembic import op

revision = "0288_risk_template_fields"
down_revision = "0287_template_generation_v8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE cehub_project.risks ADD COLUMN template_fields jsonb NOT NULL DEFAULT '{}'::jsonb;
    ALTER TABLE cehub_project.risks ADD CONSTRAINT ck_risks_template_fields_object
      CHECK(jsonb_typeof(template_fields)='object');
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""
        SELECT EXISTS(SELECT 1 FROM cehub_project.risks WHERE template_fields <> '{}'::jsonb)
    """)
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard supplemental Risk field values")
    op.execute("""
        ALTER TABLE cehub_project.risks DROP CONSTRAINT ck_risks_template_fields_object,
        DROP COLUMN template_fields;
    """)
