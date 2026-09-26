"""Tenant-bound project authorization independent from HTTP transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import Engine, select

from app.auth.errors import ObjectPermissionDeniedError
from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, allowed_actions, is_allowed
from app.db.schema import tables
from app.domain.organization import active_delegated_principals


class ProjectAccessReader(Protocol):
    def project_exists(self, *, tenant_id: UUID, project_id: UUID) -> bool: ...

    def is_project_member(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        user_id: UUID,
    ) -> bool: ...

    def delegated_principals(
        self,
        *,
        tenant_id: UUID,
        delegate_user_id: UUID,
    ) -> tuple[UUID, ...]: ...


@dataclass(frozen=True)
class ProjectAccess:
    tenant_id: UUID
    project_id: UUID
    user_id: UUID
    role: Role
    allowed_actions: frozenset[Action]
    # Set when project reach was borrowed from a principal on leave (V1-A11).
    # The delegate still acts under their own identity and their own role.
    acting_for_user_id: UUID | None = None


class SqlProjectAccessRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def project_exists(self, *, tenant_id: UUID, project_id: UUID) -> bool:
        statement = select(tables.projects.c.id).where(
            tables.projects.c.tenant_id == tenant_id,
            tables.projects.c.id == project_id,
        )
        with self._engine.connect() as connection:
            return connection.execute(statement).scalar_one_or_none() is not None

    def is_project_member(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        user_id: UUID,
    ) -> bool:
        statement = select(tables.project_members.c.id).where(
            tables.project_members.c.tenant_id == tenant_id,
            tables.project_members.c.project_id == project_id,
            tables.project_members.c.user_id == user_id,
        )
        with self._engine.connect() as connection:
            return connection.execute(statement).scalar_one_or_none() is not None

    def delegated_principals(
        self,
        *,
        tenant_id: UUID,
        delegate_user_id: UUID,
    ) -> tuple[UUID, ...]:
        with self._engine.connect() as connection:
            return active_delegated_principals(
                connection, tenant_id=tenant_id, delegate_user_id=delegate_user_id
            )


class ProjectAccessService:
    def __init__(self, repository: ProjectAccessReader) -> None:
        self._repository = repository

    def authorize(
        self,
        *,
        context: AuthContext,
        project_id: UUID,
        action: Action | str,
    ) -> ProjectAccess:
        tenant_id = context.tenant.id
        user_id = context.user.id
        role = context.user.role

        if not self._repository.project_exists(tenant_id=tenant_id, project_id=project_id):
            raise ObjectPermissionDeniedError
        acting_for: UUID | None = None
        if role not in {Role.OWNER, Role.ADMIN} and not self._repository.is_project_member(
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
        ):
            # V1-A11: an active delegate borrows the principal's project reach.
            # Only membership is borrowed — the role check below still uses the
            # delegate's own role, so delegation never escalates permissions.
            acting_for = self._delegated_membership(
                tenant_id=tenant_id, project_id=project_id, user_id=user_id
            )
            if acting_for is None:
                raise ObjectPermissionDeniedError
        if not is_allowed(role, action):
            raise ObjectPermissionDeniedError

        return ProjectAccess(
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
            role=role,
            allowed_actions=allowed_actions(role),
            acting_for_user_id=acting_for,
        )

    def _delegated_membership(
        self, *, tenant_id: UUID, project_id: UUID, user_id: UUID
    ) -> UUID | None:
        for principal_id in self._repository.delegated_principals(
            tenant_id=tenant_id, delegate_user_id=user_id
        ):
            if self._repository.is_project_member(
                tenant_id=tenant_id, project_id=project_id, user_id=principal_id
            ):
                return principal_id
        return None
