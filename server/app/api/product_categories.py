"""Category knowledge and human-controlled shared dictionary/platform maintenance."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Response

from app.api.auth import no_store
from app.api.product_workspace import Context, Database, _error
from app.domain.product_categories import (
    KnowledgeSave,
    ParameterSave,
    PlatformCreate,
    PlatformLink,
    ProductCategoryService,
)
from app.domain.product_workspace import _space, category_line_id

router = APIRouter(prefix="/api/product-work/spaces/{space_id}", tags=["product-categories"])
category_router = APIRouter(
    prefix="/api/product-work/categories/{space_id}", tags=["product-categories"]
)


def _identity(engine: Any, context: Any, space_id: UUID) -> UUID:
    with engine.connect() as c:
        _space(c, context, space_id)
        return category_line_id(c, context.tenant.id, space_id)


@category_router.get("/shared")
def category_shared(
    space_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductCategoryService(engine).read(
            context, space_id, _identity(engine, context, space_id)
        )
    except Exception as error:
        raise _error(error) from error


@category_router.post("/shared/parameters", status_code=201)
def category_parameter(
    space_id: UUID, body: ParameterSave, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductCategoryService(engine).parameter(
            context, space_id, _identity(engine, context, space_id), body
        )
    except Exception as error:
        raise _error(error) from error


@category_router.post("/shared/knowledge", status_code=201)
def category_knowledge(
    space_id: UUID, body: KnowledgeSave, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductCategoryService(engine).knowledge(
            context, space_id, _identity(engine, context, space_id), body
        )
    except Exception as error:
        raise _error(error) from error


@router.get("/categories/{line_id}")
def read_category(
    space_id: UUID, line_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductCategoryService(engine).read(context, space_id, line_id)
    except Exception as error:
        raise _error(error) from error


@router.post("/categories/{line_id}/parameters", status_code=201)
def save_parameter(
    space_id: UUID,
    line_id: UUID,
    body: ParameterSave,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductCategoryService(engine).parameter(context, space_id, line_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/categories/{line_id}/knowledge", status_code=201)
def save_knowledge(
    space_id: UUID,
    line_id: UUID,
    body: KnowledgeSave,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductCategoryService(engine).knowledge(context, space_id, line_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/platforms")
def list_platforms(
    space_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductCategoryService(engine).platforms(context, space_id)
    except Exception as error:
        raise _error(error) from error


@router.post("/platforms", status_code=201)
def create_platform(
    space_id: UUID, body: PlatformCreate, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductCategoryService(engine).platform(context, space_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/platform-links", status_code=201)
def link_platform(
    space_id: UUID, body: PlatformLink, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductCategoryService(engine).link(context, space_id, body)
    except Exception as error:
        raise _error(error) from error
