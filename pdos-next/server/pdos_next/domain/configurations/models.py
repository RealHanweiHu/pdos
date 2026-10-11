from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


def scope_constraints():
    return (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "id", "revision"),
        ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"]),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("visibility IN ('private','category','audience') AND status = 'draft'"),
    )


class _Snapshot(Row):
    product_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    visibility: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)


class PartIdentity(_Snapshot, Base):
    __tablename__ = "parts"
    internal_number: Mapped[str | None] = mapped_column(String(100))
    erp_number: Mapped[str | None] = mapped_column(String(100))
    customer_number: Mapped[str | None] = mapped_column(String(100))
    mapping_version: Mapped[str | None] = mapped_column(String(100))
    external_design_refs: Mapped[list] = mapped_column(JSONB)
    __table_args__ = (*scope_constraints(), CheckConstraint("revision = 1"))


class _Revision(_Snapshot):
    series_id: Mapped[UUID]
    previous_id: Mapped[UUID | None]
    expected_previous_revision: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)


def revision_constraints(table):
    return (
        *scope_constraints(),
        UniqueConstraint("tenant_id", "product_id", "series_id", "revision"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "series_id"],
            [f"{table}.tenant_id", f"{table}.product_id", f"{table}.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "previous_id", "expected_previous_revision"],
            [f"{table}.tenant_id", f"{table}.product_id", f"{table}.id", f"{table}.revision"],
        ),
        CheckConstraint(
            "(previous_id IS NULL AND expected_previous_revision IS NULL AND revision = 1 "
            "AND series_id = id) OR (previous_id IS NOT NULL AND previous_id <> id "
            "AND expected_previous_revision > 0 AND revision = expected_previous_revision + 1)"
        ),
    )


class BomRevision(_Revision, Base):
    __tablename__ = "bom_revisions"
    __table_args__ = revision_constraints(__tablename__)


class BomLine(Row, Base):
    __tablename__ = "bom_lines"
    product_id: Mapped[UUID]
    bom_id: Mapped[UUID]
    key: Mapped[str] = mapped_column(String(80))
    part_id: Mapped[UUID]
    part_revision: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    unit: Mapped[str | None] = mapped_column(String(80))
    loss_rate: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    critical: Mapped[bool] = mapped_column(Boolean)
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "bom_id", "key"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "bom_id"],
            ["bom_revisions.tenant_id", "bom_revisions.product_id", "bom_revisions.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "part_id", "part_revision"],
            ["parts.tenant_id", "parts.product_id", "parts.id", "parts.revision"],
        ),
        CheckConstraint("quantity IS NULL OR (quantity > 0 AND unit IS NOT NULL)"),
        CheckConstraint("loss_rate IS NULL OR loss_rate >= 0"),
    )


class EngineeringConfiguration(_Revision, Base):
    __tablename__ = "engineering_configurations"
    definition_id: Mapped[UUID]
    definition_revision: Mapped[int] = mapped_column(Integer)
    bom_id: Mapped[UUID]
    bom_revision: Mapped[int] = mapped_column(Integer)
    design_versions: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        *revision_constraints(__tablename__),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "definition_id"],
            [
                "definition_revisions.tenant_id",
                "definition_revisions.product_id",
                "definition_revisions.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "bom_id", "bom_revision"],
            [
                "bom_revisions.tenant_id",
                "bom_revisions.product_id",
                "bom_revisions.id",
                "bom_revisions.revision",
            ],
        ),
        CheckConstraint("definition_revision > 0 AND bom_revision > 0"),
    )


class ProcessRevision(_Revision, Base):
    __tablename__ = "process_revisions"
    engineering_configuration_id: Mapped[UUID]
    engineering_revision: Mapped[int] = mapped_column(Integer)
    operations: Mapped[list] = mapped_column(JSONB)
    site: Mapped[str | None] = mapped_column(String(200))
    line: Mapped[str | None] = mapped_column(String(200))
    __table_args__ = (
        *revision_constraints(__tablename__),
        UniqueConstraint("tenant_id", "product_id", "engineering_configuration_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "engineering_configuration_id", "engineering_revision"],
            [
                "engineering_configurations.tenant_id",
                "engineering_configurations.product_id",
                "engineering_configurations.id",
                "engineering_configurations.revision",
            ],
        ),
        CheckConstraint("engineering_revision > 0"),
    )
