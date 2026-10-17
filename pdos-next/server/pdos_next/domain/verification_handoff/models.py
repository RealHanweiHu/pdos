"""Immutable actual facts; FormalVerificationCurrent remains the sole request truth."""

# Common registry must initialize before the front module it also imports.
# ruff: noqa: I001

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
from pdos_next.domain.verification_front.models import request_fk


class _Fact(Row):
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    request_id: Mapped[UUID]
    request_version_id: Mapped[UUID]
    request_revision: Mapped[int] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))


def common_constraints():
    return (
        UniqueConstraint("tenant_id", "product_id", "id"),
        request_fk(project=True),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint(
            "request_revision > 0 AND revision > 0 AND "
            "visibility IN ('private','category','audience')"
        ),
    )


class ActualMethodBatch(_Fact, Base):
    __tablename__ = "verification_actual_method_batches"
    status: Mapped[str] = mapped_column(String(16), default="prepared")
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    assessment_ids: Mapped[list] = mapped_column(JSONB)
    intent_digest: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        *common_constraints(),
        CheckConstraint("revision = 1 AND status = 'prepared'"),
    )


class ActualMethodApplicability(_Fact, Base):
    __tablename__ = "verification_actual_method_applicabilities"
    batch_id: Mapped[UUID]
    sample_id: Mapped[UUID]
    sample_revision: Mapped[int] = mapped_column(Integer)
    build_id: Mapped[UUID]
    actual_configuration_id: Mapped[UUID]
    actual_configuration_revision: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[str] = mapped_column(String(120))
    previous_assessment_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24))
    method_digest: Mapped[str] = mapped_column(String(64))
    assessment_snapshot: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        *common_constraints(),
        UniqueConstraint(
            "tenant_id", "product_id", "request_id", "sample_id", "item_id", "revision"
        ),
        UniqueConstraint(
            "tenant_id", "product_id", "request_id", "sample_id", "item_id", "id", "revision"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "batch_id"],
            [
                "verification_actual_method_batches.tenant_id",
                "verification_actual_method_batches.product_id",
                "verification_actual_method_batches.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "build_id", "sample_id"],
            [
                "sample_units.tenant_id",
                "sample_units.product_id",
                "sample_units.project_id",
                "sample_units.build_id",
                "sample_units.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "build_id", "actual_configuration_id"],
            [
                "actual_configurations.tenant_id",
                "actual_configurations.product_id",
                "actual_configurations.project_id",
                "actual_configurations.build_id",
                "actual_configurations.id",
            ],
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "request_id",
                "sample_id",
                "item_id",
                "previous_assessment_id",
                "previous_revision",
            ],
            [
                "verification_actual_method_applicabilities.tenant_id",
                "verification_actual_method_applicabilities.product_id",
                "verification_actual_method_applicabilities.request_id",
                "verification_actual_method_applicabilities.sample_id",
                "verification_actual_method_applicabilities.item_id",
                "verification_actual_method_applicabilities.id",
                "verification_actual_method_applicabilities.revision",
            ],
        ),
        CheckConstraint(
            "status IN ('applicable','not_applicable','unknown') AND sample_revision > 0 "
            "AND actual_configuration_revision > 0"
        ),
        CheckConstraint(
            "(revision = 1 AND previous_assessment_id IS NULL AND previous_revision IS NULL) "
            "OR (previous_assessment_id IS NOT NULL AND previous_revision IS NOT NULL "
            "AND revision = previous_revision + 1)"
        ),
    )


class ActualMethodCurrent(Row, Base):
    __tablename__ = "verification_current_actual_methods"
    product_id: Mapped[UUID]
    request_id: Mapped[UUID]
    sample_id: Mapped[UUID]
    item_id: Mapped[str] = mapped_column(String(120))
    assessment_id: Mapped[UUID]
    assessment_revision: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "request_id", "sample_id", "item_id"),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "request_id",
                "sample_id",
                "item_id",
                "assessment_id",
                "assessment_revision",
            ],
            [
                "verification_actual_method_applicabilities.tenant_id",
                "verification_actual_method_applicabilities.product_id",
                "verification_actual_method_applicabilities.request_id",
                "verification_actual_method_applicabilities.sample_id",
                "verification_actual_method_applicabilities.item_id",
                "verification_actual_method_applicabilities.id",
                "verification_actual_method_applicabilities.revision",
            ],
        ),
        CheckConstraint("assessment_revision > 0"),
    )


class VerificationHandoffFact(_Fact, Base):
    __tablename__ = "verification_handoff_facts"
    operation: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16))
    next_request_version_id: Mapped[UUID]
    next_request_revision: Mapped[int] = mapped_column(Integer)
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    kernel_event: Mapped[dict] = mapped_column(JSONB)
    intent_digest: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        *common_constraints(),
        UniqueConstraint("tenant_id", "product_id", "next_request_version_id"),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "request_id",
                "next_request_version_id",
                "next_request_revision",
            ],
            [
                "verification_formal_requests.tenant_id",
                "verification_formal_requests.product_id",
                "verification_formal_requests.project_id",
                "verification_formal_requests.request_id",
                "verification_formal_requests.id",
                "verification_formal_requests.revision",
            ],
        ),
        CheckConstraint("revision = 1 AND next_request_revision = request_revision + 1"),
        CheckConstraint("status IN ('offered','accepted','scheduled','executing')"),
        CheckConstraint(
            "operation IN ('verification.handoff.offer','verification.handoff.accept',"
            "'verification.handoff.return')"
        ),
    )
