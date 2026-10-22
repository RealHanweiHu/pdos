"""M3-owned tables, loaded lazily so unfinished S0 metadata checks stay independent."""

from datetime import date
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.agent_kernel.models import AgentRun  # noqa: F401 -- lazy FK metadata
from pdos_next.models import Base, Row


class PreparedCandidate(Row, Base):
    __tablename__ = "proposal_prepared_candidates"
    category_id: Mapped[UUID] = mapped_column(index=True)
    requester_id: Mapped[UUID]
    writer_id: Mapped[UUID]
    run_id: Mapped[UUID]
    operation: Mapped[str] = mapped_column(Text)
    candidate_digest: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB)
    execution_binding: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "run_id", "candidate_digest"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "run_id"],
            ["agent_runs.tenant_id", "agent_runs.category_id", "agent_runs.id"],
        ),
        CheckConstraint(
            "operation IN ('proposal.create','proposal.item.patch','proposal.question.create',"
            "'category.knowledge.add','category.knowledge.withdraw','category.knowledge.promote',"
            "'category.parameter.publish','product.definition.item.patch','platform.link.create')"
        ),
    )


def category_fk():
    return ForeignKeyConstraint(
        ["tenant_id", "category_id"], ["categories.tenant_id", "categories.id"]
    )


def proposal_fk():
    return ForeignKeyConstraint(
        ["tenant_id", "category_id", "proposal_id"],
        ["proposals.tenant_id", "proposals.category_id", "proposals.id"],
    )


def principal_fk(column):
    return ForeignKeyConstraint(["tenant_id", column], ["principals.tenant_id", "principals.id"])


class Proposal(Row, Base):
    __tablename__ = "proposals"
    category_id: Mapped[UUID] = mapped_column(index=True)
    owner_id: Mapped[UUID]
    title: Mapped[str] = mapped_column(Text)
    brief: Mapped[str] = mapped_column(Text)
    entry_kind: Mapped[str] = mapped_column(Text)
    target_kind: Mapped[str] = mapped_column(Text)
    baseline_product_id: Mapped[UUID | None]
    baseline_definition_id: Mapped[UUID | None]
    baseline_definition_revision: Mapped[int | None]
    customer_identities: Mapped[list] = mapped_column(JSONB)
    visibility: Mapped[str] = mapped_column(Text, default="private")
    effective_visibility: Mapped[str] = mapped_column(Text, default="private")
    private_source_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(Text, default="draft")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    current_submission_id: Mapped[UUID | None]
    context_refs: Mapped[list] = mapped_column(JSONB)
    source_refs: Mapped[list] = mapped_column(JSONB)
    context_hint: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_run_id: Mapped[UUID | None]
    __table_args__ = (
        UniqueConstraint("tenant_id", "category_id", "id"),
        category_fk(),
        principal_fk("owner_id"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "baseline_product_id"],
            ["products.tenant_id", "products.category_id", "products.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "baseline_product_id", "baseline_definition_id"],
            [
                "definition_revisions.tenant_id",
                "definition_revisions.product_id",
                "definition_revisions.id",
            ],
        ),
        CheckConstraint("entry_kind IN ('customer_request','new_product','derivative')"),
        CheckConstraint("target_kind IN ('new_product','new_variant')"),
        CheckConstraint("visibility IN ('private','category','audience')"),
        CheckConstraint("effective_visibility IN ('private','category','audience')"),
        CheckConstraint("revision>0 AND private_source_count>=0"),
        CheckConstraint(
            "status IN ('draft','in_review','approved','returned','rejected','withdrawn')"
        ),
        CheckConstraint(
            "(entry_kind<>'derivative' AND target_kind<>'new_variant') OR "
            "(baseline_product_id IS NOT NULL AND baseline_definition_id IS NOT NULL "
            "AND baseline_definition_revision>0)"
        ),
    )


class ProposalItem(Row, Base):
    __tablename__ = "proposal_items"
    category_id: Mapped[UUID] = mapped_column(index=True)
    proposal_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(Text)
    current_version: Mapped[int] = mapped_column(Integer)
    removed: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_key: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("tenant_id", "category_id", "proposal_id", "id"),
        proposal_fk(),
        CheckConstraint("current_version>0"),
    )


class ProposalItemVersion(Row, Base):
    __tablename__ = "proposal_item_versions"
    category_id: Mapped[UUID] = mapped_column(index=True)
    proposal_id: Mapped[UUID]
    item_id: Mapped[UUID]
    version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text)
    content: Mapped[dict] = mapped_column(JSONB)
    source_refs: Mapped[list] = mapped_column(JSONB)
    origin: Mapped[str] = mapped_column(Text)
    writer_id: Mapped[UUID]
    run_id: Mapped[UUID | None]
    confirmed_by: Mapped[UUID | None]
    receipt_id: Mapped[UUID | None]
    prepared_candidate_id: Mapped[UUID | None]
    removed: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "prepared_candidate_id"],
            ["proposal_prepared_candidates.tenant_id", "proposal_prepared_candidates.id"],
        ),
        UniqueConstraint("tenant_id", "item_id", "version"),
        proposal_fk(),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "proposal_id", "item_id"],
            [
                "proposal_items.tenant_id",
                "proposal_items.category_id",
                "proposal_items.proposal_id",
                "proposal_items.id",
            ],
        ),
        principal_fk("writer_id"),
        principal_fk("confirmed_by"),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"], ["action_receipts.tenant_id", "action_receipts.id"]
        ),
        CheckConstraint("version>0 AND origin IN ('human','ai_draft','imported')"),
        CheckConstraint("origin<>'ai_draft' OR run_id IS NOT NULL"),
    )


