"""Explicit account settings, separate from business facts and authorization."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


class PersonalPreference(Row, Base):
    __tablename__ = "personal_preferences"
    owner_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    body: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("tenant_id", "owner_id"),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("revision > 0", name="personal_preferences_revision"),
        CheckConstraint("jsonb_typeof(body)='object'", name="personal_preferences_body"),
    )
