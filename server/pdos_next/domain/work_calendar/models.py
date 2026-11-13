"""Tenant working calendars (D221).

A tenant has one factory calendar and any number of supplier calendars, each kept
apart. Every save writes a complete new version; versions are never updated or
deleted, so a schedule that recorded "calendar X, revision N" can always be read
back. Only an active human tenant administrator acting for themself writes; the AI
identity and every other runtime role write nothing (database policies in s0_0870).
"""

from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.core.models import Base, Row

FACTORY_NAME = "factory"


def _principal(column):
    return ForeignKeyConstraint(["tenant_id", column], ["principals.tenant_id", "principals.id"])


class WorkCalendar(Row, Base):
    """Identity of one calendar: the factory's, or one supplier's."""

    __tablename__ = "work_calendars"
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(80))
    created_by: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "name"),
        _principal("created_by"),
        CheckConstraint("kind IN ('factory','supplier')", name="work_calendar_kind"),
        CheckConstraint(
            f"(kind='factory') = (name='{FACTORY_NAME}') AND char_length(name) BETWEEN 1 AND 80",
            name="work_calendar_name",
        ),
    )


class WorkCalendarVersion(Row, Base):
    """One complete saved calendar; the highest revision is current."""

    __tablename__ = "work_calendar_versions"
    calendar_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(String(64))
    working_weekdays: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger))
    entries: Mapped[list] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(String(200))
    author_id: Mapped[UUID]
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "calendar_id", "revision"),
        UniqueConstraint("tenant_id", "calendar_id", "request_key"),
        ForeignKeyConstraint(
            ["tenant_id", "calendar_id"], ["work_calendars.tenant_id", "work_calendars.id"]
        ),
        _principal("author_id"),
        CheckConstraint("revision > 0", name="work_calendar_revision"),
        CheckConstraint(
            "cardinality(working_weekdays) BETWEEN 1 AND 7 "
            "AND working_weekdays <@ ARRAY[1,2,3,4,5,6,7]::smallint[]",
            name="work_calendar_weekdays",
        ),
        CheckConstraint(
            "jsonb_typeof(entries)='array' AND jsonb_array_length(entries) <= 500",
            name="work_calendar_entries",
        ),
        CheckConstraint("char_length(reason) BETWEEN 1 AND 200", name="work_calendar_reason"),
        CheckConstraint("request_sha256 ~ '^[0-9a-f]{64}$'", name="work_calendar_request_sha256"),
    )
