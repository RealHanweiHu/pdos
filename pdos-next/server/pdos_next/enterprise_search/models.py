"""Derived search data only. No copied audiences and no Agent-role direct access."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


class SearchChunk(Row, Base):
    __tablename__ = "enterprise_search_chunks"
    category_id: Mapped[UUID] = mapped_column()
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[UUID]
    source_revision: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[UUID | None]
    project_id: Mapped[UUID | None]
    proposal_id: Mapped[UUID | None]
    content_hash: Mapped[str] = mapped_column(String(64))
    chunk_hash: Mapped[str] = mapped_column(String(64))
    work_key: Mapped[str] = mapped_column(String(64))
    ordinal: Mapped[int] = mapped_column(Integer)
    nature: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    locator: Mapped[dict] = mapped_column(JSONB)
    terms: Mapped[object] = mapped_column(TSVECTOR)
    term_counts: Mapped[dict] = mapped_column(JSONB)
    title_counts: Mapped[dict] = mapped_column(JSONB)
    token_count: Mapped[int] = mapped_column(Integer)
    codes: Mapped[list] = mapped_column(ARRAY(Text))
    code_families: Mapped[list] = mapped_column(ARRAY(Text))
    parser_version: Mapped[str] = mapped_column(String(160))
    chunker_version: Mapped[str] = mapped_column(String(160))
    tokenizer_version: Mapped[str] = mapped_column(String(160))
    code_rule_version: Mapped[str] = mapped_column(String(160))
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_type", "source_id", "work_key", "ordinal"),
        CheckConstraint("source_revision>0 AND ordinal>=0 AND token_count>=0"),
        CheckConstraint("nature IN ('structured','untrusted')"),
        CheckConstraint("char_length(text) BETWEEN 1 AND 20000"),
        CheckConstraint("content_hash ~ '^[a-f0-9]{64}$' AND chunk_hash ~ '^[a-f0-9]{64}$'"),
        Index("ix_enterprise_chunks_scope", "tenant_id", "category_id", "source_type", "source_id"),
        Index("ix_enterprise_chunks_terms", "terms", postgresql_using="gin"),
        Index("ix_enterprise_chunks_codes", "codes", postgresql_using="gin"),
        Index("ix_enterprise_chunks_families", "code_families", postgresql_using="gin"),
    )


class SearchSource(Row, Base):
    __tablename__ = "enterprise_search_sources"
    category_id: Mapped[UUID] = mapped_column()
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[UUID]
    original_id: Mapped[UUID | None]
    # Possible scan targets only. Current authority and scan receipts are always
    # checked on reads; NULL keeps the original projection path for older rows.
    original_ids: Mapped[list[UUID] | None] = mapped_column(ARRAY(PGUUID(as_uuid=True)))
    source_revision: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    work_key: Mapped[str | None] = mapped_column(String(64))
    chunk_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    last_error: Mapped[str | None] = mapped_column(String(80))
    event_id: Mapped[UUID | None]
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_type", "source_id"),
        CheckConstraint("source_revision>0 AND chunk_count>=0"),
        CheckConstraint("status IN ('ready','unavailable','failed','rebuild_required')"),
    )


class SearchCorpus(Base):
    __tablename__ = "enterprise_search_corpus"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    chunk_count: Mapped[int] = mapped_column(Integer)
    token_count: Mapped[int] = mapped_column(Integer)
    __table_args__ = (CheckConstraint("chunk_count>=0 AND token_count>=0"),)


class SearchTerm(Base):
    __tablename__ = "enterprise_search_terms"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    term: Mapped[str] = mapped_column(Text, primary_key=True)
    document_count: Mapped[int] = mapped_column(Integer)
    __table_args__ = (CheckConstraint("document_count>=0"),)
