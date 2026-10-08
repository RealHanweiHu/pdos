"""Persist administrator-assigned additional workspace modules."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0419_user_work_modules"
down_revision = "0418_xiaopai_conversation_replies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "work_modules", ARRAY(sa.String(32)), nullable=False, server_default=sa.text("'{}'")
        ),
        schema="cehub_core",
    )
    op.create_check_constraint(
        op.f("ck_users_work_modules_allowed"),
        "users",
        "work_modules <@ ARRAY['product','project','engineering','quality',"
        "'introduction','supply','portfolio']::varchar[] "
        "AND array_position(work_modules, NULL) IS NULL "
        "AND (role NOT IN ('supplier','customer') OR cardinality(work_modules) = 0)",
        schema="cehub_core",
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_core.users WHERE cardinality(work_modules) > 0)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Cannot downgrade 0419 while assigned work modules remain")
    op.drop_constraint(op.f("ck_users_work_modules_allowed"), "users", schema="cehub_core")
    op.drop_column("users", "work_modules", schema="cehub_core")
