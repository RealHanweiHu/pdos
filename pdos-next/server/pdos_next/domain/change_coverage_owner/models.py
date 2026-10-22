"""Candidate two-table owner; Root alone assigns/applies the actual migration."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.change_controlled_schemas import BIND
from pdos_next.change_controlled_store import _continuous, _Current, _Fact, _previous, _scope
from pdos_next.models import Base


class ChangeCoverageFact(_Fact, Base):
    __tablename__ = "controlled_change_coverage_facts"
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    change_id: Mapped[UUID]
    origin_version_id: Mapped[UUID]
    origin_revision: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dependency_epoch: Mapped[int] = mapped_column(BigInteger)
    closure_sha256: Mapped[str] = mapped_column(String(64))
    issuer_stamp: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        *_scope(),
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["principals.tenant_id", "principals.id"]),
        UniqueConstraint(
            "tenant_id", "product_id", "project_id", "change_id", "purpose_sha256", "revision"
        ),
        UniqueConstraint("tenant_id", "product_id", "actor_id", "operation", "intent_digest"),
        UniqueConstraint(*BIND, "change_id", "purpose_sha256", "id", "revision"),
        _previous(__tablename__, ("change_id", "purpose_sha256")),
        _continuous(),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "change_id",
                "origin_version_id",
                "origin_revision",
            ],
            [
                f"change_request_versions.{v}"
                for v in ("tenant_id", "product_id", "project_id", "change_id", "id", "revision")
            ],
        ),
        CheckConstraint(
            "operation='change.coverage.import' AND status='published' AND valid_from<valid_until "
            "AND dependency_epoch>0 AND origin_revision>0"
        ),
        CheckConstraint(
            "nature IN ('real','synthetic') AND jsonb_array_length(required_source_read_set)>0"
        ),
        CheckConstraint("valid_from<=created_at AND created_at<valid_until"),
    )


class ChangeCoverageCurrent(_Current, Base):
    __tablename__ = "controlled_change_coverage_currents"
    change_id: Mapped[UUID]
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "product_id", "project_id", "change_id", "purpose_sha256"),
        ForeignKeyConstraint(
            [*BIND, "change_id", "purpose_sha256", "fact_id", "revision"],
            [
                *[
                    f"controlled_change_coverage_facts.{v}"
                    for v in (*BIND, "change_id", "purpose_sha256")
                ],
                "controlled_change_coverage_facts.id",
                "controlled_change_coverage_facts.revision",
            ],
        ),
    )
