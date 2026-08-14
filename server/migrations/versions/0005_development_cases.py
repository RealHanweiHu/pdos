"""freeze Development Case conversion and state contracts

Revision ID: 0005_development_cases
Revises: 0004_requirement_pool
Create Date: 2026-08-11 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "0005_development_cases"
down_revision: str | Sequence[str] | None = "0004_requirement_pool"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROJECT_SCHEMA = "cehub_project"


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_development_cases_status_allowed"),
        "development_cases",
        type_="check",
        schema=PROJECT_SCHEMA,
    )
    op.execute(
        sa.text(
            "UPDATE cehub_project.development_cases "
            "SET status = 'evaluating' WHERE status = 'proposed'"
        )
    )
    op.create_check_constraint(
        op.f("ck_development_cases_status_allowed"),
        "development_cases",
        "status IN ('draft', 'evaluating', 'approved', 'rejected', 'converted')",
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_development_cases_code_nonblank"),
        "development_cases",
        "btrim(code) <> ''",
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_development_cases_title_nonblank"),
        "development_cases",
        "btrim(title) <> ''",
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_development_cases_business_case_object"),
        "development_cases",
        "jsonb_typeof(business_case) = 'object'",
        schema=PROJECT_SCHEMA,
    )
    op.create_unique_constraint(
        "uq_development_cases_tenant_requirement",
        "development_cases",
        ["tenant_id", "requirement_id"],
        schema=PROJECT_SCHEMA,
    )
    op.create_index(
        "ix_development_cases_tenant_updated",
        "development_cases",
        ["tenant_id", "updated_at", "id"],
        unique=False,
        schema=PROJECT_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_development_cases_tenant_updated",
        table_name="development_cases",
        schema=PROJECT_SCHEMA,
    )
    op.drop_constraint(
        "uq_development_cases_tenant_requirement",
        "development_cases",
        type_="unique",
        schema=PROJECT_SCHEMA,
    )
    op.drop_constraint(
        op.f("ck_development_cases_business_case_object"),
        "development_cases",
        type_="check",
        schema=PROJECT_SCHEMA,
    )
    op.drop_constraint(
        op.f("ck_development_cases_title_nonblank"),
        "development_cases",
        type_="check",
        schema=PROJECT_SCHEMA,
    )
    op.drop_constraint(
        op.f("ck_development_cases_code_nonblank"),
        "development_cases",
        type_="check",
        schema=PROJECT_SCHEMA,
    )
    op.drop_constraint(
        op.f("ck_development_cases_status_allowed"),
        "development_cases",
        type_="check",
        schema=PROJECT_SCHEMA,
    )
    op.execute(
        sa.text(
            "UPDATE cehub_project.development_cases "
            "SET status = 'proposed' WHERE status = 'evaluating'"
        )
    )
    op.create_check_constraint(
        op.f("ck_development_cases_status_allowed"),
        "development_cases",
        "status IN ('draft', 'proposed', 'approved', 'rejected', 'converted')",
        schema=PROJECT_SCHEMA,
    )
