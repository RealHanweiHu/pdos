"""Project Memory lifecycle and verified-only Knowledge Search HTTP boundary."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine, text

from app.ai.embeddings import EmbeddingError, EmbeddingGateway, configured_embedding_gateway
from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.engine import get_engine
from app.domain.knowledge_categories import KnowledgeClassificationError, KnowledgeKind
from app.domain.knowledge_push import (
    ContextNotFoundError,
    KnowledgeAccessError,
    KnowledgePushService,
    KnowledgeVersionError,
    PushNotFoundError,
    UnknownContextError,
)
from app.domain.knowledge_reuse import ResumeRequest
from app.domain.knowledge_sources import (
    KnowledgeSourceBindingError,
    KnowledgeSourceSelection,
    source_options,
)
from app.domain.memories import (
    MemoryContentConflictError,
    MemoryDraft,
    MemoryFourEyesError,
    MemoryInvalidTransitionError,
    MemoryNotFoundError,
    MemoryRecord,
    MemoryService,
    MemorySourceError,
    memory_review_digest,
)

router = APIRouter(tags=["memory"])


class MemoryDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1, max_length=20_000)
    applicability: str | None = Field(default=None, max_length=5_000)
    tags: list[str] = Field(default_factory=list, max_length=50)
    knowledge_kind: KnowledgeKind | None = None

    @field_validator("title", "content", mode="before")
    @classmethod
    def normalize_required(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("applicability", mode="before")
    @classmethod
    def normalize_optional(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if any(len(value) > 64 for value in normalized):
            raise ValueError("tags must not exceed 64 characters")
        return normalized


class MemoryCreateRequest(MemoryDraftRequest):
    source_selections: list[KnowledgeSourceSelection] = Field(default_factory=list, max_length=20)


class MemoryUpdateRequest(MemoryDraftRequest):
    expected_review_digest: str = Field(pattern="^[0-9a-f]{64}$")
    source_selections: list[KnowledgeSourceSelection] | None = Field(
        default=None, min_length=1, max_length=20
    )


class MemoryVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_review_digest: str = Field(pattern="^[0-9a-f]{64}$")


class MemoryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    source_finding_id: UUID | None
    source_ncr_id: UUID | None
    created_by_user_id: UUID
    verified_by_user_id: UUID | None
    archived_by_user_id: UUID | None
    title: str
    content: str
    applicability: str | None
    tags: list[str]
    knowledge_kind: KnowledgeKind | None
    source_refs: list[dict[str, object]]
    review_digest: str
    last_edited_by_user_id: UUID | None
    content_sha256: str
    status: str
    verified_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MemoryListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[MemoryResponse]


class KnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=20)
    knowledge_kind: KnowledgeKind | Literal["unclassified"] | None = None

    @field_validator("query", mode="before")
    @classmethod
    def normalize_query(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class KnowledgeSearchItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    memory: MemoryResponse
    similarity: float = Field(ge=-1, le=1)
    embedding_provider: str
    embedding_model: str
    href: str


class KnowledgeSearchResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_status: Literal["ready"] = "ready"
    items: list[KnowledgeSearchItem]


def memory_response(record: MemoryRecord) -> MemoryResponse:
    return MemoryResponse(
        id=record.id,
        project_id=record.project_id,
        source_finding_id=record.source_finding_id,
        source_ncr_id=record.source_ncr_id,
        created_by_user_id=record.created_by_user_id,
        verified_by_user_id=record.verified_by_user_id,
        archived_by_user_id=record.archived_by_user_id,
        title=record.title,
        content=record.content,
        applicability=record.applicability,
        tags=list(record.tags),
        knowledge_kind=record.knowledge_kind,
        source_refs=list(record.source_refs),
        review_digest=memory_review_digest(record),
        last_edited_by_user_id=record.last_edited_by_user_id,
        content_sha256=record.content_sha256,
        status=record.status,
        verified_at=record.verified_at,
        archived_at=record.archived_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def memory_draft(request: MemoryDraftRequest) -> MemoryDraft:
    return MemoryDraft(
        title=request.title,
        content=request.content,
        applicability=request.applicability,
        tags=tuple(request.tags),
        knowledge_kind=request.knowledge_kind,
    )


def get_embedding_gateway() -> Iterator[EmbeddingGateway]:
    try:
        with configured_embedding_gateway() as gateway:
            yield gateway
    except EmbeddingError as error:
        raise memory_error(error) from error


def memory_error(error: Exception) -> HTTPException:
    if isinstance(error, KnowledgeClassificationError):
        return HTTPException(
            status_code=409,
            detail={"code": "KNOWLEDGE_CLASSIFICATION_REQUIRED", "message": str(error)},
        )
    if isinstance(error, KnowledgeSourceBindingError):
        return HTTPException(
            status_code=409, detail={"code": "KNOWLEDGE_SOURCE_CHANGED", "message": str(error)}
        )
    if isinstance(error, MemoryNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "MEMORY_NOT_FOUND", "message": "Memory was not found"},
        )
    if isinstance(error, MemoryFourEyesError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "MEMORY_FOUR_EYES_REQUIRED",
                "message": "创建人或最后修订人不能审核同一条知识",
            },
        )
    if isinstance(error, MemorySourceError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "MEMORY_SOURCE_INVALID",
                "message": "知识来源已失效或尚待版本复核，请先检查原始依据",
            },
        )
    if isinstance(error, MemoryContentConflictError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "MEMORY_CONTENT_CONFLICT",
                "message": "知识内容、适用依据或审核版本已变化，请刷新后重新核对",
            },
        )
    if isinstance(error, MemoryInvalidTransitionError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "MEMORY_INVALID_TRANSITION",
                "message": "Memory transition is invalid",
            },
        )
    if isinstance(error, EmbeddingError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": error.code, "message": "Embedding service unavailable"},
        )
    if isinstance(error, ValueError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "MEMORY_INPUT_INVALID", "message": "Memory input is invalid"},
        )
    raise error


@router.get(
    "/api/projects/{project_id}/memories",
    response_model=MemoryListResponse,
)
def list_memories(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    memory_status: Annotated[
        Literal["draft", "verified", "archived"] | None,
        Query(alias="status"),
    ] = None,
) -> MemoryListResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.MEMORY_VIEW
    )
    return MemoryListResponse(
        items=[
            memory_response(record)
            for record in MemoryService(engine).list(
                tenant_id=context.tenant.id,
                project_id=project_id,
                status=memory_status,
            )
        ]
    )


@router.post(
    "/api/projects/{project_id}/memories",
    response_model=MemoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_memory(
    project_id: UUID,
    request: MemoryCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> MemoryResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.MEMORY_DRAFT
    )
    try:
        return memory_response(
            MemoryService(engine).create(
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                draft=memory_draft(request),
                source_selections=tuple(request.source_selections),
            )
        )
    except Exception as error:
        raise memory_error(error) from error


@router.post(
    "/api/projects/{project_id}/memories/from-ncr/{ncr_id}",
    response_model=MemoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_memory_from_ncr(
    project_id: UUID,
    ncr_id: UUID,
    request: MemoryDraftRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> MemoryResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.MEMORY_DRAFT
    )
    try:
        return memory_response(
            MemoryService(engine).create_from_ncr(
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                ncr_id=ncr_id,
                draft=memory_draft(request),
            )
        )
    except Exception as error:
        raise memory_error(error) from error


@router.patch(
    "/api/projects/{project_id}/memories/{memory_id}",
    response_model=MemoryResponse,
)
def edit_memory(
    project_id: UUID,
    memory_id: UUID,
    request: MemoryUpdateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> MemoryResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.MEMORY_DRAFT
    )
    try:
        return memory_response(
            MemoryService(engine).edit(
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                memory_id=memory_id,
                draft=memory_draft(request),
                expected_review_digest=request.expected_review_digest,
                source_selections=tuple(request.source_selections)
                if request.source_selections is not None
                else None,
            )
        )
    except Exception as error:
        raise memory_error(error) from error


@router.post(
    "/api/projects/{project_id}/memories/{memory_id}/verify",
    response_model=MemoryResponse,
)
def verify_memory(
    project_id: UUID,
    memory_id: UUID,
    response: Response,
    request: MemoryVerifyRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    gateway: Annotated[EmbeddingGateway, Depends(get_embedding_gateway)],
) -> MemoryResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.MEMORY_VERIFY
    )
    try:
        return memory_response(
            MemoryService(engine).verify(
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                memory_id=memory_id,
                gateway=gateway,
                expected_review_digest=request.expected_review_digest,
            )
        )
    except Exception as error:
        raise memory_error(error) from error


@router.post(
    "/api/projects/{project_id}/memories/{memory_id}/archive",
    response_model=MemoryResponse,
)
def archive_memory(
    project_id: UUID,
    memory_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> MemoryResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.MEMORY_ARCHIVE
    )
    try:
        return memory_response(
            MemoryService(engine).archive(
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                memory_id=memory_id,
            )
        )
    except Exception as error:
        raise memory_error(error) from error


@router.post(
    "/api/projects/{project_id}/memories/{memory_id}/reembed",
    response_model=MemoryResponse,
)
def reembed_memory(
    project_id: UUID,
    memory_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    gateway: Annotated[EmbeddingGateway, Depends(get_embedding_gateway)],
) -> MemoryResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.MEMORY_VERIFY
    )
    try:
        return memory_response(
            MemoryService(engine).reembed(
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                memory_id=memory_id,
                gateway=gateway,
            )
        )
    except Exception as error:
        raise memory_error(error) from error


@router.post("/api/knowledge/search", response_model=KnowledgeSearchResponse)
def search_knowledge(
    request: KnowledgeSearchRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    gateway: Annotated[EmbeddingGateway, Depends(get_embedding_gateway)],
) -> KnowledgeSearchResponse:
    no_store(response)
    authorize_project(
        engine=engine,
        context=context,
        project_id=request.project_id,
        action=Action.MEMORY_VIEW,
    )
    try:
        results = MemoryService(engine).search(
            tenant_id=context.tenant.id,
            project_id=request.project_id,
            query=request.query,
            gateway=gateway,
            limit=request.limit,
            knowledge_kind=request.knowledge_kind,
        )
        return KnowledgeSearchResponse(
            items=[
                KnowledgeSearchItem(
                    memory=memory_response(result.memory),
                    similarity=max(-1.0, min(1.0, result.similarity)),
                    embedding_provider=result.embedding_provider,
                    embedding_model=result.embedding_model,
                    href=(f"/knowledge?project={request.project_id}&memory={result.memory.id}"),
                )
                for result in results
            ]
        )
    except Exception as error:
        raise memory_error(error) from error


class KnowledgePushItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    push_id: UUID
    memory: MemoryResponse
    similarity: float
    rank: int
    source_project_id: UUID
    already_seen: bool
    href: str
    feedback: dict[str, object] | None = None


class KnowledgePushResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    context_kind: str
    context_entity_id: UUID
    items: list[KnowledgePushItem]


class KnowledgePushMetricsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    pushed_count: int
    engaged_count: int
    hit_rate_basis_points: int | None
    by_context: dict[str, dict[str, int]]


def _push_error(error: Exception) -> HTTPException:
    if isinstance(error, KnowledgeAccessError):
        return HTTPException(
            status_code=403, detail={"code": "KNOWLEDGE_ACCESS_DENIED", "message": str(error)}
        )
    if isinstance(error, KnowledgeVersionError):
        return HTTPException(
            status_code=409, detail={"code": "KNOWLEDGE_VERSION_CHANGED", "message": str(error)}
        )
    if isinstance(
        error,
        (
            EmbeddingError,
            MemorySourceError,
            KnowledgeSourceBindingError,
            KnowledgeClassificationError,
        ),
    ):
        return memory_error(error)
    if isinstance(error, UnknownContextError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "KNOWLEDGE_CONTEXT_UNKNOWN",
                "message": "Unsupported knowledge push context",
            },
        )
    if isinstance(error, ContextNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "KNOWLEDGE_CONTEXT_NOT_FOUND",
                "message": "Triggering object was not found in this project",
            },
        )
    if isinstance(error, PushNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "KNOWLEDGE_PUSH_NOT_FOUND", "message": "Push was not found"},
        )
    raise error


@router.get(
    "/api/projects/{project_id}/knowledge-push",
    response_model=KnowledgePushResponse,
)
def knowledge_push(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    gateway: Annotated[EmbeddingGateway, Depends(get_embedding_gateway)],
    context_kind: Annotated[str, Query(pattern="^[a-z_]{1,32}$")],
    context_entity_id: Annotated[UUID, Query()],
) -> KnowledgePushResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.MEMORY_VIEW
    )
    try:
        pushed = KnowledgePushService(engine).push_for_context(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            context_kind=context_kind,
            context_entity_id=context_entity_id,
            gateway=gateway,
            member_scoped=context.user.role not in {"owner", "admin"},
        )
    except Exception as error:
        raise _push_error(error) from error
    return KnowledgePushResponse(
        context_kind=context_kind,
        context_entity_id=context_entity_id,
        items=[
            KnowledgePushItem(
                push_id=item.push_id,
                memory=memory_response(item.memory),
                similarity=max(-1.0, min(1.0, item.similarity)),
                rank=item.rank,
                source_project_id=item.source_project_id,
                already_seen=item.already_seen,
                feedback=item.feedback,
                href=(f"/knowledge?project={item.source_project_id}&memory={item.memory.id}"),
            )
            for item in pushed
        ],
    )


@router.get("/api/projects/{project_id}/knowledge-prepared")
def knowledge_prepared(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    context_kind: Annotated[
        str, Query(pattern="^(project_kickoff|change_request|part_selection|task_takeover)$")
    ],
    context_entity_id: UUID,
    job_id: UUID | None = None,
) -> dict[str, Any]:
    from app.domain.knowledge_reuse import read_prepared

    no_store(response)
    try:
        job, items = read_prepared(
            engine,
            context.tenant.id,
            project_id,
            context.user.id,
            context_kind,
            context_entity_id,
            job_id,
        )
    except Exception as error:
        raise _push_error(error) from error
    return {
        "job": job,
        "items": [
            KnowledgePushItem(
                push_id=item.push_id,
                memory=memory_response(item.memory),
                similarity=item.similarity,
                rank=item.rank,
                source_project_id=item.source_project_id,
                already_seen=item.already_seen,
                feedback=item.feedback,
                href=f"/knowledge?project={item.source_project_id}&memory={item.memory.id}",
            ).model_dump(mode="json")
            for item in items
        ],
    }


@router.get("/api/projects/{project_id}/knowledge-prepared/requests")
def prepared_requests(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    context_kind: Annotated[
        str, Query(pattern="^(project_kickoff|change_request|part_selection|task_takeover)$")
    ],
    context_entity_id: UUID,
    before_created_at: datetime | None = None,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    from app.domain.knowledge_reuse import request_history

    no_store(response)
    try:
        return request_history(
            engine,
            context.tenant.id,
            project_id,
            context.user.id,
            context_kind,
            context_entity_id,
            before_created_at,
            before_id,
        )
    except Exception as error:
        raise _push_error(error) from error


@router.get("/api/projects/{project_id}/knowledge-prepared/{job_id}/history")
def prepared_history(
    project_id: UUID,
    job_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_id: Annotated[int | None, Query(gt=0)] = None,
) -> dict[str, Any]:
    from app.domain.knowledge_reuse import history

    no_store(response)
    try:
        return history(engine, context.tenant.id, project_id, context.user.id, job_id, before_id)
    except Exception as error:
        raise _push_error(error) from error


@router.post("/api/projects/{project_id}/knowledge-prepared/{job_id}/resume")
def prepared_resume(
    project_id: UUID,
    job_id: UUID,
    body: ResumeRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.knowledge_reuse import resume

    no_store(response)
    try:
        return resume(engine, context.tenant.id, project_id, context.user.id, job_id, body)
    except Exception as error:
        raise _push_error(error) from error


@router.get("/api/projects/{project_id}/knowledge-prepared/{job_id}/resume")
def prepared_resume_receipt(
    project_id: UUID,
    job_id: UUID,
    request_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.knowledge_reuse import resume_receipt

    no_store(response)
    try:
        return resume_receipt(
            engine, context.tenant.id, project_id, context.user.id, job_id, request_id
        )
    except Exception as error:
        raise _push_error(error) from error


@router.post(
    "/api/knowledge/pushes/{push_id}/engage",
    status_code=status.HTTP_204_NO_CONTENT,
)
def engage_knowledge_push(
    push_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> None:
    no_store(response)
    try:
        KnowledgePushService(engine).engage(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            push_id=push_id,
        )
    except Exception as error:
        raise _push_error(error) from error


@router.get("/api/knowledge/push-metrics", response_model=KnowledgePushMetricsResponse)
def knowledge_push_metrics(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> KnowledgePushMetricsResponse:
    no_store(response)
    metrics = KnowledgePushService(engine).metrics(tenant_id=context.tenant.id)
    return KnowledgePushMetricsResponse(
        pushed_count=metrics.pushed_count,
        engaged_count=metrics.engaged_count,
        hit_rate_basis_points=metrics.hit_rate_basis_points,
        by_context=metrics.by_context,
    )


class KnowledgeFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["adopted", "not_useful"]
    reason: str = Field(min_length=1, max_length=5000)
    expected_content_sha256: str = Field(pattern="^[0-9a-f]{64}$")

    @field_validator("reason")
    @classmethod
    def reason_present(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("请填写采用位置或不适用原因")
        return value.strip()


@router.post("/api/knowledge/pushes/{push_id}/feedback")
def knowledge_feedback(
    push_id: UUID,
    request: KnowledgeFeedbackRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    no_store(response)
    try:
        return KnowledgePushService(engine).record_feedback(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            push_id=push_id,
            action=request.action,
            reason=request.reason,
            expected_content_sha256=request.expected_content_sha256,
        )
    except Exception as error:
        raise _push_error(error) from error


class KnowledgeCorrectionRequest(MemoryDraftRequest):
    source_selections: list[KnowledgeSourceSelection] | None = Field(
        default=None, min_length=1, max_length=20
    )
    request_id: UUID
    expected_content_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=5000)


class KnowledgeCorrectionReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_proposal_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=5000)


@router.get("/api/projects/{project_id}/knowledge-corrections")
def list_knowledge_corrections(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    from app.domain.knowledge_corrections import KnowledgeCorrectionService

    no_store(response)
    try:
        return {
            "items": KnowledgeCorrectionService(engine).list(
                tenant_id=context.tenant.id, actor_id=context.user.id, project_id=project_id
            )
        }
    except Exception as error:
        raise _push_error(error) from error


@router.post("/api/projects/{project_id}/memories/{memory_id}/corrections")
def propose_knowledge_correction(
    project_id: UUID,
    memory_id: UUID,
    request: KnowledgeCorrectionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    from app.domain.knowledge_corrections import KnowledgeCorrectionService

    no_store(response)
    try:
        return KnowledgeCorrectionService(engine).propose(
            tenant_id=context.tenant.id,
            actor_id=context.user.id,
            project_id=project_id,
            memory_id=memory_id,
            request_id=request.request_id,
            expected_content_sha256=request.expected_content_sha256,
            draft=memory_draft(request),
            reason=request.reason,
            source_selections=tuple(request.source_selections)
            if request.source_selections is not None
            else None,
        )
    except Exception as error:
        raise _push_error(error) from error


@router.post("/api/projects/{project_id}/knowledge-corrections/{correction_id}/publish")
def publish_knowledge_correction(
    project_id: UUID,
    correction_id: UUID,
    request: KnowledgeCorrectionReview,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    gateway: Annotated[EmbeddingGateway, Depends(get_embedding_gateway)],
) -> dict[str, object]:
    from app.domain.knowledge_corrections import KnowledgeCorrectionService

    no_store(response)
    try:
        return KnowledgeCorrectionService(engine).review(
            tenant_id=context.tenant.id,
            actor_id=context.user.id,
            project_id=project_id,
            correction_id=correction_id,
            expected_proposal_sha256=request.expected_proposal_sha256,
            action="publish",
            reason=request.reason,
            gateway=gateway,
        )
    except Exception as error:
        raise _push_error(error) from error


@router.post("/api/projects/{project_id}/knowledge-corrections/{correction_id}/reject")
def reject_knowledge_correction(
    project_id: UUID,
    correction_id: UUID,
    request: KnowledgeCorrectionReview,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    from app.domain.knowledge_corrections import KnowledgeCorrectionService

    no_store(response)
    try:
        return KnowledgeCorrectionService(engine).review(
            tenant_id=context.tenant.id,
            actor_id=context.user.id,
            project_id=project_id,
            correction_id=correction_id,
            expected_proposal_sha256=request.expected_proposal_sha256,
            action="reject",
            reason=request.reason,
        )
    except Exception as error:
        raise _push_error(error) from error


@router.get("/api/projects/{project_id}/memories/{memory_id}/sources")
def memory_source_assessment(
    project_id: UUID,
    memory_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    from app.domain.knowledge_corrections import KnowledgeCorrectionService

    no_store(response)
    try:
        with engine.connect() as connection:
            KnowledgeCorrectionService._authorize(
                connection, context.tenant.id, context.user.id, project_id, Action.MEMORY_VIEW
            )
            row = (
                connection.execute(
                    text(
                        "SELECT state,sources FROM cehub_memory.memory_source_assessments "
                        "WHERE tenant_id=:tenant AND project_id=:project AND memory_id=:memory"
                    ),
                    {"tenant": context.tenant.id, "project": project_id, "memory": memory_id},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise KnowledgeAccessError("知识不存在或不能访问")
            return {
                "state": row["state"],
                "sources": row["sources"],
                "eligible": row["state"] in {"current", "manual"},
            }
    except Exception as error:
        raise _push_error(error) from error


@router.get("/api/projects/{project_id}/memory-source-options")
def knowledge_source_options(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    q: Annotated[str, Query(max_length=200)] = "",
) -> dict[str, object]:
    from app.domain.knowledge_corrections import KnowledgeCorrectionService

    no_store(response)
    try:
        with engine.connect() as connection:
            KnowledgeCorrectionService._authorize(
                connection, context.tenant.id, context.user.id, project_id, Action.MEMORY_DRAFT
            )
            return {
                "items": source_options(
                    connection,
                    tenant_id=context.tenant.id,
                    project_id=project_id,
                    actor_id=context.user.id,
                    query=q,
                ),
                "limit_per_kind": 200,
            }
    except Exception as error:
        raise _push_error(error) from error


@router.get("/api/projects/{project_id}/knowledge-learning")
def list_knowledge_learning(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    from app.domain.knowledge_learning import KnowledgeLearningWorker

    no_store(response)
    try:
        return {
            "items": KnowledgeLearningWorker(engine).list(
                tenant_id=context.tenant.id, project_id=project_id, actor_id=context.user.id
            )
        }
    except Exception as error:
        raise _push_error(error) from error


@router.post("/api/projects/{project_id}/knowledge-learning/{job_id}/collect")
def collect_knowledge_learning(
    project_id: UUID,
    job_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    from app.domain.knowledge_learning import KnowledgeLearningWorker

    no_store(response)
    try:
        return KnowledgeLearningWorker(engine).run_once(
            tenant_id=context.tenant.id,
            project_id=project_id,
            job_id=job_id,
            requested_by=context.user.id,
        )
    except Exception as error:
        raise _push_error(error) from error
