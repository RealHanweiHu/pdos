"""Pinned category knowledge consumed by G0; authoring is a subsequent M3 slice."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row

from .models import category_fk, principal_fk


class KnowledgeEntry(Row, Base):
    __tablename__ = "category_knowledge_entries"
    category_id: Mapped[UUID] = mapped_column(index=True)
    lineage_id: Mapped[UUID]
    version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    content: Mapped[dict] = mapped_column(JSONB)
    regions: Mapped[list] = mapped_column(ARRAY(Text), default=list)
    source_refs: Mapped[list] = mapped_column(JSONB, default=list)
    withdraw_reason: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text)
    writer_id: Mapped[UUID]
    run_id: Mapped[UUID | None]
    confirmed_by: Mapped[UUID | None]
    receipt_id: Mapped[UUID | None]
    prepared_candidate_id: Mapped[UUID | None]
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "prepared_candidate_id"],
            ["proposal_prepared_candidates.tenant_id", "proposal_prepared_candidates.id"],
        ),
        category_fk(),
        principal_fk("writer_id"),
        principal_fk("confirmed_by"),
        UniqueConstraint("tenant_id", "category_id", "lineage_id", "version"),
        UniqueConstraint("tenant_id", "lineage_id", "version"),
        UniqueConstraint("tenant_id", "category_id", "id"),
        CheckConstraint("version>0 AND action IN ('add','supersede','withdraw')"),
        CheckConstraint(
            "kind IN ('boundary','segment','competitor','voice','regulation','research_question')"
        ),
        CheckConstraint("action<>'withdraw' OR length(withdraw_reason)>0"),
        CheckConstraint(
            "origin IN ('human','ai_draft','imported') "
            "AND (origin<>'ai_draft' OR run_id IS NOT NULL)"
        ),
    )


class KnowledgeCurrent(Base):
    __tablename__ = "category_knowledge_current"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    lineage_id: Mapped[UUID] = mapped_column(primary_key=True)
    category_id: Mapped[UUID] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(Text)
    current_entry_id: Mapped[UUID]
    current_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        category_fk(),
        Index(
            "ix_category_knowledge_current_scope_kind_status",
            "tenant_id",
            "category_id",
            "kind",
            "status",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "current_entry_id"],
            [
                "category_knowledge_entries.tenant_id",
                "category_knowledge_entries.category_id",
                "category_knowledge_entries.id",
            ],
        ),
        CheckConstraint("current_version>0 AND status IN ('active','withdrawn')"),
    )


class ProductTargetSegment(Row, Base):
    __tablename__ = "product_target_segments"
    category_id: Mapped[UUID] = mapped_column(index=True)
    product_id: Mapped[UUID]
    segment_lineage_id: Mapped[UUID]
    segment_version: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "product_id"],
            ["products.tenant_id", "products.category_id", "products.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "segment_lineage_id", "segment_version"],
            [
                "category_knowledge_entries.tenant_id",
                "category_knowledge_entries.category_id",
                "category_knowledge_entries.lineage_id",
                "category_knowledge_entries.version",
            ],
        ),
        UniqueConstraint("tenant_id", "product_id", "segment_lineage_id"),
        CheckConstraint("segment_version>0"),
    )


TABLES = (KnowledgeEntry.__table__, KnowledgeCurrent.__table__, ProductTargetSegment.__table__)


class ParameterVersion(Row, Base):
    __tablename__ = "parameter_versions"
    category_id: Mapped[UUID] = mapped_column(index=True)
    parameter_id: Mapped[UUID]
    version: Mapped[int]
    key: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(Text)
    enum_values: Mapped[list | None] = mapped_column(JSONB)
    unit: Mapped[str | None] = mapped_column(Text)
    standard_condition: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str | None] = mapped_column(Text)
    acceptance_criterion: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(Text)
    replaces_version: Mapped[int | None]
    change_note: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text)
    writer_id: Mapped[UUID]
    run_id: Mapped[UUID | None]
    confirmed_by: Mapped[UUID | None]
    receipt_id: Mapped[UUID]
    prepared_candidate_id: Mapped[UUID | None]
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "prepared_candidate_id"],
            ["proposal_prepared_candidates.tenant_id", "proposal_prepared_candidates.id"],
        ),
        category_fk(),
        principal_fk("writer_id"),
        principal_fk("confirmed_by"),
        UniqueConstraint("tenant_id", "parameter_id", "version"),
        UniqueConstraint("tenant_id", "category_id", "parameter_id", "version"),
        UniqueConstraint("tenant_id", "category_id", "key", "version"),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["action_receipts.tenant_id", "action_receipts.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("version>0 AND (replaces_version IS NULL OR replaces_version=version-1)"),
        CheckConstraint("value_type IN ('number','range','text','boolean','enum')"),
        CheckConstraint("direction IN ('higher','lower','target','neutral')"),
        CheckConstraint(
            "origin IN ('human','ai_draft','imported') AND "
            "(origin<>'ai_draft' OR run_id IS NOT NULL)"
        ),
    )


class ParameterCurrent(Base):
    __tablename__ = "parameter_current"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    parameter_id: Mapped[UUID] = mapped_column(primary_key=True)
    category_id: Mapped[UUID] = mapped_column(index=True)
    key: Mapped[str] = mapped_column(Text)
    current_version: Mapped[int]
    __table_args__ = (
        category_fk(),
        UniqueConstraint("tenant_id", "category_id", "key"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "parameter_id", "current_version"],
            [
                "parameter_versions.tenant_id",
                "parameter_versions.category_id",
                "parameter_versions.parameter_id",
                "parameter_versions.version",
            ],
        ),
        CheckConstraint("current_version>0"),
    )


class PromotionProof(Row, Base):
    __tablename__ = "promotion_proofs"
    category_id: Mapped[UUID] = mapped_column(index=True)
    knowledge_entry_id: Mapped[UUID]
    source_proposal_id: Mapped[UUID]
    source_proposal_revision: Mapped[int]
    source_item_refs: Mapped[list] = mapped_column(JSONB)
    deidentified_by: Mapped[UUID]
    deidentified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    checks: Mapped[dict] = mapped_column(JSONB)
    receipt_id: Mapped[UUID]
    __table_args__ = (
        category_fk(),
        principal_fk("deidentified_by"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "knowledge_entry_id"],
            [
                "category_knowledge_entries.tenant_id",
                "category_knowledge_entries.category_id",
                "category_knowledge_entries.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "source_proposal_id"],
            ["proposals.tenant_id", "proposals.category_id", "proposals.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["action_receipts.tenant_id", "action_receipts.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("source_proposal_revision>0"),
    )


MATERIAL_TABLES = (ParameterVersion.__table__, ParameterCurrent.__table__, PromotionProof.__table__)
