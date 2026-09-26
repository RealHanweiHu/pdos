"""Add supplemental Task values, interpreted against the creation template."""

import sqlalchemy as sa
from alembic import op

revision = "0283_task_template_fields"
down_revision = "0282_conversation_meeting_plan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE cehub_project.tasks ADD COLUMN template_fields jsonb NOT NULL DEFAULT '{}'::jsonb;
    ALTER TABLE cehub_project.tasks ADD CONSTRAINT ck_tasks_template_fields_object
      CHECK(jsonb_typeof(template_fields)='object');
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""
        SELECT EXISTS(SELECT 1 FROM cehub_project.tasks WHERE template_fields <> '{}'::jsonb)
    """)
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard supplemental Task field values")
    op.execute("""
        ALTER TABLE cehub_project.tasks DROP CONSTRAINT ck_tasks_template_fields_object,
        DROP COLUMN template_fields;
    """)
