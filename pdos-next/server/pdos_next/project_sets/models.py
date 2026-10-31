"""Organization-owned project grouping, independent of project authorization."""

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


class ProjectSet(Row, Base):
    __tablename__ = "project_set_versions"
    set_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(500))
    author_id: Mapped[UUID]
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "set_id", "revision"),
        UniqueConstraint("tenant_id", "author_id", "request_key"),
        ForeignKeyConstraint(["tenant_id", "author_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("revision>0 AND char_length(btrim(name)) BETWEEN 1 AND 80"),
    )


class ProjectSetLink(Row, Base):
    __tablename__ = "project_set_links"
    project_id: Mapped[UUID]
    set_id: Mapped[UUID | None]
    revision: Mapped[int] = mapped_column(Integer)
    author_id: Mapped[UUID]
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "project_id", "revision"),
        UniqueConstraint("tenant_id", "author_id", "request_key", "project_id"),
        ForeignKeyConstraint(["project_id"], ["projects.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "set_id"], ["project_set_versions.tenant_id", "project_set_versions.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "author_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("revision>0"),
    )
