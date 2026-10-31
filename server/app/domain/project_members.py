"""Project membership: who may see and own work inside one Project."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, Table, delete, func, select

from app.db.schema import tables
from app.domain.tasks import TERMINAL_TASK_STATUSES
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class ProjectMemberProjectNotFoundError(LookupError):
    """Raised when the Project is absent from the active tenant."""


class ProjectMemberUserNotFoundError(LookupError):
    """Raised when the user is absent, inactive, or outside the tenant."""


class ProjectMemberNotFoundError(LookupError):
    """Raised when removing a user who is not a member."""


class ProjectMemberExistsError(ValueError):
    """Raised when adding a user who is already a member."""


class ProjectMemberOwnerError(ValueError):
    """Raised when removing the Project owner, who must stay a member."""


class ProjectMemberArchivedError(ValueError):
    """Raised when membership of an archived Project is changed."""


class ProjectMemberOpenWorkError(ValueError):
    """Raised when removing a member who still owns unfinished work."""

    def __init__(self, open_work: dict[str, int]) -> None:
        super().__init__("member still owns unfinished work")
        self.open_work = open_work


@dataclass(frozen=True)
class MemberCandidate:
    user_id: UUID
    display_name: str
    role: str


# Unfinished work a member owns; removing them would leave it with an owner outside the Project.
_OPEN_WORK: tuple[tuple[str, Table, str, frozenset[str]], ...] = (
    ("tasks", tables.tasks, "assignee_user_id", TERMINAL_TASK_STATUSES),
    ("issues", tables.issues, "owner_user_id", frozenset({"closed"})),
    ("risks", tables.risks, "owner_user_id", frozenset({"closed"})),
    ("complaints", tables.complaints, "owner_user_id", frozenset({"resolved", "closed"})),
    ("ncrs", tables.nonconformance_reports, "owner_user_id", frozenset({"closed"})),
    ("capa_actions", tables.capa_actions, "owner_user_id", frozenset({"completed"})),
)


def _member_snapshot(user_id: UUID, display_name: str, role: str) -> dict[str, object]:
    return {"user_id": str(user_id), "display_name": display_name, "role": role}


class ProjectMemberService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _lock_project(connection: Connection, *, tenant_id: UUID, project_id: UUID) -> UUID:
        row = (
            connection.execute(
                select(tables.projects.c.status, tables.projects.c.owner_user_id)
                .where(
                    tables.projects.c.tenant_id == tenant_id,
                    tables.projects.c.id == project_id,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ProjectMemberProjectNotFoundError
        if row["status"] == "archived":
            raise ProjectMemberArchivedError
        return UUID(str(row["owner_user_id"]))

    @staticmethod
    def _user(connection: Connection, *, tenant_id: UUID, user_id: UUID) -> tuple[str, str, bool]:
        row = (
            connection.execute(
                select(
                    tables.users.c.display_name,
                    tables.users.c.role,
                    tables.users.c.is_active,
                ).where(tables.users.c.tenant_id == tenant_id, tables.users.c.id == user_id)
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ProjectMemberUserNotFoundError
        return row["display_name"], row["role"], row["is_active"]

    @staticmethod
    def _open_work(
        connection: Connection, *, tenant_id: UUID, project_id: UUID, user_id: UUID
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for label, table, owner_column, closed_statuses in _OPEN_WORK:
            count = connection.execute(
                select(func.count())
                .select_from(table)
                .where(
                    table.c.tenant_id == tenant_id,
                    table.c.project_id == project_id,
                    table.c[owner_column] == user_id,
                    table.c.status.not_in(closed_statuses),
                )
            ).scalar_one()
            if count:
                counts[label] = int(count)
        return counts

    def candidates(self, *, tenant_id: UUID, project_id: UUID) -> list[MemberCandidate]:
        """Active tenant users who are not yet members of the Project."""
        existing = select(tables.project_members.c.user_id).where(
            tables.project_members.c.tenant_id == tenant_id,
            tables.project_members.c.project_id == project_id,
        )
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(tables.users.c.id, tables.users.c.display_name, tables.users.c.role)
                .where(
                    tables.users.c.tenant_id == tenant_id,
                    tables.users.c.is_active.is_(True),
                    tables.users.c.id.not_in(existing),
                )
                .order_by(tables.users.c.display_name, tables.users.c.id)
            ).mappings()
            return [
                MemberCandidate(
                    user_id=row["id"], display_name=row["display_name"], role=row["role"]
                )
                for row in rows
            ]

    def add(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        user_id: UUID,
    ) -> None:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            self._lock_project(connection, tenant_id=tenant_id, project_id=project_id)
            display_name, role, is_active = self._user(
                connection, tenant_id=tenant_id, user_id=user_id
            )
            if not is_active:
                raise ProjectMemberUserNotFoundError
            exists = connection.execute(
                select(tables.project_members.c.id).where(
                    tables.project_members.c.tenant_id == tenant_id,
                    tables.project_members.c.project_id == project_id,
                    tables.project_members.c.user_id == user_id,
                )
            ).scalar_one_or_none()
            if exists is not None:
                raise ProjectMemberExistsError
            connection.execute(
                tables.project_members.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "user_id": user_id,
                    "added_by_user_id": actor_user_id,
                    "created_at": occurred_at,
                },
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"project-member:{project_id}:added:{uuid4()}",
                    event_type="PROJECT_MEMBER_ADDED",
                    source="project_member_service",
                    entity_id=project_id,
                    payload={"user_id": str(user_id), "role": role},
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="project.member.add",
                    after_snapshot=_member_snapshot(user_id, display_name, role),
                ),
            )

    def remove(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        user_id: UUID,
    ) -> None:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            owner_user_id = self._lock_project(
                connection, tenant_id=tenant_id, project_id=project_id
            )
            member_id = connection.execute(
                select(tables.project_members.c.id).where(
                    tables.project_members.c.tenant_id == tenant_id,
                    tables.project_members.c.project_id == project_id,
                    tables.project_members.c.user_id == user_id,
                )
            ).scalar_one_or_none()
            if member_id is None:
                raise ProjectMemberNotFoundError
            if user_id == owner_user_id:
                raise ProjectMemberOwnerError
            open_work = self._open_work(
                connection, tenant_id=tenant_id, project_id=project_id, user_id=user_id
            )
            if open_work:
                raise ProjectMemberOpenWorkError(open_work)
            display_name, role, _ = self._user(connection, tenant_id=tenant_id, user_id=user_id)
            connection.execute(
                delete(tables.project_members).where(
                    tables.project_members.c.tenant_id == tenant_id,
                    tables.project_members.c.id == member_id,
                )
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"project-member:{project_id}:removed:{uuid4()}",
                    event_type="PROJECT_MEMBER_REMOVED",
                    source="project_member_service",
                    entity_id=project_id,
                    payload={"user_id": str(user_id), "role": role},
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="project.member.remove",
                    before_snapshot=_member_snapshot(user_id, display_name, role),
                ),
            )
