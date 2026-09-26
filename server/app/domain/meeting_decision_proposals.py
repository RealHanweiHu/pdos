"""Source-bound meeting decisions, confirmed by their named approver at application."""

from __future__ import annotations

import json
from datetime import datetime
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


class MeetingDecisionProposalError(ValueError):
    pass


class DecisionSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=512)
    context: str | None = Field(default=None, max_length=5000)
    options: tuple[str, ...] = Field(default=(), max_length=20)
    trade_offs: str | None = Field(default=None, max_length=5000)
    outcome: str | None = Field(default=None, max_length=5000)
    rationale: str | None = Field(default=None, max_length=5000)
    consequence: str | None = Field(default=None, max_length=5000)
    citations: tuple[MinutesQuote, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def options_valid(self) -> Self:
        if any(not o.strip() or len(o) > 2000 for o in self.options):
            raise ValueError("Options must be nonblank and bounded")
        return self


class MeetingDecisionAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    disposition: Literal["decisions", "insufficient_evidence"]
    decisions: tuple[DecisionSuggestion, ...] = Field(max_length=10)
    open_questions: tuple[str, ...] = Field(max_length=15)

    @model_validator(mode="after")
    def shape(self) -> Self:
        if (self.disposition == "decisions") != bool(self.decisions):
            raise ValueError("Decisions require cited proposals")
        if any(not q.strip() or len(q) > 2000 for q in self.open_questions):
            raise ValueError("Questions must be nonblank and bounded")
        return self


class MeetingDecisionPayload(DecisionSuggestion):
    meeting_id: UUID
    transcript_id: UUID
    source_digest: str = Field(pattern="^[0-9a-f]{64}$")
    member_options: tuple[dict[str, Any], ...]
    decision_kind: (
        Literal[
            "technical_choice",
            "supplier_choice",
            "process_decision",
            "rebaseline",
            "definition_release",
            "ccr_response",
        ]
        | None
    ) = None
    owner_id: UUID | None = None
    approver_id: UUID | None = None
    follow_up_pending: bool = True
    follow_up_note: str | None = Field(default=None, max_length=2000)
    details_confirmed: bool = False


def prompt_data() -> dict[str, Any]:
    return dict(
        json.loads((Path(__file__).parents[1] / "ai/prompts/meeting_decisions_v1.json").read_text())
    )


def validate_decision(
    connection: Connection, finding: FindingRecord, payload: MeetingDecisionPayload
) -> None:
    from app.ai.meeting_reading import source_state
    from app.domain.tasks import TaskScopeError, TaskService

    row = (
        connection.execute(
            select(tables.agent_runs).where(
                tables.agent_runs.c.tenant_id == finding.tenant_id,
                tables.agent_runs.c.project_id == finding.project_id,
                tables.agent_runs.c.id == finding.run_id,
                tables.agent_runs.c.context_version == "meeting-decisions-request-v1",
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or not row["run_context"].get("reading_propose_decisions"):
        raise MeetingDecisionProposalError("决策建议缺少实际生成运行")
    snapshot = row["run_context"]["reading_source"]
    current = source_state(
        connection, finding.tenant_id, finding.project_id, payload.meeting_id, payload.transcript_id
    )
    if current != {k: v for k, v in snapshot.items() if k != "decision_options"}:
        raise MeetingDecisionProposalError("会议、转写或说话人已变化，请重新生成")
    frozen = payload.model_dump(mode="json")
    if any(
        frozen.get(k) != finding.proposed_payload.get(k)
        for k in ("meeting_id", "transcript_id", "source_digest", "member_options", "citations")
    ):
        raise MeetingDecisionProposalError("不能改写决策候选的原始依据")
    validate_quotes(snapshot, payload.citations)
    if (
        not payload.details_confirmed
        or not payload.decision_kind
        or not payload.approver_id
        or not payload.options
        or any(
            not (getattr(payload, k) or "").strip()
            for k in ("context", "trade_offs", "outcome", "rationale", "consequence")
        )
    ):
        raise MeetingDecisionProposalError("请补齐背景、选项、权衡、结论、理由、后果和具名批准人")
    if (
        payload.decision_kind in {"rebaseline", "definition_release"}
        and not payload.follow_up_pending
    ):
        raise MeetingDecisionProposalError("基线或定义发布仍须在原业务流程执行，不能标记无需跟进")
    if payload.follow_up_pending and (
        not payload.owner_id or not (payload.follow_up_note or "").strip()
    ):
        raise MeetingDecisionProposalError("请指定跟进负责人并说明实际执行要求")
    try:
        for user_id in (payload.approver_id, payload.owner_id):
            TaskService._validate_member(
                connection,
                tenant_id=finding.tenant_id,
                project_id=finding.project_id,
                user_id=user_id,
            )
    except TaskScopeError as error:
        raise MeetingDecisionProposalError("决策批准人或负责人已无当前项目办理资格") from error


def persist_decisions(
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

    require_live_finding("knowledge_lite", "meeting_decision")
    if not FindingQualityService.is_output_allowed_connection(
        connection,
        tenant_id=row["tenant_id"],
        agent_key="knowledge_lite",
        finding_type="meeting_decision",
    ):
        raise MeetingDecisionProposalError("决策建议质量控制已收窄")
    if (
        source_state(
            connection,
            row["tenant_id"],
            row["project_id"],
            UUID(snapshot["meeting_id"]),
            UUID(snapshot["transcript_id"]),
            include_decisions=True,
        )
        != snapshot
    ):
        raise MeetingDecisionProposalError("生成期间来源已变化，请重新整理")
    result = []
    for item in MeetingDecisionAssessment.model_validate(output).decisions:
        validate_quotes(snapshot, item.citations)
        payload = MeetingDecisionPayload(
            **item.model_dump(),
            meeting_id=snapshot["meeting_id"],
            transcript_id=snapshot["transcript_id"],
            source_digest=snapshot["transcript_digest"],
            member_options=snapshot["decision_options"],
        )
        origin = "meeting-decision:" + digest(
            {
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
            result.append(str(existing))
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
                finding_type="meeting_decision",
                origin_key=origin,
                status="pending_review",
                title=payload.title,
                summary="待具名批准人核对的决策建议；原业务执行仍独立办理。",
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
                action="finding.create_meeting_decision",
                after_snapshot={"finding_id": str(finding_id)},
                context={
                    "meeting_id": snapshot["meeting_id"],
                    "model_invocation_id": str(invocation_id),
                },
            ),
        )
        result.append(str(finding_id))
    return result


def apply_decision(
    engine: Engine,
    connection: Connection,
    *,
    finding: FindingRecord,
    payload: MeetingDecisionPayload,
    actor_user_id: UUID,
    applied_at: datetime,
) -> UUID:
    from app.auth.roles import Action
    from app.domain.decisions import DecisionDraft, DecisionService
    from app.domain.knowledge_corrections import KnowledgeCorrectionService
    from app.domain.project_write_lock import lock_project_write_scope

    if not lock_project_write_scope(
        connection, tenant_id=finding.tenant_id, project_id=finding.project_id
    ):
        raise MeetingDecisionProposalError("项目已不可用")
    validate_decision(connection, finding, payload)
    KnowledgeCorrectionService._authorize(
        connection, finding.tenant_id, actor_user_id, finding.project_id, Action.WORK_ITEM_EDIT
    )
    if actor_user_id != payload.approver_id:
        raise MeetingDecisionProposalError("须由本候选指定的批准人本人独立应用")
    if connection.execute(
        select(tables.findings.c.id).where(
            tables.findings.c.tenant_id == finding.tenant_id,
            tables.findings.c.project_id == finding.project_id,
            tables.findings.c.origin_key == finding.origin_key,
            tables.findings.c.finding_type == "meeting_decision",
            tables.findings.c.status == "applied",
        )
    ).first():
        raise MeetingDecisionProposalError("相同依据的决策建议已应用，请查看原决策继续办理")
    assert payload.decision_kind is not None and payload.outcome is not None
    return (
        DecisionService(engine)
        .create(
            tenant_id=finding.tenant_id,
            project_id=finding.project_id,
            actor_user_id=actor_user_id,
            connection=connection,
            source_finding_id=finding.id,
            now=applied_at,
            draft=DecisionDraft(
                decision_kind=payload.decision_kind,
                title=payload.title,
                outcome=payload.outcome,
                context=payload.context,
                options=payload.options,
                trade_offs=payload.trade_offs,
                rationale=payload.rationale,
                consequence=payload.consequence,
                evidence_refs=tuple(
                    f"meeting-transcript:{payload.transcript_id}:segment:{q.segment_id}: "
                    f"{q.exact_quote}"
                    for q in payload.citations
                ),
                owner_user_id=payload.owner_id,
                approver_user_id=payload.approver_id,
                follow_up_pending=payload.follow_up_pending,
                follow_up_note=payload.follow_up_note,
            ),
        )
        .id
    )
