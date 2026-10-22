from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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


def scoped_fk(column, table):
    return ForeignKeyConstraint(
        ["tenant_id", "product_id", column],
        [f"{table}.tenant_id", f"{table}.product_id", f"{table}.id"],
    )


class Build(Row, Base):
    __tablename__ = "builds"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    project_revision: Mapped[int] = mapped_column(Integer)
    engineering_configuration_id: Mapped[UUID]
    manufacturing_configuration_id: Mapped[UUID]
    previous_build_id: Mapped[UUID | None]
    owner_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(String(160))
    type: Mapped[str] = mapped_column(String(24))
    purpose: Mapped[str] = mapped_column(Text)
    planned_quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    unit: Mapped[str] = mapped_column(String(80))
    planned_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_objectives: Mapped[str] = mapped_column(Text)
    disposition_plan: Mapped[str] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="planned")
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "project_id", "id"),
        UniqueConstraint(
            "tenant_id",
            "product_id",
            "project_id",
            "id",
            "engineering_configuration_id",
            "manufacturing_configuration_id",
            name="uq_build_fixed_plan_scope",
        ),
        scoped_fk("project_id", "projects"),
        scoped_fk("engineering_configuration_id", "engineering_configurations"),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "engineering_configuration_id",
                "manufacturing_configuration_id",
            ],
            [
                "process_revisions.tenant_id",
                "process_revisions.product_id",
                "process_revisions.engineering_configuration_id",
                "process_revisions.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "previous_build_id"],
            ["builds.tenant_id", "builds.product_id", "builds.project_id", "builds.id"],
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("revision > 0 AND project_revision > 0 AND planned_quantity > 0"),
        CheckConstraint("visibility IN ('private','category','audience') AND status = 'planned'"),
        CheckConstraint("type IN ('prototype','tool_trial','pilot')"),
        CheckConstraint(
            "planned_end IS NULL OR planned_start IS NULL OR planned_end >= planned_start"
        ),
        CheckConstraint("previous_build_id IS DISTINCT FROM id"),
    )


class BuildReadiness(Row, Base):
    __tablename__ = "build_readiness"
    product_id: Mapped[UUID]
    build_id: Mapped[UUID]
    build_revision: Mapped[int] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="blocked")
    result: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint("tenant_id", "build_id", "build_revision"),
        scoped_fk("build_id", "builds"),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("revision > 0 AND build_revision > 0 AND status = 'blocked'"),
        CheckConstraint("visibility IN ('private','category','audience')"),
        CheckConstraint("jsonb_typeof(result) = 'object'"),
    )
