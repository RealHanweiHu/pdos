# ruff: noqa: E501 -- PostgreSQL predicates remain readable as full expressions.
"""M3 沉淀与改进 tables (memory design §6.4, §7.5, §14.6–§14.9; P88; target architecture §6.9).

Everything here is a candidate, a notice or a ledger entry. Nothing in these
tables is memory, a business fact, a skill package or a prompt:

* ``memory_review_items``: what a person should look at. Three sources:
  a correction routed one of the four ways of §14.9 (事实错误 / 做法问题 /
  个人偏好 / 团队约定), a deterministic 待复核 flag after an object revision,
  and a review hand-over after an author left. Correction routes are written by
  the human who corrected, acting for themself; flags and hand-overs only by
  the database's own system-rule functions. The AI writer identity never
  satisfies either path.
* ``memory_review_decisions``: the assignee's one decision on an item.
* ``skill_revision_candidates``: the daily procedural summary's output, one row
  per "tenant × target × version × tool × reason" crossing the threshold.
* ``skill_revision_decisions``: a named reviewer's adopt or reject. Adopting
  only names a draft version to prepare; nothing is activated here.
* ``memory_system_rule_settings``: an administrator stopping (or restarting) a
  preset system rule. The rule text itself lives in code and cannot be rewritten.
* ``memory_maintenance_ledger``: one row per (task, subject, watermark), so
  each fan-out handler and each scheduled pass runs once and can be replayed.

All tables are append-only.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.agent.kernel.kernel_row import KernelRow
from pdos_next.core.models import Base

SOURCES = ("correction", "staleness", "departure")
# 纠正四路 (§14.9); staleness/departure items use the review kinds.
ROUTES = ("fact", "skill", "personal", "team")
REVIEW_KINDS = ("object_updated", "author_departed")
ITEM_KINDS = (*ROUTES, *REVIEW_KINDS)
SCOPE_KINDS = ("global", "category", "product", "proposal", "project")
OBJECT_KINDS = ("category", "product", "proposal", "project", "proposal_decision")
NOTE_KINDS = ("scope_note", "personal_note")
DECISIONS = ("adopted", "forwarded", "dismissed", "resolved")
TARGETS = ("skill_package", "prompt")
REVISION_DECISIONS = ("adopt", "reject")


def _in(values):
    return ",".join(repr(value) for value in values)


def _principal(column):
    return ForeignKeyConstraint(["tenant_id", column], ["principals.tenant_id", "principals.id"])


class MemoryReviewItem(KernelRow, Base):
    """One thing one person should look at. Never memory until that person acts."""

    __tablename__ = "memory_review_items"
    source: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    assignee_id: Mapped[UUID]
    # Who caused the item: the person who corrected, or NULL for a system rule.
    raised_by: Mapped[UUID | None]
    run_id: Mapped[UUID | None]
    mark_id: Mapped[UUID | None]
    parent_id: Mapped[UUID | None]
    scope_kind: Mapped[str] = mapped_column(String(16))
    category_id: Mapped[UUID | None]
    scope_id: Mapped[UUID | None]
    object_kind: Mapped[str | None] = mapped_column(String(24))
    object_id: Mapped[UUID | None]
    recorded_version: Mapped[int | None] = mapped_column(Integer)
    current_version: Mapped[int | None] = mapped_column(Integer)
    note_kind: Mapped[str | None] = mapped_column(String(16))
    note_id: Mapped[UUID | None]
    note_revision: Mapped[int | None] = mapped_column(Integer)
    target_kind: Mapped[str | None] = mapped_column(String(16))
    target_key: Mapped[str | None] = mapped_column(String(80))
    target_version: Mapped[str | None] = mapped_column(String(40))
    reasons: Mapped[list] = mapped_column(JSONB)
    text: Mapped[str | None] = mapped_column(Text)
    proposed_kind: Mapped[str | None] = mapped_column(String(24))
    event_id: Mapped[UUID | None]
    dedupe_key: Mapped[str] = mapped_column(String(64))
    request_key: Mapped[UUID | None]
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "dedupe_key"),
        _principal("assignee_id"),
        _principal("raised_by"),
        ForeignKeyConstraint(["tenant_id", "run_id"], ["agent_runs.tenant_id", "agent_runs.id"]),
        # mark_id is a plain reference: deleting a Session removes its correction marks
        # (s0_0893), and an append-only item must not block that.
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"], ["memory_review_items.tenant_id", "memory_review_items.id"]
        ),
        CheckConstraint(
            f"source IN ({_in(SOURCES)}) AND kind IN ({_in(ITEM_KINDS)}) AND "
            "((source='correction') = (kind IN ('fact','skill','personal','team'))) AND "
            "((source='staleness') = (kind='object_updated')) AND "
            "((source='departure') = (kind='author_departed')) AND "
            "((source='correction') = (raised_by IS NOT NULL AND run_id IS NOT NULL "
            "AND mark_id IS NOT NULL AND request_key IS NOT NULL))",
            name="memory_review_item_source",
        ),
        CheckConstraint(
            f"scope_kind IN ({_in(SCOPE_KINDS)}) AND "
            "((scope_kind='global') = (scope_id IS NULL)) AND "
            "((scope_kind='global') = (category_id IS NULL))",
            name="memory_review_item_scope",
        ),
        CheckConstraint(
            f"(object_kind IS NULL OR object_kind IN ({_in(OBJECT_KINDS)})) AND "
            "((object_id IS NULL) = (object_kind IS NULL)) AND "
            f"(note_kind IS NULL OR note_kind IN ({_in(NOTE_KINDS)})) AND "
            "((note_id IS NULL) = (note_kind IS NULL)) AND ((note_id IS NULL) = (note_revision IS NULL)) AND "
            f"(target_kind IS NULL OR target_kind IN ({_in(TARGETS)})) AND "
            "((target_kind IS NULL) = (target_key IS NULL))",
            name="memory_review_item_refs",
        ),
        CheckConstraint(
            # Each kind carries what it needs, and only the owner's own words.
            "(kind<>'skill' OR target_kind IS NOT NULL) AND "
            "(kind NOT IN ('personal','team') OR (text IS NOT NULL AND proposed_kind IS NOT NULL)) AND "
            "(kind<>'personal' OR (char_length(text) BETWEEN 1 AND 200 "
            "AND proposed_kind IN ('convention','background') AND assignee_id=raised_by)) AND "
            "(kind<>'team' OR (char_length(text) BETWEEN 1 AND 300 AND scope_kind<>'global' "
            "AND proposed_kind IN ('convention','concern','decision_context','observation'))) AND "
            "(kind NOT IN ('fact','skill') OR proposed_kind IS NULL) AND "
            "(text IS NULL OR char_length(text) BETWEEN 1 AND 300) AND "
            "(kind NOT IN ('object_updated','author_departed') OR (note_id IS NOT NULL AND text IS NULL)) AND "
            "(kind<>'object_updated' OR (object_id IS NOT NULL AND current_version IS NOT NULL "
            "AND event_id IS NOT NULL))",
            name="memory_review_item_shape",
        ),
        CheckConstraint(
            "jsonb_typeof(reasons)='array' AND dedupe_key ~ '^[0-9a-f]{64}$'",
            name="memory_review_item_json",
        ),
        Index("ix_memory_review_items_assignee", "tenant_id", "assignee_id", "created_at"),
        Index("ix_memory_review_items_raised", "tenant_id", "raised_by", "created_at"),
        Index("ix_memory_review_items_note", "tenant_id", "note_kind", "note_id"),
    )


class MemoryReviewDecision(KernelRow, Base):
    """The assignee's single decision on an item, with what came of it (references only)."""

    __tablename__ = "memory_review_decisions"
    item_id: Mapped[UUID]
    decided_by: Mapped[UUID]
    decision: Mapped[str] = mapped_column(String(16))
    result: Mapped[dict] = mapped_column(JSONB)
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "item_id"),
        UniqueConstraint("tenant_id", "decided_by", "request_key"),
        ForeignKeyConstraint(
            ["tenant_id", "item_id"], ["memory_review_items.tenant_id", "memory_review_items.id"]
        ),
        _principal("decided_by"),
        CheckConstraint(f"decision IN ({_in(DECISIONS)})", name="memory_review_decision_kind"),
        CheckConstraint(
            "jsonb_typeof(result)='object' AND request_sha256 ~ '^[0-9a-f]{64}$'",
            name="memory_review_decision_json",
        ),
    )


