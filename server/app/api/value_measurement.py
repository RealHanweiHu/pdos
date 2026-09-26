"""Project study protocols, explicit self consent and participant observations."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response

from app.api.auth import no_store
from app.api.product_workspace import Context, Database
from app.contracts.value_measurement import (
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
from app.domain.value_measurement import ValueMeasurementService

router = APIRouter(
    prefix="/api/projects/{project_id}/value-measurement", tags=["value-measurement"]
)


def failure(error: Exception) -> HTTPException:
    if isinstance(error, PermissionError):
        return HTTPException(
            403,
            detail={
                "code": "MEASUREMENT_ACCESS_DENIED",
                "message": "无权读取或登记该项目的本人活动与原资料",
            },
        )
    if isinstance(error, ProductWorkError):
        return HTTPException(
            409, detail={"code": "MEASUREMENT_INPUT_CHANGED", "message": str(error)}
        )
    raise error


@router.post("/options")
def options(
    project_id: UUID, body: Options, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ValueMeasurementService(engine).options(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/study-create")
def study_create(
    project_id: UUID, body: StudyCreate, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ValueMeasurementService(engine).create_study(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/study-history")
def study_history(
    project_id: UUID, body: StudyHistory, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ValueMeasurementService(engine).studies(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/consent")
def consent(
    project_id: UUID, body: Consent, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ValueMeasurementService(engine).consent(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/sample-preview")
def sample_preview(
    project_id: UUID, body: SampleDraft, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ValueMeasurementService(engine).preview(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/sample-save")
def sample_save(
    project_id: UUID, body: SampleSave, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ValueMeasurementService(engine).save(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/sample-history")
def sample_history(
    project_id: UUID, body: SampleHistory, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ValueMeasurementService(engine).history(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/sample-read")
def sample_read(
    project_id: UUID, body: SampleRead, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ValueMeasurementService(engine).read(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/summary")
def summary(
    project_id: UUID, body: Summary, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ValueMeasurementService(engine).summary(context, project_id, body)
    except Exception as error:
        raise failure(error) from error
