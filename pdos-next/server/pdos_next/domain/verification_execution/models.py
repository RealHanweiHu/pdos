from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


class VerificationPreparation(Row, Base):
    __tablename__ = "verification_preparations"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    build_revision: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="prepared")
    previous_preparation_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    request_snapshot: Mapped[dict] = mapped_column(JSONB)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "request_id", "revision"),
        UniqueConstraint("tenant_id", "product_id", "request_id", "id", "revision"),
        UniqueConstraint(
            "tenant_id",
            "product_id",
            "project_id",
            "build_id",
            "build_revision",
            "request_id",
            "id",
            "revision",
        ),
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
                "build_revision",
                "request_id",
                "previous_preparation_id",
                "previous_revision",
            ],
            [
                "verification_preparations.tenant_id",
                "verification_preparations.product_id",
                "verification_preparations.project_id",
                "verification_preparations.build_id",
                "verification_preparations.build_revision",
                "verification_preparations.request_id",
                "verification_preparations.id",
                "verification_preparations.revision",
            ],
        ),
        CheckConstraint("revision > 0 AND build_revision > 0 AND status = 'prepared'"),
        CheckConstraint("visibility IN ('private','category','audience')"),
        CheckConstraint(
            "(previous_preparation_id IS NULL AND previous_revision IS NULL AND revision = 1) OR "
            "(previous_preparation_id IS NOT NULL AND previous_revision IS NOT NULL "
            "AND previous_preparation_id <> id AND revision = previous_revision + 1)"
        ),
        CheckConstraint("COALESCE(request_snapshot->>'status' = 'draft', false)"),
        CheckConstraint(
            "COALESCE(request_snapshot->'samples' = '[]'::jsonb "
            "AND request_snapshot->'acceptances' = '[]'::jsonb "
            "AND request_snapshot->'offered_coverage' = '[]'::jsonb "
            "AND request_snapshot->'returns' = '[]'::jsonb, false)"
        ),
        CheckConstraint(
            "COALESCE(jsonb_typeof(request_snapshot->'timeline'->'request_created') "
            "= 'object', false)"
        ),
        *[
            CheckConstraint(
                f"COALESCE(request_snapshot->'timeline'->'{field}' = 'null'::jsonb, false)"
            )
            for field in (
                "sample_ready",
                "documents_complete",
                "offered",
                "accepted",
                "promised_start",
                "actual_start",
                "preliminary_result",
                "final_result",
                "disposed",
            )
        ],
    )


class VerificationCurrent(Row, Base):
    __tablename__ = "verification_current_preparations"
    product_id: Mapped[UUID]
    request_id: Mapped[UUID]
    preparation_id: Mapped[UUID]
    preparation_revision: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "request_id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "request_id", "preparation_id", "preparation_revision"],
            [
                "verification_preparations.tenant_id",
                "verification_preparations.product_id",
                "verification_preparations.request_id",
                "verification_preparations.id",
                "verification_preparations.revision",
            ],
        ),
        CheckConstraint("preparation_revision > 0"),
    )
