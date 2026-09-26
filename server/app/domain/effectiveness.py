"""Immutable CAPA effectiveness review and failure return use case."""

from __future__ import annotations

from contextlib import nullcontext
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
    NcrRecord,
    NonconformanceService,
)
from app.domain.nonconformance import _snapshot as ncr_snapshot
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.quality_evidence import validate_evidence_refs
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class EffectivenessFourEyesError(ValueError):
    """Raised when the reviewer owns any action under review."""


class EffectivenessObservationPendingError(ValueError):
    """Raised before the frozen observation period is complete."""


@dataclass(frozen=True)
class EffectivenessReviewRecord:
    id: UUID
    project_id: UUID
    ncr_id: UUID
    reviewer_user_id: UUID
    review_number: int
    criteria: str
    observation_due_at: datetime
    actual_result: str
    result: str
    evidence_refs: list[dict[str, object]]
    reviewed_at: datetime
    created_at: datetime


@dataclass(frozen=True)
class EffectivenessReviewDraft:
    actual_result: str
    result: str
    evidence_refs: list[dict[str, object]]


@dataclass(frozen=True)
class EffectivenessReviewResult:
    review: EffectivenessReviewRecord
    ncr: NcrRecord


def _statement() -> Any:
    return select(
        tables.effectiveness_reviews.c.id,
        tables.effectiveness_reviews.c.project_id,
        tables.effectiveness_reviews.c.ncr_id,
        tables.effectiveness_reviews.c.reviewer_user_id,
        tables.effectiveness_reviews.c.review_number,
        tables.effectiveness_reviews.c.criteria,
        tables.effectiveness_reviews.c.observation_due_at,
        tables.effectiveness_reviews.c.actual_result,
        tables.effectiveness_reviews.c.result,
        tables.effectiveness_reviews.c.evidence_refs,
        tables.effectiveness_reviews.c.reviewed_at,
        tables.effectiveness_reviews.c.created_at,
    )


def _record(row: RowMapping) -> EffectivenessReviewRecord:
    values = {field: row[field] for field in EffectivenessReviewRecord.__dataclass_fields__}
    return EffectivenessReviewRecord(**values)


def _snapshot(record: EffectivenessReviewRecord) -> dict[str, object]:
    return {
        "project_id": str(record.project_id),
        "ncr_id": str(record.ncr_id),
        "reviewer_user_id": str(record.reviewer_user_id),
        "review_number": record.review_number,
        "criteria": record.criteria,
        "observation_due_at": record.observation_due_at.isoformat(),
        "actual_result": record.actual_result,
        "result": record.result,
        "evidence_refs": record.evidence_refs,
        "reviewed_at": record.reviewed_at.isoformat(),
    }


class EffectivenessService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _get(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        ncr_id: UUID,
        review_id: UUID,
    ) -> EffectivenessReviewRecord:
        row = (
            connection.execute(
                _statement().where(
                    tables.effectiveness_reviews.c.tenant_id == tenant_id,
                    tables.effectiveness_reviews.c.project_id == project_id,
                    tables.effectiveness_reviews.c.ncr_id == ncr_id,
                    tables.effectiveness_reviews.c.id == review_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise NcrNotFoundError
        return _record(row)

    def review(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        ncr_id: UUID,
        draft: EffectivenessReviewDraft,
        connection: Connection | None = None,
    ) -> EffectivenessReviewResult:
        review_id, reviewed_at = uuid4(), datetime.now(UTC)
        with (
            nullcontext(connection) if connection is not None else self._engine.begin()
        ) as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise NcrNotFoundError
            before = NonconformanceService._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                ncr_id=ncr_id,
            )
            if (
                before.status != "verification"
                or before.effectiveness_criteria is None
                or before.observation_due_at is None
            ):
                raise NcrInvalidTransitionError
            if reviewed_at < before.observation_due_at:
                raise EffectivenessObservationPendingError
            ComplaintService._validate_member(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=actor_user_id,
            )
            owns_action = connection.execute(
                select(func.count())
                .select_from(tables.capa_actions)
                .where(
                    tables.capa_actions.c.tenant_id == tenant_id,
                    tables.capa_actions.c.ncr_id == ncr_id,
                    tables.capa_actions.c.owner_user_id == actor_user_id,
                )
            ).scalar_one()
            from app.domain.quality_responsibilities import historical_capa_owners

            if owns_action or actor_user_id in historical_capa_owners(
                connection, tenant_id, project_id, ncr_id
            ):
                raise EffectivenessFourEyesError
            validate_evidence_refs(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                refs=draft.evidence_refs,
                required=True,
            )
            review_number = connection.execute(
                select(
                    func.coalesce(func.max(tables.effectiveness_reviews.c.review_number), 0) + 1
                ).where(
                    tables.effectiveness_reviews.c.tenant_id == tenant_id,
                    tables.effectiveness_reviews.c.ncr_id == ncr_id,
                )
            ).scalar_one()
            connection.execute(
                tables.effectiveness_reviews.insert(),
                {
                    "id": review_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "ncr_id": ncr_id,
                    "reviewer_user_id": actor_user_id,
                    "review_number": review_number,
                    "criteria": before.effectiveness_criteria,
                    "observation_due_at": before.observation_due_at,
                    "actual_result": draft.actual_result,
                    "result": draft.result,
                    "evidence_refs": draft.evidence_refs,
                    "reviewed_at": reviewed_at,
                    "created_at": reviewed_at,
                },
            )
            if draft.result == "ineffective":
                connection.execute(
                    tables.nonconformance_reports.update()
                    .where(
                        tables.nonconformance_reports.c.tenant_id == tenant_id,
                        tables.nonconformance_reports.c.id == ncr_id,
                    )
                    .values(
                        status="action",
                        effectiveness_criteria=None,
                        observation_due_at=None,
                        updated_at=reviewed_at,
                    )
                )
            review = self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                ncr_id=ncr_id,
                review_id=review_id,
            )
            after = NonconformanceService._get(
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
                    event_id=f"effectiveness-review:{review_id}:recorded",
                    event_type="EFFECTIVENESS_REVIEWED",
                    source="quality_service",
                    entity_id=review_id,
                    payload={
                        "ncr_id": str(ncr_id),
                        "result": review.result,
                        "review_number": review.review_number,
                    },
                    occurred_at=reviewed_at,
                ),
                AuditDraft(action="quality.effectiveness.review", after_snapshot=_snapshot(review)),
            )
            if before.status != after.status:
                writer.record(
                    EventDraft(
                        event_id=f"ncr:{ncr_id}:status:action:{review_id}",
                        event_type="NCR_STATUS_CHANGED",
                        source="quality_service",
                        entity_id=ncr_id,
                        payload={"from_status": before.status, "to_status": after.status},
                        occurred_at=reviewed_at,
                    ),
                    AuditDraft(
                        action="quality.ncr.effectiveness_failed",
                        before_snapshot=ncr_snapshot(before),
                        after_snapshot=ncr_snapshot(after),
                    ),
                )
            return EffectivenessReviewResult(review=review, ncr=after)

    def list(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        ncr_id: UUID,
    ) -> list[EffectivenessReviewRecord]:
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
                        tables.effectiveness_reviews.c.tenant_id == tenant_id,
                        tables.effectiveness_reviews.c.ncr_id == ncr_id,
                    )
                    .order_by(tables.effectiveness_reviews.c.review_number)
                ).mappings()
            ]
