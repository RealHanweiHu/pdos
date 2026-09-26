"""evidence based gate decisions (vNext V1-B6)

Revision ID: 0052_evidence_based_gate
Revises: 0051_sample_build_revision
Create Date: 2026-08-27 22:52:02.136772
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0052_evidence_based_gate"
down_revision: str | Sequence[str] | None = "0051_sample_build_revision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROJECT_SCHEMA = "cehub_project"
PRODUCT_SCHEMA = "cehub_product"

# Autogenerate compares check constraints by name only, so a widened
# expression has to be swapped explicitly.
_GATE_STATUS_OLD = "status IN ('preparing', 'reviewing', 'approved', 'rejected')"
_GATE_STATUS_NEW = (
    "status IN ('preparing', 'reviewing', 'approved', 'conditional', 'hold', 'rejected')"
)
_PURPOSE_ALLOWED = (
    "purpose IN ('engineering_build', 'certification_sample', 'customer_sample', "
    "'reliability_test', 'production_trial')"
)
_GATE_EVIDENCE = "NOT is_gate OR status <> 'completed' OR evidence_reference IS NOT NULL"


def _swap_gate_status(expression: str) -> None:
    op.drop_constraint(
        op.f("ck_gates_status_allowed"), "gates", schema=PROJECT_SCHEMA, type_="check"
    )
    op.create_check_constraint(
        op.f("ck_gates_status_allowed"), "gates", expression, schema=PROJECT_SCHEMA
    )


def upgrade() -> None:
    _swap_gate_status(_GATE_STATUS_NEW)
    op.add_column(
        "build_batches",
        sa.Column(
            "purpose",
            sa.String(length=32),
            server_default=sa.text("'engineering_build'"),
            nullable=False,
        ),
        schema=PRODUCT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_build_batches_purpose_allowed"),
        "build_batches",
        _PURPOSE_ALLOWED,
        schema=PRODUCT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_project_check_items_gate_completion_needs_evidence"),
        "project_check_items",
        _GATE_EVIDENCE,
        schema=PROJECT_SCHEMA,
    )


def downgrade() -> None:
    connection = op.get_bind()
    decided = connection.execute(
        sa.text(
            f"SELECT (SELECT count(*) FROM {PROJECT_SCHEMA}.gates "
            "        WHERE status IN ('conditional', 'hold')) "
            f"+ (SELECT count(*) FROM {PRODUCT_SCHEMA}.build_batches "
            "   WHERE purpose <> 'engineering_build')"
        )
    ).scalar_one()
    if decided:
        raise RuntimeError(
            "refusing downgrade while conditional/held gate decisions or "
            "non-engineering build purposes exist; the review outcome would be lost"
        )
    op.drop_constraint(
        op.f("ck_project_check_items_gate_completion_needs_evidence"),
        "project_check_items",
        schema=PROJECT_SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_build_batches_purpose_allowed"),
        "build_batches",
        schema=PRODUCT_SCHEMA,
        type_="check",
    )
    op.drop_column("build_batches", "purpose", schema=PRODUCT_SCHEMA)
    _swap_gate_status(_GATE_STATUS_OLD)
