"""Tenant- and project-bound change governance HTTP boundary."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError

from app.ai.budget_ledger import BudgetLedgerError
from app.ai.change_discussion_queue import HumanInput as DiscussionInput
from app.ai.change_discussion_runs import Request as DiscussionRequest
from app.ai.change_work_package_runs import Request as ChangeWorkPackageRequest
from app.ai.rollout_guard import CapabilityUnavailableError
from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.engine import get_engine
from app.domain import change_quiet_periods as quiet
from app.domain.change_discussion_briefs import Review as DiscussionBriefReview
from app.domain.change_execution_evidence import EvidenceKind as ExecutionEvidenceKind
from app.domain.change_execution_followups import FollowupDraft
from app.domain.change_execution_results import (
    ConfirmDraft as ExecutionConfirmDraft,
)
from app.domain.change_execution_results import (
    ResultDraft as ExecutionResultDraft,
)
from app.domain.change_execution_tasks import BatchDraft as ChangeExecutionDraft
from app.domain.change_governance import (
    ChangeFourEyesError,
    ChangeGovernanceService,
    ChangeHandoffNotReadyError,
    ChangeNotFoundError,
    ChangeScopeError,
    ChangeTransitionError,
)
from app.domain.change_impact_scope import ObjectKind as ImpactObjectKind
from app.domain.change_impact_scope import ScopeDraft
from app.domain.change_quiet_origins import Adoption
from app.domain.change_quiet_replacements import Replacement
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError
from app.domain.professional_change_routes import RouteDraft
from app.domain.professional_change_routes import SourceKind as ProfessionalSourceKind
from app.integrations.erp_handoff import ErpDelivery, ErpHandoffError, ErpHandoffService

router = APIRouter(prefix="/api/projects/{project_id}/changes", tags=["change-governance"])


@router.get("/discussion-runs/{run_id}", dependencies=[Depends(no_store)])
def discussion_detail(
    project_id: UUID,
    run_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.ai.change_discussion_runs import detail

    try:
        return detail(engine, context, project_id, run_id)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise _error(error) from error


@router.get("/ecrs/{ecr_id}/discussion-runs", dependencies=[Depends(no_store)])
def discussion_runs(
    project_id: UUID,
    ecr_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_id: UUID | None = None,
    run_id: UUID | None = None,
) -> dict[str, Any]:
    from app.ai.change_discussion_runs import listing

    try:
        return listing(engine, context, project_id, ecr_id, before_id, run_id)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise _error(error) from error


@router.post("/ecrs/{ecr_id}/discussion-runs")
def discussion_submit(
    project_id: UUID,
    ecr_id: UUID,
    body: DiscussionRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.ai.application_gateway import configured_application_gateway
    from app.ai.change_discussion_runs import ChangeDiscussionRuns

    try:
        with configured_application_gateway(engine) as gateway:
            return ChangeDiscussionRuns(engine, gateway=gateway).submit(
                context, project_id, ecr_id, body
            )
    except (BudgetLedgerError, CapabilityUnavailableError) as error:
        raise HTTPException(
            status_code=409,
            detail={"code": error.code, "message": "本次讨论的能力、预算或授权尚未就绪"},
        ) from error
    except (ProductWorkError, ProductWorkAccessError, IntegrityError) as error:
        raise _error(error) from error


@router.post("/ecrs/{ecr_id}/discussion-runs/{run_id}/control/{action}")
def discussion_control(
    project_id: UUID,
    ecr_id: UUID,
    run_id: UUID,
    action: Literal["cancel", "recover", "cancel_related"],
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.ai.change_discussion_queue import control

    try:
        return control(engine, context, project_id, ecr_id, run_id, action)
    except (ProductWorkError, ProductWorkAccessError, IntegrityError) as error:
        raise _error(error) from error


@router.post("/ecrs/{ecr_id}/discussion-runs/{run_id}/inputs")
def discussion_input(
    project_id: UUID,
    ecr_id: UUID,
    run_id: UUID,
    body: DiscussionInput,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.ai.change_discussion_queue import control

    try:
        return control(engine, context, project_id, ecr_id, run_id, "input", body)
    except (ProductWorkError, ProductWorkAccessError, IntegrityError) as error:
        raise _error(error) from error


@router.post("/ecrs/{ecr_id}/discussion-runs/{run_id}/brief-reviews")
def discussion_brief_review(
    project_id: UUID,
    ecr_id: UUID,
    run_id: UUID,
    body: DiscussionBriefReview,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.change_discussion_briefs import review

    try:
        return review(engine, context, project_id, ecr_id, run_id, body)
    except (ProductWorkError, ProductWorkAccessError, IntegrityError) as error:
        raise _error(error) from error


@router.get("/ecrs/{ecr_id}/decision-summary", dependencies=[Depends(no_store)])
def decision_summary(
    project_id: UUID,
    ecr_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.change_decision_summary import read

    _access(engine, context, project_id, Action.CHANGE_VIEW)
    try:
        return read(engine, context, project_id, ecr_id)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise _error(error) from error


@router.post("/ecrs/{ecr_id}/quiet-period/adopt-policy")
def quiet_adopt(
    project_id: UUID,
    ecr_id: UUID,
    body: Adoption,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.change_quiet_origins import adopt

    _access(engine, context, project_id, Action.CHANGE_APPROVE)
    try:
        return adopt(engine, context, project_id, ecr_id, body)
    except (ProductWorkError, ProductWorkAccessError, IntegrityError) as error:
        raise _error(error) from error


@router.get("/quiet-policy/sources", dependencies=[Depends(no_store)])
def quiet_sources(
    project_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> dict[str, Any]:
    from app.domain.change_quiet_sources import available

    _access(engine, context, project_id, Action.CHANGE_VIEW)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        values, error = available(c, context.tenant.id, project_id)
        return {
            "items": values[offset : offset + 30],
            "source_error": error,
            "next_offset": offset + 30 if offset + 30 < len(values) else None,
        }


@router.post("/ecrs/{ecr_id}/quiet-period/{exception_id}/replace-approvers")
def quiet_replace(
    project_id: UUID,
    ecr_id: UUID,
    exception_id: UUID,
    body: Replacement,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.change_quiet_replacements import replace

    _access(engine, context, project_id, Action.CHANGE_APPROVE)
    try:
        return replace(engine, context, project_id, ecr_id, exception_id, body)
    except (ProductWorkError, ProductWorkAccessError, IntegrityError) as error:
        raise _error(error) from error


@router.get("/quiet-policy", dependencies=[Depends(no_store)])
def quiet_policy_read(
    project_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_version: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_VIEW)
    return quiet.read_policy(engine, context, project_id, before_version)


@router.post("/quiet-policy")
def quiet_policy_save(
    project_id: UUID,
    body: quiet.Policy,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_APPROVE)
    try:
        return quiet.save_policy(engine, context, project_id, body)
    except (ProductWorkError, ProductWorkAccessError, IntegrityError) as error:
        raise _error(error) from error


@router.get("/ecrs/{ecr_id}/quiet-period", dependencies=[Depends(no_store)])
def quiet_read(
    project_id: UUID,
    ecr_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_VIEW)
    try:
        return quiet.read(engine, context, project_id, ecr_id)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise _error(error) from error


@router.post("/ecrs/{ecr_id}/quiet-period")
def quiet_request(
    project_id: UUID,
    ecr_id: UUID,
    body: quiet.ExceptionRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_EDIT)
    try:
        return quiet.request_exception(engine, context, project_id, ecr_id, body)
    except (ProductWorkError, ProductWorkAccessError, IntegrityError) as error:
        raise _error(error) from error


@router.post("/ecrs/{ecr_id}/quiet-period/{exception_id}/decide")
def quiet_decide(
    project_id: UUID,
    ecr_id: UUID,
    exception_id: UUID,
    body: quiet.Vote,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_APPROVE)
    try:
        return quiet.decide(engine, context, project_id, ecr_id, exception_id, body)
    except (ProductWorkError, ProductWorkAccessError, IntegrityError) as error:
        raise _error(error) from error


@router.get("/professional-sources/{kind}/{source_id}", dependencies=[Depends(no_store)])
def professional_source_options(
    project_id: UUID,
    kind: ProfessionalSourceKind,
    source_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.professional_change_routes import options

    _access(engine, context, project_id, Action.CHANGE_VIEW)
    try:
        return options(
            engine, context=context, project_id=project_id, kind=kind, source_id=source_id
        )
    except (ProductWorkError, ValidationError, IntegrityError, ChangeScopeError) as error:
        raise _error(error) from error


@router.post("/professional-sources/{kind}/{source_id}")
def professional_source_route(
    project_id: UUID,
    kind: ProfessionalSourceKind,
    source_id: UUID,
    body: RouteDraft,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.professional_change_routes import route

    _access(engine, context, project_id, Action.CHANGE_EDIT)
    try:
        return route(
            engine,
            context=context,
            project_id=project_id,
            kind=kind,
            source_id=source_id,
            draft=body,
        )
    except (ProductWorkError, ValidationError, IntegrityError, ChangeScopeError) as error:
        raise _error(error) from error


@router.get("/ecrs/{ecr_id}/impact-graph", dependencies=[Depends(no_store)])
def ecr_impact_graph(
    project_id: UUID,
    ecr_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    depth: Annotated[int, Query(ge=1, le=6)] = 3,
) -> dict[str, Any]:
    from app.domain.change_impact_graph import read

    _access(engine, context, project_id, Action.CHANGE_VIEW)
    try:
        return read(engine, context=context, project_id=project_id, ecr_id=ecr_id, depth=depth)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise _error(error) from error


@router.get("/ecrs/{ecr_id}/impact-scope", dependencies=[Depends(no_store)])
def impact_scope_read(
    project_id: UUID,
    ecr_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_revision: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    from app.domain.change_impact_scope import read

    _access(engine, context, project_id, Action.CHANGE_VIEW)
    try:
        return read(
            engine,
            context=context,
            project_id=project_id,
            ecr_id=ecr_id,
            before_revision=before_revision,
        )
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise _error(error) from error


@router.get("/ecrs/{ecr_id}/impact-scope/sources/{kind}", dependencies=[Depends(no_store)])
def impact_scope_sources(
    project_id: UUID,
    ecr_id: UUID,
    kind: ImpactObjectKind,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    after_id: UUID | None = None,
) -> dict[str, Any]:
    from app.domain.change_impact_scope import sources

    _access(engine, context, project_id, Action.CHANGE_VIEW)
    try:
        return sources(
            engine,
            context=context,
            project_id=project_id,
            ecr_id=ecr_id,
            kind=kind,
            after_id=after_id,
        )
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise _error(error) from error


@router.get(
    "/ecrs/{ecr_id}/impact-scope/sources/{kind}/{source_id}", dependencies=[Depends(no_store)]
)
def impact_scope_source(
    project_id: UUID,
    ecr_id: UUID,
    kind: ImpactObjectKind,
    source_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.change_impact_scope import _access as scope_access
    from app.domain.change_impact_scope import _ecr, source
    from app.domain.product_workspace import digest

    scope_access(engine, context, project_id, edit=False)
    try:
        with engine.connect() as connection:
            _ecr(connection, context.tenant.id, project_id, ecr_id)
            value = source(connection, context.tenant.id, project_id, kind, source_id)
            return {"id": str(source_id), "snapshot": value, "digest": digest(value)}
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise _error(error) from error


@router.post("/ecrs/{ecr_id}/impact-scope")
def impact_scope_save(
    project_id: UUID,
    ecr_id: UUID,
    body: ScopeDraft,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.change_impact_scope import save

    _access(engine, context, project_id, Action.CHANGE_EDIT)
    try:
        return save(engine, context=context, project_id=project_id, ecr_id=ecr_id, draft=body)
    except (ProductWorkError, ValidationError, IntegrityError) as error:
        raise _error(error) from error


@router.get("/ecrs/{ecr_id}/analysis-runs", dependencies=[Depends(no_store)])
def change_analysis_runs(
    project_id: UUID,
    ecr_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_id: UUID | None = None,
) -> dict[str, Any]:
    from app.ai.change_work_package_runs import ChangeWorkPackageRuns

    try:
        return ChangeWorkPackageRuns.list_results(
            engine, context=context, project_id=project_id, ecr_id=ecr_id, before_id=before_id
        )
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise _error(error) from error


@router.post("/ecrs/{ecr_id}/analysis-runs")
def change_analysis_create(
    project_id: UUID,
    ecr_id: UUID,
    body: ChangeWorkPackageRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.ai.application_gateway import configured_application_gateway
    from app.ai.change_work_package_runs import KEY, ChangeWorkPackageRuns
    from app.ai.rollout_guard import require_live_key

    _access(engine, context, project_id, Action.CHANGE_EDIT)
    try:
        require_live_key(KEY)
        with configured_application_gateway(engine) as gateway:
            return ChangeWorkPackageRuns(engine, gateway=gateway).create(
                context=context, project_id=project_id, ecr_id=ecr_id, request=body
            )
    except (BudgetLedgerError, CapabilityUnavailableError) as error:
        raise HTTPException(
            status_code=409,
            detail={"code": error.code, "message": "本次分析的能力、预算或授权尚未就绪"},
        ) from error
    except (ProductWorkError, ValidationError, IntegrityError) as error:
        raise _error(error) from error


@router.get("/ecrs/{ecr_id}/analysis-context", dependencies=[Depends(no_store)])
def change_analysis_context(
    project_id: UUID,
    ecr_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    depth: Annotated[int, Query(ge=1, le=5)] = 3,
) -> dict[str, Any]:
    from app.ai.change_impact_preparation import read

    try:
        return read(engine, context=context, project_id=project_id, ecr_id=ecr_id, depth=depth)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise _error(error) from error


@router.get("/ecrs/{ecr_id}/execution-overview", dependencies=[Depends(no_store)])
def change_execution_overview(
    project_id: UUID,
    ecr_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.change_execution_overview import read

    try:
        return read(engine, context=context, project_id=project_id, ecr_id=ecr_id)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise _error(error) from error


@router.get("/ecrs/{ecr_id}/execution-tasks", dependencies=[Depends(no_store)])
def change_execution_read(
    project_id: UUID,
    ecr_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.change_execution_tasks import read

    _access(engine, context, project_id, Action.CHANGE_VIEW)
    try:
        return read(engine, context=context, project_id=project_id, ecr_id=ecr_id)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise _error(error) from error


@router.get("/ecrs/{ecr_id}/execution-tasks/choices", dependencies=[Depends(no_store)])
def change_execution_choices(
    project_id: UUID,
    ecr_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    after_id: UUID | None = None,
) -> dict[str, Any]:
    from app.domain.change_execution_tasks import choices

    _access(engine, context, project_id, Action.CHANGE_VIEW)
    try:
        return choices(
            engine, context=context, project_id=project_id, ecr_id=ecr_id, after_id=after_id
        )
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise _error(error) from error


@router.post("/ecrs/{ecr_id}/execution-tasks")
def change_execution_save(
    project_id: UUID,
    ecr_id: UUID,
    body: ChangeExecutionDraft,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.change_execution_tasks import save

    _access(engine, context, project_id, Action.CHANGE_EDIT)
    try:
        return save(engine, context=context, project_id=project_id, ecr_id=ecr_id, draft=body)
    except (ProductWorkError, ValidationError, IntegrityError) as error:
        raise _error(error) from error


@router.post("/execution-items/{binding_id}/follow-ups")
def execution_followup_save(
    project_id: UUID,
    binding_id: UUID,
    body: FollowupDraft,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.change_execution_followups import save

    try:
        return save(
            engine, context=context, project_id=project_id, binding_id=binding_id, draft=body
        )
    except (ProductWorkError, ValidationError, IntegrityError) as error:
        raise _error(error) from error


@router.get("/execution-items/{binding_id}/results", dependencies=[Depends(no_store)])
def execution_results_read(
    project_id: UUID,
    binding_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_revision: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    from app.domain.change_execution_results import read

    try:
        return read(
            engine,
            context=context,
            project_id=project_id,
            binding_id=binding_id,
            before_revision=before_revision,
        )
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise _error(error) from error


@router.get("/execution-items/{binding_id}/evidence/{kind}", dependencies=[Depends(no_store)])
def execution_evidence_choices(
    project_id: UUID,
    binding_id: UUID,
    kind: ExecutionEvidenceKind,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    after_id: UUID | None = None,
) -> dict[str, Any]:
    from app.domain.change_execution_results import choices

    try:
        return choices(
            engine,
            context=context,
            project_id=project_id,
            binding_id=binding_id,
            kind=kind,
            after_id=after_id,
        )
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise _error(error) from error


@router.post("/execution-items/{binding_id}/results")
def execution_results_save(
    project_id: UUID,
    binding_id: UUID,
    body: ExecutionResultDraft,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.change_execution_results import save

    try:
        return save(
            engine, context=context, project_id=project_id, binding_id=binding_id, draft=body
        )
    except (ProductWorkError, ValidationError, IntegrityError) as error:
        raise _error(error) from error


@router.post("/execution-items/{binding_id}/results/{result_id}/confirm")
def execution_results_confirm(
    project_id: UUID,
    binding_id: UUID,
    result_id: UUID,
    body: ExecutionConfirmDraft,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.change_execution_results import confirm

    try:
        return confirm(
            engine,
            context=context,
            project_id=project_id,
            binding_id=binding_id,
            result_id=result_id,
            draft=body,
        )
    except (ProductWorkError, ValidationError, IntegrityError) as error:
        raise _error(error) from error


class EcrCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    reason: str = Field(min_length=1, max_length=20_000)


class ImpactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    impact_analysis: dict[str, Any]
    affected_bom_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_boms(self) -> ImpactRequest:
        if len(set(self.affected_bom_ids)) != len(self.affected_bom_ids):
            raise ValueError("affected_bom_ids must be unique")
        return self


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=20_000)


class EcnCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    implementation_plan: dict[str, Any] = Field(default_factory=dict)


class EffectivityDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["approved", "rejected"]
    effectivity: dict[str, Any]
    released_bom_id: UUID | None = None
    target_system: str = Field(default="erp", min_length=1, max_length=64)


class HandoffQueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(
        min_length=16,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    mode: Literal["manual", "api"] = "manual"


class HandoffExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: Literal["EXPORT_CONFIRMED"]


class HandoffReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: Literal["RECONCILE_CONFIRMED"]
    outcome: Literal["confirmed_delivered", "confirmed_not_delivered"]
    external_reference: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def reference_matches_outcome(self) -> HandoffReconcileRequest:
        if self.outcome == "confirmed_delivered" and self.external_reference is None:
            raise ValueError("confirmed delivery requires external_reference")
        if self.outcome == "confirmed_not_delivered" and self.external_reference is not None:
            raise ValueError("confirmed non-delivery cannot include external_reference")
        return self


class HandoffReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: Literal["REPLAY_CONFIRMED"]


def _access(engine: Engine, context: AuthContext, project_id: UUID, action: Action) -> None:
    authorize_project(engine=engine, context=context, project_id=project_id, action=action)


def _error(error: Exception) -> HTTPException:
    if isinstance(error, ProductWorkAccessError):
        return HTTPException(
            status_code=403, detail={"code": "DISCUSSION_SOURCE_FORBIDDEN", "message": str(error)}
        )
    if isinstance(error, (ProductWorkError, ValidationError)):
        return HTTPException(
            status_code=409, detail={"code": "CHANGE_ANALYSIS_INCOMPLETE", "message": str(error)}
        )
    if isinstance(error, ChangeNotFoundError):
        return HTTPException(
            status_code=404,
            detail={"code": "CHANGE_NOT_FOUND", "message": "Change record was not found"},
        )
    if isinstance(error, ChangeFourEyesError):
        return HTTPException(
            status_code=409,
            detail={
                "code": "CHANGE_FOUR_EYES_REQUIRED",
                "message": "Requester or analyst cannot approve their own ECR",
            },
        )
    if isinstance(error, ChangeHandoffNotReadyError):
        return HTTPException(
            status_code=409,
            detail={
                "code": "HANDOFF_PVT_GATE_REQUIRED",
                "message": "PVT Gate must be approved before handoff is ready",
            },
        )
    if isinstance(error, ErpHandoffError):
        if error.code in {"ERP_HANDOFF_NOT_FOUND", "ERP_OUTBOX_NOT_FOUND"}:
            status_code = status.HTTP_404_NOT_FOUND
        elif error.code == "ERP_API_NOT_CONFIGURED":
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        else:
            status_code = status.HTTP_409_CONFLICT
        return HTTPException(
            status_code=status_code,
            detail={"code": error.code, "message": "ERP handoff request was rejected"},
        )
    if isinstance(error, (ChangeScopeError, ChangeTransitionError, IntegrityError)):
        return HTTPException(
            status_code=409,
            detail={
                "code": "CHANGE_CONFLICT",
                "message": "Change scope, lifecycle, or identity conflict",
            },
        )
    return HTTPException(
        status_code=500,
        detail={"code": "CHANGE_INTERNAL_ERROR", "message": "Change operation failed"},
    )


@router.get("", dependencies=[Depends(no_store)])
def snapshot(
    project_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, list[dict[str, Any]]]:
    _access(engine, context, project_id, Action.CHANGE_VIEW)
    try:
        return ChangeGovernanceService(engine).snapshot(
            tenant_id=context.tenant.id, project_id=project_id
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/ecrs", status_code=status.HTTP_201_CREATED)
def create_ecr(
    project_id: UUID,
    body: EcrCreateRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_EDIT)
    try:
        return ChangeGovernanceService(engine).create_ecr(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            code=body.code.strip(),
            title=body.title.strip(),
            reason=body.reason.strip(),
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/ecrs/{ecr_id}/start-impact")
def start_impact(
    project_id: UUID,
    ecr_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_EDIT)
    try:
        return ChangeGovernanceService(engine).start_impact(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            ecr_id=ecr_id,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/ecrs/{ecr_id}/submit-impact")
def submit_impact(
    project_id: UUID,
    ecr_id: UUID,
    body: ImpactRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_EDIT)
    try:
        return ChangeGovernanceService(engine).submit_impact(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            ecr_id=ecr_id,
            impact_analysis=body.impact_analysis,
            affected_bom_ids=body.affected_bom_ids,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/ecrs/{ecr_id}/decide")
def decide_ecr(
    project_id: UUID,
    ecr_id: UUID,
    body: DecisionRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_APPROVE)
    try:
        return ChangeGovernanceService(engine).decide_ecr(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            ecr_id=ecr_id,
            outcome=body.outcome,
            note=body.note.strip() if body.note else None,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/ecrs/{ecr_id}/ecns", status_code=status.HTTP_201_CREATED)
def create_ecn(
    project_id: UUID,
    ecr_id: UUID,
    body: EcnCreateRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_EDIT)
    try:
        return ChangeGovernanceService(engine).create_ecn(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            ecr_id=ecr_id,
            code=body.code.strip(),
            title=body.title.strip(),
            implementation_plan=body.implementation_plan,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/ecns/{ecn_id}/submit-effectivity")
def submit_effectivity(
    project_id: UUID,
    ecn_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_EDIT)
    try:
        return ChangeGovernanceService(engine).submit_effectivity(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            ecn_id=ecn_id,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/ecns/{ecn_id}/decide-effectivity")
def decide_effectivity(
    project_id: UUID,
    ecn_id: UUID,
    body: EffectivityDecisionRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_APPROVE)
    try:
        return ChangeGovernanceService(engine).decide_effectivity(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            ecn_id=ecn_id,
            outcome=body.outcome,
            effectivity=body.effectivity,
            released_bom_id=body.released_bom_id,
            target_system=body.target_system.strip(),
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/handoffs/{handoff_id}/ready")
def ready_handoff(
    project_id: UUID,
    handoff_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.HANDOFF_PREPARE)
    try:
        return ChangeGovernanceService(engine).mark_handoff_ready(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            handoff_id=handoff_id,
        )
    except Exception as error:
        raise _error(error) from error


def _delivery_response(delivery: ErpDelivery) -> dict[str, Any]:
    return {
        "handoff": delivery.handoff,
        "outbox": {
            "id": delivery.outbox.id,
            "status": delivery.outbox.status,
            "delivery_mode": delivery.outbox.delivery_mode,
            "attempt_count": delivery.outbox.attempt_count,
            "payload_digest": delivery.outbox.payload_digest,
            "remote_reference": delivery.outbox.remote_reference,
            "last_error_code": delivery.outbox.last_error_code,
        },
        "delivery_package": delivery.delivery_package,
    }


@router.post("/handoffs/{handoff_id}/queue")
def queue_handoff(
    project_id: UUID,
    handoff_id: UUID,
    body: HandoffQueueRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.HANDOFF_EXECUTE)
    try:
        return _delivery_response(
            ErpHandoffService(engine).queue(
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                handoff_id=handoff_id,
                idempotency_key=body.idempotency_key,
                mode=body.mode,
            )
        )
    except Exception as error:
        raise _error(error) from error


@router.get("/handoffs/{handoff_id}/delivery", dependencies=[Depends(no_store)])
def get_handoff_delivery(
    project_id: UUID,
    handoff_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.HANDOFF_VIEW)
    try:
        return _delivery_response(
            ErpHandoffService(engine).get(
                tenant_id=context.tenant.id,
                project_id=project_id,
                handoff_id=handoff_id,
            )
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/handoffs/{handoff_id}/export")
def export_handoff(
    project_id: UUID,
    handoff_id: UUID,
    body: HandoffExportRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.HANDOFF_EXECUTE)
    try:
        return _delivery_response(
            ErpHandoffService(engine).export_manual(
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                handoff_id=handoff_id,
            )
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/handoffs/{handoff_id}/reconcile")
def reconcile_handoff(
    project_id: UUID,
    handoff_id: UUID,
    body: HandoffReconcileRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.HANDOFF_RECONCILE)
    try:
        return _delivery_response(
            ErpHandoffService(engine).reconcile(
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                handoff_id=handoff_id,
                outcome=body.outcome,
                external_reference=body.external_reference,
            )
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/handoffs/{handoff_id}/replay")
def replay_handoff(
    project_id: UUID,
    handoff_id: UUID,
    body: HandoffReplayRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.HANDOFF_EXECUTE)
    try:
        return _delivery_response(
            ErpHandoffService(engine).replay(
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                handoff_id=handoff_id,
            )
        )
    except Exception as error:
        raise _error(error) from error


class RefreshImpactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=2048)


@router.post("/ecrs/{ecr_id}/refresh-impact")
def refresh_impact(
    project_id: UUID,
    ecr_id: UUID,
    body: RefreshImpactRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_EDIT)
    try:
        return ChangeGovernanceService(engine).refresh_impact(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            ecr_id=ecr_id,
            expected_digest=body.expected_digest,
            reason=body.reason,
        )
    except Exception as error:
        raise _error(error) from error
