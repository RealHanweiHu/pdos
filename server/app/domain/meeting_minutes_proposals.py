"""Typed model minutes proposals; acceptance and application remain distinct."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, select

from app.db.schema import tables
from app.domain.product_workspace import digest
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

if TYPE_CHECKING:
    from app.domain.findings import FindingRecord


class MeetingMinutesProposalError(ValueError):
    pass


class MinutesQuote(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    segment_id: UUID
    exact_quote: str = Field(min_length=1, max_length=2000)


class MeetingMinutesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=512)
    meeting_id: UUID
    transcript_id: UUID
    source_digest: str = Field(pattern="^[0-9a-f]{64}$")
    base_version: int = Field(ge=0)
    base_snapshot: dict[str, Any]
    body: str = Field(min_length=1, max_length=20000)
    unresolved_points: str = Field(min_length=1, max_length=5000)
    citations: tuple[MinutesQuote, ...] = Field(min_length=1, max_length=100)


def validate_minutes_payload(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    snapshot: dict[str, Any],
    payload: MeetingMinutesPayload,
) -> None:
    from app.ai.meeting_reading import source_state
    from app.domain.meetings import MeetingNotFoundError, MeetingStateError

    if (
        str(payload.meeting_id) != snapshot["meeting_id"]
        or str(payload.transcript_id) != snapshot["transcript_id"]
        or payload.source_digest != snapshot["transcript_digest"]
        or payload.base_snapshot != snapshot["minutes_base"]
        or payload.base_version != snapshot["minutes_base"]["version"]
    ):
        raise MeetingMinutesProposalError("不能改写候选的会议、来源或原纪要版本")
    try:
        current = source_state(
            connection,
            tenant_id,
            project_id,
            payload.meeting_id,
            payload.transcript_id,
            include_minutes=True,
        )
    except (MeetingNotFoundError, MeetingStateError) as error:
        raise MeetingMinutesProposalError("会议或转写来源已不可用") from error
    if current != snapshot or current["meeting_status"] != "completed":
        raise MeetingMinutesProposalError(
            "会议、转写、说话人或正式纪要已变化，请按当前版本重新生成"
        )
    segments = {row["id"]: row["content"] for row in snapshot["segments"]}
    seen: set[tuple[UUID, str]] = set()
    for quote in payload.citations:
        key = (quote.segment_id, quote.exact_quote)
        if (
            key in seen
            or not quote.exact_quote.strip()
            or quote.exact_quote not in segments.get(str(quote.segment_id), "")
        ):
            raise MeetingMinutesProposalError("原句引用重复、无效或超出本次候选的转写依据")
        seen.add(key)


def validate_finding_minutes(
    connection: Connection, finding: FindingRecord, payload: MeetingMinutesPayload
) -> None:
    row = (
        connection.execute(
            select(tables.agent_runs).where(
                tables.agent_runs.c.tenant_id == finding.tenant_id,
                tables.agent_runs.c.project_id == finding.project_id,
                tables.agent_runs.c.id == finding.run_id,
                tables.agent_runs.c.context_version == "meeting-minutes-request-v1",
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or not row["run_context"].get("reading_propose_minutes"):
        raise MeetingMinutesProposalError("候选缺少对应的纪要生成运行")
    validate_minutes_payload(
        connection,
        tenant_id=finding.tenant_id,
        project_id=finding.project_id,
        snapshot=row["run_context"]["reading_source"],
        payload=payload,
    )


def persist_minutes_proposal(
    connection: Connection,
    *,
    row: Any,
    snapshot: dict[str, Any],
    output: dict[str, Any],
    invocation_id: UUID,
    created_at: datetime,
) -> UUID | None:
    from app.ai.meeting_reading import MeetingReading
    from app.ai.quality import FindingQualityService
    from app.ai.rollout_guard import require_live_finding
    from app.domain.findings import FINDING_PREFLIGHT_VERSION

    require_live_finding("knowledge_lite", "meeting_minutes")
    reading = MeetingReading.model_validate(output)
    if reading.disposition != "reading":
        return None
    if not FindingQualityService.is_output_allowed_connection(
        connection,
        tenant_id=row["tenant_id"],
        agent_key="knowledge_lite",
        finding_type="meeting_minutes",
    ):
        raise MeetingMinutesProposalError("纪要候选质量控制已收窄，暂不能新增")
    quotes = {
        (quote.segment_id, quote.exact_quote): quote
        for claim in reading.claims
        for quote in claim.citations
    }
    payload = MeetingMinutesPayload(
        title=(snapshot["meeting_title"] + " · 纪要待审稿")[:512],
        meeting_id=snapshot["meeting_id"],
        transcript_id=snapshot["transcript_id"],
        source_digest=snapshot["transcript_digest"],
        base_version=snapshot["minutes_base"]["version"],
        base_snapshot=snapshot["minutes_base"],
        body="\n\n".join(claim.text for claim in reading.claims),
        unresolved_points="\n".join(reading.open_questions)
        or "原阅读结果未列出待澄清问题，确认人仍须核对是否存在未决事项。",
        citations=tuple(MinutesQuote(segment_id=key[0], exact_quote=key[1]) for key in quotes),
    )
    validate_minutes_payload(
        connection,
        tenant_id=row["tenant_id"],
        project_id=row["project_id"],
        snapshot=snapshot,
        payload=payload,
    )
    origin = "meeting-minutes:" + digest(snapshot)
    existing = connection.execute(
        select(tables.findings.c.id).where(
            tables.findings.c.tenant_id == row["tenant_id"],
            tables.findings.c.run_id == row["id"],
            tables.findings.c.origin_key == origin,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return UUID(str(existing))
    finding_id = uuid4()
    connection.execute(
        tables.findings.insert().values(
            id=finding_id,
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            run_id=row["id"],
            model_invocation_id=invocation_id,
            agent_key="knowledge_lite",
            finding_type="meeting_minutes",
            origin_key=origin,
            status="pending_review",
            title=payload.title,
            summary="根据授权转写生成的纪要待审稿；接受后仍须独立应用，不包含决定或行动批准。",
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
            detail={"source": "meeting_transcript", "preflight_version": FINDING_PREFLIGHT_VERSION},
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
            action="finding.create_from_meeting",
            after_snapshot={
                "finding_id": str(finding_id),
                "finding_type": "meeting_minutes",
                "status": "pending_review",
            },
            context={
                "meeting_id": snapshot["meeting_id"],
                "source_digest": snapshot["transcript_digest"],
                "base_version": payload.base_version,
                "model_invocation_id": str(invocation_id),
            },
        ),
    )
    return finding_id


def apply_minutes_proposal(
    engine: Engine,
    connection: Connection,
    *,
    finding: FindingRecord,
    payload: MeetingMinutesPayload,
    actor_user_id: UUID,
    applied_at: datetime,
) -> UUID:
    from app.domain.meeting_minutes import MeetingMinutesService

    validate_finding_minutes(connection, finding, payload)
    result = MeetingMinutesService(engine).confirm(
        tenant_id=finding.tenant_id,
        project_id=finding.project_id,
        meeting_id=payload.meeting_id,
        actor_id=actor_user_id,
        request_id=uuid5(finding.id, "official-minutes.v1"),
        expected_version=payload.base_version,
        body=payload.body,
        unresolved_points=payload.unresolved_points,
        reason=finding.review_comment or "应用已独立接受的会议纪要建议",
        citations=[
            {
                "transcript_id": payload.transcript_id,
                "segment_id": quote.segment_id,
                "expected_digest": payload.source_digest,
                "exact_quote": quote.exact_quote,
            }
            for quote in payload.citations
        ],
        connection=connection,
        source_finding_id=finding.id,
        now=applied_at,
    )
    return UUID(result["id"])
