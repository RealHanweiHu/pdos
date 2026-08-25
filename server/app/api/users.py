"""Owner/Admin HTTP surface for tenant account administration."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, NoReturn, Self
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.db.engine import get_engine
from app.domain.users import (
    EmailAlreadyExistsError,
    EmptyUserUpdateError,
    LastActiveOwnerRequiredError,
    ManagedUser,
    PrivilegedAccountRequiresOwnerError,
    PrivilegedRoleRequiresOwnerError,
    SelfPasswordResetError,
    SelfRoleOrStatusChangeError,
    UserAdministrationService,
    UserManagementForbiddenError,
    UsernameAlreadyExistsError,
    UserNotFoundError,
)

router = APIRouter(prefix="/api/admin/users", tags=["user-administration"])
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_email(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return None
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("invalid email")
        return normalized
    return value


class UserCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=256)
    email: str | None = Field(default=None, max_length=320)
    role: Role
    password: SecretStr = Field(min_length=12, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return _normalize_email(value)


class UserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=256)
    email: str | None = Field(default=None, max_length=320)
    role: Role | None = None
    is_active: bool | None = None

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return _normalize_email(value)

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        for required in ("display_name", "role", "is_active"):
            if required in self.model_fields_set and getattr(self, required) is None:
                raise ValueError(f"{required} cannot be null")
        return self

    def changes(self) -> dict[str, object]:
        return {
            field: getattr(self, field)
            for field in self.model_fields_set
            if field in {"display_name", "email", "role", "is_active"}
        }


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: SecretStr = Field(min_length=12, max_length=128)


class ManagedUserResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

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


class ManagedUserListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: tuple[ManagedUserResponse, ...]


def _response(user: ManagedUser) -> ManagedUserResponse:
    return ManagedUserResponse(
        id=user.id,
        tenant_id=user.tenant_id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        last_signed_in_at=user.last_signed_in_at,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def get_service(engine: Annotated[Engine, Depends(get_engine)]) -> UserAdministrationService:
    return UserAdministrationService(engine)


def _authorize(context: AuthContext) -> None:
    if not is_allowed(context.user.role, Action.USER_MANAGE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "USER_MANAGEMENT_FORBIDDEN", "message": "User management denied"},
        )


def _raise_domain(error: Exception) -> NoReturn:
    mappings: tuple[tuple[type[Exception], int, str, str], ...] = (
        (UserManagementForbiddenError, 403, "USER_MANAGEMENT_FORBIDDEN", "User management denied"),
        (
            PrivilegedRoleRequiresOwnerError,
            403,
            "PRIVILEGED_ROLE_REQUIRES_OWNER",
            "Only an Owner can assign Owner or Admin",
        ),
        (
            PrivilegedAccountRequiresOwnerError,
            403,
            "PRIVILEGED_ACCOUNT_REQUIRES_OWNER",
            "Only an Owner can manage a privileged account",
        ),
        (
            SelfRoleOrStatusChangeError,
            409,
            "SELF_ROLE_OR_STATUS_CHANGE_FORBIDDEN",
            "Use another Owner to change your own role or status",
        ),
        (SelfPasswordResetError, 409, "SELF_PASSWORD_RESET_FORBIDDEN", "Use password change"),
        (LastActiveOwnerRequiredError, 409, "LAST_ACTIVE_OWNER_REQUIRED", "Keep one active Owner"),
        (UsernameAlreadyExistsError, 409, "USERNAME_ALREADY_EXISTS", "Username already exists"),
        (EmailAlreadyExistsError, 409, "EMAIL_ALREADY_EXISTS", "Email already exists"),
        (EmptyUserUpdateError, 422, "EMPTY_USER_UPDATE", "At least one field is required"),
        (UserNotFoundError, 404, "USER_NOT_FOUND", "User not found"),
    )
    for error_type, status_code, code, message in mappings:
        if isinstance(error, error_type):
            raise HTTPException(
                status_code=status_code,
                detail={"code": code, "message": message},
            ) from error
    raise error


@router.get("", response_model=ManagedUserListResponse)
def list_users(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    service: Annotated[UserAdministrationService, Depends(get_service)],
) -> ManagedUserListResponse:
    no_store(response)
    _authorize(context)
    try:
        users = service.list_users(tenant_id=context.tenant.id, actor_role=context.user.role)
    except Exception as error:
        _raise_domain(error)
    return ManagedUserListResponse(items=tuple(_response(user) for user in users))


@router.post("", response_model=ManagedUserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    service: Annotated[UserAdministrationService, Depends(get_service)],
) -> ManagedUserResponse:
    no_store(response)
    _authorize(context)
    try:
        user = service.create_user(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            actor_role=context.user.role,
            username=payload.username,
            display_name=payload.display_name,
            email=payload.email,
            role=payload.role,
            password=payload.password.get_secret_value(),
        )
    except Exception as error:
        _raise_domain(error)
    return _response(user)


@router.patch("/{user_id}", response_model=ManagedUserResponse)
def update_user(
    user_id: UUID,
    payload: UserUpdateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    service: Annotated[UserAdministrationService, Depends(get_service)],
) -> ManagedUserResponse:
    no_store(response)
    _authorize(context)
    try:
        user = service.update_user(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            actor_role=context.user.role,
            user_id=user_id,
            changes=payload.changes(),
        )
    except Exception as error:
        _raise_domain(error)
    return _response(user)


@router.post("/{user_id}/reset-password", response_model=ManagedUserResponse)
def reset_password(
    user_id: UUID,
    payload: PasswordResetRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    service: Annotated[UserAdministrationService, Depends(get_service)],
) -> ManagedUserResponse:
    no_store(response)
    _authorize(context)
    try:
        user = service.reset_password(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            actor_role=context.user.role,
            user_id=user_id,
            password=payload.password.get_secret_value(),
        )
    except Exception as error:
        _raise_domain(error)
    return _response(user)
