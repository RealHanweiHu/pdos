"""Versioned Root Cause Analysis lifecycle with four-eyes approval."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.engine import RowMapping

from app.db.schema import tables
from app.domain.complaints import ComplaintService
from app.domain.nonconformance import (
    NcrInvalidTransitionError,
    NcrNotFoundError,
    NonconformanceService,
)
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.quality_evidence import validate_evidence_refs
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class RootCauseNotFoundError(LookupError):
    """Raised when a Root Cause Analysis is absent from the bound NCR."""


class RootCauseFourEyesError(ValueError):
    """Raised when an analyst attempts to approve their own analysis."""


class RootCauseTerminalError(ValueError):
    """Raised when an immutable Root Cause Analysis is changed."""


@dataclass(frozen=True)
class RootCauseRecord:
    id: UUID
    project_id: UUID
    ncr_id: UUID
    analyst_user_id: UUID
    approved_by_user_id: UUID | None
    version: int
    method: str
    analysis: str
    root_cause: str
    evidence_refs: list[dict[str, object]]
    status: str
    approved_at: datetime | None
    superseded_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class RootCauseDraft:
    method: str
    analysis: str
    root_cause: str
    evidence_refs: list[dict[str, object]]


def _statement() -> Any:
    return select(
        tables.root_cause_analyses.c.id,
        tables.root_cause_analyses.c.project_id,
        tables.root_cause_analyses.c.ncr_id,
        tables.root_cause_analyses.c.analyst_user_id,
        tables.root_cause_analyses.c.approved_by_user_id,
        tables.root_cause_analyses.c.version,
        tables.root_cause_analyses.c.method,
        tables.root_cause_analyses.c.analysis,
        tables.root_cause_analyses.c.root_cause,
        tables.root_cause_analyses.c.evidence_refs,
        tables.root_cause_analyses.c.status,
        tables.root_cause_analyses.c.approved_at,
        tables.root_cause_analyses.c.superseded_at,
        tables.root_cause_analyses.c.created_at,
    )


def _record(row: RowMapping) -> RootCauseRecord:
    return RootCauseRecord(**{field: row[field] for field in RootCauseRecord.__dataclass_fields__})


def _snapshot(record: RootCauseRecord) -> dict[str, object]:
    return {
        "project_id": str(record.project_id),
        "ncr_id": str(record.ncr_id),
        "analyst_user_id": str(record.analyst_user_id),
        "approved_by_user_id": (
            str(record.approved_by_user_id) if record.approved_by_user_id else None
        ),
        "version": record.version,
        "method": record.method,
        "analysis": record.analysis,
        "root_cause": record.root_cause,
        "evidence_refs": record.evidence_refs,
        "status": record.status,
        "approved_at": record.approved_at.isoformat() if record.approved_at else None,
        "superseded_at": record.superseded_at.isoformat() if record.superseded_at else None,
    }


class RootCauseService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _get(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        ncr_id: UUID,
        root_cause_id: UUID,
    ) -> RootCauseRecord:
        row = (
            connection.execute(
                _statement().where(
                    tables.root_cause_analyses.c.tenant_id == tenant_id,
                    tables.root_cause_analyses.c.project_id == project_id,
                    tables.root_cause_analyses.c.ncr_id == ncr_id,
                    tables.root_cause_analyses.c.id == root_cause_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise RootCauseNotFoundError
        return _record(row)

    def create(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        ncr_id: UUID,
        draft: RootCauseDraft,
    ) -> RootCauseRecord:
        root_cause_id, occurred_at = uuid4(), datetime.now(UTC)
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise NcrNotFoundError
            ncr = NonconformanceService._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                ncr_id=ncr_id,
            )
            if ncr.status != "root_cause":
                raise NcrInvalidTransitionError
            ComplaintService._validate_member(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=actor_user_id,
            )
            validate_evidence_refs(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                refs=draft.evidence_refs,
                required=False,
            )
            version = connection.execute(
                select(func.coalesce(func.max(tables.root_cause_analyses.c.version), 0) + 1).where(
                    tables.root_cause_analyses.c.tenant_id == tenant_id,
                    tables.root_cause_analyses.c.ncr_id == ncr_id,
                )
            ).scalar_one()
            prior_approved = [
                _record(row)
                for row in connection.execute(
                    _statement().where(
                        tables.root_cause_analyses.c.tenant_id == tenant_id,
                        tables.root_cause_analyses.c.ncr_id == ncr_id,
                        tables.root_cause_analyses.c.status == "approved",
                    )
                ).mappings()
            ]
            connection.execute(
                tables.root_cause_analyses.update()
                .where(
                    tables.root_cause_analyses.c.tenant_id == tenant_id,
                    tables.root_cause_analyses.c.ncr_id == ncr_id,
                    tables.root_cause_analyses.c.status == "approved",
                )
                .values(status="superseded", superseded_at=occurred_at)
            )
            writer = EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            )
            for prior in prior_approved:
                superseded = self._get(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    ncr_id=ncr_id,
                    root_cause_id=prior.id,
                )
                writer.record(
                    EventDraft(
                        event_id=f"root-cause:{prior.id}:superseded:{root_cause_id}",
                        event_type="ROOT_CAUSE_ANALYSIS_CHANGED",
                        source="quality_service",
                        entity_id=prior.id,
                        payload={
                            "action": "superseded",
                            "status": superseded.status,
                            "version": superseded.version,
                        },
                        occurred_at=occurred_at,
                    ),
                    AuditDraft(
                        action="quality.root_cause.supersede",
                        before_snapshot=_snapshot(prior),
                        after_snapshot=_snapshot(superseded),
                    ),
                )
            connection.execute(
                tables.root_cause_analyses.insert(),
                {
                    "id": root_cause_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "ncr_id": ncr_id,
                    "analyst_user_id": actor_user_id,
                    "version": version,
                    "method": draft.method,
                    "analysis": draft.analysis,
                    "root_cause": draft.root_cause,
                    "evidence_refs": draft.evidence_refs,
                    "status": "draft",
                    "created_at": occurred_at,
                },
            )
            record = self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                ncr_id=ncr_id,
                root_cause_id=root_cause_id,
            )
            writer.record(
                EventDraft(
                    event_id=f"root-cause:{root_cause_id}:created",
                    event_type="ROOT_CAUSE_ANALYSIS_CHANGED",
                    source="quality_service",
                    entity_id=root_cause_id,
                    payload={"action": "created", "status": record.status, "version": version},
                    occurred_at=occurred_at,
                ),
                AuditDraft(action="quality.root_cause.create", after_snapshot=_snapshot(record)),
            )
            return record

    def approve(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        ncr_id: UUID,
        root_cause_id: UUID,
    ) -> RootCauseRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise RootCauseNotFoundError
            before = self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                ncr_id=ncr_id,
                root_cause_id=root_cause_id,
            )
            if before.status != "draft":
                raise RootCauseTerminalError
            if before.analyst_user_id == actor_user_id:
                raise RootCauseFourEyesError
            ComplaintService._validate_member(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=actor_user_id,
            )
            connection.execute(
                tables.root_cause_analyses.update()
                .where(
                    tables.root_cause_analyses.c.tenant_id == tenant_id,
                    tables.root_cause_analyses.c.id == root_cause_id,
                )
                .values(
                    status="approved",
                    approved_by_user_id=actor_user_id,
                    approved_at=occurred_at,
                )
            )
            after = self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                ncr_id=ncr_id,
                root_cause_id=root_cause_id,
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"root-cause:{root_cause_id}:approved",
                    event_type="ROOT_CAUSE_ANALYSIS_CHANGED",
                    source="quality_service",
                    entity_id=root_cause_id,
                    payload={
                        "action": "approved",
                        "status": after.status,
                        "version": after.version,
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="quality.root_cause.approve",
                    before_snapshot=_snapshot(before),
                    after_snapshot=_snapshot(after),
                ),
            )
            return after

    def list(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        ncr_id: UUID,
    ) -> list[RootCauseRecord]:
        with self._engine.connect() as connection:
            NonconformanceService._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                ncr_id=ncr_id,
            )
            return [
                _record(row)
                for row in connection.execute(
                    _statement()
                    .where(
                        tables.root_cause_analyses.c.tenant_id == tenant_id,
                        tables.root_cause_analyses.c.ncr_id == ncr_id,
                    )
                    .order_by(tables.root_cause_analyses.c.version)
                ).mappings()
            ]
