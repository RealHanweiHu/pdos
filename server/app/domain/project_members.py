"""Staff an existing Project: list, add and remove its members.

Project creation seeds only the creator, and offboarding copies memberships to a
successor. These commands are the ordinary way to staff a Project afterwards.
Membership is reach, not permission: what a member may do inside the Project is
still decided by their tenant role (``app.auth.roles``).

Retries are idempotent per ``(tenant, actor, request_id)``. The receipt is the
event itself — ``unique(source, event_id)`` — so no separate ledger is needed:
the same request replays, a reused request id with different content is refused.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import RowMapping

from app.auth.errors import ObjectPermissionDeniedError
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.organization import active_delegated_principals
from app.domain.projects import ProjectNotFoundError
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

# External parties reach projects through their own surfaces, never as staff.
INTERNAL_ROLES = frozenset(
    {Role.OWNER, Role.ADMIN, Role.PROJECT_MANAGER, Role.ENGINEER, Role.QUALITY}
)
# Derived from the policy matrix so a role change there cannot drift from here.
MANAGER_ROLES = frozenset(role for role in Role if is_allowed(role, Action.PROJECT_MEMBERS_MANAGE))

# Shown on the roster before a removal is attempted, and returned if it is anyway.
OWNER_BLOCKER = "项目负责人不能移出项目"
LAST_MANAGER_BLOCKER = "项目须至少保留一名在岗的项目经理成员"

Operation = Literal["add", "remove"]
_SOURCE = "project_service"
_EVENT_TYPES: dict[Operation, str] = {
    "add": "PROJECT_MEMBER_ADDED",
    "remove": "PROJECT_MEMBER_REMOVED",
}


class ProjectMemberError(ValueError):
    """A member command conflicts with the Project's current staffing."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _receipt_key(tenant_id: UUID, actor_user_id: UUID, request_id: UUID) -> str:
    digest = hashlib.sha256(f"{tenant_id}:{actor_user_id}:{request_id}".encode()).hexdigest()
    return f"project-member:{digest}"


def _lock_project(connection: Connection, tenant_id: UUID, project_id: UUID) -> RowMapping:
    # Every member write takes the Project row first, so the last-manager count
    # cannot be raced by a concurrent removal.
    project = (
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
    if project is None:
        raise ProjectNotFoundError
    return project


def _can_manage(
    connection: Connection, tenant_id: UUID, project_id: UUID, actor_user_id: UUID
) -> bool:
    """Recheck current authority after waiting for the project write lock."""
    user = connection.execute(
        select(tables.users.c.role, tables.users.c.is_active).where(
            tables.users.c.tenant_id == tenant_id, tables.users.c.id == actor_user_id
        )
    ).one_or_none()
    if (
        user is None
        or not user.is_active
        or not is_allowed(user.role, Action.PROJECT_MEMBERS_MANAGE)
    ):
        return False
    if user.role in {Role.OWNER, Role.ADMIN}:
        return True
    principals = (
        actor_user_id,
        *active_delegated_principals(
            connection, tenant_id=tenant_id, delegate_user_id=actor_user_id
        ),
    )
    return (
        connection.execute(
            select(tables.project_members.c.id)
            .where(
                tables.project_members.c.tenant_id == tenant_id,
                tables.project_members.c.project_id == project_id,
                tables.project_members.c.user_id.in_(principals),
            )
            .limit(1)
        ).first()
        is not None
    )


def _command_project(
    connection: Connection, key: str, tenant_id: UUID, project_id: UUID, actor_user_id: UUID
) -> RowMapping:
    # A request id is shared across projects, so different project locks alone
    # cannot serialize reuse of that id before the unique event is recorded.
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key}
    )
    project = _lock_project(connection, tenant_id, project_id)
    if not _can_manage(connection, tenant_id, project_id, actor_user_id):
        raise ObjectPermissionDeniedError
    return project


def _replayed(
    connection: Connection,
    *,
    key: str,
    tenant_id: UUID,
    project_id: UUID,
    operation: Operation,
    user_id: UUID,
) -> bool:
    prior = (
        connection.execute(
            select(
                tables.events.c.tenant_id,
                tables.events.c.project_id,
                tables.events.c.event_type,
                tables.events.c.payload,
            ).where(tables.events.c.source == _SOURCE, tables.events.c.event_id == key)
        )
        .mappings()
        .one_or_none()
    )
    if prior is None:
        return False
    if (
        prior["tenant_id"] != tenant_id
        or prior["project_id"] != project_id
        or prior["event_type"] != _EVENT_TYPES[operation]
        or prior["payload"].get("member_user_id") != str(user_id)
    ):
        raise ProjectMemberError(
            "REQUEST_ID_REUSED", "同一请求编号已用于不同的成员变更，请刷新后重试"
        )
    return True


