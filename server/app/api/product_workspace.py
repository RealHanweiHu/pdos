"""Authenticated, typed market-space work; no synthetic Project identifiers."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.object_operations import ResearchConcludeRequest, ResearchStartRequest
from app.db.engine import get_engine
from app.domain import preproject_responsibilities
from app.domain.product_catalog import (
    LineMemberChange,
    ProductCatalogService,
    ProductChange,
    ProductDraft,
    SpaceChange,
    SpaceLifecycle,
)
from app.domain.product_workspace import (
    AssignWork,
    CancelResearch,
    MarketSpaceDraft,
    ProductWorkAccessError,
    ProductWorkError,
    ProductWorkspaceService,
    ResearchDraft,
    WorkAction,
    WorkDraft,
)

router = APIRouter(prefix="/api/product-work", tags=["product-work"])
Context = Annotated[AuthContext, Depends(current_context)]
Database = Annotated[Engine, Depends(get_engine)]


def _error(error: Exception) -> HTTPException:
    if isinstance(error, ProductWorkAccessError):
        return HTTPException(403, detail={"code": "PRODUCT_WORK_FORBIDDEN", "message": str(error)})
    if isinstance(error, ProductWorkError):
        return HTTPException(409, detail={"code": "PRODUCT_WORK_INVALID", "message": str(error)})
    raise error


@router.get("/spaces")
def list_spaces(response: Response, context: Context, engine: Database) -> dict[str, Any]:
    no_store(response)
    try:
        return {
            "items": ProductWorkspaceService(engine).list_spaces(context),
            "can_create": is_allowed(context.user.role, Action.PRODUCT_WORK_MANAGE),
        }
    except Exception as error:
        raise _error(error) from error


@router.post("/spaces", status_code=201)
def create_space(
    body: MarketSpaceDraft, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductWorkspaceService(engine).create_space(context, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/my-work")
def my_work(
    response: Response,
    context: Context,
    engine: Database,
    collection: Literal["research", "work_items", "experiments", "strategies", "definitions"]
    | None = None,
    offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductWorkspaceService(engine).my_work(
            context, collection=collection, offset=offset, limit=limit
        )
    except Exception as error:
        raise _error(error) from error


@router.get("/spaces/{space_id}")
def get_space(
    space_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductWorkspaceService(engine).detail(context, space_id)
    except Exception as error:
        raise _error(error) from error


class MemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access: Literal["viewer", "contributor", "manager"] | None


@router.put("/spaces/{space_id}/members/{user_id}", status_code=204)
def set_member(
    space_id: UUID,
    user_id: UUID,
    body: MemberRequest,
    response: Response,
    context: Context,
    engine: Database,
) -> None:
    no_store(response)
    try:
        ProductWorkspaceService(engine).set_member(context, space_id, user_id, body.access)
    except Exception as error:
        raise _error(error) from error


@router.get("/spaces/{space_id}/work-items/{item_id}/history")
def work_history(
    space_id: UUID,
    item_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before_id: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductWorkspaceService(engine).work_history(
            context, space_id, item_id, before_id=before_id
        )
    except Exception as error:
        raise _error(error) from error


@router.get("/spaces/{space_id}/evidence")
def evidence_options(
    space_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return {"items": ProductWorkspaceService(engine).evidence_options(context, space_id)}
    except Exception as error:
        raise _error(error) from error


@router.post("/spaces/{space_id}/research", status_code=201)
def create_research(
    space_id: UUID, body: ResearchDraft, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductWorkspaceService(engine).create_research(context, space_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/spaces/{space_id}/research/{task_id}/start")
def start_research(
    space_id: UUID,
    task_id: UUID,
    body: ResearchStartRequest,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductWorkspaceService(engine).research_action(context, space_id, task_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/spaces/{space_id}/research/{task_id}/conclude")
def conclude_research(
    space_id: UUID,
    task_id: UUID,
    body: ResearchConcludeRequest,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductWorkspaceService(engine).research_action(context, space_id, task_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/spaces/{space_id}/research/{task_id}/cancel")
def cancel_research(
    space_id: UUID,
    task_id: UUID,
    body: CancelResearch,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductWorkspaceService(engine).research_action(context, space_id, task_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/spaces/{space_id}/work-items", status_code=201)
def create_work(
    space_id: UUID, body: WorkDraft, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductWorkspaceService(engine).create_work(context, space_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/spaces/{space_id}/work-items/{item_id}/actions")
def act_on_work(
    space_id: UUID,
    item_id: UUID,
    body: WorkAction,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductWorkspaceService(engine).work_action(context, space_id, item_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/spaces/{space_id}/work-items/{item_id}/assignment")
def assign_work(
    space_id: UUID,
    item_id: UUID,
    body: AssignWork,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductWorkspaceService(engine).work_action(context, space_id, item_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/spaces/{space_id}/products")
def product_catalog(
    space_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductCatalogService(engine).catalog(context, space_id)
    except Exception as error:
        raise _error(error) from error


@router.post("/spaces/{space_id}/products", status_code=201)
def create_product(
    space_id: UUID, body: ProductDraft, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductCatalogService(engine).create(context, space_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/spaces/{space_id}/products/{node_id}/changes")
def change_product(
    space_id: UUID,
    node_id: UUID,
    body: ProductChange,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductCatalogService(engine).change(context, space_id, node_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/spaces/{space_id}/products/{line_id}/members")
def product_member(
    space_id: UUID,
    line_id: UUID,
    body: LineMemberChange,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductCatalogService(engine).set_member(context, space_id, line_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/spaces/{space_id}/changes")
def change_space(
    space_id: UUID, body: SpaceChange, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductCatalogService(engine).change_space(context, space_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/spaces/{space_id}/lifecycle")
def space_lifecycle(
    space_id: UUID, body: SpaceLifecycle, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductCatalogService(engine).change_space(context, space_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/spaces/{space_id}/responsibilities/{kind}/{record_id}")
def preproject_responsibility_get(
    space_id: UUID,
    kind: preproject_responsibilities.Kind,
    record_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before_id: int | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return preproject_responsibilities.read(
            engine, context, space_id, kind, record_id, before_id
        )
    except (ProductWorkError, ProductWorkAccessError) as exc:
        raise _error(exc) from exc


@router.post("/spaces/{space_id}/responsibilities/{kind}/{record_id}")
def preproject_responsibility_change(
    space_id: UUID,
    kind: preproject_responsibilities.Kind,
    record_id: UUID,
    body: preproject_responsibilities.Reassign,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return preproject_responsibilities.reassign(
            engine, context, space_id, kind, record_id, body
        )
    except (ProductWorkError, ProductWorkAccessError) as exc:
        raise _error(exc) from exc
