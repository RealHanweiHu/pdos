from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


class DefinitionRevision(Row, Base):
    __tablename__ = "definition_revisions"
    product_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    parent_definition_id: Mapped[UUID | None]
    title: Mapped[str] = mapped_column(String(200))
    purpose: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    visibility: Mapped[str] = mapped_column(String(16))
    use_cases: Mapped[list] = mapped_column(JSONB)
    requirements: Mapped[list] = mapped_column(JSONB)
    constraints: Mapped[list] = mapped_column(JSONB)
    unknowns: Mapped[list] = mapped_column(JSONB)
    exclusions: Mapped[list] = mapped_column(JSONB)
    change_reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "revision"),
        ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"]),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "parent_definition_id"],
            [
                "definition_revisions.tenant_id",
                "definition_revisions.product_id",
                "definition_revisions.id",
            ],
        ),
        CheckConstraint("status = 'draft'"),
        CheckConstraint("visibility IN ('private','product')"),
        CheckConstraint("revision > 0 AND parent_definition_id IS DISTINCT FROM id"),
    )


class DefinitionSpecRow(Row, Base):
    __tablename__ = "definition_specs"
    product_id: Mapped[UUID]
    definition_id: Mapped[UUID]
    key: Mapped[str] = mapped_column(String(80))
    parameter: Mapped[str] = mapped_column(String(200))
    value_type: Mapped[str] = mapped_column(String(16))
    availability: Mapped[str] = mapped_column(String(24))
    value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    lower: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    upper: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    text: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(80))
    tolerance: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    test_conditions: Mapped[list] = mapped_column(JSONB)
    method: Mapped[str | None] = mapped_column(Text)
    acceptance_criterion: Mapped[str | None] = mapped_column(Text)
    nature: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(24))
    owner_id: Mapped[UUID | None]
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "definition_id", "id"),
        UniqueConstraint("tenant_id", "definition_id", "key"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "definition_id"],
            [
                "definition_revisions.tenant_id",
                "definition_revisions.product_id",
                "definition_revisions.id",
            ],
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("value_type IN ('number','range','text')"),
        CheckConstraint("availability IN ('known','unknown','conflicted','not_applicable')"),
        CheckConstraint("nature IN ('observed','extracted','computed','inferred','decided')"),
        CheckConstraint("state IN ('proposed','needs_confirmation')"),
        CheckConstraint("tolerance IS NULL OR tolerance >= 0"),
        CheckConstraint("lower IS NULL OR upper IS NULL OR lower <= upper"),
        CheckConstraint(
            "availability = 'known' OR (value IS NULL AND lower IS NULL "
            "AND upper IS NULL AND text IS NULL AND tolerance IS NULL)"
        ),
        CheckConstraint(
            "availability <> 'known' OR "
            "(value_type = 'number' AND value IS NOT NULL AND lower IS NULL "
            "AND upper IS NULL AND text IS NULL AND unit IS NOT NULL) OR "
            "(value_type = 'range' AND lower IS NOT NULL AND upper IS NOT NULL "
            "AND value IS NULL AND text IS NULL AND unit IS NOT NULL) OR "
            "(value_type = 'text' AND text IS NOT NULL AND value IS NULL "
            "AND lower IS NULL AND upper IS NULL AND tolerance IS NULL)"
        ),
    )


class DefinitionSource(Row, Base):
    __tablename__ = "definition_sources"
    product_id: Mapped[UUID]
    definition_id: Mapped[UUID]
    artifact_id: Mapped[UUID]
    source_revision: Mapped[int] = mapped_column(Integer)
    line: Mapped[int] = mapped_column(Integer)
    quote: Mapped[str] = mapped_column(Text)
    spec_keys: Mapped[list] = mapped_column(JSONB)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "definition_id"],
            [
                "definition_revisions.tenant_id",
                "definition_revisions.product_id",
                "definition_revisions.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "artifact_id"],
            ["artifact_versions.tenant_id", "artifact_versions.product_id", "artifact_versions.id"],
        ),
        CheckConstraint("source_revision > 0 AND line > 0"),
    )
