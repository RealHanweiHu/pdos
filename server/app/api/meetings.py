"""Meeting HTTP boundary (vNext V2-1, D6/D35).

Every route authorizes against the project, so a meeting is reachable only by
someone already inside the project it belongs to.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine

from app.ai.application_gateway import ApplicationModelGateway
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.meeting_planning_runs import MeetingPlanningRequest, MeetingPlanningRuns
from app.ai.meeting_reading import MeetingReadingService
from app.ai.rollout_guard import CapabilityUnavailableError
from app.api.ai import get_application_gateway
from app.api.auth import current_context, no_store
from app.api.memories import _push_error
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.engine import get_engine
from app.domain import (
    meeting_conference_requests,
    meeting_generation,
    meeting_notifications,
    meeting_planning,
    meeting_planning_review,
    meeting_rescheduling,
    meeting_schedule_revision,
)
from app.domain import meeting_recurrence_commands as recurrence_commands
from app.domain.ai_meeting_draft_content import DraftKind
from app.domain.ai_meeting_drafts import AiMinutesDraftService, DraftChange, ScopeChange
from app.domain.ai_meeting_event_history import AiMeetingEventHistory
from app.domain.knowledge_push import KnowledgeAccessError, KnowledgeVersionError
from app.domain.knowledge_sources import KnowledgeSourceBindingError, KnowledgeSourceSelection
from app.domain.meeting_followup import MeetingFollowupService
from app.domain.meeting_minutes import MeetingMinutesService
from app.domain.meeting_preparation import TEMPLATES, MeetingPreparationService
from app.domain.meeting_recurrence_roster import RosterChange
from app.domain.meeting_retrospectives import MeetingRetrospectiveService
from app.domain.meeting_scheduling import RecurrenceNotFoundError, RecurrenceValidationError
from app.domain.meeting_transcripts import MeetingTranscriptService
from app.domain.meetings import (
    AgendaItemRecord,
    MeetingLinkError,
    MeetingNotFoundError,
    MeetingRecord,
    MeetingScopeError,
    MeetingService,
    MeetingStateError,
    ParticipantRecord,
    TranscriptRecord,
    TranscriptSegmentDraft,
)
from app.settings import get_settings

router = APIRouter(prefix="/api/projects/{project_id}/meetings", tags=["meetings"])


@router.get("/planning/{brief_id}/runs")
def meeting_planning_runs_get(
    project_id: UUID,
    brief_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return MeetingPlanningRuns(engine).list(context, project_id, brief_id, before)
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/planning/{brief_id}/runs")
def meeting_planning_run_create(
    project_id: UUID,
    brief_id: UUID,
    payload: MeetingPlanningRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    gateway: Annotated[ApplicationModelGateway, Depends(get_application_gateway)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return MeetingPlanningRuns(engine, gateway).create(context, project_id, brief_id, payload)
    except Exception as error:
        raise meeting_error(error) from error


@router.get("/planning-findings/{finding_id}")
def meeting_planning_finding_get(
    project_id: UUID,
    finding_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_planning_review.MeetingPlanningReview(engine).get(
            context, project_id, finding_id
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/planning-findings/{finding_id}/preview")
def meeting_planning_finding_preview(
    project_id: UUID,
    finding_id: UUID,
    payload: meeting_planning_review.HumanPlan,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_planning_review.MeetingPlanningReview(engine).preview(
            context, project_id, finding_id, payload
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/planning-findings/{finding_id}/review")
def meeting_planning_finding_review(
    project_id: UUID,
    finding_id: UUID,
    payload: meeting_planning_review.Review,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_planning_review.MeetingPlanningReview(engine).review(
            context, project_id, finding_id, payload
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/planning-findings/{finding_id}/apply")
def meeting_planning_finding_apply(
    project_id: UUID,
    finding_id: UUID,
    payload: meeting_planning_review.Apply,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_planning_review.MeetingPlanningReview(engine).apply(
            context, project_id, finding_id, payload
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.get("/{meeting_id}/planning-origin")
def meeting_planning_origin(
    project_id: UUID,
    meeting_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_planning_review.MeetingPlanningReview(engine).origin(
            context, project_id, meeting_id
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.get("/planning-options")
def meeting_planning_options(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    kind: meeting_planning.Kind = "issue",
    q: str = Query(default="", max_length=200),
    before: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_planning.options(engine, context, project_id, kind, q, before)
    except Exception as error:
        raise meeting_error(error) from error


@router.get("/planning")
def meeting_planning_read(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    brief_id: UUID | None = None,
    before_id: int | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_planning.read(engine, context, project_id, brief_id, before_id)
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/planning-preview")
def meeting_planning_preview(
    project_id: UUID,
    payload: meeting_planning.Draft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_planning.preview(engine, context, project_id, payload)
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/planning")
def meeting_planning_save(
    project_id: UUID,
    payload: meeting_planning.Save,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_planning.save(engine, context, project_id, payload)
    except Exception as error:
        raise meeting_error(error) from error


@router.get("/recurrences")
def recurrence_list(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return recurrence_commands.list_configurations(engine, context, project_id, before)
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/recurrences/preview")
def recurrence_draft_preview(
    project_id: UUID,
    payload: recurrence_commands.Create,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return recurrence_commands.draft_preview(engine, context, project_id, payload)
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/recurrences")
def recurrence_create(
    project_id: UUID,
    payload: recurrence_commands.Create,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return recurrence_commands.create(engine, context, project_id, payload)
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/recurrences/{recurrence_id}/preview")
def recurrence_generation_preview(
    project_id: UUID,
    recurrence_id: UUID,
    payload: recurrence_commands.Window,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return recurrence_commands.preview(engine, context, project_id, recurrence_id, payload)
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/recurrences/{recurrence_id}/generate")
def recurrence_generate(
    project_id: UUID,
    recurrence_id: UUID,
    payload: recurrence_commands.Generate,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return recurrence_commands.generate(engine, context, project_id, recurrence_id, payload)
    except Exception as error:
        raise meeting_error(error) from error


@router.get("/recurrences/{recurrence_id}/history")
def recurrence_history(
    project_id: UUID,
    recurrence_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_id: int | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return recurrence_commands.history(engine, context, project_id, recurrence_id, before_id)
    except Exception as error:
        raise meeting_error(error) from error


@router.get("/recurrences/{recurrence_id}/automation")
def recurrence_automation_read(
    project_id: UUID,
    recurrence_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_id: int | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_generation.read(
            engine,
            context,
            project_id,
            recurrence_id,
            service_enabled=get_settings().meeting_generation_enabled,
            before=before_id,
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/recurrences/{recurrence_id}/automation-preview")
def recurrence_automation_preview(
    project_id: UUID,
    recurrence_id: UUID,
    payload: meeting_generation.Draft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_generation.preview(engine, context, project_id, recurrence_id, payload)
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/recurrences/{recurrence_id}/automation")
def recurrence_automation_save(
    project_id: UUID,
    recurrence_id: UUID,
    payload: meeting_generation.Save,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_generation.save(engine, context, project_id, recurrence_id, payload)
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/recurrences/{recurrence_id}/schedule-preview")
def recurrence_schedule_preview(
    project_id: UUID,
    recurrence_id: UUID,
    payload: meeting_schedule_revision.Revision,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_schedule_revision.preview(
            engine, context, project_id, recurrence_id, payload
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/recurrences/{recurrence_id}/schedule")
def recurrence_schedule_save(
    project_id: UUID,
    recurrence_id: UUID,
    payload: meeting_schedule_revision.Save,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_schedule_revision.save(engine, context, project_id, recurrence_id, payload)
    except Exception as error:
        raise meeting_error(error) from error


@router.get("/{meeting_id}/notifications")
def meeting_notifications_read(
    project_id: UUID,
    meeting_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_id: int | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_notifications.read(
            engine, context, project_id, meeting_id, get_settings(), before_id
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/{meeting_id}/notification-preview")
def meeting_notifications_preview(
    project_id: UUID,
    meeting_id: UUID,
    payload: meeting_notifications.Draft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_notifications.preview(
            engine, context, project_id, meeting_id, payload, get_settings()
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/{meeting_id}/notifications")
def meeting_notifications_submit(
    project_id: UUID,
    meeting_id: UUID,
    payload: meeting_notifications.Submit,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_notifications.submit(
            engine, context, project_id, meeting_id, payload, get_settings()
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.get("/{meeting_id}/conference-requests")
def meeting_conference_requests_get(
    project_id: UUID,
    meeting_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_id: int | None = None,
    provider: Literal["dingtalk", "tencent_meeting"] = "dingtalk",
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_conference_requests.read(
            engine, context, project_id, meeting_id, get_settings(), before_id, provider
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/{meeting_id}/conference-preview")
def meeting_conference_preview(
    project_id: UUID,
    meeting_id: UUID,
    payload: meeting_conference_requests.Draft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_conference_requests.preview(
            engine, context, project_id, meeting_id, payload, get_settings()
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/{meeting_id}/conference-requests")
def meeting_conference_submit(
    project_id: UUID,
    meeting_id: UUID,
    payload: meeting_conference_requests.Submit,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_conference_requests.submit(
            engine, context, project_id, meeting_id, payload, get_settings()
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/{meeting_id}/conference-resolution")
def meeting_conference_resolve(
    project_id: UUID,
    meeting_id: UUID,
    payload: meeting_conference_requests.Resolve,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_conference_requests.resolve(engine, context, project_id, meeting_id, payload)
    except Exception as error:
        raise meeting_error(error) from error


@router.get("/{meeting_id}/schedule")
def meeting_schedule_get(
    project_id: UUID,
    meeting_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_id: int | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_rescheduling.read(engine, context, project_id, meeting_id, before_id)
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/{meeting_id}/schedule")
def meeting_schedule_save(
    project_id: UUID,
    meeting_id: UUID,
    payload: meeting_rescheduling.Reschedule,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_rescheduling.save(engine, context, project_id, meeting_id, payload)
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/{meeting_id}/external-schedule-confirmation")
def meeting_external_schedule_confirmation(
    project_id: UUID,
    meeting_id: UUID,
    payload: meeting_rescheduling.ExternalConfirmation,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return meeting_rescheduling.save(engine, context, project_id, meeting_id, payload)
    except Exception as error:
        raise meeting_error(error) from error


@router.get("/recurrences/{recurrence_id}/roster")
def recurrence_roster(
    project_id: UUID,
    recurrence_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_id: int | None = None,
) -> dict[str, Any]:
    from app.domain.meeting_recurrence_roster import read

    no_store(response)
    try:
        return read(engine, context, project_id, recurrence_id, before_id)
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/recurrences/{recurrence_id}/roster")
def recurrence_roster_save(
    project_id: UUID,
    recurrence_id: UUID,
    payload: RosterChange,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.meeting_recurrence_roster import save

    no_store(response)
    try:
        return save(engine, context, project_id, recurrence_id, payload)
    except Exception as error:
        raise meeting_error(error) from error


def meeting_error(error: Exception) -> HTTPException:
    if isinstance(error, (BudgetLedgerError, CapabilityUnavailableError)):
        return HTTPException(
            status_code=409,
            detail={
                "code": error.code,
                "message": "当前会议 AI 能力或运行预算尚不可用，请查看运行配置和阶段验收状态",
            },
        )
    if isinstance(error, (KnowledgeAccessError, KnowledgeVersionError)):
        return _push_error(error)
    if isinstance(error, (MeetingNotFoundError, RecurrenceNotFoundError)):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "MEETING_NOT_FOUND", "message": "Meeting was not found"},
        )
    if isinstance(error, MeetingScopeError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "MEETING_PARTICIPANT_NOT_IN_PROJECT",
                "message": "Every participant must already be a project member",
            },
        )
    if isinstance(error, MeetingLinkError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "MEETING_CONFERENCE_REJECTED",
                "message": "Conference link was rejected",
            },
        )
    if isinstance(error, (MeetingStateError, RecurrenceValidationError)):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "MEETING_INVALID_STATE",
                "message": str(error) or "Requested change does not fit the meeting state",
            },
        )
    raise error


class MeetingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    meeting_type: str
    title: str
    status: str
    scheduled_start_at: datetime
    scheduled_end_at: datetime
    actual_start_at: datetime | None
    actual_end_at: datetime | None
    organizer_user_id: UUID
    source: str
    external_provider: str | None
    external_meeting_id: str | None
    external_join_url: str | None
    retention_policy: str
    archived_at: datetime | None
    cancelled_reason: str | None
    retrospective_conclusion: str | None = None
    retrospective_applicability: str | None = None
    retrospective_source_refs: list[dict[str, Any]] = Field(default_factory=list)
    retrospective_version: int = 0
    retrospective_digest: str | None = None
    retrospective_confirmed_by_user_id: UUID | None = None
    retrospective_confirmed_at: datetime | None = None


class MeetingListResponse(BaseModel):
    items: list[MeetingResponse]


class ParticipantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    participation: str
    attendance: str


class ParticipantListResponse(BaseModel):
    items: list[ParticipantResponse]


class AgendaItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    position: int
    title: str
    item_kind: str
    detail: str | None
    owner_user_id: UUID | None
    source_kind: str | None
    source_entity_id: UUID | None
    carried_from_item_id: UUID | None
    resolution_status: str
    source_digest: str | None = None


class AgendaListResponse(BaseModel):
    items: list[AgendaItemResponse]


class TranscriptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    meeting_id: UUID
    source: str
    language: str
    content_digest: str
    byte_size: int
    segment_count: int
    speaker_labeled: bool
    uploaded_by_user_id: UUID
    uploaded_at: datetime
    reused_existing: bool


class TranscriptListResponse(BaseModel):
    items: list[TranscriptResponse]


class ParticipantInput(BaseModel):
    user_id: UUID
    participation: str = Field(default="required")

    @field_validator("participation")
    @classmethod
    def _known_participation(cls, value: str) -> str:
        if value not in {"organizer", "required", "optional"}:
            raise ValueError("unknown participation")
        return value


class MeetingCreateRequest(BaseModel):
    meeting_type: str
    title: str = Field(min_length=1, max_length=256)
    scheduled_start_at: datetime
    scheduled_end_at: datetime
    organizer_user_id: UUID | None = None
    participants: list[ParticipantInput] = Field(default_factory=list)
    retention_policy: str = Field(default="standard")

    @field_validator("retention_policy")
    @classmethod
    def _known_retention(cls, value: str) -> str:
        if value not in {"standard", "extended", "minimal"}:
            raise ValueError("unknown retention policy")
        return value


class ConferenceBindRequest(BaseModel):
    provider: str
    external_meeting_id: str = Field(min_length=1, max_length=256)
    join_url: str = Field(min_length=1, max_length=1024)


class AgendaItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID | None = None
    source_digest: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    title: str = Field(min_length=1, max_length=256)
    item_kind: str = Field(default="topic")
    detail: str | None = None
    owner_user_id: UUID | None = None
    source_kind: str | None = None
    source_entity_id: UUID | None = None
    carried_from_item_id: UUID | None = None

    @field_validator("item_kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in {"topic", "review", "decision", "information", "exception"}:
            raise ValueError("unknown agenda item kind")
        return value


class AgendaReplaceRequest(BaseModel):
    items: list[AgendaItemInput] = Field(max_length=100)
    expected_digest: str = Field(pattern="^[0-9a-f]{64}$")


class TranscriptSegmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sequence: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=20000)
    speaker_label: str | None = Field(default=None, max_length=128)
    started_offset_ms: int = Field(default=0, ge=0)
    ended_offset_ms: int | None = Field(default=None, ge=0)


class TranscriptUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authorized_source: Literal[True]
    content: str = Field(min_length=1, max_length=200000)
    segments: list[TranscriptSegmentInput] = Field(default_factory=list, max_length=1000)
    language: str = Field(default="zh-CN", max_length=16)
    source: str = Field(default="manual_upload")

    @field_validator("source")
    @classmethod
    def _known_source(cls, value: str) -> str:
        if value not in {
            "manual_upload",
            "dingtalk_export",
            "tencent_meeting_export",
        }:
            raise ValueError("unknown transcript source")
        return value


class StatusChangeRequest(BaseModel):
    status: str
    cancelled_reason: str | None = None

    @field_validator("status")
    @classmethod
    def _known_status(cls, value: str) -> str:
        if value not in {"in_progress", "completed", "cancelled"}:
            raise ValueError("unknown meeting status")
        return value


def meeting_response(record: MeetingRecord) -> MeetingResponse:
    return MeetingResponse.model_validate(record)


def _authorize(engine: Engine, context: AuthContext, project_id: UUID, action: Action) -> None:
    authorize_project(engine=engine, context=context, project_id=project_id, action=action)


@router.get("", response_model=MeetingListResponse)
def list_meetings(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> MeetingListResponse:
    no_store(response)
    _authorize(engine, context, project_id, Action.MEETING_VIEW)
    records = MeetingService(engine).list(tenant_id=context.tenant.id, project_id=project_id)
    return MeetingListResponse(items=[meeting_response(item) for item in records])


@router.post("", response_model=MeetingResponse, status_code=status.HTTP_201_CREATED)
def create_meeting(
    project_id: UUID,
    body: MeetingCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> MeetingResponse:
    no_store(response)
    _authorize(engine, context, project_id, Action.MEETING_MANAGE)
    try:
        return meeting_response(
            MeetingService(engine).create(
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                meeting_type=body.meeting_type,
                title=body.title,
                scheduled_start_at=body.scheduled_start_at,
                scheduled_end_at=body.scheduled_end_at,
                organizer_user_id=body.organizer_user_id,
                participants=[(item.user_id, item.participation) for item in body.participants],
                retention_policy=body.retention_policy,
            )
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.get("/{meeting_id}", response_model=MeetingResponse)
def get_meeting(
    project_id: UUID,
    meeting_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> MeetingResponse:
    no_store(response)
    _authorize(engine, context, project_id, Action.MEETING_VIEW)
    try:
        return meeting_response(
            MeetingService(engine).get(
                tenant_id=context.tenant.id,
                project_id=project_id,
                meeting_id=meeting_id,
            )
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.get("/{meeting_id}/participants", response_model=ParticipantListResponse)
def list_participants(
    project_id: UUID,
    meeting_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ParticipantListResponse:
    no_store(response)
    _authorize(engine, context, project_id, Action.MEETING_VIEW)
    try:
        records: list[ParticipantRecord] = MeetingService(engine).participants(
            tenant_id=context.tenant.id, project_id=project_id, meeting_id=meeting_id
        )
    except Exception as error:
        raise meeting_error(error) from error
    return ParticipantListResponse(
        items=[ParticipantResponse.model_validate(item) for item in records]
    )


@router.get("/{meeting_id}/agenda", response_model=AgendaListResponse)
def get_agenda(
    project_id: UUID,
    meeting_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> AgendaListResponse:
    no_store(response)
    _authorize(engine, context, project_id, Action.MEETING_VIEW)
    try:
        records: list[AgendaItemRecord] = MeetingService(engine).agenda(
            tenant_id=context.tenant.id, project_id=project_id, meeting_id=meeting_id
        )
    except Exception as error:
        raise meeting_error(error) from error
    return AgendaListResponse(items=[AgendaItemResponse.model_validate(item) for item in records])


@router.put("/{meeting_id}/agenda", response_model=AgendaListResponse)
def replace_agenda(
    project_id: UUID,
    meeting_id: UUID,
    body: AgendaReplaceRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> AgendaListResponse:
    no_store(response)
    _authorize(engine, context, project_id, Action.MEETING_MANAGE)
    items: list[dict[str, Any]] = [item.model_dump() for item in body.items]
    try:
        records = MeetingService(engine).replace_agenda(
            tenant_id=context.tenant.id,
            project_id=project_id,
            meeting_id=meeting_id,
            actor_user_id=context.user.id,
            items=items,
            expected_digest=body.expected_digest,
        )
    except Exception as error:
        raise meeting_error(error) from error
    return AgendaListResponse(items=[AgendaItemResponse.model_validate(item) for item in records])


@router.post("/{meeting_id}/conference", response_model=MeetingResponse)
def bind_conference(
    project_id: UUID,
    meeting_id: UUID,
    body: ConferenceBindRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> MeetingResponse:
    no_store(response)
    _authorize(engine, context, project_id, Action.MEETING_LINK_MANAGE)
    try:
        return meeting_response(
            MeetingService(engine).bind_external_conference(
                tenant_id=context.tenant.id,
                project_id=project_id,
                meeting_id=meeting_id,
                actor_user_id=context.user.id,
                provider=body.provider,
                external_meeting_id=body.external_meeting_id,
                join_url=body.join_url,
            )
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.get("/{meeting_id}/transcripts", response_model=TranscriptListResponse)
def list_transcripts(
    project_id: UUID,
    meeting_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> TranscriptListResponse:
    no_store(response)
    _authorize(engine, context, project_id, Action.MEETING_VIEW)
    try:
        records: list[TranscriptRecord] = MeetingService(engine).transcripts(
            tenant_id=context.tenant.id, project_id=project_id, meeting_id=meeting_id
        )
    except Exception as error:
        raise meeting_error(error) from error
    return TranscriptListResponse(
        items=[TranscriptResponse.model_validate(item) for item in records]
    )


@router.post(
    "/{meeting_id}/transcripts",
    response_model=TranscriptResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_transcript(
    project_id: UUID,
    meeting_id: UUID,
    body: TranscriptUploadRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> TranscriptResponse:
    no_store(response)
    _authorize(engine, context, project_id, Action.MEETING_TRANSCRIPT_UPLOAD)
    try:
        record = MeetingService(engine).upload_transcript(
            tenant_id=context.tenant.id,
            project_id=project_id,
            meeting_id=meeting_id,
            actor_user_id=context.user.id,
            content=body.content,
            segments=[
                TranscriptSegmentDraft(
                    sequence=segment.sequence,
                    content=segment.content,
                    speaker_label=segment.speaker_label,
                    started_offset_ms=segment.started_offset_ms,
                    ended_offset_ms=segment.ended_offset_ms,
                )
                for segment in body.segments
            ],
            source=body.source,
            language=body.language,
            authorized_source=body.authorized_source,
        )
    except Exception as error:
        raise meeting_error(error) from error
    return TranscriptResponse.model_validate(record)


class MeetingReadingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_digest: str = Field(pattern="^[0-9a-f]{64}$")
    propose_minutes: bool = False
    propose_actions: bool = False
    propose_decisions: bool = False
    propose_business: bool = False
    expected_minutes_version: int | None = Field(default=None, ge=0)


class MinutesCitationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transcript_id: UUID
    segment_id: UUID
    expected_digest: str = Field(pattern="^[0-9a-f]{64}$")
    exact_quote: str = Field(min_length=1, max_length=2000)


class MinutesConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_version: int = Field(ge=0)
    body: str = Field(min_length=1, max_length=20000)
    unresolved_points: str = Field(min_length=1, max_length=5000)
    reason: str = Field(min_length=1, max_length=3000)
    citations: list[MinutesCitationInput] = Field(min_length=1, max_length=100)


class MinutesRunWithdrawal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    reason: str = Field(min_length=1, max_length=1000)


@router.post("/{meeting_id}/ai-minutes-drafts/runs/{run_id}/withdraw")
def ai_minutes_run_withdraw(
    project_id: UUID,
    meeting_id: UUID,
    run_id: UUID,
    body: MinutesRunWithdrawal,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    kind: DraftKind = "minutes",
) -> dict[str, Any]:
    no_store(response)
    try:
        return AiMinutesDraftService(engine, kind).withdraw_run(
            context.tenant.id,
            project_id,
            meeting_id,
            run_id,
            context.user.id,
            body.request_id,
            body.reason,
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.get("/{meeting_id}/ai-event-history")
def ai_meeting_event_history_get(
    project_id: UUID,
    meeting_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return AiMeetingEventHistory(engine).get(
            context.tenant.id, project_id, meeting_id, context.user.id, before
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.get("/{meeting_id}/ai-minutes-drafts")
def ai_minutes_drafts_get(
    project_id: UUID,
    meeting_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before: UUID | None = None,
    kind: DraftKind = "minutes",
) -> dict[str, Any]:
    no_store(response)
    try:
        return AiMinutesDraftService(engine, kind).get(
            context.tenant.id, project_id, meeting_id, context.user.id, before
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/{meeting_id}/ai-minutes-drafts/scope")
def ai_minutes_scope_post(
    project_id: UUID,
    meeting_id: UUID,
    body: ScopeChange,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    kind: DraftKind = "minutes",
) -> dict[str, Any]:
    no_store(response)
    try:
        return AiMinutesDraftService(engine, kind).change_scope(
            context.tenant.id, project_id, context.user.id, body
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.get("/{meeting_id}/ai-minutes-drafts/{draft_id}/history")
def ai_minutes_history_get(
    project_id: UUID,
    meeting_id: UUID,
    draft_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before: int | None = Query(default=None, ge=1),
    kind: DraftKind = "minutes",
) -> dict[str, Any]:
    no_store(response)
    try:
        return AiMinutesDraftService(engine, kind).history(
            context.tenant.id, project_id, meeting_id, draft_id, context.user.id, before
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/{meeting_id}/ai-minutes-drafts/{draft_id}/actions")
def ai_minutes_draft_post(
    project_id: UUID,
    meeting_id: UUID,
    draft_id: UUID,
    body: DraftChange,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    kind: DraftKind = "minutes",
) -> dict[str, Any]:
    no_store(response)
    try:
        return AiMinutesDraftService(engine, kind).change(
            context.tenant.id, project_id, meeting_id, draft_id, context.user.id, body
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.get("/{meeting_id}/minutes")
def get_official_minutes(
    project_id: UUID,
    meeting_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_version: int | None = Query(default=None, ge=1),
    record_id: UUID | None = None,
) -> dict[str, object]:
    no_store(response)
    try:
        return MeetingMinutesService(engine).get(
            tenant_id=context.tenant.id,
            project_id=project_id,
            meeting_id=meeting_id,
            actor_id=context.user.id,
            before_version=before_version,
            record_id=record_id,
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/{meeting_id}/minutes")
def confirm_official_minutes(
    project_id: UUID,
    meeting_id: UUID,
    body: MinutesConfirmationRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    no_store(response)
    try:
        return MeetingMinutesService(engine).confirm(
            tenant_id=context.tenant.id,
            project_id=project_id,
            meeting_id=meeting_id,
            actor_id=context.user.id,
            **body.model_dump(),
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.get("/{meeting_id}/transcripts/{transcript_id}/reading")
def get_meeting_reading(
    project_id: UUID,
    meeting_id: UUID,
    transcript_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    no_store(response)
    try:
        return MeetingReadingService.list_results(
            engine,
            tenant_id=context.tenant.id,
            project_id=project_id,
            meeting_id=meeting_id,
            transcript_id=transcript_id,
            actor_id=context.user.id,
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/{meeting_id}/transcripts/{transcript_id}/reading")
def create_meeting_reading(
    project_id: UUID,
    meeting_id: UUID,
    transcript_id: UUID,
    body: MeetingReadingRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    gateway: Annotated[ApplicationModelGateway, Depends(get_application_gateway)],
) -> dict[str, object]:
    no_store(response)
    try:
        return MeetingReadingService(engine, gateway=gateway).create(
            tenant_id=context.tenant.id,
            project_id=project_id,
            meeting_id=meeting_id,
            transcript_id=transcript_id,
            actor_id=context.user.id,
            auth_version=context.user.auth_version,
            **body.model_dump(),
        )
    except Exception as error:
        raise meeting_error(error) from error


class TranscriptAttributionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_id: UUID
    speaker_label: str | None = Field(default=None, max_length=128)
    speaker_user_id: UUID | None = None


class TranscriptAttributionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_digest: str = Field(pattern="^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=3000)
    bindings: list[TranscriptAttributionInput] = Field(min_length=1, max_length=1000)


@router.get("/{meeting_id}/transcripts/{transcript_id}")
def get_transcript_source(
    project_id: UUID,
    meeting_id: UUID,
    transcript_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    no_store(response)
    try:
        return MeetingTranscriptService(engine).get(
            tenant_id=context.tenant.id,
            project_id=project_id,
            meeting_id=meeting_id,
            transcript_id=transcript_id,
            actor_id=context.user.id,
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/{meeting_id}/transcripts/{transcript_id}/speakers")
def confirm_transcript_speakers(
    project_id: UUID,
    meeting_id: UUID,
    transcript_id: UUID,
    body: TranscriptAttributionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    no_store(response)
    try:
        return MeetingTranscriptService(engine).attribute(
            tenant_id=context.tenant.id,
            project_id=project_id,
            meeting_id=meeting_id,
            transcript_id=transcript_id,
            actor_id=context.user.id,
            **body.model_dump(),
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/{meeting_id}/status", response_model=MeetingResponse)
def change_status(
    project_id: UUID,
    meeting_id: UUID,
    body: StatusChangeRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> MeetingResponse:
    no_store(response)
    _authorize(engine, context, project_id, Action.MEETING_MANAGE)
    try:
        return meeting_response(
            MeetingService(engine).change_status(
                tenant_id=context.tenant.id,
                project_id=project_id,
                meeting_id=meeting_id,
                actor_user_id=context.user.id,
                status=body.status,
                cancelled_reason=body.cancelled_reason,
            )
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/{meeting_id}/archive", response_model=MeetingResponse)
def archive_meeting(
    project_id: UUID,
    meeting_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> MeetingResponse:
    no_store(response)
    _authorize(engine, context, project_id, Action.MEETING_MANAGE)
    try:
        return meeting_response(
            MeetingService(engine).archive(
                tenant_id=context.tenant.id,
                project_id=project_id,
                meeting_id=meeting_id,
                actor_user_id=context.user.id,
            )
        )
    except Exception as error:
        raise meeting_error(error) from error


class RetrospectiveConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_version: int = Field(ge=0)
    conclusion: str = Field(min_length=1, max_length=15000)
    applicability: str = Field(min_length=1, max_length=3000)
    reason: str = Field(min_length=1, max_length=3000)
    sources: list[KnowledgeSourceSelection] = Field(default_factory=list, max_length=20)


@router.get("/{meeting_id}/retrospective")
def retrospective_history(
    project_id: UUID,
    meeting_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    no_store(response)
    try:
        return {
            "items": MeetingRetrospectiveService(engine).history(
                tenant_id=context.tenant.id,
                project_id=project_id,
                meeting_id=meeting_id,
                actor_id=context.user.id,
            )
        }
    except (KnowledgeAccessError, KnowledgeVersionError) as error:
        raise _push_error(error) from error
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/{meeting_id}/retrospective")
def confirm_retrospective(
    project_id: UUID,
    meeting_id: UUID,
    body: RetrospectiveConfirmationRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    no_store(response)
    try:
        return MeetingRetrospectiveService(engine).confirm(
            tenant_id=context.tenant.id,
            project_id=project_id,
            meeting_id=meeting_id,
            actor_id=context.user.id,
            request_id=body.request_id,
            expected_version=body.expected_version,
            conclusion=body.conclusion,
            applicability=body.applicability,
            reason=body.reason,
            sources=tuple(body.sources),
        )
    except (KnowledgeAccessError, KnowledgeVersionError, KnowledgeSourceBindingError) as error:
        raise _push_error(error) from error
    except Exception as error:
        raise meeting_error(error) from error


class MeetingPreparationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_digest: str = Field(pattern="^[0-9a-f]{64}$")
    request_id: UUID
    organizer_id: UUID
    participants: list[ParticipantInput] = Field(max_length=100)
    items: list[AgendaItemInput] = Field(max_length=100)


@router.get("/preparation/options")
def meeting_preparation_options(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    no_store(response)
    _authorize(engine, context, project_id, Action.MEETING_VIEW)
    with engine.connect() as connection:
        return {
            "templates": TEMPLATES,
            "members": MeetingPreparationService.members(connection, context.tenant.id, project_id),
        }


@router.get("/{meeting_id}/preparation")
def get_meeting_preparation(
    project_id: UUID,
    meeting_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    no_store(response)
    try:
        return MeetingPreparationService(engine).get(
            tenant_id=context.tenant.id,
            project_id=project_id,
            meeting_id=meeting_id,
            actor_id=context.user.id,
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/{meeting_id}/preparation")
def save_meeting_preparation(
    project_id: UUID,
    meeting_id: UUID,
    body: MeetingPreparationRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    no_store(response)
    try:
        return MeetingPreparationService(engine).save(
            tenant_id=context.tenant.id,
            project_id=project_id,
            meeting_id=meeting_id,
            actor_id=context.user.id,
            request_id=body.request_id,
            expected_digest=body.expected_digest,
            organizer_id=body.organizer_id,
            participants=[item.model_dump() for item in body.participants],
            items=[item.model_dump() for item in body.items],
        )
    except Exception as error:
        raise meeting_error(error) from error


class MeetingFollowupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_basis: str = Field(pattern="^[0-9a-f]{64}$")
    action: Literal["create_action", "link_action", "close", "reopen", "carry", "reassign"]
    reason: str = Field(min_length=1, max_length=3000)
    task_id: UUID | None = None
    target_meeting_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=512)
    assignee_id: UUID | None = None
    due_date: date | None = None
    expected_output: str | None = Field(default=None, min_length=1, max_length=20000)
    no_action_required: bool = False
    owner_user_id: UUID | None = None


@router.get("/{meeting_id}/review-candidates")
def get_meeting_review_candidates(
    project_id: UUID,
    meeting_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    cursor: UUID | None = None,
) -> dict[str, object]:
    no_store(response)
    try:
        return MeetingFollowupService(engine).review_candidates(
            tenant_id=context.tenant.id,
            project_id=project_id,
            meeting_id=meeting_id,
            actor_id=context.user.id,
            cursor=cursor,
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.get("/{meeting_id}/followup")
def get_meeting_followup(
    project_id: UUID,
    meeting_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    no_store(response)
    try:
        return MeetingFollowupService(engine).get(
            tenant_id=context.tenant.id,
            project_id=project_id,
            meeting_id=meeting_id,
            actor_id=context.user.id,
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.get("/{meeting_id}/agenda/{agenda_id}/responsibility-history")
def get_meeting_agenda_responsibility_history(
    project_id: UUID,
    meeting_id: UUID,
    agenda_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_id: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, object]:
    no_store(response)
    try:
        return MeetingFollowupService(engine).responsibility_history(
            tenant_id=context.tenant.id,
            project_id=project_id,
            meeting_id=meeting_id,
            agenda_id=agenda_id,
            actor_id=context.user.id,
            before_id=before_id,
        )
    except Exception as error:
        raise meeting_error(error) from error


@router.post("/{meeting_id}/agenda/{agenda_id}/followup")
def apply_meeting_followup(
    project_id: UUID,
    meeting_id: UUID,
    agenda_id: UUID,
    body: MeetingFollowupRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    from app.api.work_items import task_error
    from app.domain.tasks import TaskNotFoundError, TaskScopeError

    no_store(response)
    try:
        return MeetingFollowupService(engine).act(
            tenant_id=context.tenant.id,
            project_id=project_id,
            meeting_id=meeting_id,
            agenda_id=agenda_id,
            actor_id=context.user.id,
            **body.model_dump(),
        )
    except (TaskScopeError, TaskNotFoundError) as error:
        raise task_error(error) from error
    except Exception as error:
        raise meeting_error(error) from error
