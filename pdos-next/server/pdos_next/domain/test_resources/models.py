"""Host migrates these scoped facts; physical occupancy uses the one shared table."""

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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


def run_fk():
    return ForeignKeyConstraint(
        ["tenant_id", "product_id", "project_id", "build_id", "run_id"],
        [
            f"verification_run_identities.{key}"
            for key in ("tenant_id", "product_id", "project_id", "build_id", "id")
        ],
        deferrable=True,
        initially="DEFERRED",
    )


class TestResourceFact(Row, Base):
    __tablename__ = "test_resource_facts"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    run_id: Mapped[UUID]
    request_id: Mapped[UUID]
    accepted_request_id: Mapped[UUID]
    accepted_request_revision: Mapped[int] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    issuer_key: Mapped[str] = mapped_column(String(100))
    issuer_version: Mapped[str] = mapped_column(String(100))
    issuer_epoch: Mapped[int] = mapped_column(Integer)
    nature: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(160))
    series_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    binding: Mapped[dict] = mapped_column(JSONB)
    data: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    fact_sha256: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)

    @property
    def status(self):
        return self.state

    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id", "revision"),
        UniqueConstraint(
            "tenant_id",
            "product_id",
            "project_id",
            "build_id",
            "run_id",
            "request_id",
            "id",
            "revision",
        ),
        UniqueConstraint("tenant_id", "product_id", "run_id", "series_id", "revision"),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "request_id",
                "accepted_request_id",
                "accepted_request_revision",
            ],
            [
                f"verification_formal_requests.{key}"
                for key in ("tenant_id", "product_id", "project_id", "request_id", "id", "revision")
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "build_id"],
            [f"builds.{key}" for key in ("tenant_id", "product_id", "project_id", "id")],
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "build_id",
                "run_id",
                "request_id",
                "previous_id",
                "previous_revision",
            ],
            [
                f"test_resource_facts.{key}"
                for key in (
                    "tenant_id",
                    "product_id",
                    "project_id",
                    "build_id",
                    "run_id",
                    "request_id",
                    "id",
                    "revision",
                )
            ],
        ),
        CheckConstraint(
            "revision>0 AND accepted_request_revision>0 AND issuer_epoch>0 "
            "AND valid_until>valid_from"
        ),
        CheckConstraint(
            "state IN ('active','withdrawn') AND nature IN ('real','synthetic') "
            "AND visibility IN ('private','category','audience')"
        ),
        CheckConstraint(
            "(revision=1 AND previous_id IS NULL AND previous_revision IS NULL "
            "AND series_id=id) OR (previous_id IS NOT NULL AND previous_id<>id "
            "AND previous_revision>0 AND revision=previous_revision+1)"
        ),
    )


class TestResourceCurrent(Row, Base):
    __tablename__ = "test_resource_current"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    run_id: Mapped[UUID]
    request_id: Mapped[UUID]
    fact_id: Mapped[UUID]
    fact_revision: Mapped[int] = mapped_column(Integer)
    epoch: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "run_id"),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "build_id",
                "run_id",
                "request_id",
                "fact_id",
                "fact_revision",
            ],
            [
                f"test_resource_facts.{key}"
                for key in (
                    "tenant_id",
                    "product_id",
                    "project_id",
                    "build_id",
                    "run_id",
                    "request_id",
                    "id",
                    "revision",
                )
            ],
        ),
        CheckConstraint("fact_revision>0 AND epoch>0"),
    )


