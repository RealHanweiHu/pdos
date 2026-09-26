"""Project-scoped Specification and Development BOM application service."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select
from sqlalchemy.engine import RowMapping

from app.db.schema import tables
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class ProductEngineeringNotFoundError(LookupError):
    """Raised when a project-scoped product engineering object is absent."""


class ProductEngineeringScopeError(ValueError):
    """Raised when a related object is outside the bound tenant/project."""


class ProductEngineeringCostBoundaryError(ValueError):
    """Raised when cost truth is attached outside a Cost BOM."""


@dataclass(frozen=True)
class SpecificationRecord:
    id: UUID
    project_id: UUID
    created_by_user_id: UUID
    code: str
    title: str
    version: int
    requirement_id: UUID | None
    owner_user_id: UUID | None
    verification_method: str | None
    acceptance_criteria: str | None
    criticality: str
    content: dict[str, object]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SpecificationDraft:
    code: str
    title: str
    version: int
    content: dict[str, object]
    requirement_id: UUID | None = None
    owner_user_id: UUID | None = None
    verification_method: str | None = None
    acceptance_criteria: str | None = None
    criticality: str = "standard"


@dataclass(frozen=True)
class BomItemCostRecord:
    currency: str
    unit_cost: Decimal
    cost_category: str | None


@dataclass(frozen=True)
class BomItemCostDraft:
    currency: str
    unit_cost: Decimal
    cost_category: str | None


@dataclass(frozen=True)
class DevelopmentBomItemRecord:
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
    cost: BomItemCostRecord | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DevelopmentBomItemDraft:
    parent_item_id: UUID | None
    line_number: int
    part_number: str
    description: str
    quantity: Decimal
    unit: str
    material_reference: str | None
    attributes: dict[str, object]
    cost: BomItemCostDraft | None


@dataclass(frozen=True)
class DevelopmentBomRecord:
    id: UUID
    project_id: UUID
    specification_id: UUID | None
    created_by_user_id: UUID
    bom_type: str
    code: str
    name: str
    version: int
    notes: str | None
    items: tuple[DevelopmentBomItemRecord, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DevelopmentBomDraft:
    specification_id: UUID | None
    bom_type: str
    code: str
    name: str
    version: int
    notes: str | None


@dataclass(frozen=True)
class ErpBomReferenceRecord:
    id: UUID
    project_id: UUID
    bom_id: UUID | None
    reference_type: str
    source_system: str
    external_id: str
    external_url: str | None
    metadata: dict[str, object]
    created_at: datetime


@dataclass(frozen=True)
class ErpBomReferenceDraft:
    bom_id: UUID | None
    reference_type: str
    source_system: str
    external_id: str
    external_url: str | None
    metadata: dict[str, object]


def _specification_record(values: RowMapping) -> SpecificationRecord:
    return SpecificationRecord(
        id=values["id"],
        project_id=values["project_id"],
        created_by_user_id=values["created_by_user_id"],
        code=values["code"],
        title=values["title"],
        version=values["version"],
        requirement_id=values["requirement_id"],
        owner_user_id=values["owner_user_id"],
        verification_method=values["verification_method"],
        acceptance_criteria=values["acceptance_criteria"],
        criticality=values["criticality"],
        content=dict(values["content"]),
        created_at=values["created_at"],
        updated_at=values["updated_at"],
    )


def _cost_record(values: RowMapping) -> BomItemCostRecord:
    return BomItemCostRecord(
        currency=values["currency"],
        unit_cost=values["unit_cost"],
        cost_category=values["cost_category"],
    )


def _bom_item_record(
    values: RowMapping, *, cost: BomItemCostRecord | None
) -> DevelopmentBomItemRecord:
    return DevelopmentBomItemRecord(
        id=values["id"],
        bom_id=values["bom_id"],
        parent_item_id=values["parent_item_id"],
        line_number=values["line_number"],
        part_number=values["part_number"],
        description=values["description"],
        quantity=values["quantity"],
        unit=values["unit"],
        material_reference=values["material_reference"],
        attributes=dict(values["attributes"]),
        cost=cost,
        created_at=values["created_at"],
        updated_at=values["updated_at"],
    )


def _erp_reference_record(values: RowMapping) -> ErpBomReferenceRecord:
    return ErpBomReferenceRecord(
        id=values["id"],
        project_id=values["project_id"],
        bom_id=values["bom_id"],
        reference_type=values["reference_type"],
        source_system=values["source_system"],
        external_id=values["external_id"],
        external_url=values["external_url"],
        metadata=dict(values["metadata"]),
        created_at=values["created_at"],
    )


def _specification_snapshot(record: SpecificationRecord) -> dict[str, object]:
    return {
        "id": str(record.id),
        "project_id": str(record.project_id),
        "code": record.code,
        "title": record.title,
        "version": record.version,
        "requirement_id": str(record.requirement_id) if record.requirement_id else None,
        "owner_user_id": str(record.owner_user_id) if record.owner_user_id else None,
        "acceptance_criteria": record.acceptance_criteria,
        "criticality": record.criticality,
        "verification_method": record.verification_method,
        "content": record.content,
    }


def _bom_snapshot(record: DevelopmentBomRecord) -> dict[str, object]:
    return {
        "id": str(record.id),
        "project_id": str(record.project_id),
        "specification_id": str(record.specification_id) if record.specification_id else None,
        "bom_type": record.bom_type,
        "code": record.code,
        "name": record.name,
        "version": record.version,
    }


def _item_snapshot(record: DevelopmentBomItemRecord) -> dict[str, object]:
    return {
        "id": str(record.id),
        "bom_id": str(record.bom_id),
        "parent_item_id": str(record.parent_item_id) if record.parent_item_id else None,
        "line_number": record.line_number,
        "part_number": record.part_number,
        "description": record.description,
        "quantity": str(record.quantity),
        "unit": record.unit,
        "material_reference": record.material_reference,
        "attributes": record.attributes,
        "cost": (
            {
                "currency": record.cost.currency,
                "unit_cost": str(record.cost.unit_cost),
                "cost_category": record.cost.cost_category,
            }
            if record.cost
            else None
        ),
    }


def _reference_snapshot(record: ErpBomReferenceRecord) -> dict[str, object]:
    return {
        "id": str(record.id),
        "project_id": str(record.project_id),
        "bom_id": str(record.bom_id) if record.bom_id else None,
        "reference_type": record.reference_type,
        "source_system": record.source_system,
        "external_id": record.external_id,
        "external_url": record.external_url,
        "metadata": record.metadata,
    }


class ProductEngineeringService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _require_project(connection: Connection, *, tenant_id: UUID, project_id: UUID) -> None:
        found = connection.execute(
            select(tables.projects.c.id).where(
                tables.projects.c.tenant_id == tenant_id,
                tables.projects.c.id == project_id,
            )
        ).scalar_one_or_none()
        if found is None:
            raise ProductEngineeringNotFoundError

    @staticmethod
    def _require_specification(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        specification_id: UUID,
    ) -> None:
        found = connection.execute(
            select(tables.specifications.c.id).where(
                tables.specifications.c.tenant_id == tenant_id,
                tables.specifications.c.project_id == project_id,
                tables.specifications.c.id == specification_id,
            )
        ).scalar_one_or_none()
        if found is None:
            raise ProductEngineeringScopeError

    @staticmethod
    def _get_bom_row(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        bom_id: UUID,
    ) -> RowMapping:
        row = (
            connection.execute(
                select(tables.development_boms).where(
                    tables.development_boms.c.tenant_id == tenant_id,
                    tables.development_boms.c.project_id == project_id,
                    tables.development_boms.c.id == bom_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ProductEngineeringNotFoundError
        return row

    @staticmethod
    def _list_items(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        bom_id: UUID,
    ) -> tuple[DevelopmentBomItemRecord, ...]:
        items: list[DevelopmentBomItemRecord] = []
        rows = (
            connection.execute(
                select(tables.development_bom_items)
                .where(
                    tables.development_bom_items.c.tenant_id == tenant_id,
                    tables.development_bom_items.c.project_id == project_id,
                    tables.development_bom_items.c.bom_id == bom_id,
                )
                .order_by(tables.development_bom_items.c.line_number)
            )
            .mappings()
            .all()
        )
        for row in rows:
            cost_row = (
                connection.execute(
                    select(tables.cost_bom_items).where(
                        tables.cost_bom_items.c.tenant_id == tenant_id,
                        tables.cost_bom_items.c.bom_item_id == row["id"],
                    )
                )
                .mappings()
                .one_or_none()
            )
            items.append(_bom_item_record(row, cost=_cost_record(cost_row) if cost_row else None))
        return tuple(items)

    @classmethod
    def _bom_record(
        cls,
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        bom_id: UUID,
    ) -> DevelopmentBomRecord:
        row = cls._get_bom_row(
            connection,
            tenant_id=tenant_id,
            project_id=project_id,
            bom_id=bom_id,
        )
        values = row
        return DevelopmentBomRecord(
            id=values["id"],
            project_id=values["project_id"],
            specification_id=values["specification_id"],
            created_by_user_id=values["created_by_user_id"],
            bom_type=values["bom_type"],
            code=values["code"],
            name=values["name"],
            version=values["version"],
            notes=values["notes"],
            items=cls._list_items(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                bom_id=bom_id,
            ),
            created_at=values["created_at"],
            updated_at=values["updated_at"],
        )

    def list_specifications(
        self, *, tenant_id: UUID, project_id: UUID
    ) -> list[SpecificationRecord]:
        with self._engine.connect() as connection:
            self._require_project(connection, tenant_id=tenant_id, project_id=project_id)
            return [
                _specification_record(row)
                for row in connection.execute(
                    select(tables.specifications)
                    .where(
                        tables.specifications.c.tenant_id == tenant_id,
                        tables.specifications.c.project_id == project_id,
                    )
                    .order_by(
                        tables.specifications.c.updated_at.desc(),
                        tables.specifications.c.id.desc(),
                    )
                )
                .mappings()
                .all()
            ]

    def create_specification(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        draft: SpecificationDraft,
        connection: Connection | None = None,
        audit_draft: AuditDraft | None = None,
    ) -> SpecificationRecord:
        specification_id = uuid4()
        occurred_at = datetime.now(UTC)
        with (
            nullcontext(connection)
            if connection is not None
            else self._engine.begin() as connection
        ):
            self._require_project(connection, tenant_id=tenant_id, project_id=project_id)
            connection.execute(
                tables.specifications.insert(),
                {
                    "id": specification_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "created_by_user_id": actor_user_id,
                    "code": draft.code,
                    "title": draft.title,
                    "version": draft.version,
                    "requirement_id": draft.requirement_id,
                    "owner_user_id": draft.owner_user_id,
                    "verification_method": draft.verification_method,
                    "acceptance_criteria": draft.acceptance_criteria,
                    "criticality": draft.criticality,
                    "content": draft.content,
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            row = (
                connection.execute(
                    select(tables.specifications).where(
                        tables.specifications.c.tenant_id == tenant_id,
                        tables.specifications.c.project_id == project_id,
                        tables.specifications.c.id == specification_id,
                    )
                )
                .mappings()
                .one()
            )
            record = _specification_record(row)
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"specification:{specification_id}:created",
                    event_type="SPECIFICATION_CREATED",
                    source="product_engineering_service",
                    entity_id=specification_id,
                    payload={"specification_code": record.code, "version": record.version},
                    occurred_at=occurred_at,
                ),
                replace(
                    audit_draft or AuditDraft(action="specification.create"),
                    after_snapshot=_specification_snapshot(record),
                ),
            )
            return record

    def list_boms(self, *, tenant_id: UUID, project_id: UUID) -> list[DevelopmentBomRecord]:
        with self._engine.connect() as connection:
            self._require_project(connection, tenant_id=tenant_id, project_id=project_id)
            bom_ids = connection.execute(
                select(tables.development_boms.c.id)
                .where(
                    tables.development_boms.c.tenant_id == tenant_id,
                    tables.development_boms.c.project_id == project_id,
                )
                .order_by(
                    tables.development_boms.c.updated_at.desc(),
                    tables.development_boms.c.id.desc(),
                )
            ).scalars()
            return [
                self._bom_record(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    bom_id=bom_id,
                )
                for bom_id in bom_ids
            ]

    def create_bom(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        draft: DevelopmentBomDraft,
    ) -> DevelopmentBomRecord:
        bom_id = uuid4()
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            self._require_project(connection, tenant_id=tenant_id, project_id=project_id)
            if draft.specification_id is not None:
                self._require_specification(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    specification_id=draft.specification_id,
                )
            connection.execute(
                tables.development_boms.insert(),
                {
                    "id": bom_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "specification_id": draft.specification_id,
                    "created_by_user_id": actor_user_id,
                    "bom_type": draft.bom_type,
                    "code": draft.code,
                    "name": draft.name,
                    "version": draft.version,
                    "notes": draft.notes,
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            record = self._bom_record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                bom_id=bom_id,
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"development-bom:{bom_id}:created",
                    event_type="DEVELOPMENT_BOM_CREATED",
                    source="product_engineering_service",
                    entity_id=bom_id,
                    payload={
                        "bom_code": record.code,
                        "bom_type": record.bom_type,
                        "version": record.version,
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="development_bom.create",
                    after_snapshot=_bom_snapshot(record),
                ),
            )
            return record

    def add_bom_item(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        bom_id: UUID,
        draft: DevelopmentBomItemDraft,
    ) -> DevelopmentBomItemRecord:
        item_id = uuid4()
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            bom_values = self._get_bom_row(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                bom_id=bom_id,
            )
            if (bom_values["bom_type"] == "cost") is (draft.cost is None):
                raise ProductEngineeringCostBoundaryError
            if draft.parent_item_id is not None:
                parent = connection.execute(
                    select(tables.development_bom_items.c.id).where(
                        tables.development_bom_items.c.tenant_id == tenant_id,
                        tables.development_bom_items.c.bom_id == bom_id,
                        tables.development_bom_items.c.id == draft.parent_item_id,
                    )
                ).scalar_one_or_none()
                if parent is None:
                    raise ProductEngineeringScopeError
            connection.execute(
                tables.development_bom_items.insert(),
                {
                    "id": item_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "bom_id": bom_id,
                    "parent_item_id": draft.parent_item_id,
                    "line_number": draft.line_number,
                    "part_number": draft.part_number,
                    "description": draft.description,
                    "quantity": draft.quantity,
                    "unit": draft.unit,
                    "material_reference": draft.material_reference,
                    "attributes": draft.attributes,
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            cost_record = None
            if draft.cost is not None:
                connection.execute(
                    tables.cost_bom_items.insert(),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "bom_id": bom_id,
                        "bom_type": "cost",
                        "bom_item_id": item_id,
                        "currency": draft.cost.currency,
                        "unit_cost": draft.cost.unit_cost,
                        "cost_category": draft.cost.cost_category,
                        "created_at": occurred_at,
                        "updated_at": occurred_at,
                    },
                )
                cost_record = BomItemCostRecord(
                    currency=draft.cost.currency,
                    unit_cost=draft.cost.unit_cost,
                    cost_category=draft.cost.cost_category,
                )
            row = (
                connection.execute(
                    select(tables.development_bom_items).where(
                        tables.development_bom_items.c.tenant_id == tenant_id,
                        tables.development_bom_items.c.id == item_id,
                    )
                )
                .mappings()
                .one()
            )
            record = _bom_item_record(row, cost=cost_record)
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"development-bom-item:{item_id}:added",
                    event_type="DEVELOPMENT_BOM_ITEM_ADDED",
                    source="product_engineering_service",
                    entity_id=item_id,
                    payload={
                        "bom_id": str(bom_id),
                        "part_number": record.part_number,
                        "line_number": record.line_number,
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="development_bom_item.add",
                    after_snapshot=_item_snapshot(record),
                ),
            )
            return record

    def list_erp_references(
        self, *, tenant_id: UUID, project_id: UUID
    ) -> list[ErpBomReferenceRecord]:
        with self._engine.connect() as connection:
            self._require_project(connection, tenant_id=tenant_id, project_id=project_id)
            return [
                _erp_reference_record(row)
                for row in connection.execute(
                    select(tables.erp_bom_references)
                    .where(
                        tables.erp_bom_references.c.tenant_id == tenant_id,
                        tables.erp_bom_references.c.project_id == project_id,
                    )
                    .order_by(
                        tables.erp_bom_references.c.created_at.desc(),
                        tables.erp_bom_references.c.id.desc(),
                    )
                )
                .mappings()
                .all()
            ]

    def add_erp_reference(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        draft: ErpBomReferenceDraft,
    ) -> ErpBomReferenceRecord:
        reference_id = uuid4()
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            self._require_project(connection, tenant_id=tenant_id, project_id=project_id)
            if draft.bom_id is not None:
                self._get_bom_row(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    bom_id=draft.bom_id,
                )
            connection.execute(
                tables.erp_bom_references.insert(),
                {
                    "id": reference_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "bom_id": draft.bom_id,
                    "reference_type": draft.reference_type,
                    "source_system": draft.source_system,
                    "external_id": draft.external_id,
                    "external_url": draft.external_url,
                    "metadata": draft.metadata,
                    "created_at": occurred_at,
                },
            )
            row = (
                connection.execute(
                    select(tables.erp_bom_references).where(
                        tables.erp_bom_references.c.tenant_id == tenant_id,
                        tables.erp_bom_references.c.id == reference_id,
                    )
                )
                .mappings()
                .one()
            )
            record = _erp_reference_record(row)
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"erp-bom-reference:{reference_id}:added",
                    event_type="ERP_BOM_REFERENCE_ADDED",
                    source="product_engineering_service",
                    entity_id=reference_id,
                    payload={
                        "reference_type": record.reference_type,
                        "source_system": record.source_system,
                        "external_id": record.external_id,
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="erp_bom_reference.add",
                    after_snapshot=_reference_snapshot(record),
                ),
            )
            return record
