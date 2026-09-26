"""FMEA evidence candidates, catch-up and human disposition."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict

from app.api.auth import no_store
from app.api.living_fmea import Context, Database, Offset, error
from app.domain import fmea_candidates as service

router = APIRouter(prefix="/api/projects/{project_id}/quality/fmea/candidates", tags=["quality"])


class Scan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after_issue_id: UUID | None = None


@router.get("")
def listing(
    project_id: UUID, response: Response, context: Context, engine: Database, offset: Offset = 0
) -> dict[str, Any]:
    no_store(response)
    try:
        return service.listing(engine, context, project_id, offset)
    except Exception as exc:
        raise error(exc) from exc


@router.post("/capture")
def scan(
    project_id: UUID, body: Scan, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return service.scan(engine, context, project_id, body.after_issue_id)
    except Exception as exc:
        raise error(exc) from exc


@router.get("/{candidate_id}")
def detail(
    project_id: UUID, candidate_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return service.detail(engine, context, project_id, candidate_id)
    except Exception as exc:
        raise error(exc) from exc


@router.post("/{candidate_id}/refresh")
def refresh(
    project_id: UUID, candidate_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return service.refresh(engine, context, project_id, candidate_id)
    except Exception as exc:
        raise error(exc) from exc


@router.post("/{candidate_id}/disposition")
def dispose(
    project_id: UUID,
    candidate_id: UUID,
    body: service.Disposition,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return service.dispose(engine, context, project_id, candidate_id, body)
    except Exception as exc:
        raise error(exc) from exc