class ProposalRevision(Row, Base):
    __tablename__ = "proposal_revisions"
    category_id: Mapped[UUID] = mapped_column(index=True)
    proposal_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    changed_items: Mapped[list] = mapped_column(JSONB)
    actor_id: Mapped[UUID]
    run_id: Mapped[UUID | None]
    receipt_id: Mapped[UUID | None]
    document_digest: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("tenant_id", "proposal_id", "revision"),
        proposal_fk(),
        principal_fk("actor_id"),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"], ["action_receipts.tenant_id", "action_receipts.id"]
        ),
        CheckConstraint("revision>0"),
    )


class ProposalSource(Row, Base):
    __tablename__ = "proposal_sources"
    category_id: Mapped[UUID] = mapped_column(index=True)
    proposal_id: Mapped[UUID]
    source_type: Mapped[str] = mapped_column(Text)
    source_id: Mapped[UUID]
    source_version: Mapped[int] = mapped_column(Integer)
    privacy: Mapped[str] = mapped_column(Text)
    ref_count: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        proposal_fk(),
        UniqueConstraint("tenant_id", "proposal_id", "source_type", "source_id", "source_version"),
        CheckConstraint("source_version>0 AND privacy IN ('private','shared')"),
        CheckConstraint("source_type IN ('original','snapshot','knowledge','definition')"),
        CheckConstraint("ref_count>0"),
    )


class ProposalSubmission(Row, Base):
    __tablename__ = "proposal_submissions"
    category_id: Mapped[UUID] = mapped_column(index=True)
    proposal_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    reviewer_id: Mapped[UUID]
    frozen_document: Mapped[dict] = mapped_column(JSONB)
    document_digest: Mapped[str] = mapped_column(Text)
    context_refs: Mapped[list] = mapped_column(JSONB)
    option_count: Mapped[int] = mapped_column(Integer)
    no_alternative_reason: Mapped[str | None] = mapped_column(Text)
    receipt_id: Mapped[UUID | None]
    __table_args__ = (
        proposal_fk(),
        principal_fk("owner_id"),
        principal_fk("reviewer_id"),
        UniqueConstraint("tenant_id", "proposal_id", "revision"),
        UniqueConstraint("tenant_id", "category_id", "proposal_id", "id"),
        UniqueConstraint("tenant_id", "id", "owner_id", "reviewer_id"),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"], ["action_receipts.tenant_id", "action_receipts.id"]
        ),
        CheckConstraint("revision>0 AND option_count>=0", name="proposal_submissions_check"),
    )


class ProposalDecision(Row, Base):
    __tablename__ = "proposal_decisions"
    category_id: Mapped[UUID] = mapped_column(index=True)
    proposal_id: Mapped[UUID]
    submission_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    decided_by: Mapped[UUID]
    outcome: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    selected_option_item_id: Mapped[UUID | None]
    dispositions: Mapped[list] = mapped_column(JSONB)
    creation: Mapped[dict] = mapped_column(JSONB)
    project_owner_id: Mapped[UUID | None]
    project_owner_audience_added: Mapped[bool] = mapped_column(Boolean)
    signer_grant_snapshot: Mapped[dict] = mapped_column(JSONB)
    review_digest: Mapped[str] = mapped_column(Text)
    created_product_id: Mapped[UUID | None]
    created_variant_id: Mapped[UUID | None]
    created_definition_id: Mapped[UUID | None]
    created_project_id: Mapped[UUID | None]
    receipt_id: Mapped[UUID | None]
    __table_args__ = (
        proposal_fk(),
        UniqueConstraint("tenant_id", "submission_id"),
        UniqueConstraint("tenant_id", "category_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "proposal_id", "submission_id"],
            [
                "proposal_submissions.tenant_id",
                "proposal_submissions.category_id",
                "proposal_submissions.proposal_id",
                "proposal_submissions.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "submission_id", "owner_id", "decided_by"],
            [
                "proposal_submissions.tenant_id",
                "proposal_submissions.id",
                "proposal_submissions.owner_id",
                "proposal_submissions.reviewer_id",
            ],
        ),
        principal_fk("project_owner_id"),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"], ["action_receipts.tenant_id", "action_receipts.id"]
        ),
        CheckConstraint("outcome IN ('approved','returned','rejected')"),
        CheckConstraint(
            "outcome<>'approved' OR (created_product_id IS NOT NULL "
            "AND created_definition_id IS NOT NULL AND created_project_id IS NOT NULL)"
        ),
    )


class ProjectOpenItem(Row, Base):
    __tablename__ = "project_open_items"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[UUID]
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text)
    source_question_id: Mapped[UUID | None]
    source_spec_item_id: Mapped[UUID | None]
    g0_decision_id: Mapped[UUID]
    __table_args__ = (
        category_fk(),
        principal_fk("owner_id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id"],
            ["projects.tenant_id", "projects.product_id", "projects.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "g0_decision_id"],
            [
                "proposal_decisions.tenant_id",
                "proposal_decisions.category_id",
                "proposal_decisions.id",
            ],
        ),
        CheckConstraint("kind IN ('task','risk') AND length(status)>0"),
        CheckConstraint("(source_question_id IS NULL)<>(source_spec_item_id IS NULL)"),
    )


TABLES = tuple(
    cls.__table__
    for cls in (
        PreparedCandidate,
        Proposal,
        ProposalItem,
        ProposalItemVersion,
        ProposalRevision,
        ProposalSource,
        ProposalSubmission,
        ProposalDecision,
        ProjectOpenItem,
    )
)

for _table in TABLES:
    for _foreign_key in _table.foreign_key_constraints:
        if _foreign_key.referred_table.name == "action_receipts":
            _foreign_key.deferrable, _foreign_key.initially = True, "DEFERRED"
