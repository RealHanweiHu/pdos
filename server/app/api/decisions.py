"""Project-scoped Decision HTTP boundaries (vNext V1-B4)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Self
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Engine, select

from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.engine import get_engine
from app.db.schema import tables
from app.domain import decision_responsibilities
from app.domain.decision_intake_confirm import DecisionIntakeConfirmation
from app.domain.decisions import (
    MANUAL_DECISION_KINDS,
    DecisionContentError,
    DecisionDraft,
    DecisionFollowUpError,
    DecisionNotFoundError,
    DecisionRecord,
    DecisionScopeError,
    DecisionService,
)
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError

router = APIRouter(prefix="/api/projects/{project_id}", tags=["decisions"])

_MANUAL_KIND_PATTERN = "^(" + "|".join(sorted(MANUAL_DECISION_KINDS)) + ")$"


class DecisionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    gate_id: UUID | None
    issue_id: UUID | None
    decided_by_user_id: UUID | None
    owner_user_id: UUID | None
    approver_user_id: UUID | None
    decision_kind: str
    title: str
    context: str | None
    options: list[str]
    trade_offs: str | None
    outcome: str
    rationale: str | None
    consequence: str | None
    evidence_refs: list[str]
    follow_up_state: str
    follow_up_note: str | None
    follow_up_task_id: UUID | None
    follow_up_audit_id: int | None
    execution_evidence: dict[str, object] | None
    decided_at: datetime
    created_at: datetime
    updated_at: datetime
    historical_source: dict[str, object] | None = None
    historical_origin_state: dict[str, object] | None = None
    source_finding_id: UUID | None = None


class DecisionListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[DecisionResponse]


class DecisionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_kind: str = Field(pattern=_MANUAL_KIND_PATTERN)
    title: str = Field(min_length=1, max_length=512)
    outcome: str = Field(min_length=1, max_length=20_000)
    context: str | None = Field(default=None, max_length=20_000)
    options: list[str] = Field(default_factory=list, max_length=20)
    trade_offs: str | None = Field(default=None, max_length=20_000)
    rationale: str | None = Field(default=None, max_length=20_000)
    consequence: str | None = Field(default=None, max_length=20_000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)
    issue_id: UUID | None = None
    gate_id: UUID | None = None
    owner_user_id: UUID | None = None
    approver_user_id: UUID | None = None
    follow_up_task_id: UUID | None = None
    follow_up_pending: bool = False
    follow_up_note: str | None = Field(default=None, max_length=2_000)

    @field_validator("title", "outcome", mode="before")
    @classmethod
    def normalize_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "context", "trade_offs", "rationale", "consequence", "follow_up_note", mode="before"
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("options", "evidence_refs")
    @classmethod
    def require_nonblank_entries(cls, value: list[str]) -> list[str]:
        normalized = [entry.strip() for entry in value]
        if any(not entry for entry in normalized):
            raise ValueError("entries cannot be blank")
        return normalized

    @model_validator(mode="after")
    def follow_up_requires_note(self) -> Self:
        if self.follow_up_pending and self.follow_up_note is None:
            raise ValueError("follow_up_note is required when follow_up_pending is true")
        return self


class DecisionFollowUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_audit_id: int = Field(gt=0)
    note: str = Field(min_length=1, max_length=2_000)

    @field_validator("note", mode="before")
    @classmethod
    def normalize_note(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


def decision_response(record: DecisionRecord) -> DecisionResponse:
    return DecisionResponse(
        id=record.id,
        project_id=record.project_id,
        gate_id=record.gate_id,
        issue_id=record.issue_id,
        decided_by_user_id=record.decided_by_user_id,
        owner_user_id=record.owner_user_id,
        approver_user_id=record.approver_user_id,
        decision_kind=record.decision_kind,
        title=record.title,
        context=record.context,
        options=list(record.options),
        trade_offs=record.trade_offs,
        outcome=record.outcome,
        rationale=record.rationale,
        consequence=record.consequence,
        evidence_refs=list(record.evidence_refs),
        follow_up_state=record.follow_up_state,
        follow_up_note=record.follow_up_note,
        follow_up_task_id=record.follow_up_task_id,
        follow_up_audit_id=record.follow_up_audit_id,
        execution_evidence=record.execution_evidence,
        decided_at=record.decided_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
        source_finding_id=record.source_finding_id,
        historical_source=record.historical_source,
        historical_origin_state=record.historical_origin_state,
    )


def decision_error(error: Exception) -> HTTPException:
    if isinstance(error, DecisionNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DECISION_NOT_FOUND", "message": "Decision was not found"},
        )
    if isinstance(error, DecisionScopeError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "DECISION_RELATED_OBJECT_NOT_FOUND",
                "message": "Related object was not found in this project",
            },
        )
    if isinstance(error, DecisionContentError):
        return HTTPException(
            422, detail={"code": "DECISION_CONTENT_REQUIRED", "message": str(error)}
        )
    if isinstance(error, DecisionFollowUpError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DECISION_FOLLOW_UP_INVALID",
                "message": str(error) or "只有待跟进决策可凭当前有效的目标执行记录完成",
            },
        )
    raise error


@router.get("/decisions", response_model=DecisionListResponse)
def list_decisions(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> DecisionListResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW
    )
    return DecisionListResponse(
        items=[
            decision_response(record)
            for record in DecisionService(engine).list(
                tenant_id=context.tenant.id, project_id=project_id
            )
        ]
    )


@router.post("/decisions", response_model=DecisionResponse, status_code=status.HTTP_201_CREATED)
def create_decision(
    project_id: UUID,
    body: DecisionCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> DecisionResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        record = DecisionService(engine).create(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            draft=DecisionDraft(
                decision_kind=body.decision_kind,
                title=body.title,
                outcome=body.outcome,
                context=body.context,
                options=tuple(body.options),
                trade_offs=body.trade_offs,
                rationale=body.rationale,
                consequence=body.consequence,
                evidence_refs=tuple(body.evidence_refs),
                issue_id=body.issue_id,
                gate_id=body.gate_id,
                owner_user_id=body.owner_user_id,
                approver_user_id=body.approver_user_id,
                follow_up_task_id=body.follow_up_task_id,
                follow_up_pending=body.follow_up_pending,
                follow_up_note=body.follow_up_note,
            ),
        )
    except Exception as error:
        raise decision_error(error) from error
    return decision_response(record)


@router.post("/decisions/{decision_id}/follow-up", response_model=DecisionResponse)
def complete_follow_up(
    project_id: UUID,
    decision_id: UUID,
    body: DecisionFollowUpRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> DecisionResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        record = DecisionService(engine).complete_follow_up(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            decision_id=decision_id,
            note=body.note,
            execution_audit_id=body.execution_audit_id,
        )
    except Exception as error:
        raise decision_error(error) from error
    return decision_response(record)


@router.get("/decisions/{decision_id}/execution-evidence")
def list_execution_evidence(
    project_id: UUID,
    decision_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW
    )
    try:
        return {
            "items": DecisionService(engine).execution_choices(
                tenant_id=context.tenant.id, project_id=project_id, decision_id=decision_id
            )
        }
    except Exception as error:
        raise decision_error(error) from error


@router.get("/decisions/options")
def decision_form_options(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW
    )
    with engine.connect() as connection:
        members = connection.execute(
            select(tables.users.c.id, tables.users.c.display_name)
            .join(
                tables.project_members,
                (tables.project_members.c.tenant_id == tables.users.c.tenant_id)
                & (tables.project_members.c.user_id == tables.users.c.id),
            )
            .where(
                tables.users.c.tenant_id == context.tenant.id,
                tables.users.c.is_active.is_(True),
                tables.users.c.role.in_(
                    ("owner", "admin", "project_manager", "engineer", "quality")
                ),
                tables.project_members.c.project_id == project_id,
            )
        ).mappings()
        tasks = connection.execute(
            select(tables.tasks.c.id, tables.tasks.c.title).where(
                tables.tasks.c.tenant_id == context.tenant.id,
                tables.tasks.c.project_id == project_id,
                tables.tasks.c.status.not_in(("done", "skipped")),
            )
        ).mappings()
        gates = connection.execute(
            select(tables.gates.c.id, tables.gates.c.name).where(
                tables.gates.c.tenant_id == context.tenant.id,
                tables.gates.c.project_id == project_id,
            )
        ).mappings()
        return {
            "members": [dict(row) for row in members],
            "tasks": [dict(row) for row in tasks],
            "gates": [dict(row) for row in gates],
        }


class DecisionExecutionTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: UUID


@router.post("/decisions/{decision_id}/execution-target", response_model=DecisionResponse)
def bind_execution_task(
    project_id: UUID,
    decision_id: UUID,
    body: DecisionExecutionTarget,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> DecisionResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        return decision_response(
            DecisionService(engine).bind_execution_task(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                decision_id=decision_id,
                task_id=body.task_id,
            )
        )
    except Exception as error:
        raise decision_error(error) from error


@router.get("/decisions/{decision_id}/intake-sources")
def get_historical_decision_sources(
    project_id: UUID,
    decision_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_created_at: AwareDatetime | None = None,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    from app.api.conversations import error_response

    no_store(response)
    try:
        return DecisionIntakeConfirmation(engine).sources(
            context,
            project_id,
            decision_id,
            before_created_at=before_created_at,
            before_id=before_id,
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/issues/{issue_id}/decision-intake-sources")
def get_issue_historical_decision_sources(
    project_id: UUID,
    issue_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_created_at: AwareDatetime | None = None,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    from app.api.conversations import error_response

    no_store(response)
    try:
        return DecisionIntakeConfirmation(engine).sources(
            context,
            project_id,
            issue_id=issue_id,
            before_created_at=before_created_at,
            before_id=before_id,
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/decisions/{decision_id}/responsibility")
def decision_owner_get(
    project_id: UUID,
    decision_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_id: int | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return decision_responsibilities.read(engine, context, project_id, decision_id, before_id)
    except (ProductWorkError, ProductWorkAccessError) as exc:
        raise HTTPException(
            403 if isinstance(exc, ProductWorkAccessError) else 409,
            detail={"code": "DECISION_RESPONSIBILITY_INVALID", "message": str(exc)},
        ) from exc


@router.post("/decisions/{decision_id}/responsibility")
def decision_owner_change(
    project_id: UUID,
    decision_id: UUID,
    body: decision_responsibilities.Reassign,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return decision_responsibilities.reassign(engine, context, project_id, decision_id, body)
    except (ProductWorkError, ProductWorkAccessError) as exc:
        raise HTTPException(
            403 if isinstance(exc, ProductWorkAccessError) else 409,
            detail={"code": "DECISION_RESPONSIBILITY_INVALID", "message": str(exc)},
        ) from exc
