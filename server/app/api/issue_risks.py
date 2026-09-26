"""Project-scoped Issue and Risk HTTP boundaries."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Engine, select

from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.engine import get_engine
from app.db.schema import tables
from app.domain import (
    risk_candidate_batches,
    risk_followup_results,
    risk_followups,
    risk_references,
)
from app.domain.issues import (
    IssueAssignmentIncompleteError,
    IssueCloseNotVerifierError,
    IssueClosureEvidenceRequiredError,
    IssueDraft,
    IssueFourEyesError,
    IssueInvalidTransitionError,
    IssueNotFoundError,
    IssueRecord,
    IssueRejectNotVerifierError,
    IssueScopeError,
    IssueService,
    IssueSubmitNotOwnerError,
    IssueTerminalError,
    IssueUpdate,
)
from app.domain.process_template_fields import (
    TemplateFieldConflictError,
    TemplateFieldError,
    project_fields,
)
from app.domain.process_template_risk_fields import project_fields as risk_project_fields
from app.domain.risk_candidates import RiskCandidateService, ScanResult
from app.domain.risks import (
    RiskDraft,
    RiskInvalidTransitionError,
    RiskNotConfirmedError,
    RiskNotFoundError,
    RiskRecord,
    RiskScopeError,
    RiskService,
    RiskTerminalError,
    RiskUpdate,
    RiskVersionConflictError,
)

router = APIRouter(prefix="/api/projects/{project_id}", tags=["work-items"])


class IssueResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    stage_id: UUID | None
    owner_user_id: UUID | None
    verifier_user_id: UUID | None
    sample_id: UUID | None
    reported_by_user_id: UUID
    title: str
    description: str | None
    issue_type: str
    status: str
    severity: str
    root_cause: str | None
    resolution: str | None
    closure_criteria: str | None
    closure_evidence_ref: str | None
    reopen_count: int
    target_date: date | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    source_finding_id: UUID | None = None
    source_field_capture_id: UUID | None = None
    template_fields: dict[str, Any] = Field(default_factory=dict)


class IssueListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[IssueResponse]


class IssueCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: UUID | None = None
    owner_user_id: UUID | None = None
    verifier_user_id: UUID | None = None
    sample_id: UUID | None = None
    title: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=20_000)
    issue_type: str = Field(
        default="engineering",
        pattern=r"^(engineering|quality|supplier|test_failure|certification)$",
    )
    severity: str = Field(default="medium", pattern=r"^(low|medium|high|critical)$")
    root_cause: str | None = Field(default=None, max_length=20_000)
    resolution: str | None = Field(default=None, max_length=20_000)
    closure_criteria: str | None = Field(default=None, max_length=20_000)
    target_date: date | None = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("description", "root_cause", "resolution", "closure_criteria", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class IssueUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_updated_at: AwareDatetime | None = None

    stage_id: UUID | None = None
    owner_user_id: UUID | None = None
    verifier_user_id: UUID | None = None
    sample_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=20_000)
    issue_type: str | None = Field(
        default=None,
        pattern=r"^(engineering|quality|supplier|test_failure|certification)$",
    )
    severity: str | None = Field(default=None, pattern=r"^(low|medium|high|critical)$")
    root_cause: str | None = Field(default=None, max_length=20_000)
    resolution: str | None = Field(default=None, max_length=20_000)
    closure_criteria: str | None = Field(default=None, max_length=20_000)
    target_date: date | None = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("description", "root_cause", "resolution", "closure_criteria", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not (self.model_fields_set - {"expected_updated_at"}):
            raise ValueError("at least one field must be supplied")
        for field_name in {"title", "severity", "issue_type"}:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


ISSUE_ASSIGNMENT_FIELDS = frozenset(
    {"owner_user_id", "verifier_user_id", "target_date", "closure_criteria"}
)


class IssueTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_updated_at: AwareDatetime | None = None

    to_status: str = Field(pattern=r"^(analysis|action|verification|closed)$")
    comment: str | None = Field(default=None, max_length=2_000)
    closure_evidence_ref: str | None = Field(default=None, max_length=2_000)

    @field_validator("comment", "closure_evidence_ref", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class RiskResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    owner_user_id: UUID | None
    title: str
    description: str | None
    status: str
    likelihood: int
    impact: int
    score: int
    mitigation_plan: str | None
    contingency_plan: str | None
    target_date: date | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    source_finding_id: UUID | None = None
    template_fields: dict[str, Any] = Field(default_factory=dict)


class RiskListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[RiskResponse]


class RiskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_user_id: UUID | None = None
    title: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=20_000)
    likelihood: int = Field(default=1, ge=1, le=5)
    impact: int = Field(default=1, ge=1, le=5)
    mitigation_plan: str | None = Field(default=None, max_length=20_000)
    contingency_plan: str | None = Field(default=None, max_length=20_000)
    target_date: date | None = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "description",
        "mitigation_plan",
        "contingency_plan",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class RiskUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_updated_at: AwareDatetime | None = None

    owner_user_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=20_000)
    likelihood: int | None = Field(default=None, ge=1, le=5)
    impact: int | None = Field(default=None, ge=1, le=5)
    mitigation_plan: str | None = Field(default=None, max_length=20_000)
    contingency_plan: str | None = Field(default=None, max_length=20_000)
    target_date: date | None = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "description",
        "mitigation_plan",
        "contingency_plan",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not (self.model_fields_set - {"expected_updated_at"}):
            raise ValueError("at least one field must be supplied")
        for field_name in {"title", "likelihood", "impact"}:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class RiskTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_updated_at: AwareDatetime | None = None

    to_status: str = Field(pattern=r"^(mitigating|watching|closed)$")


def issue_response(record: IssueRecord) -> IssueResponse:
    return IssueResponse.model_validate(record, from_attributes=True)


def risk_response(record: RiskRecord) -> RiskResponse:
    return RiskResponse.model_validate(record, from_attributes=True)


def issue_error(error: Exception) -> HTTPException:
    if isinstance(error, (TemplateFieldError, TemplateFieldConflictError)):
        return HTTPException(
            status_code=409 if isinstance(error, TemplateFieldConflictError) else 422,
            detail={"code": "ISSUE_TEMPLATE_FIELDS", "message": str(error)},
        )
    if isinstance(error, IssueNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ISSUE_NOT_FOUND", "message": "Issue was not found"},
        )
    if isinstance(error, IssueScopeError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "ISSUE_RELATED_OBJECT_NOT_FOUND",
                "message": "Related object was not found",
            },
        )
    if isinstance(error, IssueInvalidTransitionError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ISSUE_INVALID_TRANSITION",
                "message": "Issue transition is not allowed",
            },
        )
    if isinstance(error, IssueTerminalError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "ISSUE_TERMINAL", "message": "Closed Issue cannot be edited"},
        )
    if isinstance(error, IssueAssignmentIncompleteError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ISSUE_ASSIGNMENT_INCOMPLETE",
                "message": (
                    "Owner, verifier, target date, and closure criteria "
                    "are required before analysis"
                ),
            },
        )
    if isinstance(error, IssueFourEyesError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ISSUE_FOUR_EYES_REQUIRED",
                "message": "High and critical Issues need a verifier distinct from the owner",
            },
        )
    if isinstance(error, IssueCloseNotVerifierError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ISSUE_CLOSE_REQUIRES_VERIFIER",
                "message": "Only the assigned verifier can close a high or critical Issue",
            },
        )
    if isinstance(error, IssueSubmitNotOwnerError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ISSUE_SUBMIT_REQUIRES_OWNER",
                "message": "Only the assigned owner can submit an Issue for verification",
            },
        )
    if isinstance(error, IssueRejectNotVerifierError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ISSUE_REJECT_REQUIRES_VERIFIER",
                "message": "Only the assigned verifier can reject a verification",
            },
        )
    if isinstance(error, IssueClosureEvidenceRequiredError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ISSUE_CLOSURE_EVIDENCE_REQUIRED",
                "message": "High and critical Issues need closure evidence to close",
            },
        )
    raise error


def risk_error(error: Exception) -> HTTPException:
    if isinstance(error, (TemplateFieldError, TemplateFieldConflictError)):
        return HTTPException(
            409 if isinstance(error, TemplateFieldConflictError) else 422,
            detail={"code": "RISK_TEMPLATE_FIELDS", "message": str(error)},
        )
    if isinstance(error, risk_references.RiskReferencedError):
        return HTTPException(
            status_code=409,
            detail={
                "code": "RISK_HAS_BUSINESS_REFERENCES",
                "message": (
                    "风险已有任务、会议、阶段评审或交接引用，不能退回草稿；"
                    "请查看业务引用并在原记录继续处理"
                ),
            },
        )
    if isinstance(error, risk_candidate_batches.RiskCandidateSourceChangedError):
        return HTTPException(
            status_code=409,
            detail={
                "code": "RISK_CANDIDATE_SOURCE_CHANGED",
                "message": "来源或规则内容已变化，本项目整组未提交；请重新扫描并核对候选",
            },
        )
    if isinstance(error, RiskVersionConflictError):
        return HTTPException(
            status_code=409,
            detail={
                "code": "RISK_VERSION_CHANGED",
                "message": "风险内容或状态已变化，请刷新工作卡后核对",
            },
        )
    if isinstance(error, RiskNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RISK_NOT_FOUND", "message": "Risk was not found"},
        )
    if isinstance(error, RiskScopeError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RISK_RELATED_OBJECT_NOT_FOUND",
                "message": "Related object was not found",
            },
        )
    if isinstance(error, RiskInvalidTransitionError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "RISK_INVALID_TRANSITION", "message": "Risk transition is not allowed"},
        )
    if isinstance(error, RiskTerminalError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "RISK_TERMINAL", "message": "Closed Risk cannot be edited"},
        )
    if isinstance(error, RiskNotConfirmedError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "RISK_NOT_CONFIRMED",
                "message": "Risk candidates must be confirmed before editing",
            },
        )
    raise error


def require_access(
    *, engine: Engine, context: AuthContext, project_id: UUID, action: Action
) -> None:
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=action,
    )


@router.get("/issues", response_model=IssueListResponse)
def list_issues(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> IssueListResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW
    )
    return IssueListResponse(
        items=[
            issue_response(item)
            for item in IssueService(engine).list(
                tenant_id=context.tenant.id, project_id=project_id
            )
        ]
    )


@router.post("/issues", response_model=IssueResponse, status_code=status.HTTP_201_CREATED)
def create_issue(
    project_id: UUID,
    body: IssueCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> IssueResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    if ISSUE_ASSIGNMENT_FIELDS & body.model_fields_set:
        require_access(
            engine=engine, context=context, project_id=project_id, action=Action.ISSUE_ASSIGN
        )
    try:
        record = IssueService(engine).create(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            draft=IssueDraft(
                stage_id=body.stage_id,
                owner_user_id=body.owner_user_id,
                verifier_user_id=body.verifier_user_id,
                sample_id=body.sample_id,
                title=body.title,
                description=body.description,
                issue_type=body.issue_type,
                severity=body.severity,
                root_cause=body.root_cause,
                resolution=body.resolution,
                closure_criteria=body.closure_criteria,
                target_date=body.target_date,
            ),
        )
    except Exception as error:
        raise issue_error(error) from error
    return issue_response(record)


@router.get("/issues/{issue_id}", response_model=IssueResponse)
def get_issue(
    project_id: UUID,
    issue_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> IssueResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW
    )
    try:
        return issue_response(
            IssueService(engine).get(
                tenant_id=context.tenant.id,
                project_id=project_id,
                issue_id=issue_id,
            )
        )
    except Exception as error:
        raise issue_error(error) from error


@router.patch("/issues/{issue_id}", response_model=IssueResponse)
def update_issue(
    project_id: UUID,
    issue_id: UUID,
    body: IssueUpdateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> IssueResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    if ISSUE_ASSIGNMENT_FIELDS & body.model_fields_set:
        require_access(
            engine=engine, context=context, project_id=project_id, action=Action.ISSUE_ASSIGN
        )
    try:
        return issue_response(
            IssueService(engine).update(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                issue_id=issue_id,
                patch=IssueUpdate(
                    changes=body.model_dump(exclude_unset=True, exclude={"expected_updated_at"}),
                    expected_updated_at=body.expected_updated_at,
                ),
            )
        )
    except Exception as error:
        raise issue_error(error) from error


@router.post("/issues/{issue_id}/transitions", response_model=IssueResponse)
def transition_issue(
    project_id: UUID,
    issue_id: UUID,
    body: IssueTransitionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> IssueResponse:
    no_store(response)
    require_access(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.ISSUE_VERIFY if body.to_status == "closed" else Action.ISSUE_EXECUTE,
    )
    try:
        return issue_response(
            IssueService(engine).transition(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                issue_id=issue_id,
                to_status=body.to_status,
                comment=body.comment,
                closure_evidence_ref=body.closure_evidence_ref,
                expected_updated_at=body.expected_updated_at,
            )
        )
    except Exception as error:
        raise issue_error(error) from error


@router.get("/risks", response_model=RiskListResponse)
def list_risks(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RiskListResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW
    )
    return RiskListResponse(
        items=[
            risk_response(item)
            for item in RiskService(engine).list(tenant_id=context.tenant.id, project_id=project_id)
        ]
    )


@router.post("/risks", response_model=RiskResponse, status_code=status.HTTP_201_CREATED)
def create_risk(
    project_id: UUID,
    body: RiskCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RiskResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        record = RiskService(engine).create(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            draft=RiskDraft(
                owner_user_id=body.owner_user_id,
                title=body.title,
                description=body.description,
                likelihood=body.likelihood,
                impact=body.impact,
                mitigation_plan=body.mitigation_plan,
                contingency_plan=body.contingency_plan,
                target_date=body.target_date,
            ),
        )
    except Exception as error:
        raise risk_error(error) from error
    return risk_response(record)


@router.get("/risks/{risk_id}", response_model=RiskResponse)
def get_risk(
    project_id: UUID,
    risk_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RiskResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW
    )
    try:
        return risk_response(
            RiskService(engine).get(
                tenant_id=context.tenant.id,
                project_id=project_id,
                risk_id=risk_id,
            )
        )
    except Exception as error:
        raise risk_error(error) from error


@router.patch("/risks/{risk_id}", response_model=RiskResponse)
def update_risk(
    project_id: UUID,
    risk_id: UUID,
    body: RiskUpdateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RiskResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        return risk_response(
            RiskService(engine).update(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                risk_id=risk_id,
                patch=RiskUpdate(
                    changes=body.model_dump(exclude_unset=True, exclude={"expected_updated_at"}),
                    expected_updated_at=body.expected_updated_at,
                ),
            )
        )
    except Exception as error:
        raise risk_error(error) from error


@router.post("/risks/{risk_id}/transitions", response_model=RiskResponse)
def transition_risk(
    project_id: UUID,
    risk_id: UUID,
    body: RiskTransitionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RiskResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        return risk_response(
            RiskService(engine).transition(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                risk_id=risk_id,
                to_status=body.to_status,
                expected_updated_at=body.expected_updated_at,
            )
        )
    except Exception as error:
        raise risk_error(error) from error


class RiskCandidateListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[RiskResponse]


class RiskCandidateScanResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    created: int
    reactivated: int
    cleared: int
    items: list[RiskResponse]


@router.get("/risk-candidates", response_model=RiskCandidateListResponse)
def list_risk_candidates(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RiskCandidateListResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW
    )
    return RiskCandidateListResponse(
        items=[
            risk_response(item)
            for item in RiskCandidateService(engine).list_candidates(
                tenant_id=context.tenant.id, project_id=project_id
            )
        ]
    )


@router.post("/risk-candidates/batches")
def confirm_risk_candidate_receipt(
    project_id: UUID,
    body: risk_candidate_batches.BatchRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        return risk_candidate_batches.execute(
            engine,
            context.tenant.id,
            context.user.id,
            project_id,
            body,
        )
    except Exception as error:
        raise risk_error(error) from error


@router.get("/risk-candidates/batches/{request_id}")
def read_risk_candidate_receipt(
    project_id: UUID,
    request_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW
    )
    try:
        return risk_candidate_batches.read(
            engine,
            context.tenant.id,
            context.user.id,
            project_id,
            request_id,
        )
    except Exception as error:
        raise risk_error(error) from error


@router.post("/risk-candidates/scan", response_model=RiskCandidateScanResponse)
def scan_risk_candidates(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RiskCandidateScanResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        result: ScanResult = RiskCandidateService(engine).scan(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
        )
    except Exception as error:
        raise risk_error(error) from error
    return RiskCandidateScanResponse(
        created=result.created,
        reactivated=result.reactivated,
        cleared=result.cleared,
        items=[risk_response(item) for item in result.active_candidates],
    )


@router.post("/risks/{risk_id}/confirm", response_model=RiskResponse)
def confirm_risk_candidate(
    project_id: UUID,
    risk_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RiskResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        return risk_response(
            RiskCandidateService(engine).confirm(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                risk_id=risk_id,
            )
        )
    except Exception as error:
        raise risk_error(error) from error


class RiskCandidateBatchConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_ids: list[UUID] = Field(min_length=1, max_length=200)


class RiskCandidateBatchConfirmResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    confirmed: list[UUID]
    already: list[UUID]
    not_found: list[UUID]


@router.post("/risk-candidates/confirm-batch", response_model=RiskCandidateBatchConfirmResponse)
def confirm_risk_candidates_batch(
    project_id: UUID,
    body: RiskCandidateBatchConfirmRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RiskCandidateBatchConfirmResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    outcome = RiskCandidateService(engine).confirm_batch(
        tenant_id=context.tenant.id,
        actor_user_id=context.user.id,
        project_id=project_id,
        risk_ids=tuple(body.risk_ids),
    )
    return RiskCandidateBatchConfirmResponse(
        confirmed=outcome["confirmed"],
        already=outcome["already"],
        not_found=outcome["not_found"],
    )


def risk_followup_error(error: Exception) -> HTTPException:
    from app.api.work_items import task_error
    from app.domain.knowledge_push import KnowledgeAccessError
    from app.domain.tasks import TaskDateOrderError, TaskNotFoundError, TaskScopeError

    if isinstance(error, risk_followup_results.RiskResultError):
        return HTTPException(
            409, detail={"code": "RISK_FOLLOWUP_RESULT_CONFLICT", "message": str(error)}
        )
    if isinstance(error, KnowledgeAccessError):
        return HTTPException(
            403,
            detail={
                "code": "RISK_FOLLOWUP_FORBIDDEN",
                "message": "当前无权读取或安排本风险及完整引用范围，请由有权限的项目成员处理",
            },
        )
    if isinstance(error, (TaskScopeError, TaskNotFoundError, TaskDateOrderError)):
        return task_error(error)
    return risk_error(error)


@router.get("/risks/{risk_id}/follow-up/{task_id}/results/evidence")
def risk_followup_evidence_options(
    project_id: UUID,
    risk_id: UUID,
    task_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    search: str = "",
    before_created_at: datetime | None = None,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return risk_followup_results.evidence_options(
            engine, context, project_id, risk_id, task_id, search, before_created_at, before_id
        )
    except Exception as error:
        raise risk_followup_error(error) from error


@router.get("/risks/{risk_id}/follow-up/{task_id}/results")
def read_risk_followup_results(
    project_id: UUID,
    risk_id: UUID,
    task_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    request_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        if request_id:
            return risk_followup_results.read_request(
                engine, context, project_id, risk_id, task_id, request_id
            )
        return risk_followup_results.read(engine, context, project_id, risk_id, task_id)
    except Exception as error:
        raise risk_followup_error(error) from error


@router.post("/risks/{risk_id}/follow-up/{task_id}/results")
def save_risk_followup_results(
    project_id: UUID,
    risk_id: UUID,
    task_id: UUID,
    body: risk_followup_results.ResultRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return risk_followup_results.save(engine, context, project_id, risk_id, task_id, body)
    except Exception as error:
        raise risk_followup_error(error) from error


@router.get("/risks/{risk_id}/follow-up")
def risk_followup_preparation(
    project_id: UUID,
    risk_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    request_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        if request_id is not None:
            return risk_followups.read(engine, context, project_id, risk_id, request_id)
        return risk_followups.prepare(engine, context, project_id, risk_id)
    except Exception as error:
        raise risk_followup_error(error) from error


@router.post("/risks/{risk_id}/follow-up")
def create_risk_followup(
    project_id: UUID,
    risk_id: UUID,
    body: risk_followups.FollowupRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return risk_followups.create(engine, context, project_id, risk_id, body)
    except Exception as error:
        raise risk_followup_error(error) from error


@router.get("/risks/{risk_id}/references")
def risk_business_references(
    project_id: UUID,
    risk_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    kind: Literal["task", "initialization", "meeting", "gate", "handoff"] = "task",
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW
    )
    try:
        RiskService(engine).get(tenant_id=context.tenant.id, project_id=project_id, risk_id=risk_id)
        allowed = set()
        for key, (_, action) in risk_references.KINDS.items():
            try:
                require_access(engine=engine, context=context, project_id=project_id, action=action)
                allowed.add(key)
            except HTTPException as error:
                if error.status_code != 403:
                    raise
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            return risk_references.page(
                c, context.tenant.id, project_id, risk_id, allowed, kind, offset
            )
    except HTTPException:
        raise
    except Exception as error:
        raise risk_error(error) from error


class RiskCandidateUndoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: AwareDatetime


@router.post("/risks/{risk_id}/unconfirm", response_model=RiskResponse)
def unconfirm_risk_candidate(
    project_id: UUID,
    risk_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    body: RiskCandidateUndoRequest | None = None,
) -> RiskResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        return risk_response(
            RiskCandidateService(engine).unconfirm(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                risk_id=risk_id,
                expected_updated_at=body.expected_updated_at if body else None,
            )
        )
    except Exception as error:
        raise risk_error(error) from error


@router.post("/risks/{risk_id}/dismiss", response_model=RiskResponse)
def dismiss_risk_candidate(
    project_id: UUID,
    risk_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RiskResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        return risk_response(
            RiskCandidateService(engine).dismiss(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                risk_id=risk_id,
            )
        )
    except Exception as error:
        raise risk_error(error) from error


class IssueTemplateFieldsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, Any] = Field(max_length=30)
    expected_updated_at: AwareDatetime


@router.get("/issues/{issue_id}/template-fields")
def get_issue_template_fields(
    project_id: UUID,
    issue_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW
    )
    try:
        record = IssueService(engine).get(
            tenant_id=context.tenant.id, project_id=project_id, issue_id=issue_id
        )
        with engine.connect() as connection:
            fields, source = project_fields(connection, context.tenant.id, project_id)
        return {
            "issue": issue_response(record).model_dump(mode="json"),
            "fields": [item.model_dump(mode="json") for item in fields],
            "source": source,
        }
    except Exception as error:
        raise issue_error(error) from error


@router.patch("/issues/{issue_id}/template-fields", response_model=IssueResponse)
def save_issue_template_fields(
    project_id: UUID,
    issue_id: UUID,
    body: IssueTemplateFieldsRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> IssueResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        return issue_response(
            IssueService(engine).update(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                issue_id=issue_id,
                patch=IssueUpdate(
                    changes={"template_fields": body.values},
                    expected_updated_at=body.expected_updated_at,
                ),
            )
        )
    except Exception as error:
        raise issue_error(error) from error


@router.get("/issues/{issue_id}/intake-sources")
def get_issue_intake_sources(
    project_id: UUID,
    issue_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.issue_intake_confirm import IssueIntakeConfirmation
    from app.domain.knowledge_push import KnowledgeAccessError

    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW
    )
    try:
        IssueService(engine).get(
            tenant_id=context.tenant.id, project_id=project_id, issue_id=issue_id
        )
        return IssueIntakeConfirmation(engine).issue_sources(context, project_id, issue_id)
    except KnowledgeAccessError as error:
        raise HTTPException(
            403,
            detail={"code": "ISSUE_SOURCE_ACCESS_DENIED", "message": "当前无法读取问题导入来源"},
        ) from error
    except Exception as error:
        raise issue_error(error) from error


@router.get("/{collection}/{item_id}/work-card")
def personal_work_card(
    project_id: UUID,
    collection: Literal["issues", "risks"],
    item_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW
    )
    try:
        if collection == "issues":
            issue = IssueService(engine).get(
                tenant_id=context.tenant.id, project_id=project_id, issue_id=item_id
            )
            item = issue_response(issue).model_dump(mode="json")
        else:
            risk = RiskService(engine).get(
                tenant_id=context.tenant.id, project_id=project_id, risk_id=item_id
            )
            item = risk_response(risk).model_dump(mode="json") | {
                "draft_state": risk.draft_state,
                "source_entity": risk.source_entity,
                "source_entity_id": str(risk.source_entity_id) if risk.source_entity_id else None,
            }
        permissions = {}
        for key, action in (
            ("edit", Action.WORK_ITEM_EDIT),
            ("assign", Action.ISSUE_ASSIGN),
            ("execute", Action.ISSUE_EXECUTE),
            ("verify", Action.ISSUE_VERIFY),
        ):
            try:
                require_access(engine=engine, context=context, project_id=project_id, action=action)
                permissions[key] = True
            except HTTPException as error:
                if error.status_code != 403:
                    raise
                permissions[key] = False
        with engine.connect() as c:
            u, m, p = tables.users, tables.project_members, tables.projects
            people = [
                {"id": str(row.id), "name": row.display_name, "active": row.is_active}
                for row in c.execute(
                    select(u.c.id, u.c.display_name, u.c.is_active)
                    .join(m, (m.c.tenant_id == u.c.tenant_id) & (m.c.user_id == u.c.id))
                    .where(m.c.tenant_id == context.tenant.id, m.c.project_id == project_id)
                    .order_by(u.c.display_name, u.c.id)
                )
            ]
            policy = (
                c.execute(
                    select(p.c.issue_verify_low, p.c.issue_verify_medium).where(
                        p.c.tenant_id == context.tenant.id, p.c.id == project_id
                    )
                )
                .mappings()
                .one()
            )
        return {
            "item": item,
            "permissions": permissions,
            "people": people,
            "actor_id": str(context.user.id),
            "verification_policy": dict(policy),
        }
    except HTTPException:
        raise
    except Exception as error:
        raise (issue_error(error) if collection == "issues" else risk_error(error)) from error


class RiskTemplateFieldsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, Any] = Field(max_length=30)
    expected_updated_at: AwareDatetime


@router.get("/risks/{risk_id}/template-fields")
def get_risk_template_fields(
    project_id: UUID,
    risk_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW
    )
    try:
        record = RiskService(engine).get(
            tenant_id=context.tenant.id, project_id=project_id, risk_id=risk_id
        )
        with engine.connect() as connection:
            fields, source = risk_project_fields(connection, context.tenant.id, project_id)
        return {
            "risk": risk_response(record).model_dump(mode="json"),
            "fields": [item.model_dump(mode="json") for item in fields],
            "source": source,
        }
    except Exception as error:
        raise risk_error(error) from error


@router.patch("/risks/{risk_id}/template-fields", response_model=RiskResponse)
def save_risk_template_fields(
    project_id: UUID,
    risk_id: UUID,
    body: RiskTemplateFieldsRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RiskResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        return risk_response(
            RiskService(engine).update(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                risk_id=risk_id,
                patch=RiskUpdate(
                    changes={"template_fields": body.values},
                    expected_updated_at=body.expected_updated_at,
                ),
            )
        )
    except Exception as error:
        raise risk_error(error) from error
