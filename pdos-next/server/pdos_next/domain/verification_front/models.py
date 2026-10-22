"""Immutable front-stage facts; host owns registration, migrations and transactions."""

from uuid import UUID

from sqlalchemy import (
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


def request_fk(*, project=False):
    return ForeignKeyConstraint(
        [
            "tenant_id",
            "product_id",
            *(["project_id"] if project else []),
            "request_id",
            "request_version_id",
            "request_revision",
        ],
        [
            "verification_formal_requests.tenant_id",
            "verification_formal_requests.product_id",
            *(["verification_formal_requests.project_id"] if project else []),
            "verification_formal_requests.request_id",
            "verification_formal_requests.id",
            "verification_formal_requests.revision",
        ],
    )


class FormalVerificationRequest(Row, Base):
    __tablename__ = "verification_formal_requests"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    build_revision: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    previous_request_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    operation: Mapped[str] = mapped_column(String(80))
    preparation_id: Mapped[UUID]
    preparation_revision: Mapped[int] = mapped_column(Integer)
    preparation_sha256: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(Text)
    request_snapshot: Mapped[dict] = mapped_column(JSONB)
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    intent_digest: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "request_id", "revision"),
        UniqueConstraint("tenant_id", "product_id", "request_id", "id", "revision"),
        UniqueConstraint("tenant_id", "product_id", "project_id", "request_id", "id", "revision"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "build_id"],
            ["builds.tenant_id", "builds.product_id", "builds.project_id", "builds.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "preparation_id"],
            [
                "verification_preparations.tenant_id",
                "verification_preparations.product_id",
                "verification_preparations.id",
            ],
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "request_id", "previous_request_id", "previous_revision"],
            [
                "verification_formal_requests.tenant_id",
                "verification_formal_requests.product_id",
                "verification_formal_requests.request_id",
                "verification_formal_requests.id",
                "verification_formal_requests.revision",
            ],
        ),
        CheckConstraint("revision > 0 AND build_revision > 0 AND preparation_revision > 0"),
        CheckConstraint(
            "status IN ('draft','offered','accepted','scheduled','executing',"
            "'reported','disposed') "
            "AND visibility IN ('private','category','audience')"
        ),
        CheckConstraint(
            "operation IN ('verification.request.create',"
            "'verification.method.prepare','verification.schedule.propose',"
            "'verification.handoff.offer','verification.handoff.accept','verification.handoff.return',"
            "'verification.schedule.promise','test.run.start','test.results.import','test.run.review','test.disposition.decide')"
        ),
        CheckConstraint(
            "(revision = 1 AND previous_request_id IS NULL AND previous_revision IS NULL)"
            " OR (previous_request_id IS NOT NULL AND previous_request_id <> id"
            " AND previous_revision IS NOT NULL AND revision = previous_revision + 1)"
        ),
        CheckConstraint("COALESCE(request_snapshot->>'status' = status, false)"),
        CheckConstraint(
            "status <> 'draft' OR COALESCE(request_snapshot->'samples' = '[]'::jsonb AND "
            "request_snapshot->'acceptances' = '[]'::jsonb AND "
            "request_snapshot->'returns' = '[]'::jsonb AND "
            "request_snapshot->'offered_coverage' = '[]'::jsonb, false)"
        ),
        *[
            CheckConstraint(
                "status NOT IN ('draft','offered','accepted','scheduled') OR "
                f"COALESCE(request_snapshot->'timeline'->'{name}' = 'null'::jsonb, false)"
            )
            for name in (
                "preliminary_result",
                "final_result",
                "disposed",
            )
        ],
        CheckConstraint(
            "status <> 'draft' OR COALESCE("
            "request_snapshot->'timeline'->'sample_ready' = 'null'::jsonb AND "
            "request_snapshot->'timeline'->'offered' = 'null'::jsonb AND "
            "request_snapshot->'timeline'->'accepted' = 'null'::jsonb, false)"
        ),
        CheckConstraint(
            "status = 'draft' OR COALESCE("
            "jsonb_array_length(request_snapshot->'samples') > 0 AND "
            "jsonb_array_length(request_snapshot->'offered_coverage') > 0 AND "
            "jsonb_typeof(request_snapshot->'timeline'->'offered') = 'object', false)"
        ),
        CheckConstraint(
            "status NOT IN ('accepted','scheduled','executing','reported','disposed') OR COALESCE("
            "jsonb_array_length(request_snapshot->'acceptances') > 0 AND "
            "jsonb_typeof(request_snapshot->'timeline'->'accepted') = 'object', false)"
        ),
        CheckConstraint(
            "COALESCE(CASE WHEN status IN ('scheduled','executing','reported','disposed') THEN "
            "jsonb_typeof(request_snapshot->'timeline'->'promised_start')='object' ELSE "
            "request_snapshot->'timeline'->'promised_start'='null'::jsonb END, false)"
        ),
        CheckConstraint(
            "COALESCE(CASE WHEN status IN ('executing','reported','disposed') THEN "
            "jsonb_typeof(request_snapshot->'timeline'->'actual_start')='object' ELSE "
            "request_snapshot->'timeline'->'actual_start'='null'::jsonb END, false)"
        ),
        CheckConstraint(
            "(status<>'scheduled' OR operation IN ('verification.schedule.promise',"
            "'verification.handoff.accept','verification.handoff.return')) AND "
            "(status<>'executing' OR operation IN ('verification.schedule.promise',"
            "'verification.handoff.accept','verification.handoff.return',"
            "'test.run.start','test.results.import',"
            "'test.run.review','test.disposition.decide')) AND "
            "(status<>'reported' OR operation IN ('test.results.import','test.run.review',"
            "'test.disposition.decide')) AND "
            "(status<>'disposed' OR operation='test.disposition.decide')"
        ),
        CheckConstraint(
            "COALESCE(CASE WHEN status IN ('reported','disposed') THEN "
            "jsonb_typeof(request_snapshot->'timeline'->'final_result')='object' ELSE "
            "request_snapshot->'timeline'->'final_result'='null'::jsonb END, false)"
        ),
        CheckConstraint(
            "COALESCE(CASE WHEN status='disposed' THEN "
            "jsonb_typeof(request_snapshot->'timeline'->'disposed')='object' ELSE "
            "request_snapshot->'timeline'->'disposed'='null'::jsonb END, false)"
        ),
    )


