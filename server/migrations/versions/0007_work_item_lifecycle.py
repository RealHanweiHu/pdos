"""freeze task dependency and work-item lifecycle contracts

Revision ID: 0007_work_item_lifecycle
Revises: 0006_project_lifecycle
Create Date: 2026-08-11 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "0007_work_item_lifecycle"
down_revision: str | Sequence[str] | None = "0006_project_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CORE_SCHEMA = "cehub_core"
PROJECT_SCHEMA = "cehub_project"


def upgrade() -> None:
    op.add_column(
        "tasks", sa.Column("workflow_id", sa.Uuid(), nullable=True), schema=PROJECT_SCHEMA
    )
    op.add_column(
        "tasks", sa.Column("blocked_reason", sa.Text(), nullable=True), schema=PROJECT_SCHEMA
    )
    op.add_column(
        "issues", sa.Column("workflow_id", sa.Uuid(), nullable=True), schema=PROJECT_SCHEMA
    )

    op.execute(
        """
        UPDATE cehub_project.tasks AS task
        SET workflow_id = stage.workflow_id
        FROM cehub_project.stages AS stage
        WHERE task.stage_id = stage.id AND task.tenant_id = stage.tenant_id
        """
    )
    op.execute(
        """
        UPDATE cehub_project.issues AS issue
        SET workflow_id = stage.workflow_id
        FROM cehub_project.stages AS stage
        WHERE issue.stage_id = stage.id AND issue.tenant_id = stage.tenant_id
        """
    )
    op.execute(
        """
        UPDATE cehub_project.tasks
        SET blocked_reason = 'Migrated legacy blocked task'
        WHERE status = 'blocked' AND (blocked_reason IS NULL OR btrim(blocked_reason) = '')
        """
    )
    op.execute(
        "UPDATE cehub_project.tasks SET completed_at = CURRENT_TIMESTAMP "
        "WHERE status = 'done' AND completed_at IS NULL"
    )
    op.execute("UPDATE cehub_project.tasks SET completed_at = NULL WHERE status <> 'done'")
    for table_name in ("issues", "risks"):
        op.execute(
            f"UPDATE cehub_project.{table_name} SET closed_at = CURRENT_TIMESTAMP "
            "WHERE status = 'closed' AND closed_at IS NULL"
        )
        op.execute(
            f"UPDATE cehub_project.{table_name} SET closed_at = NULL WHERE status <> 'closed'"
        )

    _create_work_item_constraints()
    _create_work_item_indexes()
    _create_task_dependencies()


def _create_work_item_constraints() -> None:
    for table_name in ("tasks", "issues", "risks"):
        op.create_check_constraint(
            op.f(f"ck_{table_name}_title_nonblank"),
            table_name,
            "btrim(title) <> ''",
            schema=PROJECT_SCHEMA,
        )

    op.create_check_constraint(
        op.f("ck_tasks_blocked_reason_consistent"),
        "tasks",
        "(status = 'blocked' AND blocked_reason IS NOT NULL AND btrim(blocked_reason) <> '') "
        "OR (status <> 'blocked' AND blocked_reason IS NULL)",
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_tasks_completion_consistent"),
        "tasks",
        "(status = 'done' AND completed_at IS NOT NULL) "
        "OR (status <> 'done' AND completed_at IS NULL)",
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_tasks_stage_pair_consistent"),
        "tasks",
        "(workflow_id IS NULL AND stage_id IS NULL) "
        "OR (workflow_id IS NOT NULL AND stage_id IS NOT NULL)",
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_issues_closed_at_consistent"),
        "issues",
        "(status = 'closed' AND closed_at IS NOT NULL) "
        "OR (status <> 'closed' AND closed_at IS NULL)",
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_issues_stage_pair_consistent"),
        "issues",
        "(workflow_id IS NULL AND stage_id IS NULL) "
        "OR (workflow_id IS NOT NULL AND stage_id IS NOT NULL)",
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_risks_closed_at_consistent"),
        "risks",
        "(status = 'closed' AND closed_at IS NOT NULL) "
        "OR (status <> 'closed' AND closed_at IS NULL)",
        schema=PROJECT_SCHEMA,
    )

    for table_name in ("tasks", "issues"):
        op.drop_constraint(
            f"fk_{table_name}_tenant_stage",
            table_name,
            type_="foreignkey",
            schema=PROJECT_SCHEMA,
        )
        op.create_foreign_key(
            f"fk_{table_name}_tenant_project_workflow",
            table_name,
            "projects",
            ["tenant_id", "workflow_id", "project_id"],
            ["tenant_id", "workflow_id", "id"],
            source_schema=PROJECT_SCHEMA,
            referent_schema=PROJECT_SCHEMA,
            ondelete="RESTRICT",
        )
        op.create_foreign_key(
            f"fk_{table_name}_tenant_workflow_stage",
            table_name,
            "stages",
            ["tenant_id", "workflow_id", "stage_id"],
            ["tenant_id", "workflow_id", "id"],
            source_schema=PROJECT_SCHEMA,
            referent_schema=PROJECT_SCHEMA,
            ondelete="RESTRICT",
        )


def _create_work_item_indexes() -> None:
    for table_name in ("tasks", "issues", "risks"):
        op.create_index(
            f"ix_{table_name}_tenant_project_updated",
            table_name,
            ["tenant_id", "project_id", "updated_at", "id"],
            unique=False,
            schema=PROJECT_SCHEMA,
        )


def _create_task_dependencies() -> None:
    op.create_table(
        "task_dependencies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("depends_on_task_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "task_id <> depends_on_task_id",
            name=op.f("ck_task_dependencies_no_self_reference"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{CORE_SCHEMA}.tenants.id"],
            name=op.f("fk_task_dependencies_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "task_id"],
            [
                f"{PROJECT_SCHEMA}.tasks.tenant_id",
                f"{PROJECT_SCHEMA}.tasks.project_id",
                f"{PROJECT_SCHEMA}.tasks.id",
            ],
            name="fk_task_dependencies_tenant_project_task",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "depends_on_task_id"],
            [
                f"{PROJECT_SCHEMA}.tasks.tenant_id",
                f"{PROJECT_SCHEMA}.tasks.project_id",
                f"{PROJECT_SCHEMA}.tasks.id",
            ],
            name="fk_task_dependencies_tenant_project_predecessor",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_dependencies")),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "task_id",
            "depends_on_task_id",
            name="uq_task_dependencies_tenant_project_edge",
        ),
        schema=PROJECT_SCHEMA,
    )
    op.create_index(
        "ix_task_dependencies_tenant_project_predecessor",
        "task_dependencies",
        ["tenant_id", "project_id", "depends_on_task_id"],
        unique=False,
        schema=PROJECT_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_task_dependencies_tenant_project_predecessor",
        table_name="task_dependencies",
        schema=PROJECT_SCHEMA,
    )
    op.drop_table("task_dependencies", schema=PROJECT_SCHEMA)

    for table_name in ("risks", "issues", "tasks"):
        op.drop_index(
            f"ix_{table_name}_tenant_project_updated",
            table_name=table_name,
            schema=PROJECT_SCHEMA,
        )
    for table_name in ("issues", "tasks"):
        op.drop_constraint(
            f"fk_{table_name}_tenant_workflow_stage",
            table_name,
            type_="foreignkey",
            schema=PROJECT_SCHEMA,
        )
        op.drop_constraint(
            f"fk_{table_name}_tenant_project_workflow",
            table_name,
            type_="foreignkey",
            schema=PROJECT_SCHEMA,
        )
        op.create_foreign_key(
            f"fk_{table_name}_tenant_stage",
            table_name,
            "stages",
            ["tenant_id", "stage_id"],
            ["tenant_id", "id"],
            source_schema=PROJECT_SCHEMA,
            referent_schema=PROJECT_SCHEMA,
            ondelete="RESTRICT",
        )

    for constraint_name, table_name in (
        ("ck_risks_closed_at_consistent", "risks"),
        ("ck_issues_stage_pair_consistent", "issues"),
        ("ck_issues_closed_at_consistent", "issues"),
        ("ck_tasks_stage_pair_consistent", "tasks"),
        ("ck_tasks_completion_consistent", "tasks"),
        ("ck_tasks_blocked_reason_consistent", "tasks"),
    ):
        op.drop_constraint(
            constraint_name,
            table_name,
            type_="check",
            schema=PROJECT_SCHEMA,
        )
    for table_name in ("risks", "issues", "tasks"):
        op.drop_constraint(
            f"ck_{table_name}_title_nonblank",
            table_name,
            type_="check",
            schema=PROJECT_SCHEMA,
        )

    op.drop_column("issues", "workflow_id", schema=PROJECT_SCHEMA)
    op.drop_column("tasks", "blocked_reason", schema=PROJECT_SCHEMA)
    op.drop_column("tasks", "workflow_id", schema=PROJECT_SCHEMA)
