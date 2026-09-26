"""Meeting Issue/Risk/ECR candidates; independent human application to real lifecycles."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.db.schema import tables
from app.domain.meeting_action_proposals import validate_quotes
from app.domain.meeting_minutes_proposals import MinutesQuote
from app.domain.product_workspace import digest
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

if TYPE_CHECKING:
    from app.domain.findings import FindingRecord


class MeetingBusinessProposalError(ValueError):
    pass


class BusinessSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    kind: Literal["issue", "risk", "change"]
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1, max_length=5000)
    suggested_response: str | None = Field(default=None, max_length=3000)
    citations: tuple[MinutesQuote, ...] = Field(min_length=1, max_length=8)


class MeetingBusinessAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    disposition: Literal["proposals", "insufficient_evidence"]
    proposals: tuple[BusinessSuggestion, ...] = Field(max_length=15)
    open_questions: tuple[str, ...] = Field(max_length=15)

    @model_validator(mode="after")
    def shape(self) -> Self:
        if (self.disposition == "proposals") != bool(self.proposals):
            raise ValueError("Proposals require evidence")
        if any(not q.strip() or len(q) > 2000 for q in self.open_questions):
            raise ValueError("Questions must be nonblank and bounded")
        return self


class BusinessPayload(BusinessSuggestion):
    meeting_id: UUID
    transcript_id: UUID
    source_digest: str = Field(pattern="^[0-9a-f]{64}$")
    member_options: tuple[dict[str, Any], ...]
    details_confirmed: bool = False


class MeetingIssuePayload(BusinessPayload):
    kind: Literal["issue"] = "issue"
    owner_id: UUID | None = None
    verifier_id: UUID | None = None
    target_date: date | None = None
    issue_type: (
        Literal["engineering", "quality", "supplier", "test_failure", "certification"] | None
    ) = None
    severity: Literal["low", "medium", "high", "critical"] | None = None
    closure_criteria: str | None = Field(default=None, max_length=5000)


class MeetingRiskPayload(BusinessPayload):
    kind: Literal["risk"] = "risk"
    owner_id: UUID | None = None
    target_date: date | None = None
    likelihood: int | None = Field(default=None, ge=1, le=5)
    impact: int | None = Field(default=None, ge=1, le=5)
    mitigation_plan: str | None = Field(default=None, max_length=5000)
    contingency_plan: str | None = Field(default=None, max_length=5000)


class MeetingChangePayload(BusinessPayload):
    kind: Literal["change"] = "change"
    code: str | None = Field(default=None, min_length=1, max_length=64)


type MeetingBusinessPayload = MeetingIssuePayload | MeetingRiskPayload | MeetingChangePayload
PAYLOAD_TYPES: dict[
    str, type[MeetingIssuePayload] | type[MeetingRiskPayload] | type[MeetingChangePayload]
] = {
    "issue": MeetingIssuePayload,
    "risk": MeetingRiskPayload,
    "change": MeetingChangePayload,
}


def prompt_data() -> dict[str, Any]:
    return dict(
        json.loads((Path(__file__).parents[1] / "ai/prompts/meeting_business_v1.json").read_text())
    )


def validate_business(
    connection: Connection, finding: FindingRecord, payload: MeetingBusinessPayload
) -> None:
    from app.ai.meeting_reading import source_state
    from app.domain.tasks import TaskScopeError, TaskService

    row = (
        connection.execute(
            select(tables.agent_runs).where(
                tables.agent_runs.c.tenant_id == finding.tenant_id,
                tables.agent_runs.c.project_id == finding.project_id,
                tables.agent_runs.c.id == finding.run_id,
                tables.agent_runs.c.context_version == "meeting-business-request-v1",
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or not row["run_context"].get("reading_propose_business"):
        raise MeetingBusinessProposalError("建议缺少实际生成运行")
    snapshot = row["run_context"]["reading_source"]
    current = source_state(
        connection, finding.tenant_id, finding.project_id, payload.meeting_id, payload.transcript_id
    )
    if current != {k: v for k, v in snapshot.items() if k != "business_options"}:
        raise MeetingBusinessProposalError("会议、转写或说话人已变化，请重新整理")
    serialized = payload.model_dump(mode="json")
    if any(
        serialized.get(k) != finding.proposed_payload.get(k)
        for k in (
            "kind",
            "meeting_id",
            "transcript_id",
            "source_digest",
            "member_options",
            "citations",
            "suggested_response",
        )
    ):
        raise MeetingBusinessProposalError("不能改写候选类别或原始转写依据")
    validate_quotes(snapshot, payload.citations)
    if not payload.details_confirmed:
        raise MeetingBusinessProposalError("请逐项核对本候选后再接受")
    people: list[UUID | None] = []
    if isinstance(payload, MeetingIssuePayload):
        if (
            not payload.owner_id
            or not payload.target_date
            or not payload.issue_type
            or not payload.severity
            or not (payload.closure_criteria or "").strip()
        ):
            raise MeetingBusinessProposalError("请核对问题类别、级别、负责人、日期和关闭标准")
        if payload.severity in {"high", "critical"} and (
            not payload.verifier_id or payload.verifier_id == payload.owner_id
        ):
            raise MeetingBusinessProposalError("高或严重问题须指定不同于负责人的验证人")
        people = [payload.owner_id, payload.verifier_id]
    elif isinstance(payload, MeetingRiskPayload):
        if (
            not payload.owner_id
            or not payload.target_date
            or payload.likelihood is None
            or payload.impact is None
            or not (payload.mitigation_plan or "").strip()
        ):
            raise MeetingBusinessProposalError("请核对风险负责人、日期、可能性、影响和缓解计划")
        people = [payload.owner_id]
    else:
        if not payload.code:
            raise MeetingBusinessProposalError("请填写变更申请编号")
        if connection.execute(
            select(tables.engineering_change_requests.c.id).where(
                tables.engineering_change_requests.c.tenant_id == finding.tenant_id,
                tables.engineering_change_requests.c.project_id == finding.project_id,
                tables.engineering_change_requests.c.code == payload.code,
            )
        ).first():
            raise MeetingBusinessProposalError("变更申请编号已使用，请核对原申请或调整编号")
    try:
        for user_id in people:
            TaskService._validate_member(
                connection,
                tenant_id=finding.tenant_id,
                project_id=finding.project_id,
                user_id=user_id,
            )
    except TaskScopeError as error:
        raise MeetingBusinessProposalError("所选责任人已无当前项目办理资格") from error


def persist_business(
    connection: Connection,
    *,
    row: Any,
    snapshot: dict[str, Any],
    output: dict[str, Any],
    invocation_id: UUID,
    created_at: datetime,
) -> list[str]:
    from app.ai.meeting_reading import source_state
    from app.ai.quality import FindingQualityService
    from app.ai.rollout_guard import require_live_finding
    from app.domain.findings import FINDING_PREFLIGHT_VERSION

    if (
        source_state(
            connection,
            row["tenant_id"],
            row["project_id"],
            UUID(snapshot["meeting_id"]),
            UUID(snapshot["transcript_id"]),
            include_business=True,
        )
        != snapshot
    ):
        raise MeetingBusinessProposalError("生成期间来源已变化，请重新整理")
    results = []
    for item in MeetingBusinessAssessment.model_validate(output).proposals:
        finding_type = "meeting_" + item.kind
        require_live_finding("knowledge_lite", finding_type)
        if not FindingQualityService.is_output_allowed_connection(
            connection,
            tenant_id=row["tenant_id"],
            agent_key="knowledge_lite",
            finding_type=finding_type,
        ):
            raise MeetingBusinessProposalError("本类候选质量控制已收窄")
        validate_quotes(snapshot, item.citations)
        payload = PAYLOAD_TYPES[item.kind].model_validate(
            {
                **item.model_dump(),
                "meeting_id": snapshot["meeting_id"],
                "transcript_id": snapshot["transcript_id"],
                "source_digest": snapshot["transcript_digest"],
                "member_options": snapshot["business_options"],
            }
        )
        origin = "meeting-business:" + digest(
            {
                "kind": item.kind,
                "title": item.title,
                "meeting": snapshot["meeting_id"],
                "transcript": snapshot["transcript_id"],
                "quotes": sorted((str(q.segment_id), q.exact_quote) for q in item.citations),
            }
        )
        existing = connection.execute(
            select(tables.findings.c.id).where(
                tables.findings.c.tenant_id == row["tenant_id"],
                tables.findings.c.run_id == row["id"],
                tables.findings.c.origin_key == origin,
            )
        ).scalar_one_or_none()
        if existing is not None:
            results.append(str(existing))
            continue
        finding_id = uuid4()
        connection.execute(
            tables.findings.insert().values(
                id=finding_id,
                tenant_id=row["tenant_id"],
                project_id=row["project_id"],
                run_id=row["id"],
                model_invocation_id=invocation_id,
                agent_key="knowledge_lite",
                finding_type=finding_type,
                origin_key=origin,
                status="pending_review",
                title=payload.title,
                summary=payload.description,
                proposed_payload=payload.model_dump(mode="json"),
                evidence_event_ids=[],
                confidence_basis_points=0,
                preflight_version=FINDING_PREFLIGHT_VERSION,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        connection.execute(
            tables.finding_actions.insert().values(
                id=uuid4(),
                tenant_id=row["tenant_id"],
                project_id=row["project_id"],
                finding_id=finding_id,
                action="created",
                actor_user_id=None,
                to_status="pending_review",
                detail={"source": "meeting_transcript"},
                created_at=created_at,
            )
        )
        EventAuditWriter(
            connection,
            tenant_id=row["tenant_id"],
            actor_user_id=row["requested_by_user_id"],
            project_id=row["project_id"],
        ).record(
            EventDraft(
                event_id=f"ai-finding:{finding_id}:created",
                event_type="AI_FINDING_CREATED",
                source="ai_runtime",
                entity_id=finding_id,
                occurred_at=created_at,
                payload={"finding_id": str(finding_id), "agent_run_id": str(row["id"])},
            ),
            AuditDraft(
                action="finding.create_meeting_business",
                after_snapshot={"finding_id": str(finding_id)},
                context={
                    "meeting_id": snapshot["meeting_id"],
                    "model_invocation_id": str(invocation_id),
                },
            ),
        )
        results.append(str(finding_id))
    return results


def apply_business(
    engine: Engine,
    connection: Connection,
    *,
    finding: FindingRecord,
    payload: MeetingBusinessPayload,
    actor_user_id: UUID,
    applied_at: datetime,
) -> UUID:
    from app.auth.roles import Action
    from app.domain.knowledge_corrections import KnowledgeCorrectionService
    from app.domain.project_write_lock import lock_project_write_scope

    if not lock_project_write_scope(
        connection, tenant_id=finding.tenant_id, project_id=finding.project_id
    ):
        raise MeetingBusinessProposalError("项目已不可用")
    validate_business(connection, finding, payload)
    KnowledgeCorrectionService._authorize(
        connection,
        finding.tenant_id,
        actor_user_id,
        finding.project_id,
        Action.CHANGE_EDIT if isinstance(payload, MeetingChangePayload) else Action.WORK_ITEM_EDIT,
    )
    if connection.execute(
        select(tables.findings.c.id).where(
            tables.findings.c.tenant_id == finding.tenant_id,
            tables.findings.c.project_id == finding.project_id,
            tables.findings.c.origin_key == finding.origin_key,
            tables.findings.c.finding_type == finding.finding_type,
            tables.findings.c.status == "applied",
        )
    ).first():
        raise MeetingBusinessProposalError("相同依据的候选已应用，请打开原业务记录继续办理")
    if isinstance(payload, MeetingIssuePayload):
        from app.domain.issues import IssueDraft, IssueService

        assert payload.issue_type is not None and payload.severity is not None
        return (
            IssueService(engine)
            .create(
                tenant_id=finding.tenant_id,
                project_id=finding.project_id,
                actor_user_id=actor_user_id,
                connection=connection,
                source_finding_id=finding.id,
                now=applied_at,
                draft=IssueDraft(
                    stage_id=None,
                    sample_id=None,
                    owner_user_id=payload.owner_id,
                    verifier_user_id=payload.verifier_id,
                    title=payload.title,
                    description=payload.description,
                    issue_type=payload.issue_type,
                    severity=payload.severity,
                    root_cause=None,
                    resolution=None,
                    closure_criteria=payload.closure_criteria,
                    target_date=payload.target_date,
                ),
            )
            .id
        )
    if isinstance(payload, MeetingRiskPayload):
        from app.domain.risks import RiskDraft, RiskService

        assert payload.likelihood is not None and payload.impact is not None
        return (
            RiskService(engine)
            .create(
                tenant_id=finding.tenant_id,
                project_id=finding.project_id,
                actor_user_id=actor_user_id,
                connection=connection,
                source_finding_id=finding.id,
                now=applied_at,
                draft=RiskDraft(
                    owner_user_id=payload.owner_id,
                    title=payload.title,
                    description=payload.description,
                    likelihood=payload.likelihood,
                    impact=payload.impact,
                    mitigation_plan=payload.mitigation_plan,
                    contingency_plan=payload.contingency_plan,
                    target_date=payload.target_date,
                ),
            )
            .id
        )
    from app.domain.change_governance import ChangeGovernanceService

    assert payload.code is not None
    result = ChangeGovernanceService(engine).create_ecr_in_transaction(
        connection,
        tenant_id=finding.tenant_id,
        project_id=finding.project_id,
        actor_user_id=actor_user_id,
        code=payload.code,
        title=payload.title,
        reason=payload.description,
        source_finding_id=finding.id,
        now=applied_at,
    )
    return UUID(str(result["id"]))
