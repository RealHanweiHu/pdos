"""add OpenRouter and OpenCode Go model provider identities

Revision ID: 0033_expand_model_providers
Revises: 0032_repair_task_titles
Create Date: 2026-08-22 01:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0033_expand_model_providers"
down_revision: str | Sequence[str] | None = "0032_repair_task_titles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_PROVIDERS = "provider IN ('minimax', 'deepseek', 'glm', 'openai', 'anthropic')"
_NEW_PROVIDERS = (
    "provider IN ('minimax', 'deepseek', 'glm', 'openai', 'anthropic', 'openrouter', 'opencode_go')"
)


def _replace_provider_constraints(expression: str) -> None:
    for table_name in ("tenant_model_settings", "model_invocations"):
        constraint_name = f"ck_{table_name}_provider_allowed"
        op.drop_constraint(
            op.f(constraint_name),
            table_name,
            schema="cehub_ai",
            type_="check",
        )
        op.create_check_constraint(
            op.f(constraint_name),
            table_name,
            expression,
            schema="cehub_ai",
        )


def upgrade() -> None:
    _replace_provider_constraints(_NEW_PROVIDERS)


def downgrade() -> None:
    _replace_provider_constraints(_OLD_PROVIDERS)
