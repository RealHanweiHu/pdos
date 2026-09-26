"""Read-only dashboard risk ranking and complete project summaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Engine, func, select

from app.auth.roles import Role
from app.db.schema import tables


@dataclass(frozen=True)
class DashboardRiskProject:
    id: UUID
    code: str
    name: str


@dataclass(frozen=True)
class DashboardRisk:
    id: UUID
    project_id: UUID
    title: str
    status: str
    likelihood: int
    impact: int
    score: int
    updated_at: datetime
    project: DashboardRiskProject


@dataclass(frozen=True)
class DashboardProjectRiskSummary:
    project_id: UUID
    open_risk_count: int
    max_score: int


@dataclass(frozen=True)
class DashboardRiskSnapshot:
    items: tuple[DashboardRisk, ...]
    total: int
    projects: tuple[DashboardProjectRiskSummary, ...]


class DashboardRiskService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def load(self, *, tenant_id: UUID, user_id: UUID, role: Role) -> DashboardRiskSnapshot:
        projects = tables.projects
        risks = tables.risks
        visible_statement = select(
            projects.c.id,
            projects.c.tenant_id,
            projects.c.code,
            projects.c.name,
            projects.c.updated_at,
        ).where(projects.c.tenant_id == tenant_id)
        # Keep the same direct-membership scope as ProjectService.list.
        if role not in (Role.OWNER, Role.ADMIN):
            visible_statement = visible_statement.where(
                projects.c.id.in_(
                    select(tables.project_members.c.project_id).where(
                        tables.project_members.c.tenant_id == tenant_id,
                        tables.project_members.c.user_id == user_id,
                    )
                )
            )
        visible = visible_statement.cte("visible_projects")
        open_project_risks = (
            (risks.c.tenant_id == visible.c.tenant_id)
            & (risks.c.project_id == visible.c.id)
            & (risks.c.draft_state == "confirmed")
            & (risks.c.status != "closed")
        )
        score = risks.c.likelihood * risks.c.impact
        top_statement = (
            select(
                risks.c.id,
                risks.c.project_id,
                risks.c.title,
                risks.c.status,
                risks.c.likelihood,
                risks.c.impact,
                score.label("score"),
                risks.c.updated_at,
                visible.c.code.label("project_code"),
                visible.c.name.label("project_name"),
            )
            .select_from(visible.join(risks, open_project_risks))
            .order_by(score.desc(), risks.c.updated_at.desc(), risks.c.id.desc())
            .limit(8)
        )
        summary_statement = (
            select(
                visible.c.id.label("project_id"),
                func.count(risks.c.id).label("open_risk_count"),
                func.coalesce(func.max(score), 0).label("max_score"),
            )
            .select_from(visible.outerjoin(risks, open_project_risks))
            .group_by(visible.c.id, visible.c.updated_at)
            .order_by(visible.c.updated_at.desc(), visible.c.id.desc())
        )
        # Both SELECTs share a snapshot: concurrent edits cannot make the top
        # ranking disagree with the complete counts returned alongside it.
        with self._engine.connect() as connection:
            connection = connection.execution_options(isolation_level="REPEATABLE READ")
            with connection.begin():
                top_rows = connection.execute(top_statement).mappings().all()
                summary_rows = connection.execute(summary_statement).mappings().all()
        items = tuple(
            DashboardRisk(
                id=row["id"],
                project_id=row["project_id"],
                title=row["title"],
                status=row["status"],
                likelihood=row["likelihood"],
                impact=row["impact"],
                score=row["score"],
                updated_at=row["updated_at"],
                project=DashboardRiskProject(
                    id=row["project_id"], code=row["project_code"], name=row["project_name"]
                ),
            )
            for row in top_rows
        )
        summaries = tuple(
            DashboardProjectRiskSummary(
                project_id=row["project_id"],
                open_risk_count=row["open_risk_count"],
                max_score=row["max_score"],
            )
            for row in summary_rows
        )
        return DashboardRiskSnapshot(
            items=items,
            total=sum(project.open_risk_count for project in summaries),
            projects=summaries,
        )
