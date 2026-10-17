"""Host-published release policy facts; declarations grant no qualification."""

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

TABLE = "release_policy_facts"
CURRENT = "release_policy_currents"
OPERATION = "release.policy.import"
EVENT = "release.policy_imported"
SUBJECT = "release_policy_fact"
SCOPE = ("tenant_id", "category_id", "product_id", "project_id")
BINDING = (*SCOPE, "purpose_sha256", "series_id", "owner_id", "visibility")


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
        CheckConstraint("revision>0 AND epoch=revision"),
        CheckConstraint("purpose_sha256 ~ '^[a-f0-9]{64}$'"),
    )


class ReleasePolicyFact(Row, Base):
    __tablename__ = TABLE
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    series_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    epoch: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    writer_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    requester_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(Text)
    purpose_sha256: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    nature: Mapped[str] = mapped_column(String(16))
    operation: Mapped[str] = mapped_column(String(80), default=OPERATION)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    material: Mapped[dict] = mapped_column(JSONB)
    material_sha256: Mapped[str] = mapped_column(String(64))
    source: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    intent_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    fact_sha256: Mapped[str] = mapped_column(String(64))
    command_id: Mapped[UUID]
    receipt_id: Mapped[UUID]
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "project_id", "purpose_sha256", "revision"),
        UniqueConstraint(*BINDING, "id", "revision"),
        UniqueConstraint(*BINDING, "id", "revision", "epoch"),
        UniqueConstraint("tenant_id", "receipt_id"),
        UniqueConstraint("tenant_id", "command_id"),
        UniqueConstraint("tenant_id", "product_id", "actor_id", "operation", "intent_digest"),
        _fk(
            (*BINDING, "previous_id", "previous_revision"),
            TABLE,
            (*BINDING, "id", "revision"),
            deferrable=True,
            initially="DEFERRED",
        ),
        *(
            _fk(("tenant_id", field), "principals", ("tenant_id", "id"))
            for field in ("writer_id", "actor_id", "requester_id")
        ),
        _fk(
            ("tenant_id", "receipt_id"),
            "action_receipts",
            ("tenant_id", "id"),
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "(revision=1 AND epoch=1 AND series_id=id AND previous_id IS NULL "
            "AND previous_revision IS NULL) OR (revision>1 AND previous_id IS NOT NULL "
            "AND previous_id<>id AND previous_revision>0 AND revision=previous_revision+1)"
        ),
        CheckConstraint(f"operation='{OPERATION}' AND status IN ('active','withdrawn')"),
        CheckConstraint("nature IN ('real','synthetic')"),
        CheckConstraint("writer_id=actor_id AND actor_id=requester_id"),
        CheckConstraint("valid_from IS NULL OR valid_until IS NULL OR valid_from<valid_until"),
        CheckConstraint("length(purpose)>0 AND length(policy_version)>0"),
        CheckConstraint(
            "jsonb_typeof(material)='object' AND jsonb_typeof(source)='object' "
            "AND jsonb_typeof(source_basis)='object' AND jsonb_typeof(authority_snapshot)='object' "
            "AND jsonb_typeof(input_snapshot)='object' "
            "AND jsonb_typeof(sources)='array' AND jsonb_array_length(sources)>0 "
            "AND jsonb_typeof(required_source_read_set)='array' "
            "AND jsonb_array_length(required_source_read_set)>0"
        ),
        CheckConstraint(
            "material_sha256 ~ '^[a-f0-9]{64}$' AND fact_sha256 ~ '^[a-f0-9]{64}$' "
            "AND intent_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$'"
        ),
    )


class ReleasePolicyCurrent(Row, Base):
    __tablename__ = CURRENT
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    purpose_sha256: Mapped[str] = mapped_column(String(64))
    series_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    fact_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    epoch: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "product_id", "project_id", "purpose_sha256"),
        _fk(
            (*BINDING, "fact_id", "revision", "epoch"),
            TABLE,
            (*BINDING, "id", "revision", "epoch"),
        ),
    )
