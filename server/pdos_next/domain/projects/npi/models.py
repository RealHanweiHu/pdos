"""Append-only framework revisions, effective within one product category."""

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.core.models import Base, Row


class FrameworkRevision(Row, Base):
    __tablename__ = "npi_framework_revisions"
    category_id: Mapped[UUID] = mapped_column(index=True)
    project_type: Mapped[str] = mapped_column(Text)
    revision: Mapped[int]
    state: Mapped[str] = mapped_column(Text)
    document: Mapped[dict] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text)
    author_id: Mapped[UUID]
    previous_id: Mapped[UUID | None]
    receipt_id: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("tenant_id", "category_id", "id"),
        UniqueConstraint("tenant_id", "category_id", "project_type", "revision"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"], ["categories.tenant_id", "categories.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "author_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "previous_id"],
            [
                "npi_framework_revisions.tenant_id",
                "npi_framework_revisions.category_id",
                "npi_framework_revisions.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["action_receipts.tenant_id", "action_receipts.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("revision > 0 AND project_type IN ('new_product','derivative')"),
        CheckConstraint("state IN ('draft','published','retired')"),
    )

    @property
    def status(self):
        return self.state
