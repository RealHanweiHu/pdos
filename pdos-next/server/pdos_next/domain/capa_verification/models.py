"""Append-only declarations; host owns registration, migration and atomic receipt guards."""

from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


class _Basis:
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    issue_id: Mapped[UUID]
    issue_version_id: Mapped[UUID]
    issue_revision: Mapped[int] = mapped_column(Integer)
    capa_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    writer_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(Text)
    nature: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    basis_snapshot: Mapped[dict] = mapped_column(JSONB)
    basis_sha256: Mapped[str] = mapped_column(String(64))
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    intent_digest: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)


def _constraints():
    return (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "project_id", "issue_id", "capa_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "owner_id", "intent_digest"),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "issue_id",
                "issue_version_id",
                "issue_revision",
            ],
            [
                "quality_issue_versions.tenant_id",
                "quality_issue_versions.product_id",
                "quality_issue_versions.project_id",
                "quality_issue_versions.issue_id",
                "quality_issue_versions.id",
                "quality_issue_versions.revision",
            ],
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(["tenant_id", "writer_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint(
            "revision=1 AND issue_revision>0 AND visibility IN ('private','category','audience')"
        ),
        CheckConstraint("nature IN ('real','synthetic')"),
        CheckConstraint(
            "COALESCE(jsonb_typeof(required_source_read_set)='array' "
            "AND jsonb_array_length(required_source_read_set)>0,false)"
        ),
        CheckConstraint(
            "COALESCE(basis_snapshot->>'issue_id'=issue_id::text "
            "AND basis_snapshot->>'issue_version_id'=issue_version_id::text "
            "AND (basis_snapshot->>'issue_revision')::integer=issue_revision "
            "AND basis_snapshot->>'capa_id'=capa_id::text "
            "AND basis_snapshot->>'purpose'=purpose "
            "AND basis_snapshot->>'nature'=nature "
            "AND basis_snapshot->'scope'->>'tenant_id'=tenant_id::text "
            "AND basis_snapshot->'scope'->>'product_id'=product_id::text "
            "AND basis_snapshot->'scope'->>'project_id'=project_id::text,false)"
        ),
    )


class RemediationLinkRecord(_Basis, Row, Base):
    __tablename__ = "capa_remediation_links"
    action_id: Mapped[UUID]
    output_snapshot: Mapped[dict] = mapped_column(JSONB)
    resolution_sha256: Mapped[str] = mapped_column(String(64))
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    policy_snapshot: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="recorded")
    __table_args__ = (
        *_constraints(),
        CheckConstraint("status='recorded'"),
        CheckConstraint(
            "COALESCE(input_snapshot->'shared_proof'->>'tier'='T1' "
            "AND input_snapshot->'shared_proof'->>'id' ~ "
            "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',false) "
            "AND NOT (input_snapshot ? 'confirmation_token') "
            "AND NOT (input_snapshot ? 'approval_token')"
        ),
        CheckConstraint(
            "COALESCE(output_snapshot->>'action_id'=action_id::text "
            "AND output_snapshot->>'resolution_sha256'=resolution_sha256,false)"
        ),
    )


class CapaVerificationEvidence(_Basis, Row, Base):
    """A candidate, never a positive PolicyPort.verification or closure assertion."""

    __tablename__ = "capa_verification_evidence"
    remediation_link_id: Mapped[UUID | None]
    candidate_binding: Mapped[dict] = mapped_column(JSONB)
    binding_sha256: Mapped[str] = mapped_column(String(64))
    candidate_snapshot: Mapped[dict] = mapped_column(JSONB)
    inspection_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="candidate")
    result: Mapped[str] = mapped_column(String(24), default="indeterminate")
    applicable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    independently_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    observation_complete: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    __table_args__ = (
        *_constraints(),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "issue_id", "capa_id", "remediation_link_id"],
            [
                "capa_remediation_links.tenant_id",
                "capa_remediation_links.product_id",
                "capa_remediation_links.project_id",
                "capa_remediation_links.issue_id",
                "capa_remediation_links.capa_id",
                "capa_remediation_links.id",
            ],
        ),
        CheckConstraint(
            "status='candidate' AND result='indeterminate' AND applicable IS NULL "
            "AND independently_verified IS NULL AND observation_complete IS NULL"
        ),
        CheckConstraint(
            "COALESCE(candidate_snapshot->>'result'='indeterminate' "
            "AND candidate_snapshot->'applicable'='null'::jsonb "
            "AND candidate_snapshot->'independently_verified'='null'::jsonb "
            "AND candidate_snapshot->'observation_complete'='null'::jsonb,false)"
        ),
    )
