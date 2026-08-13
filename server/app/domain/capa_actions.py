"""CAPA Action assignment and immutable completion lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select
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


class CapaActionNotFoundError(LookupError):
    """Raised when an Action is absent from the bound NCR."""


class CapaActionOwnershipError(ValueError):
    """Raised when someone other than the assigned owner executes an Action."""


class CapaActionTransitionError(ValueError):
    """Raised when an Action transition violates the frozen lifecycle."""


@dataclass(frozen=True)
class CapaActionRecord:
    id: UUID
    project_id: UUID
    ncr_id: UUID
    owner_user_id: UUID
    created_by_user_id: UUID
    action_type: str
    description: str
    due_date: date
    status: str
    completion_summary: str | None
    evidence_refs: list[dict[str, object]]
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CapaActionDraft:
    owner_user_id: UUID
    action_type: str
    description: str
    due_date: date


def _statement() -> Any:
    return select(
        tables.capa_actions.c.id,
        tables.capa_actions.c.project_id,
        tables.capa_actions.c.ncr_id,
        tables.capa_actions.c.owner_user_id,
        tables.capa_actions.c.created_by_user_id,
        tables.capa_actions.c.action_type,
        tables.capa_actions.c.description,
        tables.capa_actions.c.due_date,
        tables.capa_actions.c.status,
        tables.capa_actions.c.completion_summary,
        tables.capa_actions.c.evidence_refs,
        tables.capa_actions.c.started_at,
        tables.capa_actions.c.completed_at,
        tables.capa_actions.c.created_at,
        tables.capa_actions.c.updated_at,
    )


def _record(row: RowMapping) -> CapaActionRecord:
    values = {field: row[field] for field in CapaActionRecord.__dataclass_fields__}
    return CapaActionRecord(**values)


def _snapshot(record: CapaActionRecord) -> dict[str, object]:
    return {
        "project_id": str(record.project_id),
        "ncr_id": str(record.ncr_id),
        "owner_user_id": str(record.owner_user_id),
        "action_type": record.action_type,
        "description": record.description,
        "due_date": record.due_date.isoformat(),
        "status": record.status,
        "completion_summary": record.completion_summary,
        "evidence_refs": record.evidence_refs,
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
    }


class CapaActionService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _get(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        ncr_id: UUID,
        action_id: UUID,
    ) -> CapaActionRecord:
        row = (
            connection.execute(
                _statement().where(
                    tables.capa_actions.c.tenant_id == tenant_id,
                    tables.capa_actions.c.project_id == project_id,
                    tables.capa_actions.c.ncr_id == ncr_id,
                    tables.capa_actions.c.id == action_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise CapaActionNotFoundError
        return _record(row)

    def create(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        ncr_id: UUID,
        draft: CapaActionDraft,
    ) -> CapaActionRecord:
        action_id, occurred_at = uuid4(), datetime.now(UTC)
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise NcrNotFoundError
            ncr = NonconformanceService._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                ncr_id=ncr_id,
            )
            if ncr.status != "action":
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
                tables.capa_actions.insert(),
                {
                    "id": action_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "ncr_id": ncr_id,
                    "owner_user_id": draft.owner_user_id,
                    "created_by_user_id": actor_user_id,
                    "action_type": draft.action_type,
                    "description": draft.description,
                    "due_date": draft.due_date,
                    "status": "planned",
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            record = self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                ncr_id=ncr_id,
                action_id=action_id,
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"capa-action:{action_id}:created",
                    event_type="CAPA_ACTION_CREATED",
                    source="quality_service",
                    entity_id=action_id,
                    payload={"ncr_id": str(ncr_id), "action_type": record.action_type},
                    occurred_at=occurred_at,
                ),
                AuditDraft(action="quality.capa_action.create", after_snapshot=_snapshot(record)),
            )
            return record

    def transition(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        ncr_id: UUID,
        action_id: UUID,
        to_status: str,
        completion_summary: str | None,
        evidence_refs: list[dict[str, object]],
    ) -> CapaActionRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise CapaActionNotFoundError
            ncr = NonconformanceService._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                ncr_id=ncr_id,
            )
            if ncr.status != "action":
                raise NcrInvalidTransitionError
            before = self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                ncr_id=ncr_id,
                action_id=action_id,
            )
            if before.owner_user_id != actor_user_id:
                raise CapaActionOwnershipError
            allowed = {"planned": "in_progress", "in_progress": "completed"}
            if allowed.get(before.status) != to_status:
                raise CapaActionTransitionError
            values: dict[str, object] = {"status": to_status, "updated_at": occurred_at}
            if to_status == "in_progress":
                if completion_summary is not None or evidence_refs:
                    raise CapaActionTransitionError
                values["started_at"] = occurred_at
            else:
                if completion_summary is None:
                    raise CapaActionTransitionError
                validate_evidence_refs(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    refs=evidence_refs,
                    required=True,
                )
                values.update(
                    completion_summary=completion_summary,
                    evidence_refs=evidence_refs,
                    completed_at=occurred_at,
                )
            connection.execute(
                tables.capa_actions.update()
                .where(
                    tables.capa_actions.c.tenant_id == tenant_id,
                    tables.capa_actions.c.id == action_id,
                )
                .values(**values)
            )
            after = self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                ncr_id=ncr_id,
                action_id=action_id,
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"capa-action:{action_id}:status:{to_status}",
                    event_type="CAPA_ACTION_STATUS_CHANGED",
                    source="quality_service",
                    entity_id=action_id,
                    payload={"from_status": before.status, "to_status": after.status},
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="quality.capa_action.transition",
                    before_snapshot=_snapshot(before),
                    after_snapshot=_snapshot(after),
                ),
            )
            return after
