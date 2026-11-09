"""Project discussions and object comments (P34-2, P41-6/7).

A thread hangs on its project (a named topic) or on one object inside it (a task
or a document). It never carries its own audience: every read re-evaluates the
subject's current audience, so narrowing the object narrows its comments.
Messages are authored by named humans only; edits keep every version and a
retraction leaves an "已撤回" placeholder while the version history stays.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.core.models import Base, Row

SUBJECT_TYPES = ("project", "work_task", "artifact")
MESSAGE_STATES = ("posted", "edited", "retracted")


def _principal(column, name=None):
    return ForeignKeyConstraint(
        ["tenant_id", column], ["principals.tenant_id", "principals.id"], name=name
    )


class DiscussionThread(Row, Base):
    """A project topic (title, subject = project) or the one comment thread of an object."""

    __tablename__ = "discussion_threads"
    category_id: Mapped[UUID] = mapped_column(index=True)
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    subject_type: Mapped[str] = mapped_column(String(16))
    subject_id: Mapped[UUID]
    title: Mapped[str | None] = mapped_column(String(160))
    author_id: Mapped[UUID]
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "author_id", "request_key"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "product_id"],
            ["products.tenant_id", "products.category_id", "products.id"],
            name="discussion_thread_product_fk",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id"],
            ["projects.tenant_id", "projects.product_id", "projects.id"],
            name="discussion_thread_project_fk",
        ),
        _principal("author_id", "discussion_thread_author_fk"),
        Index(
            "uq_discussion_object_thread",
            "tenant_id",
            "project_id",
            "subject_type",
            "subject_id",
            unique=True,
            postgresql_where=text("subject_type<>'project'"),
        ),
        Index("ix_discussion_threads_project", "tenant_id", "project_id", "created_at"),
        CheckConstraint(
            "subject_type IN ('project','work_task','artifact') "
            "AND ((subject_type='project') = (title IS NOT NULL)) "
            "AND (subject_type<>'project' OR subject_id=project_id) "
            "AND (title IS NULL OR char_length(btrim(title)) BETWEEN 1 AND 160) "
            "AND request_sha256 ~ '^[a-f0-9]{64}$'",
            name="discussion_thread_shape",
        ),
    )


class DiscussionMessage(Row, Base):
    """Current state of one message; every change is also a DiscussionMessageVersion."""

    __tablename__ = "discussion_messages"
    thread_id: Mapped[UUID]
    sequence: Mapped[int] = mapped_column(Integer)
    author_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16))
    body: Mapped[str] = mapped_column(Text)
    mentions: Mapped[list] = mapped_column(JSONB)
    # The object version the comment was written against (P41-6); null for topics.
    subject_revision: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Set by the database on every insert or change; live delivery compares it.
    change_seq: Mapped[int] = mapped_column(BigInteger)
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "thread_id", "sequence"),
        UniqueConstraint("tenant_id", "author_id", "request_key"),
        ForeignKeyConstraint(
            ["tenant_id", "thread_id"],
            ["discussion_threads.tenant_id", "discussion_threads.id"],
            name="discussion_message_thread_fk",
        ),
        _principal("author_id", "discussion_message_author_fk"),
        Index("ix_discussion_messages_thread_change", "tenant_id", "thread_id", "change_seq"),
        CheckConstraint(
            "sequence>0 AND revision>0 AND state IN ('posted','edited','retracted') "
            "AND jsonb_typeof(mentions)='array' "
            "AND ((state='retracted' AND body='' AND mentions='[]'::jsonb) "
            "OR (state<>'retracted' AND char_length(btrim(body)) BETWEEN 1 AND 8000)) "
            "AND (subject_revision IS NULL OR subject_revision>0) "
            "AND request_sha256 ~ '^[a-f0-9]{64}$'",
            name="discussion_message_shape",
        ),
    )


class DiscussionMessageVersion(Row, Base):
    """Append-only history of a message: what was said, by whom, against which version."""

    __tablename__ = "discussion_message_versions"
    message_id: Mapped[UUID]
    thread_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16))
    body: Mapped[str] = mapped_column(Text)
    mentions: Mapped[list] = mapped_column(JSONB)
    subject_revision: Mapped[int | None] = mapped_column(Integer)
    editor_id: Mapped[UUID]
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "message_id", "revision"),
        UniqueConstraint("tenant_id", "editor_id", "request_key"),
        ForeignKeyConstraint(
            ["tenant_id", "message_id"],
            ["discussion_messages.tenant_id", "discussion_messages.id"],
            name="discussion_version_message_fk",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "thread_id"],
            ["discussion_threads.tenant_id", "discussion_threads.id"],
            name="discussion_version_thread_fk",
        ),
        _principal("editor_id", "discussion_version_editor_fk"),
        CheckConstraint(
            "revision>0 AND state IN ('posted','edited','retracted') "
            "AND jsonb_typeof(mentions)='array' "
            "AND (state='retracted' OR char_length(btrim(body)) BETWEEN 1 AND 8000) "
            "AND request_sha256 ~ '^[a-f0-9]{64}$'",
            name="discussion_version_shape",
        ),
    )


class DiscussionFollow(Row, Base):
    """Whether one person follows a thread or a task (§8 自动关注); explicit choice wins."""

    __tablename__ = "discussion_follows"
    principal_id: Mapped[UUID]
    project_id: Mapped[UUID]
    target_kind: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[UUID]
    followed: Mapped[bool]
    reason: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "principal_id", "target_kind", "target_id"),
        _principal("principal_id", "discussion_follow_principal_fk"),
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="discussion_follow_project_fk"),
        Index("ix_discussion_follows_target", "tenant_id", "target_kind", "target_id"),
        CheckConstraint(
            "target_kind IN ('thread','work_task') "
            "AND reason IN ('created','commented','mentioned','assigned','manual')",
            name="discussion_follow_shape",
        ),
    )
