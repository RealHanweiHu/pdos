"""Human pre-project plan preparation; does not create tasks or approve execution."""

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Response

from app.api.auth import no_store
from app.api.development_cases import case_link_error
from app.api.product_workspace import Context, Database
from app.domain.initial_plan_candidates import (
    InitialPlanCandidateService,
    PlanPreparation,
    PlanSource,
)
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError
from app.domain.project_templates import ProjectTemplateError

router = APIRouter(tags=["initial-plan-candidates"])


@router.get("/api/product-work/spaces/{space_id}/initial-plans")
def space_plans(
    space_id: UUID,
    source_kind: Literal["opportunity", "product_definition"],
    source_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    options: bool = False,
) -> dict[str, Any]:
    no_store(response)
    try:
        service = InitialPlanCandidateService(engine)
        return (service.options if options else service.list)(
            context, space_id, PlanSource(kind=source_kind, id=source_id)
        )
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise case_link_error(error) from error


@router.post("/api/product-work/spaces/{space_id}/initial-plans")
def prepare_space_plan(
    space_id: UUID, payload: PlanPreparation, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return InitialPlanCandidateService(engine).create(context, space_id, payload)
    except (ProductWorkError, ProductWorkAccessError, ProjectTemplateError) as error:
        raise case_link_error(error) from error


@router.get("/api/development-cases/{case_id}/initial-plans")
def case_plans(
    case_id: UUID, response: Response, context: Context, engine: Database, options: bool = False
) -> dict[str, Any]:
    no_store(response)
    try:
        service = InitialPlanCandidateService(engine)
        return (service.options if options else service.list)(
            context, None, PlanSource(kind="development_case", id=case_id)
        )
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise case_link_error(error) from error


@router.post("/api/development-cases/{case_id}/initial-plans")
def prepare_case_plan(
    case_id: UUID, payload: PlanPreparation, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        if payload.source != PlanSource(kind="development_case", id=case_id):
            raise ProductWorkAccessError("请求来源与案例入口不一致")
        return InitialPlanCandidateService(engine).create(context, None, payload)
    except (ProductWorkError, ProductWorkAccessError, ProjectTemplateError) as error:
        raise case_link_error(error) from error


@router.get("/api/initial-plans/{candidate_id}")
def plan_detail(
    candidate_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return InitialPlanCandidateService(engine).detail(context, candidate_id)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise case_link_error(error) from error
