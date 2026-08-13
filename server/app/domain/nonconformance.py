"""Complaint triage and Nonconformance Report records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.engine import RowMapping

from app.db.schema import tables
from app.domain.complaints import (
    ComplaintNotFoundError,
    ComplaintRecord,
    ComplaintService,
)
from app.domain.complaints import _snapshot as complaint_snapshot
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class NcrNotFoundError(LookupError):
    """Raised when an NCR is absent from the tenant-bound Project."""


class NcrInvalidTransitionError(ValueError):
    """Raised when Complaint triage is attempted from an invalid state."""


class NcrContainmentGateError(ValueError):
    """Raised when containment evidence is missing."""


class NcrRootCauseGateError(ValueError):
    """Raised when no approved Root Cause Analysis exists."""


class NcrActionGateError(ValueError):
    """Raised when corrective/preventive completion is not ready."""


class NcrObservationPlanError(ValueError):
    """Raised when effectiveness criteria or observation timing is invalid."""


@dataclass(frozen=True)
class NcrRecord:
    id: UUID
    project_id: UUID
    complaint_id: UUID
    owner_user_id: UUID
    created_by_user_id: UUID
    preventive_disposition_approved_by_user_id: UUID | None
    closed_by_user_id: UUID | None
    code: str
    nonconformity: str
    requirement_reference: str
    severity: str
    status: str
    target_date: date
    containment_action: str | None
    containment_completed_at: datetime | None
    affected_quantity: int | None
    affected_scope: str | None
    preventive_not_applicable_reason: str | None
    preventive_disposition_approved_at: datetime | None
    effectiveness_criteria: str | None
    observation_due_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class NcrDraft:
    owner_user_id: UUID
    nonconformity: str
    requirement_reference: str
    severity: str
    target_date: date
    affected_quantity: int | None
    affected_scope: str | None


@dataclass(frozen=True)
class TriageResult:
    complaint: ComplaintRecord
    ncr: NcrRecord


def _ncr_statement() -> Any:
    return select(
        tables.nonconformance_reports.c.id,
        tables.nonconformance_reports.c.project_id,
        tables.nonconformance_reports.c.complaint_id,
        tables.nonconformance_reports.c.owner_user_id,
        tables.nonconformance_reports.c.created_by_user_id,
        tables.nonconformance_reports.c.preventive_disposition_approved_by_user_id,
        tables.nonconformance_reports.c.closed_by_user_id,
        tables.nonconformance_reports.c.code,
        tables.nonconformance_reports.c.nonconformity,
        tables.nonconformance_reports.c.requirement_reference,
        tables.nonconformance_reports.c.severity,
        tables.nonconformance_reports.c.status,
        tables.nonconformance_reports.c.target_date,
        tables.nonconformance_reports.c.containment_action,
        tables.nonconformance_reports.c.containment_completed_at,
        tables.nonconformance_reports.c.affected_quantity,
        tables.nonconformance_reports.c.affected_scope,
        tables.nonconformance_reports.c.preventive_not_applicable_reason,
        tables.nonconformance_reports.c.preventive_disposition_approved_at,
        tables.nonconformance_reports.c.effectiveness_criteria,
        tables.nonconformance_reports.c.observation_due_at,
        tables.nonconformance_reports.c.closed_at,
        tables.nonconformance_reports.c.created_at,
        tables.nonconformance_reports.c.updated_at,
    )


def _record(row: RowMapping) -> NcrRecord:
    return NcrRecord(**{field: row[field] for field in NcrRecord.__dataclass_fields__})


def _snapshot(record: NcrRecord) -> dict[str, object]:
    return {
        "project_id": str(record.project_id),
        "complaint_id": str(record.complaint_id),
        "owner_user_id": str(record.owner_user_id),
        "code": record.code,
        "nonconformity": record.nonconformity,
        "requirement_reference": record.requirement_reference,
        "severity": record.severity,
        "status": record.status,
        "target_date": record.target_date.isoformat(),
        "affected_quantity": record.affected_quantity,
        "affected_scope": record.affected_scope,
        "effectiveness_criteria": record.effectiveness_criteria,
        "observation_due_at": (
            record.observation_due_at.isoformat() if record.observation_due_at else None
        ),
    }


class NonconformanceService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _get(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        ncr_id: UUID,
    ) -> NcrRecord:
        row = (
            connection.execute(
                _ncr_statement().where(
                    tables.nonconformance_reports.c.tenant_id == tenant_id,
                    tables.nonconformance_reports.c.project_id == project_id,
                    tables.nonconformance_reports.c.id == ncr_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise NcrNotFoundError
        return _record(row)

    def triage(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        complaint_id: UUID,
        draft: NcrDraft,
    ) -> TriageResult:
        ncr_id = uuid4()
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise ComplaintNotFoundError
            before = ComplaintService._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                complaint_id=complaint_id,
            )
            if before.status != "open":
                raise NcrInvalidTransitionError
            ComplaintService._validate_member(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=actor_user_id,
            )
            ComplaintService._validate_member(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=draft.owner_user_id,
            )
            connection.execute(
                tables.nonconformance_reports.insert(),
                {
                    "id": ncr_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "complaint_id": complaint_id,
                    "owner_user_id": draft.owner_user_id,
                    "created_by_user_id": actor_user_id,
                    "code": f"NCR-{ncr_id.hex.upper()}",
                    "nonconformity": draft.nonconformity,
                    "requirement_reference": draft.requirement_reference,
                    "severity": draft.severity,
                    "status": "open",
                    "target_date": draft.target_date,
                    "affected_quantity": draft.affected_quantity,
                    "affected_scope": draft.affected_scope,
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            connection.execute(
                tables.complaints.update()
                .where(
                    tables.complaints.c.tenant_id == tenant_id,
                    tables.complaints.c.project_id == project_id,
                    tables.complaints.c.id == complaint_id,
                )
                .values(status="triaged", updated_at=occurred_at)
            )
            after = ComplaintService._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                complaint_id=complaint_id,
            )
            ncr = self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                ncr_id=ncr_id,
            )
            writer = EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            )
            writer.record(
                EventDraft(
                    event_id=f"complaint:{complaint_id}:status:triaged",
                    event_type="COMPLAINT_STATUS_CHANGED",
                    source="quality_service",
                    entity_id=complaint_id,
                    payload={"from_status": before.status, "to_status": after.status},
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="quality.complaint.triage",
                    before_snapshot=complaint_snapshot(before),
                    after_snapshot=complaint_snapshot(after),
                ),
            )
            writer.record(
                EventDraft(
                    event_id=f"ncr:{ncr_id}:created",
                    event_type="NCR_CREATED",
                    source="quality_service",
                    entity_id=ncr_id,
                    payload={"complaint_id": str(complaint_id), "severity": ncr.severity},
                    occurred_at=occurred_at,
                ),
                AuditDraft(action="quality.ncr.create", after_snapshot=_snapshot(ncr)),
            )
            return TriageResult(complaint=after, ncr=ncr)

    def get(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        ncr_id: UUID,
    ) -> NcrRecord:
        with self._engine.connect() as connection:
            return self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                ncr_id=ncr_id,
            )

    def list_for_complaint(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        complaint_id: UUID,
    ) -> list[NcrRecord]:
        with self._engine.connect() as connection:
            ComplaintService._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                complaint_id=complaint_id,
            )
            return [
                _record(row)
                for row in connection.execute(
                    _ncr_statement()
                    .where(
                        tables.nonconformance_reports.c.tenant_id == tenant_id,
                        tables.nonconformance_reports.c.project_id == project_id,
                        tables.nonconformance_reports.c.complaint_id == complaint_id,
                    )
                    .order_by(
                        tables.nonconformance_reports.c.created_at,
                        tables.nonconformance_reports.c.id,
                    )
                ).mappings()
            ]

    def transition(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        ncr_id: UUID,
        to_status: str,
        containment_action: str | None = None,
        effectiveness_criteria: str | None = None,
        observation_due_at: datetime | None = None,
    ) -> NcrRecord:
        occurred_at = datetime.now(UTC)
        transitions = {
            "open": "containment",
            "containment": "root_cause",
            "root_cause": "action",
            "action": "verification",
            "verification": "closed",
        }
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise NcrNotFoundError
            before = self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                ncr_id=ncr_id,
            )
            if transitions.get(before.status) != to_status:
                raise NcrInvalidTransitionError
            ComplaintService._validate_member(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=actor_user_id,
            )
            values: dict[str, object] = {"status": to_status, "updated_at": occurred_at}
            if before.status == "containment":
                if containment_action is None:
                    raise NcrContainmentGateError
                values.update(
                    containment_action=containment_action,
                    containment_completed_at=occurred_at,
                )
            elif before.status == "root_cause":
                approved = connection.execute(
                    select(func.count())
                    .select_from(tables.root_cause_analyses)
                    .where(
                        tables.root_cause_analyses.c.tenant_id == tenant_id,
                        tables.root_cause_analyses.c.ncr_id == ncr_id,
                        tables.root_cause_analyses.c.status == "approved",
                    )
                ).scalar_one()
                if approved < 1:
                    raise NcrRootCauseGateError
            elif before.status == "action":
                actions = connection.execute(
                    select(
                        tables.capa_actions.c.action_type,
                        tables.capa_actions.c.status,
                        tables.capa_actions.c.completed_at,
                    ).where(
                        tables.capa_actions.c.tenant_id == tenant_id,
                        tables.capa_actions.c.project_id == project_id,
                        tables.capa_actions.c.ncr_id == ncr_id,
                    )
                ).mappings().all()
                completed_types = {
                    row["action_type"] for row in actions if row["status"] == "completed"
                }
                preventive_ready = (
                    "preventive" in completed_types
                    or before.preventive_disposition_approved_by_user_id is not None
                )
                if (
                    not actions
                    or any(row["status"] != "completed" for row in actions)
                    or "corrective" not in completed_types
                    or not preventive_ready
                ):
                    raise NcrActionGateError
                completed_at_values = [row["completed_at"] for row in actions]
                if any(value is None for value in completed_at_values):
                    raise NcrActionGateError
                final_completion = max(
                    value for value in completed_at_values if isinstance(value, datetime)
                )
                if effectiveness_criteria is None or observation_due_at is None:
                    raise NcrObservationPlanError
                normalized_due = observation_due_at.astimezone(UTC)
                if normalized_due <= final_completion:
                    raise NcrObservationPlanError
                values.update(
                    effectiveness_criteria=effectiveness_criteria,
                    observation_due_at=normalized_due,
                )
            elif before.status == "verification":
                raise NcrInvalidTransitionError
            connection.execute(
                tables.nonconformance_reports.update()
                .where(
                    tables.nonconformance_reports.c.tenant_id == tenant_id,
                    tables.nonconformance_reports.c.id == ncr_id,
                )
                .values(**values)
            )
            after = self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                ncr_id=ncr_id,
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"ncr:{ncr_id}:status:{to_status}:{uuid4()}",
                    event_type="NCR_STATUS_CHANGED",
                    source="quality_service",
                    entity_id=ncr_id,
                    payload={"from_status": before.status, "to_status": after.status},
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="quality.ncr.transition",
                    before_snapshot=_snapshot(before),
                    after_snapshot=_snapshot(after),
                ),
            )
            return after