def _is_manager(row: RowMapping) -> bool:
    return bool(row["is_active"]) and row["role"] in MANAGER_ROLES


def roster(
    connection: Connection, *, tenant_id: UUID, project_id: UUID, can_manage: bool
) -> dict[str, Any]:
    project = connection.execute(
        select(tables.projects.c.owner_user_id).where(
            tables.projects.c.tenant_id == tenant_id,
            tables.projects.c.id == project_id,
        )
    ).one_or_none()
    if project is None:
        raise ProjectNotFoundError
    owner = project.owner_user_id
    member = tables.project_members
    user = tables.users
    adder = tables.users.alias("added_by")
    rows = (
        connection.execute(
            select(
                member.c.user_id,
                member.c.added_by_user_id,
                member.c.created_at,
                user.c.username,
                user.c.display_name,
                user.c.role,
                user.c.is_active,
                adder.c.display_name.label("added_by_display_name"),
            )
            .join(user, (user.c.tenant_id == member.c.tenant_id) & (user.c.id == member.c.user_id))
            .join(
                adder,
                (adder.c.tenant_id == member.c.tenant_id)
                & (adder.c.id == member.c.added_by_user_id),
            )
            .where(member.c.tenant_id == tenant_id, member.c.project_id == project_id)
            .order_by(member.c.created_at, member.c.id)
        )
        .mappings()
        .all()
    )
    managers = sum(1 for row in rows if _is_manager(row))
    items: list[dict[str, Any]] = []
    for row in rows:
        blocker = None
        if row["user_id"] == owner:
            blocker = OWNER_BLOCKER
        elif _is_manager(row) and managers <= 1:
            blocker = LAST_MANAGER_BLOCKER
        items.append(
            {
                "user_id": row["user_id"],
                "username": row["username"],
                "display_name": row["display_name"],
                "role": row["role"],
                "is_active": row["is_active"],
                "added_by_user_id": row["added_by_user_id"],
                "added_by_display_name": row["added_by_display_name"],
                "created_at": row["created_at"],
                "is_owner": row["user_id"] == owner,
                "is_manager": _is_manager(row),
                "removal_blocker": blocker,
            }
        )
    available: list[RowMapping] = []
    if can_manage:
        current = select(member.c.user_id).where(
            member.c.tenant_id == tenant_id, member.c.project_id == project_id
        )
        # Offer exactly the people ``add`` would accept.
        available = list(
            connection.execute(
                select(
                    user.c.id.label("user_id"),
                    user.c.username,
                    user.c.display_name,
                    user.c.role,
                )
                .where(
                    user.c.tenant_id == tenant_id,
                    user.c.is_active.is_(True),
                    user.c.role.in_(sorted(INTERNAL_ROLES)),
                    user.c.id.not_in(current),
                )
                .order_by(user.c.display_name, user.c.id)
            ).mappings()
        )
    return {
        "project_id": project_id,
        "owner_user_id": owner,
        "can_manage": can_manage,
        "items": items,
        "available_users": [dict(row) for row in available],
    }


def _record(
    connection: Connection,
    *,
    key: str,
    tenant_id: UUID,
    project_id: UUID,
    actor_user_id: UUID,
    request_id: UUID,
    operation: Operation,
    snapshot: dict[str, Any],
    occurred_at: datetime,
) -> None:
    EventAuditWriter(
        connection,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        project_id=project_id,
    ).record(
        EventDraft(
            event_id=key,
            event_type=_EVENT_TYPES[operation],
            source=_SOURCE,
            entity_id=project_id,
            payload={"member_user_id": snapshot["user_id"]},
            occurred_at=occurred_at,
        ),
        AuditDraft(
            action=f"project.member.{operation}",
            before_snapshot=snapshot if operation == "remove" else None,
            after_snapshot=snapshot if operation == "add" else None,
            context={"request_id": str(request_id)},
        ),
    )


