"""Two host-registered immutable fact/current tables; no second SampleUnit ledger."""

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


class SampleReadinessFact(Row, Base):
    __tablename__ = "sample_readiness_facts"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    build_revision: Mapped[int] = mapped_column(Integer)
    sample_id: Mapped[UUID]
    sample_revision: Mapped[int] = mapped_column(Integer)
    lot_id: Mapped[UUID]
    lot_revision: Mapped[int] = mapped_column(Integer)
    actual_configuration_id: Mapped[UUID]
    actual_configuration_revision: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    previous_readiness_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(String(160))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    occurred_timezone: Mapped[str] = mapped_column(String(160))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    nature: Mapped[str] = mapped_column(String(16))
    event_source: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    fixed_snapshot: Mapped[dict] = mapped_column(JSONB)
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    intent_digest: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "sample_id", "revision"),
        UniqueConstraint(
            "tenant_id", "product_id", "project_id", "build_id", "sample_id", "id", "revision"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "build_id", "sample_id"],
            [
                f"sample_units.{key}"
                for key in ("tenant_id", "product_id", "project_id", "build_id", "id")
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
                f"build_lots.{key}"
                for key in (
                    "tenant_id",
                    "product_id",
                    "project_id",
                    "build_id",
                    "id",
                    "actual_configuration_id",
                )
            ],
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "build_id",
                "sample_id",
                "previous_readiness_id",
                "previous_revision",
            ],
            [
                f"sample_readiness_facts.{key}"
                for key in (
                    "tenant_id",
                    "product_id",
                    "project_id",
                    "build_id",
                    "sample_id",
                    "id",
                    "revision",
                )
            ],
        ),
        CheckConstraint(
            "revision > 0 AND sample_revision = 1 AND lot_revision = 1 "
            "AND actual_configuration_revision = 1 AND build_revision > 0"
        ),
        CheckConstraint(
            "status IN ('ready','hold') AND visibility IN ('private','category','audience') "
            "AND nature IN ('real','synthetic')"
        ),
        CheckConstraint("occurred_at <= received_at AND received_at = created_at"),
        CheckConstraint(
            "(revision = 1 AND previous_readiness_id IS NULL AND previous_revision IS NULL) "
            "OR (previous_readiness_id IS NOT NULL AND previous_readiness_id <> id "
            "AND previous_revision IS NOT NULL AND revision = previous_revision + 1)"
        ),
    )


class SampleReadinessCurrent(Row, Base):
    __tablename__ = "sample_current_readiness"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    sample_id: Mapped[UUID]
    readiness_id: Mapped[UUID]
    readiness_revision: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "sample_id"),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "build_id",
                "sample_id",
                "readiness_id",
                "readiness_revision",
            ],
            [
                f"sample_readiness_facts.{key}"
                for key in (
                    "tenant_id",
                    "product_id",
                    "project_id",
                    "build_id",
                    "sample_id",
                    "id",
                    "revision",
                )
            ],
        ),
        CheckConstraint("readiness_revision > 0"),
    )
