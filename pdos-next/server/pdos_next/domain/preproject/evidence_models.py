"""M3 evidence append-only records; import only when activating the evidence slice.

The migration/command layer enforces immutable rows. Evidence links may only gain
a reverted receipt; single-Claim withdrawal is represented by a separate record.
Polymorphic source and target references are validated by the command transaction.
"""

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


def _receipt_fk(column):
    return ForeignKeyConstraint(
        ["tenant_id", column],
        ["action_receipts.tenant_id", "action_receipts.id"],
        deferrable=True,
        initially="DEFERRED",
    )


def _principal_fk(column):
    return ForeignKeyConstraint(["tenant_id", column], ["principals.tenant_id", "principals.id"])


class EvidenceLink(Row, Base):
    __tablename__ = "evidence_links"
    category_id: Mapped[UUID] = mapped_column(index=True)
    evidence_type: Mapped[str] = mapped_column(Text)
    evidence_id: Mapped[UUID]
    evidence_version: Mapped[int]
    evidence_locator: Mapped[str | None] = mapped_column(Text)
    target_type: Mapped[str] = mapped_column(Text)
    target_id: Mapped[UUID]
    target_version: Mapped[int]
    relation: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text)
    writer_id: Mapped[UUID]
    run_id: Mapped[UUID | None]
    confirmed_by: Mapped[UUID | None]
    receipt_id: Mapped[UUID]
    reverted_by_receipt_id: Mapped[UUID | None]
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "category_id"], ["categories.tenant_id", "categories.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "run_id"],
            ["agent_runs.tenant_id", "agent_runs.category_id", "agent_runs.id"],
        ),
        _principal_fk("writer_id"),
        _principal_fk("confirmed_by"),
        _receipt_fk("receipt_id"),
        _receipt_fk("reverted_by_receipt_id"),
        UniqueConstraint("tenant_id", "category_id", "id"),
        Index(
            "ix_evidence_links_target",
            "tenant_id",
            "category_id",
            "target_type",
            "target_id",
            "target_version",
        ),
        Index(
            "ix_evidence_links_source",
            "tenant_id",
            "category_id",
            "evidence_type",
            "evidence_id",
        ),
        CheckConstraint("evidence_type IN ('claim','snapshot','artifact')"),
        CheckConstraint("target_type IN ('proposal_item','knowledge_entry','definition_spec')"),
        CheckConstraint("evidence_version>0 AND target_version>0"),
        CheckConstraint("length(trim(relation))>0"),
        CheckConstraint(
            "origin IN ('human','ai_draft','imported') "
            "AND (origin<>'ai_draft' OR run_id IS NOT NULL)"
        ),
    )


class ClaimWithdrawal(Row, Base):
    __tablename__ = "claim_withdrawals"
    category_id: Mapped[UUID] = mapped_column(index=True)
    claim_id: Mapped[UUID]
    expected_version: Mapped[int]
    reason: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[UUID]
    confirmation_id: Mapped[UUID]
    receipt_id: Mapped[UUID]
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "claim_id"],
            ["claims.tenant_id", "claims.category_id", "claims.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "confirmation_id"], ["confirmations.tenant_id", "confirmations.id"]
        ),
        _principal_fk("actor_id"),
        _receipt_fk("receipt_id"),
        UniqueConstraint("tenant_id", "category_id", "id"),
        UniqueConstraint("tenant_id", "category_id", "claim_id"),
        UniqueConstraint("tenant_id", "confirmation_id"),
        CheckConstraint("expected_version>0 AND length(trim(reason))>0"),
    )


TABLES = (EvidenceLink.__table__, ClaimWithdrawal.__table__)
