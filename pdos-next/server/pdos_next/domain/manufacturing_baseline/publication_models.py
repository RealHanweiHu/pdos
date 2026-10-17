"""Uninstalled publication ledger, pointer and exact document links.

Importing these declarations does not install schema, RLS, append-only/CAS or
reciprocal common receipt guards. Root must integrate all of those with the
actual owner. Existing preparation rows remain immutable draft records.
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

from pdos_next.models import Base, Row

from .models import FIXED as PREPARATION_FIXED
from .models import TABLE as PREPARATION_TABLE
from .publication_schemas import OPERATION

TABLE = "manufacturing_baseline_publications"
CURRENT = "manufacturing_publication_currents"
LINK = "manufacturing_publication_documents"
SCOPE = ("tenant_id", "category_id", "product_id", "project_id")
BINDING = (*SCOPE, "series_id", "owner_id", "visibility")
FIXED = (*SCOPE, "id", "revision", "process_id", "process_revision")


def _fk(local, table, remote, **options):
    return ForeignKeyConstraint(list(local), [f"{table}.{v}" for v in remote], **options)


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
    )


class ManufacturingBaselinePublication(Row, Base):
    __tablename__ = TABLE
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    series_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    writer_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    requester_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(Text)
    baseline_kind: Mapped[str] = mapped_column(String(32), default="manufacturing_baseline")
    baseline_id: Mapped[UUID]
    baseline_revision: Mapped[int] = mapped_column(Integer)
    process_id: Mapped[UUID]
    process_revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="published")
    operation: Mapped[str] = mapped_column(String(80), default=OPERATION)
    write_tier: Mapped[str] = mapped_column(String(4), default="T2")
    body: Mapped[dict] = mapped_column(JSONB)
    body_sha256: Mapped[str] = mapped_column(String(64))
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    gaps: Mapped[list] = mapped_column(JSONB)
    command_id: Mapped[UUID]
    receipt_id: Mapped[UUID]
    shared_proof_id: Mapped[UUID]
    shared_proof_revision: Mapped[int] = mapped_column(Integer)
    proof_consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    proof_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_sha256: Mapped[str] = mapped_column(String(64))
    material_sha256: Mapped[str] = mapped_column(String(64))
    read_set_sha256: Mapped[str] = mapped_column(String(64))
    intent_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "product_id", "id", "revision"),
        UniqueConstraint(*SCOPE, "series_id", "revision"),
        UniqueConstraint(*BINDING, "id", "revision"),
        UniqueConstraint(*FIXED),
        UniqueConstraint("tenant_id", "shared_proof_id"),
        UniqueConstraint("tenant_id", "receipt_id"),
        UniqueConstraint("tenant_id", "command_id"),
        UniqueConstraint("tenant_id", "product_id", "actor_id", "operation", "intent_digest"),
        _fk(
            (*BINDING, "previous_id", "previous_revision"),
            TABLE,
            (*BINDING, "id", "revision"),
        ),
        _fk(
            (
                "tenant_id",
                "product_id",
                "project_id",
                "baseline_kind",
                "baseline_id",
                "baseline_revision",
                "process_id",
                "process_revision",
            ),
            PREPARATION_TABLE,
            PREPARATION_FIXED,
        ),
        *(
            _fk(("tenant_id", field), "principals", ("tenant_id", "id"))
            for field in ("owner_id", "writer_id", "actor_id", "requester_id")
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
        CheckConstraint(f"operation='{OPERATION}' AND write_tier='T2' AND status='published'"),
        CheckConstraint("baseline_kind='manufacturing_baseline'"),
        CheckConstraint("visibility IN ('private','category','audience')"),
        CheckConstraint("actor_id=requester_id AND writer_id=actor_id"),
        CheckConstraint("baseline_revision>0 AND process_revision>0 AND shared_proof_revision>0"),
        CheckConstraint(
            "(revision=1 AND series_id=id AND previous_id IS NULL AND previous_revision IS NULL) "
            "OR (revision>1 AND previous_id IS NOT NULL AND previous_id<>id "
            "AND previous_revision>0 AND revision=previous_revision+1)"
        ),
        CheckConstraint(
            "proof_consumed_at<=created_at AND "
            "(proof_expires_at IS NULL OR created_at<proof_expires_at)"
        ),
        CheckConstraint(
            "jsonb_typeof(required_source_read_set)='array' "
            "AND jsonb_array_length(required_source_read_set)>0 "
            "AND jsonb_typeof(sources)='array' AND jsonb_array_length(sources)>0"
        ),
        CheckConstraint(
            "COALESCE(body->>'qualification'='unknown',false) "
            "AND COALESCE(body->'manufacturing_release'='null'::jsonb,false)"
        ),
        CheckConstraint(
            "body_sha256 ~ '^[a-f0-9]{64}$' AND payload_sha256 ~ '^[a-f0-9]{64}$' "
            "AND token_sha256 ~ '^[a-f0-9]{64}$' AND material_sha256 ~ '^[a-f0-9]{64}$' "
            "AND read_set_sha256 ~ '^[a-f0-9]{64}$' AND intent_digest ~ '^[a-f0-9]{64}$' "
            "AND request_digest ~ '^[a-f0-9]{64}$'"
        ),
    )


class ManufacturingBaselinePublicationCurrent(Row, Base):
    __tablename__ = CURRENT
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    series_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    version_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    epoch: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        *_scope(),
        UniqueConstraint(*SCOPE, "series_id"),
        _fk((*BINDING, "version_id", "revision"), TABLE, (*BINDING, "id", "revision")),
        CheckConstraint("revision>0 AND epoch>0"),
    )


class ManufacturingPublicationDocument(Row, Base):
    __tablename__ = LINK
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    publication_id: Mapped[UUID]
    publication_revision: Mapped[int] = mapped_column(Integer)
    process_id: Mapped[UUID]
    process_revision: Mapped[int] = mapped_column(Integer)
    operation_key: Mapped[str] = mapped_column(String(80))
    document_kind: Mapped[str] = mapped_column(String(32))
    document_id: Mapped[UUID]
    document_revision: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint(*SCOPE, "publication_id", "operation_key", "document_kind"),
        _fk(
            (*SCOPE, "publication_id", "publication_revision", "process_id", "process_revision"),
            TABLE,
            FIXED,
        ),
        _fk(
            (
                "tenant_id",
                "product_id",
                "project_id",
                "document_kind",
                "document_id",
                "document_revision",
                "process_id",
                "process_revision",
                "operation_key",
            ),
            PREPARATION_TABLE,
            (*PREPARATION_FIXED, "operation_key"),
        ),
        CheckConstraint("document_kind IN ('work_instruction','control_plan')"),
        CheckConstraint("publication_revision>0 AND document_revision>0 AND process_revision>0"),
    )
