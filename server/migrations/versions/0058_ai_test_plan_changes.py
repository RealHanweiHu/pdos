"""Typed test-plan Finding and append-only revision links."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0058_ai_test_plan_changes"
down_revision: str | Sequence[str] | None = "0057_test_template_snapshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINTS = {
    (
        "finding_quality_controls",
        "type_allowed",
    ): (
        "(agent_key = 'project_intelligence' AND finding_type IN "
        "('risk_suggestion', 'blocker_alert', 'gate_readiness_anomaly')) OR "
        "(agent_key = 'knowledge_lite' AND finding_type = 'knowledge_draft') OR "
        "(agent_key = 'engineering_intelligence' AND finding_type IN "
        "('bom_impact_suggestion', 'change_impact_suggestion')) OR (agent_key = "
        "'quality_intelligence' AND finding_type IN ('quality_cluster_alert', "
        "'capa_suggestion', 'test_plan_change')) OR (agent_key = "
        "'supplier_intelligence' AND finding_type = 'supplier_delay_risk') OR "
        "(agent_key = 'executive_intelligence' AND finding_type = "
        "'executive_portfolio_brief')"
    ),
    (
        "findings",
        "type_allowed",
    ): (
        "(agent_key = 'project_intelligence' AND finding_type IN "
        "('risk_suggestion', 'blocker_alert', 'gate_readiness_anomaly')) OR "
        "(agent_key = 'knowledge_lite' AND finding_type = 'knowledge_draft') OR "
        "(agent_key = 'engineering_intelligence' AND finding_type IN "
        "('bom_impact_suggestion', 'change_impact_suggestion')) OR (agent_key = "
        "'quality_intelligence' AND finding_type IN ('quality_cluster_alert', "
        "'capa_suggestion', 'test_plan_change')) OR (agent_key = "
        "'supplier_intelligence' AND finding_type = 'supplier_delay_risk') OR "
        "(agent_key = 'executive_intelligence' AND finding_type = "
        "'executive_portfolio_brief')"
    ),
    (
        "findings",
        "apply_lifecycle_consistent",
    ): (
        "(status <> 'applied' AND applied_by_user_id IS NULL AND applied_at IS NULL"
        " AND applied_entity_type IS NULL AND applied_entity_id IS NULL) OR (status"
        " = 'applied' AND applied_by_user_id IS NOT NULL AND applied_at IS NOT NULL"
        " AND applied_entity_type IN ('risk', 'memory', 'issue', 'task', "
        "'test_run', 'sample_build_configuration', 'knowledge_candidate', "
        "'schedule_change_proposal', 'material_exception', 'test_plan') AND "
        "applied_entity_id IS NOT NULL AND reviewed_at < applied_at)"
    ),
}


def constraints(*, upgrade: bool) -> None:
    for (table, name), expression in CONSTRAINTS.items():
        if not upgrade:
            expression = expression.replace(", 'test_plan_change'", "").replace(
                ", 'test_plan') AND", ") AND"
            )
        op.drop_constraint(op.f(f"ck_{table}_{name}"), table, schema="cehub_ai", type_="check")
        op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, expression, schema="cehub_ai")


def upgrade() -> None:
    constraints(upgrade=True)
    for name in ("parent_plan_id", "source_finding_id"):
        op.add_column(
            "test_plans", sa.Column(name, sa.Uuid(), nullable=True), schema="cehub_quality"
        )
    for name, target, column, remote in (
        ("parent", "test_plans", "parent_plan_id", "cehub_quality"),
        ("finding", "findings", "source_finding_id", "cehub_ai"),
    ):
        op.create_foreign_key(
            f"fk_test_plans_{name}",
            "test_plans",
            target,
            ["tenant_id", "project_id", column],
            ["tenant_id", "project_id", "id"],
            source_schema="cehub_quality",
            referent_schema=remote,
            ondelete="RESTRICT",
        )
    op.create_unique_constraint(
        "uq_test_plans_parent_revision",
        "test_plans",
        ["tenant_id", "parent_plan_id"],
        schema="cehub_quality",
    )
    op.create_unique_constraint(
        "uq_test_plans_source_finding",
        "test_plans",
        ["tenant_id", "source_finding_id"],
        schema="cehub_quality",
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM cehub_ai.findings WHERE finding_type = "
                "'test_plan_change') "
                "OR EXISTS (SELECT 1 FROM cehub_quality.test_plans WHERE parent_plan_id IS "
                "NOT NULL OR source_finding_id IS NOT NULL) "
                "OR EXISTS (SELECT 1 FROM cehub_ai.finding_quality_controls WHERE "
                "finding_type = 'test_plan_change')"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("refusing downgrade: test plan proposals or revisions exist")
    for name in ("uq_test_plans_parent_revision", "uq_test_plans_source_finding"):
        op.drop_constraint(name, "test_plans", type_="unique", schema="cehub_quality")
    for name in ("fk_test_plans_parent", "fk_test_plans_finding"):
        op.drop_constraint(name, "test_plans", type_="foreignkey", schema="cehub_quality")
    for name in ("parent_plan_id", "source_finding_id"):
        op.drop_column("test_plans", name, schema="cehub_quality")
    constraints(upgrade=False)
