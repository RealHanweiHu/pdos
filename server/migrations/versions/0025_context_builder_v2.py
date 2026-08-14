"""version Agent run context with Multimodal and User layers

Revision ID: 0025_context_builder_v2
Revises: 0024_phase_two_agents
Create Date: 2026-08-13 00:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_context_builder_v2"
down_revision: str | Sequence[str] | None = "0024_phase_two_agents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "agent_runs",
        "context_version",
        schema="cehub_ai",
        existing_type=sa.String(length=64),
        existing_nullable=False,
        server_default=sa.text("'run-context-v2'"),
    )


def downgrade() -> None:
    op.execute(
        """
        DO $block$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM cehub_ai.agent_runs
                WHERE run_context->>'schema_version' = '2'
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade 0025 while run-context-v2 records exist';
            END IF;
        END
        $block$
        """
    )
    op.alter_column(
        "agent_runs",
        "context_version",
        schema="cehub_ai",
        existing_type=sa.String(length=64),
        existing_nullable=False,
        server_default=sa.text("'run-context-v1'"),
    )
