"""add provider prompt-cache token accounting

Revision ID: 0009_invocation_cache_tokens
Revises: 0008_model_gateway
Create Date: 2026-08-11 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_invocation_cache_tokens"
down_revision: str | Sequence[str] | None = "0008_model_gateway"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AI_SCHEMA = "cehub_ai"


def upgrade() -> None:
    op.add_column(
        "model_invocations",
        sa.Column(
            "cache_read_tokens",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        schema=AI_SCHEMA,
    )
    op.add_column(
        "model_invocations",
        sa.Column(
            "cache_creation_tokens",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        schema=AI_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_model_invocations_cache_tokens_nonnegative"),
        "model_invocations",
        "cache_read_tokens >= 0 AND cache_creation_tokens >= 0",
        schema=AI_SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_model_invocations_cache_tokens_nonnegative"),
        "model_invocations",
        type_="check",
        schema=AI_SCHEMA,
    )
    op.drop_column("model_invocations", "cache_creation_tokens", schema=AI_SCHEMA)
    op.drop_column("model_invocations", "cache_read_tokens", schema=AI_SCHEMA)
