"""Tenant-bound account administration with role and credential invariants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, RowMapping, select, update
from sqlalchemy.exc import IntegrityError

from app.auth.passwords import PasswordService
from app.auth.roles import Role
from app.db.schema import tables
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

PRIVILEGED_ROLES = frozenset({Role.OWNER, Role.ADMIN})
ADMIN_ASSIGNABLE_ROLES = frozenset(
    {Role.PROJECT_MANAGER, Role.ENGINEER, Role.QUALITY, Role.SUPPLIER, Role.CUSTOMER}
)


class UserAdministrationError(RuntimeError):
    """Base error for stable API mapping."""


class UserManagementForbiddenError(UserAdministrationError):
    pass


class PrivilegedRoleRequiresOwnerError(UserAdministrationError):
    pass


class PrivilegedAccountRequiresOwnerError(UserAdministrationError):
    pass


class SelfRoleOrStatusChangeError(UserAdministrationError):
    pass


class SelfPasswordResetError(UserAdministrationError):
    pass


class UserNotFoundError(UserAdministrationError):
    pass


class UsernameAlreadyExistsError(UserAdministrationError):
    pass


class EmailAlreadyExistsError(UserAdministrationError):
    pass


class EmptyUserUpdateError(UserAdministrationError):
    pass


class LastActiveOwnerRequiredError(UserAdministrationError):
    pass


@dataclass(frozen=True)
class ManagedUser:
    id: UUID
    tenant_id: UUID
    username: str
    display_name: str
    email: str | None
    role: Role
    is_active: bool
    last_signed_in_at: datetime | None
    created_at: datetime
    updated_at: datetime


PUBLIC_COLUMNS = (
    tables.users.c.id,
    tables.users.c.tenant_id,
    tables.users.c.username,
    tables.users.c.display_name,
    tables.users.c.email,
    tables.users.c.role,
    tables.users.c.is_active,
    tables.users.c.last_signed_in_at,
    tables.users.c.created_at,
    tables.users.c.updated_at,
)


def _managed_user(row: RowMapping) -> ManagedUser:
    return ManagedUser(
        id=row["id"],
        tenant_id=row["tenant_id"],
        username=row["username"],
        display_name=row["display_name"],
        email=row["email"],
        role=Role(row["role"]),
        is_active=row["is_active"],
        last_signed_in_at=row["last_signed_in_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _snapshot(user: ManagedUser) -> dict[str, Any]:
    return {
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "role": user.role.value,
        "is_active": user.is_active,
    }


def _require_manager(actor_role: Role) -> None:
    if actor_role not in PRIVILEGED_ROLES:
        raise UserManagementForbiddenError


def _require_assignable(actor_role: Role, target_role: Role) -> None:
    if actor_role is Role.ADMIN and target_role not in ADMIN_ASSIGNABLE_ROLES:
        raise PrivilegedRoleRequiresOwnerError


def _require_target_access(actor_role: Role, target_role: Role) -> None:
    if actor_role is Role.ADMIN and target_role in PRIVILEGED_ROLES:
        raise PrivilegedAccountRequiresOwnerError


def _constraint_name(error: IntegrityError) -> str:
    diagnostic = getattr(error.orig, "diag", None)
    return str(getattr(diagnostic, "constraint_name", "") or "")


class UserAdministrationService:
    def __init__(self, engine: Engine, passwords: PasswordService | None = None) -> None:
        self._engine = engine
        self._passwords = passwords or PasswordService()

    def list_users(self, *, tenant_id: UUID, actor_role: Role) -> tuple[ManagedUser, ...]:
        _require_manager(actor_role)
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(*PUBLIC_COLUMNS)
                .where(tables.users.c.tenant_id == tenant_id)
                .order_by(tables.users.c.created_at, tables.users.c.username)
            ).mappings()
            return tuple(_managed_user(row) for row in rows)

    def create_user(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        actor_role: Role,
        username: str,
        display_name: str,
        email: str | None,
        role: Role,
        password: str,
    ) -> ManagedUser:
        _require_manager(actor_role)
        _require_assignable(actor_role, role)
        user_id = uuid4()
        occurred_at = datetime.now(UTC)
        password_hash = self._passwords.hash(password)
        try:
            with self._engine.begin() as connection:
                self._require_unique(
                    connection,
                    tenant_id=tenant_id,
                    username=username,
                    email=email,
                )
                row = (
                    connection.execute(
                        tables.users.insert()
                        .values(
                            id=user_id,
                            tenant_id=tenant_id,
                            username=username,
                            display_name=display_name,
                            email=email,
                            role=role.value,
                            password_hash=password_hash,
                            auth_version=1,
                            is_active=True,
                            created_at=occurred_at,
                            updated_at=occurred_at,
                        )
                        .returning(*PUBLIC_COLUMNS)
                    )
                    .mappings()
                    .one()
                )
                created = _managed_user(row)
                EventAuditWriter(
                    connection, tenant_id=tenant_id, actor_user_id=actor_user_id
                ).record(
                    EventDraft(
                        event_id=f"user:{user_id}:created",
                        event_type="USER_CREATED",
                        source="user_administration_service",
                        entity_id=user_id,
                        payload={
                            "username": username,
                            "role": role.value,
                            "is_active": True,
                        },
                        occurred_at=occurred_at,
                    ),
                    AuditDraft(
                        action="user.create",
                        after_snapshot=_snapshot(created),
                        context={"actor_role": actor_role.value},
                    ),
                )
                return created
        except IntegrityError as error:
            constraint = _constraint_name(error)
            if constraint == "uq_users_tenant_username":
                raise UsernameAlreadyExistsError from error
            if constraint == "uq_users_tenant_email":
                raise EmailAlreadyExistsError from error
            raise

    def update_user(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        actor_role: Role,
        user_id: UUID,
        changes: dict[str, object],
    ) -> ManagedUser:
        _require_manager(actor_role)
        if not changes:
            raise EmptyUserUpdateError
        occurred_at = datetime.now(UTC)
        try:
            with self._engine.begin() as connection:
                before = self._locked_user(connection, tenant_id=tenant_id, user_id=user_id)
                _require_target_access(actor_role, before.role)
                role_change = changes.get("role", before.role)
                requested_role = (
                    role_change if isinstance(role_change, Role) else Role(str(role_change))
                )
                _require_assignable(actor_role, requested_role)
                if actor_user_id == user_id and ({"role", "is_active"} & changes.keys()):
                    raise SelfRoleOrStatusChangeError

                next_active = bool(changes.get("is_active", before.is_active))
                if (
                    before.role is Role.OWNER
                    and before.is_active
                    and (requested_role is not Role.OWNER or not next_active)
                ):
                    active_owner_ids = tuple(
                        connection.execute(
                            select(tables.users.c.id)
                            .where(
                                tables.users.c.tenant_id == tenant_id,
                                tables.users.c.role == Role.OWNER.value,
                                tables.users.c.is_active.is_(True),
                            )
                            .order_by(tables.users.c.id)
                            .with_for_update()
                        ).scalars()
                    )
                    if len(active_owner_ids) <= 1:
                        raise LastActiveOwnerRequiredError

                if "email" in changes or "username" in changes:
                    self._require_unique(
                        connection,
                        tenant_id=tenant_id,
                        username=before.username,
                        email=changes.get("email", before.email),
                        exclude_user_id=user_id,
                    )
                before_snapshot = _snapshot(before)
                proposed_snapshot = {
                    "display_name": changes.get("display_name", before.display_name),
                    "email": changes.get("email", before.email),
                    "role": requested_role.value,
                    "is_active": next_active,
                }
                changed_fields = [
                    field
                    for field in ("display_name", "email", "role", "is_active")
                    if field in changes and before_snapshot[field] != proposed_snapshot[field]
                ]
                if not changed_fields:
                    return before
                values: dict[str, object] = {
                    field: proposed_snapshot[field] for field in changed_fields
                }
                values["updated_at"] = occurred_at
                row = (
                    connection.execute(
                        update(tables.users)
                        .where(
                            tables.users.c.tenant_id == tenant_id,
                            tables.users.c.id == user_id,
                        )
                        .values(**values)
                        .returning(*PUBLIC_COLUMNS)
                    )
                    .mappings()
                    .one()
                )
                after = _managed_user(row)
                EventAuditWriter(
                    connection, tenant_id=tenant_id, actor_user_id=actor_user_id
                ).record(
                    EventDraft(
                        event_id=f"user:{user_id}:updated:{uuid4()}",
                        event_type="USER_UPDATED",
                        source="user_administration_service",
                        entity_id=user_id,
                        payload={
                            "changed_fields": changed_fields,
                            "role": after.role.value,
                            "is_active": after.is_active,
                        },
                        occurred_at=occurred_at,
                    ),
                    AuditDraft(
                        action="user.update",
                        before_snapshot={field: before_snapshot[field] for field in changed_fields},
                        after_snapshot={field: _snapshot(after)[field] for field in changed_fields},
                        context={"actor_role": actor_role.value},
                    ),
                )
                return after
        except IntegrityError as error:
            if _constraint_name(error) == "uq_users_tenant_email":
                raise EmailAlreadyExistsError from error
            raise

    def reset_password(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        actor_role: Role,
        user_id: UUID,
        password: str,
    ) -> ManagedUser:
        _require_manager(actor_role)
        if actor_user_id == user_id:
            raise SelfPasswordResetError
        occurred_at = datetime.now(UTC)
        password_hash = self._passwords.hash(password)
        with self._engine.begin() as connection:
            before = self._locked_user(connection, tenant_id=tenant_id, user_id=user_id)
            _require_target_access(actor_role, before.role)
            credential_version = connection.execute(
                update(tables.users)
                .where(
                    tables.users.c.tenant_id == tenant_id,
                    tables.users.c.id == user_id,
                )
                .values(
                    password_hash=password_hash,
                    auth_version=tables.users.c.auth_version + 1,
                    updated_at=occurred_at,
                )
                .returning(tables.users.c.auth_version)
            ).scalar_one()
            row = (
                connection.execute(
                    select(*PUBLIC_COLUMNS).where(
                        tables.users.c.tenant_id == tenant_id,
                        tables.users.c.id == user_id,
                    )
                )
                .mappings()
                .one()
            )
            after = _managed_user(row)
            EventAuditWriter(connection, tenant_id=tenant_id, actor_user_id=actor_user_id).record(
                EventDraft(
                    event_id=f"user:{user_id}:credential:{credential_version}",
                    event_type="USER_PASSWORD_RESET",
                    source="user_administration_service",
                    entity_id=user_id,
                    payload={"credential_version": credential_version},
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="user.password_reset",
                    before_snapshot={"credential_version": credential_version - 1},
                    after_snapshot={"credential_version": credential_version},
                    context={"actor_role": actor_role.value},
                ),
            )
            return after

    @staticmethod
    def _locked_user(connection: Any, *, tenant_id: UUID, user_id: UUID) -> ManagedUser:
        row = (
            connection.execute(
                select(*PUBLIC_COLUMNS)
                .where(tables.users.c.tenant_id == tenant_id, tables.users.c.id == user_id)
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise UserNotFoundError
        return _managed_user(row)

    @staticmethod
    def _require_unique(
        connection: Any,
        *,
        tenant_id: UUID,
        username: str,
        email: object,
        exclude_user_id: UUID | None = None,
    ) -> None:
        username_query = select(tables.users.c.id).where(
            tables.users.c.tenant_id == tenant_id,
            tables.users.c.username == username,
        )
        if exclude_user_id is not None:
            username_query = username_query.where(tables.users.c.id != exclude_user_id)
        if connection.execute(username_query).scalar_one_or_none() is not None:
            raise UsernameAlreadyExistsError
        if email is not None:
            email_query = select(tables.users.c.id).where(
                tables.users.c.tenant_id == tenant_id,
                tables.users.c.email == str(email),
            )
            if exclude_user_id is not None:
                email_query = email_query.where(tables.users.c.id != exclude_user_id)
            if connection.execute(email_query).scalar_one_or_none() is not None:
                raise EmailAlreadyExistsError
