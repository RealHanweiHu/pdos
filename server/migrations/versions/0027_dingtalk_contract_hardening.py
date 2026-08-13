"""harden DingTalk connector contract

Revision ID: 0027_dingtalk_hardening
Revises: 0026_dingtalk_connector
Create Date: 2026-08-13 01:02:00.000000
"""

from collections.abc import Sequence

from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "0027_dingtalk_hardening"
down_revision: str | Sequence[str] | None = "0026_dingtalk_connector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        op.f("ck_dingtalk_tenant_bindings_agent_id_numeric"),
        "dingtalk_tenant_bindings",
        "agent_id IS NULL OR agent_id ~ '^[1-9][0-9]{0,19}$'",
        schema="cehub_core",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_dingtalk_tenant_bindings_agent_id_numeric"),
        "dingtalk_tenant_bindings",
        type_="check",
        schema="cehub_core",
    )
