"""AI Finding review and controlled business-application workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Connection, Engine, RowMapping, select, update

from app.ai.quality import FindingQualityService
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.memories import MemoryDraft, memory_content_hash
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

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


type FindingPayload = RiskSuggestionPayload | KnowledgeDraftPayload


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


@dataclass(frozen=True)
class FindingReview:
    decision: Literal["accepted", "rejected"]
    edited_payload: FindingPayload | None = None
    comment: str | None = None


@dataclass(frozen=True)
class FindingApplyResult:
    finding: FindingRecord
    applied_entity_type: Literal["risk", "memory"]
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


class FindingService:
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
        statement = select(tables.findings).where(
            tables.findings.c.tenant_id == tenant_id,
            tables.findings.c.id == finding_id,
        )
        if for_update:
            statement = statement.with_for_update()
        row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            raise FindingNotFoundError
        return _record(row)

    def get(self, *, tenant_id: UUID, finding_id: UUID) -> FindingRecord:
        with self._engine.connect() as connection:
            return self._get(connection, tenant_id=tenant_id, finding_id=finding_id)

    def list(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID | None = None,
        status: str | None = None,
        member_user_id: UUID | None = None,
    ) -> list[FindingRecord]:
        statement = select(tables.findings).where(tables.findings.c.tenant_id == tenant_id)
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
            ]

    def review(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        finding_id: UUID,
        review: FindingReview,
        now: datetime | None = None,
    ) -> FindingRecord:
        reviewed_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            before = self._get(
                connection,
                tenant_id=tenant_id,
                finding_id=finding_id,
                for_update=True,
            )
            self._authorize_user(
                connection,
                tenant_id=tenant_id,
                project_id=before.project_id,
                user_id=actor_user_id,
                action=Action.FINDING_REVIEW,
            )
            if before.status != "pending_review":
                raise FindingInvalidTransitionError
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

    def apply(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        finding_id: UUID,
        now: datetime | None = None,
    ) -> FindingApplyResult:
        applied_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            before = self._get(
                connection,
                tenant_id=tenant_id,
                finding_id=finding_id,
                for_update=True,
            )
            self._authorize_user(
                connection,
                tenant_id=tenant_id,
                project_id=before.project_id,
                user_id=actor_user_id,
                action=Action.FINDING_APPLY,
            )
            if before.status == "applied" and before.applied_entity_id is not None:
                return FindingApplyResult(
                    finding=before,
                    applied_entity_type=(
                        "memory" if before.applied_entity_type == "memory" else "risk"
                    ),
                    applied_entity_id=before.applied_entity_id,
                    idempotent_replay=True,
                )
            if before.status != "accepted" or before.accepted_payload is None:
                raise FindingInvalidTransitionError
            payload = self._revalidate_ground_truth(connection, finding=before)
            if isinstance(payload, RiskSuggestionPayload):
                applied_entity_type: Literal["risk", "memory"] = "risk"
                applied_entity_id = self._create_risk(
                    connection,
                    finding=before,
                    payload=payload,
                    actor_user_id=actor_user_id,
                    applied_at=applied_at,
                )
            else:
                applied_entity_type = "memory"
                applied_entity_id = self._create_memory_draft(
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
        }:
            return RiskSuggestionPayload.model_validate(payload)
        if finding_type == "knowledge_draft":
            return KnowledgeDraftPayload.model_validate(payload)
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
