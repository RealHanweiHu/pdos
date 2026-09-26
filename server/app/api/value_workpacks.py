"""Fixed team measurement scope and independent downstream receipt endpoints."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Response

from app.api.auth import no_store
from app.api.product_workspace import Context, Database
from app.api.value_measurement import failure
from app.contracts.value_workpacks import (
    Close,
    ClosePreview,
    DeliveryPreview,
    DeliverySave,
    History,
    Options,
    Read,
    ReceptionPreview,
    ReceptionSave,
    WorkpackCreate,
)
from app.domain.value_workpacks import ValueWorkpackService

router = APIRouter(prefix="/api/projects/{project_id}/value-workpacks", tags=["value-workpacks"])


@router.post("/options")
def options(
    project_id: UUID, body: Options, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ValueWorkpackService(engine).options(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/create")
def create(
    project_id: UUID, body: WorkpackCreate, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ValueWorkpackService(engine).create(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/history")
def history(
    project_id: UUID, body: History, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ValueWorkpackService(engine).history(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/read")
def read(
    project_id: UUID, body: Read, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ValueWorkpackService(engine).read(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/delivery-preview")
def delivery_preview(
    project_id: UUID, body: DeliveryPreview, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ValueWorkpackService(engine).preview(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/delivery-save")
def delivery_save(
    project_id: UUID, body: DeliverySave, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ValueWorkpackService(engine).deliver(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/reception-preview")
def reception_preview(
    project_id: UUID, body: ReceptionPreview, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ValueWorkpackService(engine).preview(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/reception-save")
def reception_save(
    project_id: UUID, body: ReceptionSave, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ValueWorkpackService(engine).receive(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/close-preview")
def close_preview(
    project_id: UUID, body: ClosePreview, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ValueWorkpackService(engine).preview(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/close")
def close(
    project_id: UUID, body: Close, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ValueWorkpackService(engine).close(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/summary")
def summary(
    project_id: UUID, body: Read, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ValueWorkpackService(engine).summary(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/study-summary")
def study_summary(
    project_id: UUID, body: History, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ValueWorkpackService(engine).study_summary(context, project_id, body)
    except Exception as error:
        raise failure(error) from error
