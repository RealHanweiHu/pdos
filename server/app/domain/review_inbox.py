"""Review Inbox digest: one queue for everything awaiting a human (vNext V1-A10).

Aggregates the three draft sources of the D32 model — hard-gate findings
pending review, free-zone rule-generated risk candidates, and confirm-zone
test-report import batches — grouped by project, with findings ordered by
capability quality score (acceptance rate) then confidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Engine, Select, func, select

from app.ai.quality import FindingQualityService
from app.ai.rollout_guard import employee_finding_visibility
from app.db.schema import tables


@dataclass(frozen=True)
class InboxItem:
    kind: str  # 'finding' | 'risk_candidate' | 'import_batch'
    id: UUID
    title: str
    created_at: datetime
    agent_key: str | None = None
    finding_type: str | None = None
    confidence_basis_points: int | None = None
    quality_acceptance_basis_points: int | None = None
    href: str = ""


@dataclass(frozen=True)
class InboxGroup:
    project_id: UUID
    project_name: str
    items: tuple[InboxItem, ...]


@dataclass(frozen=True)
class InboxDigest:
    groups: tuple[InboxGroup, ...]
    finding_count: int
    risk_candidate_count: int
    import_batch_count: int
    archived_count: int


class ReviewInboxService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def digest(
        self,
        *,
        tenant_id: UUID,
        member_user_id: UUID | None = None,
    ) -> InboxDigest:
        quality = FindingQualityService(self._engine).snapshot(tenant_id=tenant_id)
        acceptance = {
            (control.agent_key, control.finding_type): control.acceptance_rate_basis_points
            for control in quality.controls
        }

        def member_scoped(
            statement: Select[Any], project_column: ColumnElement[UUID]
        ) -> Select[Any]:
            if member_user_id is None:
                return statement
            return statement.join(
                tables.project_members,
                (tables.project_members.c.tenant_id == tenant_id)
                & (tables.project_members.c.project_id == project_column),
            ).where(tables.project_members.c.user_id == member_user_id)

        with self._engine.connect() as connection:
            finding_rows = connection.execute(
                member_scoped(
                    select(
                        tables.findings.c.id,
                        tables.findings.c.project_id,
                        tables.projects.c.name.label("project_name"),
                        tables.findings.c.agent_key,
                        tables.findings.c.finding_type,
                        tables.findings.c.title,
                        tables.findings.c.confidence_basis_points,
                        tables.findings.c.created_at,
                    ).join(
                        tables.projects,
                        (tables.projects.c.tenant_id == tables.findings.c.tenant_id)
                        & (tables.projects.c.id == tables.findings.c.project_id),
                    ),
                    tables.findings.c.project_id,
                ).where(
                    tables.findings.c.tenant_id == tenant_id,
                    tables.findings.c.status == "pending_review",
                    employee_finding_visibility(),
                )
            ).all()
            candidate_rows = connection.execute(
                member_scoped(
                    select(
                        tables.risks.c.id,
                        tables.risks.c.project_id,
                        tables.projects.c.name.label("project_name"),
                        tables.risks.c.title,
                        tables.risks.c.created_at,
                    ).join(
                        tables.projects,
                        (tables.projects.c.tenant_id == tables.risks.c.tenant_id)
                        & (tables.projects.c.id == tables.risks.c.project_id),
                    ),
                    tables.risks.c.project_id,
                ).where(
                    tables.risks.c.tenant_id == tenant_id,
                    tables.risks.c.draft_state == "draft",
                )
            ).all()
            batch_rows = connection.execute(
                member_scoped(
                    select(
                        tables.test_report_import_batches.c.id,
                        tables.test_report_import_batches.c.project_id,
                        tables.projects.c.name.label("project_name"),
                        tables.test_report_import_batches.c.created_at,
                    ).join(
                        tables.projects,
                        (
                            tables.projects.c.tenant_id
                            == tables.test_report_import_batches.c.tenant_id
                        )
                        & (tables.projects.c.id == tables.test_report_import_batches.c.project_id),
                    ),
                    tables.test_report_import_batches.c.project_id,
                ).where(
                    tables.test_report_import_batches.c.tenant_id == tenant_id,
                    tables.test_report_import_batches.c.status == "parsed",
                )
            ).all()
            archived_count = connection.execute(
                member_scoped(
                    select(func.count(tables.findings.c.id)),
                    tables.findings.c.project_id,
                ).where(
                    tables.findings.c.tenant_id == tenant_id,
                    tables.findings.c.status == "archived",
                    employee_finding_visibility(),
                )
            ).scalar_one()

        projects: dict[UUID, tuple[str, list[InboxItem]]] = {}

        def bucket(project_id: UUID, project_name: str) -> list[InboxItem]:
            return projects.setdefault(project_id, (project_name, []))[1]

        finding_items = sorted(
            finding_rows,
            key=lambda row: (
                -(acceptance.get((row.agent_key, row.finding_type)) or -1),
                -row.confidence_basis_points,
                row.created_at,
            ),
        )
        for row in finding_items:
            bucket(row.project_id, row.project_name).append(
                InboxItem(
                    kind="finding",
                    id=row.id,
                    title=row.title,
                    created_at=row.created_at,
                    agent_key=row.agent_key,
                    finding_type=row.finding_type,
                    confidence_basis_points=row.confidence_basis_points,
                    quality_acceptance_basis_points=acceptance.get(
                        (row.agent_key, row.finding_type)
                    ),
                    href=f"/ai-review?finding={row.id}",
                )
            )
        for row in sorted(candidate_rows, key=lambda row: row.created_at):
            bucket(row.project_id, row.project_name).append(
                InboxItem(
                    kind="risk_candidate",
                    id=row.id,
                    title=row.title,
                    created_at=row.created_at,
                    href=f"/projects?project={row.project_id}&tab=work-items",
                )
            )
        for row in sorted(batch_rows, key=lambda row: row.created_at):
            bucket(row.project_id, row.project_name).append(
                InboxItem(
                    kind="import_batch",
                    id=row.id,
                    title="测试报告导入待确认",
                    created_at=row.created_at,
                    href=f"/projects?project={row.project_id}&tab=quality",
                )
            )

        groups = tuple(
            InboxGroup(project_id=project_id, project_name=name, items=tuple(items))
            for project_id, (name, items) in sorted(projects.items(), key=lambda entry: entry[1][0])
        )
        return InboxDigest(
            groups=groups,
            finding_count=len(finding_rows),
            risk_candidate_count=len(candidate_rows),
            import_batch_count=len(batch_rows),
            archived_count=int(archived_count),
        )
