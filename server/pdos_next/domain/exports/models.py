"""One append-only audit row per delivered export (D56; C16 记审计)."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.core.models import Base, now

VIEWS = ("project", "my_work", "bom_diff", "test_summary")


class ExportAudit(Base):
    __tablename__ = "export_audits"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    actor_id: Mapped[UUID]
    category_id: Mapped[UUID | None]
    product_id: Mapped[UUID | None]
    project_id: Mapped[UUID | None]
    view: Mapped[str] = mapped_column(String(32))
    scope: Mapped[dict] = mapped_column(JSONB)
    row_count: Mapped[int] = mapped_column(Integer)
    ai_row_count: Mapped[int] = mapped_column(Integer)
    ai_cell_count: Mapped[int] = mapped_column(Integer)
    contains_ai: Mapped[bool] = mapped_column(Boolean)
    sheet_rows: Mapped[dict] = mapped_column(JSONB)
    file_format: Mapped[str] = mapped_column(String(16))
    filename: Mapped[str] = mapped_column(String(200))
    content_sha256: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer)
    marker_version: Mapped[str] = mapped_column(String(40))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"], ["categories.tenant_id", "categories.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"]),
        CheckConstraint(
            "view IN ('project','my_work','bom_diff','test_summary') AND file_format='xlsx'"
            " AND row_count>=0 AND ai_row_count>=0 AND ai_cell_count>=0"
            " AND ai_row_count<=row_count AND byte_size>0"
            " AND contains_ai=(ai_row_count>0 OR ai_cell_count>0)"
            " AND content_sha256 ~ '^[0-9a-f]{64}$'"
            " AND ((view='my_work' AND category_id IS NULL AND product_id IS NULL"
            " AND project_id IS NULL) OR (view<>'my_work' AND category_id IS NOT NULL"
            " AND product_id IS NOT NULL))",
            name="export_audit_shape",
        ),
        Index("ix_export_audits_actor_recent", "tenant_id", "actor_id", "created_at"),
    )
