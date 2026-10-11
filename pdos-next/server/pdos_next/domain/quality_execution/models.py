"""Immutable Issue/Policy versions and scoped pointers; root registers/migrates."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


def project_fk():
    return ForeignKeyConstraint(
        ["tenant_id", "product_id", "project_id"],
        ["projects.tenant_id", "projects.product_id", "projects.id"],
    )


def issue_fk(id_column="issue_version_id", revision_column="issue_revision"):
    columns = ("tenant_id", "product_id", "project_id", "issue_id", "id", "revision")
    return ForeignKeyConstraint(
        ["tenant_id", "product_id", "project_id", "issue_id", id_column, revision_column],
        [f"quality_issue_versions.{c}" for c in columns],
    )


class QualityIssueVersion(Row, Base):
    __tablename__ = "quality_issue_versions"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    issue_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    previous_issue_version_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    writer_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    operation: Mapped[str] = mapped_column(String(80))
    issue_snapshot: Mapped[dict] = mapped_column(JSONB)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    policy_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    intent_digest: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        project_fk(),
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "project_id", "issue_id", "revision"),
        UniqueConstraint("tenant_id", "product_id", "project_id", "issue_id", "id", "revision"),
        issue_fk("previous_issue_version_id", "previous_revision"),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(["tenant_id", "writer_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("revision>0 AND visibility IN ('private','category','audience')"),
        CheckConstraint("status IN ('open','triaged','actioning','awaiting_verification')"),
        CheckConstraint(
            "operation IN ('quality.issue.create','quality.issue.merge','quality.issue.triage',"
            "'quality.issue.containment.record','quality.capa.draft',"
            "'quality.issue.root_cause.decide','quality.capa.actions.complete')"
        ),
        CheckConstraint(
            "jsonb_typeof(required_source_read_set)='array' "
            "AND jsonb_array_length(required_source_read_set)>0"
        ),
        CheckConstraint(
            "(revision=1 AND previous_issue_version_id IS NULL AND previous_revision IS NULL) "
            "OR (previous_issue_version_id IS NOT NULL AND previous_revision IS NOT NULL "
            "AND previous_issue_version_id<>id "
            "AND revision=previous_revision+1)"
        ),
        CheckConstraint(
            "COALESCE(issue_snapshot->>'id'=issue_id::text "
            "AND (issue_snapshot->>'revision')::integer=revision "
            "AND issue_snapshot->>'status'=status,false)"
        ),
        CheckConstraint(
            "COALESCE(issue_snapshot->'scope'->>'tenant_id'=tenant_id::text "
            "AND issue_snapshot->'scope'->>'product_id'=product_id::text "
            "AND issue_snapshot->'scope'->>'project_id'=project_id::text,false)"
        ),
    )


class QualityIssueCurrent(Row, Base):
    __tablename__ = "quality_current_issues"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    issue_id: Mapped[UUID]
    issue_version_id: Mapped[UUID]
    issue_revision: Mapped[int] = mapped_column(Integer)
    epoch: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "project_id", "issue_id"),
        issue_fk(),
        CheckConstraint("issue_revision>0 AND epoch>0"),
    )


class QualityFailureMap(Row, Base):
    __tablename__ = "quality_failure_maps"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    failure_identity: Mapped[str] = mapped_column(String(64))
    issue_id: Mapped[UUID]
    epoch: Mapped[int] = mapped_column(Integer, default=1)
    failure: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "project_id", "failure_identity"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "issue_id"],
            [
                f"quality_current_issues.{c}"
                for c in ("tenant_id", "product_id", "project_id", "issue_id")
            ],
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("epoch>0 AND length(failure_identity)=64"),
        CheckConstraint(
            "COALESCE(failure->>'identity'=failure_identity "
            "AND failure->'build'->>'product_id'=product_id::text "
            "AND failure->'build'->>'project_id'=project_id::text,false)"
        ),
    )


class QualityEventFailureLink(Row, Base):
    __tablename__ = "quality_event_failure_links"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    issue_id: Mapped[UUID]
    issue_version_id: Mapped[UUID]
    issue_revision: Mapped[int] = mapped_column(Integer)
    event_id: Mapped[UUID]
    failure_identity: Mapped[str] = mapped_column(String(64))
    build_id: Mapped[UUID]
    request_id: Mapped[UUID]
    run_id: Mapped[UUID]
    run_version_id: Mapped[UUID]
    run_revision: Mapped[int] = mapped_column(Integer)
    measurement_id: Mapped[UUID]
    measurement_revision: Mapped[int] = mapped_column(Integer, default=1)
    projection_id: Mapped[UUID]
    projection_revision: Mapped[int] = mapped_column(Integer)
    basis_sha256: Mapped[str] = mapped_column(String(64))
    failure: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "project_id", "event_id", "failure_identity"),
        issue_fk(),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "build_id", "run_id"],
            [
                f"verification_run_identities.{c}"
                for c in ("tenant_id", "product_id", "project_id", "build_id", "id")
            ],
        ),
        *[
            ForeignKeyConstraint(
                [
                    "tenant_id",
                    "product_id",
                    "project_id",
                    "request_id",
                    "run_id",
                    identity,
                    revision,
                ],
                [
                    f"{table}.{c}"
                    for c in (
                        "tenant_id",
                        "product_id",
                        "project_id",
                        "request_id",
                        "run_id",
                        "id",
                        "revision",
                    )
                ],
            )
            for table, identity, revision in (
                ("verification_run_versions", "run_version_id", "run_revision"),
                ("test_measurements", "measurement_id", "measurement_revision"),
                ("test_result_projections", "projection_id", "projection_revision"),
            )
        ],
        ForeignKeyConstraint(
            ["tenant_id", "event_id"], ["outbox_events.tenant_id", "outbox_events.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "measurement_id"],
            ["test_measurements.tenant_id", "test_measurements.product_id", "test_measurements.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "projection_id"],
            [
                "test_result_projections.tenant_id",
                "test_result_projections.product_id",
                "test_result_projections.id",
            ],
        ),
        CheckConstraint("run_revision>2 AND issue_revision>0 AND projection_revision>0"),
        CheckConstraint("measurement_revision=1"),
        CheckConstraint(
            "COALESCE(failure->>'identity'=failure_identity "
            "AND failure->'run'->>'id'=run_id::text "
            "AND (failure->'run'->>'revision')::integer=run_revision "
            "AND failure->>'measurement_id'=measurement_id::text "
            "AND failure->'build'->>'id'=build_id::text "
            "AND failure->'build'->>'product_id'=product_id::text "
            "AND failure->'build'->>'project_id'=project_id::text,false)"
        ),
        CheckConstraint(
            "jsonb_typeof(required_source_read_set)='array' "
            "AND jsonb_array_length(required_source_read_set)>0"
        ),
    )


class QualityPolicyFact(Row, Base):
    __tablename__ = "quality_policy_facts"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    purpose: Mapped[str] = mapped_column(Text)
    series_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    risk: Mapped[str] = mapped_column(String(16))
    independent_verification: Mapped[bool] = mapped_column(Boolean)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    issuer_key: Mapped[str] = mapped_column(String(100))
    issuer_version: Mapped[str] = mapped_column(String(100))
    issuer_epoch: Mapped[int] = mapped_column(Integer)
    nature: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(200))
    data: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    fact_sha256: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        project_fk(),
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint(
            "tenant_id", "product_id", "project_id", "purpose", "series_id", "id", "revision"
        ),
        UniqueConstraint(
            "tenant_id", "product_id", "project_id", "purpose", "series_id", "revision"
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "purpose",
                "series_id",
                "previous_id",
                "previous_revision",
            ],
            [
                f"quality_policy_facts.{c}"
                for c in (
                    "tenant_id",
                    "product_id",
                    "project_id",
                    "purpose",
                    "series_id",
                    "id",
                    "revision",
                )
            ],
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint(
            "nature='synthetic' AND status IN ('active','withdrawn') "
            "AND risk IN ('low','medium','high','critical')"
        ),
        CheckConstraint(
            "revision>0 AND issuer_epoch>0 AND valid_until>valid_from "
            "AND visibility IN ('private','category','audience')"
        ),
        CheckConstraint(
            "(revision=1 AND previous_id IS NULL AND previous_revision IS NULL AND series_id=id) "
            "OR (previous_id IS NOT NULL AND previous_revision IS NOT NULL "
            "AND previous_id<>id AND revision=previous_revision+1)"
        ),
        CheckConstraint(
            "jsonb_typeof(required_source_read_set)='array' "
            "AND jsonb_array_length(required_source_read_set)>0"
        ),
    )


class QualityPolicyCurrent(Row, Base):
    __tablename__ = "quality_current_policies"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    purpose: Mapped[str] = mapped_column(Text)
    series_id: Mapped[UUID]
    fact_id: Mapped[UUID]
    fact_revision: Mapped[int] = mapped_column(Integer)
    issuer_key: Mapped[str] = mapped_column(String(100))
    external_id: Mapped[str] = mapped_column(String(200))
    epoch: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "product_id", "project_id", "purpose", "issuer_key", "external_id"
        ),
        UniqueConstraint("tenant_id", "product_id", "project_id", "purpose", "series_id"),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "purpose",
                "series_id",
                "fact_id",
                "fact_revision",
            ],
            [
                f"quality_policy_facts.{c}"
                for c in (
                    "tenant_id",
                    "product_id",
                    "project_id",
                    "purpose",
                    "series_id",
                    "id",
                    "revision",
                )
            ],
        ),
        CheckConstraint("epoch>0 AND fact_revision>0"),
    )
