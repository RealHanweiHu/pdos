"""Scoped experience candidates and explicitly published, versioned rules.

Category candidates need no fabricated product/project. Publication and its
assessment belong to one actual project and one named T2 transaction.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row

CANDIDATE = "knowledge_candidate_versions"
CANDIDATE_CURRENT = "knowledge_candidate_currents"
ASSESSMENT = "knowledge_applicability_assessments"
RULE = "knowledge_rule_versions"
RULE_CURRENT = "knowledge_rule_currents"
CANDIDATE_OP = "knowledge.candidate.create"
RULE_OP = "knowledge.rule.publish"
CANDIDATE_SUBJECT = "knowledge_candidate"
RULE_SUBJECT = "design_rule"
CANDIDATE_EVENT = "knowledge.candidate_created"
RULE_EVENT = "knowledge.rule_published"
SCOPE = ("tenant_id", "category_id", "product_id", "project_id", "owner_id", "visibility")


def _fk(local, table, remote, **options):
    return ForeignKeyConstraint(list(local), [f"{table}.{key}" for key in remote], **options)


def _scope():
    return (
        _fk(("tenant_id", "category_id"), "categories", ("tenant_id", "id")),
        _fk(
            ("tenant_id", "category_id", "product_id"),
            "products",
            ("tenant_id", "category_id", "id"),
        ),
        _fk(
            ("tenant_id", "product_id", "project_id"),
            "projects",
            ("tenant_id", "product_id", "id"),
        ),
        _fk(("tenant_id", "owner_id"), "principals", ("tenant_id", "id")),
        CheckConstraint("visibility IN ('private','category')"),
        CheckConstraint("project_id IS NULL OR product_id IS NOT NULL"),
    )


def _fact():
    return (
        *_scope(),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "category_id", "id", "revision"),
        UniqueConstraint("tenant_id", "receipt_id"),
        UniqueConstraint("tenant_id", "command_id"),
        UniqueConstraint("tenant_id", "category_id", "actor_id", "operation", "intent_digest"),
        *(
            _fk(("tenant_id", name), "principals", ("tenant_id", "id"))
            for name in ("writer_id", "actor_id", "requester_id")
        ),
        *(
            _fk(
                ("tenant_id", name),
                table,
                ("tenant_id", "id"),
                deferrable=True,
                initially="DEFERRED",
            )
            for name, table in (
                ("receipt_id", "action_receipts"),
                ("confirmation_id", "confirmations"),
            )
        ),
        CheckConstraint("writer_id=actor_id AND revision>0"),
        CheckConstraint(
            "jsonb_typeof(command)='object' AND jsonb_typeof(body)='object' "
            "AND jsonb_typeof(source_basis)='object' AND jsonb_typeof(sources)='array' "
            "AND jsonb_typeof(reads)='array' AND jsonb_array_length(sources)>0 "
            "AND jsonb_array_length(reads)>0"
        ),
        CheckConstraint(
            "body_sha256 ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$' "
            "AND intent_digest ~ '^[a-f0-9]{64}$'"
        ),
    )


class _Scope(Row):
    category_id: Mapped[UUID] = mapped_column(index=True)
    product_id: Mapped[UUID | None]
    project_id: Mapped[UUID | None]
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))


class _Fact(_Scope):
    revision: Mapped[int] = mapped_column(Integer)
    writer_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    requester_id: Mapped[UUID]
    operation: Mapped[str] = mapped_column(String(80))
    command_id: Mapped[UUID]
    command: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    reads: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    body: Mapped[dict] = mapped_column(JSONB)
    body_sha256: Mapped[str] = mapped_column(String(64))
    intent_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    receipt_id: Mapped[UUID]
    confirmation_id: Mapped[UUID | None]


class KnowledgeCandidateVersion(_Fact, Base):
    __tablename__ = CANDIDATE
    candidate_id: Mapped[UUID]
    previous_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)

    @property
    def status(self):
        return "draft"

    __table_args__ = (
        *_fact(),
        UniqueConstraint("tenant_id", "category_id", "candidate_id", "revision"),
        UniqueConstraint("tenant_id", "category_id", "candidate_id", "id", "revision"),
        _fk(
            ("tenant_id", "category_id", "candidate_id", "previous_id", "previous_revision"),
            CANDIDATE,
            ("tenant_id", "category_id", "candidate_id", "id", "revision"),
        ),
        CheckConstraint(
            "(revision=1 AND candidate_id=id AND previous_id IS NULL "
            "AND previous_revision IS NULL) OR (revision>1 AND previous_id IS NOT NULL "
            "AND previous_id<>id AND previous_revision=revision-1)",
            name="knowledge_candidate_chain",
        ),
        CheckConstraint(
            "operation='knowledge.candidate.create' AND confirmation_id IS NULL",
            name="knowledge_candidate_t0_only",
        ),
    )


class KnowledgeCandidateCurrent(_Scope, Base):
    __tablename__ = CANDIDATE_CURRENT
    candidate_id: Mapped[UUID]
    version_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "category_id", "candidate_id"),
        _fk(
            ("tenant_id", "category_id", "candidate_id", "version_id", "revision"),
            CANDIDATE,
            ("tenant_id", "category_id", "candidate_id", "id", "revision"),
        ),
        CheckConstraint("revision>0", name="knowledge_candidate_current_revision"),
    )


class ApplicabilityAssessment(_Scope, Base):
    __tablename__ = ASSESSMENT
    publication_id: Mapped[UUID]
    candidate_version_id: Mapped[UUID]
    candidate_revision: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[UUID]
    body: Mapped[dict] = mapped_column(JSONB)
    body_sha256: Mapped[str] = mapped_column(String(64))
    receipt_id: Mapped[UUID]
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "publication_id"),
        UniqueConstraint("tenant_id", "id", "publication_id"),
        _fk(
            ("tenant_id", "category_id", "candidate_version_id", "candidate_revision"),
            CANDIDATE,
            ("tenant_id", "category_id", "id", "revision"),
        ),
        _fk(("tenant_id", "actor_id"), "principals", ("tenant_id", "id")),
        _fk(
            ("tenant_id", "receipt_id"),
            "action_receipts",
            ("tenant_id", "id"),
            deferrable=True,
            initially="DEFERRED",
        ),
        _fk(
            ("tenant_id", "publication_id", "id"),
            RULE,
            ("tenant_id", "id", "assessment_id"),
            name="knowledge_assessment_publication_fk",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "product_id IS NOT NULL AND project_id IS NOT NULL "
            "AND candidate_revision>0 AND jsonb_typeof(body)='object' "
            "AND body_sha256 ~ '^[a-f0-9]{64}$'",
            name="knowledge_assessment_fixed_scope",
        ),
    )


class DesignRuleVersion(_Fact, Base):
    __tablename__ = RULE
    rule_id: Mapped[UUID]
    candidate_id: Mapped[UUID]
    candidate_version_id: Mapped[UUID]
    candidate_revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    assessment_id: Mapped[UUID]
    nature: Mapped[str] = mapped_column(String(16))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def status(self):
        return "published"

    __table_args__ = (
        *_fact(),
        UniqueConstraint("tenant_id", "category_id", "rule_id", "revision"),
        UniqueConstraint("tenant_id", "category_id", "rule_id", "id", "revision"),
        UniqueConstraint("tenant_id", "id", "assessment_id"),
        _fk(
            ("tenant_id", "category_id", "rule_id", "previous_id", "previous_revision"),
            RULE,
            ("tenant_id", "category_id", "rule_id", "id", "revision"),
        ),
        _fk(
            (
                "tenant_id",
                "category_id",
                "candidate_id",
                "candidate_version_id",
                "candidate_revision",
            ),
            CANDIDATE,
            ("tenant_id", "category_id", "candidate_id", "id", "revision"),
        ),
        _fk(
            ("tenant_id", "assessment_id", "id"),
            ASSESSMENT,
            ("tenant_id", "id", "publication_id"),
            name="knowledge_rule_assessment_fk",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "(revision=1 AND rule_id=id AND previous_id IS NULL AND previous_revision IS NULL) "
            "OR (revision>1 AND previous_id IS NOT NULL AND previous_id<>id "
            "AND previous_revision=revision-1)",
            name="knowledge_rule_chain",
        ),
        CheckConstraint(
            "operation='knowledge.rule.publish' AND confirmation_id IS NOT NULL "
            "AND writer_id=actor_id AND actor_id=requester_id",
            name="knowledge_rule_t2_only",
        ),
        CheckConstraint(
            "product_id IS NOT NULL AND project_id IS NOT NULL AND candidate_revision>0 "
            "AND nature IN ('real','synthetic') "
            "AND (valid_until IS NULL OR valid_from<valid_until)",
            name="knowledge_rule_fixed_scope",
        ),
    )


class DesignRuleCurrent(_Scope, Base):
    __tablename__ = RULE_CURRENT
    rule_id: Mapped[UUID]
    version_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "category_id", "rule_id"),
        _fk(
            ("tenant_id", "category_id", "rule_id", "version_id", "revision"),
            RULE,
            ("tenant_id", "category_id", "rule_id", "id", "revision"),
        ),
        CheckConstraint(
            "product_id IS NOT NULL AND project_id IS NOT NULL AND revision>0",
            name="knowledge_rule_current_scope",
        ),
    )
