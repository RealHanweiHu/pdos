"""Pinned category knowledge consumed by G0; authoring is a subsequent M3 slice."""

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Integer, Text, UniqueConstraint
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
    __table_args__ = (
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
