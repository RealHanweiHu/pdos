"""Parameterized SQL operations for authentication and bootstrap."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Engine, func, select, update
from sqlalchemy.engine import RowMapping

from app.auth.errors import SetupAlreadyCompletedError
from app.db.schema import tables

SETUP_ADVISORY_LOCK_KEY = 0x50444F5353455455


@dataclass(frozen=True)
class TenantRecord:
    id: UUID
    slug: str
    name: str
    status: str


@dataclass(frozen=True)
class UserRecord:
    id: UUID
    tenant_id: UUID
    username: str
    display_name: str
    email: str | None
    password_hash: str | None
    is_active: bool


@dataclass(frozen=True)
class AuthContext:
    tenant: TenantRecord
    user: UserRecord


class AuthRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def needs_setup(self) -> bool:
        with self._engine.connect() as connection:
            user_exists = connection.execute(
                select(tables.users.c.id).limit(1)
            ).scalar_one_or_none()
        return user_exists is None

    def create_initial_context(
        self,
        *,
        tenant_slug: str,
        tenant_name: str,
        username: str,
        display_name: str,
        password_hash: str,
    ) -> AuthContext:
        tenant_id = uuid4()
        user_id = uuid4()
        with self._engine.begin() as connection:
            connection.execute(select(func.pg_advisory_xact_lock(SETUP_ADVISORY_LOCK_KEY)))
            user_exists = connection.execute(
                select(tables.users.c.id).limit(1)
            ).scalar_one_or_none()
            if user_exists is not None:
                raise SetupAlreadyCompletedError
            connection.execute(
                tables.tenants.insert(),
                {
                    "id": tenant_id,
                    "slug": tenant_slug,
                    "name": tenant_name,
                },
            )
            connection.execute(
                tables.users.insert(),
                {
                    "id": user_id,
                    "tenant_id": tenant_id,
                    "username": username,
                    "display_name": display_name,
                    "password_hash": password_hash,
                },
            )
        return AuthContext(
            tenant=TenantRecord(
                id=tenant_id,
                slug=tenant_slug,
                name=tenant_name,
                status="active",
            ),
            user=UserRecord(
                id=user_id,
                tenant_id=tenant_id,
                username=username,
                display_name=display_name,
                email=None,
                password_hash=password_hash,
                is_active=True,
            ),
        )

    def find_login_context(self, *, tenant_slug: str, username: str) -> AuthContext | None:
        statement = (
            select(
                tables.tenants.c.id.label("tenant_id"),
                tables.tenants.c.slug.label("tenant_slug"),
                tables.tenants.c.name.label("tenant_name"),
                tables.tenants.c.status.label("tenant_status"),
                tables.users.c.id.label("user_id"),
                tables.users.c.username,
                tables.users.c.display_name,
                tables.users.c.email,
                tables.users.c.password_hash,
                tables.users.c.is_active,
            )
            .select_from(
                tables.users.join(
                    tables.tenants,
                    tables.tenants.c.id == tables.users.c.tenant_id,
                )
            )
            .where(
                tables.tenants.c.slug == tenant_slug,
                tables.users.c.username == username,
                tables.tenants.c.status == "active",
                tables.users.c.is_active.is_(True),
            )
        )
        with self._engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return self._context_from_mapping(row) if row is not None else None

    def find_user_context(self, user_id: UUID) -> AuthContext | None:
        statement = (
            select(
                tables.tenants.c.id.label("tenant_id"),
                tables.tenants.c.slug.label("tenant_slug"),
                tables.tenants.c.name.label("tenant_name"),
                tables.tenants.c.status.label("tenant_status"),
                tables.users.c.id.label("user_id"),
                tables.users.c.username,
                tables.users.c.display_name,
                tables.users.c.email,
                tables.users.c.password_hash,
                tables.users.c.is_active,
            )
            .select_from(
                tables.users.join(
                    tables.tenants,
                    tables.tenants.c.id == tables.users.c.tenant_id,
                )
            )
            .where(tables.users.c.id == user_id)
        )
        with self._engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return self._context_from_mapping(row) if row is not None else None

    def record_successful_login(self, *, user_id: UUID, signed_in_at: datetime) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                update(tables.users)
                .where(tables.users.c.id == user_id)
                .values(last_signed_in_at=signed_in_at, updated_at=signed_in_at)
            )

    @staticmethod
    def _context_from_mapping(row: RowMapping) -> AuthContext:
        return AuthContext(
            tenant=TenantRecord(
                id=row["tenant_id"],
                slug=row["tenant_slug"],
                name=row["tenant_name"],
                status=row["tenant_status"],
            ),
            user=UserRecord(
                id=row["user_id"],
                tenant_id=row["tenant_id"],
                username=row["username"],
                display_name=row["display_name"],
                email=row["email"],
                password_hash=row["password_hash"],
                is_active=row["is_active"],
            ),
        )
