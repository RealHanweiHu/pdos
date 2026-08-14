"""freeze project workflow and stage instance contracts

Revision ID: 0006_project_lifecycle
Revises: 0005_development_cases
Create Date: 2026-08-11 16:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "0006_project_lifecycle"
down_revision: str | Sequence[str] | None = "0005_development_cases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROJECT_SCHEMA = "cehub_project"


def upgrade() -> None:
    for table_name in ("workflows", "stages", "projects"):
        op.create_check_constraint(
            op.f(f"ck_{table_name}_code_nonblank"),
            table_name,
            "btrim(code) <> ''",
            schema=PROJECT_SCHEMA,
        )
        op.create_check_constraint(
            op.f(f"ck_{table_name}_name_nonblank"),
            table_name,
            "btrim(name) <> ''",
            schema=PROJECT_SCHEMA,
        )
    op.create_unique_constraint(
        "uq_projects_tenant_development_case",
        "projects",
        ["tenant_id", "development_case_id"],
        schema=PROJECT_SCHEMA,
    )
    op.create_unique_constraint(
        "uq_projects_tenant_workflow",
        "projects",
        ["tenant_id", "workflow_id"],
        schema=PROJECT_SCHEMA,
    )
    op.create_index(
        "ix_projects_tenant_updated",
        "projects",
        ["tenant_id", "updated_at", "id"],
        unique=False,
        schema=PROJECT_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_projects_tenant_updated",
        table_name="projects",
        schema=PROJECT_SCHEMA,
    )
    op.drop_constraint(
        "uq_projects_tenant_workflow",
        "projects",
        type_="unique",
        schema=PROJECT_SCHEMA,
    )
    op.drop_constraint(
        "uq_projects_tenant_development_case",
        "projects",
        type_="unique",
        schema=PROJECT_SCHEMA,
    )
    for table_name in ("projects", "stages", "workflows"):
        op.drop_constraint(
            op.f(f"ck_{table_name}_name_nonblank"),
            table_name,
            type_="check",
            schema=PROJECT_SCHEMA,
        )
        op.drop_constraint(
            op.f(f"ck_{table_name}_code_nonblank"),
            table_name,
            type_="check",
            schema=PROJECT_SCHEMA,
        )
