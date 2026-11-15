"""Personal memory tables (P84–P86). Owner-only reads; no AI-identity writes."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.agent.enterprise_search.embedding_models import Vector
from pdos_next.agent.kernel.kernel_row import KernelRow
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
    """Keyword index rows per episode: the owner's own words, and 小Pai's answer side."""

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
        CheckConstraint("source_kind IN ('episode','answer')", name="memory_index_source_kind"),
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
    # M2a (P86 第 9 项): the administrator may close free-text notes and proposals.
    notes_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    proposals_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
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


# ---------------------------------------------------------------------------
# M2a 本人记忆条目 (P86). A note is an identity row plus owner-written versions.
# Deleting a note purges every version body (and its source candidate) and
# leaves only a tombstone "某时删除了一条" (design §5 第 5 条).

NOTE_KINDS = ("convention", "background", "alias")
SCOPE_KINDS = ("global", "category", "product", "proposal", "project")
OBJECT_KINDS = ("category", "product", "proposal", "project")


class MemoryNote(KernelRow, Base):
    """Identity of one personal note; carries no content."""

    __tablename__ = "memory_notes"
    owner_id: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        Index("ix_memory_notes_owner", "tenant_id", "owner_id"),
    )


class MemoryNoteVersion(KernelRow, Base):
    """One owner-written version. Never updated; deleted only by the owner's purge."""

    __tablename__ = "memory_note_versions"
    owner_id: Mapped[UUID]
    note_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    scope_kind: Mapped[str] = mapped_column(String(16))
    scope_id: Mapped[UUID | None]
    category_id: Mapped[UUID | None]
    alias_term: Mapped[str | None] = mapped_column(String(40))
    alias_canonical: Mapped[str | None] = mapped_column(String(80))
    target_kind: Mapped[str | None] = mapped_column(String(16))
    target_id: Mapped[UUID | None]
    target_version: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[UUID | None]
    origin: Mapped[str] = mapped_column(String(16))
    candidate_id: Mapped[UUID | None]
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "note_id", "revision"),
        UniqueConstraint("tenant_id", "note_id", "request_key"),
        ForeignKeyConstraint(
            ["tenant_id", "note_id"], ["memory_notes.tenant_id", "memory_notes.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("revision > 0", name="memory_note_revision"),
        CheckConstraint("kind IN ('convention','background','alias')", name="memory_note_kind"),
        CheckConstraint("char_length(text) BETWEEN 1 AND 200", name="memory_note_text"),
        CheckConstraint(
            "scope_kind IN ('global','category','product','proposal','project') AND "
            "((scope_kind='global') = (scope_id IS NULL)) AND "
            "((scope_kind='global') = (category_id IS NULL))",
            name="memory_note_scope",
        ),
        CheckConstraint(
            "((kind='alias') = (alias_term IS NOT NULL)) AND (kind<>'alias' OR "
            "((alias_canonical IS NOT NULL) <> (target_id IS NOT NULL)))",
            name="memory_note_alias",
        ),
        CheckConstraint(
            "(target_id IS NULL) = (target_kind IS NULL) AND (target_id IS NULL) = "
            "(target_version IS NULL) AND (target_kind IS NULL OR "
            "target_kind IN ('category','product','proposal','project'))",
            name="memory_note_target",
        ),
        CheckConstraint("status IN ('active','replaced')", name="memory_note_status"),
        CheckConstraint("origin IN ('manual','candidate','merge')", name="memory_note_origin"),
        CheckConstraint("request_sha256 ~ '^[0-9a-f]{64}$'", name="memory_note_request_sha256"),
        Index("ix_memory_note_versions_owner", "tenant_id", "owner_id", "note_id", "revision"),
    )


class MemoryNoteDeletion(KernelRow, Base):
    """Tombstone left after the owner purged a note: when, and how many versions."""

    __tablename__ = "memory_note_deletions"
    owner_id: Mapped[UUID]
    note_id: Mapped[UUID]
    purged_versions: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "note_id"),
        UniqueConstraint("tenant_id", "owner_id", "request_key"),
        ForeignKeyConstraint(
            ["tenant_id", "note_id"], ["memory_notes.tenant_id", "memory_notes.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("purged_versions >= 0", name="memory_note_deletion_count"),
        CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$'", name="memory_note_deletion_request_sha256"
        ),
    )


