"""Uninstalled native Pilot roots, mutable heads and immutable observations.

These declarations do not register tables, authorize a start or grant factory
qualification. Actual owners, common-consumption atoms, append-only/CAS/RLS and
the cyclic Current/observation guards must be integrated by the trusted host.
Original roots remain revision one after every observation or correction.
"""

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

from pdos_next.domain.manufacturing_baseline.publication_models import FIXED as PUBLICATION_FIXED
from pdos_next.domain.manufacturing_baseline.publication_models import TABLE as PUBLICATION_TABLE
from pdos_next.models import Base, Row

from .native_schemas import CREATE_OPERATION, RESULT_OPERATION

TABLE = "native_pilot_runs"
CURRENT = "native_pilot_currents"
OBSERVATION = "native_pilot_observations"
SCOPE = ("tenant_id", "category_id", "product_id", "project_id")
BINDING = (*SCOPE, "owner_id", "visibility")


def _fk(local, table, remote, **options):
    return ForeignKeyConstraint(list(local), [f"{table}.{key}" for key in remote], **options)


def _scope():
    return (
        _fk(
            ("tenant_id", "category_id", "product_id"),
            "products",
            ("tenant_id", "category_id", "id"),
        ),
        _fk(
            ("tenant_id", "product_id", "project_id"),
            "projects",
            ("tenant_id", "product_id", "id"),
        ),
        _fk(("tenant_id", "owner_id"), "principals", ("tenant_id", "id")),
        CheckConstraint("visibility IN ('private','category','audience')"),
    )


def _common(operation):
    return (
        UniqueConstraint("tenant_id", "shared_proof_id"),
        UniqueConstraint("tenant_id", "receipt_id"),
        UniqueConstraint("tenant_id", "command_id"),
        UniqueConstraint("tenant_id", "product_id", "actor_id", "operation", "intent_digest"),
        *(
            _fk(("tenant_id", key), "principals", ("tenant_id", "id"))
            for key in ("writer_id", "actor_id", "requester_id")
        ),
        _fk(
            ("tenant_id", "shared_proof_id"),
            "confirmations",
            ("tenant_id", "id"),
            deferrable=True,
            initially="DEFERRED",
        ),
        _fk(
            ("tenant_id", "receipt_id"),
            "action_receipts",
            ("tenant_id", "id"),
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(f"operation='{operation}' AND write_tier='T1' AND status='recorded'"),
        CheckConstraint("actor_id=requester_id AND writer_id=actor_id"),
        CheckConstraint("shared_proof_revision>0"),
        CheckConstraint("proof_consumed_at<=created_at AND created_at<proof_expires_at"),
        CheckConstraint(
            "jsonb_typeof(required_source_read_set)='array' "
            "AND jsonb_array_length(required_source_read_set)>0 "
            "AND jsonb_typeof(sources)='array' AND jsonb_array_length(sources)>0"
        ),
        CheckConstraint(
            "payload_sha256 ~ '^[a-f0-9]{64}$' AND token_sha256 ~ '^[a-f0-9]{64}$' "
            "AND material_sha256 ~ '^[a-f0-9]{64}$' AND read_set_sha256 ~ '^[a-f0-9]{64}$' "
            "AND intent_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$'"
        ),
    )


class _Confirmed(Row):
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    writer_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    requester_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="recorded")
    write_tier: Mapped[str] = mapped_column(String(4), default="T1")
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    material_snapshot: Mapped[dict] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    gaps: Mapped[list] = mapped_column(JSONB)
    command_id: Mapped[UUID]
    receipt_id: Mapped[UUID]
    shared_proof_id: Mapped[UUID]
    shared_proof_revision: Mapped[int] = mapped_column(Integer)
    proof_consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    proof_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    token_sha256: Mapped[str] = mapped_column(String(64))
    material_sha256: Mapped[str] = mapped_column(String(64))
    read_set_sha256: Mapped[str] = mapped_column(String(64))
    intent_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))


