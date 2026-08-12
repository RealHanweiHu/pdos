"""Synchronous AI API surface with server-enforced scope and evidence contracts."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine

from app.ai.application_gateway import (
    ApplicationModelGateway,
    configured_application_gateway,
)
from app.ai.chat import ChatEvidence, ChatService
from app.ai.risk_suggestions import (
    RiskSuggestionEvidenceError,
    RiskSuggestionRequestConflictError,
    RiskSuggestionService,
)
from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.engine import get_engine
from app.domain.documents import MAX_DOCUMENT_BYTES, DocumentError, DocumentService
from app.storage.documents import DocumentObjectStore, get_document_object_store

router = APIRouter(prefix="/api/ai", tags=["ai"])


class DocumentFragmentResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    ordinal: int
    locator: str
    href: str
    excerpt: str


class DocumentAnalysisResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: UUID
    project_id: UUID
    filename: str
    media_type: str
    classification: str
    size_bytes: int
    sha256: str
    extraction_status: str
    fragments: list[DocumentFragmentResponse]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    question: str = Field(min_length=1, max_length=2_000)

    @field_validator("question", mode="before")
    @classmethod
    def normalize_question(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ChatResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    answer: str | None
    citations: list[ChatEvidence]
    error_code: str | None = None


class RiskSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    request_id: str = Field(min_length=1, max_length=128)
    concern: str = Field(min_length=1, max_length=2_000)
    evidence_event_ids: tuple[int, ...] = Field(min_length=1, max_length=100)

    @field_validator("request_id", "concern", mode="before")
    @classmethod
    def normalize_risk_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class RiskSuggestionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    run_id: UUID
    finding_id: UUID | None
    error_code: str | None


def require_ai_action(context: AuthContext, action: Action) -> None:
    if not is_allowed(context.user.role, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "OBJECT_PERMISSION_DENIED", "message": "AI action is not allowed"},
        )


def get_application_gateway(
    engine: Annotated[Engine, Depends(get_engine)],
) -> Iterator[ApplicationModelGateway]:
    with configured_application_gateway(engine) as gateway:
        yield gateway


@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    gateway: Annotated[ApplicationModelGateway, Depends(get_application_gateway)],
) -> ChatResponse:
    require_ai_action(context, Action.AI_CHAT_USE)
    authorize_project(
        engine=engine,
        context=context,
        project_id=request.project_id,
        action=Action.PROJECT_VIEW,
    )
    result = ChatService(engine, gateway=gateway).answer(
        tenant_id=context.tenant.id,
        project_id=request.project_id,
        question=request.question,
    )
    no_store(response)
    return ChatResponse(
        status=result.status,
        answer=result.answer,
        citations=list(result.citations),
        error_code=result.error_code,
    )


@router.post("/create-risk-suggestion", response_model=RiskSuggestionResponse)
def create_risk_suggestion(
    request: RiskSuggestionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    gateway: Annotated[ApplicationModelGateway, Depends(get_application_gateway)],
) -> RiskSuggestionResponse:
    require_ai_action(context, Action.RISK_SUGGESTION_CREATE)
    authorize_project(
        engine=engine,
        context=context,
        project_id=request.project_id,
        action=Action.PROJECT_VIEW,
    )
    try:
        result = RiskSuggestionService(engine, gateway=gateway).create(
            tenant_id=context.tenant.id,
            project_id=request.project_id,
            actor_user_id=context.user.id,
            request_id=request.request_id,
            concern=request.concern,
            evidence_event_ids=request.evidence_event_ids,
        )
    except RiskSuggestionEvidenceError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "RISK_EVIDENCE_INVALID", "message": str(error)},
        ) from error
    except RiskSuggestionRequestConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "RISK_REQUEST_CONFLICT",
                "message": "request_id was already used with another request",
            },
        ) from error
    no_store(response)
    return RiskSuggestionResponse(
        status=result.status,
        run_id=result.run_id,
        finding_id=result.finding_id,
        error_code=result.error_code,
    )


@router.post(
    "/analyze-document",
    response_model=DocumentAnalysisResponse,
    status_code=status.HTTP_201_CREATED,
)
async def analyze_document(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
    file: Annotated[UploadFile, File()],
    project_id: Annotated[UUID, Form()],
    classification: Annotated[
        str,
        Form(pattern=r"^(internal|confidential|restricted)$"),
    ] = "internal",
) -> DocumentAnalysisResponse:
    require_ai_action(context, Action.DOCUMENT_ANALYZE)
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.PROJECT_VIEW,
    )
    content = await file.read(MAX_DOCUMENT_BYTES + 1)
    try:
        document = DocumentService(engine, object_store=object_store).analyze(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            filename=file.filename or "",
            classification=classification,
            content=content,
        )
    except DocumentError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": error.code, "message": str(error)},
        ) from error
    no_store(response)
    return DocumentAnalysisResponse(
        document_id=document.id,
        project_id=document.project_id,
        filename=document.filename,
        media_type=document.media_type,
        classification=document.classification,
        size_bytes=document.size_bytes,
        sha256=document.sha256,
        extraction_status=document.extraction_status,
        fragments=[
            DocumentFragmentResponse(
                ordinal=fragment.ordinal,
                locator=fragment.locator,
                href=(
                    f"/projects/{document.project_id}?tab=documents&document_id={document.id}"
                    f"&fragment={fragment.ordinal}"
                ),
                excerpt=fragment.text[:500],
            )
            for fragment in document.fragments
        ],
    )