class FormalVerificationCurrent(Row, Base):
    __tablename__ = "verification_current_formal_requests"
    product_id: Mapped[UUID]
    request_id: Mapped[UUID]
    request_version_id: Mapped[UUID]
    request_revision: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "request_id"),
        request_fk(),
        CheckConstraint("request_revision > 0"),
    )


class MethodApplicability(Row, Base):
    __tablename__ = "verification_method_applicabilities"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    request_id: Mapped[UUID]
    # Exact request version the reviewer inspected, prior to its resulting successor.
    request_version_id: Mapped[UUID]
    request_revision: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[str] = mapped_column(String(120))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24))
    engineering_configuration_id: Mapped[UUID]
    engineering_configuration_revision: Mapped[int] = mapped_column(Integer)
    manufacturing_configuration_id: Mapped[UUID]
    manufacturing_configuration_revision: Mapped[int] = mapped_column(Integer)
    method_ref: Mapped[dict | None] = mapped_column(JSONB)
    assessment_snapshot: Mapped[dict] = mapped_column(JSONB)
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        request_fk(project=True),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("revision = 1 AND request_revision > 0"),
        CheckConstraint("status IN ('applicable','not_applicable','unknown')"),
        CheckConstraint("visibility IN ('private','category','audience')"),
        CheckConstraint(
            "engineering_configuration_revision > 0 AND manufacturing_configuration_revision > 0"
        ),
    )


class VerificationWindowProposal(Row, Base):
    __tablename__ = "verification_window_proposals"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    request_id: Mapped[UUID]
    request_version_id: Mapped[UUID]
    request_revision: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="tentative")
    window: Mapped[dict] = mapped_column(JSONB)
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text)
    resources: Mapped[list] = mapped_column(JSONB)
    gaps: Mapped[list] = mapped_column(JSONB)
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    occupancy: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        request_fk(project=True),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("revision = 1 AND request_revision > 0 AND occupancy = 0"),
        CheckConstraint("status = 'tentative' AND visibility IN ('private','category','audience')"),
    )