class MemoryCandidate(KernelRow, Base):
    """A note 小Pai proposed from the owner's own words. Not memory until confirmed."""

    __tablename__ = "memory_candidates"
    owner_id: Mapped[UUID]
    session_id: Mapped[UUID]
    run_id: Mapped[UUID]
    candidate_key: Mapped[str] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    scope_kind: Mapped[str] = mapped_column(String(16))
    scope_id: Mapped[UUID | None]
    category_id: Mapped[UUID | None]
    alias_term: Mapped[str | None] = mapped_column(String(40))
    alias_canonical: Mapped[str | None] = mapped_column(String(80))
    conflicts: Mapped[list] = mapped_column(JSONB)
    trigger: Mapped[list] = mapped_column(JSONB)
    prompt_version: Mapped[str] = mapped_column(String(40))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "candidate_key"),
        ForeignKeyConstraint(["tenant_id", "run_id"], ["agent_runs.tenant_id", "agent_runs.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "session_id"], ["agent_sessions.tenant_id", "agent_sessions.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("origin IN ('explicit','proactive')", name="memory_candidate_origin"),
        CheckConstraint(
            "kind IN ('convention','background','alias')", name="memory_candidate_kind"
        ),
        CheckConstraint("char_length(text) BETWEEN 1 AND 200", name="memory_candidate_text"),
        CheckConstraint(
            "scope_kind IN ('global','category','product','proposal','project') AND "
            "((scope_kind='global') = (scope_id IS NULL)) AND "
            "((scope_kind='global') = (category_id IS NULL))",
            name="memory_candidate_scope",
        ),
        CheckConstraint(
            "((kind='alias') = (alias_term IS NOT NULL)) AND "
            "((kind='alias') = (alias_canonical IS NOT NULL))",
            name="memory_candidate_alias",
        ),
        CheckConstraint(
            "jsonb_typeof(conflicts)='array' AND jsonb_typeof(trigger)='array'",
            name="memory_candidate_json",
        ),
        CheckConstraint("candidate_key ~ '^[0-9a-f]{64}$'", name="memory_candidate_key"),
        Index("ix_memory_candidates_owner", "tenant_id", "owner_id", "created_at"),
        Index("ix_memory_candidates_session", "tenant_id", "session_id", "origin"),
    )


class MemoryCandidateDecision(KernelRow, Base):
    """The owner's single decision on a candidate: 记住 (adopted) or 忽略 (ignored)."""

    __tablename__ = "memory_candidate_decisions"
    owner_id: Mapped[UUID]
    candidate_id: Mapped[UUID]
    decision: Mapped[str] = mapped_column(String(16))
    note_id: Mapped[UUID | None]
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "candidate_id"),
        UniqueConstraint("tenant_id", "owner_id", "request_key"),
        ForeignKeyConstraint(
            ["tenant_id", "candidate_id"], ["memory_candidates.tenant_id", "memory_candidates.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint(
            "decision IN ('adopted','ignored') AND ((decision='adopted') = (note_id IS NOT NULL))",
            name="memory_candidate_decision",
        ),
        CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$'", name="memory_candidate_decision_sha256"
        ),
    )


class MemoryOwnerSetting(KernelRow, Base):
    """The owner's own switch for 小Pai's proactive proposals (P86 第 3 项)."""

    __tablename__ = "memory_owner_settings"
    owner_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    proactive_off: Mapped[bool] = mapped_column(Boolean)
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "owner_id", "revision"),
        UniqueConstraint("tenant_id", "owner_id", "request_key"),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("revision > 0", name="memory_owner_setting_revision"),
        CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$'", name="memory_owner_setting_sha256"
        ),
    )


# ---------------------------------------------------------------------------
# M2a 情景向量化 (P85 第 3 项). Optional: only when the tenant's active embedding
# profile selects the "本人会话记录" (owner_session) data category. Vectors are
# written by the episode owner's own background work; the call ledger is the
# outbound receipt (provider, data categories, P26 decision, cost), no text.


