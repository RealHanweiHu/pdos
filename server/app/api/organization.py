"""Owner/Admin HTTP surface for org structure, delegation, and handover (vNext V1-A11)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.engine import get_engine
from app.domain.organization import (
    DelegationNotFoundError,
    DelegationRecord,
    DelegationWindowError,
    DepartmentNotFoundError,
    DepartmentRecord,
    HandoverTargetError,
    OrganizationService,
    ReportingCycleError,
    UserNotFoundError,
)

router = APIRouter(prefix="/api/admin/organization", tags=["organization"])


def _require_user_management(context: AuthContext) -> None:
    if not is_allowed(context.user.role, Action.USER_MANAGE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "USER_MANAGEMENT_FORBIDDEN", "message": "User management denied"},
        )


def organization_error(error: Exception) -> HTTPException:
    from sqlalchemy.exc import DBAPIError

    from app.domain.responsibility_handover import HandoverConflictError

    if isinstance(error, HandoverConflictError):
        return HTTPException(
            status_code=409, detail={"code": "HANDOVER_REVIEW_REQUIRED", "message": str(error)}
        )
    if isinstance(error, DBAPIError) and getattr(error.orig, "sqlstate", None) == "40001":
        return HTTPException(
            status_code=409,
            detail={"code": "HANDOVER_CHANGED", "message": "办理期间责任有变化，请刷新清单后重试"},
        )
    if isinstance(error, DepartmentNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DEPARTMENT_NOT_FOUND", "message": "Department was not found"},
        )
    if isinstance(error, UserNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "USER_NOT_FOUND", "message": "User was not found"},
        )
    if isinstance(error, DelegationNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "DELEGATION_NOT_FOUND",
                "message": "Delegation was not found or already revoked",
            },
        )
    if isinstance(error, ReportingCycleError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "REPORTING_CYCLE",
                "message": "Reporting line would form a cycle",
            },
        )
    if isinstance(error, DelegationWindowError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "DELEGATION_WINDOW_INVALID",
                "message": "Delegation window must end in the future and after it starts",
            },
        )
    if isinstance(error, HandoverTargetError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "HANDOVER_TARGET_INVALID",
                "message": "Source and target must be two different people",
            },
        )
    raise error


class DepartmentResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    name: str
    parent_department_id: UUID | None
    created_at: datetime
    updated_at: datetime


class DepartmentListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[DepartmentResponse]


class DepartmentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    parent_department_id: UUID | None = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class PlacementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    department_id: UUID | None = None
    manager_user_id: UUID | None = None


class EscalationChainResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    manager_user_ids: list[UUID]


class DelegationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    principal_user_id: UUID
    delegate_user_id: UUID
    starts_at: datetime
    ends_at: datetime
    reason: str
    created_by_user_id: UUID
    revoked_at: datetime | None
    revoked_by_user_id: UUID | None
    created_at: datetime


class DelegationListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[DelegationResponse]


class DelegationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_user_id: UUID
    delegate_user_id: UUID
    starts_at: datetime
    ends_at: datetime
    reason: str = Field(min_length=1, max_length=512)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class HandoverPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_user_id: UUID
    to_user_id: UUID


class HandoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_user_id: UUID
    to_user_id: UUID
    deactivate_source: bool = True
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class HandoverResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    from_user_id: UUID
    to_user_id: UUID
    transferred_counts: dict[str, int]
    deactivated: bool


def department_response(record: DepartmentRecord) -> DepartmentResponse:
    return DepartmentResponse(
        id=record.id,
        name=record.name,
        parent_department_id=record.parent_department_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def delegation_response(record: DelegationRecord) -> DelegationResponse:
    return DelegationResponse(
        id=record.id,
        principal_user_id=record.principal_user_id,
        delegate_user_id=record.delegate_user_id,
        starts_at=record.starts_at,
        ends_at=record.ends_at,
        reason=record.reason,
        created_by_user_id=record.created_by_user_id,
        revoked_at=record.revoked_at,
        revoked_by_user_id=record.revoked_by_user_id,
        created_at=record.created_at,
    )


@router.get("/departments", response_model=DepartmentListResponse)
def list_departments(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> DepartmentListResponse:
    no_store(response)
    _require_user_management(context)
    return DepartmentListResponse(
        items=[
            department_response(record)
            for record in OrganizationService(engine).list_departments(tenant_id=context.tenant.id)
        ]
    )


@router.post(
    "/departments",
    response_model=DepartmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_department(
    body: DepartmentCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> DepartmentResponse:
    no_store(response)
    _require_user_management(context)
    try:
        return department_response(
            OrganizationService(engine).create_department(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                name=body.name,
                parent_department_id=body.parent_department_id,
            )
        )
    except Exception as error:
        raise organization_error(error) from error


@router.put("/users/{user_id}/placement", status_code=status.HTTP_204_NO_CONTENT)
def set_placement(
    user_id: UUID,
    body: PlacementRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> None:
    no_store(response)
    _require_user_management(context)
    try:
        OrganizationService(engine).assign_placement(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            user_id=user_id,
            department_id=body.department_id,
            manager_user_id=body.manager_user_id,
        )
    except Exception as error:
        raise organization_error(error) from error


@router.get("/users/{user_id}/escalation-chain", response_model=EscalationChainResponse)
def get_escalation_chain(
    user_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> EscalationChainResponse:
    no_store(response)
    _require_user_management(context)
    return EscalationChainResponse(
        user_id=user_id,
        manager_user_ids=list(
            OrganizationService(engine).escalation_chain_for(
                tenant_id=context.tenant.id, user_id=user_id
            )
        ),
    )


@router.get("/delegations", response_model=DelegationListResponse)
def list_delegations(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    principal_user_id: Annotated[UUID | None, Query()] = None,
    delegate_user_id: Annotated[UUID | None, Query()] = None,
) -> DelegationListResponse:
    no_store(response)
    _require_user_management(context)
    return DelegationListResponse(
        items=[
            delegation_response(record)
            for record in OrganizationService(engine).list_delegations(
                tenant_id=context.tenant.id,
                principal_user_id=principal_user_id,
                delegate_user_id=delegate_user_id,
            )
        ]
    )


@router.post(
    "/delegations",
    response_model=DelegationResponse,
    status_code=status.HTTP_201_CREATED,
)
def grant_delegation(
    body: DelegationCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> DelegationResponse:
    no_store(response)
    _require_user_management(context)
    try:
        return delegation_response(
            OrganizationService(engine).grant_delegation(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                principal_user_id=body.principal_user_id,
                delegate_user_id=body.delegate_user_id,
                starts_at=body.starts_at,
                ends_at=body.ends_at,
                reason=body.reason,
            )
        )
    except Exception as error:
        raise organization_error(error) from error


@router.post("/delegations/{delegation_id}/revoke", response_model=DelegationResponse)
def revoke_delegation(
    delegation_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> DelegationResponse:
    no_store(response)
    _require_user_management(context)
    try:
        return delegation_response(
            OrganizationService(engine).revoke_delegation(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                delegation_id=delegation_id,
            )
        )
    except Exception as error:
        raise organization_error(error) from error


@router.post("/handover/preview")
def preview_handover(
    body: HandoverPreviewRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    _require_user_management(context)
    try:
        return OrganizationService(engine).preview_handover(
            tenant_id=context.tenant.id, from_user_id=body.from_user_id, to_user_id=body.to_user_id
        )
    except Exception as error:
        raise organization_error(error) from error


@router.post("/handover", response_model=HandoverResponse)
def hand_over(
    body: HandoverRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> HandoverResponse:
    no_store(response)
    _require_user_management(context)
    try:
        result = OrganizationService(engine).hand_over(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            from_user_id=body.from_user_id,
            to_user_id=body.to_user_id,
            deactivate_source=body.deactivate_source,
            expected_digest=body.expected_digest,
        )
    except Exception as error:
        raise organization_error(error) from error
    return HandoverResponse(
        from_user_id=result.from_user_id,
        to_user_id=result.to_user_id,
        transferred_counts=result.transferred_counts,
        deactivated=result.deactivated,
    )


@router.get("/handover/history")
def handover_history(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    from_user_id: UUID | None = None,
    to_user_id: UUID | None = None,
    before_id: Annotated[int | None, Query(gt=0)] = None,
) -> dict[str, Any]:
    from app.domain.handover_workflows import history

    no_store(response)
    _require_user_management(context)
    return history(engine, context.tenant.id, from_user_id, to_user_id, before_id)
