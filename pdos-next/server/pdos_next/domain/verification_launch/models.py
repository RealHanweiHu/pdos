"""Immutable Run versions and intent facts; FormalCurrent remains request truth."""

# The common model registry initializes before its domain children.
# ruff: noqa: I001
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row
from pdos_next.domain.verification_front.models import request_fk


def identity_fk():
    return ForeignKeyConstraint(
        ["tenant_id", "product_id", "project_id", "build_id", "run_id"],
        [
            f"verification_run_identities.{name}"
            for name in ("tenant_id", "product_id", "project_id", "build_id", "id")
        ],
    )


def version_fk(identity="run_version_id", revision="run_revision"):
    return ForeignKeyConstraint(
        ["tenant_id", "product_id", "request_id", "run_id", identity, revision],
        [
            f"verification_run_versions.{name}"
            for name in ("tenant_id", "product_id", "request_id", "run_id", "id", "revision")
        ],
    )


class VerificationRunIdentity(Row, Base):
    __tablename__ = "verification_run_identities"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    request_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "project_id", "build_id", "id"),
        Index("ix_verification_run_identities_request", "tenant_id", "product_id", "request_id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "build_id"],
            [f"builds.{name}" for name in ("tenant_id", "product_id", "project_id", "id")],
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("visibility IN ('private','category','audience')"),
    )


class VerificationRunVersion(Row, Base):
    __tablename__ = "verification_run_versions"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    build_revision: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[UUID]
    # Immutable originating request version; current request advances independently.
    request_version_id: Mapped[UUID]
    request_revision: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    previous_run_version_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    writer_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    operation: Mapped[str] = mapped_column(String(80))
    run_snapshot: Mapped[dict] = mapped_column(JSONB)
    execution_plan: Mapped[dict] = mapped_column(JSONB)
    plan_sha256: Mapped[str] = mapped_column(String(64))
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    intent_digest: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "request_id", "run_id", "revision"),
        UniqueConstraint("tenant_id", "product_id", "request_id", "run_id", "id", "revision"),
        identity_fk(),
        request_fk(project=True),
        version_fk("previous_run_version_id", "previous_revision"),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(["tenant_id", "writer_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("build_revision > 0 AND request_revision > 0 AND revision > 0"),
        CheckConstraint(
            "visibility IN ('private','category','audience') AND "
            "status IN ('planned','running','results_pending','reviewed','disposed')"
        ),
        CheckConstraint(
            "operation IN ('test.run.plan','test.run.start','test.results.import',"
            "'test.run.review','test.disposition.decide')"
        ),
        CheckConstraint(
            "(revision = 1 AND status = 'planned' AND previous_run_version_id IS NULL "
            "AND previous_revision IS NULL) OR (revision = 2 AND status = 'running' "
            "AND previous_run_version_id IS NOT NULL AND previous_revision = 1) OR "
            "(revision >= 3 AND previous_run_version_id IS NOT NULL "
            "AND previous_revision = revision - 1 "
            "AND operation IN ('test.results.import','test.run.review','test.disposition.decide'))"
        ),
    )


class VerificationRunCurrent(Row, Base):
    __tablename__ = "verification_current_runs"
    product_id: Mapped[UUID]
    request_id: Mapped[UUID]
    run_id: Mapped[UUID]
    run_version_id: Mapped[UUID]
    run_revision: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        Index("ix_verification_current_runs_request", "tenant_id", "product_id", "request_id"),
        UniqueConstraint("tenant_id", "product_id", "run_id"),
        version_fk(),
        CheckConstraint("run_revision > 0"),
    )


class VerificationLaunchFact(Row, Base):
    __tablename__ = "verification_launch_facts"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    request_id: Mapped[UUID]
    request_version_id: Mapped[UUID]
    request_revision: Mapped[int] = mapped_column(Integer)
    next_request_version_id: Mapped[UUID]
    next_request_revision: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[UUID]
    run_version_id: Mapped[UUID]
    run_revision: Mapped[int] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16))
    operation: Mapped[str] = mapped_column(String(80))
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    kernel_event: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    intent_digest: Mapped[str] = mapped_column(String(64))
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "operation", "run_id"),
        identity_fk(),
        request_fk(project=True),
        version_fk(),
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
                f"verification_formal_requests.{name}"
                for name in (
                    "tenant_id",
                    "product_id",
                    "project_id",
                    "request_id",
                    "id",
                    "revision",
                )
            ],
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("revision = 1 AND request_revision > 0 AND run_revision > 0"),
        CheckConstraint("visibility IN ('private','category','audience')"),
        CheckConstraint(
            "operation IN ('test.run.plan','verification.schedule.promise','test.run.start')"
        ),
    )
