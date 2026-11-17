"""范围条目 (M2b; P87, P121 第 3、4、6 项): team notes attached to a business scope.

A scope note is attached to a category and optionally one product, proposal or
project inside it; who can read it follows that object's own audience. Content
lives in append-only versions that share the unified item contract of the
target architecture §5.7 (occurred/valid time, epistemic and confirmation
states, formal link, evidence links, relations). Every version is bound to the
common receipt of one registered domain command; nothing here is written
outside ``scope_note.save``, ``scope_note.retire`` or
``scope_note.observation.record``. A note is a business record: it is retired,
withdrawn or superseded, never deleted.
"""

# ruff: noqa: E501 -- PostgreSQL predicates remain readable as full expressions.

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

from pdos_next.core.models import Base, Row

ANCHORS = ("category", "product", "proposal", "project")
KINDS = ("convention", "concern", "decision_context", "observation")
LIFECYCLES = ("active", "superseded", "withdrawn", "retired")
ACTIONS = ("create", "revise", "add_evidence", "supersede", "backfill", "retire", "withdraw")
AUTHORITIES = (
    "business_record", "published_rule", "verified_answer", "original", "human_statement",
    "discussion", "xiaopai_generated",
)
EPISTEMIC = ("stated", "verified", "inferred", "disputed")
CONFIRMATIONS = ("discussion", "proposed", "member_confirmed", "formal_linked")
GENERATED = ("human", "xiaopai_drafted", "xiaopai")
OPERATIONS = ("scope_note.save", "scope_note.retire", "scope_note.observation.record")
OBJECTS = ("category", "product", "proposal", "project")
FORMALS = (*OBJECTS, "proposal_decision")
SOURCES = ("run", "discussion", "receipt", "original", "business_object")
STANCES = ("supports", "opposes", "context")
RELATIONS = ("supersedes", "conflicts", "duplicates", "refines", "derived_from")


def _in(values):
    return ",".join(repr(value) for value in values)


_ANCHOR = (
    f"anchor_kind IN ({_in(ANCHORS)}) AND "
    "((anchor_kind='category' AND product_id IS NULL AND proposal_id IS NULL AND project_id IS NULL) OR "
    "(anchor_kind='product' AND product_id IS NOT NULL AND proposal_id IS NULL AND project_id IS NULL) OR "
    "(anchor_kind='proposal' AND product_id IS NULL AND proposal_id IS NOT NULL AND project_id IS NULL) OR "
    "(anchor_kind='project' AND product_id IS NOT NULL AND proposal_id IS NULL AND project_id IS NOT NULL))"
)


def _anchor_fks():
    return (
        ForeignKeyConstraint(["tenant_id", "category_id"], ["categories.tenant_id", "categories.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "product_id"],
            ["products.tenant_id", "products.category_id", "products.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "proposal_id"],
            ["proposals.tenant_id", "proposals.category_id", "proposals.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id"],
            ["projects.tenant_id", "projects.product_id", "projects.id"],
        ),
    )


def _principal(column):
    return ForeignKeyConstraint(["tenant_id", column], ["principals.tenant_id", "principals.id"])


class _Anchor(Row):
    category_id: Mapped[UUID] = mapped_column(index=True)
    product_id: Mapped[UUID | None]
    proposal_id: Mapped[UUID | None]
    project_id: Mapped[UUID | None]
    anchor_kind: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(24))


class ScopeNote(_Anchor, Base):
    """Identity: where the note is attached, its kind and claim key. Never changes."""

    __tablename__ = "scope_notes"
    claim_key: Mapped[str] = mapped_column(String(64))
    author_id: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint(
            "tenant_id", "category_id", "id", "anchor_kind", "kind",
            name="scope_note_binding",
        ),
        *_anchor_fks(),
        _principal("author_id"),
        CheckConstraint(_ANCHOR, name="scope_note_anchor"),
        CheckConstraint(f"kind IN ({_in(KINDS)})", name="scope_note_kind"),
        CheckConstraint("claim_key ~ '^[0-9a-f]{64}$'", name="scope_note_claim_key"),
        Index("ix_scope_notes_anchor", "tenant_id", "category_id", "anchor_kind"),
        Index("ix_scope_notes_project", "tenant_id", "project_id"),
        Index("ix_scope_notes_proposal", "tenant_id", "proposal_id"),
    )


