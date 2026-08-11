"""Owner/Admin-only Event catalog and ordered debug stream."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.engine import get_engine
from app.domain.events import EventProjectNotFoundError, EventQueryService, EventRecord
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
