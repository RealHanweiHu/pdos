"""harden requirement pool data contracts

Revision ID: 0004_requirement_pool
Revises: 0003_events_audit
Create Date: 2026-08-11 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "0004_requirement_pool"
down_revision: str | Sequence[str] | None = "0003_events_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CORE_SCHEMA = "cehub_core"
PROJECT_SCHEMA = "cehub_project"


def upgrade() -> None:
    op.create_check_constraint(
        op.f("ck_customers_code_nonblank"),
        "customers",
        "btrim(code) <> ''",
        schema=CORE_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_customers_name_nonblank"),
        "customers",
        "btrim(name) <> ''",
        schema=CORE_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_requirements_code_nonblank"),
        "requirements",
        "btrim(code) <> ''",
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_requirements_title_nonblank"),
        "requirements",
        "btrim(title) <> ''",
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_requirements_acceptance_criteria_array"),
        "requirements",
        "jsonb_typeof(acceptance_criteria) = 'array'",
        schema=PROJECT_SCHEMA,
    )
    op.create_index(
        "ix_requirements_tenant_updated",
        "requirements",
        ["tenant_id", "updated_at", "id"],
        unique=False,
        schema=PROJECT_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_requirements_tenant_updated",
        table_name="requirements",
        schema=PROJECT_SCHEMA,
    )
    op.drop_constraint(
        op.f("ck_requirements_acceptance_criteria_array"),
        "requirements",
        type_="check",
        schema=PROJECT_SCHEMA,
    )
    op.drop_constraint(
        op.f("ck_requirements_title_nonblank"),
        "requirements",
        type_="check",
        schema=PROJECT_SCHEMA,
    )
    op.drop_constraint(
        op.f("ck_requirements_code_nonblank"),
        "requirements",
        type_="check",
        schema=PROJECT_SCHEMA,
    )
    op.drop_constraint(
        op.f("ck_customers_name_nonblank"),
        "customers",
        type_="check",
        schema=CORE_SCHEMA,
    )
    op.drop_constraint(
        op.f("ck_customers_code_nonblank"),
        "customers",
        type_="check",
        schema=CORE_SCHEMA,
    )
