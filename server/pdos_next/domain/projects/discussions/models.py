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


class DiscussionAgentRequest(Row, Base):
    """One @小Pai in a shared thread (P34-4, P52, P54, P62; D37 ⑥).

    The human message that mentioned 小Pai starts a Run in the requester's own
    Session for this thread (thread × requester, P52). Once the Run ends, the host
    checks every source the Run read against the thread's current audience and
    delivers 小Pai's reply into the thread, or only a notice that the requester got a
    private reply. Rows change only through the SECURITY DEFINER functions of
    s0_0880; the agent role has no privilege on this table.
    """

    __tablename__ = "discussion_agent_requests"
    category_id: Mapped[UUID] = mapped_column(index=True)
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    thread_id: Mapped[UUID]
    message_id: Mapped[UUID]
    requester_id: Mapped[UUID]
    writer_id: Mapped[UUID]
    session_id: Mapped[UUID]
    run_id: Mapped[UUID]
    private_only: Mapped[bool]
    # pending → public (reply posted) | private (only a notice posted) | none (no reply).
    delivery: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(40))
    reply_message_id: Mapped[UUID | None]
    # Receipt of the audience check: counts and reasons only, never source content.
    audience_check: Mapped[dict | None] = mapped_column(JSONB)
    # Frozen read manifest of the Run (dependency identities only), used to gate a
    # link share per viewer; never returned by any API.
    manifest: Mapped[dict | None] = mapped_column(JSONB)
    shared_message_id: Mapped[UUID | None]
    share_mode: Mapped[str | None] = mapped_column(String(8))
    share_receipt: Mapped[dict | None] = mapped_column(JSONB)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    change_seq: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "message_id"),
        UniqueConstraint("tenant_id", "run_id"),
        ForeignKeyConstraint(
            ["tenant_id", "thread_id"],
            ["discussion_threads.tenant_id", "discussion_threads.id"],
            name="discussion_agent_thread_fk",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "message_id"],
            ["discussion_messages.tenant_id", "discussion_messages.id"],
            name="discussion_agent_message_fk",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reply_message_id"],
            ["discussion_messages.tenant_id", "discussion_messages.id"],
            name="discussion_agent_reply_fk",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "shared_message_id"],
            ["discussion_messages.tenant_id", "discussion_messages.id"],
            name="discussion_agent_share_fk",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["agent_runs.tenant_id", "agent_runs.id"],
            name="discussion_agent_run_fk",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "session_id"],
            ["agent_sessions.tenant_id", "agent_sessions.id"],
            name="discussion_agent_session_fk",
        ),
        _principal("requester_id", "discussion_agent_requester_fk"),
        _principal("writer_id", "discussion_agent_writer_fk"),
        Index(
            "ix_discussion_agent_requests_thread",
            "tenant_id",
            "thread_id",
            "requester_id",
            "created_at",
        ),
        Index(
            "ix_discussion_agent_requests_pending",
            "tenant_id",
            "created_at",
            postgresql_where=text("delivery='pending'"),
        ),
        CheckConstraint(
            "delivery IN ('pending','public','private','none') "
            "AND ((delivery='pending') = (settled_at IS NULL)) "
            "AND (reply_message_id IS NULL OR delivery IN ('public','private')) "
            "AND (shared_message_id IS NULL OR delivery='private') "
            "AND ((shared_message_id IS NULL) = (share_mode IS NULL)) "
            "AND ((shared_message_id IS NULL) = (share_receipt IS NULL)) "
            "AND (share_mode IS NULL OR share_mode IN ('body','link'))",
            name="discussion_agent_request_shape",
        ),
    )
