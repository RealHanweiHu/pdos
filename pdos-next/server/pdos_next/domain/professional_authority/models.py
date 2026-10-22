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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


class ProfessionalFact(Row, Base):
    __tablename__ = "professional_authority_facts"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    subject_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    role: Mapped[str] = mapped_column(String(32))
    nature: Mapped[str] = mapped_column(String(16))
    issuer_key: Mapped[str] = mapped_column(String(100))
    issuer_version: Mapped[str] = mapped_column(String(100))
    external_id: Mapped[str] = mapped_column(String(200))
    operations: Mapped[list] = mapped_column(JSONB)
    purposes: Mapped[list] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(16))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    series_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    fact_sha256: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "product_id",
            "project_id",
            "subject_id",
            "kind",
            "series_id",
            "id",
            "revision",
        ),
        UniqueConstraint(
            "tenant_id", "product_id", "project_id", "subject_id", "kind", "series_id", "revision"
        ),
        UniqueConstraint(
            "tenant_id",
            "product_id",
            "project_id",
            "subject_id",
            "kind",
            "issuer_key",
            "external_id",
            "revision",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id"],
            ["projects.tenant_id", "projects.product_id", "projects.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "subject_id"], ["principals.tenant_id", "principals.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "subject_id",
                "kind",
                "series_id",
                "previous_id",
                "previous_revision",
            ],
            [
                f"professional_authority_facts.{key}"
                for key in (
                    "tenant_id",
                    "product_id",
                    "project_id",
                    "subject_id",
                    "kind",
                    "series_id",
                    "id",
                    "revision",
                )
            ],
        ),
        CheckConstraint(
            "kind IN ('duty','qualification') "
            "AND role IN ('engineering','quality','manufacturing','knowledge') "
            "AND nature IN ('real','synthetic')"
        ),
        CheckConstraint(
            "visibility IN ('private','category','audience') AND "
            "valid_until > valid_from AND revision > 0"
        ),
        CheckConstraint(
            "(kind='duty' AND state IN ('active','withdrawn')) OR "
            "(kind='qualification' AND state IN ('active','revoked'))"
        ),
        CheckConstraint(
            "(revision=1 AND previous_id IS NULL AND previous_revision IS NULL AND series_id=id) "
            "OR (previous_id IS NOT NULL AND previous_id<>id AND previous_revision>0 "
            "AND revision=previous_revision+1)"
        ),
        CheckConstraint(
            "jsonb_typeof(operations)='array' AND jsonb_array_length(operations)>0 "
            "AND jsonb_typeof(purposes)='array' AND jsonb_array_length(purposes)>0"
        ),
        CheckConstraint(
            "COALESCE(length(source_basis->'approval'->>'version')>0 "
            "AND length(source_basis->'approval'->>'approved_by')>0 "
            "AND length(source_basis->'approval'->>'external_id')>0, false)"
        ),
    )


class ProfessionalCurrent(Row, Base):
    __tablename__ = "professional_authority_current"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    subject_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(16))
    issuer_key: Mapped[str] = mapped_column(String(100))
    external_id: Mapped[str] = mapped_column(String(200))
    series_id: Mapped[UUID]
    fact_id: Mapped[UUID]
    fact_revision: Mapped[int] = mapped_column(Integer)
    epoch: Mapped[int] = mapped_column(Integer)
    summary: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "product_id",
            "project_id",
            "subject_id",
            "kind",
            "issuer_key",
            "external_id",
        ),
        UniqueConstraint(
            "tenant_id", "product_id", "project_id", "subject_id", "kind", "series_id"
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "subject_id",
                "kind",
                "series_id",
                "fact_id",
                "fact_revision",
            ],
            [
                f"professional_authority_facts.{key}"
                for key in (
                    "tenant_id",
                    "product_id",
                    "project_id",
                    "subject_id",
                    "kind",
                    "series_id",
                    "id",
                    "revision",
                )
            ],
        ),
        CheckConstraint("epoch>0 AND fact_revision>0 AND kind IN ('duty','qualification')"),
    )
