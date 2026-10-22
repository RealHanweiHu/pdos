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


class _Scoped(Row):
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    build_revision: Mapped[int] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)


def _scope():
    return (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "project_id", "build_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "build_id"],
            ["builds.tenant_id", "builds.product_id", "builds.project_id", "builds.id"],
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("visibility IN ('private','category','audience') AND build_revision > 0"),
    )


class SupplyCapture(_Scoped, Base):
    __tablename__ = "supply_source_captures"
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="unapplied")
    capture_key: Mapped[str] = mapped_column(String(160))
    request_sha256: Mapped[str] = mapped_column(String(64))
    snapshot_id: Mapped[UUID]
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    bound_demand: Mapped[dict] = mapped_column(JSONB)
    proposed_snapshot: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "product_id", "owner_id", "capture_key"),
        UniqueConstraint("tenant_id", "product_id", "snapshot_id"),
        UniqueConstraint("tenant_id", "product_id", "project_id", "build_id", "id", "snapshot_id"),
        CheckConstraint("revision = 1 AND status = 'unapplied'"),
    )


class SupplySnapshot(_Scoped, Base):
    __tablename__ = "supply_snapshots"
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="recorded")
    capture_id: Mapped[UUID]
    previous_snapshot_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    bound_demand: Mapped[dict] = mapped_column(JSONB)
    reconciliation: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "product_id", "build_id", "revision"),
        UniqueConstraint("tenant_id", "product_id", "build_id", "id", "revision"),
        UniqueConstraint("tenant_id", "product_id", "capture_id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "build_id", "capture_id", "id"],
            [
                "supply_source_captures.tenant_id",
                "supply_source_captures.product_id",
                "supply_source_captures.project_id",
                "supply_source_captures.build_id",
                "supply_source_captures.id",
                "supply_source_captures.snapshot_id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "build_id", "previous_snapshot_id", "previous_revision"],
            [
                "supply_snapshots.tenant_id",
                "supply_snapshots.product_id",
                "supply_snapshots.build_id",
                "supply_snapshots.id",
                "supply_snapshots.revision",
            ],
        ),
        CheckConstraint("status = 'recorded' AND revision > 0"),
        CheckConstraint(
            "(previous_snapshot_id IS NULL AND previous_revision IS NULL AND revision = 1) OR "
            "(previous_snapshot_id IS NOT NULL AND previous_revision IS NOT NULL "
            "AND previous_snapshot_id <> id AND revision = previous_revision + 1)"
        ),
    )


class SupplyCurrent(Row, Base):
    __tablename__ = "supply_current_snapshots"
    product_id: Mapped[UUID]
    build_id: Mapped[UUID]
    snapshot_id: Mapped[UUID]
    snapshot_revision: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "build_id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "build_id", "snapshot_id", "snapshot_revision"],
            [
                "supply_snapshots.tenant_id",
                "supply_snapshots.product_id",
                "supply_snapshots.build_id",
                "supply_snapshots.id",
                "supply_snapshots.revision",
            ],
        ),
        CheckConstraint("snapshot_revision > 0"),
    )


class KitProjection(_Scoped, Base):
    __tablename__ = "supply_kit_projections"
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="computed")
    supply_snapshot_id: Mapped[UUID]
    supply_revision: Mapped[int] = mapped_column(Integer)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    projection: Mapped[dict] = mapped_column(JSONB)
    projection_sha256: Mapped[str] = mapped_column(String(64))
    bound_demand: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        *_scope(),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "build_id", "supply_snapshot_id", "supply_revision"],
            [
                "supply_snapshots.tenant_id",
                "supply_snapshots.product_id",
                "supply_snapshots.build_id",
                "supply_snapshots.id",
                "supply_snapshots.revision",
            ],
        ),
        CheckConstraint("revision = 1 AND status = 'computed' AND supply_revision > 0"),
        CheckConstraint("as_of <= created_at"),
    )
