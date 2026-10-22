"""One immutable version ledger / one Current for each new preparation series.

ProcessRevision and its existing revision chain are never updated or duplicated.
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

TABLE = "manufacturing_preparation_versions"
CURRENT = "manufacturing_preparation_currents"
LINK = "manufacturing_baseline_document_links"
BINDING = ("tenant_id", "product_id", "project_id", "kind", "series_id", "owner_id", "visibility")
FIXED = (
    "tenant_id",
    "product_id",
    "project_id",
    "kind",
    "id",
    "revision",
    "process_id",
    "process_revision",
)


def fk(local, table, remote, **kwargs):
    return ForeignKeyConstraint(local, [f"{table}.{v}" for v in remote], **kwargs)


class PreparationVersion(Row, Base):
    __tablename__ = TABLE
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(32))
    series_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(12))
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    process_id: Mapped[UUID]
    process_revision: Mapped[int] = mapped_column(Integer)
    operation_key: Mapped[str | None] = mapped_column(String(80))
    purpose: Mapped[str] = mapped_column(Text)
    purpose_sha256: Mapped[str] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(String(80))
    intent_digest: Mapped[str] = mapped_column(String(64))
    body: Mapped[dict] = mapped_column(JSONB)
    body_sha256: Mapped[str] = mapped_column(String(64))
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    review: Mapped[dict] = mapped_column(JSONB)
    shared_proof_id: Mapped[UUID]
    shared_proof_revision: Mapped[int] = mapped_column(Integer)
    proof_consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    proof_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    token_sha256: Mapped[str] = mapped_column(String(64))
    material_sha256: Mapped[str] = mapped_column(String(64))
    read_set_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "shared_proof_id"),
        UniqueConstraint("tenant_id", "product_id", "id", "revision"),
        UniqueConstraint(*BINDING, "id", "revision"),
        UniqueConstraint(*FIXED),
        UniqueConstraint(*FIXED, "operation_key"),
        UniqueConstraint("tenant_id", "product_id", "project_id", "kind", "series_id", "revision"),
        UniqueConstraint("tenant_id", "product_id", "owner_id", "operation", "intent_digest"),
        fk(["tenant_id", "product_id"], "products", ["tenant_id", "id"]),
        fk(
            ["tenant_id", "product_id", "project_id"], "projects", ["tenant_id", "product_id", "id"]
        ),
        fk(["tenant_id", "owner_id"], "principals", ["tenant_id", "id"]),
        fk(
            ["tenant_id", "product_id", "process_id", "process_revision"],
            "process_revisions",
            ["tenant_id", "product_id", "id", "revision"],
        ),
        fk([*BINDING, "previous_id", "previous_revision"], TABLE, [*BINDING, "id", "revision"]),
        fk(["tenant_id", "shared_proof_id"], "confirmations", ["tenant_id", "id"]),
        CheckConstraint(
            "kind IN ('work_instruction','control_plan','manufacturing_baseline') "
            "AND status='draft'"
        ),
        CheckConstraint(
            "visibility IN ('private','category','audience') AND "
            "process_revision>0 AND shared_proof_revision>0"
        ),
        CheckConstraint(
            "(kind='manufacturing_baseline' AND operation_key IS NULL) OR "
            "(kind IN ('work_instruction','control_plan') AND operation_key IS NOT NULL)"
        ),
        CheckConstraint(
            "(previous_id IS NULL AND previous_revision IS NULL "
            "AND revision=1 AND series_id=id) OR "
            "(previous_id IS NOT NULL AND previous_id<>id AND previous_revision>0 "
            "AND revision=previous_revision+1)"
        ),
        CheckConstraint(
            "(kind='work_instruction' AND operation='npi.work_instruction.record') OR "
            "(kind='control_plan' AND operation='npi.control_plan.record') OR "
            "(kind='manufacturing_baseline' AND operation='npi.manufacturing_baseline.record')"
        ),
        CheckConstraint("proof_consumed_at<proof_expires_at"),
        CheckConstraint(
            "body_sha256 ~ '^[a-f0-9]{64}$' AND intent_digest ~ '^[a-f0-9]{64}$' "
            "AND purpose_sha256 ~ '^[a-f0-9]{64}$' AND token_sha256 ~ '^[a-f0-9]{64}$' "
            "AND material_sha256 ~ '^[a-f0-9]{64}$' AND read_set_sha256 ~ '^[a-f0-9]{64}$'"
        ),
    )


class PreparationCurrent(Row, Base):
    __tablename__ = CURRENT
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(32))
    series_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(12))
    version_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "project_id", "kind", "series_id"),
        fk([*BINDING, "version_id", "revision"], TABLE, [*BINDING, "id", "revision"]),
        CheckConstraint("revision>0"),
    )


class BaselineDocumentLink(Row, Base):
    __tablename__ = LINK
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    baseline_kind: Mapped[str] = mapped_column(String(32), default="manufacturing_baseline")
    baseline_id: Mapped[UUID]
    baseline_revision: Mapped[int] = mapped_column(Integer)
    process_id: Mapped[UUID]
    process_revision: Mapped[int] = mapped_column(Integer)
    operation_key: Mapped[str] = mapped_column(String(80))
    document_kind: Mapped[str] = mapped_column(String(32))
    document_id: Mapped[UUID]
    document_revision: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "product_id", "baseline_id", "operation_key", "document_kind"
        ),
        fk(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "baseline_kind",
                "baseline_id",
                "baseline_revision",
                "process_id",
                "process_revision",
            ],
            TABLE,
            list(FIXED),
        ),
        fk(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "document_kind",
                "document_id",
                "document_revision",
                "process_id",
                "process_revision",
                "operation_key",
            ],
            TABLE,
            [*FIXED, "operation_key"],
        ),
        CheckConstraint(
            "baseline_kind='manufacturing_baseline' "
            "AND document_kind IN ('work_instruction','control_plan')"
        ),
        CheckConstraint("baseline_revision>0 AND document_revision>0 AND process_revision>0"),
    )
