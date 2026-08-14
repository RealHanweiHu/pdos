"""Tenant- and project-bound NPI execution HTTP boundary."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError

from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action, Role
from app.db.engine import get_engine
from app.domain.npi_execution import (
    NpiAudienceError,
    NpiConflictError,
    NpiExecutionService,
    NpiNotFoundError,
    NpiScopeError,
    NpiTransitionError,
)

router = APIRouter(prefix="/api/projects/{project_id}/npi", tags=["npi"])


class BuildCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage_id: UUID
    phase: Literal["evt", "dvt", "pvt"]
    code: str = Field(min_length=1, max_length=64)
    planned_quantity: int = Field(gt=0)
    notes: str | None = Field(default=None, max_length=20_000)


class BuildUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["in_progress", "completed", "cancelled"]
    completed_quantity: int = Field(ge=0)


class SampleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    serial_number: str = Field(min_length=1, max_length=128)
    parent_sample_id: UUID | None = None
    prototype_bom_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=20_000)


class SampleSignoffCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phase: Literal["evt", "dvt", "pvt"]
    title: str = Field(min_length=1, max_length=512)
    signoff_type: Literal[
        "evt_sample", "dvt_sample", "pvt_sample", "golden_sample", "first_article", "other"
    ]
    audience: Literal["internal", "supplier", "customer"]
    sample_ids: list[UUID] = Field(min_length=1, max_length=100)
    due_date: date | None = None

    @model_validator(mode="after")
    def unique_samples(self) -> SampleSignoffCreateRequest:
        if len(set(self.sample_ids)) != len(self.sample_ids):
            raise ValueError("sample_ids must be unique")
        return self


class SampleSignoffResponseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["approved", "rejected", "waived"]
    note: str | None = Field(default=None, max_length=20_000)


class TestPlanCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage_id: UUID
    phase: Literal["evt", "dvt", "pvt"]
    title: str = Field(min_length=1, max_length=512)
    scope: str | None = Field(default=None, max_length=20_000)
    sample_size: int = Field(gt=0)
    status: Literal["draft", "active"] = "draft"


class TestCaseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=512)
    category: str = Field(min_length=1, max_length=64)
    acceptance_criteria: str = Field(min_length=1, max_length=20_000)
    method: str | None = Field(default=None, max_length=20_000)
    severity: Literal["minor", "major", "critical"] = "major"
    sample_ids: list[UUID] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_samples(self) -> TestCaseCreateRequest:
        if len(set(self.sample_ids)) != len(self.sample_ids):
            raise ValueError("sample_ids must be unique")
        return self


class TestResultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["planned", "passed", "failed", "blocked", "waived"]
    result_notes: str | None = Field(default=None, max_length=20_000)
    related_issue_id: UUID | None = None


class TestReportCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_number: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    result: Literal["pass", "fail", "conditional"]
    summary: str = Field(min_length=1, max_length=20_000)


class TestReportReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_status: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=20_000)


class CertificationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_user_id: UUID | None = None
    certificate_type: Literal[
        "un38_3",
        "msds",
        "battery_safety",
        "product_safety",
        "component_safety",
        "market_access",
        "regulatory_compliance",
    ]
    certificate_number: str | None = Field(default=None, max_length=256)
    issuing_body: str | None = Field(default=None, max_length=256)
    target_markets: list[str] = Field(default_factory=list, max_length=100)
    status: Literal["draft", "valid", "expired", "revoked"] = "draft"
    is_required: bool = False
    valid_from: date | None = None
    valid_until: date | None = None
    evidence_reference: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def valid_certificate_has_identity(self) -> CertificationCreateRequest:
        if (
            self.valid_until is not None
            and self.valid_from is not None
            and self.valid_until < self.valid_from
        ):
            raise ValueError("valid_until cannot precede valid_from")
        if self.status == "valid" and (not self.certificate_number or self.valid_until is None):
            raise ValueError("valid certification requires certificate_number and valid_until")
        return self


class CertificationScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of: date


def _clean(value: str | None) -> str | None:
    normalized = value.strip() if value else ""
    return normalized or None


def _access(engine: Engine, context: AuthContext, project_id: UUID, action: Action) -> None:
    authorize_project(engine=engine, context=context, project_id=project_id, action=action)


def _error(error: Exception) -> HTTPException:
    if isinstance(error, NpiNotFoundError):
        return HTTPException(
            status_code=404, detail={"code": "NPI_NOT_FOUND", "message": "NPI record was not found"}
        )
    if isinstance(error, (NpiScopeError, NpiTransitionError, NpiConflictError, IntegrityError)):
        return HTTPException(
            status_code=409,
            detail={
                "code": "NPI_CONFLICT",
                "message": "NPI operation conflicts with project truth",
            },
        )
    if isinstance(error, NpiAudienceError):
        return HTTPException(
            status_code=403,
            detail={
                "code": "NPI_AUDIENCE_DENIED",
                "message": "Signoff audience does not match actor",
            },
        )
    raise error


@router.get("")
def get_npi(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, list[dict[str, Any]]]:
    no_store(response)
    _access(engine, context, project_id, Action.PROJECT_VIEW)
    return NpiExecutionService(engine).snapshot(
        tenant_id=context.tenant.id, project_id=project_id, role=context.user.role
    )


@router.post("/builds", status_code=status.HTTP_201_CREATED)
def create_build(
    project_id: UUID,
    body: BuildCreateRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
    try:
        return NpiExecutionService(engine).create_build(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            stage_id=body.stage_id,
            phase=body.phase,
            code=body.code.strip(),
            planned_quantity=body.planned_quantity,
            notes=_clean(body.notes),
        )
    except Exception as error:
        raise _error(error) from error


@router.patch("/builds/{build_id}")
def update_build(
    project_id: UUID,
    build_id: UUID,
    body: BuildUpdateRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
    try:
        return NpiExecutionService(engine).update_build(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            build_id=build_id,
            status=body.status,
            completed_quantity=body.completed_quantity,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/builds/{build_id}/samples", status_code=status.HTTP_201_CREATED)
def create_sample(
    project_id: UUID,
    build_id: UUID,
    body: SampleCreateRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
    try:
        return NpiExecutionService(engine).create_sample(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            build_id=build_id,
            serial_number=body.serial_number.strip(),
            parent_sample_id=body.parent_sample_id,
            prototype_bom_id=body.prototype_bom_id,
            notes=_clean(body.notes),
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/sample-signoffs", status_code=status.HTTP_201_CREATED)
def create_signoff(
    project_id: UUID,
    body: SampleSignoffCreateRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
    try:
        return NpiExecutionService(engine).create_signoff(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            phase=body.phase,
            title=body.title.strip(),
            signoff_type=body.signoff_type,
            audience=body.audience,
            sample_ids=body.sample_ids,
            due_date=body.due_date,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/sample-signoffs/{signoff_id}/respond")
def respond_signoff(
    project_id: UUID,
    signoff_id: UUID,
    body: SampleSignoffResponseRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    action = (
        Action.EXTERNAL_RESPOND
        if context.user.role in {Role.SUPPLIER, Role.CUSTOMER}
        else Action.QUALITY_MANAGE
    )
    _access(engine, context, project_id, action)
    try:
        return NpiExecutionService(engine).respond_signoff(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            actor_role=context.user.role,
            signoff_id=signoff_id,
            status=body.status,
            note=_clean(body.note),
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/test-plans", status_code=status.HTTP_201_CREATED)
def create_test_plan(
    project_id: UUID,
    body: TestPlanCreateRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.WORK_ITEM_EDIT)
    try:
        return NpiExecutionService(engine).create_test_plan(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            stage_id=body.stage_id,
            phase=body.phase,
            title=body.title.strip(),
            scope=_clean(body.scope),
            sample_size=body.sample_size,
            status=body.status,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/test-plans/{plan_id}/cases", status_code=status.HTTP_201_CREATED)
def create_test_case(
    project_id: UUID,
    plan_id: UUID,
    body: TestCaseCreateRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.WORK_ITEM_EDIT)
    try:
        return NpiExecutionService(engine).create_test_case(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            plan_id=plan_id,
            title=body.title.strip(),
            category=body.category.strip(),
            acceptance_criteria=body.acceptance_criteria.strip(),
            method=_clean(body.method),
            severity=body.severity,
            sample_ids=body.sample_ids,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/test-cases/{test_case_id}/result")
def record_test_result(
    project_id: UUID,
    test_case_id: UUID,
    body: TestResultRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.WORK_ITEM_EDIT)
    try:
        return NpiExecutionService(engine).record_test_result(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            test_case_id=test_case_id,
            status=body.status,
            result_notes=_clean(body.result_notes),
            related_issue_id=body.related_issue_id,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/test-plans/{plan_id}/reports", status_code=status.HTTP_201_CREATED)
def create_test_report(
    project_id: UUID,
    plan_id: UUID,
    body: TestReportCreateRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.WORK_ITEM_EDIT)
    try:
        return NpiExecutionService(engine).create_test_report(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            plan_id=plan_id,
            report_number=body.report_number.strip(),
            title=body.title.strip(),
            result=body.result,
            summary=body.summary.strip(),
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/test-reports/{report_id}/review")
def review_test_report(
    project_id: UUID,
    report_id: UUID,
    body: TestReportReviewRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.QUALITY_MANAGE)
    try:
        return NpiExecutionService(engine).review_test_report(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            report_id=report_id,
            review_status=body.review_status,
            note=_clean(body.note),
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/certifications", status_code=status.HTTP_201_CREATED)
def create_certification(
    project_id: UUID,
    body: CertificationCreateRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.QUALITY_MANAGE)
    values = body.model_dump(exclude={"owner_user_id"})
    values["certificate_number"] = _clean(body.certificate_number)
    values["issuing_body"] = _clean(body.issuing_body)
    values["evidence_reference"] = _clean(body.evidence_reference)
    values["target_markets"] = sorted(
        {market.strip().upper() for market in body.target_markets if market.strip()}
    )
    try:
        return NpiExecutionService(engine).create_certification(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            owner_user_id=body.owner_user_id or context.user.id,
            values=values,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/certifications/scan")
def scan_certifications(
    project_id: UUID,
    body: CertificationScanRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, int]:
    _access(engine, context, project_id, Action.QUALITY_MANAGE)
    try:
        return NpiExecutionService(engine).scan_certifications(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            as_of=body.as_of,
        )
    except Exception as error:
        raise _error(error) from error
