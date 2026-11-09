"""In-app notifications and per-project notification settings (P34-7, §8, D73, D74).

A notification row names who should look at which subject and why; it keeps no
copy of the content. Its text is read from the subject at display time under the
reader's own access, so losing access hides the notification as well.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.core.models import Base, Row

# 提及我、分派给我、要我确认或决定、小Pai 需要我、关注的变化 (§8)
CATEGORIES = ("mention", "assigned", "decide", "agent", "follow")
SUBJECT_KINDS = ("thread", "work_task", "project", "member_handover")
LEVELS = ("all", "important", "mentions")


class Notification(Row, Base):
    __tablename__ = "notifications"
    recipient_id: Mapped[UUID]
    category_id: Mapped[UUID] = mapped_column(index=True)
    project_id: Mapped[UUID]
    category: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(40))
    subject_kind: Mapped[str] = mapped_column(String(16))
    subject_id: Mapped[UUID]
    thread_id: Mapped[UUID | None]
    merge_key: Mapped[str] = mapped_column(String(240))
    actor_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)))
    event_count: Mapped[int] = mapped_column(Integer)
    first_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    latest: Mapped[dict] = mapped_column(JSONB)
    delivery: Mapped[str] = mapped_column(String(16))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set by the database on every insert or change; the live cursor reads it.
    change_seq: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "recipient_id"],
            ["principals.tenant_id", "principals.id"],
            name="notification_recipient_fk",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["categories.tenant_id", "categories.id"],
            name="notification_category_fk",
        ),
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="notification_project_fk"),
        Index("ix_notifications_recipient_change", "tenant_id", "recipient_id", "change_seq"),
        Index(
            "ix_notifications_open_merge",
            "tenant_id",
            "recipient_id",
            "merge_key",
            postgresql_where=text("read_at IS NULL AND archived_at IS NULL"),
        ),
        CheckConstraint(
            "category IN ('mention','assigned','decide','agent','follow') "
            "AND subject_kind IN ('thread','work_task','project','member_handover') "
            "AND delivery IN ('instant','digest') AND event_count>0 "
            "AND cardinality(actor_ids) BETWEEN 0 AND 20 AND last_at>=first_at "
            "AND jsonb_typeof(latest)='object' "
            "AND (delivery='instant' OR category='follow')",
            name="notification_shape",
        ),
    )


class NotificationPreference(Row, Base):
    """One person's setting for one project: level, mute, daily digest for follow changes."""

    __tablename__ = "notification_preferences"
    principal_id: Mapped[UUID]
    project_id: Mapped[UUID]
    level: Mapped[str] = mapped_column(String(16))
    muted: Mapped[bool] = mapped_column(Boolean)
    digest: Mapped[bool] = mapped_column(Boolean)
    revision: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "principal_id", "project_id"),
        ForeignKeyConstraint(
            ["tenant_id", "principal_id"],
            ["principals.tenant_id", "principals.id"],
            name="notification_preference_principal_fk",
        ),
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="notification_preference_project_fk"
        ),
        CheckConstraint(
            "level IN ('all','important','mentions') AND revision>0",
            name="notification_preference_shape",
        ),
    )
