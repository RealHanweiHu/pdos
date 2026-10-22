"""Immutable aggregate versions and captured graphs; host owns DDL/RLS/triggers."""

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


class ChangeRequestVersion(Row, Base):
    __tablename__ = "change_request_versions"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    change_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    previous_version_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    operation: Mapped[str] = mapped_column(String(80))
    intent_digest: Mapped[str] = mapped_column(String(64))
    request_snapshot: Mapped[dict] = mapped_column(JSONB)
    request_sha256: Mapped[str] = mapped_column(String(64))
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "change_id", "revision"),
        UniqueConstraint("tenant_id", "product_id", "change_id", "id", "revision"),
        UniqueConstraint("tenant_id", "product_id", "project_id", "change_id", "id", "revision"),
        UniqueConstraint("tenant_id", "product_id", "owner_id", "operation", "intent_digest"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id"],
            ["projects.tenant_id", "projects.product_id", "projects.id"],
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "change_id",
                "previous_version_id",
                "previous_revision",
            ],
            [
                "change_request_versions.tenant_id",
                "change_request_versions.product_id",
                "change_request_versions.project_id",
                "change_request_versions.change_id",
                "change_request_versions.id",
                "change_request_versions.revision",
            ],
        ),
        CheckConstraint(
            "visibility IN ('private','category','audience') AND status IN "
            "('draft','analysis','review','approved','implementing','verifying','closed')"
        ),
        CheckConstraint(
            "operation IN ('change.request.create','change.impact.compute',"
            "'change.order.prepare','change.order.approve','change.implementation.record',"
            "'change.effectivity.record','change.verification.record','change.close')"
        ),
        CheckConstraint(
            "(revision = 1 AND previous_version_id IS NULL AND previous_revision IS NULL) OR "
            "(revision > 1 AND previous_version_id IS NOT NULL AND previous_revision IS NOT NULL "
            "AND previous_version_id <> id AND revision = previous_revision + 1)"
        ),
        CheckConstraint("COALESCE(request_snapshot->>'status' = status, false)"),
        CheckConstraint(
            "(operation IN ('change.order.prepare','change.order.approve',"
            "'change.implementation.record','change.effectivity.record',"
            "'change.verification.record','change.close')) OR "
            "COALESCE(request_snapshot->'orders' = '[]'::jsonb, false)"
        ),
        CheckConstraint("COALESCE((request_snapshot->>'revision')::integer = revision, false)"),
        CheckConstraint("jsonb_array_length(required_source_read_set)>0"),
    )


class ChangeCurrent(Row, Base):
    __tablename__ = "change_request_currents"
    product_id: Mapped[UUID]
    change_id: Mapped[UUID]
    version_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "change_id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "change_id", "version_id", "revision"],
            [
                "change_request_versions.tenant_id",
                "change_request_versions.product_id",
                "change_request_versions.change_id",
                "change_request_versions.id",
                "change_request_versions.revision",
            ],
        ),
        CheckConstraint("revision > 0"),
    )


class ChangeGraphCapture(Row, Base):
    __tablename__ = "change_graph_captures"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    change_id: Mapped[UUID]
    change_version_id: Mapped[UUID]
    change_revision: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="prepared")
    capture_key: Mapped[str] = mapped_column(String(160))
    input_digest: Mapped[str] = mapped_column(String(64))
    graph_snapshot: Mapped[dict] = mapped_column(JSONB)
    graph_sha256: Mapped[str] = mapped_column(String(64))
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "id", "revision"),
        UniqueConstraint("tenant_id", "product_id", "owner_id", "capture_key"),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "change_id",
                "change_version_id",
                "change_revision",
            ],
            [
                "change_request_versions.tenant_id",
                "change_request_versions.product_id",
                "change_request_versions.project_id",
                "change_request_versions.change_id",
                "change_request_versions.id",
                "change_request_versions.revision",
            ],
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("revision = 1 AND status = 'prepared' AND change_revision > 0"),
        CheckConstraint("visibility IN ('private','category','audience')"),
        CheckConstraint("expires_at IS NULL OR expires_at > created_at"),
        CheckConstraint("COALESCE(graph_snapshot->>'nature' IN ('real','synthetic'), false)"),
        CheckConstraint("jsonb_array_length(required_source_read_set)>0"),
    )
