"""Release ledgers, declared without installing or granting release authority.

Packages fix the assembled evidence. Engineering and manufacturing decisions are
separate named T2 records for one exact package; neither record rewrites it.
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

from .constants import ASSEMBLE, ENGINEERING_APPROVE, MANUFACTURING_APPROVE

TABLE = "release_packages"
CURRENT = "release_package_currents"
DECISION = "release_decisions"
SCOPE = ("tenant_id", "category_id", "product_id", "project_id")
BINDING = (*SCOPE, "series_id", "owner_id", "visibility")
FIXED = (*SCOPE, "id", "revision", "visibility")


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
        CheckConstraint("visibility IN ('private','category','audience')"),
    )


def _common():
    return (
        *_scope(),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "id", "revision"),
        UniqueConstraint("tenant_id", "receipt_id"),
        UniqueConstraint("tenant_id", "command_id"),
        UniqueConstraint("tenant_id", "product_id", "actor_id", "operation", "intent_digest"),
        *(
            _fk(("tenant_id", field), "principals", ("tenant_id", "id"))
            for field in ("owner_id", "writer_id", "actor_id", "requester_id")
        ),
        _fk(
            ("tenant_id", "receipt_id"),
            "action_receipts",
            ("tenant_id", "id"),
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("writer_id=actor_id"),
        CheckConstraint(
            "jsonb_typeof(body)='object' AND jsonb_typeof(material_snapshot)='object' "
            "AND jsonb_typeof(input_snapshot)='object' AND jsonb_typeof(source_basis)='object' "
            "AND jsonb_typeof(required_source_read_set)='array' "
            "AND jsonb_array_length(required_source_read_set)>0 "
            "AND jsonb_typeof(sources)='array' AND jsonb_array_length(sources)>0"
        ),
        CheckConstraint(
            "body_sha256 ~ '^[a-f0-9]{64}$' AND intent_digest ~ '^[a-f0-9]{64}$' "
            "AND request_digest ~ '^[a-f0-9]{64}$'"
        ),
    )


class _Recorded(Row):
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    writer_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    requester_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(Text)
    body: Mapped[dict] = mapped_column(JSONB)
    body_sha256: Mapped[str] = mapped_column(String(64))
    material_snapshot: Mapped[dict] = mapped_column(JSONB)
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    command_id: Mapped[UUID]
    receipt_id: Mapped[UUID]
    intent_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))


class ReleasePackage(_Recorded, Base):
    __tablename__ = TABLE
    series_id: Mapped[UUID]
    previous_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="assembled")
    operation: Mapped[str] = mapped_column(String(80), default=ASSEMBLE)
    write_tier: Mapped[str] = mapped_column(String(4), default="T0")
    __table_args__ = (
        *_common(),
        UniqueConstraint(*SCOPE, "series_id", "revision"),
        UniqueConstraint(*BINDING, "id", "revision"),
        UniqueConstraint(*FIXED),
        _fk(
            (*BINDING, "previous_id", "previous_revision"),
            TABLE,
            (*BINDING, "id", "revision"),
        ),
        CheckConstraint(f"operation='{ASSEMBLE}' AND write_tier='T0' AND status='assembled'"),
        CheckConstraint(
            "(revision=1 AND series_id=id AND previous_id IS NULL AND previous_revision IS NULL) "
            "OR (revision>1 AND previous_id IS NOT NULL AND previous_id<>id "
            "AND previous_revision>0 AND revision=previous_revision+1)"
        ),
    )


class ReleasePackageCurrent(Row, Base):
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
        CheckConstraint("revision>0 AND epoch=revision"),
    )


class ReleaseDecision(_Recorded, Base):
    __tablename__ = DECISION
    package_id: Mapped[UUID]
    package_revision: Mapped[int] = mapped_column(Integer)
    discipline: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="approved")
    operation: Mapped[str] = mapped_column(String(80))
    write_tier: Mapped[str] = mapped_column(String(4), default="T2")
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    shared_proof_id: Mapped[UUID]
    shared_proof_revision: Mapped[int] = mapped_column(Integer)
    proof_consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    proof_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_sha256: Mapped[str] = mapped_column(String(64))
    material_sha256: Mapped[str] = mapped_column(String(64))
    read_set_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        *_common(),
        UniqueConstraint(*SCOPE, "package_id", "package_revision", "discipline"),
        UniqueConstraint("tenant_id", "shared_proof_id"),
        _fk(
            (*SCOPE, "package_id", "package_revision", "visibility"),
            TABLE,
            FIXED,
        ),
        _fk(
            ("tenant_id", "shared_proof_id"),
            "confirmations",
            ("tenant_id", "id"),
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("revision=1 AND package_revision>0 AND shared_proof_revision>0"),
        CheckConstraint("actor_id=requester_id AND writer_id=actor_id AND owner_id=requester_id"),
        CheckConstraint("write_tier='T2' AND status='approved'"),
        CheckConstraint(
            f"(discipline='engineering' AND operation='{ENGINEERING_APPROVE}') OR "
            f"(discipline='manufacturing' AND operation='{MANUFACTURING_APPROVE}')"
        ),
        CheckConstraint(
            "proof_consumed_at<=created_at AND "
            "(proof_expires_at IS NULL OR created_at<proof_expires_at)"
        ),
        CheckConstraint(
            "token_sha256 ~ '^[a-f0-9]{64}$' AND material_sha256 ~ '^[a-f0-9]{64}$' "
            "AND read_set_sha256 ~ '^[a-f0-9]{64}$'"
        ),
    )
