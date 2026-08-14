"""Owner/Admin-only Event catalog and ordered debug stream."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.engine import get_engine
from app.domain.events import (
    CrmCustomerNotFoundError,
    CrmRequirementConflictError,
    EventIdempotencyConflictError,
    EventProjectNotFoundError,
    EventQueryService,
    EventRecord,
    ExternalEventService,
    ExternalEventTypeDeniedError,
    InvalidEventPayloadError,
    SensitiveAuditDataError,
)
from app.events.catalog import (
    EVENT_REGISTRY,
    SPRINT_1_IMPLEMENTED_EVENT_TYPES,
    EventDefinition,
)

router = APIRouter(prefix="/api/events", tags=["events"])


class EventDefinitionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_type: str
    version: int
    entity: str
    producer: str
    consumers: list[str]
    payload_schema: dict[str, Any]
    idempotency: str
    implemented_in_sprint_1: bool


class EventCatalogResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[EventDefinitionResponse]


class EventResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    project_id: UUID | None
    event_id: str
    event_type: str
    schema_version: int
    source: str
    entity: str
    entity_id: UUID
    payload: dict[str, Any]
    timestamp: datetime
    consumers: list[str]


class EventListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[EventResponse]
    next_after_id: int | None
    has_more: bool


class EventIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    event_id: str = Field(min_length=1, max_length=128)
    event_type: str = Field(min_length=1, max_length=64)
    entity_id: UUID
    payload: dict[str, Any]
    occurred_at: datetime

    @field_validator("event_id", "event_type", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value


class EventIngestResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    created: bool
    event: EventResponse
    requirement_id: UUID | None = None


def require_event_debug(context: AuthContext) -> None:
    if not is_allowed(context.user.role, Action.EVENT_DEBUG_VIEW):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "OBJECT_PERMISSION_DENIED",
                "message": "Event debugging is restricted to tenant administrators",
            },
        )


def definition_response(definition: EventDefinition) -> EventDefinitionResponse:
    return EventDefinitionResponse(
        event_type=definition.event_type,
        version=definition.version,
        entity=definition.entity,
        producer=definition.producer,
        consumers=list(definition.consumers),
        payload_schema=definition.payload_schema,
        idempotency=definition.idempotency,
        implemented_in_sprint_1=(definition.event_type in SPRINT_1_IMPLEMENTED_EVENT_TYPES),
    )


def event_response(record: EventRecord) -> EventResponse:
    return EventResponse(
        id=record.id,
        project_id=record.project_id,
        event_id=record.event_id,
        event_type=record.event_type,
        schema_version=record.schema_version,
        source=record.source,
        entity=record.entity,
        entity_id=record.entity_id,
        payload=record.payload,
        timestamp=record.timestamp,
        consumers=list(record.consumers),
    )


@router.post("", response_model=EventIngestResponse, status_code=status.HTTP_201_CREATED)
def ingest_event(
    request: EventIngestRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> EventIngestResponse:
    if not is_allowed(context.user.role, Action.EVENT_INGEST):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "OBJECT_PERMISSION_DENIED", "message": "Event ingestion is denied"},
        )
    authorize_project(
        engine=engine,
        context=context,
        project_id=request.project_id,
        action=Action.PROJECT_VIEW,
    )
    try:
        result = ExternalEventService(engine).ingest(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=request.project_id,
            event_id=request.event_id,
            event_type=request.event_type,
            entity_id=request.entity_id,
            payload=request.payload,
            occurred_at=request.occurred_at,
        )
    except ExternalEventTypeDeniedError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "EXTERNAL_EVENT_TYPE_DENIED",
                "message": "Event type is not accepted by the external ingress",
            },
        ) from error
    except (InvalidEventPayloadError, SensitiveAuditDataError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "INVALID_EVENT_PAYLOAD", "message": "Event payload is invalid"},
        ) from error
    except EventIdempotencyConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "EVENT_IDEMPOTENCY_CONFLICT",
                "message": "event_id was already used with a different request",
            },
        ) from error
    except CrmCustomerNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "CRM_CUSTOMER_NOT_FOUND",
                "message": "CRM customer code does not identify an active tenant customer",
            },
        ) from error
    except CrmRequirementConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CRM_REQUIREMENT_CONFLICT",
                "message": "CRM requirement identity conflicts with an existing record",
            },
        ) from error
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    no_store(response)
    return EventIngestResponse(
        created=result.created,
        event=event_response(result.record),
        requirement_id=result.requirement_id,
    )


@router.get("/catalog", response_model=EventCatalogResponse)
def event_catalog(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
) -> EventCatalogResponse:
    require_event_debug(context)
    no_store(response)
    return EventCatalogResponse(
        items=[
            definition_response(definition)
            for definition in sorted(EVENT_REGISTRY.values(), key=lambda item: item.event_type)
        ]
    )


@router.get("", response_model=EventListResponse)
def list_events(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    after_id: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    event_type: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    project_id: UUID | None = None,
) -> EventListResponse:
    require_event_debug(context)
    no_store(response)
    try:
        page = EventQueryService(engine).list(
            tenant_id=context.tenant.id,
            after_id=after_id,
            limit=limit,
            event_type=event_type,
            project_id=project_id,
        )
    except EventProjectNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PROJECT_NOT_FOUND", "message": "Project was not found"},
        ) from error
    return EventListResponse(
        items=[event_response(item) for item in page.items],
        next_after_id=page.next_after_id,
        has_more=page.has_more,
    )
