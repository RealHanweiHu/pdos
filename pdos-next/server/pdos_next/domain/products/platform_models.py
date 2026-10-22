"""Immutable platform/link facts with an explicit current projection."""

from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


class Provenance:
    origin: Mapped[str] = mapped_column(Text)
    writer_id: Mapped[UUID]
    run_id: Mapped[UUID | None]
    confirmed_by: Mapped[UUID]
    prepared_candidate_id: Mapped[UUID | None]
    receipt_id: Mapped[UUID]
    confirmation_id: Mapped[UUID]


def provenance_constraints():
    return (
        *(
            ForeignKeyConstraint(["tenant_id", column], ["principals.tenant_id", "principals.id"])
            for column in ("writer_id", "confirmed_by")
        ),
        ForeignKeyConstraint(["tenant_id", "run_id"], ["agent_runs.tenant_id", "agent_runs.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "prepared_candidate_id"],
            ["proposal_prepared_candidates.tenant_id", "proposal_prepared_candidates.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["action_receipts.tenant_id", "action_receipts.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "confirmation_id"],
            ["confirmations.tenant_id", "confirmations.id"],
        ),
        CheckConstraint("origin IN ('human','ai_draft')"),
        CheckConstraint(
            "(origin='human' AND run_id IS NULL AND prepared_candidate_id IS NULL) OR "
            "(origin='ai_draft' AND run_id IS NOT NULL AND prepared_candidate_id IS NOT NULL)"
        ),
    )


class Platform(Provenance, Row, Base):
    __tablename__ = "platforms"
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "code"),
        CheckConstraint("length(code)>0 AND length(name)>0"),
        *provenance_constraints(),
    )


class PlatformLink(Provenance, Row, Base):
    __tablename__ = "platform_product_links"
    product_id: Mapped[UUID]
    platform_id: Mapped[UUID]
    variant_id: Mapped[UUID | None]
    target_id: Mapped[UUID]
    version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(Text)
    compatibility: Mapped[str | None] = mapped_column(Text)
    platform_version: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        Index("ix_platform_links_platform", "tenant_id", "platform_id"),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint(
            "tenant_id", "category_id", "product_id", "platform_id", "target_id", "version"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "product_id"],
            ["products.tenant_id", "products.category_id", "products.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "variant_id"],
            ["product_variants.tenant_id", "product_variants.product_id", "product_variants.id"],
        ),
        ForeignKeyConstraint(["tenant_id", "platform_id"], ["platforms.tenant_id", "platforms.id"]),
        CheckConstraint("target_id=coalesce(variant_id,product_id) AND version>0"),
        CheckConstraint("action IN ('attach','detach') AND length(reason)>0"),
        *provenance_constraints(),
    )

    @property
    def revision(self):
        return self.version

    @property
    def status(self):
        return "attached" if self.action == "attach" else "detached"


class PlatformLinkCurrent(Base):
    __tablename__ = "platform_link_current"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    product_id: Mapped[UUID] = mapped_column(primary_key=True)
    platform_id: Mapped[UUID] = mapped_column(primary_key=True)
    target_id: Mapped[UUID] = mapped_column(primary_key=True)
    category_id: Mapped[UUID]
    current_version: Mapped[int] = mapped_column(Integer)
    attached: Mapped[bool] = mapped_column(Boolean)
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "tenant_id",
                "category_id",
                "product_id",
                "platform_id",
                "target_id",
                "current_version",
            ],
            [
                "platform_product_links.tenant_id",
                "platform_product_links.category_id",
                "platform_product_links.product_id",
                "platform_product_links.platform_id",
                "platform_product_links.target_id",
                "platform_product_links.version",
            ],
            deferrable=True,
            initially="DEFERRED",
        ),
    )
