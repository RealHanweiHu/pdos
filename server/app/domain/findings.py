"""AI Finding review and controlled business-application workflow."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, ClassVar, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Connection, Engine, RowMapping, select, update

from app.ai.quality import FindingQualityService
from app.ai.rollout_guard import employee_finding_visibility, require_live_finding
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain import change_notice_disclosure
from app.domain.change_work_package_proposals import (
    ChangeWorkPackagePayload,
)
from app.domain.change_work_package_proposals import (
    validate_review as validate_change_work_package,
)
from app.domain.cost_reduction_findings import CostReductionPayload
from app.domain.cost_reduction_findings import validate_review as validate_cost_reduction
from app.domain.meeting_action_proposals import MeetingActionPayload, apply_action, validate_action
from app.domain.meeting_business_proposals import (
    MeetingChangePayload,
    MeetingIssuePayload,
    MeetingRiskPayload,
    apply_business,
    validate_business,
)
from app.domain.meeting_decision_proposals import (
    MeetingDecisionPayload,
    apply_decision,
    validate_decision,
)
from app.domain.meeting_minutes_proposals import (
    MeetingMinutesPayload,
    apply_minutes_proposal,
    validate_finding_minutes,
)
from app.domain.memories import MemoryDraft, memory_content_hash
from app.domain.quality_work_packages import (
    QualityWorkPackagePayload,
)
from app.domain.quality_work_packages import (
    authorize as authorize_quality_package,
)
from app.domain.quality_work_packages import (
    validate_review as validate_quality_package,
)
from app.domain.supplier_recovery_findings import (
    SupplierRecoveryPayload,
)
from app.domain.supplier_recovery_findings import (
    authorize as authorize_supplier_recovery,
)
from app.domain.supplier_recovery_findings import (
    validate_review as validate_supplier_recovery,
)
from app.domain.test_plan_changes import (
    TestPlanChangePayload,
    apply_test_plan_change,
    validate_finding_change,
)
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

# `FindingService.list` shadows the builtin inside the class body, so
# annotations there use this alias.
FindingList = list

FINDING_REVIEW_UNDO_SECONDS = 5


class FindingUndoUnavailableError(ValueError):
    pass


FINDING_PREFLIGHT_VERSION = "finding-preflight-v2"


class FindingNotFoundError(LookupError):
    pass


class FindingInvalidTransitionError(ValueError):
    pass


class FindingPayloadInvalidError(ValueError):
    pass


class FindingGroundTruthConflictError(ValueError):
    pass


class FindingApplyPermissionError(PermissionError):
    pass


class FindingApplyNotSupportedError(ValueError):
    pass


class RiskSuggestionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=20_000)
    likelihood: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    mitigation_plan: str | None = Field(default=None, max_length=20_000)
    contingency_plan: str | None = Field(default=None, max_length=20_000)
    target_date: date | None = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "description",
        "mitigation_plan",
        "contingency_plan",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class KnowledgeDraftPayload(BaseModel):
    """Unverified knowledge proposed by Knowledge Lite; never trusted memory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1, max_length=512)
    draft_text: str = Field(min_length=1, max_length=20_000)
    applicability: str | None = Field(default=None, max_length=5_000)

    @field_validator("title", "draft_text", mode="before")
    @classmethod
    def normalize_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("applicability", mode="before")
    @classmethod
    def normalize_applicability(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


type FindingPayload = (
    RiskSuggestionPayload
    | KnowledgeDraftPayload
    | TestPlanChangePayload
    | MeetingMinutesPayload
    | MeetingActionPayload
    | MeetingDecisionPayload
    | MeetingIssuePayload
    | MeetingRiskPayload
    | MeetingChangePayload
    | ChangeWorkPackagePayload
    | SupplierRecoveryPayload
    | CostReductionPayload
    | QualityWorkPackagePayload
)


@dataclass(frozen=True)
class FindingRecord:
    id: UUID
    tenant_id: UUID
    project_id: UUID
    run_id: UUID
    model_invocation_id: UUID
    agent_key: str
    finding_type: str
    origin_key: str
    status: str
    title: str
    summary: str
    proposed_payload: dict[str, Any]
    accepted_payload: dict[str, Any] | None
    evidence_event_ids: tuple[int, ...]
    confidence_basis_points: int
    preflight_version: str
    reviewed_by_user_id: UUID | None
    reviewed_at: datetime | None
    review_comment: str | None
    applied_by_user_id: UUID | None
    applied_at: datetime | None
    applied_entity_type: str | None
    applied_entity_id: UUID | None
    created_at: datetime
    updated_at: datetime
    superseded_by: str | None = None


@dataclass(frozen=True)
class FindingReview:
    decision: Literal["accepted", "rejected"]
    edited_payload: FindingPayload | None = None
    comment: str | None = None


@dataclass(frozen=True)
class FindingApplyResult:
    finding: FindingRecord
    applied_entity_type: str
    applied_entity_id: UUID
    idempotent_replay: bool

    @property
    def risk_id(self) -> UUID | None:
        return self.applied_entity_id if self.applied_entity_type == "risk" else None

    @property
    def memory_id(self) -> UUID | None:
        return self.applied_entity_id if self.applied_entity_type == "memory" else None


def _record(row: RowMapping) -> FindingRecord:
    return FindingRecord(
        id=row["id"],
        tenant_id=row["tenant_id"],
        project_id=row["project_id"],
        run_id=row["run_id"],
        model_invocation_id=row["model_invocation_id"],
        agent_key=str(row["agent_key"]),
        finding_type=str(row["finding_type"]),
        origin_key=str(row["origin_key"]),
        status=str(row["status"]),
        title=str(row["title"]),
        summary=str(row["summary"]),
        proposed_payload=dict(row["proposed_payload"]),
        accepted_payload=(
            dict(row["accepted_payload"]) if row["accepted_payload"] is not None else None
        ),
        evidence_event_ids=tuple(int(value) for value in row["evidence_event_ids"]),
        confidence_basis_points=int(row["confidence_basis_points"]),
        preflight_version=str(row["preflight_version"]),
        reviewed_by_user_id=row["reviewed_by_user_id"],
        reviewed_at=row["reviewed_at"],
        review_comment=row["review_comment"],
        applied_by_user_id=row["applied_by_user_id"],
        applied_at=row["applied_at"],
        applied_entity_type=row["applied_entity_type"],
        applied_entity_id=row["applied_entity_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        superseded_by=row.get("superseded_by"),
    )


def _finding_select() -> Any:
    return (
        select(
            tables.findings,
            tables.agent_runs.c.run_context["superseded_by"].as_string().label("superseded_by"),
        )
        .join(
            tables.agent_runs,
            (tables.agent_runs.c.id == tables.findings.c.run_id)
            & (tables.agent_runs.c.tenant_id == tables.findings.c.tenant_id),
        )
        .where(tables.findings.c.project_id.is_not(None))
    )


def _snapshot(record: FindingRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "project_id": str(record.project_id),
        "finding_type": record.finding_type,
        "status": record.status,
        "title": record.title,
        "accepted_payload": record.accepted_payload,
        "applied_entity_type": record.applied_entity_type,
        "applied_entity_id": (
            str(record.applied_entity_id) if record.applied_entity_id is not None else None
        ),
    }


FINDING_ARCHIVE_TTL_DAYS = 14


class FindingService:
    """Human review and independent apply for agent findings.

    `_APPLY_ADAPTERS` is the closed apply-target whitelist (V1-C1). It is
    populated below the class because the adapters reference this class; the
    declaration here keeps it part of the type rather than an untyped bolt-on.
    """

    _APPLY_ADAPTERS: ClassVar[dict[type[Any], tuple[str, Callable[..., UUID]]]] = {}

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _get(
        connection: Connection,
        *,
        tenant_id: UUID,
        finding_id: UUID,
        for_update: bool = False,
    ) -> FindingRecord:
        statement = _finding_select().where(
            tables.findings.c.tenant_id == tenant_id,
            tables.findings.c.id == finding_id,
            tables.findings.c.finding_type.not_in(("intake_organization", "meeting_plan")),
        )
        if for_update:
            statement = statement.with_for_update(of=tables.findings)
        row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            raise FindingNotFoundError
        return _record(row)

    def get(
        self, *, tenant_id: UUID, finding_id: UUID, actor_user_id: UUID | None = None
    ) -> FindingRecord:
        with self._engine.connect() as connection:
            record = self._get(connection, tenant_id=tenant_id, finding_id=finding_id)
            change_notice_disclosure.require(connection, record, actor_user_id)
            if record.status != "applied":
                require_live_finding(record.agent_key, record.finding_type)
            return record

    def list(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID | None = None,
        status: str | None = None,
        member_user_id: UUID | None = None,
        actor_user_id: UUID | None = None,
    ) -> list[FindingRecord]:
        statement = _finding_select().where(
            tables.findings.c.tenant_id == tenant_id, employee_finding_visibility()
        )
        if member_user_id is not None:
            statement = statement.join(
                tables.project_members,
                (tables.project_members.c.tenant_id == tables.findings.c.tenant_id)
                & (tables.project_members.c.project_id == tables.findings.c.project_id),
            ).where(tables.project_members.c.user_id == member_user_id)
        if project_id is not None:
            statement = statement.where(tables.findings.c.project_id == project_id)
        if status is not None:
            statement = statement.where(tables.findings.c.status == status)
        with self._engine.connect() as connection:
            return [
                _record(row)
                for row in connection.execute(
                    statement.order_by(tables.findings.c.created_at.desc(), tables.findings.c.id)
                ).mappings()
                if change_notice_disclosure.visible(
                    connection, _record(row), actor_user_id or member_user_id
                )
            ]

    def _get_for_action(
        self,
        connection: Connection,
        *,
        tenant_id: UUID,
        finding_id: UUID,
        actor_user_id: UUID | None = None,
    ) -> FindingRecord:
        before = connection.execute(
            select(tables.findings.c.finding_type, tables.findings.c.project_id).where(
                tables.findings.c.tenant_id == tenant_id, tables.findings.c.id == finding_id
            )
        ).one_or_none()
        if before is None:
            raise FindingNotFoundError
        if before.finding_type in {
            "change_work_package",
            "capa_work_package",
            "supplier_recovery",
            "cost_reduction",
        }:
            from app.domain.project_write_lock import lock_project_write_scope

            if not lock_project_write_scope(
                connection, tenant_id=tenant_id, project_id=before.project_id
            ):
                raise FindingGroundTruthConflictError
        record = self._get(connection, tenant_id=tenant_id, finding_id=finding_id, for_update=True)
        change_notice_disclosure.require(connection, record, actor_user_id)
        return record

    def review(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        finding_id: UUID,
        review: FindingReview,
        now: datetime | None = None,
        shared_connection: Connection | None = None,
        expected_updated_at: datetime | None = None,
    ) -> FindingRecord:
        reviewed_at = (now or datetime.now(UTC)).astimezone(UTC)
        transaction = (
            self._engine.begin() if shared_connection is None else nullcontext(shared_connection)
        )
        with transaction as connection:
            before = self._get_for_action(
                connection,
                tenant_id=tenant_id,
                finding_id=finding_id,
                actor_user_id=actor_user_id,
            )
            self._authorize_user(
                connection,
                tenant_id=tenant_id,
                project_id=before.project_id,
                user_id=actor_user_id,
                action=Action.FINDING_REVIEW,
            )
            if expected_updated_at is not None and before.updated_at != expected_updated_at:
                raise FindingGroundTruthConflictError
            if before.status != "pending_review":
                raise FindingInvalidTransitionError
            require_live_finding(before.agent_key, before.finding_type)
            if review.decision == "rejected" and review.edited_payload is not None:
                raise FindingPayloadInvalidError
            accepted_payload = None
            if review.decision == "accepted":
                try:
                    raw_payload = (
                        review.edited_payload.model_dump(mode="json")
                        if review.edited_payload is not None
                        else before.proposed_payload
                    )
                    accepted = self._validated_payload(before.finding_type, raw_payload)
                except ValueError as error:
                    raise FindingPayloadInvalidError from error
                if isinstance(accepted, ChangeWorkPackagePayload):
                    self._authorize_user(
                        connection,
                        tenant_id=tenant_id,
                        project_id=before.project_id,
                        user_id=actor_user_id,
                        action=Action.CHANGE_EDIT,
                    )
                    self._authorize_user(
                        connection,
                        tenant_id=tenant_id,
                        project_id=before.project_id,
                        user_id=actor_user_id,
                        action=Action.PRODUCT_ENGINEERING_VIEW,
                    )
                    validate_change_work_package(connection, before, accepted, actor_user_id)
                if isinstance(accepted, CostReductionPayload):
                    validate_cost_reduction(connection, before, accepted, actor_user_id)
                if isinstance(accepted, SupplierRecoveryPayload):
                    authorize_supplier_recovery(connection, before, actor_user_id)
                    validate_supplier_recovery(connection, before, accepted)
                if isinstance(accepted, QualityWorkPackagePayload):
                    authorize_quality_package(
                        connection, before, actor_user_id, accepted.assessment.phase
                    )
                    validate_quality_package(connection, before, accepted)
                if isinstance(accepted, TestPlanChangePayload):
                    validate_finding_change(connection, before, accepted)
                if isinstance(
                    accepted, (MeetingIssuePayload, MeetingRiskPayload, MeetingChangePayload)
                ):
                    validate_business(connection, before, accepted)
                if isinstance(accepted, MeetingDecisionPayload):
                    validate_decision(connection, before, accepted)
                if isinstance(accepted, MeetingActionPayload):
                    validate_action(connection, before, accepted)
                if isinstance(accepted, MeetingMinutesPayload):
                    validate_finding_minutes(connection, before, accepted)
                accepted_payload = accepted.model_dump(mode="json")
            review_values: dict[str, object] = {
                "status": review.decision,
                "reviewed_by_user_id": actor_user_id,
                "reviewed_at": reviewed_at,
                "review_comment": review.comment,
                "updated_at": reviewed_at,
            }
            if accepted_payload is not None:
                review_values["accepted_payload"] = accepted_payload
            connection.execute(
                update(tables.findings)
                .where(
                    tables.findings.c.tenant_id == tenant_id,
                    tables.findings.c.id == finding_id,
                    tables.findings.c.status == "pending_review",
                )
                .values(**review_values)
            )
            after = self._get(connection, tenant_id=tenant_id, finding_id=finding_id)
            connection.execute(
                tables.finding_actions.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": before.project_id,
                    "finding_id": finding_id,
                    "action": review.decision,
                    "actor_user_id": actor_user_id,
                    "from_status": "pending_review",
                    "to_status": review.decision,
                    "detail": {"comment": review.comment},
                    "created_at": reviewed_at,
                },
            )
            self._feedback_event(
                connection,
                before=before,
                after=after,
                actor_user_id=actor_user_id,
                decision=review.decision,
                occurred_at=reviewed_at,
            )
            FindingQualityService(self._engine).evaluate_connection(
                connection,
                tenant_id=tenant_id,
                evaluated_at=reviewed_at,
            )
            return after

    def undo_review(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        finding_id: UUID,
        expected_updated_at: datetime,
        comment: str,
        shared_connection: Connection,
    ) -> FindingRecord:
        connection = shared_connection
        before = self._get_for_action(
            connection, tenant_id=tenant_id, finding_id=finding_id, actor_user_id=actor_user_id
        )
        self._authorize_user(
            connection,
            tenant_id=tenant_id,
            project_id=before.project_id,
            user_id=actor_user_id,
            action=Action.FINDING_REVIEW,
        )
        now = datetime.now(UTC)
        if (
            before.status not in {"accepted", "rejected"}
            or before.reviewed_by_user_id != actor_user_id
            or before.reviewed_at is None
            or before.superseded_by
            or before.applied_entity_id is not None
            or before.updated_at != expected_updated_at
            or not (
                before.reviewed_at
                <= now
                <= before.reviewed_at + timedelta(seconds=FINDING_REVIEW_UNDO_SECONDS)
            )
        ):
            raise FindingUndoUnavailableError
        require_live_finding(before.agent_key, before.finding_type)
        previous_action = connection.execute(
            select(tables.finding_actions.c.id).where(
                tables.finding_actions.c.tenant_id == tenant_id,
                tables.finding_actions.c.finding_id == finding_id,
                tables.finding_actions.c.action == before.status,
                tables.finding_actions.c.actor_user_id == actor_user_id,
                tables.finding_actions.c.created_at == before.reviewed_at,
            )
        ).scalar_one_or_none()
        if previous_action is None:
            raise FindingUndoUnavailableError
        connection.execute(
            update(tables.findings)
            .where(tables.findings.c.tenant_id == tenant_id, tables.findings.c.id == finding_id)
            .values(
                status="pending_review",
                accepted_payload=None,
                reviewed_by_user_id=None,
                reviewed_at=None,
                review_comment=None,
                updated_at=now,
            )
        )
        after = self._get(connection, tenant_id=tenant_id, finding_id=finding_id)
        self._record_lifecycle_action(
            connection,
            before=before,
            after=after,
            actor_user_id=actor_user_id,
            action="review_undone",
            from_status=before.status,
            to_status="pending_review",
            occurred_at=now,
            detail={
                "comment": comment,
                "undone_action_id": str(previous_action),
                "reviewed_at": before.reviewed_at.isoformat(),
                "review_comment": before.review_comment,
                "accepted_payload": before.accepted_payload,
                "window_seconds": FINDING_REVIEW_UNDO_SECONDS,
            },
        )
        FindingQualityService(self._engine).evaluate_connection(
            connection, tenant_id=tenant_id, evaluated_at=now
        )
        return after

    def apply(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        finding_id: UUID,
        now: datetime | None = None,
        shared_connection: Connection | None = None,
        expected_updated_at: datetime | None = None,
    ) -> FindingApplyResult:
        applied_at = (now or datetime.now(UTC)).astimezone(UTC)
        transaction = (
            self._engine.begin() if shared_connection is None else nullcontext(shared_connection)
        )
        with transaction as connection:
            before = self._get_for_action(
                connection,
                tenant_id=tenant_id,
                finding_id=finding_id,
                actor_user_id=actor_user_id,
            )
            self._authorize_user(
                connection,
                tenant_id=tenant_id,
                project_id=before.project_id,
                user_id=actor_user_id,
                action=Action.FINDING_APPLY,
            )
            if expected_updated_at is not None and before.updated_at != expected_updated_at:
                raise FindingGroundTruthConflictError
            if before.status == "applied" and before.applied_entity_id is not None:
                return FindingApplyResult(
                    finding=before,
                    applied_entity_type=str(before.applied_entity_type),
                    applied_entity_id=before.applied_entity_id,
                    idempotent_replay=True,
                )
            if before.status != "accepted" or before.accepted_payload is None:
                raise FindingInvalidTransitionError
            require_live_finding(before.agent_key, before.finding_type)
            payload = self._revalidate_ground_truth(connection, finding=before)
            # D16/D32: apply targets are a closed, typed whitelist. Each payload
            # type maps to exactly one adapter; anything unmapped fails closed.
            adapter = self._APPLY_ADAPTERS.get(type(payload))
            if adapter is None:
                raise FindingInvalidTransitionError
            applied_entity_type, handler = adapter
            applied_entity_id = handler(
                self,
                connection,
                finding=before,
                payload=payload,
                actor_user_id=actor_user_id,
                applied_at=applied_at,
            )
            connection.execute(
                update(tables.findings)
                .where(
                    tables.findings.c.tenant_id == tenant_id,
                    tables.findings.c.id == finding_id,
                    tables.findings.c.status == "accepted",
                )
                .values(
                    status="applied",
                    applied_by_user_id=actor_user_id,
                    applied_at=applied_at,
                    applied_entity_type=applied_entity_type,
                    applied_entity_id=applied_entity_id,
                    updated_at=applied_at,
                )
            )
            after = self._get(connection, tenant_id=tenant_id, finding_id=finding_id)
            connection.execute(
                tables.finding_actions.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": before.project_id,
                    "finding_id": finding_id,
                    "action": "applied",
                    "actor_user_id": actor_user_id,
                    "from_status": "accepted",
                    "to_status": "applied",
                    "detail": {
                        "entity_type": applied_entity_type,
                        "entity_id": str(applied_entity_id),
                    },
                    "created_at": applied_at,
                },
            )
            self._feedback_event(
                connection,
                before=before,
                after=after,
                actor_user_id=actor_user_id,
                decision="applied",
                occurred_at=applied_at,
            )
            FindingQualityService(self._engine).evaluate_connection(
                connection,
                tenant_id=tenant_id,
                evaluated_at=applied_at,
            )
            return FindingApplyResult(
                finding=after,
                applied_entity_type=applied_entity_type,
                applied_entity_id=applied_entity_id,
                idempotent_replay=False,
            )

    def archive_stale(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID | None,
        member_user_id: UUID | None = None,
        ttl_days: int = FINDING_ARCHIVE_TTL_DAYS,
        project_id: UUID | None = None,
        automatic: bool = False,
        now: datetime | None = None,
    ) -> FindingList[FindingRecord]:
        """Archive pending findings older than the TTL (V1-A10 review fatigue).

        Reversible via restore(); every transition leaves an action row, an
        AI_FEEDBACK_RECEIVED event, and an audit entry.
        """
        if not 1 <= ttl_days <= 365:
            raise FindingPayloadInvalidError
        if automatic:
            if (
                actor_user_id is not None
                or project_id is None
                or ttl_days != FINDING_ARCHIVE_TTL_DAYS
            ):
                raise FindingApplyPermissionError
        elif actor_user_id is None:
            raise FindingApplyPermissionError
        archived_at = (now or datetime.now(UTC)).astimezone(UTC)
        cutoff = archived_at - timedelta(days=ttl_days)
        statement = select(tables.findings.c.id).where(
            tables.findings.c.tenant_id == tenant_id,
            tables.findings.c.status == "pending_review",
            tables.findings.c.updated_at < cutoff,
            tables.findings.c.scope_kind == "project",
            employee_finding_visibility(),
            tables.findings.c.finding_type.not_in(("intake_organization", "meeting_plan")),
        )
        if project_id is not None:
            statement = statement.where(tables.findings.c.project_id == project_id)
        if member_user_id is not None:
            statement = statement.join(
                tables.project_members,
                (tables.project_members.c.tenant_id == tables.findings.c.tenant_id)
                & (tables.project_members.c.project_id == tables.findings.c.project_id),
            ).where(tables.project_members.c.user_id == member_user_id)
        archived: list[FindingRecord] = []
        with self._engine.begin() as connection:
            if automatic:
                active = connection.execute(
                    select(tables.projects.c.id)
                    .join(tables.tenants, tables.tenants.c.id == tables.projects.c.tenant_id)
                    .where(
                        tables.projects.c.tenant_id == tenant_id,
                        tables.projects.c.id == project_id,
                        tables.projects.c.status != "archived",
                        tables.tenants.c.status == "active",
                    )
                ).scalar_one_or_none()
                if active is None:
                    return []
            stale_ids = [
                row.id
                for row in connection.execute(
                    statement.order_by(tables.findings.c.updated_at, tables.findings.c.id).limit(
                        200
                    )
                )
            ]
            for finding_id in stale_ids:
                before = self._get(
                    connection, tenant_id=tenant_id, finding_id=finding_id, for_update=True
                )
                if actor_user_id is not None and not change_notice_disclosure.visible(
                    connection, before, actor_user_id
                ):
                    continue
                if before.status != "pending_review" or before.updated_at >= cutoff:
                    continue
                if actor_user_id is not None:
                    self._authorize_user(
                        connection,
                        tenant_id=tenant_id,
                        project_id=before.project_id,
                        user_id=actor_user_id,
                        action=Action.FINDING_REVIEW,
                    )
                connection.execute(
                    update(tables.findings)
                    .where(
                        tables.findings.c.tenant_id == tenant_id,
                        tables.findings.c.id == finding_id,
                        tables.findings.c.status == "pending_review",
                    )
                    .values(status="archived", updated_at=archived_at)
                )
                after = self._get(connection, tenant_id=tenant_id, finding_id=finding_id)
                self._record_lifecycle_action(
                    connection,
                    before=before,
                    after=after,
                    actor_user_id=actor_user_id,
                    action="archived",
                    from_status="pending_review",
                    to_status="archived",
                    detail={
                        "ttl_days": ttl_days,
                        "policy": "finding-inactivity-v1",
                        "automatic": automatic,
                        "inactive_since": before.updated_at.isoformat(),
                    },
                    occurred_at=archived_at,
                )
                archived.append(after)
            return archived

    def restore(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        finding_id: UUID,
        now: datetime | None = None,
    ) -> FindingRecord:
        """Return an archived finding to the review inbox (V1-A10)."""
        restored_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            before = self._get(
                connection, tenant_id=tenant_id, finding_id=finding_id, for_update=True
            )
            self._authorize_user(
                connection,
                tenant_id=tenant_id,
                project_id=before.project_id,
                user_id=actor_user_id,
                action=Action.FINDING_REVIEW,
            )
            change_notice_disclosure.require(connection, before, actor_user_id)
            if before.status != "archived":
                raise FindingInvalidTransitionError
            require_live_finding(before.agent_key, before.finding_type)
            connection.execute(
                update(tables.findings)
                .where(
                    tables.findings.c.tenant_id == tenant_id,
                    tables.findings.c.id == finding_id,
                    tables.findings.c.status == "archived",
                )
                .values(status="pending_review", updated_at=restored_at)
            )
            after = self._get(connection, tenant_id=tenant_id, finding_id=finding_id)
            self._record_lifecycle_action(
                connection,
                before=before,
                after=after,
                actor_user_id=actor_user_id,
                action="restored",
                from_status="archived",
                to_status="pending_review",
                detail={},
                occurred_at=restored_at,
            )
            return after

    @staticmethod
    def _record_lifecycle_action(
        connection: Connection,
        *,
        before: FindingRecord,
        after: FindingRecord,
        actor_user_id: UUID | None,
        action: str,
        from_status: str,
        to_status: str,
        detail: dict[str, object],
        occurred_at: datetime,
    ) -> None:
        connection.execute(
            tables.finding_actions.insert(),
            {
                "id": uuid4(),
                "tenant_id": before.tenant_id,
                "project_id": before.project_id,
                "finding_id": before.id,
                "action": action,
                "actor_user_id": actor_user_id,
                "from_status": from_status,
                "to_status": to_status,
                "detail": detail,
                "created_at": occurred_at,
            },
        )
        EventAuditWriter(
            connection,
            tenant_id=before.tenant_id,
            actor_user_id=actor_user_id,
            project_id=before.project_id,
        ).record(
            EventDraft(
                event_id=f"ai-finding:{before.id}:{action}:{uuid4()}",
                event_type="AI_FEEDBACK_RECEIVED",
                source="finding_review_service",
                entity_id=before.id,
                payload={"finding_id": str(before.id), "decision": action},
                occurred_at=occurred_at,
            ),
            AuditDraft(
                action=f"finding.{action}",
                before_snapshot=_snapshot(before),
                after_snapshot=_snapshot(after),
            ),
        )

    @staticmethod
    def _create_risk(
        connection: Connection,
        *,
        finding: FindingRecord,
        payload: RiskSuggestionPayload,
        actor_user_id: UUID,
        applied_at: datetime,
    ) -> UUID:
        risk_id = uuid4()
        connection.execute(
            tables.risks.insert(),
            {
                "id": risk_id,
                "tenant_id": finding.tenant_id,
                "project_id": finding.project_id,
                "title": payload.title,
                "description": payload.description,
                "status": "open",
                "likelihood": payload.likelihood,
                "impact": payload.impact,
                "mitigation_plan": payload.mitigation_plan,
                "contingency_plan": payload.contingency_plan,
                "target_date": payload.target_date,
                "created_at": applied_at,
                "updated_at": applied_at,
            },
        )
        EventAuditWriter(
            connection,
            tenant_id=finding.tenant_id,
            actor_user_id=actor_user_id,
            project_id=finding.project_id,
        ).record(
            EventDraft(
                event_id=f"risk:{risk_id}:created",
                event_type="RISK_CREATED",
                source="risk_service",
                entity_id=risk_id,
                payload={
                    "risk_id": str(risk_id),
                    "score": payload.likelihood * payload.impact,
                    "status": "open",
                },
                occurred_at=applied_at,
            ),
            AuditDraft(
                action="risk.create_from_finding",
                after_snapshot={
                    "id": str(risk_id),
                    "project_id": str(finding.project_id),
                    "title": payload.title,
                    "status": "open",
                    "likelihood": payload.likelihood,
                    "impact": payload.impact,
                },
                context={"finding_id": str(finding.id)},
            ),
        )
        return risk_id

    @staticmethod
    def _create_memory_draft(
        connection: Connection,
        *,
        finding: FindingRecord,
        payload: KnowledgeDraftPayload,
        actor_user_id: UUID,
        applied_at: datetime,
    ) -> UUID:
        memory_id = uuid4()
        draft = MemoryDraft(
            title=payload.title,
            content=payload.draft_text,
            applicability=payload.applicability,
        )
        event_refs = list(
            connection.execute(
                select(tables.events.c.event_id)
                .where(
                    tables.events.c.tenant_id == finding.tenant_id,
                    tables.events.c.project_id == finding.project_id,
                    tables.events.c.id.in_(finding.evidence_event_ids),
                )
                .order_by(tables.events.c.id)
            ).scalars()
        )
        connection.execute(
            tables.memories.insert(),
            {
                "id": memory_id,
                "tenant_id": finding.tenant_id,
                "project_id": finding.project_id,
                "source_finding_id": finding.id,
                "created_by_user_id": actor_user_id,
                "title": draft.title,
                "content": draft.content,
                "applicability": draft.applicability,
                "tags": [],
                "source_refs": [
                    {"kind": "event", "reference": event_id} for event_id in event_refs
                ],
                "content_sha256": memory_content_hash(draft),
                "status": "draft",
                "created_at": applied_at,
                "updated_at": applied_at,
            },
        )
        EventAuditWriter(
            connection,
            tenant_id=finding.tenant_id,
            actor_user_id=actor_user_id,
            project_id=finding.project_id,
        ).record(
            EventDraft(
                event_id=f"memory:{memory_id}:draft-created",
                event_type="MEMORY_DRAFT_CREATED",
                source="memory_service",
                entity_id=memory_id,
                payload={"memory_id": str(memory_id), "source_type": "finding"},
                occurred_at=applied_at,
            ),
            AuditDraft(
                action="memory.create_from_finding",
                after_snapshot={
                    "id": str(memory_id),
                    "project_id": str(finding.project_id),
                    "source_finding_id": str(finding.id),
                    "title": draft.title,
                    "content": draft.content,
                    "applicability": draft.applicability,
                    "tags": [],
                    "source_refs": [
                        {"kind": "event", "reference": event_id} for event_id in event_refs
                    ],
                    "content_sha256": memory_content_hash(draft),
                    "status": "draft",
                },
                context={"finding_id": str(finding.id)},
            ),
        )
        return memory_id

    @staticmethod
    def _authorize_user(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        user_id: UUID,
        action: Action,
    ) -> None:
        user = (
            connection.execute(
                select(tables.users.c.role, tables.users.c.is_active).where(
                    tables.users.c.tenant_id == tenant_id,
                    tables.users.c.id == user_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if user is None or not user["is_active"]:
            raise FindingApplyPermissionError
        role = Role(str(user["role"]))
        if not is_allowed(role, action):
            raise FindingApplyPermissionError
        if role not in {Role.OWNER, Role.ADMIN}:
            member = connection.execute(
                select(tables.project_members.c.id).where(
                    tables.project_members.c.tenant_id == tenant_id,
                    tables.project_members.c.project_id == project_id,
                    tables.project_members.c.user_id == user_id,
                )
            ).scalar_one_or_none()
            if member is None:
                raise FindingApplyPermissionError

    @staticmethod
    def _revalidate_ground_truth(
        connection: Connection,
        *,
        finding: FindingRecord,
    ) -> FindingPayload:
        project_status = connection.execute(
            select(tables.projects.c.status).where(
                tables.projects.c.tenant_id == finding.tenant_id,
                tables.projects.c.id == finding.project_id,
            )
        ).scalar_one_or_none()
        if project_status is None or project_status in {"completed", "archived"}:
            raise FindingGroundTruthConflictError
        run = (
            connection.execute(
                select(
                    tables.agent_runs.c.agent_key,
                    tables.agent_runs.c.status,
                    tables.agent_runs.c.event_row_ids,
                ).where(
                    tables.agent_runs.c.tenant_id == finding.tenant_id,
                    tables.agent_runs.c.project_id == finding.project_id,
                    tables.agent_runs.c.id == finding.run_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        invocation = connection.execute(
            select(tables.model_invocations.c.id).where(
                tables.model_invocations.c.tenant_id == finding.tenant_id,
                tables.model_invocations.c.project_id == finding.project_id,
                tables.model_invocations.c.run_id == finding.run_id,
                tables.model_invocations.c.id == finding.model_invocation_id,
                tables.model_invocations.c.agent_key == finding.agent_key,
                tables.model_invocations.c.status == "succeeded",
            )
        ).scalar_one_or_none()
        event_ids = set(
            connection.execute(
                select(tables.events.c.id).where(
                    tables.events.c.tenant_id == finding.tenant_id,
                    tables.events.c.project_id == finding.project_id,
                    tables.events.c.id.in_(finding.evidence_event_ids),
                )
            ).scalars()
        )
        if (
            run is None
            or run["agent_key"] != finding.agent_key
            or run["status"] not in {"succeeded", "degraded"}
            or not set(finding.evidence_event_ids).issubset(set(run["event_row_ids"]))
            or invocation is None
            or event_ids != set(finding.evidence_event_ids)
        ):
            raise FindingGroundTruthConflictError
        accepted_payload = finding.accepted_payload
        if accepted_payload is None:
            raise FindingPayloadInvalidError
        try:
            payload = FindingService._validated_payload(
                finding.finding_type,
                accepted_payload,
            )
        except ValueError as error:
            raise FindingPayloadInvalidError from error
        return payload

    @staticmethod
    def _validated_payload(
        finding_type: str,
        payload: dict[str, Any],
    ) -> FindingPayload:
        if finding_type in {
            "risk_suggestion",
            "blocker_alert",
            "gate_readiness_anomaly",
            "bom_impact_suggestion",
            "change_impact_suggestion",
            "quality_cluster_alert",
            "capa_suggestion",
            "supplier_delay_risk",
            "executive_portfolio_brief",
        }:
            return RiskSuggestionPayload.model_validate(payload)
        if finding_type == "cost_reduction":
            return CostReductionPayload.model_validate(payload)
        if finding_type == "supplier_recovery":
            return SupplierRecoveryPayload.model_validate(payload)
        if finding_type == "capa_work_package":
            return QualityWorkPackagePayload.model_validate(payload)
        if finding_type == "change_work_package":
            return ChangeWorkPackagePayload.model_validate(payload)
        if finding_type == "knowledge_draft":
            return KnowledgeDraftPayload.model_validate(payload)
        if finding_type == "test_plan_change":
            return TestPlanChangePayload.model_validate(payload)
        if finding_type == "meeting_issue":
            return MeetingIssuePayload.model_validate(payload)
        if finding_type == "meeting_risk":
            return MeetingRiskPayload.model_validate(payload)
        if finding_type == "meeting_change":
            return MeetingChangePayload.model_validate(payload)
        if finding_type == "meeting_decision":
            return MeetingDecisionPayload.model_validate(payload)
        if finding_type == "meeting_action":
            return MeetingActionPayload.model_validate(payload)
        if finding_type == "meeting_minutes":
            return MeetingMinutesPayload.model_validate(payload)
        raise FindingPayloadInvalidError

    @staticmethod
    def _feedback_event(
        connection: Connection,
        *,
        before: FindingRecord,
        after: FindingRecord,
        actor_user_id: UUID,
        decision: str,
        occurred_at: datetime,
    ) -> None:
        EventAuditWriter(
            connection,
            tenant_id=before.tenant_id,
            actor_user_id=actor_user_id,
            project_id=before.project_id,
        ).record(
            EventDraft(
                event_id=f"ai-finding:{before.id}:{decision}",
                event_type="AI_FEEDBACK_RECEIVED",
                source="finding_review_service",
                entity_id=before.id,
                payload={"finding_id": str(before.id), "decision": decision},
                occurred_at=occurred_at,
            ),
            AuditDraft(
                action=f"finding.{decision}",
                before_snapshot=_snapshot(before),
                after_snapshot=_snapshot(after),
            ),
        )


def _apply_risk_adapter(service: FindingService, connection: Connection, **kwargs: Any) -> UUID:
    return FindingService._create_risk(connection, **kwargs)


def _apply_memory_adapter(service: FindingService, connection: Connection, **kwargs: Any) -> UUID:
    return service._create_memory_draft(connection, **kwargs)


def _apply_test_plan_adapter(
    service: FindingService, connection: Connection, **kwargs: Any
) -> UUID:
    del service
    return apply_test_plan_change(connection, **kwargs)


def _apply_business_adapter(service: FindingService, connection: Connection, **kwargs: Any) -> UUID:
    return apply_business(service._engine, connection, **kwargs)


def _apply_decision_adapter(service: FindingService, connection: Connection, **kwargs: Any) -> UUID:
    return apply_decision(service._engine, connection, **kwargs)


def _apply_action_adapter(service: FindingService, connection: Connection, **kwargs: Any) -> UUID:
    return apply_action(service._engine, connection, **kwargs)


def _apply_minutes_adapter(service: FindingService, connection: Connection, **kwargs: Any) -> UUID:
    return apply_minutes_proposal(service._engine, connection, **kwargs)


def _apply_change_package_adapter(
    service: FindingService, connection: Connection, **kwargs: Any
) -> UUID:
    from app.domain.change_work_package_proposals import apply_package

    return apply_package(connection, **kwargs)


def _apply_quality_package_adapter(
    _service: FindingService, connection: Connection, **kwargs: Any
) -> UUID:
    from app.domain.quality_work_packages import apply_package

    return apply_package(connection, **kwargs)


def _apply_supplier_recovery_adapter(
    _service: FindingService, connection: Connection, **kwargs: Any
) -> UUID:
    from app.domain.supplier_recovery_findings import apply_package

    return apply_package(connection, **kwargs)


def _apply_cost_reduction_adapter(
    _service: FindingService, connection: Connection, **kwargs: Any
) -> UUID:
    from app.domain.cost_reduction_findings import apply_package

    return apply_package(connection, **kwargs)


# Registered after all adapters exist; the class declares the attribute so the
# whitelist is part of the type rather than bolted on at import time.
FindingService._APPLY_ADAPTERS = {
    CostReductionPayload: ("cost_reduction", _apply_cost_reduction_adapter),
    SupplierRecoveryPayload: ("supplier_recovery", _apply_supplier_recovery_adapter),
    QualityWorkPackagePayload: ("quality_work_package", _apply_quality_package_adapter),
    ChangeWorkPackagePayload: ("change_impact_scope", _apply_change_package_adapter),
    RiskSuggestionPayload: ("risk", _apply_risk_adapter),
    KnowledgeDraftPayload: ("memory", _apply_memory_adapter),
    TestPlanChangePayload: ("test_plan", _apply_test_plan_adapter),
    MeetingMinutesPayload: ("meeting_minutes", _apply_minutes_adapter),
    MeetingActionPayload: ("task", _apply_action_adapter),
    MeetingDecisionPayload: ("decision", _apply_decision_adapter),
    MeetingIssuePayload: ("issue", _apply_business_adapter),
    MeetingRiskPayload: ("risk", _apply_business_adapter),
    MeetingChangePayload: ("ecr", _apply_business_adapter),
}
