"""Development Case conversion and state-machine use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError

from app.db.schema import tables
from app.domain.case_requirements import require_case_requirements_ready
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class CaseCodeConflictError(ValueError):
    """Raised when a Development Case code already exists in the tenant."""


class CaseInvalidTransitionError(ValueError):
    """Raised when a state transition is not in the frozen graph."""


class CaseProjectRequiredError(ValueError):
    """Raised when conversion is requested before a Project references the Case."""


class CaseTerminalError(ValueError):
    """Raised when content mutation is attempted on a terminal Case."""


class DevelopmentCaseNotFoundError(LookupError):
    """Raised when a Case is absent from the active tenant scope."""


class RequirementAlreadyConvertedError(ValueError):
    """Raised when formal conversion has already created a Case."""


class RequirementNotApprovedError(ValueError):
    """Raised when formal conversion is attempted before approval."""


class RequirementNotFoundForConversionError(LookupError):
    """Raised when a Requirement is absent from the active tenant scope."""


@dataclass(frozen=True)
class DevelopmentCaseRecord:
    id: UUID
    requirement_id: UUID
    code: str
    title: str
    summary: str | None
    status: str
    business_case: dict[str, Any]
    created_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DecisionRecord:
    id: UUID
    requirement_id: UUID
    development_case_id: UUID
    decided_by_user_id: UUID
    decision_kind: str
    title: str
    outcome: str
    rationale: str
    decided_at: datetime


@dataclass(frozen=True)
class ConversionDraft:
    code: str
    title: str
    summary: str | None
    business_case: dict[str, Any]
    rationale: str


@dataclass(frozen=True)
class CaseUpdate:
    changes: dict[str, object]


@dataclass(frozen=True)
class ConversionResult:
    development_case: DevelopmentCaseRecord
    decision: DecisionRecord


CASE_TRANSITIONS = {
    "draft": frozenset({"evaluating"}),
    "evaluating": frozenset({"approved", "rejected"}),
    "approved": frozenset({"converted"}),
    "converted": frozenset(),
    "rejected": frozenset(),
}
TERMINAL_CASE_STATUSES = frozenset({"converted", "rejected"})


def _case_statement() -> Any:
    return select(
        tables.development_cases.c.id,
        tables.development_cases.c.requirement_id,
        tables.development_cases.c.code,
        tables.development_cases.c.title,
        tables.development_cases.c.summary,
        tables.development_cases.c.status,
        tables.development_cases.c.business_case,
        tables.development_cases.c.created_by_user_id,
        tables.development_cases.c.created_at,
        tables.development_cases.c.updated_at,
    )


def _record_from_row(row: RowMapping) -> DevelopmentCaseRecord:
    return DevelopmentCaseRecord(
        id=row["id"],
        requirement_id=row["requirement_id"],
        code=row["code"],
        title=row["title"],
        summary=row["summary"],
        status=row["status"],
        business_case=dict(row["business_case"]),
        created_by_user_id=row["created_by_user_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _case_snapshot(record: DevelopmentCaseRecord) -> dict[str, object]:
    return {
        "requirement_id": str(record.requirement_id),
        "code": record.code,
        "title": record.title,
        "summary": record.summary,
        "status": record.status,
        "business_case": record.business_case,
        "created_by_user_id": (
            str(record.created_by_user_id) if record.created_by_user_id is not None else None
        ),
    }


def _requirement_snapshot(row: RowMapping, *, status: str | None = None) -> dict[str, object]:
    return {
        "code": row["code"],
        "title": row["title"],
        "description": row["description"],
        "source": row["source"],
        "status": status or row["status"],
        "priority": row["priority"],
        "acceptance_criteria": list(row["acceptance_criteria"]),
        "customer_id": str(row["customer_id"]) if row["customer_id"] is not None else None,
        "created_by_user_id": (
            str(row["created_by_user_id"]) if row["created_by_user_id"] is not None else None
        ),
    }


def _decision_snapshot(record: DecisionRecord) -> dict[str, object]:
    return {
        "requirement_id": str(record.requirement_id),
        "development_case_id": str(record.development_case_id),
        "decided_by_user_id": str(record.decided_by_user_id),
        "decision_kind": record.decision_kind,
        "title": record.title,
        "outcome": record.outcome,
        "rationale": record.rationale,
    }


class DevelopmentCaseService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _get_record(
        connection: Connection,
        *,
        tenant_id: UUID,
        case_id: UUID,
    ) -> DevelopmentCaseRecord:
        row = (
            connection.execute(
                _case_statement().where(
                    tables.development_cases.c.tenant_id == tenant_id,
                    tables.development_cases.c.id == case_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise DevelopmentCaseNotFoundError
        return _record_from_row(row)

    def get(self, *, tenant_id: UUID, case_id: UUID) -> DevelopmentCaseRecord:
        with self._engine.connect() as connection:
            return self._get_record(connection, tenant_id=tenant_id, case_id=case_id)

    def list(self, *, tenant_id: UUID) -> list[DevelopmentCaseRecord]:
        statement = (
            _case_statement()
            .where(tables.development_cases.c.tenant_id == tenant_id)
            .order_by(
                tables.development_cases.c.updated_at.desc(),
                tables.development_cases.c.id.desc(),
            )
        )
        with self._engine.connect() as connection:
            return [_record_from_row(row) for row in connection.execute(statement).mappings()]

    def convert_requirement(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        requirement_id: UUID,
        draft: ConversionDraft,
    ) -> ConversionResult:
        case_id = uuid4()
        decision_id = uuid4()
        occurred_at = datetime.now(UTC)
        try:
            with self._engine.begin() as connection:
                requirement = (
                    connection.execute(
                        select(tables.requirements)
                        .where(
                            tables.requirements.c.tenant_id == tenant_id,
                            tables.requirements.c.id == requirement_id,
                        )
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if requirement is None:
                    raise RequirementNotFoundForConversionError
                existing_case = connection.execute(
                    select(tables.development_cases.c.id).where(
                        tables.development_cases.c.tenant_id == tenant_id,
                        tables.development_cases.c.requirement_id == requirement_id,
                    )
                ).scalar_one_or_none()
                if existing_case is not None:
                    raise RequirementAlreadyConvertedError
                if requirement["status"] != "approved":
                    raise RequirementNotApprovedError

                connection.execute(
                    tables.development_cases.insert(),
                    {
                        "id": case_id,
                        "tenant_id": tenant_id,
                        "requirement_id": requirement_id,
                        "created_by_user_id": actor_user_id,
                        "code": draft.code,
                        "title": draft.title,
                        "summary": draft.summary,
                        "status": "draft",
                        "business_case": draft.business_case,
                        "created_at": occurred_at,
                        "updated_at": occurred_at,
                    },
                )
                decision = DecisionRecord(
                    id=decision_id,
                    requirement_id=requirement_id,
                    development_case_id=case_id,
                    decided_by_user_id=actor_user_id,
                    decision_kind="requirement_to_development_case",
                    title=f"Convert {requirement['code']} to {draft.code}",
                    outcome="converted",
                    rationale=draft.rationale,
                    decided_at=occurred_at,
                )
                connection.execute(
                    tables.decisions.insert(),
                    {
                        "id": decision.id,
                        "tenant_id": tenant_id,
                        "requirement_id": requirement_id,
                        "development_case_id": case_id,
                        "decided_by_user_id": actor_user_id,
                        "decision_kind": decision.decision_kind,
                        "title": decision.title,
                        "outcome": decision.outcome,
                        "rationale": decision.rationale,
                        "decided_at": occurred_at,
                        "created_at": occurred_at,
                        "updated_at": occurred_at,
                    },
                )
                connection.execute(
                    tables.requirements.update()
                    .where(
                        tables.requirements.c.tenant_id == tenant_id,
                        tables.requirements.c.id == requirement_id,
                    )
                    .values(status="converted", updated_at=occurred_at)
                )
                case = self._get_record(
                    connection,
                    tenant_id=tenant_id,
                    case_id=case_id,
                )
                writer = EventAuditWriter(
                    connection,
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                )
                writer.record(
                    EventDraft(
                        event_id=f"development-case:{case_id}:created",
                        event_type="DEVELOPMENT_CASE_CREATED",
                        source="development_case_service",
                        entity_id=case_id,
                        payload={
                            "case_code": case.code,
                            "requirement_id": str(requirement_id),
                            "status": case.status,
                        },
                        occurred_at=occurred_at,
                    ),
                    AuditDraft(
                        action="development_case.create",
                        after_snapshot=_case_snapshot(case),
                    ),
                )
                writer.record(
                    EventDraft(
                        event_id=f"requirement:{requirement_id}:converted:{case_id}",
                        event_type="REQUIREMENT_CONVERTED",
                        source="development_case_service",
                        entity_id=requirement_id,
                        payload={
                            "development_case_id": str(case_id),
                            "decision_id": str(decision_id),
                        },
                        occurred_at=occurred_at,
                    ),
                    AuditDraft(
                        action="requirement.convert_to_case",
                        before_snapshot=_requirement_snapshot(requirement),
                        after_snapshot=_requirement_snapshot(requirement, status="converted"),
                    ),
                )
                writer.record(
                    EventDraft(
                        event_id=f"decision:{decision_id}:recorded",
                        event_type="DECISION_RECORDED",
                        source="development_case_service",
                        entity_id=decision_id,
                        payload={
                            "decision_kind": decision.decision_kind,
                            "outcome": decision.outcome,
                        },
                        occurred_at=occurred_at,
                    ),
                    AuditDraft(
                        action="decision.record",
                        after_snapshot=_decision_snapshot(decision),
                    ),
                )
                return ConversionResult(development_case=case, decision=decision)
        except IntegrityError as error:
            constraint = str(error.orig)
            if "uq_development_cases_tenant_requirement" in constraint:
                raise RequirementAlreadyConvertedError from error
            if "uq_development_cases_tenant_code" in constraint:
                raise CaseCodeConflictError from error
            raise

    def update(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        case_id: UUID,
        patch: CaseUpdate,
    ) -> DevelopmentCaseRecord:
        occurred_at = datetime.now(UTC)
        try:
            with self._engine.begin() as connection:
                locked_status = connection.execute(
                    select(tables.development_cases.c.status)
                    .where(
                        tables.development_cases.c.tenant_id == tenant_id,
                        tables.development_cases.c.id == case_id,
                    )
                    .with_for_update()
                ).scalar_one_or_none()
                if locked_status is None:
                    raise DevelopmentCaseNotFoundError
                if locked_status in TERMINAL_CASE_STATUSES:
                    raise CaseTerminalError
                before = self._get_record(connection, tenant_id=tenant_id, case_id=case_id)
                connection.execute(
                    tables.development_cases.update()
                    .where(
                        tables.development_cases.c.tenant_id == tenant_id,
                        tables.development_cases.c.id == case_id,
                    )
                    .values(**patch.changes, updated_at=occurred_at)
                )
                after = self._get_record(connection, tenant_id=tenant_id, case_id=case_id)
                EventAuditWriter(
                    connection,
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                ).record(
                    EventDraft(
                        event_id=f"development-case:{case_id}:updated:{uuid4()}",
                        event_type="DEVELOPMENT_CASE_UPDATED",
                        source="development_case_service",
                        entity_id=case_id,
                        payload={
                            "changed_fields": sorted(patch.changes),
                            "status": after.status,
                        },
                        occurred_at=occurred_at,
                    ),
                    AuditDraft(
                        action="development_case.update",
                        before_snapshot=_case_snapshot(before),
                        after_snapshot=_case_snapshot(after),
                    ),
                )
                return after
        except IntegrityError as error:
            if "uq_development_cases_tenant_code" in str(error.orig):
                raise CaseCodeConflictError from error
            raise

    def transition(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        case_id: UUID,
        to_status: str,
    ) -> DevelopmentCaseRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            locked_status = connection.execute(
                select(tables.development_cases.c.status)
                .where(
                    tables.development_cases.c.tenant_id == tenant_id,
                    tables.development_cases.c.id == case_id,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if locked_status is None:
                raise DevelopmentCaseNotFoundError
            if to_status not in CASE_TRANSITIONS[locked_status]:
                raise CaseInvalidTransitionError
            if to_status == "approved":
                case_row = (
                    connection.execute(
                        select(tables.development_cases).where(
                            tables.development_cases.c.tenant_id == tenant_id,
                            tables.development_cases.c.id == case_id,
                        )
                    )
                    .mappings()
                    .one()
                )
                from app.domain.case_reviews import require_case_reviews_ready

                require_case_reviews_ready(connection, tenant_id, case_row)
                require_case_requirements_ready(connection, tenant_id, case_row)
            if to_status == "converted":
                project_id = connection.execute(
                    select(tables.projects.c.id).where(
                        tables.projects.c.tenant_id == tenant_id,
                        tables.projects.c.development_case_id == case_id,
                    )
                ).scalar_one_or_none()
                if project_id is None:
                    raise CaseProjectRequiredError
            before = self._get_record(connection, tenant_id=tenant_id, case_id=case_id)
            connection.execute(
                tables.development_cases.update()
                .where(
                    tables.development_cases.c.tenant_id == tenant_id,
                    tables.development_cases.c.id == case_id,
                )
                .values(status=to_status, updated_at=occurred_at)
            )
            after = self._get_record(connection, tenant_id=tenant_id, case_id=case_id)
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
            ).record(
                EventDraft(
                    event_id=f"development-case:{case_id}:status:{to_status}:{uuid4()}",
                    event_type="DEVELOPMENT_CASE_STATUS_CHANGED",
                    source="development_case_service",
                    entity_id=case_id,
                    payload={"from_status": before.status, "to_status": after.status},
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="development_case.transition",
                    before_snapshot=_case_snapshot(before),
                    after_snapshot=_case_snapshot(after),
                ),
            )
            return after
