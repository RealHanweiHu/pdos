"""Project webhook administration and durable queue operations."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Response

from app.api.auth import no_store
from app.api.product_workspace import Context, Database
from app.api.project_reports import failure
from app.domain.project_webhooks import (
    ControlHistory,
    DeliveryAction,
    DeliveryHistory,
    EndpointControl,
    EndpointCreate,
    EndpointHistory,
    NoticePreview,
    NoticeSave,
    ProjectWebhookService,
    ScanHistory,
    SourceOptions,
)

router = APIRouter(prefix="/api/projects/{project_id}/webhooks", tags=["project-webhooks"])


@router.post("/options")
def options(
    project_id: UUID, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectWebhookService(engine).options(context, project_id)
    except Exception as error:
        raise failure(error) from error


@router.post("/create")
def create(
    project_id: UUID, body: EndpointCreate, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectWebhookService(engine).create(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/control")
def set_control(
    project_id: UUID, body: EndpointControl, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectWebhookService(engine).set_control(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/history")
def history(
    project_id: UUID, body: EndpointHistory, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectWebhookService(engine).history(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/sources")
def sources(
    project_id: UUID, body: SourceOptions, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectWebhookService(engine).sources(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/preview")
def preview(
    project_id: UUID, body: NoticePreview, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectWebhookService(engine).preview(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/enqueue")
def enqueue(
    project_id: UUID, body: NoticeSave, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectWebhookService(engine).enqueue(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/deliveries")
def deliveries(
    project_id: UUID, body: DeliveryHistory, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectWebhookService(engine).deliveries(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/delivery-action")
def delivery_action(
    project_id: UUID, body: DeliveryAction, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectWebhookService(engine).delivery_action(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/controls")
def controls(
    project_id: UUID, body: ControlHistory, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectWebhookService(engine).controls(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/scans")
def scans(
    project_id: UUID, body: ScanHistory, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectWebhookService(engine).scans(context, project_id, body)
    except Exception as error:
        raise failure(error) from error