class ScopeNoteVersion(_Anchor, Base):
    """One append-only version under the unified item contract (§5.7)."""

    __tablename__ = "scope_note_versions"
    note_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))
    lifecycle: Mapped[str] = mapped_column(String(16))
    statement: Mapped[str] = mapped_column(Text)
    subject_kind: Mapped[str | None] = mapped_column(String(16))
    subject_id: Mapped[UUID | None]
    subject_version: Mapped[int | None] = mapped_column(Integer)
    customer_identity: Mapped[str | None] = mapped_column(String(80))
    stage: Mapped[str | None] = mapped_column(String(40))
    topic: Mapped[str | None] = mapped_column(String(40))
    sensitivity: Mapped[str] = mapped_column(String(24))
    source_authority: Mapped[str] = mapped_column(String(24))
    epistemic: Mapped[str] = mapped_column(String(16))
    confirmation: Mapped[str] = mapped_column(String(24))
    formal_kind: Mapped[str | None] = mapped_column(String(24))
    formal_id: Mapped[UUID | None]
    formal_version: Mapped[int | None] = mapped_column(Integer)
    generated_by: Mapped[str] = mapped_column(String(24))
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    pinned: Mapped[bool] = mapped_column(Boolean)
    writer_id: Mapped[UUID]
    requester_id: Mapped[UUID]
    confirmed_by: Mapped[UUID | None]
    run_id: Mapped[UUID | None]
    reason: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[dict] = mapped_column(JSONB)
    operation: Mapped[str] = mapped_column(String(80))
    command_id: Mapped[UUID]
    receipt_id: Mapped[UUID]
    request_digest: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "note_id", "revision"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "note_id", "anchor_kind", "kind"],
            ["scope_notes.tenant_id", "scope_notes.category_id", "scope_notes.id",
             "scope_notes.anchor_kind", "scope_notes.kind"],
        ),
        *_anchor_fks(),
        *(_principal(column) for column in ("writer_id", "requester_id", "confirmed_by")),
        ForeignKeyConstraint(["tenant_id", "run_id"], ["agent_runs.tenant_id", "agent_runs.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"], ["action_receipts.tenant_id", "action_receipts.id"],
            deferrable=True, initially="DEFERRED",
        ),
        CheckConstraint(_ANCHOR, name="scope_note_version_anchor"),
        CheckConstraint(
            f"revision > 0 AND kind IN ({_in(KINDS)}) AND action IN ({_in(ACTIONS)}) AND "
            f"lifecycle IN ({_in(LIFECYCLES)}) AND operation IN ({_in(OPERATIONS)}) AND "
            "((revision=1) = (action IN ('create','backfill')))",
            name="scope_note_version_chain",
        ),
        CheckConstraint("char_length(statement) BETWEEN 1 AND 300", name="scope_note_version_statement"),
        CheckConstraint(
            f"(subject_id IS NULL) = (subject_kind IS NULL) AND (subject_id IS NULL) = (subject_version IS NULL) "
            f"AND (subject_kind IS NULL OR subject_kind IN ({_in(OBJECTS)}))",
            name="scope_note_version_subject",
        ),
        CheckConstraint(
            f"(formal_id IS NULL) = (formal_kind IS NULL) AND (formal_id IS NULL) = (formal_version IS NULL) "
            f"AND (formal_kind IS NULL OR formal_kind IN ({_in(FORMALS)})) "
            # 已关联正式记录必须带正式对象 (§5.7); 没有就不是 formal_linked.
            "AND ((confirmation='formal_linked') = (formal_id IS NOT NULL))",
            name="scope_note_version_formal",
        ),
        CheckConstraint(
            f"source_authority IN ({_in(AUTHORITIES)}) AND epistemic IN ({_in(EPISTEMIC)}) AND "
            f"confirmation IN ({_in(CONFIRMATIONS)}) AND generated_by IN ({_in(GENERATED)}) AND "
            "sensitivity IN ('normal','customer_private') AND "
            "((sensitivity='customer_private') = (customer_identity IS NOT NULL))",
            name="scope_note_version_states",
        ),
        CheckConstraint(
            # P121 第 4 项: what 小Pai writes by itself is an unverified observation, never
            # pinned, never a convention, and carries the Run it can be withdrawn by.
            "(generated_by<>'xiaopai' OR (kind='observation' AND epistemic IN ('stated','inferred') "
            "AND confirmation='proposed' AND confirmed_by IS NULL AND run_id IS NOT NULL AND NOT pinned)) "
            "AND (generated_by='xiaopai' OR action IN ('retire','withdraw','supersede') OR confirmed_by IS NOT NULL) "
            "AND (generated_by<>'xiaopai_drafted' OR run_id IS NOT NULL)",
            name="scope_note_version_writer",
        ),
        CheckConstraint(
            "(valid_to IS NULL OR valid_to >= valid_from) AND review_due_at >= created_at "
            "AND (lifecycle<>'active' OR action IN ('create','revise','add_evidence')) "
            "AND ((action IN ('retire','withdraw')) = (lifecycle IN ('retired','withdrawn'))) "
            "AND (reason IS NULL OR char_length(reason) BETWEEN 1 AND 200)",
            name="scope_note_version_time",
        ),
        CheckConstraint(
            "jsonb_typeof(origin)='object' AND request_digest ~ '^[0-9a-f]{64}$'",
            name="scope_note_version_origin",
        ),
        Index("ix_scope_note_versions_note", "tenant_id", "note_id", "revision"),
        Index("ix_scope_note_versions_receipt", "tenant_id", "receipt_id"),
        Index("ix_scope_note_versions_run", "tenant_id", "run_id"),
    )

    @property
    def status(self):
        return self.lifecycle