class TestResourceReservation(Row, Base):
    __tablename__ = "test_resource_reservations"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    run_id: Mapped[UUID]
    fact_id: Mapped[UUID]
    fact_revision: Mapped[int] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(16), default="formal")
    intent_digest: Mapped[str] = mapped_column(String(64))
    binding: Mapped[dict] = mapped_column(JSONB)
    reservation: Mapped[dict] = mapped_column(JSONB)
    reservation_sha256: Mapped[str] = mapped_column(String(64))
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    facts_revision: Mapped[str] = mapped_column(String(64))
    fingerprint_version: Mapped[str | None] = mapped_column(String(64))
    dependency_proof: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "run_id"),
        UniqueConstraint("tenant_id", "product_id", "id"),
        run_fk(),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "fact_id", "fact_revision"],
            [f"test_resource_facts.{key}" for key in ("tenant_id", "product_id", "id", "revision")],
        ),
        CheckConstraint(
            "revision=1 AND fact_revision>0 AND state='formal' "
            "AND visibility IN ('private','category','audience')"
        ),
        CheckConstraint(
            "((fingerprint_version IS NULL AND dependency_proof IS NULL) OR "
            "(fingerprint_version='test-resource-dependency-v2' "
            "AND jsonb_typeof(dependency_proof)='object' "
            "AND dependency_proof ?& ARRAY['schema_version','material','facts_revision'] "
            "AND dependency_proof-ARRAY['schema_version','material','facts_revision']='{}'::jsonb "
            "AND dependency_proof->>'schema_version'=fingerprint_version "
            "AND jsonb_typeof(dependency_proof->'facts_revision')='string' "
            "AND dependency_proof->>'facts_revision'=facts_revision "
            "AND facts_revision ~ '^[a-f0-9]{64}$' "
            "AND jsonb_typeof(dependency_proof->'material')='object' "
            "AND (dependency_proof->'material') ?& ARRAY["
            "'binding','fact','epoch','issuer','issuer_epochs','assets','sample_epochs',"
            "'samples','authority','source_basis','proofs','checks'] "
            "AND (dependency_proof->'material')-ARRAY["
            "'binding','fact','epoch','issuer','issuer_epochs','assets','sample_epochs',"
            "'samples','authority','source_basis','proofs','checks']='{}'::jsonb "
            "AND jsonb_typeof(dependency_proof->'material'->'authority')='object' "
            "AND jsonb_typeof(dependency_proof->'material'->'source_basis')='object')) IS TRUE",
            name="test_resource_dependency_version_complete",
        ),
    )


class SampleUsageSentinel(Row, Base):
    __tablename__ = "sample_usage_sentinels"
    product_id: Mapped[UUID]
    sample_id: Mapped[UUID]
    epoch: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        UniqueConstraint("tenant_id", "sample_id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "sample_id"],
            ["sample_units.tenant_id", "sample_units.product_id", "sample_units.id"],
        ),
        CheckConstraint("epoch>0"),
    )


class SampleRunUsage(Row, Base):
    __tablename__ = "sample_run_usages"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    run_id: Mapped[UUID]
    sample_id: Mapped[UUID]
    sample_revision: Mapped[int] = mapped_column(Integer)
    actual_configuration_id: Mapped[UUID]
    actual_configuration_revision: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    destructive: Mapped[bool] = mapped_column(Boolean)
    state: Mapped[str] = mapped_column(String(16))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_finish: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    coverage: Mapped[list] = mapped_column(JSONB)
    intent_digest: Mapped[str] = mapped_column(String(64))
    source_basis: Mapped[dict] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "run_id", "sample_id"),
        Index(
            "one_destructive_sample_use",
            "tenant_id",
            "sample_id",
            unique=True,
            postgresql_where=text("destructive"),
        ),
        run_fk(),
        ForeignKeyConstraint(
            ["tenant_id", "sample_id"],
            ["sample_usage_sentinels.tenant_id", "sample_usage_sentinels.sample_id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "build_id", "sample_id"],
            [
                f"sample_units.{key}"
                for key in ("tenant_id", "product_id", "project_id", "build_id", "id")
            ],
        ),
        CheckConstraint(
            "revision=1 AND sample_revision>0 AND actual_configuration_revision>0 "
            "AND window_finish>window_start AND visibility IN ('private','category','audience')"
        ),
        CheckConstraint(
            "(destructive AND state='consumed') OR (NOT destructive AND state='reserved')"
        ),
    )
