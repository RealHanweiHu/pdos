"""Private conversation boundaries; client messages never authorize business writes."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import Engine

from app.ai.application_gateway import ApplicationModelGateway
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.chat_runs import ChatRequestConflictError
from app.ai.intake_ai_runs import IntakeAiRuns, IntakeRunRequest
from app.ai.rollout_guard import CapabilityUnavailableError
from app.api.ai import get_application_gateway
from app.api.auth import current_context, no_store
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.repository import AuthContext
from app.db.engine import get_engine
from app.domain.conversation_attachments import ConversationAttachmentService
from app.domain.conversation_email_parts import (
    ConversationEmailParts,
    EmailPartSave,
    origin_records,
)
from app.domain.conversation_focus import FocusRef, Kind
from app.domain.conversation_focus import snapshot as focus_snapshot
from app.domain.conversation_report_imports import ConversationReportImports
from app.domain.conversations import ConversationAccessError, ConversationError, ConversationService
from app.domain.decision_intake_confirm import DecisionIntakeConfirm, DecisionIntakeConfirmation
from app.domain.decision_intake_preview import DecisionIntakePrepare, DecisionIntakePreviews
from app.domain.documents import MAX_DOCUMENT_BYTES, DocumentError
from app.domain.findings import FindingApplyPermissionError
from app.domain.intake_ai_findings import IntakeAiFindings, IntakeAssessment, IntakeFindingReview
from app.domain.intake_ai_imports import CitedImportPrepare, IntakeAiImports
from app.domain.intake_ai_observations import (
    IntakeAiObservations,
    ObservationAdoption,
    ObservationSelection,
)
from app.domain.intake_ai_sources import IntakeAiSources, IntakeBriefInput
from app.domain.issue_intake_confirm import IssueIntakeConfirm, IssueIntakeConfirmation
from app.domain.issue_intake_preview import IssueIntakePrepare, IssueIntakePreviews
from app.domain.knowledge_push import KnowledgeAccessError, KnowledgeVersionError
from app.domain.meetings import MeetingNotFoundError, MeetingStateError
from app.domain.nonconformance import NcrNotFoundError
from app.domain.pdf_intake_previews import PdfIntakePrepare, PdfIntakePreviews
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError
from app.domain.quality_operations import Evidence
from app.domain.test_report_workbook import ImportError_
from app.storage.documents import DocumentObjectStore, get_document_object_store

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    meeting_id: UUID | None = None
    request_id: UUID


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_context_version: int = Field(ge=1)
    body: str = Field(min_length=1, max_length=2000)
    action: Literal[
        "note",
        "project_query",
        "meeting_reading",
        "minutes",
        "actions",
        "decisions",
        "business",
        "change_work_package",
        "quality_work_package",
        "meeting_planning",
    ] = "note"
    meeting_planning_brief_id: UUID | None = None
    object_focus: FocusRef | None = None
    ncr_id: UUID | None = None
    quality_selections: list[Evidence] | None = Field(default=None, max_length=50)
    ecr_id: UUID | None = None
    impact_depth: int | None = Field(default=None, ge=1, le=5)
    allow_discussion: bool = False
    include_supplier_notices: bool = False
    transcript_id: UUID | None = None
    expected_digest: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    expected_minutes_version: int | None = Field(default=None, ge=0)
    attachment_ids: tuple[UUID, ...] = Field(default=(), max_length=6)


class ArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    archived: bool


def error_response(error: Exception) -> HTTPException:
    if isinstance(error, NcrNotFoundError):
        return HTTPException(
            404, detail={"code": "QUALITY_SOURCE_NOT_FOUND", "message": "原 NCR 当前不可用"}
        )
    if isinstance(error, ImportError_):
        return HTTPException(409, detail={"code": error.code, "message": str(error)})
    if isinstance(error, DocumentError):
        return HTTPException(422, detail={"code": error.code, "message": str(error)})
    if isinstance(
        error,
        (
            ConversationAccessError,
            ProductWorkAccessError,
            KnowledgeAccessError,
            ObjectPermissionDeniedError,
            FindingApplyPermissionError,
        ),
    ):
        return HTTPException(
            403,
            detail={
                "code": "CONVERSATION_ACCESS_DENIED",
                "message": "当前无法访问此私人会话或其来源",
            },
        )
    if isinstance(
        error,
        (
            ConversationError,
            ProductWorkError,
            ChatRequestConflictError,
            KnowledgeVersionError,
            MeetingStateError,
            MeetingNotFoundError,
        ),
    ):
        return HTTPException(
            409,
            detail={"code": "CONVERSATION_CONFLICT", "message": str(error) or "会议来源已不可用"},
        )
    if isinstance(error, (BudgetLedgerError, CapabilityUnavailableError)):
        return HTTPException(
            409,
            detail={
                "code": error.code,
                "message": "消息已保存，本次运行的能力、授权或预算条件尚不满足",
            },
        )
    raise error


@router.get("")
def list_conversations(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    meeting_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return {
            "items": ConversationService(engine).list(
                context=context, project_id=project_id, meeting_id=meeting_id
            )
        }
    except Exception as error:
        raise error_response(error) from error


@router.post("")
def create_conversation(
    body: ConversationCreate,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return ConversationService(engine).create(context=context, **body.model_dump())
    except Exception as error:
        raise error_response(error) from error


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_sequence: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    no_store(response)
    try:
        return ConversationService(engine).get(
            context=context, conversation_id=conversation_id, before_sequence=before_sequence
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/work-context/{project_id}/{kind}/{object_id}")
def work_context(
    project_id: UUID,
    kind: Kind,
    object_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        with engine.connect() as c:
            ConversationService(engine)._authorize(c, context, project_id)
            return focus_snapshot(
                c, context.tenant.id, project_id, context.user.id, kind, object_id
            )
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/messages")
def save_conversation_message(
    conversation_id: UUID,
    body: MessageCreate,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return ConversationService(engine).save_message(
            context=context, conversation_id=conversation_id, **body.model_dump()
        )
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/messages/{message_id}/run")
def dispatch_conversation_message(
    conversation_id: UUID,
    message_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    gateway: Annotated[ApplicationModelGateway, Depends(get_application_gateway)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return ConversationService(engine, gateway=gateway).dispatch(
            context=context, conversation_id=conversation_id, message_id=message_id
        )
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/archive")
def archive_conversation(
    conversation_id: UUID,
    body: ArchiveRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return ConversationService(engine).archive(
            context=context, conversation_id=conversation_id, archived=body.archived
        )
    except Exception as error:
        raise error_response(error) from error


class AttachmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    filename: str = Field(min_length=1, max_length=512)
    size_bytes: int = Field(ge=1, le=MAX_DOCUMENT_BYTES)
    sha256: str = Field(pattern="^[0-9a-f]{64}$")
    classification: Literal["internal", "confidential", "restricted"] = "internal"


@router.post("/{conversation_id}/attachments")
def register_attachment(
    conversation_id: UUID,
    body: AttachmentCreate,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return ConversationAttachmentService(engine).register(
            context=context, conversation_id=conversation_id, **body.model_dump()
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/{conversation_id}/attachments")
def list_attachments(
    conversation_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return ConversationAttachmentService(engine).list(
            context=context, conversation_id=conversation_id
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/{conversation_id}/attachments/{attachment_id}")
def get_attachment(
    conversation_id: UUID,
    attachment_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    after_ordinal: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    no_store(response)
    try:
        return ConversationAttachmentService(engine).get(
            context=context,
            conversation_id=conversation_id,
            attachment_id=attachment_id,
            after_ordinal=after_ordinal,
        )
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/attachments/{attachment_id}/content")
async def upload_attachment(
    conversation_id: UUID,
    attachment_id: UUID,
    request: Request,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> dict[str, Any]:
    no_store(response)
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_DOCUMENT_BYTES:
            raise HTTPException(
                413, detail={"code": "DOCUMENT_TOO_LARGE", "message": "单文件不能超过20 MiB"}
            )
    try:
        from starlette.concurrency import run_in_threadpool

        return await run_in_threadpool(
            ConversationAttachmentService(engine, object_store=object_store).upload,
            context=context,
            conversation_id=conversation_id,
            attachment_id=attachment_id,
            content=bytes(content),
        )
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/attachments/{attachment_id}/parse")
def parse_attachment(
    conversation_id: UUID,
    attachment_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return ConversationAttachmentService(engine, object_store=object_store).parse(
            context=context, conversation_id=conversation_id, attachment_id=attachment_id
        )
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/attachments/{attachment_id}/revoke")
def revoke_attachment(
    conversation_id: UUID,
    attachment_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return ConversationAttachmentService(engine).revoke(
            context=context, conversation_id=conversation_id, attachment_id=attachment_id
        )
    except Exception as error:
        raise error_response(error) from error


class ConversationReportImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    attachment_id: UUID
    plan_id: UUID
    publish_to_project: Literal[True]


@router.get("/{conversation_id}/messages/{message_id}/report-imports")
def list_conversation_report_imports(
    conversation_id: UUID,
    message_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return ConversationReportImports(engine).list(
            context=context, conversation_id=conversation_id, message_id=message_id
        )
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/messages/{message_id}/report-imports")
def create_conversation_report_import(
    conversation_id: UUID,
    message_id: UUID,
    body: ConversationReportImportRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
    gateway: Annotated[ApplicationModelGateway, Depends(get_application_gateway)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return ConversationReportImports(engine, object_store=object_store, gateway=gateway).create(
            context=context,
            conversation_id=conversation_id,
            message_id=message_id,
            **body.model_dump(),
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/{conversation_id}/report-imports/{operation_id}")
def get_conversation_report_import(
    conversation_id: UUID,
    operation_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return ConversationReportImports(engine).get(
            context=context, conversation_id=conversation_id, operation_id=operation_id
        )
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/report-imports/{operation_id}/prepare")
def prepare_conversation_report_import(
    conversation_id: UUID,
    operation_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
    gateway: Annotated[ApplicationModelGateway, Depends(get_application_gateway)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return ConversationReportImports(
            engine, object_store=object_store, gateway=gateway
        ).prepare(context=context, conversation_id=conversation_id, operation_id=operation_id)
    except Exception as error:
        raise error_response(error) from error


@router.get("/{conversation_id}/messages/{message_id}/decision-intake-previews")
def list_decision_intake_previews(
    conversation_id: UUID,
    message_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return DecisionIntakePreviews(engine).list(context, conversation_id, message_id)
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/messages/{message_id}/decision-intake-previews")
def prepare_decision_intake_preview(
    conversation_id: UUID,
    message_id: UUID,
    body: DecisionIntakePrepare,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return DecisionIntakePreviews(engine).prepare(context, conversation_id, message_id, body)
    except Exception as error:
        raise error_response(error) from error


@router.get("/{conversation_id}/decision-intake-previews/{preview_id}")
def get_decision_intake_preview(
    conversation_id: UUID,
    preview_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return DecisionIntakePreviews(engine).get(context, conversation_id, preview_id)
    except Exception as error:
        raise error_response(error) from error


@router.get("/{conversation_id}/messages/{message_id}/issue-intake-previews")
def list_issue_intake_previews(
    conversation_id: UUID,
    message_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return IssueIntakePreviews(engine).list(context, conversation_id, message_id)
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/messages/{message_id}/issue-intake-previews")
def prepare_issue_intake_preview(
    conversation_id: UUID,
    message_id: UUID,
    body: IssueIntakePrepare,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return IssueIntakePreviews(engine).prepare(context, conversation_id, message_id, body)
    except Exception as error:
        raise error_response(error) from error


@router.get("/{conversation_id}/issue-intake-previews/{preview_id}")
def get_issue_intake_preview(
    conversation_id: UUID,
    preview_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return IssueIntakePreviews(engine).get(context, conversation_id, preview_id)
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/decision-intake-previews/{preview_id}/confirm")
def confirm_decision_intake(
    conversation_id: UUID,
    preview_id: UUID,
    body: DecisionIntakeConfirm,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return DecisionIntakeConfirmation(engine, object_store=object_store).confirm(
            context, conversation_id, preview_id, body
        )
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/issue-intake-previews/{preview_id}/confirm")
def confirm_issue_intake(
    conversation_id: UUID,
    preview_id: UUID,
    body: IssueIntakeConfirm,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return IssueIntakeConfirmation(engine, object_store=object_store).confirm(
            context, conversation_id, preview_id, body
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/{conversation_id}/issue-intake-previews/{preview_id}/issue-options")
def list_issue_intake_options(
    conversation_id: UUID,
    preview_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    search: str = Query(default="", max_length=200),
    issue_id: UUID | None = None,
    before_updated_at: AwareDatetime | None = None,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    from app.domain.issue_intake_reuse import issue_options

    no_store(response)
    try:
        return issue_options(
            engine,
            context,
            conversation_id,
            preview_id,
            search=search,
            issue_id=issue_id,
            before_updated_at=before_updated_at,
            before_id=before_id,
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/{conversation_id}/decision-intake-previews/{preview_id}/target-options")
def decision_intake_target_options(
    conversation_id: UUID,
    preview_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    kind: Literal["decision", "issue"],
    search: str = Query(default="", max_length=200),
    target_id: UUID | None = None,
    before_updated_at: AwareDatetime | None = None,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    from app.domain.decision_intake_targets import options

    no_store(response)
    try:
        return options(
            engine,
            context,
            conversation_id,
            preview_id,
            kind=kind,
            search=search,
            target_id=target_id,
            before_updated_at=before_updated_at,
            before_id=before_id,
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/{conversation_id}/messages/{message_id}/pdf-intake-previews")
def list_pdf_intake_previews(
    conversation_id: UUID,
    message_id: UUID,
    kind: Literal["issue", "decision"],
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return PdfIntakePreviews(engine).list(context, conversation_id, message_id, kind)
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/messages/{message_id}/pdf-intake-previews")
def prepare_pdf_intake_preview(
    conversation_id: UUID,
    message_id: UUID,
    body: PdfIntakePrepare,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return PdfIntakePreviews(engine).prepare(context, conversation_id, message_id, body)
    except Exception as error:
        raise error_response(error) from error


@router.get("/{conversation_id}/messages/{message_id}/email-intake-previews")
def list_email_intake_previews(
    conversation_id: UUID,
    message_id: UUID,
    kind: Literal["issue", "decision"],
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return PdfIntakePreviews(engine, source_kind="email").list(
            context, conversation_id, message_id, kind
        )
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/messages/{message_id}/email-intake-previews")
def prepare_email_intake_preview(
    conversation_id: UUID,
    message_id: UUID,
    body: PdfIntakePrepare,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return PdfIntakePreviews(engine, source_kind="email").prepare(
            context, conversation_id, message_id, body
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/{conversation_id}/attachments/{attachment_id}/email-parts")
def email_parts(
    conversation_id: UUID,
    attachment_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return ConversationEmailParts(engine, object_store=object_store).preview(
            context, conversation_id, attachment_id
        )
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/attachments/{attachment_id}/email-parts")
def save_email_part(
    conversation_id: UUID,
    attachment_id: UUID,
    body: EmailPartSave,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return ConversationEmailParts(engine, object_store=object_store).save(
            context, conversation_id, attachment_id, body
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/{conversation_id}/attachments/{attachment_id}/email-origins")
def email_origins(
    conversation_id: UUID,
    attachment_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        with engine.connect() as c:
            service = ConversationAttachmentService(engine)
            service._scope(c, context, conversation_id)
            service._row(c, context.tenant.id, conversation_id, attachment_id)
            return origin_records(c, context.tenant.id, conversation_id, attachment_id, before_id)
    except Exception as error:
        raise error_response(error) from error


@router.get("/{conversation_id}/messages/{message_id}/intake-ai-sources")
def intake_ai_sources(
    conversation_id: UUID,
    message_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_revision: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    no_store(response)
    try:
        return IntakeAiSources(engine).list(context, conversation_id, message_id, before_revision)
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/messages/{message_id}/intake-ai-sources")
def prepare_intake_ai_sources(
    conversation_id: UUID,
    message_id: UUID,
    body: IntakeBriefInput,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return IntakeAiSources(engine).save(context, conversation_id, message_id, body)
    except Exception as error:
        raise error_response(error) from error


@router.get("/{conversation_id}/intake-ai-sources/{brief_id}")
def intake_ai_source_detail(
    conversation_id: UUID,
    brief_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return IntakeAiSources(engine).get(context, conversation_id, brief_id)
    except Exception as error:
        raise error_response(error) from error


@router.get("/{conversation_id}/intake-ai-sources/{brief_id}/runs")
def intake_ai_runs(
    conversation_id: UUID,
    brief_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return IntakeAiRuns(engine).list(context, conversation_id, brief_id)
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/intake-ai-sources/{brief_id}/runs")
def generate_intake_ai(
    conversation_id: UUID,
    brief_id: UUID,
    body: IntakeRunRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    gateway: Annotated[ApplicationModelGateway, Depends(get_application_gateway)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return IntakeAiRuns(engine, gateway).create(context, conversation_id, brief_id, body)
    except Exception as error:
        raise error_response(error) from error


@router.get("/{conversation_id}/intake-ai-findings/{finding_id}")
def intake_finding_detail(
    conversation_id: UUID,
    finding_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return IntakeAiFindings(engine).get(context, conversation_id, finding_id)
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/intake-ai-findings/{finding_id}/preview")
def intake_finding_preview(
    conversation_id: UUID,
    finding_id: UUID,
    body: IntakeAssessment,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return IntakeAiFindings(engine).preview(context, conversation_id, finding_id, body)
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/intake-ai-findings/{finding_id}/review")
def intake_finding_review(
    conversation_id: UUID,
    finding_id: UUID,
    body: IntakeFindingReview,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return IntakeAiFindings(engine).review(context, conversation_id, finding_id, body)
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/intake-ai-findings/{finding_id}/observation-preview")
def intake_observation_preview(
    conversation_id: UUID,
    finding_id: UUID,
    body: ObservationSelection,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return IntakeAiObservations(engine).preview(context, conversation_id, finding_id, body)
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/intake-ai-findings/{finding_id}/adopt-observations")
def intake_observation_adopt(
    conversation_id: UUID,
    finding_id: UUID,
    body: ObservationAdoption,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return IntakeAiObservations(engine, object_store=object_store).adopt(
            context, conversation_id, finding_id, body
        )
    except Exception as error:
        raise error_response(error) from error


@router.post("/{conversation_id}/intake-ai-findings/{finding_id}/prepare-import")
def intake_ai_prepare_import(
    conversation_id: UUID,
    finding_id: UUID,
    body: CitedImportPrepare,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return IntakeAiImports(engine).prepare(context, conversation_id, finding_id, body)
    except Exception as error:
        raise error_response(error) from error
