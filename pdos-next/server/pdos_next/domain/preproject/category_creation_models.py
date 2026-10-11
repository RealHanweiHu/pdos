"""A tenant-owned T1 proof, before a category permission root exists."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


class CategoryCreationConfirmation(Row, Base):
    __tablename__ = "category_creation_confirmations"
    actor_id: Mapped[UUID]
    reserved_category_id: Mapped[UUID]
    token_hash: Mapped[str] = mapped_column(String(64))
    payload_digest: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        UniqueConstraint("token_hash"),
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["principals.tenant_id", "principals.id"]),
    )


TABLES = (CategoryCreationConfirmation.__table__,)
