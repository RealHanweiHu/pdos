"""Immutable observation/result records. Root owns registration, RLS and migrations."""

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

from pdos_next.domain.verification_front.models import request_fk
from pdos_next.domain.verification_launch.models import identity_fk, version_fk
from pdos_next.models import Base, Row


class ResultScope:
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    request_id: Mapped[UUID]
    run_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer, default=1)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24))


def base_constraints():
    return (
        identity_fk(),
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "run_id", "id", "revision"),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("revision = 1 AND visibility IN ('private','category','audience')"),
    )


class MeasurementImportCapture(ResultScope, Row, Base):
    __tablename__ = "measurement_import_captures"
    capture_key: Mapped[str] = mapped_column(String(200))
    input_digest: Mapped[str] = mapped_column(String(64))
    run_version_id: Mapped[UUID]
    run_revision: Mapped[int] = mapped_column(Integer)
    run_sha256: Mapped[str] = mapped_column(String(64))
    request_version_id: Mapped[UUID]
    request_revision: Mapped[int] = mapped_column(Integer)
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    observations: Mapped[list] = mapped_column(JSONB)
    report_binding: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        *base_constraints(),
        version_fk(),
        request_fk(project=True),
        UniqueConstraint("tenant_id", "product_id", "run_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "owner_id", "capture_key"),
        CheckConstraint("status = 'prepared' AND run_revision >= 2 AND request_revision > 0"),
    )


class MeasurementRecord(ResultScope, Row, Base):
    __tablename__ = "test_measurements"
    run_version_id: Mapped[UUID]
    run_revision: Mapped[int] = mapped_column(Integer)
    sample_id: Mapped[UUID]
    sample_revision: Mapped[int] = mapped_column(Integer)
    actual_configuration_id: Mapped[UUID]
    actual_configuration_revision: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[str] = mapped_column(String(120))
    capture_id: Mapped[UUID]
    measurement: Mapped[dict] = mapped_column(JSONB)
    measurement_sha256: Mapped[str] = mapped_column(String(64))
    verified_observation: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        *base_constraints(),
        version_fk(),
        UniqueConstraint("tenant_id", "run_id", "sample_id", "item_id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "sample_id"],
            ["sample_units.tenant_id", "sample_units.product_id", "sample_units.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "actual_configuration_id"],
            [
                "actual_configurations.tenant_id",
                "actual_configurations.product_id",
                "actual_configurations.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "capture_id"],
            [
                "measurement_import_captures.tenant_id",
                "measurement_import_captures.product_id",
                "measurement_import_captures.id",
            ],
        ),
        CheckConstraint(
            "status = 'recorded' AND run_revision > 2 AND sample_revision > 0 "
            "AND actual_configuration_revision > 0"
        ),
    )


class TestResultProjection(ResultScope, Row, Base):
    __tablename__ = "test_result_projections"
    run_version_id: Mapped[UUID]
    run_revision: Mapped[int] = mapped_column(Integer)
    run_sha256: Mapped[str] = mapped_column(String(64))
    basis_sha256: Mapped[str] = mapped_column(String(64))
    rules_version: Mapped[str] = mapped_column(String(120))
    rules_sha256: Mapped[str] = mapped_column(String(64))
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[str] = mapped_column(String(24))
    computed_results: Mapped[list] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        *base_constraints(),
        version_fk(),
        UniqueConstraint("tenant_id", "product_id", "run_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "run_id", "basis_sha256"),
        CheckConstraint("status = 'computed' AND result IN ('pass','fail','indeterminate')"),
    )


class TestResultActionFact(ResultScope, Row, Base):
    __tablename__ = "test_result_actions"
    operation: Mapped[str] = mapped_column(String(80))
    actor_id: Mapped[UUID]
    intent_digest: Mapped[str] = mapped_column(String(64))
    request_version_id: Mapped[UUID]
    request_revision: Mapped[int] = mapped_column(Integer)
    next_request_version_id: Mapped[UUID]
    next_request_revision: Mapped[int] = mapped_column(Integer)
    run_version_id: Mapped[UUID]
    run_revision: Mapped[int] = mapped_column(Integer)
    next_run_version_id: Mapped[UUID]
    next_run_revision: Mapped[int] = mapped_column(Integer)
    capture_id: Mapped[UUID | None]
    projection_id: Mapped[UUID]
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    event: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        *base_constraints(),
        version_fk(),
        version_fk("next_run_version_id", "next_run_revision"),
        request_fk(project=True),
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
        UniqueConstraint("tenant_id", "product_id", "next_run_version_id"),
        UniqueConstraint("tenant_id", "product_id", "actor_id", "operation", "intent_digest"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "capture_id"],
            [
                "measurement_import_captures.tenant_id",
                "measurement_import_captures.product_id",
                "measurement_import_captures.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "projection_id"],
            [
                "test_result_projections.tenant_id",
                "test_result_projections.product_id",
                "test_result_projections.id",
            ],
        ),
        CheckConstraint(
            "operation IN ('test.results.import','test.run.review','test.disposition.decide') "
            "AND status = 'recorded'"
        ),
        CheckConstraint(
            "next_run_revision = run_revision + 1 "
            "AND next_request_revision IN (request_revision, request_revision + 1)"
        ),
    )