class ProjectMemberService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def roster(self, *, tenant_id: UUID, project_id: UUID, can_manage: bool) -> dict[str, Any]:
        with self._engine.connect() as connection:
            return roster(
                connection, tenant_id=tenant_id, project_id=project_id, can_manage=can_manage
            )

    def add(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        request_id: UUID,
        user_id: UUID,
    ) -> dict[str, Any]:
        key = _receipt_key(tenant_id, actor_user_id, request_id)
        with self._engine.begin() as connection:
            project = _command_project(connection, key, tenant_id, project_id, actor_user_id)
            replayed = _replayed(
                connection,
                key=key,
                tenant_id=tenant_id,
                project_id=project_id,
                operation="add",
                user_id=user_id,
            )
            if not replayed:
                if project["status"] == "archived":
                    raise ProjectMemberError("PROJECT_TERMINAL", "已归档项目不能调整成员")
                candidate = (
                    connection.execute(
                        select(
                            tables.users.c.display_name,
                            tables.users.c.role,
                            tables.users.c.is_active,
                        ).where(
                            tables.users.c.tenant_id == tenant_id,
                            tables.users.c.id == user_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                # Absent, cross-tenant, inactive and external users are one answer.
                if (
                    candidate is None
                    or not candidate["is_active"]
                    or candidate["role"] not in INTERNAL_ROLES
                ):
                    raise ProjectMemberError(
                        "PROJECT_MEMBER_CANDIDATE_INVALID", "只能添加本租户内在岗的内部成员"
                    )
                occurred_at = datetime.now(UTC)
                membership_id = connection.execute(
                    insert(tables.project_members)
                    .values(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        project_id=project_id,
                        user_id=user_id,
                        added_by_user_id=actor_user_id,
                        created_at=occurred_at,
                    )
                    .on_conflict_do_nothing(index_elements=["tenant_id", "project_id", "user_id"])
                    .returning(tables.project_members.c.id)
                ).scalar_one_or_none()
                if membership_id is None:
                    raise ProjectMemberError("PROJECT_MEMBER_EXISTS", "该用户已是项目成员")
                _record(
                    connection,
                    key=key,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    actor_user_id=actor_user_id,
                    request_id=request_id,
                    operation="add",
                    snapshot={
                        "membership_id": str(membership_id),
                        "user_id": str(user_id),
                        "display_name": candidate["display_name"],
                        "role": candidate["role"],
                    },
                    occurred_at=occurred_at,
                )
            return {
                **roster(connection, tenant_id=tenant_id, project_id=project_id, can_manage=True),
                "receipt": {"operation": "add", "user_id": user_id, "replayed": replayed},
            }

    def remove(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        request_id: UUID,
        user_id: UUID,
    ) -> dict[str, Any]:
        key = _receipt_key(tenant_id, actor_user_id, request_id)
        member = tables.project_members
        user = tables.users
        with self._engine.begin() as connection:
            project = _command_project(connection, key, tenant_id, project_id, actor_user_id)
            replayed = _replayed(
                connection,
                key=key,
                tenant_id=tenant_id,
                project_id=project_id,
                operation="remove",
                user_id=user_id,
            )
            if not replayed:
                if project["status"] == "archived":
                    raise ProjectMemberError("PROJECT_TERMINAL", "已归档项目不能调整成员")
                if user_id == project["owner_user_id"]:
                    raise ProjectMemberError("PROJECT_OWNER_MEMBER", OWNER_BLOCKER)
                target = (
                    connection.execute(
                        select(
                            member.c.id,
                            member.c.added_by_user_id,
                            user.c.display_name,
                            user.c.role,
                            user.c.is_active,
                        )
                        .join(
                            user,
                            (user.c.tenant_id == member.c.tenant_id)
                            & (user.c.id == member.c.user_id),
                        )
                        .where(
                            member.c.tenant_id == tenant_id,
                            member.c.project_id == project_id,
                            member.c.user_id == user_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if target is None:
                    raise ProjectMemberError("PROJECT_MEMBER_NOT_FOUND", "该用户不是本项目成员")
                if _is_manager(target):
                    remaining = connection.execute(
                        select(func.count())
                        .select_from(member)
                        .join(
                            user,
                            (user.c.tenant_id == member.c.tenant_id)
                            & (user.c.id == member.c.user_id),
                        )
                        .where(
                            member.c.tenant_id == tenant_id,
                            member.c.project_id == project_id,
                            member.c.user_id != user_id,
                            user.c.is_active.is_(True),
                            user.c.role.in_(sorted(MANAGER_ROLES)),
                        )
                    ).scalar_one()
                    if remaining == 0:
                        raise ProjectMemberError("PROJECT_LAST_MANAGER", LAST_MANAGER_BLOCKER)
                connection.execute(
                    member.delete().where(
                        member.c.tenant_id == tenant_id,
                        member.c.id == target["id"],
                    )
                )
                _record(
                    connection,
                    key=key,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    actor_user_id=actor_user_id,
                    request_id=request_id,
                    operation="remove",
                    snapshot={
                        "membership_id": str(target["id"]),
                        "user_id": str(user_id),
                        "display_name": target["display_name"],
                        "role": target["role"],
                        "added_by_user_id": str(target["added_by_user_id"]),
                    },
                    occurred_at=datetime.now(UTC),
                )
            can_manage = _can_manage(connection, tenant_id, project_id, actor_user_id)
            result = (
                roster(connection, tenant_id=tenant_id, project_id=project_id, can_manage=True)
                if can_manage
                else {
                    "project_id": project_id,
                    "owner_user_id": None,
                    "can_manage": False,
                    "items": [],
                    "available_users": [],
                }
            )
            return {
                **result,
                "access_lost": not can_manage,
                "receipt": {"operation": "remove", "user_id": user_id, "replayed": replayed},
            }
