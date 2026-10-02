"""Cited meeting action candidates and independent, atomic task application."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.db.schema import tables
from app.domain.meeting_minutes_proposals import MinutesQuote
from app.domain.product_workspace import digest
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

if TYPE_CHECKING:
    from app.domain.findings import FindingRecord


class MeetingActionProposalError(ValueError):
    pass


class ActionSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1, max_length=3000)
    owner_text: str | None = Field(default=None, max_length=512)
    date_text: str | None = Field(default=None, max_length=512)
    expected_output: str | None = Field(default=None, max_length=3000)
    citations: tuple[MinutesQuote, ...] = Field(min_length=1, max_length=8)


class MeetingActionAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    disposition: Literal["actions", "insufficient_evidence"]
    actions: tuple[ActionSuggestion, ...] = Field(max_length=10)
    open_questions: tuple[str, ...] = Field(max_length=15)

    @model_validator(mode="after")
    def shape(self) -> Self:
        if (self.disposition == "actions") != bool(self.actions):
            raise ValueError("Actions require cited suggestions")
        if any(not q.strip() or len(q) > 2000 for q in self.open_questions):
            raise ValueError("Questions must be nonblank and bounded")
        return self


class MeetingActionPayload(ActionSuggestion):
    meeting_id: UUID
    transcript_id: UUID
    source_digest: str = Field(pattern="^[0-9a-f]{64}$")
    agenda_options: tuple[dict[str, Any], ...]
    member_options: tuple[dict[str, Any], ...]
    agenda_id: UUID | None = None
    assignee_id: UUID | None = None
    due_date: date | None = None
    details_confirmed: bool = False


def prompt_data() -> dict[str, Any]:
    import json

    return dict(
        json.loads((Path(__file__).parents[1] / "ai/prompts/meeting_actions_v1.json").read_text())
    )


def action_options(
    connection: Connection, tenant_id: UUID, project_id: UUID, meeting_id: UUID
) -> dict[str, Any]:
    from app.domain.meeting_preparation import MeetingPreparationService
    from app.domain.product_workspace import _plain

    agenda = [
        dict(row)
        for row in connection.execute(
            select(tables.meeting_agenda_items)
            .where(
                tables.meeting_agenda_items.c.tenant_id == tenant_id,
                tables.meeting_agenda_items.c.meeting_id == meeting_id,
            )
            .order_by(tables.meeting_agenda_items.c.id)
        ).mappings()
    ]
    return {
        "agendas": [_plain(item) for item in agenda],
        "members": [
            _plain(m)
            for m in sorted(
                MeetingPreparationService.members(connection, tenant_id, project_id),
                key=lambda m: (m["display_name"], str(m["id"])),
            )
            if m["role"] in {"owner", "admin", "project_manager", "engineer", "quality"}
        ],
    }


def validate_action(
    connection: Connection, finding: FindingRecord, payload: MeetingActionPayload
) -> None:
    from app.ai.meeting_reading import source_state
    from app.domain.meeting_followup import _agenda
    from app.domain.product_workspace import _plain
    from app.domain.tasks import TaskScopeError, TaskService

    row = (
        connection.execute(
            select(tables.agent_runs).where(
                tables.agent_runs.c.tenant_id == finding.tenant_id,
                tables.agent_runs.c.project_id == finding.project_id,
                tables.agent_runs.c.id == finding.run_id,
                tables.agent_runs.c.context_version == "meeting-actions-request-v1",
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or not row["run_context"].get("reading_propose_actions"):
        raise MeetingActionProposalError("行动建议缺少对应的实际生成运行")
    snapshot = row["run_context"]["reading_source"]
    current = source_state(
        connection, finding.tenant_id, finding.project_id, payload.meeting_id, payload.transcript_id
    )
    original = {k: v for k, v in snapshot.items() if k != "action_options"}
    if current != original or payload.source_digest != original["transcript_digest"]:
        raise MeetingActionProposalError("会议、转写或说话人已变化，请重新生成行动建议")
    if (
        list(payload.agenda_options) != snapshot["action_options"]["agendas"]
        or list(payload.member_options) != snapshot["action_options"]["members"]
    ):
        raise MeetingActionProposalError("不能改写行动建议的议题和人员核对资料")
    if any(
        payload.model_dump(mode="json").get(key) != finding.proposed_payload.get(key)
        for key in (
            "meeting_id",
            "transcript_id",
            "source_digest",
            "owner_text",
            "date_text",
            "citations",
        )
    ):
        raise MeetingActionProposalError("不能改写行动的原始来源、责任时间摘录或引用")
    validate_quotes(snapshot, payload.citations)
    if (
        not payload.details_confirmed
        or payload.agenda_id is None
        or payload.assignee_id is None
        or payload.due_date is None
        or not (payload.expected_output or "").strip()
    ):
        raise MeetingActionProposalError("请逐项确认议题、具名负责人、日期和完成标准后再接受")
    original_agenda = next(
        (a for a in payload.agenda_options if a["id"] == str(payload.agenda_id)), None
    )
    current_agenda = _plain(
        dict(_agenda(connection, finding.tenant_id, payload.meeting_id, payload.agenda_id))
    )
    if original_agenda is None or current_agenda != original_agenda:
        raise MeetingActionProposalError("所选议题已变化，请核对会议资料后重新生成")
    try:
        TaskService._validate_member(
            connection,
            tenant_id=finding.tenant_id,
            project_id=finding.project_id,
            user_id=payload.assignee_id,
        )
    except TaskScopeError as error:
        raise MeetingActionProposalError("所选负责人已无当前任务办理资格，请重新核对") from error


def validate_quotes(snapshot: dict[str, Any], citations: tuple[MinutesQuote, ...]) -> None:
    segments = {r["id"]: r["content"] for r in snapshot["segments"]}
    seen = set()
    for quote in citations:
        key = (str(quote.segment_id), quote.exact_quote)
        if (
            key in seen
            or not quote.exact_quote.strip()
            or quote.exact_quote not in segments.get(key[0], "")
        ):
            raise MeetingActionProposalError("行动原句引用重复或无法在原文中核对")
        seen.add(key)


def persist_actions(
    connection: Connection,
    *,
    row: Any,
    snapshot: dict[str, Any],
    output: dict[str, Any],
    invocation_id: UUID,
    created_at: datetime,
) -> list[str]:
    from app.ai.quality import FindingQualityService
    from app.ai.rollout_guard import require_live_finding
    from app.domain.findings import FINDING_PREFLIGHT_VERSION

    require_live_finding("knowledge_lite", "meeting_action")
    if not FindingQualityService.is_output_allowed_connection(
        connection,
        tenant_id=row["tenant_id"],
        agent_key="knowledge_lite",
        finding_type="meeting_action",
    ):
        raise MeetingActionProposalError("行动建议质量控制已收窄")
    from app.ai.meeting_reading import source_state

    if (
        source_state(
            connection,
            row["tenant_id"],
            row["project_id"],
            UUID(snapshot["meeting_id"]),
            UUID(snapshot["transcript_id"]),
            include_actions=True,
        )
        != snapshot
    ):
        raise MeetingActionProposalError("生成期间会议来源已变化，请刷新后重新整理")
    assessment = MeetingActionAssessment.model_validate(output)
    result = []
    for item in assessment.actions:
        validate_quotes(snapshot, item.citations)
        for wording in (item.owner_text, item.date_text):
            if wording is not None and not any(wording in q.exact_quote for q in item.citations):
                raise MeetingActionProposalError("责任或时间表述未能在本行动的引用原句中核对")
        payload = MeetingActionPayload(
            **item.model_dump(),
            meeting_id=snapshot["meeting_id"],
            transcript_id=snapshot["transcript_id"],
            source_digest=snapshot["transcript_digest"],
            agenda_options=snapshot["action_options"]["agendas"],
            member_options=snapshot["action_options"]["members"],
        )
        # Distinct actions may share a paragraph. Identity uses the original title and quotes.
        origin = "meeting-action:" + digest(
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
                finding_type="meeting_action",
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
                action="finding.create_meeting_action",
                after_snapshot={"finding_id": str(finding_id)},
                context={
                    "meeting_id": snapshot["meeting_id"],
                    "model_invocation_id": str(invocation_id),
                },
            ),
        )
        from app.domain.ai_meeting_drafts import capture_minutes_draft

        capture_minutes_draft(
            connection,
            row=row,
            finding_id=finding_id,
            payload=payload,
            snapshot=snapshot,
            invocation_id=invocation_id,
            now=created_at,
            kind="actions",
        )
        result.append(str(finding_id))
    return result


def apply_action(
    engine: Engine,
    connection: Connection,
    *,
    finding: FindingRecord,
    payload: MeetingActionPayload,
    actor_user_id: UUID,
    applied_at: datetime,
) -> UUID:
    from app.domain.meeting_followup import MeetingFollowupService, _agenda, _basis
    from app.domain.project_write_lock import lock_project_write_scope

    if not lock_project_write_scope(
        connection, tenant_id=finding.tenant_id, project_id=finding.project_id
    ):
        raise MeetingActionProposalError("项目已不可用")
    from app.domain.ai_meeting_draft_content import require_unpublished_origin

    require_unpublished_origin(
        connection, finding.tenant_id, finding.project_id, finding.finding_type, finding.origin_key
    )
    validate_action(connection, finding, payload)
    duplicate = connection.execute(
        select(tables.findings.c.applied_entity_id).where(
            tables.findings.c.tenant_id == finding.tenant_id,
            tables.findings.c.project_id == finding.project_id,
            tables.findings.c.origin_key == finding.origin_key,
            tables.findings.c.finding_type == "meeting_action",
            tables.findings.c.status == "applied",
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise MeetingActionProposalError("相同转写依据已应用为行动，请打开原任务继续办理")
    assert payload.agenda_id is not None
    agenda = _agenda(connection, finding.tenant_id, payload.meeting_id, payload.agenda_id)
    result = MeetingFollowupService(engine).act(
        tenant_id=finding.tenant_id,
        project_id=finding.project_id,
        meeting_id=payload.meeting_id,
        agenda_id=payload.agenda_id,
        actor_id=actor_user_id,
        request_id=uuid5(finding.id, "meeting-action.v1"),
        expected_basis=_basis(connection, finding.tenant_id, finding.project_id, agenda)[
            "basis_digest"
        ],
        action="create_action",
        reason=payload.description,
        title=payload.title,
        assignee_id=payload.assignee_id,
        due_date=payload.due_date,
        expected_output=payload.expected_output,
        connection=connection,
        source_finding_id=finding.id,
        now=applied_at,
    )
    return UUID(result["task_id"])