class MemoryEmbeddingCall(KernelRow, Base):
    __tablename__ = "memory_embedding_calls"
    owner_id: Mapped[UUID]
    profile_version_id: Mapped[UUID]
    state: Mapped[str] = mapped_column(String(24))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    episode_ids: Mapped[list] = mapped_column(JSONB)
    character_count: Mapped[int] = mapped_column(Integer)
    input_digest: Mapped[str] = mapped_column(String(64))
    data_categories: Mapped[list] = mapped_column(JSONB)
    egress: Mapped[dict] = mapped_column(JSONB)
    pricing: Mapped[dict] = mapped_column(JSONB)
    reserved_tokens: Mapped[int] = mapped_column(BigInteger)
    reserved_micro_usd: Mapped[int] = mapped_column(BigInteger)
    charged_micro_usd: Mapped[int] = mapped_column(BigInteger, default=0)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    provider_request_id: Mapped[str | None] = mapped_column(String(200))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "profile_version_id"],
            ["enterprise_embedding_profiles.tenant_id", "enterprise_embedding_profiles.id"],
        ),
        CheckConstraint(
            "state IN ('started','completed','unknown','unknown_usage')",
            name="memory_embedding_call_state",
        ),
        CheckConstraint(
            "revision > 0 AND character_count >= 0 AND reserved_tokens >= 0 AND "
            "reserved_micro_usd >= 0 AND charged_micro_usd >= 0 AND "
            "(input_tokens IS NULL OR input_tokens >= 0)",
            name="memory_embedding_call_counts",
        ),
        CheckConstraint(
            "jsonb_typeof(episode_ids)='array' AND jsonb_typeof(data_categories)='array' "
            "AND data_categories ? 'owner_session'",
            name="memory_embedding_call_categories",
        ),
        Index("ix_memory_embedding_calls_owner", "tenant_id", "owner_id", "created_at"),
    )


class MemoryEpisodeVector(KernelRow, Base):
    __tablename__ = "memory_episode_vectors"
    owner_id: Mapped[UUID]
    session_id: Mapped[UUID]
    episode_id: Mapped[UUID]
    profile_version_id: Mapped[UUID]
    call_id: Mapped[UUID]
    text_digest: Mapped[str] = mapped_column(String(64))
    dimensions: Mapped[int] = mapped_column(Integer)
    vector: Mapped[object] = mapped_column(Vector())
    norm: Mapped[float] = mapped_column(Float)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "episode_id", "profile_version_id"),
        ForeignKeyConstraint(
            ["tenant_id", "episode_id"], ["memory_episodes.tenant_id", "memory_episodes.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "call_id"],
            ["memory_embedding_calls.tenant_id", "memory_embedding_calls.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "profile_version_id"],
            ["enterprise_embedding_profiles.tenant_id", "enterprise_embedding_profiles.id"],
        ),
        CheckConstraint(
            "dimensions BETWEEN 1 AND 2000 AND vector_dims(vector)=dimensions AND norm=1",
            name="memory_episode_vector_shape",
        ),
        CheckConstraint("text_digest ~ '^[0-9a-f]{64}$'", name="memory_episode_vector_digest"),
        Index("ix_memory_episode_vectors_owner", "tenant_id", "owner_id", "profile_version_id"),
    )


class MemoryVectorProfile(KernelRow, Base):
    """Mirror of each saved embedding profile version's “本人会话记录” switch.

    Written only by a database trigger when an administrator saves a profile, so
    the dispatch role can find eligible episodes without reading profiles.
    """

    __tablename__ = "memory_vector_profiles"
    profile_id: Mapped[UUID]
    profile_version_id: Mapped[UUID]
    enabled: Mapped[bool] = mapped_column(Boolean)
    categories: Mapped[list] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "profile_version_id"),
        ForeignKeyConstraint(
            ["tenant_id", "profile_version_id"],
            ["enterprise_embedding_profiles.tenant_id", "enterprise_embedding_profiles.id"],
        ),
        CheckConstraint(
            "jsonb_typeof(categories)='array'", name="memory_vector_profile_categories"
        ),
        Index("ix_memory_vector_profiles_latest", "tenant_id", "profile_id", "created_at"),
    )


class MemorySessionDeletion(KernelRow, Base):
    """What stays after the owner deleted a Session: when, and how many rows went.

    No content. Written only by the database function ``memory_delete_session``,
    which checks the caller is the human owner acting for themself (P121 第 8 项).
    """

    __tablename__ = "memory_session_deletions"
    owner_id: Mapped[UUID]
    session_id: Mapped[UUID]
    purged_episodes: Mapped[int] = mapped_column(Integer)
    purged_marks: Mapped[int] = mapped_column(Integer)
    purged_index_rows: Mapped[int] = mapped_column(Integer)
    purged_vectors: Mapped[int] = mapped_column(Integer)
    purged_candidates: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "session_id"),
        UniqueConstraint("tenant_id", "owner_id", "request_key"),
        ForeignKeyConstraint(
            ["tenant_id", "session_id"], ["agent_sessions.tenant_id", "agent_sessions.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint(
            "purged_episodes >= 0 AND purged_marks >= 0 AND purged_index_rows >= 0 "
            "AND purged_vectors >= 0 AND purged_candidates >= 0",
            name="memory_session_deletion_counts",
        ),
        CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$'", name="memory_session_deletion_request_sha256"
        ),
        Index("ix_memory_session_deletions_owner", "tenant_id", "owner_id", "created_at"),
    )
