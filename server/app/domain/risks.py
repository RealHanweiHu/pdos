"""Project-scoped Risk lifecycle use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select
from sqlalchemy.engine import RowMapping

from app.db.schema import tables
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class RiskNotFoundError(LookupError):
    """Raised when a Risk is absent from the tenant-bound Project."""


class RiskScopeError(ValueError):
    """Raised when a Risk owner is outside the Project."""


class RiskInvalidTransitionError(ValueError):
    """Raised when a Risk status edge is outside the frozen graph."""


class RiskTerminalError(ValueError):
    """Raised when a closed Risk is edited."""


@dataclass(frozen=True)
class RiskRecord:
    id: UUID
    project_id: UUID
    owner_user_id: UUID | None
    title: str
    description: str | None
    status: str
    likelihood: int
    impact: int
    score: int
    mitigation_plan: str | None
    contingency_plan: str | None
    target_date: date | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class RiskDraft:
    owner_user_id: UUID | None
    title: str
    description: str | None
    likelihood: int
    impact: int
    mitigation_plan: str | None
    contingency_plan: str | None
    target_date: date | None


@dataclass(frozen=True)
class RiskUpdate:
    changes: dict[str, object]


RISK_TRANSITIONS = {
    "open": frozenset({"mitigating", "watching"}),
    "mitigating": frozenset({"watching", "closed"}),
    "watching": frozenset({"mitigating", "closed"}),
    "closed": frozenset(),
}


def _risk_statement() -> Any:
    return select(
        tables.risks.c.id,
        tables.risks.c.project_id,
        tables.risks.c.owner_user_id,
        tables.risks.c.title,
        tables.risks.c.description,
        tables.risks.c.status,
        tables.risks.c.likelihood,
        tables.risks.c.impact,
        tables.risks.c.mitigation_plan,
        tables.risks.c.contingency_plan,
        tables.risks.c.target_date,
        tables.risks.c.closed_at,
        tables.risks.c.created_at,
        tables.risks.c.updated_at,
    )


def _record_from_row(row: RowMapping) -> RiskRecord:
    likelihood = row["likelihood"]
    impact = row["impact"]
    return RiskRecord(
        id=row["id"],
        project_id=row["project_id"],
        owner_user_id=row["owner_user_id"],
        title=row["title"],
        description=row["description"],
        status=row["status"],
        likelihood=likelihood,
        impact=impact,
        score=likelihood * impact,
        mitigation_plan=row["mitigation_plan"],
        contingency_plan=row["contingency_plan"],
        target_date=row["target_date"],
        closed_at=row["closed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _risk_snapshot(record: RiskRecord) -> dict[str, object]:
    return {
        "project_id": str(record.project_id),
        "owner_user_id": (str(record.owner_user_id) if record.owner_user_id is not None else None),
        "title": record.title,
        "description": record.description,
        "status": record.status,
        "likelihood": record.likelihood,
        "impact": record.impact,
        "score": record.score,
        "mitigation_plan": record.mitigation_plan,
        "contingency_plan": record.contingency_plan,
        "target_date": record.target_date.isoformat() if record.target_date is not None else None,
        "closed_at": record.closed_at.isoformat() if record.closed_at is not None else None,
    }


class RiskService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _project_exists(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
    ) -> None:
        found = connection.execute(
            select(tables.projects.c.id).where(
                tables.projects.c.tenant_id == tenant_id,
                tables.projects.c.id == project_id,
            )
        ).scalar_one_or_none()
        if found is None:
            raise RiskNotFoundError

    @staticmethod
    def _get_record(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        risk_id: UUID,
    ) -> RiskRecord:
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
        return _record_from_row(row)

    @staticmethod
    def _validate_member(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        user_id: UUID | None,
    ) -> None:
        if user_id is None:
            return
        found = connection.execute(
            select(tables.project_members.c.id)
            .join(
                tables.users,
                (tables.users.c.tenant_id == tables.project_members.c.tenant_id)
                & (tables.users.c.id == tables.project_members.c.user_id),
            )
            .where(
                tables.project_members.c.tenant_id == tenant_id,
                tables.project_members.c.project_id == project_id,
                tables.project_members.c.user_id == user_id,
                tables.users.c.role.in_(
                    {"owner", "admin", "project_manager", "engineer", "quality"}
                ),
            )
        ).scalar_one_or_none()
        if found is None:
            raise RiskScopeError

    def get(self, *, tenant_id: UUID, project_id: UUID, risk_id: UUID) -> RiskRecord:
        with self._engine.connect() as connection:
            return self._get_record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                risk_id=risk_id,
            )

    def list(self, *, tenant_id: UUID, project_id: UUID) -> list[RiskRecord]:
        with self._engine.connect() as connection:
            return [
                _record_from_row(row)
                for row in connection.execute(
                    _risk_statement()
                    .where(
                        tables.risks.c.tenant_id == tenant_id,
                        tables.risks.c.project_id == project_id,
                    )
                    .order_by(tables.risks.c.updated_at.desc(), tables.risks.c.id.desc())
                ).mappings()
            ]

    def create(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        draft: RiskDraft,
    ) -> RiskRecord:
        risk_id = uuid4()
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            self._project_exists(connection, tenant_id=tenant_id, project_id=project_id)
            self._validate_member(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=draft.owner_user_id,
            )
            connection.execute(
                tables.risks.insert(),
                {
                    "id": risk_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "owner_user_id": draft.owner_user_id,
                    "title": draft.title,
                    "description": draft.description,
                    "status": "open",
                    "likelihood": draft.likelihood,
                    "impact": draft.impact,
                    "mitigation_plan": draft.mitigation_plan,
                    "contingency_plan": draft.contingency_plan,
                    "target_date": draft.target_date,
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            risk = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, risk_id=risk_id
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"risk:{risk_id}:created",
                    event_type="RISK_CREATED",
                    source="risk_service",
                    entity_id=risk_id,
                    payload={"risk_id": str(risk_id), "score": risk.score, "status": risk.status},
                    occurred_at=occurred_at,
                ),
                AuditDraft(action="risk.create", after_snapshot=_risk_snapshot(risk)),
            )
            return risk

    def update(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        risk_id: UUID,
        patch: RiskUpdate,
    ) -> RiskRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            before = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, risk_id=risk_id
            )
            if before.status == "closed":
                raise RiskTerminalError
            changes = dict(patch.changes)
            if "owner_user_id" in changes:
                owner_id = changes["owner_user_id"]
                if owner_id is not None and not isinstance(owner_id, UUID):
                    raise RiskScopeError
                self._validate_member(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    user_id=owner_id,
                )
            connection.execute(
                tables.risks.update()
                .where(
                    tables.risks.c.tenant_id == tenant_id,
                    tables.risks.c.project_id == project_id,
                    tables.risks.c.id == risk_id,
                )
                .values(**changes, updated_at=occurred_at)
            )
            after = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, risk_id=risk_id
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"risk:{risk_id}:updated:{uuid4()}",
                    event_type="RISK_UPDATED",
                    source="risk_service",
                    entity_id=risk_id,
                    payload={
                        "changed_fields": sorted(patch.changes),
                        "status": after.status,
                        "score": after.score,
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="risk.update",
                    before_snapshot=_risk_snapshot(before),
                    after_snapshot=_risk_snapshot(after),
                ),
            )
            return after

    def transition(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        risk_id: UUID,
        to_status: str,
    ) -> RiskRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            before = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, risk_id=risk_id
            )
            if to_status not in RISK_TRANSITIONS[before.status]:
                raise RiskInvalidTransitionError
            connection.execute(
                tables.risks.update()
                .where(
                    tables.risks.c.tenant_id == tenant_id,
                    tables.risks.c.project_id == project_id,
                    tables.risks.c.id == risk_id,
                )
                .values(
                    status=to_status,
                    closed_at=occurred_at if to_status == "closed" else None,
                    updated_at=occurred_at,
                )
            )
            after = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, risk_id=risk_id
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"risk:{risk_id}:status:{to_status}:{uuid4()}",
                    event_type="RISK_STATUS_CHANGED",
                    source="risk_service",
                    entity_id=risk_id,
                    payload={"from_status": before.status, "to_status": after.status},
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="risk.transition",
                    before_snapshot=_risk_snapshot(before),
                    after_snapshot=_risk_snapshot(after),
                ),
            )
            return after
