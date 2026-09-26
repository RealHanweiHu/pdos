"""Deterministic rule-based risk candidates (vNext V1-A6, I7 step one).

No model calls: every candidate derives from source-object state via frozen
rules. Idempotency comes from a per-tenant unique origin key; when a source
condition recovers, the draft is cleared (kept for audit) instead of deleted,
and reactivated if the condition returns.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select

from app.db.schema import tables
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.risks import (
    RiskNotFoundError,
    RiskRecord,
    RiskVersionConflictError,
    _record_from_row,
    _risk_statement,
)
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

OPEN_TASK_STATUSES = ("todo", "in_progress", "blocked", "pending_approval")

_PRIORITY_IMPACT = {"low": 2, "medium": 3, "high": 4, "critical": 5}
_TEST_SEVERITY_IMPACT = {"minor": 3, "major": 4, "critical": 5}


@dataclass(frozen=True)
class CandidateSpec:
    origin_key: str
    rule_key: str
    source_entity: str
    source_entity_id: UUID
    title: str
    description: str
    likelihood: int
    impact: int


@dataclass(frozen=True)
class ScanResult:
    created: int
    reactivated: int
    cleared: int
    active_candidates: tuple[RiskRecord, ...]


def _active_specs(
    connection: Connection, *, tenant_id: UUID, project_id: UUID, today: date
) -> list[CandidateSpec]:
    specs: list[CandidateSpec] = []
    overdue_tasks = connection.execute(
        select(tables.tasks.c.id, tables.tasks.c.title, tables.tasks.c.priority).where(
            tables.tasks.c.tenant_id == tenant_id,
            tables.tasks.c.project_id == project_id,
            tables.tasks.c.status.in_(OPEN_TASK_STATUSES),
            tables.tasks.c.due_date < today,
        )
    ).all()
    for row in overdue_tasks:
        specs.append(
            CandidateSpec(
                origin_key=f"task_overdue:{row.id}",
                rule_key="task_overdue",
                source_entity="task",
                source_entity_id=row.id,
                title=f"任务逾期：{row.title}"[:512],
                description="来源任务已超过截止日期且未完成，可能拖累下游计划。",
                likelihood=3,
                impact=_PRIORITY_IMPACT.get(row.priority, 3),
            )
        )
    overdue_issues = connection.execute(
        select(tables.issues.c.id, tables.issues.c.title, tables.issues.c.severity).where(
            tables.issues.c.tenant_id == tenant_id,
            tables.issues.c.project_id == project_id,
            tables.issues.c.status != "closed",
            tables.issues.c.target_date < today,
        )
    ).all()
    for row in overdue_issues:
        specs.append(
            CandidateSpec(
                origin_key=f"issue_overdue:{row.id}",
                rule_key="issue_overdue",
                source_entity="issue",
                source_entity_id=row.id,
                title=f"问题逾期：{row.title}"[:512],
                description="来源问题已超过目标日期仍未关闭。",
                likelihood=3,
                impact=_PRIORITY_IMPACT.get(row.severity, 3),
            )
        )
    failed_cases = connection.execute(
        select(
            tables.test_cases.c.id, tables.test_cases.c.title, tables.test_cases.c.severity
        ).where(
            tables.test_cases.c.tenant_id == tenant_id,
            tables.test_cases.c.project_id == project_id,
            tables.test_cases.c.status == "failed",
        )
    ).all()
    for row in failed_cases:
        specs.append(
            CandidateSpec(
                origin_key=f"test_failed:{row.id}",
                rule_key="test_failed",
                source_entity="test_case",
                source_entity_id=row.id,
                title=f"测试失败：{row.title}"[:512],
                description="来源测试用例处于失败状态，未见通过或豁免。",
                likelihood=4,
                impact=_TEST_SEVERITY_IMPACT.get(row.severity, 4),
            )
        )
    return specs


class RiskCandidateService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list_candidates(self, *, tenant_id: UUID, project_id: UUID) -> list[RiskRecord]:
        with self._engine.connect() as connection:
            return [
                _record_from_row(row)
                for row in connection.execute(
                    _risk_statement()
                    .where(
                        tables.risks.c.tenant_id == tenant_id,
                        tables.risks.c.project_id == project_id,
                        tables.risks.c.draft_state == "draft",
                    )
                    .order_by(tables.risks.c.created_at.asc(), tables.risks.c.id.asc())
                ).mappings()
            ]

    def list_visible_candidates(
        self, *, tenant_id: UUID, member_user_id: UUID | None
    ) -> list[RiskRecord]:
        """Read the Review Inbox scope without a query for each visible project."""
        statement = (
            _risk_statement()
            .join(
                tables.projects,
                (tables.projects.c.tenant_id == tables.risks.c.tenant_id)
                & (tables.projects.c.id == tables.risks.c.project_id),
            )
            .where(
                tables.risks.c.tenant_id == tenant_id,
                tables.risks.c.draft_state == "draft",
            )
        )
        # Match ProjectService.list and ReviewInboxService.digest exactly:
        # only Owner/Admin receive None; other internal roles need direct membership.
        if member_user_id is not None:
            statement = statement.where(
                tables.risks.c.project_id.in_(
                    select(tables.project_members.c.project_id).where(
                        tables.project_members.c.tenant_id == tenant_id,
                        tables.project_members.c.user_id == member_user_id,
                    )
                )
            )
        statement = statement.order_by(tables.risks.c.created_at.asc(), tables.risks.c.id.asc())
        with self._engine.connect() as connection:
            return [_record_from_row(row) for row in connection.execute(statement).mappings()]

    def scan(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID | None,
        project_id: UUID,
        today: date | None = None,
        automatic: bool = False,
    ) -> ScanResult:
        occurred_at = datetime.now(UTC)
        effective_today = today or occurred_at.date()
        created = reactivated = cleared = 0
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise RiskNotFoundError
            if (
                automatic
                and connection.execute(
                    select(tables.projects.c.id)
                    .join(tables.tenants, tables.tenants.c.id == tables.projects.c.tenant_id)
                    .where(
                        tables.projects.c.tenant_id == tenant_id,
                        tables.projects.c.id == project_id,
                        tables.projects.c.status != "archived",
                        tables.tenants.c.status == "active",
                    )
                ).scalar_one_or_none()
                is None
            ):
                return ScanResult(created=0, reactivated=0, cleared=0, active_candidates=())
            writer = EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            )
            specs = _active_specs(
                connection, tenant_id=tenant_id, project_id=project_id, today=effective_today
            )
            active_origins = {spec.origin_key for spec in specs}
            existing_rows = connection.execute(
                select(
                    tables.risks.c.id,
                    tables.risks.c.origin_key,
                    tables.risks.c.draft_state,
                    tables.risks.c.dismissed_at,
                    tables.risks.c.likelihood,
                    tables.risks.c.impact,
                    tables.risks.c.title,
                    tables.risks.c.description,
                ).where(
                    tables.risks.c.tenant_id == tenant_id,
                    tables.risks.c.project_id == project_id,
                    tables.risks.c.origin_key.is_not(None),
                )
            ).all()
            existing = {row.origin_key: row for row in existing_rows}

            for spec in specs:
                row = existing.get(spec.origin_key)
                if row is None:
                    risk_id = uuid4()
                    connection.execute(
                        tables.risks.insert(),
                        {
                            "id": risk_id,
                            "tenant_id": tenant_id,
                            "project_id": project_id,
                            "title": spec.title,
                            "description": spec.description,
                            "likelihood": spec.likelihood,
                            "impact": spec.impact,
                            "draft_state": "draft",
                            "origin_key": spec.origin_key,
                            "rule_key": spec.rule_key,
                            "source_entity": spec.source_entity,
                            "source_entity_id": spec.source_entity_id,
                            "created_at": occurred_at,
                            "updated_at": occurred_at,
                        },
                    )
                    writer.record(
                        EventDraft(
                            event_id=f"risk:{risk_id}:candidate:created",
                            event_type="RISK_CREATED",
                            source="risk_service",
                            entity_id=risk_id,
                            payload={
                                "risk_id": str(risk_id),
                                "score": spec.likelihood * spec.impact,
                                "status": "open",
                            },
                            occurred_at=occurred_at,
                        ),
                        AuditDraft(
                            action="risk.candidate_create",
                            after_snapshot={
                                "origin_key": spec.origin_key,
                                "rule_key": spec.rule_key,
                                "title": spec.title,
                                "draft_state": "draft",
                            },
                        ),
                    )
                    created += 1
                elif (row.draft_state == "cleared" and row.dismissed_at is None) or (
                    row.draft_state == "draft"
                    and (row.title, row.description, row.likelihood, row.impact)
                    != (spec.title, spec.description, spec.likelihood, spec.impact)
                ):
                    refreshed = row.draft_state == "draft"
                    connection.execute(
                        tables.risks.update()
                        .where(
                            tables.risks.c.tenant_id == tenant_id,
                            tables.risks.c.id == row.id,
                        )
                        .values(
                            draft_state="draft",
                            title=spec.title,
                            description=spec.description,
                            likelihood=spec.likelihood,
                            impact=spec.impact,
                            updated_at=occurred_at,
                        )
                    )
                    writer.record(
                        EventDraft(
                            event_id=f"risk:{row.id}:candidate:refreshed:{uuid4()}",
                            event_type="RISK_UPDATED",
                            source="risk_service",
                            entity_id=row.id,
                            payload={
                                "changed_fields": [
                                    "draft_state",
                                    "title",
                                    "description",
                                    "likelihood",
                                    "impact",
                                ],
                                "status": "open",
                                "score": spec.likelihood * spec.impact,
                            },
                            occurred_at=occurred_at,
                        ),
                        AuditDraft(
                            action="risk.candidate_refresh"
                            if refreshed
                            else "risk.candidate_reactivate",
                            before_snapshot={
                                "draft_state": row.draft_state,
                                "title": row.title,
                                "description": row.description,
                                "likelihood": row.likelihood,
                                "impact": row.impact,
                            },
                            after_snapshot={
                                "draft_state": "draft",
                                "origin_key": spec.origin_key,
                                "title": spec.title,
                                "description": spec.description,
                                "likelihood": spec.likelihood,
                                "impact": spec.impact,
                            },
                        ),
                    )
                    reactivated += int(not refreshed)

            for origin_key, row in existing.items():
                if (
                    origin_key not in active_origins
                    and row.draft_state == "cleared"
                    and row.dismissed_at is not None
                ):
                    connection.execute(
                        tables.risks.update()
                        .where(
                            tables.risks.c.tenant_id == tenant_id,
                            tables.risks.c.id == row.id,
                        )
                        .values(dismissed_at=None, updated_at=occurred_at)
                    )
                if origin_key not in active_origins and row.draft_state == "draft":
                    connection.execute(
                        tables.risks.update()
                        .where(
                            tables.risks.c.tenant_id == tenant_id,
                            tables.risks.c.id == row.id,
                        )
                        .values(draft_state="cleared", updated_at=occurred_at)
                    )
                    writer.record(
                        EventDraft(
                            event_id=f"risk:{row.id}:candidate:cleared:{uuid4()}",
                            event_type="RISK_UPDATED",
                            source="risk_service",
                            entity_id=row.id,
                            payload={
                                "changed_fields": ["draft_state"],
                                "status": "open",
                                "score": row.likelihood * row.impact,
                            },
                            occurred_at=occurred_at,
                        ),
                        AuditDraft(
                            action="risk.candidate_clear",
                            before_snapshot={"draft_state": "draft", "origin_key": origin_key},
                            after_snapshot={"draft_state": "cleared"},
                        ),
                    )
                    cleared += 1

        return ScanResult(
            created=created,
            reactivated=reactivated,
            cleared=cleared,
            active_candidates=tuple(
                self.list_candidates(tenant_id=tenant_id, project_id=project_id)
            ),
        )

    def confirm(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        risk_id: UUID,
        shared_connection: Connection | None = None,
        expected_updated_at: datetime | None = None,
    ) -> RiskRecord:
        from app.domain.risks import RiskNotConfirmedError

        occurred_at = datetime.now(UTC)
        with (
            nullcontext(shared_connection)
            if shared_connection is not None
            else self._engine.begin()
        ) as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise RiskNotFoundError
            row = (
                connection.execute(
                    _risk_statement().where(
                        tables.risks.c.tenant_id == tenant_id,
                        tables.risks.c.project_id == project_id,
                        tables.risks.c.id == risk_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise RiskNotFoundError
            before = _record_from_row(row)
            if expected_updated_at is not None and before.updated_at != expected_updated_at:
                raise RiskVersionConflictError
            if before.draft_state != "draft":
                raise RiskNotConfirmedError
            connection.execute(
                tables.risks.update()
                .where(tables.risks.c.tenant_id == tenant_id, tables.risks.c.id == risk_id)
                .values(draft_state="confirmed", updated_at=occurred_at)
            )
            after_row = (
                connection.execute(
                    _risk_statement().where(
                        tables.risks.c.tenant_id == tenant_id,
                        tables.risks.c.id == risk_id,
                    )
                )
                .mappings()
                .one()
            )
            after = _record_from_row(after_row)
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"risk:{risk_id}:candidate:confirmed:{uuid4()}",
                    event_type="RISK_UPDATED",
                    source="risk_service",
                    entity_id=risk_id,
                    payload={
                        "changed_fields": ["draft_state"],
                        "status": after.status,
                        "score": after.score,
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="risk.candidate_confirm",
                    before_snapshot={"draft_state": "draft", "origin_key": before.origin_key},
                    after_snapshot={"draft_state": "confirmed"},
                ),
            )
            return after

    def confirm_batch(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        risk_ids: tuple[UUID, ...],
    ) -> dict[str, list[UUID]]:
        """Single-action batch confirm (D32 confirm zone); idempotent per id."""
        from app.domain.risks import RiskNotConfirmedError

        outcome: dict[str, list[UUID]] = {"confirmed": [], "already": [], "not_found": []}
        for risk_id in risk_ids:
            try:
                self.confirm(
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    project_id=project_id,
                    risk_id=risk_id,
                )
                outcome["confirmed"].append(risk_id)
            except RiskNotConfirmedError:
                outcome["already"].append(risk_id)
            except RiskNotFoundError:
                outcome["not_found"].append(risk_id)
        return outcome

    def unconfirm(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        risk_id: UUID,
        expected_updated_at: datetime | None = None,
    ) -> RiskRecord:
        """Undo a confirm (D32: confirm-zone actions stay reversible with audit)."""
        from app.domain.risks import RiskNotConfirmedError

        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise RiskNotFoundError
            row = (
                connection.execute(
                    _risk_statement().where(
                        tables.risks.c.tenant_id == tenant_id,
                        tables.risks.c.project_id == project_id,
                        tables.risks.c.id == risk_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise RiskNotFoundError
            before = _record_from_row(row)
            if expected_updated_at is not None and before.updated_at != expected_updated_at:
                raise RiskVersionConflictError
            if (
                before.draft_state != "confirmed"
                or before.origin_key is None
                or before.status != "open"
            ):
                raise RiskNotConfirmedError
            from app.domain.risk_references import require_unreferenced

            require_unreferenced(connection, tenant_id, project_id, risk_id)
            connection.execute(
                tables.risks.update()
                .where(tables.risks.c.tenant_id == tenant_id, tables.risks.c.id == risk_id)
                .values(draft_state="draft", updated_at=occurred_at)
            )
            after_row = (
                connection.execute(
                    _risk_statement().where(
                        tables.risks.c.tenant_id == tenant_id,
                        tables.risks.c.id == risk_id,
                    )
                )
                .mappings()
                .one()
            )
            after = _record_from_row(after_row)
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"risk:{risk_id}:candidate:unconfirmed:{uuid4()}",
                    event_type="RISK_UPDATED",
                    source="risk_service",
                    entity_id=risk_id,
                    payload={
                        "changed_fields": ["draft_state"],
                        "status": after.status,
                        "score": after.score,
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="risk.candidate_unconfirm",
                    before_snapshot={"draft_state": "confirmed", "origin_key": before.origin_key},
                    after_snapshot={"draft_state": "draft"},
                ),
            )
            return after

    def dismiss(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        risk_id: UUID,
    ) -> RiskRecord:
        """Free-zone one-click ignore (D32): a dismissed draft stays hidden
        until its source condition recovers; a later re-occurrence resurfaces it."""
        from app.domain.risks import RiskNotConfirmedError

        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise RiskNotFoundError
            row = (
                connection.execute(
                    _risk_statement().where(
                        tables.risks.c.tenant_id == tenant_id,
                        tables.risks.c.project_id == project_id,
                        tables.risks.c.id == risk_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise RiskNotFoundError
            before = _record_from_row(row)
            if before.draft_state != "draft":
                raise RiskNotConfirmedError
            connection.execute(
                tables.risks.update()
                .where(tables.risks.c.tenant_id == tenant_id, tables.risks.c.id == risk_id)
                .values(draft_state="cleared", dismissed_at=occurred_at, updated_at=occurred_at)
            )
            after_row = (
                connection.execute(
                    _risk_statement().where(
                        tables.risks.c.tenant_id == tenant_id,
                        tables.risks.c.id == risk_id,
                    )
                )
                .mappings()
                .one()
            )
            after = _record_from_row(after_row)
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"risk:{risk_id}:candidate:dismissed:{uuid4()}",
                    event_type="RISK_UPDATED",
                    source="risk_service",
                    entity_id=risk_id,
                    payload={
                        "changed_fields": ["draft_state"],
                        "status": after.status,
                        "score": after.score,
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="risk.candidate_dismiss",
                    before_snapshot={"draft_state": "draft", "origin_key": before.origin_key},
                    after_snapshot={"draft_state": "cleared", "dismissed": True},
                ),
            )
            return after
