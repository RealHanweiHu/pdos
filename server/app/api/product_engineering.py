"""Project-scoped Specification and Development BOM HTTP boundary."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError

from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.engine import get_engine
from app.domain.product_engineering import (
    BomItemCostDraft,
    BomItemCostRecord,
    DevelopmentBomDraft,
    DevelopmentBomItemDraft,
    DevelopmentBomItemRecord,
    DevelopmentBomRecord,
    ErpBomReferenceDraft,
    ErpBomReferenceRecord,
    ProductEngineeringCostBoundaryError,
    ProductEngineeringNotFoundError,
    ProductEngineeringScopeError,
    ProductEngineeringService,
    SpecificationDraft,
    SpecificationRecord,
)

router = APIRouter(
    prefix="/api/projects/{project_id}/product-engineering",
    tags=["product-engineering"],
)


class SpecificationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    version: int = Field(default=1, ge=1)
    content: dict[str, object] = Field(default_factory=dict)

    @field_validator("code", "title", mode="before")
    @classmethod
    def normalize_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class SpecificationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    created_by_user_id: UUID
    code: str
    title: str
    version: int
    content: dict[str, object]
    created_at: datetime
    updated_at: datetime


class SpecificationListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[SpecificationResponse]


class BomItemCostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str = Field(pattern=r"^[A-Z]{3}$")
    unit_cost: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    cost_category: str | None = Field(default=None, max_length=64)

    @field_validator("cost_category", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class BomItemCostResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    currency: str
    unit_cost: Decimal
    cost_category: str | None


class DevelopmentBomItemCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_item_id: UUID | None = None
    line_number: int = Field(ge=1)
    part_number: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=512)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    unit: str = Field(min_length=1, max_length=32)
    material_reference: str | None = Field(default=None, max_length=256)
    attributes: dict[str, object] = Field(default_factory=dict)
    cost: BomItemCostRequest | None = None

    @field_validator("part_number", "description", "unit", mode="before")
    @classmethod
    def normalize_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("material_reference", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class DevelopmentBomItemResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    bom_id: UUID
    parent_item_id: UUID | None
    line_number: int
    part_number: str
    description: str
    quantity: Decimal
    unit: str
    material_reference: str | None
    attributes: dict[str, object]
    cost: BomItemCostResponse | None
    created_at: datetime
    updated_at: datetime


class DevelopmentBomCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    specification_id: UUID | None = None
    bom_type: str = Field(pattern=r"^(ebom|prototype|cost)$")
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)
    version: int = Field(default=1, ge=1)
    notes: str | None = Field(default=None, max_length=20_000)

    @field_validator("code", "name", mode="before")
    @classmethod
    def normalize_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class DevelopmentBomResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    specification_id: UUID | None
    created_by_user_id: UUID
    bom_type: str
    code: str
    name: str
    version: int
    notes: str | None
    items: list[DevelopmentBomItemResponse]
    created_at: datetime
    updated_at: datetime


class DevelopmentBomListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[DevelopmentBomResponse]


class ErpBomReferenceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bom_id: UUID | None = None
    reference_type: str = Field(pattern=r"^(mbom|routing|production_version)$")
    source_system: str = Field(min_length=1, max_length=64)
    external_id: str = Field(min_length=1, max_length=256)
    external_url: str | None = Field(default=None, max_length=2048)
    metadata: dict[str, object] = Field(default_factory=dict)

    @field_validator("source_system", "external_id", mode="before")
    @classmethod
    def normalize_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("external_url", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class ErpBomReferenceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    bom_id: UUID | None
    reference_type: str
    source_system: str
    external_id: str
    external_url: str | None
    metadata: dict[str, object]
    created_at: datetime


class ErpBomReferenceListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[ErpBomReferenceResponse]


def specification_response(record: SpecificationRecord) -> SpecificationResponse:
    return SpecificationResponse.model_validate(record, from_attributes=True)


def cost_response(record: BomItemCostRecord | None) -> BomItemCostResponse | None:
    return (
        BomItemCostResponse.model_validate(record, from_attributes=True)
        if record is not None
        else None
    )


def item_response(record: DevelopmentBomItemRecord) -> DevelopmentBomItemResponse:
    return DevelopmentBomItemResponse(
        id=record.id,
        bom_id=record.bom_id,
        parent_item_id=record.parent_item_id,
        line_number=record.line_number,
        part_number=record.part_number,
        description=record.description,
        quantity=record.quantity,
        unit=record.unit,
        material_reference=record.material_reference,
        attributes=record.attributes,
        cost=cost_response(record.cost),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def bom_response(record: DevelopmentBomRecord) -> DevelopmentBomResponse:
    return DevelopmentBomResponse(
        id=record.id,
        project_id=record.project_id,
        specification_id=record.specification_id,
        created_by_user_id=record.created_by_user_id,
        bom_type=record.bom_type,
        code=record.code,
        name=record.name,
        version=record.version,
        notes=record.notes,
        items=[item_response(item) for item in record.items],
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def erp_reference_response(record: ErpBomReferenceRecord) -> ErpBomReferenceResponse:
    return ErpBomReferenceResponse.model_validate(record, from_attributes=True)


def require_access(
    *, engine: Engine, context: AuthContext, project_id: UUID, action: Action
) -> None:
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=action,
    )


def product_error(error: Exception) -> HTTPException:
    if isinstance(error, (ProductEngineeringNotFoundError, ProductEngineeringScopeError)):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "PRODUCT_ENGINEERING_OBJECT_NOT_FOUND",
                "message": "Product engineering object was not found",
            },
        )
    if isinstance(error, ProductEngineeringCostBoundaryError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "COST_BOM_BOUNDARY_VIOLATION",
                "message": "Cost data is required only for Cost BOM items",
            },
        )
    if isinstance(error, IntegrityError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PRODUCT_ENGINEERING_CONFLICT",
                "message": "Product engineering record conflicts with existing data",
            },
        )
    raise error


@router.get("/specifications", response_model=SpecificationListResponse)
def list_specifications(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> SpecificationListResponse:
    no_store(response)
    require_access(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.PRODUCT_ENGINEERING_VIEW,
    )
    return SpecificationListResponse(
        items=[
            specification_response(record)
            for record in ProductEngineeringService(engine).list_specifications(
                tenant_id=context.tenant.id,
                project_id=project_id,
            )
        ]
    )


@router.post(
    "/specifications",
    response_model=SpecificationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_specification(
    project_id: UUID,
    body: SpecificationCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> SpecificationResponse:
    no_store(response)
    require_access(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.PRODUCT_ENGINEERING_EDIT,
    )
    try:
        record = ProductEngineeringService(engine).create_specification(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            draft=SpecificationDraft(
                code=body.code,
                title=body.title,
                version=body.version,
                content=body.content,
            ),
        )
    except (ProductEngineeringNotFoundError, IntegrityError) as error:
        raise product_error(error) from error
    return specification_response(record)


@router.get("/boms", response_model=DevelopmentBomListResponse)
def list_boms(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> DevelopmentBomListResponse:
    no_store(response)
    require_access(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.PRODUCT_ENGINEERING_VIEW,
    )
    return DevelopmentBomListResponse(
        items=[
            bom_response(record)
            for record in ProductEngineeringService(engine).list_boms(
                tenant_id=context.tenant.id,
                project_id=project_id,
            )
        ]
    )


@router.post("/boms", response_model=DevelopmentBomResponse, status_code=status.HTTP_201_CREATED)
def create_bom(
    project_id: UUID,
    body: DevelopmentBomCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> DevelopmentBomResponse:
    no_store(response)
    require_access(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.PRODUCT_ENGINEERING_EDIT,
    )
    try:
        record = ProductEngineeringService(engine).create_bom(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            draft=DevelopmentBomDraft(
                specification_id=body.specification_id,
                bom_type=body.bom_type,
                code=body.code,
                name=body.name,
                version=body.version,
                notes=body.notes,
            ),
        )
    except (
        ProductEngineeringNotFoundError,
        ProductEngineeringScopeError,
        IntegrityError,
    ) as error:
        raise product_error(error) from error
    return bom_response(record)


@router.post(
    "/boms/{bom_id}/items",
    response_model=DevelopmentBomItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_bom_item(
    project_id: UUID,
    bom_id: UUID,
    body: DevelopmentBomItemCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> DevelopmentBomItemResponse:
    no_store(response)
    require_access(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.PRODUCT_ENGINEERING_EDIT,
    )
    try:
        record = ProductEngineeringService(engine).add_bom_item(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            bom_id=bom_id,
            draft=DevelopmentBomItemDraft(
                parent_item_id=body.parent_item_id,
                line_number=body.line_number,
                part_number=body.part_number,
                description=body.description,
                quantity=body.quantity,
                unit=body.unit,
                material_reference=body.material_reference,
                attributes=body.attributes,
                cost=(
                    BomItemCostDraft(
                        currency=body.cost.currency,
                        unit_cost=body.cost.unit_cost,
                        cost_category=body.cost.cost_category,
                    )
                    if body.cost is not None
                    else None
                ),
            ),
        )
    except (
        ProductEngineeringNotFoundError,
        ProductEngineeringScopeError,
        ProductEngineeringCostBoundaryError,
        IntegrityError,
    ) as error:
        raise product_error(error) from error
    return item_response(record)


@router.get("/erp-references", response_model=ErpBomReferenceListResponse)
def list_erp_references(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ErpBomReferenceListResponse:
    no_store(response)
    require_access(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.PRODUCT_ENGINEERING_VIEW,
    )
    return ErpBomReferenceListResponse(
        items=[
            erp_reference_response(record)
            for record in ProductEngineeringService(engine).list_erp_references(
                tenant_id=context.tenant.id,
                project_id=project_id,
            )
        ]
    )


@router.post(
    "/erp-references",
    response_model=ErpBomReferenceResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_erp_reference(
    project_id: UUID,
    body: ErpBomReferenceCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ErpBomReferenceResponse:
    no_store(response)
    require_access(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.PRODUCT_ENGINEERING_EDIT,
    )
    try:
        record = ProductEngineeringService(engine).add_erp_reference(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            draft=ErpBomReferenceDraft(
                bom_id=body.bom_id,
                reference_type=body.reference_type,
                source_system=body.source_system,
                external_id=body.external_id,
                external_url=body.external_url,
                metadata=body.metadata,
            ),
        )
    except (
        ProductEngineeringNotFoundError,
        ProductEngineeringScopeError,
        IntegrityError,
    ) as error:
        raise product_error(error) from error
    return erp_reference_response(record)
