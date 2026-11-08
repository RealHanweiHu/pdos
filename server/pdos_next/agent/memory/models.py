"""Personal memory tables (P84, P85). Owner-only reads; no AI-identity writes."""

from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.agent.kernel.models import KernelRow
from pdos_next.core.models import Base


class MemoryEpisode(KernelRow, Base):
    """One deterministic record per finished conversation Run; inserted only by the
    database projection of the Run's committed work-state version."""

    __tablename__ = "memory_episodes"
    owner_id: Mapped[UUID]
    session_id: Mapped[UUID]
    run_id: Mapped[UUID]
    work_state_id: Mapped[UUID]
    work_state_revision: Mapped[int] = mapped_column(Integer)
    category_id: Mapped[UUID | None]
    product_id: Mapped[UUID | None]
    proposal_id: Mapped[UUID | None]
    project_id: Mapped[UUID | None]
    entry: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32))
    goal: Mapped[str] = mapped_column(Text)
    body: Mapped[dict] = mapped_column(JSONB)
    projection_version: Mapped[str] = mapped_column(String(40))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "run_id"),
        ForeignKeyConstraint(
            ["tenant_id", "session_id"], ["agent_sessions.tenant_id", "agent_sessions.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(["tenant_id", "run_id"], ["agent_runs.tenant_id", "agent_runs.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "work_state_id"], ["agent_work_states.tenant_id", "agent_work_states.id"]
        ),
        CheckConstraint("work_state_revision > 0", name="memory_episode_revision"),
        CheckConstraint("entry IN ('web','dingtalk')", name="memory_episode_entry"),
        CheckConstraint("jsonb_typeof(body)='object'", name="memory_episode_body"),
        Index("ix_memory_episodes_owner_recent", "tenant_id", "owner_id", "created_at"),
    )


class MemoryEpisodeMark(KernelRow, Base):
    """Owner pins, hides and corrections. Append-only; latest pin/hide wins."""

    __tablename__ = "memory_episode_marks"
    owner_id: Mapped[UUID]
    session_id: Mapped[UUID]
    episode_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(16))
    body: Mapped[dict] = mapped_column(JSONB)
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "owner_id", "request_key"),
        ForeignKeyConstraint(
            ["tenant_id", "episode_id"], ["memory_episodes.tenant_id", "memory_episodes.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint(
            "kind IN ('pin','unpin','hide','unhide','correction')", name="memory_mark_kind"
        ),
        CheckConstraint("jsonb_typeof(body)='object'", name="memory_mark_body"),
        CheckConstraint("request_sha256 ~ '^[0-9a-f]{64}$'", name="memory_mark_request_sha256"),
        Index("ix_memory_episode_marks_episode", "tenant_id", "episode_id"),
    )


class MemoryIndexEntry(KernelRow, Base):
    """Keyword index rows for the owner's own words; filled by a background activity."""

    __tablename__ = "memory_index"
    owner_id: Mapped[UUID]
    session_id: Mapped[UUID]
    episode_id: Mapped[UUID]
    source_kind: Mapped[str] = mapped_column(String(16))
    source_version: Mapped[int] = mapped_column(Integer)
    profile_version: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    terms: Mapped[object] = mapped_column(TSVECTOR)
    term_counts: Mapped[dict] = mapped_column(JSONB)
    codes: Mapped[list] = mapped_column(ARRAY(Text))
    token_count: Mapped[int] = mapped_column(Integer)
    tokenizer_version: Mapped[str] = mapped_column(String(160))
    code_rule_version: Mapped[str] = mapped_column(String(160))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "idempotency_key"),
        ForeignKeyConstraint(
            ["tenant_id", "episode_id"], ["memory_episodes.tenant_id", "memory_episodes.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("source_kind IN ('episode')", name="memory_index_source_kind"),
        CheckConstraint("source_version > 0 AND token_count >= 0", name="memory_index_counts"),
        CheckConstraint("idempotency_key ~ '^[0-9a-f]{64}$'", name="memory_index_key"),
        Index("ix_memory_index_owner", "tenant_id", "owner_id", "tokenizer_version"),
        Index("ix_memory_index_terms", "terms", postgresql_using="gin"),
        Index("ix_memory_index_codes", "codes", postgresql_using="gin"),
    )


class MemorySessionSetting(KernelRow, Base):
    """The owner's "不进记忆" switch for one Session. Append-only versions."""

    __tablename__ = "memory_session_settings"
    owner_id: Mapped[UUID]
    session_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    memory_off: Mapped[bool] = mapped_column(Boolean)
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "session_id", "revision"),
        UniqueConstraint("tenant_id", "owner_id", "request_key"),
        ForeignKeyConstraint(
            ["tenant_id", "session_id"], ["agent_sessions.tenant_id", "agent_sessions.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("revision > 0", name="memory_setting_revision"),
        CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$'", name="memory_setting_request_sha256"
        ),
    )


class MemoryTenantPolicy(KernelRow, Base):
    """Tenant memory policy set by a current human administrator. Append-only versions."""

    __tablename__ = "memory_tenant_policies"
    revision: Mapped[int] = mapped_column(Integer)
    work_state_idle_days: Mapped[int] = mapped_column(Integer)
    set_by: Mapped[UUID]
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "revision"),
        UniqueConstraint("tenant_id", "request_key"),
        ForeignKeyConstraint(["tenant_id", "set_by"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("revision > 0", name="memory_policy_revision"),
        CheckConstraint(
            "work_state_idle_days BETWEEN 1 AND 365", name="memory_policy_idle_days"
        ),
        CheckConstraint("request_sha256 ~ '^[0-9a-f]{64}$'", name="memory_policy_request_sha256"),
    )
