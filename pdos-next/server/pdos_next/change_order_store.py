"""Candidate append-only atoms; reuse ChangeCurrent, never a second truth chain."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.change_command_schemas import (  # noqa: E402,F401
    CaptureInput,
    ControlledPolicy,
    ImplementationPayload,
    OrderApprovePayload,
    OrderPreparePayload,
    SelectionProof,
    Target,
)
from pdos_next.models import Base, Row

BOUND = ("tenant_id", "product_id", "project_id", "change_id")
PARENT = (*BOUND, "change_version_id", "change_revision")


def parent_fk():
    return ForeignKeyConstraint(
        PARENT,
        (
            *[f"change_request_versions.{v}" for v in BOUND],
            "change_request_versions.id",
            "change_request_versions.revision",
        ),
        deferrable=True,
        initially="DEFERRED",
    )


def shared_constraints(operation):
    return (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint(*PARENT),
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "shared_proof_id"],
            ["confirmations.tenant_id", "confirmations.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        parent_fk(),
        CheckConstraint(f"operation = '{operation}'"),
        CheckConstraint("revision = 1 AND change_revision > 1 AND shared_proof_revision > 0"),
        CheckConstraint("visibility IN ('private','category','audience')"),
        CheckConstraint(
            "proof_consumed_at <= created_at AND "
            + (
                "(proof_expires_at IS NULL OR created_at < proof_expires_at)"
                if operation == "change.order.approve"
                else "proof_expires_at IS NOT NULL AND created_at < proof_expires_at"
            )
        ),
        CheckConstraint("jsonb_array_length(required_source_read_set)>0"),
    )


class _Atom(Row):
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    change_id: Mapped[UUID]
    change_version_id: Mapped[UUID]
    change_revision: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[UUID]
    operation: Mapped[str] = mapped_column(String(80))
    command_id: Mapped[UUID]
    intent_digest: Mapped[str] = mapped_column(String(64))
    shared_proof_id: Mapped[UUID]
    shared_proof_revision: Mapped[int] = mapped_column(Integer)
    proof_consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    proof_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_sha256: Mapped[str] = mapped_column(String(64))
    material_sha256: Mapped[str] = mapped_column(String(64))
    read_set_sha256: Mapped[str] = mapped_column(String(64))
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    policy_snapshot: Mapped[dict] = mapped_column(JSONB)
    input_snapshot: Mapped[dict] = mapped_column(JSONB)


class ChangeOrderRecord(_Atom, Base):
    __tablename__ = "change_order_records"
    proof_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    order_id: Mapped[UUID]
    content_sha256: Mapped[str] = mapped_column(String(64))
    order_snapshot: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        *shared_constraints("change.order.prepare"),
        UniqueConstraint(*BOUND, "order_id"),
        UniqueConstraint(*BOUND, "order_id", "id"),
    )


class ChangeApprovalRecord(_Atom, Base):
    __tablename__ = "change_approval_records"
    order_id: Mapped[UUID]
    order_record_id: Mapped[UUID]
    discipline: Mapped[str] = mapped_column(String(24))
    approval_snapshot: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        *shared_constraints("change.order.approve"),
        UniqueConstraint(*BOUND, "order_id", "discipline"),
        ForeignKeyConstraint(
            [*BOUND, "order_id", "order_record_id"],
            [
                *[f"change_order_records.{v}" for v in BOUND],
                "change_order_records.order_id",
                "change_order_records.id",
            ],
        ),
        CheckConstraint(
            "discipline IN ('engineering','manufacturing','quality','customer','regulatory')"
        ),
        CheckConstraint(
            "(approval_snapshot->>'decision_id')::uuid = shared_proof_id "
            "AND (approval_snapshot->>'actor_id')::uuid = actor_id"
        ),
    )


class ImplementationCapture(Row, Base):
    __tablename__ = "change_implementation_captures"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    change_id: Mapped[UUID]
    change_version_id: Mapped[UUID]
    change_revision: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    executor_id: Mapped[UUID]
    order_id: Mapped[UUID]
    item_id: Mapped[UUID]
    fact_id: Mapped[UUID]
    capture_key: Mapped[str] = mapped_column(String(160))
    input_digest: Mapped[str] = mapped_column(String(64))
    fact_snapshot: Mapped[dict] = mapped_column(JSONB)
    occurrence_snapshot: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    output_basis: Mapped[dict] = mapped_column(JSONB)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint(*BOUND, "fact_id"),
        UniqueConstraint("tenant_id", "product_id", "executor_id", "capture_key"),
        UniqueConstraint(*BOUND, "order_id", "item_id", "fact_id", "id"),
        parent_fk(),
        ForeignKeyConstraint(
            ["tenant_id", "executor_id"], ["principals.tenant_id", "principals.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint(
            "revision = 1 AND visibility IN ('private','category','audience') AND "
            "change_revision > 0"
        ),
        CheckConstraint("expires_at IS NULL OR expires_at > created_at"),
        CheckConstraint("jsonb_array_length(required_source_read_set)>0"),
    )


class ChangeImplementationRecord(_Atom, Base):
    __tablename__ = "change_implementation_records"
    proof_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    order_id: Mapped[UUID]
    order_record_id: Mapped[UUID]
    item_id: Mapped[UUID]
    fact_id: Mapped[UUID]
    capture_id: Mapped[UUID]
    fact_snapshot: Mapped[dict] = mapped_column(JSONB)
    output_basis: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        *shared_constraints("change.implementation.record"),
        UniqueConstraint(*BOUND, "fact_id"),
        ForeignKeyConstraint(
            [*BOUND, "order_id", "order_record_id"],
            [
                *[f"change_order_records.{v}" for v in BOUND],
                "change_order_records.order_id",
                "change_order_records.id",
            ],
        ),
        ForeignKeyConstraint(
            [*BOUND, "order_id", "item_id", "fact_id", "capture_id"],
            [
                *[f"change_implementation_captures.{v}" for v in BOUND],
                "change_implementation_captures.order_id",
                "change_implementation_captures.item_id",
                "change_implementation_captures.fact_id",
                "change_implementation_captures.id",
            ],
        ),
    )


class ChangeCompletionRecord(_Atom, Base):
    """One common command's native fact or named closure, on the existing chain."""

    __tablename__ = "change_completion_records"
    order_id: Mapped[UUID]
    order_record_id: Mapped[UUID]
    item_id: Mapped[UUID | None]
    fact_id: Mapped[UUID]
    fact_snapshot: Mapped[dict] = mapped_column(JSONB)
    native_input: Mapped[dict] = mapped_column(JSONB)
    owner_basis: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint(*PARENT),
        UniqueConstraint(*BOUND, "operation", "fact_id"),
        parent_fk(),
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "shared_proof_id"],
            ["confirmations.tenant_id", "confirmations.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [*BOUND, "order_id", "order_record_id"],
            [
                *[f"change_order_records.{v}" for v in BOUND],
                "change_order_records.order_id",
                "change_order_records.id",
            ],
        ),
        CheckConstraint(
            "operation IN ('change.effectivity.record','change.verification.record','change.close')"
        ),
        CheckConstraint("revision = 1 AND change_revision > 1 AND shared_proof_revision > 0"),
        CheckConstraint("visibility IN ('private','category','audience')"),
        CheckConstraint(
            "proof_consumed_at <= created_at AND "
            "(proof_expires_at IS NULL OR created_at < proof_expires_at)"
        ),
        CheckConstraint(
            "operation <> 'change.effectivity.record' OR "
            "(proof_expires_at IS NOT NULL AND item_id IS NOT NULL)"
        ),
        CheckConstraint("operation = 'change.effectivity.record' OR item_id IS NULL"),
        CheckConstraint("jsonb_array_length(required_source_read_set)>0"),
    )
