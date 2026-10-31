from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


class Conversation(Row, Base):
    __tablename__ = "inbox_conversations"
    category_id: Mapped[UUID] = mapped_column()
    owner_id: Mapped[UUID]
    member_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)))
    title: Mapped[str] = mapped_column(String(160))
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "owner_id", "request_key"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"], ["categories.tenant_id", "categories.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("char_length(btrim(title)) BETWEEN 1 AND 160", name="inbox_title"),
        CheckConstraint(
            "cardinality(member_ids) BETWEEN 2 AND 20 AND owner_id=ANY(member_ids)",
            name="inbox_members",
        ),
    )


class Message(Row, Base):
    __tablename__ = "inbox_messages"
    conversation_id: Mapped[UUID]
    sender_id: Mapped[UUID]
    sequence: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "conversation_id", "sequence"),
        UniqueConstraint("tenant_id", "sender_id", "request_key"),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["inbox_conversations.tenant_id", "inbox_conversations.id"],
        ),
        ForeignKeyConstraint(["tenant_id", "sender_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("sequence > 0", name="inbox_message_sequence"),
        CheckConstraint("char_length(btrim(body)) BETWEEN 1 AND 8000", name="inbox_message_body"),
    )


class InboxState(Row, Base):
    __tablename__ = "inbox_states"
    owner_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    read_through: Mapped[str] = mapped_column(String(64))
    archived: Mapped[bool] = mapped_column(Boolean)
    followed: Mapped[bool] = mapped_column(Boolean)
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "owner_id", "kind", "target_id", "revision"),
        UniqueConstraint("tenant_id", "owner_id", "request_key"),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("kind IN ('conversation','run','project')", name="inbox_state_kind"),
        CheckConstraint("revision > 0", name="inbox_state_revision"),
    )
