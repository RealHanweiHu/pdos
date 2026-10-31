"""Ancillary provenance/review facts and explicitly shared gaps, never mirrored knowledge."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


def scoped():
    return (
        ForeignKeyConstraint(
            ["tenant_id", "category_id"], ["categories.tenant_id", "categories.id"]
        ),
        UniqueConstraint("tenant_id", "id"),
    )


class KnowledgeAnswerReview(Row, Base):
    __tablename__ = "knowledge_answer_reviews"
    category_id: Mapped[UUID] = mapped_column(index=True)
    subject_kind: Mapped[str] = mapped_column(Text)
    subject_id: Mapped[UUID]
    responsible_id: Mapped[UUID]
    applicability_scope: Mapped[str] = mapped_column(Text)
    review_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    origin_run_id: Mapped[UUID | None]
    answer_digest: Mapped[str | None] = mapped_column(Text)
    source_proof: Mapped[list] = mapped_column(JSONB)
    basis_count: Mapped[int]
    verified_by: Mapped[UUID | None]
    command_id: Mapped[UUID]
    receipt_id: Mapped[UUID]
    __table_args__ = (
        *scoped(),
        UniqueConstraint("tenant_id", "subject_kind", "subject_id"),
        ForeignKeyConstraint(
            ["tenant_id", "responsible_id"], ["principals.tenant_id", "principals.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "verified_by"], ["principals.tenant_id", "principals.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "origin_run_id"], ["agent_runs.tenant_id", "agent_runs.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["action_receipts.tenant_id", "action_receipts.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("subject_kind IN ('category','candidate','rule')"),
        CheckConstraint("length(applicability_scope)>0 AND jsonb_typeof(source_proof)='array'"),
        CheckConstraint("basis_count>=jsonb_array_length(source_proof) AND basis_count>=0"),
        CheckConstraint("(origin_run_id IS NULL)=(answer_digest IS NULL)"),
        CheckConstraint("answer_digest IS NULL OR answer_digest ~ '^[a-f0-9]{64}$'"),
    )


class KnowledgeGapSubmission(Row, Base):
    __tablename__ = "knowledge_gap_submissions"
    category_id: Mapped[UUID] = mapped_column(index=True)
    owner_id: Mapped[UUID]
    recipient_id: Mapped[UUID]
    run_id: Mapped[UUID]
    feedback_id: Mapped[UUID | None]
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    search_scope: Mapped[dict] = mapped_column(JSONB)
    source_proof: Mapped[list] = mapped_column(JSONB)
    __table_args__ = (
        *scoped(),
        UniqueConstraint("tenant_id", "owner_id", "request_key"),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "recipient_id"], ["principals.tenant_id", "principals.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "run_id"], ["agent_runs.tenant_id", "agent_runs.id"]),
        ForeignKeyConstraint(["feedback_id"], ["agent_run_events.id"]),
        CheckConstraint("kind IN ('missing_material','shared_feedback')"),
        CheckConstraint(
            "length(question)>0 AND jsonb_typeof(search_scope)='object' "
            "AND jsonb_typeof(source_proof)='array'"
        ),
        CheckConstraint(
            "(kind='shared_feedback')=(feedback_id IS NOT NULL AND answer IS NOT NULL)"
        ),
    )


class KnowledgeGapAttribution(Row, Base):
    __tablename__ = "knowledge_gap_attributions"
    category_id: Mapped[UUID] = mapped_column(index=True)
    submission_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    request_key: Mapped[UUID]
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        *scoped(),
        UniqueConstraint("tenant_id", "actor_id", "request_key"),
        ForeignKeyConstraint(
            ["tenant_id", "submission_id"],
            ["knowledge_gap_submissions.tenant_id", "knowledge_gap_submissions.id"],
        ),
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint(
            "reason IN ('missing_material','version_conflict','unclear_content',"
            "'retrieval_miss','answer_problem')"
        ),
    )
