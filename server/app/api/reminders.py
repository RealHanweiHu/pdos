"""Reminder scan and in-app notification HTTP boundaries (vNext V1-A7)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.engine import get_engine
from app.domain import reminder_preferences as preferences
from app.domain.reminders import (
    ReminderNotFiredError,
    ReminderNotFoundError,
    ReminderService,
)
from app.integrations.reminder_delivery import ReminderDeliveryDispatcher
from app.settings import Settings, get_settings

router = APIRouter(tags=["reminders"])


class ReminderDispatchResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    enqueued: int
    already_enqueued: int
    skipped_unbound: int
    deferred_quiet_hours: int
    capped_recipients: int
    delivery_enabled: bool


@router.post(
    "/api/projects/{project_id}/reminders/dispatch",
    response_model=ReminderDispatchResponse,
)
def dispatch_reminders(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings)],
    as_of: Annotated[datetime | None, Query()] = None,
) -> ReminderDispatchResponse:
    no_store(response)
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.WORK_ITEM_EDIT,
    )
    outcome = ReminderDeliveryDispatcher(engine, settings).dispatch(
        tenant_id=context.tenant.id,
        actor_user_id=context.user.id,
        project_id=project_id,
        now=as_of,
    )
    return ReminderDispatchResponse(
        enqueued=outcome.enqueued,
        already_enqueued=outcome.already_enqueued,
        skipped_unbound=outcome.skipped_unbound,
        deferred_quiet_hours=outcome.deferred_quiet_hours,
        capped_recipients=outcome.capped_recipients,
        delivery_enabled=outcome.delivery_enabled,
    )


class ReminderScanResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    scheduled: int
    cancelled: int
    fired: int


class NotificationProjectResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    code: str
    name: str


class NotificationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project: NotificationProjectResponse
    policy_key: str
    target_entity: str
    target_entity_id: UUID
    title: str
    status: str
    escalation_level: int
    fire_at: datetime
    fired_at: datetime | None
    acknowledged_at: datetime | None


class NotificationDigestEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_key: str
    count: int


class NotificationListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[NotificationResponse]
    unread_count: int
    digest: list[NotificationDigestEntry]


@router.post(
    "/api/projects/{project_id}/reminders/scan",
    response_model=ReminderScanResponse,
)
def scan_reminders(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    as_of: Annotated[datetime | None, Query()] = None,
) -> ReminderScanResponse:
    no_store(response)
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.WORK_ITEM_EDIT,
    )
    outcome = ReminderService(engine).scan(
        tenant_id=context.tenant.id,
        actor_user_id=context.user.id,
        project_id=project_id,
        as_of=as_of,
    )
    return ReminderScanResponse(
        scheduled=outcome.scheduled, cancelled=outcome.cancelled, fired=outcome.fired
    )


@router.get("/api/me/notifications", response_model=NotificationListResponse)
def list_notifications(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> NotificationListResponse:
    no_store(response)
    if not is_allowed(context.user.role, Action.MY_WORK_VIEW):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "MY_WORK_FORBIDDEN",
                "message": "This role cannot view the notification center",
            },
        )
    items, unread_count, digest = ReminderService(engine).list_notifications(
        tenant_id=context.tenant.id,
        recipient_user_id=context.user.id,
        limit=limit,
    )
    return NotificationListResponse(
        items=[
            NotificationResponse(
                id=record.id,
                project=NotificationProjectResponse(
                    id=record.project_id, code=project_code, name=project_name
                ),
                policy_key=record.policy_key,
                target_entity=record.target_entity,
                target_entity_id=record.target_entity_id,
                title=record.title,
                status=record.status,
                escalation_level=record.escalation_level,
                fire_at=record.fire_at,
                fired_at=record.fired_at,
                acknowledged_at=record.acknowledged_at,
            )
            for record, project_code, project_name in items
        ],
        unread_count=unread_count,
        digest=[
            NotificationDigestEntry(policy_key=key, count=count)
            for key, count in sorted(digest.items())
        ],
    )


@router.post("/api/me/notifications/{reminder_id}/ack", response_model=NotificationResponse)
def acknowledge_notification(
    reminder_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> NotificationResponse:
    no_store(response)
    if not is_allowed(context.user.role, Action.MY_WORK_VIEW):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "MY_WORK_FORBIDDEN",
                "message": "This role cannot view the notification center",
            },
        )
    try:
        record = ReminderService(engine).acknowledge(
            tenant_id=context.tenant.id,
            recipient_user_id=context.user.id,
            reminder_id=reminder_id,
        )
    except ReminderNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "REMINDER_NOT_FOUND", "message": "Reminder was not found"},
        ) from error
    except ReminderNotFiredError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "REMINDER_NOT_FIRED",
                "message": "Only fired reminders can be acknowledged",
            },
        ) from error
    items, _, _ = ReminderService(engine).list_notifications(
        tenant_id=context.tenant.id, recipient_user_id=context.user.id, limit=200
    )
    for candidate, project_code, project_name in items:
        if candidate.id == record.id:
            return NotificationResponse(
                id=candidate.id,
                project=NotificationProjectResponse(
                    id=candidate.project_id, code=project_code, name=project_name
                ),
                policy_key=candidate.policy_key,
                target_entity=candidate.target_entity,
                target_entity_id=candidate.target_entity_id,
                title=candidate.title,
                status=candidate.status,
                escalation_level=candidate.escalation_level,
                fire_at=candidate.fire_at,
                fired_at=candidate.fired_at,
                acknowledged_at=candidate.acknowledged_at,
            )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "REMINDER_NOT_FOUND", "message": "Reminder was not found"},
    )


@router.get("/api/me/reminder-preferences", dependencies=[Depends(no_store)])
def read_reminder_preferences(
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings)],
    before_version: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    if not is_allowed(context.user.role, Action.MY_WORK_VIEW):
        raise HTTPException(403, detail="Personal reminder settings unavailable")
    return preferences.read(engine, context.tenant.id, context.user.id, settings, before_version)


@router.post("/api/me/reminder-preferences", dependencies=[Depends(no_store)])
def save_reminder_preferences(
    body: preferences.PreferenceInput,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    if not is_allowed(context.user.role, Action.MY_WORK_VIEW):
        raise HTTPException(403, detail="Personal reminder settings unavailable")
    try:
        preferences.save(engine, context.tenant.id, context.user.id, body)
    except preferences.PreferenceConflict as error:
        raise HTTPException(
            409,
            detail={
                "code": "REMINDER_PREFERENCE_CHANGED",
                "message": "提醒设置已在别处修改，请刷新当前设置后再保存。",
            },
        ) from error
    return preferences.read(engine, context.tenant.id, context.user.id, settings)
