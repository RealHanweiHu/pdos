"""Project object-permission boundary for future project APIs."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.project_access import (
    ProjectAccess,
    ProjectAccessService,
    SqlProjectAccessRepository,
)
from app.auth.repository import AuthContext
from app.auth.roles import Action, Role
from app.db.engine import get_engine

router = APIRouter(prefix="/api/projects", tags=["project access"])


class ProjectAccessResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    role: Role
    allowed_actions: list[Action]


def require_project_view(
    project_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ProjectAccess:
    service = ProjectAccessService(SqlProjectAccessRepository(engine))
    try:
        return service.authorize(
            context=context,
            project_id=project_id,
            action=Action.PROJECT_VIEW,
        )
    except ObjectPermissionDeniedError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "OBJECT_PERMISSION_DENIED",
                "message": "The requested project action is not permitted",
            },
        ) from error


@router.get("/{project_id}/access", response_model=ProjectAccessResponse)
def project_access(
    response: Response,
    access: Annotated[ProjectAccess, Depends(require_project_view)],
) -> ProjectAccessResponse:
    no_store(response)
    return ProjectAccessResponse(
        project_id=access.project_id,
        role=access.role,
        allowed_actions=sorted(access.allowed_actions, key=lambda action: action.value),
    )
