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


class Variant(Row, Base):
    __tablename__ = "product_variants"
    product_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(24))
    visibility: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    g0_decision_id: Mapped[UUID | None]
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "g0_decision_id"],
            [
                "proposal_decisions.tenant_id",
                "proposal_decisions.category_id",
                "proposal_decisions.id",
            ],
            name="m3_variant_decision_fk",
            use_alter=True,
        ),
        UniqueConstraint("tenant_id", "product_id", "id"),
        ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"]),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("kind IN ('customer','region','configuration')"),
        CheckConstraint("visibility IN ('private','category','audience')"),
        CheckConstraint("status = 'draft'"),
    )


class VariantRevision(Row, Base):
    __tablename__ = "variant_revisions"
    product_id: Mapped[UUID]
    variant_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    parent_definition_id: Mapped[UUID]
    definition_id: Mapped[UUID | None]
    parent_revision: Mapped[int] = mapped_column(Integer)
    previous_revision_id: Mapped[UUID | None]
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    visibility: Mapped[str] = mapped_column(String(16))
    effective_definition: Mapped[dict] = mapped_column(JSONB)
    overrides: Mapped[dict] = mapped_column(JSONB)
    applicability: Mapped[list] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    choices: Mapped[list] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "definition_id"],
            [
                "definition_revisions.tenant_id",
                "definition_revisions.product_id",
                "definition_revisions.id",
            ],
            name="m3_variant_revision_definition_fk",
        ),
        UniqueConstraint("tenant_id", "product_id", "variant_id", "id"),
        UniqueConstraint("tenant_id", "variant_id", "revision"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "variant_id"],
            ["product_variants.tenant_id", "product_variants.product_id", "product_variants.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "parent_definition_id"],
            [
                "definition_revisions.tenant_id",
                "definition_revisions.product_id",
                "definition_revisions.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "variant_id", "previous_revision_id"],
            [
                "variant_revisions.tenant_id",
                "variant_revisions.product_id",
                "variant_revisions.variant_id",
                "variant_revisions.id",
            ],
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("revision > 0 AND parent_revision > 0"),
        CheckConstraint("status = 'draft'"),
        CheckConstraint("visibility IN ('private','category','audience')"),
        CheckConstraint(
            "jsonb_typeof(effective_definition) = 'object' AND jsonb_typeof(overrides) = 'object'"
        ),
        CheckConstraint("previous_revision_id IS DISTINCT FROM id"),
    )
