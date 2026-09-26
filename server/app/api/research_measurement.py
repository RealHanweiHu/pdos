"""Typed participant measurements without synthetic project identity."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response

from app.api.auth import no_store
from app.api.product_workspace import Context, Database
from app.contracts.research_measurement import (
    Consent,
    Options,
    SampleDraft,
    SampleHistory,
    SampleRead,
    SampleSave,
    StudyCreate,
    StudyHistory,
    Summary,
)
from app.domain.product_workspace import ProductWorkError
from app.domain.research_measurement import ResearchMeasurementService

router = APIRouter(
    prefix="/api/product-work/spaces/{space_id}/research-measurement", tags=["research-measurement"]
)


def failure(error: Exception) -> HTTPException:
    if isinstance(error, PermissionError):
        return HTTPException(
            403,
            detail={
                "code": "RESEARCH_MEASUREMENT_ACCESS_DENIED",
                "message": "无权读取当前范围或原业务资料",
            },
        )
    if isinstance(error, ProductWorkError):
        return HTTPException(
            409, detail={"code": "RESEARCH_MEASUREMENT_INPUT_CHANGED", "message": str(error)}
        )
    raise error


@router.post("/options")
def options(
    space_id: UUID, body: Options, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchMeasurementService(engine).options(context, space_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/study-create")
def study_create(
    space_id: UUID, body: StudyCreate, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchMeasurementService(engine).create_study(context, space_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/study-history")
def study_history(
    space_id: UUID, body: StudyHistory, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchMeasurementService(engine).studies(context, space_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/consent")
def consent(
    space_id: UUID, body: Consent, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchMeasurementService(engine).consent(context, space_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/sample-preview")
def sample_preview(
    space_id: UUID, body: SampleDraft, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchMeasurementService(engine).preview(context, space_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/sample-save")
def sample_save(
    space_id: UUID, body: SampleSave, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchMeasurementService(engine).save(context, space_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/sample-history")
def sample_history(
    space_id: UUID, body: SampleHistory, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchMeasurementService(engine).history(context, space_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/sample-read")
def sample_read(
    space_id: UUID, body: SampleRead, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchMeasurementService(engine).read(context, space_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/summary")
def summary(
    space_id: UUID, body: Summary, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchMeasurementService(engine).summary(context, space_id, body)
    except Exception as error:
        raise failure(error) from error
