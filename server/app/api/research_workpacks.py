"""Actual pre-project teams with independent, version-bound downstream reception."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Response

from app.api.auth import no_store
from app.api.product_workspace import Context, Database
from app.api.research_measurement import failure
from app.contracts.research_workpacks import (
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
from app.domain.research_workpacks import ResearchWorkpackService

router = APIRouter(
    prefix="/api/product-work/spaces/{space_id}/research-workpacks", tags=["research-workpacks"]
)


@router.post("/options")
def options(
    space_id: UUID, body: Options, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchWorkpackService(engine).options(context, space_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/create")
def create(
    space_id: UUID, body: WorkpackCreate, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchWorkpackService(engine).create(context, space_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/history")
def history(
    space_id: UUID, body: History, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchWorkpackService(engine).history(context, space_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/read")
def read(
    space_id: UUID, body: Read, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchWorkpackService(engine).read(context, space_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/delivery-preview")
def delivery_preview(
    space_id: UUID, body: DeliveryPreview, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchWorkpackService(engine).preview(context, space_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/delivery-save")
def delivery_save(
    space_id: UUID, body: DeliverySave, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchWorkpackService(engine).deliver(context, space_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/reception-preview")
def reception_preview(
    space_id: UUID, body: ReceptionPreview, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchWorkpackService(engine).preview(context, space_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/reception-save")
def reception_save(
    space_id: UUID, body: ReceptionSave, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchWorkpackService(engine).receive(context, space_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/close-preview")
def close_preview(
    space_id: UUID, body: ClosePreview, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchWorkpackService(engine).preview(context, space_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/close")
def close(
    space_id: UUID, body: Close, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchWorkpackService(engine).close(context, space_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/summary")
def summary(
    space_id: UUID, body: Read, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchWorkpackService(engine).summary(context, space_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/study-summary")
def study_summary(
    space_id: UUID, body: History, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchWorkpackService(engine).study_summary(context, space_id, body)
    except Exception as error:
        raise failure(error) from error
