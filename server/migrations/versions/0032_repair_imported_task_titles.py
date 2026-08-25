"""repair imported CEHub task titles from the checked-in manifest

Revision ID: 0032_repair_task_titles
Revises: 0031_user_account_management
Create Date: 2026-08-21 02:30:00.000000
"""

from collections.abc import Iterator, Sequence

import sqlalchemy as sa
from alembic import op

from app.domain.deliverable_checks import load_manifest

revision: str = "0032_repair_task_titles"
down_revision: str | Sequence[str] | None = "0031_user_account_management"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _task_titles() -> Iterator[tuple[str, str, str, str]]:
    titles: dict[tuple[str, str, str], str] = {}
    for item in load_manifest()["items"]:
        for binding in item["bindings"]:
            key = (
                str(binding["projectType"]).lower(),
                str(binding["phaseId"]),
                str(binding["taskId"]),
            )
            title = str(binding["taskName"]).strip()
            existing = titles.setdefault(key, title)
            if existing != title:
                raise ValueError(f"ambiguous CEHub task title binding: {':'.join(key)}")
    for (project_type, phase_id, task_id), title in sorted(titles.items()):
        if project_type in {"npd", "obt"}:
            yield project_type, phase_id, task_id, title


def _repair(*, reverse: bool) -> None:
    connection = op.get_bind()
    statement = sa.text(
        """
        UPDATE cehub_project.tasks AS task
           SET title = :replacement
          FROM cehub_project.projects AS project,
               cehub_project.workflows AS workflow,
               cehub_project.stages AS stage,
               cehub_audit.migration_mappings AS mapping
         WHERE task.tenant_id = project.tenant_id
           AND task.project_id = project.id
           AND task.stage_id = stage.id
           AND workflow.tenant_id = project.tenant_id
           AND workflow.id = project.workflow_id
           AND stage.tenant_id = project.tenant_id
           AND stage.workflow_id = project.workflow_id
           AND mapping.tenant_id = project.tenant_id
           AND mapping.entity_type = 'task'
           AND mapping.source_system = 'cehub-v3'
           AND mapping.target_id = task.id
           AND workflow.code LIKE :workflow_prefix
           AND stage.code = :phase_id
           AND task.title = :expected
        """
    )
    for project_type, phase_id, task_id, title in _task_titles():
        connection.execute(
            statement,
            {
                "replacement": task_id if reverse else title,
                "workflow_prefix": f"{project_type}-cehub-%",
                "phase_id": phase_id,
                "expected": title if reverse else task_id,
            },
        )


def upgrade() -> None:
    _repair(reverse=False)


def downgrade() -> None:
    _repair(reverse=True)
