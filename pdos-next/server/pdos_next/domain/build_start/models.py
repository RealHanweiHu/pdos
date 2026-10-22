"""Immutable execution facts; host owns monotonic pointer triggers and migration."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
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


def build_fk():
    return ForeignKeyConstraint(
        [
            "tenant_id",
            "product_id",
            "project_id",
            "build_id",
            "engineering_configuration_id",
            "manufacturing_configuration_id",
        ],
        [
            "builds.tenant_id",
            "builds.product_id",
            "builds.project_id",
            "builds.id",
            "builds.engineering_configuration_id",
            "builds.manufacturing_configuration_id",
        ],
    )


def owner_fk():
    return ForeignKeyConstraint(
        ["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]
    )


class BuildExecutionAssessment(Row, Base):
    __tablename__ = "build_execution_assessments"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    build_revision: Mapped[int] = mapped_column(Integer)
    engineering_configuration_id: Mapped[UUID]
    manufacturing_configuration_id: Mapped[UUID]
    engineering_configuration_revision: Mapped[int] = mapped_column(Integer)
    manufacturing_configuration_revision: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    previous_assessment_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32))
    execution_scope: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict] = mapped_column(JSONB)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    intent_digest: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "build_id", "revision"),
        UniqueConstraint("tenant_id", "product_id", "project_id", "build_id", "id", "revision"),
        build_fk(),
        owner_fk(),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "build_id",
                "previous_assessment_id",
                "previous_revision",
            ],
            [
                f"build_execution_assessments.{key}"
                for key in ("tenant_id", "product_id", "project_id", "build_id", "id", "revision")
            ],
        ),
        CheckConstraint(
            "revision > 0 AND build_revision > 0 AND engineering_configuration_revision > 0 "
            "AND manufacturing_configuration_revision > 0"
        ),
        CheckConstraint(
            "status IN ('UNKNOWN','BLOCKED','READY_WITH_CONDITIONS','READY') "
            "AND visibility IN ('private','category','audience')"
        ),
        CheckConstraint(
            "(revision = 1 AND previous_assessment_id IS NULL AND previous_revision IS NULL) "
            "OR (previous_assessment_id IS NOT NULL AND previous_assessment_id <> id "
            "AND previous_revision IS NOT NULL AND revision = previous_revision + 1)"
        ),
    )


class BuildAssessmentCurrent(Row, Base):
    __tablename__ = "build_current_execution_assessments"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    assessment_id: Mapped[UUID]
    assessment_revision: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "build_id"),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "build_id",
                "assessment_id",
                "assessment_revision",
            ],
            [
                f"build_execution_assessments.{key}"
                for key in ("tenant_id", "product_id", "project_id", "build_id", "id", "revision")
            ],
        ),
        CheckConstraint("assessment_revision > 0"),
    )


class BuildAuthorizationDecision(Row, Base):
    __tablename__ = "build_authorization_decisions"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    engineering_configuration_id: Mapped[UUID]
    manufacturing_configuration_id: Mapped[UUID]
    role: Mapped[str] = mapped_column(String(24))
    revision: Mapped[int] = mapped_column(Integer)
    previous_decision_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    assessment_id: Mapped[UUID]
    assessment_revision: Mapped[int] = mapped_column(Integer)
    assessment_sha256: Mapped[str] = mapped_column(String(64))
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    fact_binding: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    intent_digest: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "build_id", "role", "revision"),
        UniqueConstraint(
            "tenant_id", "product_id", "project_id", "build_id", "role", "id", "revision"
        ),
        build_fk(),
        owner_fk(),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "build_id",
                "assessment_id",
                "assessment_revision",
            ],
            [
                f"build_execution_assessments.{key}"
                for key in ("tenant_id", "product_id", "project_id", "build_id", "id", "revision")
            ],
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "build_id",
                "role",
                "previous_decision_id",
                "previous_revision",
            ],
            [
                f"build_authorization_decisions.{key}"
                for key in (
                    "tenant_id",
                    "product_id",
                    "project_id",
                    "build_id",
                    "role",
                    "id",
                    "revision",
                )
            ],
        ),
        CheckConstraint(
            "role IN ('engineering','manufacturing') AND revision > 0 AND assessment_revision > 0"
        ),
        CheckConstraint(
            "visibility IN ('private','category','audience') AND "
            "((action = 'approve' AND status = 'approved') "
            "OR (action = 'revoke' AND status = 'revoked'))"
        ),
        CheckConstraint(
            "(revision = 1 AND previous_decision_id IS NULL AND previous_revision IS NULL) "
            "OR (previous_decision_id IS NOT NULL AND previous_decision_id <> id "
            "AND previous_revision IS NOT NULL AND revision = previous_revision + 1)"
        ),
    )


class BuildAuthorizationCurrent(Row, Base):
    __tablename__ = "build_current_authorizations"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    role: Mapped[str] = mapped_column(String(24))
    decision_id: Mapped[UUID]
    decision_revision: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "build_id", "role"),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "build_id",
                "role",
                "decision_id",
                "decision_revision",
            ],
            [
                f"build_authorization_decisions.{key}"
                for key in (
                    "tenant_id",
                    "product_id",
                    "project_id",
                    "build_id",
                    "role",
                    "id",
                    "revision",
                )
            ],
        ),
        CheckConstraint("decision_revision > 0 AND role IN ('engineering','manufacturing')"),
    )


class BuildStart(Row, Base):
    __tablename__ = "build_starts"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    build_revision: Mapped[int] = mapped_column(Integer)
    engineering_configuration_id: Mapped[UUID]
    manufacturing_configuration_id: Mapped[UUID]
    assessment_id: Mapped[UUID]
    assessment_revision: Mapped[int] = mapped_column(Integer)
    assessment_sha256: Mapped[str] = mapped_column(String(64))
    engineering_authorization_id: Mapped[UUID]
    engineering_authorization_revision: Mapped[int] = mapped_column(Integer)
    manufacturing_authorization_id: Mapped[UUID]
    manufacturing_authorization_revision: Mapped[int] = mapped_column(Integer)
    engineering_role: Mapped[str] = mapped_column(String(24), default="engineering")
    manufacturing_role: Mapped[str] = mapped_column(String(24), default="manufacturing")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="executing")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    occurred_timezone: Mapped[str] = mapped_column(String(160))
    execution_scope: Mapped[dict] = mapped_column(JSONB)
    event_source: Mapped[dict] = mapped_column(JSONB)
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    reservations: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    intent_digest: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "project_id", "build_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "build_id"),
        build_fk(),
        owner_fk(),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "build_id",
                "assessment_id",
                "assessment_revision",
            ],
            [
                f"build_execution_assessments.{key}"
                for key in ("tenant_id", "product_id", "project_id", "build_id", "id", "revision")
            ],
        ),
        *[
            ForeignKeyConstraint(
                [
                    "tenant_id",
                    "product_id",
                    "project_id",
                    "build_id",
                    f"{role}_role",
                    f"{role}_authorization_id",
                    f"{role}_authorization_revision",
                ],
                [
                    f"build_authorization_decisions.{key}"
                    for key in (
                        "tenant_id",
                        "product_id",
                        "project_id",
                        "build_id",
                        "role",
                        "id",
                        "revision",
                    )
                ],
            )
            for role in ("engineering", "manufacturing")
        ],
        CheckConstraint(
            "revision = 1 AND status = 'executing' "
            "AND build_revision > 0 AND assessment_revision > 0"
        ),
        CheckConstraint(
            "visibility IN ('private','category','audience') AND engineering_role = 'engineering' "
            "AND manufacturing_role = 'manufacturing'"
        ),
    )
