"""Derived projection/profile accounting; vectors never enter public serialization."""

from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from pdos_next.models import Base, Row


class Vector(UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions=None):
        if dimensions is not None and (type(dimensions) is not int or not 1 <= dimensions <= 2000):
            raise ValueError("Registered pgvector dimensions required")
        self.dimensions = dimensions

    def get_col_spec(self, **kw):
        return "vector" if self.dimensions is None else f"vector({self.dimensions})"

    def bind_processor(self, dialect):
        return lambda value: "[" + ",".join(str(float(item)) for item in value) + "]"


class EmbeddingProfileHead(Base):
    __tablename__ = "enterprise_embedding_profile_heads"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    profile_id: Mapped[UUID] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean)


class EmbeddingProfile(Row, Base):
    __tablename__ = "enterprise_embedding_profiles"
    profile_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    budget_revision: Mapped[int] = mapped_column(Integer)
    metadata_json: Mapped[dict] = mapped_column(JSONB)
    enabled: Mapped[bool] = mapped_column(Boolean)
    binding_digest: Mapped[str] = mapped_column(String(64))
    secret_json: Mapped[dict | None] = mapped_column(JSONB)
    created_by: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("tenant_id", "profile_id", "revision"),
        UniqueConstraint("tenant_id", "budget_revision"),
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "profile_id"],
            [
                "enterprise_embedding_profile_heads.tenant_id",
                "enterprise_embedding_profile_heads.profile_id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by"],
            [
                "principals.tenant_id",
                "principals.id",
            ],
        ),
        CheckConstraint("revision>0 AND budget_revision>0"),
    )

    @property
    def status(self):
        return "enabled" if self.enabled else "disabled"


class EmbeddingBudget(Base):
    __tablename__ = "enterprise_embedding_budgets"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    limit_micro_usd: Mapped[int] = mapped_column(BigInteger, default=0)
    held_micro_usd: Mapped[int] = mapped_column(BigInteger, default=0)
    spent_micro_usd: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (
        CheckConstraint(
            "revision>=0 AND limit_micro_usd>=0 AND held_micro_usd>=0 AND spent_micro_usd>=0"
        ),
    )


class EmbeddingBatch(Row, Base):
    __tablename__ = "enterprise_embedding_batches"
    profile_version_id: Mapped[UUID]
    category_id: Mapped[UUID] = mapped_column(nullable=False)
    manifest: Mapped[dict] = mapped_column(JSONB)
    work_key: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(80))
    __table_args__ = (
        UniqueConstraint("tenant_id", "work_key"),
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "profile_version_id"],
            [
                "enterprise_embedding_profiles.tenant_id",
                "enterprise_embedding_profiles.id",
            ],
        ),
        CheckConstraint("state IN ('queued','running','ready','retryable','unavailable')"),
        CheckConstraint("attempts BETWEEN 0 AND 3"),
    )


class EmbeddingCall(Row, Base):
    __tablename__ = "enterprise_embedding_calls"
    batch_id: Mapped[UUID]
    category_id: Mapped[UUID] = mapped_column(nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    attempt: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(24))
    profile_digest: Mapped[str] = mapped_column(String(64))
    input_digest: Mapped[str] = mapped_column(String(64))
    source_count: Mapped[int] = mapped_column(Integer)
    character_count: Mapped[int] = mapped_column(Integer)
    data_categories: Mapped[list] = mapped_column(JSONB)
    egress: Mapped[dict] = mapped_column(JSONB)
    pricing: Mapped[dict] = mapped_column(JSONB)
    reserved_tokens: Mapped[int] = mapped_column(BigInteger)
    reserved_micro_usd: Mapped[int] = mapped_column(BigInteger)
    charged_micro_usd: Mapped[int] = mapped_column(BigInteger, default=0)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    provider_request_id: Mapped[str | None] = mapped_column(String(200))
    evidence_ref: Mapped[str | None] = mapped_column(String(500))
    __table_args__ = (
        UniqueConstraint("tenant_id", "batch_id", "attempt"),
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            [
                "enterprise_embedding_batches.tenant_id",
                "enterprise_embedding_batches.id",
            ],
        ),
        CheckConstraint("state IN ('started','completed','unknown','unknown_usage','reconciled')"),
        CheckConstraint(
            "attempt BETWEEN 1 AND 3 AND revision>0 AND source_count>=0 "
            "AND character_count>=0 AND reserved_tokens>=0 AND reserved_micro_usd>=0 "
            "AND charged_micro_usd>=0 AND (input_tokens IS NULL OR input_tokens>=0)"
        ),
    )

    @property
    def status(self):
        return self.state


class ChunkEmbedding(Base):
    __tablename__ = "enterprise_chunk_embeddings"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("enterprise_search_chunks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    profile_version_id: Mapped[UUID] = mapped_column(primary_key=True)
    category_id: Mapped[UUID]
    chunk_hash: Mapped[str] = mapped_column(String(64))
    dimensions: Mapped[int] = mapped_column(Integer)
    vector: Mapped[object] = mapped_column(Vector())
    norm: Mapped[float] = mapped_column(Float)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "profile_version_id"],
            [
                "enterprise_embedding_profiles.tenant_id",
                "enterprise_embedding_profiles.id",
            ],
        ),
        CheckConstraint(
            "dimensions BETWEEN 1 AND 2000 AND vector_dims(vector)=dimensions AND norm=1"
        ),
    )
