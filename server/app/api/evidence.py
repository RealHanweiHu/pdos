"""Evidence and research source HTTP boundary (vNext V2-7, C8).

Tenant-scoped rather than project-scoped: one capture serves every project, so
authorization is the tenant RBAC action, not project membership.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.engine import get_engine
from app.domain import research_source_responsibilities
from app.domain.evidence import (
    EvidenceContentUnavailableError,
    EvidenceImmutableError,
    EvidenceService,
    EvidenceSnapshotNotFoundError,
    EvidenceSnapshotRecord,
    EvidenceValidationError,
    ResearchSourceNotFoundError,
    ResearchSourceRecord,
)
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError

router = APIRouter(prefix="/api/evidence", tags=["evidence"])


def _require(context: AuthContext, action: Action) -> None:
    if not is_allowed(context.user.role, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "EVIDENCE_FORBIDDEN", "message": "Evidence access denied"},
        )


def evidence_error(error: Exception) -> HTTPException:
    if isinstance(error, ResearchSourceNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RESEARCH_SOURCE_NOT_FOUND",
                "message": "Research source was not found",
            },
        )
    if isinstance(error, EvidenceSnapshotNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "EVIDENCE_SNAPSHOT_NOT_FOUND",
                "message": "Evidence snapshot was not found",
            },
        )
    if isinstance(error, EvidenceContentUnavailableError):
        return HTTPException(
            409, detail={"code": "EVIDENCE_CONTENT_UNAVAILABLE", "message": str(error)}
        )
    if isinstance(error, EvidenceImmutableError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "EVIDENCE_SNAPSHOT_IMMUTABLE",
                "message": "Captured evidence cannot be rewritten",
            },
        )
    if isinstance(error, EvidenceValidationError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "EVIDENCE_INVALID",
                "message": "Evidence request was rejected",
            },
        )
    raise error


class ResearchSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    source_type: str
    base_url: str | None
    owner_user_id: UUID
    license_note: str | None
    allowed_use: str
    collection_frequency: str
    retention_policy: str
    trust_tier: str
    status: str


class ResearchSourceListResponse(BaseModel):
    items: list[ResearchSourceResponse]


class SnapshotResponse(BaseModel):
    id: UUID
    source_id: UUID | None
    url: str | None
    captured_at: datetime
    captured_by_user_id: UUID
    content_digest: str
    content_ref: str
    content_language: str
    source_version: str | None
    trust_tier: str
    taint: str
    byte_size: int
    freshness_expires_at: datetime | None
    superseded_by_id: UUID | None
    conflicts_with_id: UUID | None
    conflict_note: str | None
    reused_existing: bool
    is_stale: bool


class SnapshotListResponse(BaseModel):
    items: list[SnapshotResponse]


class ResearchSourceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    source_type: str
    allowed_use: str
    collection_frequency: str
    retention_policy: str = Field(default="standard")
    trust_tier: str = Field(default="unknown")
    base_url: str | None = None
    license_note: str | None = None
    owner_user_id: UUID | None = None

    @field_validator("source_type")
    @classmethod
    def _known_source_type(cls, value: str) -> str:
        if value not in {"web", "api", "file", "internal_system"}:
            raise ValueError("unknown source type")
        return value

    @field_validator("allowed_use")
    @classmethod
    def _known_allowed_use(cls, value: str) -> str:
        if value not in {"internal_analysis", "internal_citation", "redistribution"}:
            raise ValueError("unknown allowed use")
        return value

    @field_validator("collection_frequency")
    @classmethod
    def _known_frequency(cls, value: str) -> str:
        if value not in {"on_demand", "daily", "weekly", "monthly", "event_driven"}:
            raise ValueError("unknown collection frequency")
        return value


class SnapshotCaptureRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2 * 1024 * 1024)
    source_id: UUID | None = None
    url: str | None = None
    source_version: str | None = Field(default=None, max_length=128)
    content_language: str = Field(default="zh-CN", max_length=16)
    trust_tier: str | None = None
    taint: str | None = None
    freshness_expires_at: datetime | None = None


class SupersedeRequest(BaseModel):
    superseded_by_id: UUID


class ConflictRequest(BaseModel):
    conflicts_with_id: UUID
    note: str = Field(min_length=1)


def snapshot_response(record: EvidenceSnapshotRecord) -> SnapshotResponse:
    return SnapshotResponse(
        id=record.id,
        source_id=record.source_id,
        url=record.url,
        captured_at=record.captured_at,
        captured_by_user_id=record.captured_by_user_id,
        content_digest=record.content_digest,
        content_ref=record.content_ref,
        content_language=record.content_language,
        source_version=record.source_version,
        trust_tier=record.trust_tier,
        taint=record.taint,
        byte_size=record.byte_size,
        freshness_expires_at=record.freshness_expires_at,
        superseded_by_id=record.superseded_by_id,
        conflicts_with_id=record.conflicts_with_id,
        conflict_note=record.conflict_note,
        reused_existing=record.reused_existing,
        is_stale=record.is_stale(as_of=datetime.now(UTC)),
    )


@router.get("/sources", response_model=ResearchSourceListResponse)
def list_sources(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ResearchSourceListResponse:
    no_store(response)
    _require(context, Action.EVIDENCE_VIEW)
    records: list[ResearchSourceRecord] = EvidenceService(engine).list_sources(
        tenant_id=context.tenant.id
    )
    return ResearchSourceListResponse(
        items=[ResearchSourceResponse.model_validate(item) for item in records]
    )


@router.post(
    "/sources",
    response_model=ResearchSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_source(
    body: ResearchSourceCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ResearchSourceResponse:
    no_store(response)
    _require(context, Action.RESEARCH_SOURCE_MANAGE)
    try:
        record = EvidenceService(engine).create_source(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            name=body.name,
            source_type=body.source_type,
            allowed_use=body.allowed_use,
            collection_frequency=body.collection_frequency,
            retention_policy=body.retention_policy,
            trust_tier=body.trust_tier,
            base_url=body.base_url,
            license_note=body.license_note,
            owner_user_id=body.owner_user_id,
        )
    except Exception as error:
        raise evidence_error(error) from error
    return ResearchSourceResponse.model_validate(record)


@router.get("/snapshots", response_model=SnapshotListResponse)
def list_snapshots(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    source_id: UUID | None = None,
    include_superseded: bool = True,
) -> SnapshotListResponse:
    no_store(response)
    _require(context, Action.EVIDENCE_VIEW)
    records = EvidenceService(engine).list_snapshots(
        tenant_id=context.tenant.id,
        source_id=source_id,
        include_superseded=include_superseded,
    )
    return SnapshotListResponse(items=[snapshot_response(item) for item in records])


@router.post("/snapshots", response_model=SnapshotResponse, status_code=status.HTTP_201_CREATED)
def capture_snapshot(
    body: SnapshotCaptureRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> SnapshotResponse:
    no_store(response)
    _require(context, Action.EVIDENCE_CAPTURE)
    try:
        record = EvidenceService(engine).capture(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            content=body.content,
            source_id=body.source_id,
            url=body.url,
            source_version=body.source_version,
            content_language=body.content_language,
            trust_tier=body.trust_tier,
            taint=body.taint,
            freshness_expires_at=body.freshness_expires_at,
        )
    except Exception as error:
        raise evidence_error(error) from error
    return snapshot_response(record)


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotResponse)
def get_snapshot(
    snapshot_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> SnapshotResponse:
    no_store(response)
    _require(context, Action.EVIDENCE_VIEW)
    try:
        record = EvidenceService(engine).get_snapshot(
            tenant_id=context.tenant.id, snapshot_id=snapshot_id
        )
    except Exception as error:
        raise evidence_error(error) from error
    return snapshot_response(record)


@router.post("/snapshots/{snapshot_id}/supersede", response_model=SnapshotResponse)
def supersede_snapshot(
    snapshot_id: UUID,
    body: SupersedeRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> SnapshotResponse:
    no_store(response)
    _require(context, Action.EVIDENCE_CAPTURE)
    try:
        record = EvidenceService(engine).supersede(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            snapshot_id=snapshot_id,
            superseded_by_id=body.superseded_by_id,
        )
    except Exception as error:
        raise evidence_error(error) from error
    return snapshot_response(record)


@router.post("/snapshots/{snapshot_id}/conflict", response_model=SnapshotResponse)
def record_conflict(
    snapshot_id: UUID,
    body: ConflictRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> SnapshotResponse:
    no_store(response)
    _require(context, Action.EVIDENCE_CAPTURE)
    try:
        record = EvidenceService(engine).record_conflict(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            snapshot_id=snapshot_id,
            conflicts_with_id=body.conflicts_with_id,
            note=body.note,
        )
    except Exception as error:
        raise evidence_error(error) from error
    return snapshot_response(record)


@router.get("/snapshots/{snapshot_id}/content")
def snapshot_content(
    snapshot_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    _require(context, Action.EVIDENCE_VIEW)
    try:
        return EvidenceService(engine).read_content(
            tenant_id=context.tenant.id, snapshot_id=snapshot_id
        )
    except Exception as error:
        raise evidence_error(error) from error


@router.get("/sources/{source_id}/responsibility")
def source_responsibility_get(
    source_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_id: int | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return research_source_responsibilities.read(engine, context, source_id, before_id)
    except ProductWorkAccessError as exc:
        raise HTTPException(
            403, detail={"code": "SOURCE_RESPONSIBILITY_FORBIDDEN", "message": str(exc)}
        ) from exc
    except ProductWorkError as exc:
        raise HTTPException(
            409, detail={"code": "SOURCE_RESPONSIBILITY_INVALID", "message": str(exc)}
        ) from exc


@router.post("/sources/{source_id}/responsibility")
def source_responsibility_change(
    source_id: UUID,
    body: research_source_responsibilities.Reassign,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return research_source_responsibilities.reassign(engine, context, source_id, body)
    except ProductWorkAccessError as exc:
        raise HTTPException(
            403, detail={"code": "SOURCE_RESPONSIBILITY_FORBIDDEN", "message": str(exc)}
        ) from exc
    except ProductWorkError as exc:
        raise HTTPException(
            409, detail={"code": "SOURCE_RESPONSIBILITY_INVALID", "message": str(exc)}
        ) from exc