class SkillRevisionCandidate(KernelRow, Base):
    """A procedural revision candidate: counts and sample Runs, never a revision itself."""

    __tablename__ = "skill_revision_candidates"
    target_kind: Mapped[str] = mapped_column(String(16))
    target_key: Mapped[str] = mapped_column(String(80))
    target_version: Mapped[str] = mapped_column(String(40))
    tool: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(String(40))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    signal_count: Mapped[int] = mapped_column(Integer)
    threshold: Mapped[int] = mapped_column(Integer)
    sample_run_ids: Mapped[list] = mapped_column(JSONB)
    signal_sources: Mapped[dict] = mapped_column(JSONB)
    signals_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "signals_sha256"),
        CheckConstraint(
            f"target_kind IN ({_in(TARGETS)}) AND signal_count >= threshold AND threshold > 0 "
            "AND window_end > window_start AND jsonb_typeof(sample_run_ids)='array' "
            "AND jsonb_array_length(sample_run_ids) BETWEEN 1 AND 10 "
            "AND jsonb_typeof(signal_sources)='object' AND signals_sha256 ~ '^[0-9a-f]{64}$'",
            name="skill_revision_candidate_shape",
        ),
        Index("ix_skill_revision_candidates_target", "tenant_id", "target_kind", "target_key",
              "target_version", "tool", "reason"),
    )


