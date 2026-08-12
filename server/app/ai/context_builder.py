"""Deterministic SQL-backed builder for immutable Agent run context."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import Connection, RowMapping, func, select

from app.ai.runtime_contract import AgentKey, EventReference, FrozenRunContext
from app.db.schema import tables


class RunContextIntegrityError(RuntimeError):
    """Raised when persisted run references cannot form a tenant-safe context."""


class RunContextBuilder:
    def __init__(self, *, default_daily_token_budget: int = 2_000_000) -> None:
        if not 1 <= default_daily_token_budget <= 1_000_000_000:
            raise ValueError("default daily token budget is invalid")
        self._default_daily_token_budget = default_daily_token_budget

    def build(
        self,
        connection: Connection,
        *,
        run: RowMapping,
        built_at: datetime,
    ) -> FrozenRunContext:
        now = built_at.astimezone(UTC)
        tenant_id = UUID(str(run["tenant_id"]))
        project_id = UUID(str(run["project_id"]))
        run_id = UUID(str(run["id"]))
        project = self._project(connection, tenant_id=tenant_id, project_id=project_id)
        events = self._events(
            connection,
            tenant_id=tenant_id,
            project_id=project_id,
            event_row_ids=[int(value) for value in run["event_row_ids"]],
        )
        if len(events) != int(run["event_count"]):
            raise RunContextIntegrityError("Agent run event references are incomplete")

        return FrozenRunContext(
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            agent_key=AgentKey(str(run["agent_key"])),
            built_at=now,
            window_started_at=run["window_started_at"],
            window_ended_at=run["window_ended_at"],
            trigger_events=tuple(
                EventReference(
                    id=int(event["id"]),
                    event_type=str(event["event_type"]),
                    entity=str(event["entity"]),
                    entity_id=event["entity_id"],
                    timestamp=event["timestamp"],
                )
                for event in events
            ),
            project=self._project_payload(connection, project=project),
            execution=self._execution_metrics(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                agent_key=AgentKey(str(run["agent_key"])),
                now=now,
            ),
        )

    @staticmethod
    def _project(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
    ) -> RowMapping:
        row = (
            connection.execute(
                select(tables.projects).where(
                    tables.projects.c.tenant_id == tenant_id,
                    tables.projects.c.id == project_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise RunContextIntegrityError("Agent run Project is outside the tenant scope")
        return row

    @staticmethod
    def _events(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        event_row_ids: list[int],
    ) -> list[RowMapping]:
        return list(
            connection.execute(
                select(tables.events)
                .where(
                    tables.events.c.tenant_id == tenant_id,
                    tables.events.c.project_id == project_id,
                    tables.events.c.id.in_(event_row_ids),
                )
                .order_by(tables.events.c.id)
            ).mappings()
        )

    @staticmethod
    def _project_payload(connection: Connection, *, project: RowMapping) -> dict[str, object]:
        current_stage: dict[str, object] = {
            "code": "unassigned",
            "name": "Unassigned",
            "sequence": 0,
        }
        if project["current_stage_id"] is not None:
            stage = (
                connection.execute(
                    select(tables.stages).where(
                        tables.stages.c.tenant_id == project["tenant_id"],
                        tables.stages.c.workflow_id == project["workflow_id"],
                        tables.stages.c.id == project["current_stage_id"],
                    )
                )
                .mappings()
                .one_or_none()
            )
            if stage is None:
                raise RunContextIntegrityError("Project current stage is incomplete")
            current_stage = {
                "code": str(stage["code"]),
                "name": str(stage["name"]),
                "sequence": int(stage["sequence"]),
            }
        return {
            "id": str(project["id"]),
            "code": str(project["code"]),
            "name": str(project["name"]),
            "status": str(project["status"]),
            "current_stage": current_stage,
        }

    def _execution_metrics(
        self,
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        agent_key: AgentKey,
        now: datetime,
    ) -> dict[str, object]:
        day_start = datetime.combine(now.date(), time.min, tzinfo=UTC)
        day_end = day_start + timedelta(days=1)
        seven_days_ago = now - timedelta(days=7)

        open_issue_count = connection.execute(
            select(func.count())
            .select_from(tables.issues)
            .where(
                tables.issues.c.tenant_id == tenant_id,
                tables.issues.c.project_id == project_id,
                tables.issues.c.status != "closed",
            )
        ).scalar_one()
        recent_issue_count = connection.execute(
            select(func.count())
            .select_from(tables.issues)
            .where(
                tables.issues.c.tenant_id == tenant_id,
                tables.issues.c.project_id == project_id,
                tables.issues.c.created_at >= seven_days_ago,
                tables.issues.c.created_at <= now,
            )
        ).scalar_one()
        open_risk_count = connection.execute(
            select(func.count())
            .select_from(tables.risks)
            .where(
                tables.risks.c.tenant_id == tenant_id,
                tables.risks.c.project_id == project_id,
                tables.risks.c.status != "closed",
            )
        ).scalar_one()
        overdue_task_count = connection.execute(
            select(func.count())
            .select_from(tables.tasks)
            .where(
                tables.tasks.c.tenant_id == tenant_id,
                tables.tasks.c.project_id == project_id,
                tables.tasks.c.due_date < now.date(),
                tables.tasks.c.status.not_in(("done", "skipped")),
            )
        ).scalar_one()
        next_gate_due_at = connection.execute(
            select(func.min(tables.gates.c.review_due_at)).where(
                tables.gates.c.tenant_id == tenant_id,
                tables.gates.c.project_id == project_id,
                tables.gates.c.status.in_(("preparing", "reviewing")),
                tables.gates.c.review_due_at.is_not(None),
            )
        ).scalar_one()
        stage_progress_percent = self._stage_progress(
            connection,
            tenant_id=tenant_id,
            project_id=project_id,
        )

        configured_budget = connection.execute(
            select(tables.tenant_model_settings.c.daily_token_budget).where(
                tables.tenant_model_settings.c.tenant_id == tenant_id
            )
        ).scalar_one_or_none()
        daily_budget = int(configured_budget or self._default_daily_token_budget)
        used_tokens = connection.execute(
            select(func.coalesce(func.sum(tables.model_invocations.c.total_tokens), 0)).where(
                tables.model_invocations.c.tenant_id == tenant_id,
                tables.model_invocations.c.created_at >= day_start,
                tables.model_invocations.c.created_at < day_end,
            )
        ).scalar_one()
        agent_runs_today = connection.execute(
            select(func.count())
            .select_from(tables.agent_runs)
            .where(
                tables.agent_runs.c.tenant_id == tenant_id,
                tables.agent_runs.c.agent_key == agent_key.value,
                tables.agent_runs.c.created_at >= day_start,
                tables.agent_runs.c.created_at < day_end,
            )
        ).scalar_one()

        return {
            "open_issue_count": int(open_issue_count),
            "issues_created_last_7_days": int(recent_issue_count),
            "open_risk_count": int(open_risk_count),
            "overdue_task_count": int(overdue_task_count),
            "stage_progress_percent": stage_progress_percent,
            "next_gate_due_in_days": (
                (next_gate_due_at.date() - now.date()).days
                if next_gate_due_at is not None
                else None
            ),
            "remaining_tokens_today": max(0, daily_budget - int(used_tokens)),
            "agent_runs_today": int(agent_runs_today),
        }

    @staticmethod
    def _stage_progress(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
    ) -> int:
        project = connection.execute(
            select(tables.projects.c.workflow_id, tables.projects.c.current_stage_id).where(
                tables.projects.c.tenant_id == tenant_id,
                tables.projects.c.id == project_id,
            )
        ).one_or_none()
        if project is None or project.current_stage_id is None:
            return 0
        current_sequence = connection.execute(
            select(tables.stages.c.sequence).where(
                tables.stages.c.tenant_id == tenant_id,
                tables.stages.c.workflow_id == project.workflow_id,
                tables.stages.c.id == project.current_stage_id,
            )
        ).scalar_one_or_none()
        max_sequence = connection.execute(
            select(func.max(tables.stages.c.sequence)).where(
                tables.stages.c.tenant_id == tenant_id,
                tables.stages.c.workflow_id == project.workflow_id,
            )
        ).scalar_one()
        if current_sequence is None or max_sequence in (None, 0):
            return 0
        return round(int(current_sequence) * 100 / int(max_sequence))
