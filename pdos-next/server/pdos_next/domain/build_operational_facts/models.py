"""Host registers these five tables and migrations; no independent database."""

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


class BuildOperationalFact(Row, Base):
    __tablename__ = "build_operational_facts"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    build_revision: Mapped[int] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    issuer_key: Mapped[str] = mapped_column(String(100))
    issuer_version: Mapped[str] = mapped_column(String(100))
    issuer_epoch: Mapped[int] = mapped_column(Integer)
    nature: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(200))
    series_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    binding: Mapped[dict] = mapped_column(JSONB)
    data: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    fact_sha256: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)

    @property
    def status(self):
        return self.state

    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "project_id", "build_id", "id", "revision"),
        UniqueConstraint("tenant_id", "product_id", "build_id", "series_id", "revision"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "build_id"],
            ["builds.tenant_id", "builds.product_id", "builds.project_id", "builds.id"],
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "build_id",
                "previous_id",
                "previous_revision",
            ],
            [
                "build_operational_facts.tenant_id",
                "build_operational_facts.product_id",
                "build_operational_facts.project_id",
                "build_operational_facts.build_id",
                "build_operational_facts.id",
                "build_operational_facts.revision",
            ],
        ),
        CheckConstraint(
            "revision>0 AND build_revision>0 AND issuer_epoch>0 AND valid_until>valid_from"
        ),
        CheckConstraint(
            "state IN ('active','withdrawn') AND nature IN ('real','synthetic') "
            "AND visibility IN ('private','category','audience')"
        ),
        CheckConstraint(
            "(revision=1 AND previous_id IS NULL AND previous_revision IS NULL AND series_id=id) "
            "OR (previous_id IS NOT NULL AND previous_id<>id AND previous_revision>0 "
            "AND revision=previous_revision+1)"
        ),
    )


class BuildOperationalCurrent(Row, Base):
    __tablename__ = "build_operational_current"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    fact_id: Mapped[UUID]
    fact_revision: Mapped[int] = mapped_column(Integer)
    epoch: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "build_id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "build_id", "fact_id", "fact_revision"],
            [
                "build_operational_facts.tenant_id",
                "build_operational_facts.product_id",
                "build_operational_facts.project_id",
                "build_operational_facts.build_id",
                "build_operational_facts.id",
                "build_operational_facts.revision",
            ],
        ),
        CheckConstraint("fact_revision>0 AND epoch>0"),
    )


class OperationalAsset(Row, Base):
    __tablename__ = "operational_asset_sentinels"
    kind: Mapped[str] = mapped_column(String(16))
    external_key: Mapped[str] = mapped_column(String(64))
    identity: Mapped[dict] = mapped_column(JSONB)
    revision: Mapped[int] = mapped_column(Integer)
    data_sha256: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSONB)
    occupancy_epoch: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "kind", "external_key"),
        CheckConstraint("kind IN ('material','resource') AND revision>0 AND occupancy_epoch>0"),
    )


class MaterialHold(Row, Base):
    __tablename__ = "operational_material_holds"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    owner_execution_id: Mapped[UUID]
    asset_id: Mapped[UUID]
    bom_item_id: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 12))
    unit: Mapped[str] = mapped_column(String(200))
    intent_digest: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "build_id", "asset_id", "bom_item_id"),
        ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["operational_asset_sentinels.tenant_id", "operational_asset_sentinels.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "build_id"],
            ["builds.tenant_id", "builds.product_id", "builds.project_id", "builds.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "build_id", "owner_execution_id"],
            [
                f"build_starts.{key}"
                for key in ("tenant_id", "product_id", "project_id", "build_id", "id")
            ],
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("quantity>0"),
    )


class ResourceOccupancy(Row, Base):
    __tablename__ = "operational_resource_occupancies"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    owner_execution_id: Mapped[UUID]
    owner_kind: Mapped[str] = mapped_column(String(16), default="build", server_default="build")
    build_start_id: Mapped[UUID | None]
    test_run_id: Mapped[UUID | None]
    asset_id: Mapped[UUID]
    resource_id: Mapped[UUID]
    resource_revision: Mapped[int] = mapped_column(Integer)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_finish: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    units: Mapped[Decimal] = mapped_column(Numeric(24, 12))
    intent_digest: Mapped[str] = mapped_column(String(64))
    reservation: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "owner_kind", "owner_execution_id", "asset_id"),
        ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["operational_asset_sentinels.tenant_id", "operational_asset_sentinels.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "build_id"],
            ["builds.tenant_id", "builds.product_id", "builds.project_id", "builds.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "build_id", "build_start_id"],
            [
                f"build_starts.{key}"
                for key in ("tenant_id", "product_id", "project_id", "build_id", "id")
            ],
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "build_id", "test_run_id"],
            [
                f"verification_run_identities.{key}"
                for key in ("tenant_id", "product_id", "project_id", "build_id", "id")
            ],
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "(owner_kind='build' AND build_start_id=owner_execution_id "
            "AND build_start_id IS NOT NULL AND test_run_id IS NULL) OR "
            "(owner_kind='test_run' AND test_run_id=owner_execution_id "
            "AND test_run_id IS NOT NULL AND build_start_id IS NULL)"
        ),
        CheckConstraint("resource_revision>0 AND units>0 AND window_finish>window_start"),
        CheckConstraint("asset_id=resource_id"),
    )