class NativePilotRun(_Confirmed, Base):
    __tablename__ = TABLE
    revision: Mapped[int] = mapped_column(Integer, default=1)
    operation: Mapped[str] = mapped_column(String(80), default=CREATE_OPERATION)
    purpose: Mapped[str] = mapped_column(Text)
    build_id: Mapped[UUID]
    build_revision: Mapped[int] = mapped_column(Integer)
    lot_id: Mapped[UUID]
    lot_revision: Mapped[int] = mapped_column(Integer)
    actual_configuration_id: Mapped[UUID]
    actual_configuration_revision: Mapped[int] = mapped_column(Integer)
    engineering_configuration_id: Mapped[UUID]
    engineering_revision: Mapped[int] = mapped_column(Integer)
    process_id: Mapped[UUID]
    process_revision: Mapped[int] = mapped_column(Integer)
    publication_id: Mapped[UUID | None]
    publication_revision: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict] = mapped_column(JSONB)
    statistics_basis: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    __table_args__ = (
        *_scope(),
        *_common(CREATE_OPERATION),
        UniqueConstraint("tenant_id", "product_id", "id", "revision"),
        UniqueConstraint(*SCOPE, "id"),
        UniqueConstraint(*BINDING, "id"),
        _fk(
            ("tenant_id", "product_id", "project_id", "build_id"),
            "builds",
            ("tenant_id", "product_id", "project_id", "id"),
        ),
        _fk(
            (
                "tenant_id",
                "product_id",
                "project_id",
                "build_id",
                "lot_id",
                "actual_configuration_id",
            ),
            "build_lots",
            ("tenant_id", "product_id", "project_id", "build_id", "id", "actual_configuration_id"),
        ),
        _fk(
            ("tenant_id", "product_id", "project_id", "build_id", "actual_configuration_id"),
            "actual_configurations",
            ("tenant_id", "product_id", "project_id", "build_id", "id"),
        ),
        _fk(
            ("tenant_id", "product_id", "engineering_configuration_id", "engineering_revision"),
            "engineering_configurations",
            ("tenant_id", "product_id", "id", "revision"),
        ),
        _fk(
            ("tenant_id", "product_id", "process_id", "process_revision"),
            "process_revisions",
            ("tenant_id", "product_id", "id", "revision"),
        ),
        _fk(
            ("tenant_id", "product_id", "engineering_configuration_id", "process_id"),
            "process_revisions",
            ("tenant_id", "product_id", "engineering_configuration_id", "id"),
        ),
        _fk(
            (*SCOPE, "publication_id", "publication_revision", "process_id", "process_revision"),
            PUBLICATION_TABLE,
            PUBLICATION_FIXED,
        ),
        CheckConstraint("revision=1 AND build_revision>0"),
        CheckConstraint("lot_revision=1 AND actual_configuration_revision=1"),
        CheckConstraint("engineering_revision>0 AND process_revision>0"),
        CheckConstraint(
            "(publication_id IS NULL AND publication_revision IS NULL) OR "
            "(publication_id IS NOT NULL AND publication_revision>0)"
        ),
    )


class NativePilotCurrent(Row, Base):
    __tablename__ = CURRENT
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    pilot_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    latest_observation_id: Mapped[UUID | None]
    epoch: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        *_scope(),
        UniqueConstraint(*SCOPE, "pilot_id"),
        _fk((*BINDING, "pilot_id"), TABLE, (*BINDING, "id")),
        _fk(
            (*BINDING, "pilot_id", "latest_observation_id", "revision"),
            OBSERVATION,
            (*BINDING, "pilot_id", "id", "revision"),
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
            name="fk_native_pilot_current_observation",
        ),
        CheckConstraint(
            "(revision=1 AND epoch=1 AND latest_observation_id IS NULL) OR "
            "(revision>1 AND epoch=revision AND latest_observation_id IS NOT NULL)"
        ),
    )


class NativePilotObservation(_Confirmed, Base):
    __tablename__ = OBSERVATION
    pilot_id: Mapped[UUID]
    pilot_revision_before: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    previous_observation_id: Mapped[UUID | None]
    operation: Mapped[str] = mapped_column(String(80), default=RESULT_OPERATION)
    record: Mapped[dict] = mapped_column(JSONB)
    fixed_scope: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    projection: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    __table_args__ = (
        *_scope(),
        *_common(RESULT_OPERATION),
        UniqueConstraint("tenant_id", "product_id", "id", "revision"),
        UniqueConstraint(*SCOPE, "pilot_id", "revision"),
        UniqueConstraint(*BINDING, "pilot_id", "id", "revision"),
        _fk((*BINDING, "pilot_id"), TABLE, (*BINDING, "id")),
        _fk(
            (*BINDING, "pilot_id", "previous_observation_id", "pilot_revision_before"),
            OBSERVATION,
            (*BINDING, "pilot_id", "id", "revision"),
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("pilot_revision_before>0 AND revision=pilot_revision_before+1"),
        CheckConstraint(
            "(pilot_revision_before=1 AND previous_observation_id IS NULL) OR "
            "(pilot_revision_before>1 AND previous_observation_id IS NOT NULL "
            "AND previous_observation_id<>id)"
        ),
    )
