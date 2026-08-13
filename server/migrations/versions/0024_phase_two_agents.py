"""add Phase 2 Engineering and Quality Agent contracts

Revision ID: 0024_phase_two_agents
Revises: 0023_memory_finding_apply
Create Date: 2026-08-12 23:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024_phase_two_agents"
down_revision: str | Sequence[str] | None = "0023_memory_finding_apply"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AI_SCHEMA = "cehub_ai"
AGENT_KEYS = (
    "agent_key IN ('project_intelligence', 'knowledge_lite', "
    "'engineering_intelligence', 'quality_intelligence')"
)
PHASE_ONE_AGENT_KEYS = "agent_key IN ('project_intelligence', 'knowledge_lite')"
FINDING_TYPES = (
    "(agent_key = 'project_intelligence' AND finding_type IN "
    "('risk_suggestion', 'blocker_alert', 'gate_readiness_anomaly')) OR "
    "(agent_key = 'knowledge_lite' AND finding_type = 'knowledge_draft') OR "
    "(agent_key = 'engineering_intelligence' AND finding_type IN "
    "('bom_impact_suggestion', 'change_impact_suggestion')) OR "
    "(agent_key = 'quality_intelligence' AND finding_type IN "
    "('quality_cluster_alert', 'capa_suggestion'))"
)
PHASE_ONE_FINDING_TYPES = (
    "(agent_key = 'project_intelligence' AND finding_type IN "
    "('risk_suggestion', 'blocker_alert', 'gate_readiness_anomaly')) OR "
    "(agent_key = 'knowledge_lite' AND finding_type = 'knowledge_draft')"
)


def _replace_check(*, table: str, constraint: str, expression: str) -> None:
    op.drop_constraint(op.f(constraint), table, schema=AI_SCHEMA, type_="check")
    op.create_check_constraint(op.f(constraint), table, expression, schema=AI_SCHEMA)


def upgrade() -> None:
    _replace_check(
        table="agent_subscriptions",
        constraint="ck_agent_subscriptions_agent_key_allowed",
        expression=AGENT_KEYS,
    )
    _replace_check(
        table="agent_runs",
        constraint="ck_agent_runs_agent_key_allowed",
        expression=AGENT_KEYS,
    )
    _replace_check(
        table="finding_quality_controls",
        constraint="ck_finding_quality_controls_type_allowed",
        expression=FINDING_TYPES,
    )
    _replace_check(
        table="findings",
        constraint="ck_findings_type_allowed",
        expression=FINDING_TYPES,
    )


def downgrade() -> None:
    op.execute(
        """
        DO $block$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM cehub_ai.agent_subscriptions
                WHERE agent_key IN ('engineering_intelligence', 'quality_intelligence')
            ) OR EXISTS (
                SELECT 1 FROM cehub_ai.agent_runs
                WHERE agent_key IN ('engineering_intelligence', 'quality_intelligence')
            ) OR EXISTS (
                SELECT 1 FROM cehub_ai.findings
                WHERE agent_key IN ('engineering_intelligence', 'quality_intelligence')
            ) OR EXISTS (
                SELECT 1 FROM cehub_ai.finding_quality_controls
                WHERE agent_key IN ('engineering_intelligence', 'quality_intelligence')
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade 0024 while Phase 2 Agent records exist';
            END IF;
        END
        $block$
        """
    )
    _replace_check(
        table="findings",
        constraint="ck_findings_type_allowed",
        expression=PHASE_ONE_FINDING_TYPES,
    )
    _replace_check(
        table="finding_quality_controls",
        constraint="ck_finding_quality_controls_type_allowed",
        expression=PHASE_ONE_FINDING_TYPES,
    )
    _replace_check(
        table="agent_runs",
        constraint="ck_agent_runs_agent_key_allowed",
        expression=PHASE_ONE_AGENT_KEYS,
    )
    _replace_check(
        table="agent_subscriptions",
        constraint="ck_agent_subscriptions_agent_key_allowed",
        expression=PHASE_ONE_AGENT_KEYS,
    )
