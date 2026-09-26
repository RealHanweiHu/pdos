"""requirement tiering and spec-to-verification traceability (vNext V1-B1)

Revision ID: 0039_req_spec_traceability
Revises: 0038_decision_contract
Create Date: 2026-08-25 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039_req_spec_traceability"
down_revision: str | Sequence[str] | None = "0038_decision_contract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROJECT_SCHEMA = "cehub_project"
PRODUCT_SCHEMA = "cehub_product"
QUALITY_SCHEMA = "cehub_quality"


def upgrade() -> None:
    op.add_column(
        "requirements",
        sa.Column(
            "tier", sa.String(length=16), nullable=False, server_default=sa.text("'customer'")
        ),
        schema=PROJECT_SCHEMA,
    )
    op.add_column(
        "requirements",
        sa.Column("parent_requirement_id", sa.Uuid(), nullable=True),
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_requirements_tier_allowed"),
        "requirements",
        "tier IN ('customer', 'market', 'product')",
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_requirements_parent_not_self"),
        "requirements",
        "parent_requirement_id IS NULL OR parent_requirement_id <> id",
        schema=PROJECT_SCHEMA,
    )
    op.create_foreign_key(
        "fk_requirements_tenant_parent",
        "requirements",
        "requirements",
        ["tenant_id", "parent_requirement_id"],
        ["tenant_id", "id"],
        source_schema=PROJECT_SCHEMA,
        referent_schema=PROJECT_SCHEMA,
        ondelete="RESTRICT",
    )

    op.add_column(
        "specifications",
        sa.Column("requirement_id", sa.Uuid(), nullable=True),
        schema=PRODUCT_SCHEMA,
    )
    op.add_column(
        "specifications",
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        schema=PRODUCT_SCHEMA,
    )
    op.add_column(
        "specifications",
        sa.Column("verification_method", sa.Text(), nullable=True),
        schema=PRODUCT_SCHEMA,
    )
    op.add_column(
        "specifications",
        sa.Column("acceptance_criteria", sa.Text(), nullable=True),
        schema=PRODUCT_SCHEMA,
    )
    op.add_column(
        "specifications",
        sa.Column(
            "criticality",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'standard'"),
        ),
        schema=PRODUCT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_specifications_criticality_allowed"),
        "specifications",
        "criticality IN ('standard', 'key')",
        schema=PRODUCT_SCHEMA,
    )
    op.create_foreign_key(
        "fk_specifications_tenant_requirement",
        "specifications",
        "requirements",
        ["tenant_id", "requirement_id"],
        ["tenant_id", "id"],
        source_schema=PRODUCT_SCHEMA,
        referent_schema=PROJECT_SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_specifications_tenant_owner",
        "specifications",
        "users",
        ["tenant_id", "owner_user_id"],
        ["tenant_id", "id"],
        source_schema=PRODUCT_SCHEMA,
        referent_schema="cehub_core",
        ondelete="RESTRICT",
    )

    op.add_column(
        "test_cases",
        sa.Column("specification_id", sa.Uuid(), nullable=True),
        schema=QUALITY_SCHEMA,
    )
    op.create_foreign_key(
        "fk_test_cases_tenant_specification",
        "test_cases",
        "specifications",
        ["tenant_id", "specification_id"],
        ["tenant_id", "id"],
        source_schema=QUALITY_SCHEMA,
        referent_schema=PRODUCT_SCHEMA,
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    connection = op.get_bind()
    traced_rows = connection.execute(
        sa.text(
            "SELECT "
            f"(SELECT count(*) FROM {PROJECT_SCHEMA}.requirements "
            " WHERE tier <> 'customer' OR parent_requirement_id IS NOT NULL) + "
            f"(SELECT count(*) FROM {PRODUCT_SCHEMA}.specifications "
            " WHERE requirement_id IS NOT NULL OR owner_user_id IS NOT NULL "
            " OR verification_method IS NOT NULL OR acceptance_criteria IS NOT NULL "
            " OR criticality <> 'standard') + "
            f"(SELECT count(*) FROM {QUALITY_SCHEMA}.test_cases "
            " WHERE specification_id IS NOT NULL)"
        )
    ).scalar_one()
    if traced_rows:
        raise RuntimeError("refusing lossy downgrade while traceability data exists")

    op.drop_constraint(
        "fk_test_cases_tenant_specification",
        "test_cases",
        schema=QUALITY_SCHEMA,
        type_="foreignkey",
    )
    op.drop_column("test_cases", "specification_id", schema=QUALITY_SCHEMA)

    op.drop_constraint(
        "fk_specifications_tenant_owner",
        "specifications",
        schema=PRODUCT_SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_specifications_tenant_requirement",
        "specifications",
        schema=PRODUCT_SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("ck_specifications_criticality_allowed"),
        "specifications",
        schema=PRODUCT_SCHEMA,
        type_="check",
    )
    for column in (
        "criticality",
        "acceptance_criteria",
        "verification_method",
        "owner_user_id",
        "requirement_id",
    ):
        op.drop_column("specifications", column, schema=PRODUCT_SCHEMA)

    op.drop_constraint(
        "fk_requirements_tenant_parent",
        "requirements",
        schema=PROJECT_SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("ck_requirements_parent_not_self"),
        "requirements",
        schema=PROJECT_SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_requirements_tier_allowed"),
        "requirements",
        schema=PROJECT_SCHEMA,
        type_="check",
    )
    op.drop_column("requirements", "parent_requirement_id", schema=PROJECT_SCHEMA)
    op.drop_column("requirements", "tier", schema=PROJECT_SCHEMA)
