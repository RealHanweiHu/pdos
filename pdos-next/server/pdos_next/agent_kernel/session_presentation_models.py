"""Append-only, owner-authored presentation history for existing Sessions."""

from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base

from .models import KernelRow


class AgentSessionPresentation(KernelRow, Base):
    __tablename__ = "agent_session_presentations"

    session_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[UUID | None]
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(16))
    title: Mapped[str | None] = mapped_column(String(160))
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "session_id", "revision"),
        UniqueConstraint("tenant_id", "owner_id", "request_key"),
        ForeignKeyConstraint(
            ["tenant_id", "session_id"], ["agent_sessions.tenant_id", "agent_sessions.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "previous_id"],
            ["agent_session_presentations.tenant_id", "agent_session_presentations.id"],
        ),
        CheckConstraint("revision > 0", name="session_presentation_revision"),
        CheckConstraint(
            "action IN ('rename', 'pin', 'unpin', 'archive', 'restore')",
            name="session_presentation_action",
        ),
        CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$'", name="session_presentation_request_sha256"
        ),
        CheckConstraint(
            "title IS NULL OR char_length(title) BETWEEN 1 AND 160",
            name="session_presentation_title",
        ),
        CheckConstraint(
            "(revision = 1) = (previous_id IS NULL)", name="session_presentation_previous"
        ),
    )
