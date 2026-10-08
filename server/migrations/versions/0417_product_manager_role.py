"""Add independent product managers without granting project administration."""

from alembic import op
from sqlalchemy import text

revision = "0417_product_manager_role"
down_revision = "0416_product_evidence_item_decisions"
branch_labels = None
depends_on = None

OLD_ROLE_CHECK = (
    "role IN ('owner', 'admin', 'project_manager', 'engineer', 'quality', 'supplier', 'customer')"
)
NEW_ROLE_CHECK = (
    "role IN ('owner', 'admin', 'product_manager', 'project_manager', "
    "'engineer', 'quality', 'supplier', 'customer')"
)
INTERNAL_ROLES = "('owner','admin','project_manager','engineer','quality')"
PRODUCT_INTERNAL_ROLES = (
    "('owner','admin','product_manager','project_manager','engineer','quality')"
)
INTERNAL_FUNCTIONS = (
    "cehub_ai.application_pre_product_evaluation_authorization_is_current(uuid)",
    "cehub_ai.application_pre_product_work_authorization_is_current(uuid)",
    "cehub_ai.guard_product_discovery_finding()",
    "cehub_ai.guard_product_evidence_finding()",
    "cehub_ai.guard_product_planning_finding()",
    "cehub_ai.guard_product_research_finding()",
    "cehub_ai.protect_application_input_wait()",
    "cehub_ai.require_product_conversation_actor(uuid,uuid,uuid,uuid)",
    "cehub_evidence.protect_research_subscription()",
    "cehub_product.guard_id_handoff()",
    "cehub_project.guard_portfolio_selection_decision()",
)
MANAGER_ROLES = "('owner','admin','project_manager')"
PRODUCT_MANAGER_ROLES = "('owner','admin','product_manager','project_manager')"
PRODUCT_MANAGER_FUNCTIONS = (
    "cehub_ai.guard_product_rfq_finding()",
    "cehub_product.protect_market_space_identity()",
)
REPLACEMENTS = (
    *((name, INTERNAL_ROLES, PRODUCT_INTERNAL_ROLES) for name in INTERNAL_FUNCTIONS),
    *((name, MANAGER_ROLES, PRODUCT_MANAGER_ROLES) for name in PRODUCT_MANAGER_FUNCTIONS),
    (
        "cehub_project.guard_gate_named_assignment()",
        "s.key='product' AND p.role='project_manager'",
        "s.key='product' AND p.role IN ('product_manager','project_manager')",
    ),
    (
        "cehub_project.guard_gate_named_signoff()",
        "NEW.slot='product' AND actual_role='project_manager'",
        "NEW.slot='product' AND actual_role IN ('product_manager','project_manager')",
    ),
    (
        "cehub_project.guard_actual_correction()",
        "u.role IN ('engineer','quality') AND t.assignee_user_id=u.id",
        "u.role IN ('product_manager','engineer','quality') AND t.assignee_user_id=u.id",
    ),
)


def rewrite(*, forward: bool) -> None:
    for name, old, new in REPLACEMENTS:
        source, target = (old, new) if forward else (new, old)
        definition = str(
            op.get_bind()
            .execute(text("SELECT pg_get_functiondef(CAST(:name AS regprocedure))"), {"name": name})
            .scalar_one()
        )
        if definition.count(source) != 1:
            raise RuntimeError(f"Expected product-manager role guard is unavailable: {name}")
        op.execute(definition.replace(source, target))


def role_check(expression: str) -> None:
    op.drop_constraint(op.f("ck_users_role_allowed"), "users", schema="cehub_core", type_="check")
    op.create_check_constraint(
        op.f("ck_users_role_allowed"), "users", expression, schema="cehub_core"
    )


def upgrade() -> None:
    role_check(NEW_ROLE_CHECK)
    rewrite(forward=True)


def downgrade() -> None:
    # Never silently remap people or erase retained named signatures.
    op.execute("LOCK TABLE cehub_core.users IN ACCESS EXCLUSIVE MODE")
    op.execute(
        "LOCK TABLE cehub_project.gate_signoff_rounds, cehub_project.gate_signoffs "
        "IN ACCESS EXCLUSIVE MODE"
    )
    used = (
        op.get_bind()
        .execute(
            text(
                "SELECT EXISTS(SELECT 1 FROM cehub_core.users WHERE role='product_manager') "
                "OR EXISTS(SELECT 1 FROM cehub_project.gate_signoffs "
                "WHERE signer_role='product_manager') "
                "OR EXISTS(SELECT 1 FROM cehub_project.gate_signoff_rounds "
                "WHERE routing_snapshot#>>'{assignment,signers,product,role}'='product_manager')"
            )
        )
        .scalar_one()
    )
    if used:
        message = "Cannot downgrade 0417 while product-manager accounts or signatures remain"
        raise RuntimeError(message)
    rewrite(forward=False)
    role_check(OLD_ROLE_CHECK)
