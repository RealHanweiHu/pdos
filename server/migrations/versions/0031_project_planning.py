"""add cancelled Project status and Stage plan/actual dates

Revision ID: 0031_project_planning
Revises: 0030_phase_three_agents
Create Date: 2026-10-31 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031_project_planning"
down_revision: str | Sequence[str] | None = "0030_phase_three_agents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROJECT_SCHEMA = "cehub_project"
STATUS_WITH_CANCELLED = (
    "status IN ('draft', 'proposed', 'approved', 'active', 'on_hold', 'completed', "
    "'cancelled', 'archived')"
)
STATUS_WITHOUT_CANCELLED = (
    "status IN ('draft', 'proposed', 'approved', 'active', 'on_hold', 'completed', 'archived')"
)
PLANNED_DATE_ORDER = (
    "planned_end_date IS NULL OR planned_start_date IS NULL "
    "OR planned_end_date >= planned_start_date"
)


def _replace_project_status(expression: str) -> None:
    op.drop_constraint(
        op.f("ck_projects_status_allowed"), "projects", schema=PROJECT_SCHEMA, type_="check"
    )
    op.create_check_constraint(
        op.f("ck_projects_status_allowed"), "projects", expression, schema=PROJECT_SCHEMA
    )


def upgrade() -> None:
    _replace_project_status(STATUS_WITH_CANCELLED)
    op.add_column("stages", sa.Column("planned_start_date", sa.Date()), schema=PROJECT_SCHEMA)
    op.add_column("stages", sa.Column("planned_end_date", sa.Date()), schema=PROJECT_SCHEMA)
    op.add_column(
        "stages", sa.Column("entered_at", sa.DateTime(timezone=True)), schema=PROJECT_SCHEMA
    )
    op.add_column(
        "stages", sa.Column("exited_at", sa.DateTime(timezone=True)), schema=PROJECT_SCHEMA
    )
    op.create_check_constraint(
        op.f("ck_stages_planned_date_order"), "stages", PLANNED_DATE_ORDER, schema=PROJECT_SCHEMA
    )
    # Recover actual stage dates from the stage-change event history; the first stage of every
    # Project was entered when the Project was created. Imported Projects without history stay NULL.
    op.execute(
        """
        UPDATE cehub_project.stages AS stage
        SET entered_at = history.entered_at
        FROM (
            SELECT tenant_id, (payload->>'to_stage_id')::uuid AS stage_id,
                   max(timestamp) AS entered_at
            FROM cehub_event.events
            WHERE event_type = 'PROJECT_STAGE_CHANGED'
            GROUP BY tenant_id, (payload->>'to_stage_id')::uuid
        ) AS history
        WHERE stage.tenant_id = history.tenant_id AND stage.id = history.stage_id
        """
    )
    op.execute(
        """
        UPDATE cehub_project.stages AS stage
        SET exited_at = history.exited_at
        FROM (
            SELECT tenant_id, (payload->>'from_stage_id')::uuid AS stage_id,
                   max(timestamp) AS exited_at
            FROM cehub_event.events
            WHERE event_type = 'PROJECT_STAGE_CHANGED'
            GROUP BY tenant_id, (payload->>'from_stage_id')::uuid
        ) AS history
        WHERE stage.tenant_id = history.tenant_id AND stage.id = history.stage_id
        """
    )
    op.execute(
        """
        UPDATE cehub_project.stages AS stage
        SET entered_at = project.created_at
        FROM cehub_project.projects AS project
        WHERE stage.tenant_id = project.tenant_id
          AND stage.workflow_id = project.workflow_id
          AND stage.sequence = 1
          AND stage.entered_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $block$
        BEGIN
            IF EXISTS (SELECT 1 FROM cehub_project.projects WHERE status = 'cancelled') THEN
                RAISE EXCEPTION 'Cannot downgrade 0031 while cancelled Projects exist';
            END IF;
        END
        $block$
        """
    )
    op.drop_constraint(
        op.f("ck_stages_planned_date_order"), "stages", schema=PROJECT_SCHEMA, type_="check"
    )
    op.drop_column("stages", "exited_at", schema=PROJECT_SCHEMA)
    op.drop_column("stages", "entered_at", schema=PROJECT_SCHEMA)
    op.drop_column("stages", "planned_end_date", schema=PROJECT_SCHEMA)
    op.drop_column("stages", "planned_start_date", schema=PROJECT_SCHEMA)
    _replace_project_status(STATUS_WITHOUT_CANCELLED)
