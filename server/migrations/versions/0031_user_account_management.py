"""add tenant user account management credential version

Revision ID: 0031_user_account_management
Revises: 0030_phase_three_agents
Create Date: 2026-08-20 06:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031_user_account_management"
down_revision: str | Sequence[str] | None = "0030_phase_three_agents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CORE_SCHEMA = "cehub_core"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("auth_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        schema=CORE_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_users_auth_version_positive"),
        "users",
        "auth_version >= 1",
        schema=CORE_SCHEMA,
    )


def downgrade() -> None:
    op.execute(
        """
        DO $block$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM cehub_core.users WHERE auth_version <> 1
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade 0031 while revoked credential versions exist';
            END IF;
        END
        $block$
        """
    )
    op.drop_constraint(
        op.f("ck_users_auth_version_positive"),
        "users",
        schema=CORE_SCHEMA,
        type_="check",
    )
    op.drop_column("users", "auth_version", schema=CORE_SCHEMA)
