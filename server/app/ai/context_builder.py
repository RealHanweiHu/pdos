"""Deterministic SQL-backed builder for immutable Agent run context."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, RowMapping, func, select, text

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
        run: RowMapping | dict[str, Any],
        built_at: datetime,
        projection_only: bool = False,
    ) -> FrozenRunContext:
        now = built_at.astimezone(UTC)
        tenant_id = UUID(str(run["tenant_id"]))
        project_id = UUID(str(run["project_id"]))
        run_id = UUID(str(run["id"]))
        event_row_ids = [int(value) for value in run["event_row_ids"]]
        if projection_only:
            project = self._project_projection(connection, project_id=project_id)
            events = self._event_projection(connection, event_row_ids=event_row_ids)
        else:
            project = self._project(connection, tenant_id=tenant_id, project_id=project_id)
            events = self._events(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                event_row_ids=event_row_ids,
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
            project=(
                self._project_projection_payload(project)
                if projection_only
                else self._project_payload(connection, project=project)
            ),
            execution=(
                self._projection_execution_metrics(
                    connection,
                    agent_key=AgentKey(str(run["agent_key"])),
                    now=now,
                )
                if projection_only
                else self._execution_metrics(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    agent_key=AgentKey(str(run["agent_key"])),
                    now=now,
                )
            ),
        )

    @staticmethod
    def _project_projection(connection: Connection, *, project_id: UUID) -> RowMapping:
        row = (
            connection.execute(
                text("SELECT * FROM cehub_ai.agent_project_projection WHERE id = :project_id"),
                {"project_id": project_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise RunContextIntegrityError("Agent run Project projection is unavailable")
        return row

    @staticmethod
    def _event_projection(
        connection: Connection,
        *,
        event_row_ids: list[int],
    ) -> list[RowMapping]:
        return list(
            connection.execute(
                text(
                    "SELECT * FROM cehub_ai.agent_event_projection "
                    "WHERE id = ANY(:event_row_ids) ORDER BY id"
                ),
                {"event_row_ids": event_row_ids},
            ).mappings()
        )

    @staticmethod
    def _project_projection_payload(project: RowMapping) -> dict[str, object]:
        current_stage = {
            "code": str(project["current_stage_code"] or "unassigned"),
            "name": str(project["current_stage_name"] or "Unassigned"),
            "sequence": int(project["current_stage_sequence"] or 0),
        }
        return {
            "id": str(project["id"]),
            "code": str(project["code"]),
            "name": str(project["name"]),
            "status": str(project["status"]),
            "current_stage": current_stage,
        }

    def _projection_execution_metrics(
        self,
        connection: Connection,
        *,
        agent_key: AgentKey,
        now: datetime,
    ) -> dict[str, object]:
        seven_days_ago = now - timedelta(days=7)
        day_start = datetime.combine(now.date(), time.min, tzinfo=UTC)
        day_end = day_start + timedelta(days=1)
        issues = connection.execute(
            text(
                "SELECT count(*) FILTER (WHERE status <> 'closed') AS open_count, "
                "count(*) FILTER (WHERE created_at >= :seven_days_ago "
                "AND created_at <= :now) AS recent_count "
                "FROM cehub_ai.agent_issue_projection"
            ),
            {"seven_days_ago": seven_days_ago, "now": now},
        ).one()
        open_risk_count = connection.execute(
            text("SELECT count(*) FROM cehub_ai.agent_risk_projection WHERE status <> 'closed'")
        ).scalar_one()
        overdue_task_count = connection.execute(
            text(
                "SELECT count(*) FROM cehub_ai.agent_task_projection "
                "WHERE due_date < :today AND status NOT IN ('done', 'skipped')"
            ),
            {"today": now.date()},
        ).scalar_one()
        next_gate_due_at = connection.execute(
            text(
                "SELECT min(review_due_at) FROM cehub_ai.agent_gate_projection "
                "WHERE status IN ('preparing', 'reviewing') AND review_due_at IS NOT NULL"
            )
        ).scalar_one()
        project = (
            connection.execute(text("SELECT * FROM cehub_ai.agent_project_projection"))
            .mappings()
            .one()
        )
        current_sequence = int(project["current_stage_sequence"] or 0)
        max_sequence = int(project["max_stage_sequence"] or 0)
        configured_budget = connection.execute(
            text("SELECT daily_token_budget FROM cehub_ai.agent_model_settings_projection")
        ).scalar_one_or_none()
        daily_budget = int(configured_budget or self._default_daily_token_budget)
        used_tokens = connection.execute(
            text(
                "SELECT coalesce(sum(total_tokens), 0) "
                "FROM cehub_ai.agent_model_usage_projection "
                "WHERE created_at >= :day_start AND created_at < :day_end"
            ),
            {"day_start": day_start, "day_end": day_end},
        ).scalar_one()
        agent_runs_today = connection.execute(
            text(
                "SELECT count(*) FROM cehub_ai.agent_run_usage_projection "
                "WHERE agent_key = :agent_key AND created_at >= :day_start "
                "AND created_at < :day_end"
            ),
            {"agent_key": agent_key.value, "day_start": day_start, "day_end": day_end},
        ).scalar_one()
        return {
            "open_issue_count": int(issues.open_count),
            "issues_created_last_7_days": int(issues.recent_count),
            "open_risk_count": int(open_risk_count),
            "overdue_task_count": int(overdue_task_count),
            "stage_progress_percent": (
                round(current_sequence * 100 / max_sequence) if max_sequence else 0
            ),
            "next_gate_due_in_days": (
                (next_gate_due_at.date() - now.date()).days
                if next_gate_due_at is not None
                else None
            ),
            "remaining_tokens_today": max(0, daily_budget - int(used_tokens)),
            "agent_runs_today": int(agent_runs_today),
        }

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