class SkillRevisionDecision(KernelRow, Base):
    """A named reviewer's decision. ``draft`` names the draft version to prepare, if adopted."""

    __tablename__ = "skill_revision_decisions"
    candidate_id: Mapped[UUID]
    decided_by: Mapped[UUID]
    decision: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text)
    draft: Mapped[dict] = mapped_column(JSONB)
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "candidate_id"),
        UniqueConstraint("tenant_id", "decided_by", "request_key"),
        ForeignKeyConstraint(
            ["tenant_id", "candidate_id"],
            ["skill_revision_candidates.tenant_id", "skill_revision_candidates.id"],
        ),
        _principal("decided_by"),
        CheckConstraint(
            f"decision IN ({_in(REVISION_DECISIONS)}) AND jsonb_typeof(draft)='object' "
            "AND ((decision='adopt') = (draft ? 'draft_version')) "
            "AND (draft->>'activated') IS NULL "
            "AND (note IS NULL OR char_length(note) BETWEEN 1 AND 500) "
            "AND request_sha256 ~ '^[0-9a-f]{64}$'",
            name="skill_revision_decision_shape",
        ),
    )


class MemorySystemRuleSetting(KernelRow, Base):
    """An administrator stopping or restarting one preset system rule; latest row wins."""

    __tablename__ = "memory_system_rule_settings"
    rule_key: Mapped[str] = mapped_column(String(40))
    revision: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean)
    set_by: Mapped[UUID]
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "rule_key", "revision"),
        UniqueConstraint("tenant_id", "set_by", "request_key"),
        _principal("set_by"),
        CheckConstraint(
            "revision > 0 AND rule_key ~ '^[a-z][a-z0-9_]{2,39}$' "
            "AND request_sha256 ~ '^[0-9a-f]{64}$'",
            name="memory_system_rule_setting_shape",
        ),
    )


class MemoryMaintenanceLedger(KernelRow, Base):
    """Each fan-out handler and scheduled pass, once per subject and watermark."""

    __tablename__ = "memory_maintenance_ledger"
    task: Mapped[str] = mapped_column(String(40))
    subject_key: Mapped[str] = mapped_column(String(120))
    watermark: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16))
    detail: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "task", "subject_key", "watermark"),
        CheckConstraint(
            "task ~ '^[a-z][a-z0-9_.:]{2,39}$' AND watermark ~ '^[0-9a-f]{64}$' "
            "AND outcome IN ('done','held','skipped') AND jsonb_typeof(detail)='object'",
            name="memory_maintenance_ledger_shape",
        ),
        Index("ix_memory_maintenance_ledger_task", "tenant_id", "task", "created_at"),
    )
