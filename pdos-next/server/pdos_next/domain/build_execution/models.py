from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


class _Snapshot(Row):
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    build_revision: Mapped[int] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    reason: Mapped[str] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)


def build_fk(column, table):
    return ForeignKeyConstraint(
        ["tenant_id", "product_id", "project_id", "build_id", column],
        [
            f"{table}.tenant_id",
            f"{table}.product_id",
            f"{table}.project_id",
            f"{table}.build_id",
            f"{table}.id",
        ],
    )


def scope_constraints(status):
    return (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "project_id", "build_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "build_id"],
            ["builds.tenant_id", "builds.product_id", "builds.project_id", "builds.id"],
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint(
            "visibility IN ('private','category','audience') AND "
            "revision = 1 AND build_revision > 0"
        ),
        CheckConstraint(f"status = '{status}'"),
    )


class ActualConfiguration(_Snapshot, Base):
    __tablename__ = "actual_configurations"
    status: Mapped[str] = mapped_column(String(16), default="recorded")
    planned_engineering_configuration_id: Mapped[UUID]
    planned_manufacturing_configuration_id: Mapped[UUID]
    actual_engineering_configuration_id: Mapped[UUID]
    actual_engineering_revision: Mapped[int] = mapped_column(Integer)
    actual_manufacturing_configuration_id: Mapped[UUID]
    actual_manufacturing_revision: Mapped[int] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    differences: Mapped[list] = mapped_column(JSONB)
    __table_args__ = (
        *scope_constraints("recorded"),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "build_id",
                "planned_engineering_configuration_id",
                "planned_manufacturing_configuration_id",
            ],
            [
                "builds.tenant_id",
                "builds.product_id",
                "builds.project_id",
                "builds.id",
                "builds.engineering_configuration_id",
                "builds.manufacturing_configuration_id",
            ],
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "planned_engineering_configuration_id",
                "planned_manufacturing_configuration_id",
            ],
            [
                "process_revisions.tenant_id",
                "process_revisions.product_id",
                "process_revisions.engineering_configuration_id",
                "process_revisions.id",
            ],
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "actual_engineering_configuration_id",
                "actual_manufacturing_configuration_id",
            ],
            [
                "process_revisions.tenant_id",
                "process_revisions.product_id",
                "process_revisions.engineering_configuration_id",
                "process_revisions.id",
            ],
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "actual_engineering_configuration_id",
                "actual_engineering_revision",
            ],
            [
                "engineering_configurations.tenant_id",
                "engineering_configurations.product_id",
                "engineering_configurations.id",
                "engineering_configurations.revision",
            ],
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "actual_manufacturing_configuration_id",
                "actual_manufacturing_revision",
            ],
            [
                "process_revisions.tenant_id",
                "process_revisions.product_id",
                "process_revisions.id",
                "process_revisions.revision",
            ],
        ),
        CheckConstraint("actual_engineering_revision > 0 AND actual_manufacturing_revision > 0"),
        CheckConstraint("observed_at <= created_at"),
    )


class BuildLot(_Snapshot, Base):
    __tablename__ = "build_lots"
    status: Mapped[str] = mapped_column(String(16), default="observed")
    actual_configuration_id: Mapped[UUID]
    actual_configuration_revision: Mapped[int] = mapped_column(Integer)
    lot_label: Mapped[str] = mapped_column(String(100))
    observed_unit_count: Mapped[int] = mapped_column(Integer)
    unit: Mapped[str] = mapped_column(String(80))
    observation_system: Mapped[str] = mapped_column(String(100))
    observation_external_id: Mapped[str] = mapped_column(String(200))
    observation_nature: Mapped[str] = mapped_column(String(16))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        *scope_constraints("observed"),
        UniqueConstraint("tenant_id", "product_id", "lot_label"),
        UniqueConstraint(
            "tenant_id", "product_id", "observation_system", "observation_external_id"
        ),
        UniqueConstraint(
            "tenant_id", "product_id", "project_id", "build_id", "id", "actual_configuration_id"
        ),
        build_fk("actual_configuration_id", "actual_configurations"),
        CheckConstraint("observed_unit_count > 0 AND actual_configuration_revision > 0"),
        CheckConstraint("observation_nature IN ('real','synthetic')"),
        CheckConstraint("occurred_at <= received_at AND received_at = created_at"),
        CheckConstraint("unit IN ('台','件','个','只','套','ea','piece','unit')"),
    )


class SampleAllocation(_Snapshot, Base):
    __tablename__ = "sample_allocations"
    status: Mapped[str] = mapped_column(String(16), default="identified")
    lot_id: Mapped[UUID]
    actual_configuration_id: Mapped[UUID]
    unit_count: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        *scope_constraints("identified"),
        UniqueConstraint("tenant_id", "product_id", "project_id", "build_id", "lot_id", "id"),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "build_id",
                "lot_id",
                "actual_configuration_id",
            ],
            [
                "build_lots.tenant_id",
                "build_lots.product_id",
                "build_lots.project_id",
                "build_lots.build_id",
                "build_lots.id",
                "build_lots.actual_configuration_id",
            ],
        ),
        CheckConstraint("unit_count > 0"),
    )


class SampleUnit(_Snapshot, Base):
    __tablename__ = "sample_units"
    status: Mapped[str] = mapped_column(String(16), default="identified")
    lot_id: Mapped[UUID]
    allocation_id: Mapped[UUID]
    actual_configuration_id: Mapped[UUID]
    label: Mapped[str] = mapped_column(String(100))
    operation_key: Mapped[str | None] = mapped_column(String(80))
    cavity: Mapped[str | None] = mapped_column(String(100))
    custodian_id: Mapped[UUID | None]
    custodian_label: Mapped[str | None] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(500))
    destination: Mapped[str | None] = mapped_column(String(500))
    availability: Mapped[str] = mapped_column(String(16), default="unknown")
    __table_args__ = (
        *scope_constraints("identified"),
        UniqueConstraint("tenant_id", "product_id", "label"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "build_id", "lot_id", "allocation_id"],
            [
                "sample_allocations.tenant_id",
                "sample_allocations.product_id",
                "sample_allocations.project_id",
                "sample_allocations.build_id",
                "sample_allocations.lot_id",
                "sample_allocations.id",
            ],
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "build_id",
                "lot_id",
                "actual_configuration_id",
            ],
            [
                "build_lots.tenant_id",
                "build_lots.product_id",
                "build_lots.project_id",
                "build_lots.build_id",
                "build_lots.id",
                "build_lots.actual_configuration_id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "custodian_id"],
            ["principals.tenant_id", "principals.id"],
        ),
        CheckConstraint("availability IN ('unknown','hold')"),
    )
