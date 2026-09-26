"""Bounded original uploads and explicit human review of mobile field captures."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine
from starlette.concurrency import run_in_threadpool

from app.api.auth import current_context, no_store
from app.auth.repository import AuthContext
from app.db.engine import get_engine
from app.domain.field_capture_drafts import CaptureConflict, FieldCaptureDraftService
from app.domain.field_capture_inputs import CaptureDraft
from app.domain.field_captures import MAX_BYTES, CaptureError, FieldCaptureService
from app.domain.field_recognitions import FieldRecognitionService
from app.domain.issues import IssueNotFoundError, IssueScopeError
from app.domain.knowledge_push import KnowledgeAccessError
from app.domain.test_runs import (
    TestRunFactError,
    TestRunNotFoundError,
    TestRunScopeError,
    TestRunStateError,
)
from app.storage.documents import DocumentObjectStore, get_document_object_store

router = APIRouter(prefix="/api/field-captures/projects/{project_id}", tags=["field-captures"])
Context = Annotated[AuthContext, Depends(current_context)]
Database = Annotated[Engine, Depends(get_engine)]
Store = Annotated[DocumentObjectStore, Depends(get_document_object_store)]


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=512)
    media_type: str = Field(max_length=128)
    size_bytes: int = Field(ge=1, le=MAX_BYTES)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class CaptureCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    original_text: str = Field(default="", max_length=20000)
    attachment: Attachment | None = None


class CaptureReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1, max_length=16000)
    issue_type: Literal["engineering", "quality", "supplier", "test_failure", "certification"] = (
        "engineering"
    )
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    sample_id: UUID | None = None
    sample_reason: str = Field(default="", max_length=2000)
    confirmed: Literal[True]

    @field_validator("title", "description", mode="before")
    @classmethod
    def normalize(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


def failure(error: Exception) -> HTTPException:
    if isinstance(error, CaptureConflict):
        return HTTPException(409, detail={"message": str(error)})
    if isinstance(error, KnowledgeAccessError):
        return HTTPException(403, detail={"message": "当前无权办理此项目的现场资料"})
    if isinstance(
        error,
        (
            CaptureError,
            IssueScopeError,
            IssueNotFoundError,
            TestRunFactError,
            TestRunNotFoundError,
            TestRunScopeError,
            TestRunStateError,
        ),
    ):
        return HTTPException(400, detail={"message": str(error) or "请核对项目和样机范围"})
    return HTTPException(503, detail={"message": "现场采集暂不可用，保留原输入后重试"})


@router.get("")
def list_captures(
    project_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return {"items": FieldCaptureService(engine).list_captures(context, project_id)}
    except Exception as error:
        raise failure(error) from error


@router.post("")
def create(
    project_id: UUID, body: CaptureCreate, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return FieldCaptureService(engine).create(
            context,
            project_id,
            body.request_id,
            body.original_text,
            body.attachment.model_dump() if body.attachment else None,
        )
    except Exception as error:
        raise failure(error) from error


@router.get("/samples")
def samples(
    project_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    q: Annotated[str, Query(max_length=200)] = "",
) -> dict[str, Any]:
    no_store(response)
    try:
        return {"items": FieldCaptureService(engine).samples(context, project_id, q)}
    except Exception as error:
        raise failure(error) from error


@router.get("/test-cases")
def test_cases(
    project_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    q: Annotated[str, Query(max_length=200)] = "",
) -> dict[str, Any]:
    no_store(response)
    try:
        return {"items": FieldCaptureDraftService(engine).cases(context, project_id, q)}
    except Exception as error:
        raise failure(error) from error


@router.get("/{capture_id}")
def get(
    project_id: UUID, capture_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return FieldCaptureService(engine).get(context, project_id, capture_id)
    except Exception as error:
        raise failure(error) from error


@router.put("/{capture_id}/original")
async def upload(
    project_id: UUID,
    capture_id: UUID,
    request: Request,
    response: Response,
    context: Context,
    engine: Database,
    store: Store,
) -> dict[str, Any]:
    no_store(response)
    try:
        service = FieldCaptureService(engine, store)
        await run_in_threadpool(service.get, context, project_id, capture_id)
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > MAX_BYTES:
                raise HTTPException(413, detail={"message": "原件不能超过12 MiB"})
            content.extend(chunk)
        return await run_in_threadpool(
            service.upload, context, project_id, capture_id, bytes(content)
        )
    except HTTPException:
        raise
    except Exception as error:
        raise failure(error) from error


@router.get("/{capture_id}/original")
def original(
    project_id: UUID, capture_id: UUID, context: Context, engine: Database, store: Store
) -> Response:
    try:
        content, media = FieldCaptureService(engine, store).original(
            context, project_id, capture_id
        )
        return Response(
            content,
            media_type=media,
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": "inline",
            },
        )
    except Exception as error:
        raise failure(error) from error


@router.post("/{capture_id}/issue")
def submit(
    project_id: UUID,
    capture_id: UUID,
    body: CaptureReview,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return FieldCaptureService(engine).submit(
            context, project_id, capture_id, body.model_dump(mode="json")
        )
    except Exception as error:
        raise failure(error) from error


class SaveDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_version: int = Field(ge=0)
    draft: CaptureDraft


class SubmitDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    confirmed: Literal[True]


@router.get("/{capture_id}/drafts")
def draft_history(
    project_id: UUID,
    capture_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return FieldCaptureDraftService(engine).history(context, project_id, capture_id, before)
    except Exception as error:
        raise failure(error) from error


@router.post("/{capture_id}/drafts")
def save_draft(
    project_id: UUID,
    capture_id: UUID,
    body: SaveDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return FieldCaptureDraftService(engine).save(
            context, project_id, capture_id, body.request_id, body.expected_version, body.draft
        )
    except Exception as error:
        raise failure(error) from error


@router.post("/{capture_id}/submit")
def submit_draft(
    project_id: UUID,
    capture_id: UUID,
    body: SubmitDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return FieldCaptureDraftService(engine).submit(
            context, project_id, capture_id, body.expected_version
        )
    except Exception as error:
        raise failure(error) from error


class RecognitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    language: Literal["zh", "en", "auto"] = "zh"


@router.get("/{capture_id}/recognitions")
def recognitions(
    project_id: UUID, capture_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return FieldRecognitionService(engine).list(context, project_id, capture_id)
    except Exception as error:
        raise failure(error) from error


@router.post("/{capture_id}/recognitions")
def recognize(
    project_id: UUID,
    capture_id: UUID,
    body: RecognitionRequest,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return FieldRecognitionService(engine).request(
            context, project_id, capture_id, body.request_id, body.language
        )
    except Exception as error:
        raise failure(error) from error


@router.get("/{capture_id}/recognitions/{recognition_id}")
def recognition_result(
    project_id: UUID,
    capture_id: UUID,
    recognition_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return FieldRecognitionService(engine).get(context, project_id, capture_id, recognition_id)
    except Exception as error:
        raise failure(error) from error


@router.post("/{capture_id}/recognitions/{recognition_id}/cancel")
def cancel_recognition(
    project_id: UUID,
    capture_id: UUID,
    recognition_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return FieldRecognitionService(engine).cancel(
            context, project_id, capture_id, recognition_id
        )
    except Exception as error:
        raise failure(error) from error
