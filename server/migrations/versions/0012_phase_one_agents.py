"""add Phase 1 dual Agent Finding types

Revision ID: 0012_phase_one_agents
Revises: 0011_ai_findings
Create Date: 2026-08-12 00:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012_phase_one_agents"
down_revision: str | Sequence[str] | None = "0011_ai_findings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AI_SCHEMA = "cehub_ai"
CONSTRAINT_NAME = "ck_findings_type_allowed"


def upgrade() -> None:
    op.drop_constraint(
        op.f(CONSTRAINT_NAME),
        "findings",
        type_="check",
        schema=AI_SCHEMA,
    )
    op.create_check_constraint(
        op.f(CONSTRAINT_NAME),
        "findings",
        "(agent_key = 'project_intelligence' AND finding_type IN "
        "('risk_suggestion', 'blocker_alert', 'gate_readiness_anomaly')) OR "
        "(agent_key = 'knowledge_lite' AND finding_type = 'knowledge_draft')",
        schema=AI_SCHEMA,
    )


def downgrade() -> None:
    op.execute(
        """
        DO $block$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM cehub_ai.findings
                WHERE finding_type <> 'risk_suggestion'
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade 0012 while Phase 1 non-risk findings exist';
            END IF;
        END
        $block$
        """
    )
    op.drop_constraint(
        op.f(CONSTRAINT_NAME),
        "findings",
        type_="check",
        schema=AI_SCHEMA,
    )
    op.create_check_constraint(
        op.f(CONSTRAINT_NAME),
        "findings",
        "finding_type IN ('risk_suggestion')",
        schema=AI_SCHEMA,
    )
