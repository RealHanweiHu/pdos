"""Tenant-bound Development Case and formal conversion HTTP boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.object_operations import ReviewFinalizeRequest
from app.db.engine import get_engine
from app.domain.case_requirements import (
    CaseRequirementCommand,
    CaseRequirementReadinessError,
    CaseRequirementService,
    _case,
)
from app.domain.case_reviews import (
    CaseReviewNotReadyError,
    CaseReviewService,
    ReviewAction,
    ReviewDraft,
    ReviewPolicyDraft,
    ReviewSignoff,
)
from app.domain.development_cases import (
    CaseCodeConflictError,
    CaseInvalidTransitionError,
    CaseProjectRequiredError,
    CaseTerminalError,
    CaseUpdate,
    ConversionDraft,
    ConversionResult,
    DecisionRecord,
    DevelopmentCaseNotFoundError,
    DevelopmentCaseRecord,
    DevelopmentCaseService,
    RequirementAlreadyConvertedError,
    RequirementNotApprovedError,
    RequirementNotFoundForConversionError,
)
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError
from app.domain.review_materials import material_options

router = APIRouter(tags=["development-cases"])


class DevelopmentCaseResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    requirement_id: UUID
    code: str
    title: str
    summary: str | None
    status: str
    business_case: dict[str, Any]
    created_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime


class DecisionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    requirement_id: UUID
    development_case_id: UUID
    decided_by_user_id: UUID
    decision_kind: str
    title: str
    outcome: str
    rationale: str
    decided_at: datetime


class ConversionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    development_case: DevelopmentCaseResponse
    decision: DecisionResponse


class DevelopmentCaseListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[DevelopmentCaseResponse]


class RequirementConversionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    summary: str | None = Field(default=None, max_length=20_000)
    business_case: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(min_length=1, max_length=20_000)

    @field_validator("code", "title", "rationale", mode="before")
    @classmethod
    def normalize_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("summary", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class DevelopmentCaseUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=512)
    summary: str | None = Field(default=None, max_length=20_000)
    business_case: dict[str, Any] | None = None

    @field_validator("code", "title", mode="before")
    @classmethod
    def normalize_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("summary", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @model_validator(mode="after")
    def require_nonempty_valid_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        for field_name in {"code", "title", "business_case"}:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class DevelopmentCaseTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_status: str = Field(pattern=r"^(evaluating|approved|rejected|converted)$")


def case_response(record: DevelopmentCaseRecord) -> DevelopmentCaseResponse:
    return DevelopmentCaseResponse(
        id=record.id,
        requirement_id=record.requirement_id,
        code=record.code,
        title=record.title,
        summary=record.summary,
        status=record.status,
        business_case=record.business_case,
        created_by_user_id=record.created_by_user_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def decision_response(record: DecisionRecord) -> DecisionResponse:
    return DecisionResponse(
        id=record.id,
        requirement_id=record.requirement_id,
        development_case_id=record.development_case_id,
        decided_by_user_id=record.decided_by_user_id,
        decision_kind=record.decision_kind,
        title=record.title,
        outcome=record.outcome,
        rationale=record.rationale,
        decided_at=record.decided_at,
    )


def conversion_response(result: ConversionResult) -> ConversionResponse:
    return ConversionResponse(
        development_case=case_response(result.development_case),
        decision=decision_response(result.decision),
    )


def require_case_action(context: AuthContext, action: Action) -> None:
    if not is_allowed(context.user.role, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "OBJECT_PERMISSION_DENIED",
                "message": "The requested Development Case action is not permitted",
            },
        )


def case_not_found(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "DEVELOPMENT_CASE_NOT_FOUND",
            "message": "Development Case was not found",
        },
    )


@router.post(
    "/api/requirements/{requirement_id}/convert-to-case",
    response_model=ConversionResponse,
    status_code=status.HTTP_201_CREATED,
)
def convert_requirement(
    requirement_id: UUID,
    payload: RequirementConversionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ConversionResponse:
    require_case_action(context, Action.DEVELOPMENT_CASE_CREATE)
    try:
        result = DevelopmentCaseService(engine).convert_requirement(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            requirement_id=requirement_id,
            draft=ConversionDraft(**payload.model_dump()),
        )
    except RequirementNotFoundForConversionError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "REQUIREMENT_NOT_FOUND", "message": "Requirement was not found"},
        ) from error
    except RequirementNotApprovedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "REQUIREMENT_NOT_APPROVED",
                "message": "Requirement must be approved before conversion",
            },
        ) from error
    except RequirementAlreadyConvertedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "REQUIREMENT_ALREADY_CONVERTED",
                "message": "Requirement already has a Development Case",
            },
        ) from error
    except CaseCodeConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CASE_CODE_CONFLICT", "message": "Case code already exists"},
        ) from error
    no_store(response)
    return conversion_response(result)


@router.get("/api/development-cases", response_model=DevelopmentCaseListResponse)
def list_development_cases(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> DevelopmentCaseListResponse:
    require_case_action(context, Action.DEVELOPMENT_CASE_VIEW)
    records = DevelopmentCaseService(engine).list(tenant_id=context.tenant.id)
    no_store(response)
    return DevelopmentCaseListResponse(items=[case_response(record) for record in records])


@router.get("/api/development-cases/{case_id}", response_model=DevelopmentCaseResponse)
def get_development_case(
    case_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> DevelopmentCaseResponse:
    require_case_action(context, Action.DEVELOPMENT_CASE_VIEW)
    try:
        record = DevelopmentCaseService(engine).get(
            tenant_id=context.tenant.id,
            case_id=case_id,
        )
    except DevelopmentCaseNotFoundError as error:
        raise case_not_found(error) from error
    no_store(response)
    return case_response(record)


@router.patch("/api/development-cases/{case_id}", response_model=DevelopmentCaseResponse)
def update_development_case(
    case_id: UUID,
    payload: DevelopmentCaseUpdateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> DevelopmentCaseResponse:
    require_case_action(context, Action.DEVELOPMENT_CASE_EDIT)
    try:
        record = DevelopmentCaseService(engine).update(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            case_id=case_id,
            patch=CaseUpdate(changes=payload.model_dump(exclude_unset=True)),
        )
    except DevelopmentCaseNotFoundError as error:
        raise case_not_found(error) from error
    except CaseTerminalError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CASE_TERMINAL", "message": "Terminal Case cannot be edited"},
        ) from error
    except CaseCodeConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CASE_CODE_CONFLICT", "message": "Case code already exists"},
        ) from error
    no_store(response)
    return case_response(record)


@router.post(
    "/api/development-cases/{case_id}/transitions",
    response_model=DevelopmentCaseResponse,
)
def transition_development_case(
    case_id: UUID,
    payload: DevelopmentCaseTransitionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> DevelopmentCaseResponse:
    require_case_action(context, Action.DEVELOPMENT_CASE_TRANSITION)
    try:
        record = DevelopmentCaseService(engine).transition(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            case_id=case_id,
            to_status=payload.to_status,
        )
    except DevelopmentCaseNotFoundError as error:
        raise case_not_found(error) from error
    except (CaseRequirementReadinessError, CaseReviewNotReadyError) as error:
        raise HTTPException(
            status_code=409, detail={"code": "CASE_REQUIREMENTS_NOT_READY", "message": str(error)}
        ) from error
    except CaseInvalidTransitionError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CASE_INVALID_TRANSITION", "message": "Case transition is invalid"},
        ) from error
    except CaseProjectRequiredError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CASE_PROJECT_REQUIRED",
                "message": "A Project must reference the Case before conversion",
            },
        ) from error
    no_store(response)
    return case_response(record)


# Scoped, human-maintained requirement relations alongside the original primary source.


def case_link_error(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=403 if isinstance(error, ProductWorkAccessError) else 409,
        detail={"code": "CASE_REQUIREMENT_LINK_CONFLICT", "message": str(error)},
    )


@router.get("/api/development-cases/{case_id}/requirement-links")
def case_requirement_links(
    case_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CaseRequirementService(engine).detail(context, case_id)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise case_link_error(error) from error


@router.post("/api/development-cases/{case_id}/requirement-links")
def change_case_requirement_links(
    case_id: UUID,
    payload: CaseRequirementCommand,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CaseRequirementService(engine).change(context, case_id, payload)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise case_link_error(error) from error


@router.get("/api/development-cases/{case_id}/requirement-options")
def case_requirement_options(
    case_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    q: str = "",
) -> dict[str, Any]:
    no_store(response)
    if len(q) > 120:
        raise HTTPException(status_code=422, detail={"message": "查询内容最多120字"})
    try:
        return CaseRequirementService(engine).options(context, case_id, q)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise case_link_error(error) from error


@router.get("/api/development-cases/{case_id}/requirement-link-history")
def case_requirement_history(
    case_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CaseRequirementService(engine).history(context, case_id)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise case_link_error(error) from error


@router.get("/api/requirements/{requirement_id}/case-links")
def requirement_case_links(
    requirement_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CaseRequirementService(engine).backlinks(context, requirement_id)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise case_link_error(error) from error


@router.get("/api/development-cases/{case_id}/reviews")
def case_reviews(
    case_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    review_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return CaseReviewService(engine).list(context, case_id, review_id=review_id)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise case_link_error(error) from error


@router.post("/api/development-cases/{case_id}/review-policies")
def case_review_policy(
    case_id: UUID,
    payload: ReviewPolicyDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CaseReviewService(engine).policy(context, case_id, payload)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise case_link_error(error) from error


@router.post("/api/development-cases/{case_id}/reviews")
def create_case_review(
    case_id: UUID,
    payload: ReviewDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CaseReviewService(engine).create(context, case_id, payload)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise case_link_error(error) from error


@router.post("/api/development-cases/{case_id}/reviews/{review_id}/actions")
def case_review_action(
    case_id: UUID,
    review_id: UUID,
    payload: ReviewAction,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CaseReviewService(engine).act(context, case_id, review_id, payload)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise case_link_error(error) from error


@router.post("/api/development-cases/{case_id}/reviews/{review_id}/signoffs")
def case_review_signoff(
    case_id: UUID,
    review_id: UUID,
    payload: ReviewSignoff,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CaseReviewService(engine).act(context, case_id, review_id, payload)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise case_link_error(error) from error


@router.post("/api/development-cases/{case_id}/reviews/{review_id}/finalize")
def finalize_case_review(
    case_id: UUID,
    review_id: UUID,
    payload: ReviewFinalizeRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CaseReviewService(engine).act(context, case_id, review_id, payload)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise case_link_error(error) from error


@router.get("/api/development-cases/{case_id}/review-materials")
def case_review_material_options(
    case_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    kind: Literal["specification", "test_report", "certification"],
    q: str = "",
) -> dict[str, Any]:
    no_store(response)
    require_case_action(context, Action.DEVELOPMENT_CASE_VIEW)
    if len(q) > 120:
        raise HTTPException(status_code=422, detail={"message": "查询内容最多120字"})
    try:
        with engine.connect() as connection:
            _case(connection, context, case_id)
            return material_options(
                connection, context.tenant.id, case_id, context.user.id, kind, q
            )
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise case_link_error(error) from error