class ScopeNoteEvidence(Row, Base):
    """证据链接: where a version's claim comes from. No quoted text is stored."""

    __tablename__ = "scope_note_evidence"
    category_id: Mapped[UUID] = mapped_column(index=True)
    note_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    source_type: Mapped[str] = mapped_column(String(24))
    source_kind: Mapped[str | None] = mapped_column(String(24))
    source_id: Mapped[UUID]
    source_version: Mapped[int | None] = mapped_column(Integer)
    locator: Mapped[dict] = mapped_column(JSONB)
    quote_sha256: Mapped[str | None] = mapped_column(String(64))
    root_source_id: Mapped[UUID]
    stance: Mapped[str] = mapped_column(String(16))
    writer_id: Mapped[UUID]
    run_id: Mapped[UUID | None]
    # A retraction row names the link it takes back (撤回按运行办理); links are never updated.
    retracts_id: Mapped[UUID | None]
    receipt_id: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "retracts_id"),
        ForeignKeyConstraint(
            ["tenant_id", "retracts_id"],
            ["scope_note_evidence.tenant_id", "scope_note_evidence.id"],
        ),
        ForeignKeyConstraint(["tenant_id", "run_id"], ["agent_runs.tenant_id", "agent_runs.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "note_id", "revision"],
            ["scope_note_versions.tenant_id", "scope_note_versions.note_id",
             "scope_note_versions.revision"],
            deferrable=True, initially="DEFERRED",
        ),
        _principal("writer_id"),
        CheckConstraint(
            f"source_type IN ({_in(SOURCES)}) AND stance IN ({_in(STANCES)}) AND "
            f"((source_type='business_object') = (source_kind IS NOT NULL)) AND "
            f"(source_kind IS NULL OR source_kind IN ({_in(FORMALS)})) AND "
            "jsonb_typeof(locator)='object' AND (quote_sha256 IS NULL OR quote_sha256 ~ '^[0-9a-f]{64}$')",
            name="scope_note_evidence_shape",
        ),
        Index("ix_scope_note_evidence_note", "tenant_id", "note_id", "revision"),
        Index("ix_scope_note_evidence_run", "tenant_id", "run_id"),
    )


class ScopeNoteRelation(Row, Base):
    """关系: 替代 / 冲突 / 重复 / 细化 / 派生自, between two notes of one category."""

    __tablename__ = "scope_note_relations"
    category_id: Mapped[UUID] = mapped_column(index=True)
    from_note_id: Mapped[UUID]
    to_note_id: Mapped[UUID]
    type: Mapped[str] = mapped_column(String(16))
    created_by: Mapped[UUID]
    receipt_id: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "from_note_id", "to_note_id", "type"),
        ForeignKeyConstraint(["tenant_id", "from_note_id"], ["scope_notes.tenant_id", "scope_notes.id"]),
        ForeignKeyConstraint(["tenant_id", "to_note_id"], ["scope_notes.tenant_id", "scope_notes.id"]),
        _principal("created_by"),
        CheckConstraint(
            f"type IN ({_in(RELATIONS)}) AND from_note_id<>to_note_id", name="scope_note_relation_type"
        ),
        Index("ix_scope_note_relations_to", "tenant_id", "to_note_id"),
    )
