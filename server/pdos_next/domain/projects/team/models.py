"""Project team (P34-1): named members, roles from a tenant catalog, one lead per role.

Membership never grants access. Scope comes from the project row under its own
row-level security, so these tables carry no category column of their own.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.core.models import Base, Row


def _principal(column):
    return ForeignKeyConstraint(["tenant_id", column], ["principals.tenant_id", "principals.id"])


class RoleCatalogVersion(Row, Base):
    """Tenant role catalog, append-only. No row means the built-in default (revision 0)."""

    __tablename__ = "project_role_catalog_versions"
    revision: Mapped[int] = mapped_column(Integer)
    roles: Mapped[list] = mapped_column(JSONB)
    author_id: Mapped[UUID]
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "revision"),
        UniqueConstraint("tenant_id", "author_id", "request_key"),
        _principal("author_id"),
        CheckConstraint(
            "revision>0 AND jsonb_typeof(roles)='array' AND request_sha256 ~ '^[a-f0-9]{64}$'",
            name="project_role_catalog_shape",
        ),
    )


class TeamChange(Row, Base):
    """One accepted change set to a project's team; its revision is the team revision."""

    __tablename__ = "project_team_changes"
    project_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16))
    author_id: Mapped[UUID]
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    changes: Mapped[list] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "project_id", "id"),
        UniqueConstraint("tenant_id", "project_id", "revision"),
        UniqueConstraint("tenant_id", "author_id", "request_key"),
        ForeignKeyConstraint(["project_id"], ["projects.id"]),
        _principal("author_id"),
        CheckConstraint(
            "revision>0 AND source IN ('owner','g0','backfill') "
            "AND jsonb_typeof(changes)='array' AND request_sha256 ~ '^[a-f0-9]{64}$'",
            name="project_team_change_shape",
        ),
    )


class ProjectMember(Row, Base):
    """One stint of a named person on a project; leaving closes it, nothing is deleted."""

    __tablename__ = "project_members"
    project_id: Mapped[UUID]
    principal_id: Mapped[UUID]
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    added_by: Mapped[UUID]
    joined_change_id: Mapped[UUID]
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by: Mapped[UUID | None]
    left_change_id: Mapped[UUID | None]
    departed_roles: Mapped[list | None] = mapped_column(JSONB)
    # P56: a person who leaves with unhanded work loses the project audience at once
    # and keeps only their own open items through the handover lane until it settles.
    handover_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "project_id", "id"),
        ForeignKeyConstraint(["project_id"], ["projects.id"]),
        _principal("principal_id"),
        _principal("added_by"),
        _principal("removed_by"),
        ForeignKeyConstraint(
            ["tenant_id", "project_id", "joined_change_id"],
            [
                "project_team_changes.tenant_id",
                "project_team_changes.project_id",
                "project_team_changes.id",
            ],
            name="project_member_joined_change_fk",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "project_id", "left_change_id"],
            [
                "project_team_changes.tenant_id",
                "project_team_changes.project_id",
                "project_team_changes.id",
            ],
            name="project_member_left_change_fk",
        ),
        Index(
            "uq_project_member_active",
            "tenant_id",
            "project_id",
            "principal_id",
            unique=True,
            postgresql_where=text("left_at IS NULL"),
        ),
        CheckConstraint(
            "((left_at IS NULL) = (removed_by IS NULL)) "
            "AND ((left_at IS NULL) = (left_change_id IS NULL)) "
            "AND ((left_at IS NULL) = (departed_roles IS NULL)) "
            "AND (departed_roles IS NULL OR jsonb_typeof(departed_roles)='array') "
            "AND (left_at IS NULL OR left_at >= joined_at) "
            "AND (NOT handover_pending OR left_at IS NOT NULL)",
            name="project_member_stint",
        ),
    )


class MemberRole(Row, Base):
    """A current role of an active member; at most one lead per role per project."""

    __tablename__ = "project_member_roles"
    project_id: Mapped[UUID]
    member_id: Mapped[UUID]
    role_key: Mapped[str] = mapped_column(String(64))
    is_lead: Mapped[bool] = mapped_column(Boolean)
    change_id: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "member_id", "role_key"),
        ForeignKeyConstraint(
            ["tenant_id", "project_id", "member_id"],
            ["project_members.tenant_id", "project_members.project_id", "project_members.id"],
            name="project_member_role_member_fk",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "project_id", "change_id"],
            [
                "project_team_changes.tenant_id",
                "project_team_changes.project_id",
                "project_team_changes.id",
            ],
            name="project_member_role_change_fk",
        ),
        Index(
            "uq_project_role_lead",
            "tenant_id",
            "project_id",
            "role_key",
            unique=True,
            postgresql_where=text("is_lead"),
        ),
        CheckConstraint("role_key ~ '^[a-z][a-z0-9_]{1,63}$'", name="project_member_role_key"),
    )


UPSTREAM_TYPES = ("products", "definition_revisions", "product_variants", "variant_revisions")


class MemberAudience(Row, Base):
    """Upstream model/definition audience a membership relies on, and whether it added it.

    Rows added for this membership are withdrawn when it is fully removed, unless
    another current membership still relies on them; pre-existing rows are kept.
    """

    __tablename__ = "project_member_audiences"
    project_id: Mapped[UUID]
    member_id: Mapped[UUID]
    object_type: Mapped[str] = mapped_column(String(64))
    subject_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    principal_id: Mapped[UUID]
    inserted: Mapped[bool] = mapped_column(Boolean)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "member_id", "object_type", "subject_id"),
        ForeignKeyConstraint(
            ["tenant_id", "project_id", "member_id"],
            ["project_members.tenant_id", "project_members.project_id", "project_members.id"],
            name="project_member_audience_member_fk",
        ),
        _principal("owner_id"),
        _principal("principal_id"),
        CheckConstraint(
            "object_type IN "
            "('products','definition_revisions','product_variants','variant_revisions')",
            name="project_member_audience_type",
        ),
    )
