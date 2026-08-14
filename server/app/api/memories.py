"""Project Memory lifecycle and verified-only Knowledge Search HTTP boundary."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine

from app.ai.embeddings import EmbeddingError, EmbeddingGateway, configured_embedding_gateway
from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.engine import get_engine
from app.domain.memories import (
    MemoryContentConflictError,
    MemoryDraft,
    MemoryFourEyesError,
    MemoryInvalidTransitionError,
    MemoryNotFoundError,
    MemoryRecord,
    MemoryService,
    MemorySourceError,
)

router = APIRouter(tags=["memory"])


class MemoryDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1, max_length=20_000)
    applicability: str | None = Field(default=None, max_length=5_000)
    tags: list[str] = Field(default_factory=list, max_length=50)

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
    source_refs: list[dict[str, object]]
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
        source_refs=list(record.source_refs),
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
    )


def get_embedding_gateway() -> Iterator[EmbeddingGateway]:
    try:
        with configured_embedding_gateway() as gateway:
            yield gateway
    except EmbeddingError as error:
        raise memory_error(error) from error


def memory_error(error: Exception) -> HTTPException:
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
                "message": "Memory creator cannot verify the same Memory",
            },
        )
    if isinstance(error, MemorySourceError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "MEMORY_SOURCE_INVALID", "message": "Memory source is invalid"},
        )
    if isinstance(error, MemoryContentConflictError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "MEMORY_CONTENT_CONFLICT",
                "message": "Memory content or embedding route changed",
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
            MemoryService(engine).create(
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                draft=memory_draft(request),
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
            MemoryService(engine).edit(
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                memory_id=memory_id,
                draft=memory_draft(request),
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
