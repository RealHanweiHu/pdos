"""HTTP boundary for setup, login, and tenant-bound identity."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import Engine

from app.auth.errors import (
    InvalidAccessTokenError,
    InvalidCredentialsError,
    SetupAlreadyCompletedError,
    TenantContextDeniedError,
)
from app.auth.passwords import PasswordService
from app.auth.repository import AuthContext, AuthRepository
from app.auth.service import AuthService
from app.auth.tokens import TokenCodec
from app.db.engine import get_engine
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api", tags=["authentication"])
bearer = HTTPBearer(auto_error=False)


class SetupStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    needs_setup: bool


class SetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_slug: str = Field(
        min_length=2, max_length=64, pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$"
    )
    tenant_name: str = Field(min_length=1, max_length=256)
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9_.-]+$")
    password: SecretStr = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=256)

    @field_validator("tenant_slug", "username", mode="before")
    @classmethod
    def normalize_identifier(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("tenant_name", "display_name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_slug: str = Field(
        min_length=2, max_length=64, pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$"
    )
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9_.-]+$")
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("tenant_slug", "username", mode="before")
    @classmethod
    def normalize_identifier(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class PublicTenant(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    slug: str
    name: str


class PublicUser(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    username: str
    display_name: str
    email: str | None
    is_active: bool


class IdentityResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant: PublicTenant
    user: PublicUser


class TokenResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


def get_auth_service(
    settings: Annotated[Settings, Depends(get_settings)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> AuthService:
    return AuthService(
        repository=AuthRepository(engine),
        passwords=PasswordService(),
        tokens=TokenCodec(settings),
        settings=settings,
    )


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def unauthorized(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": code, "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def public_identity(context: AuthContext) -> IdentityResponse:
    return IdentityResponse(
        tenant=PublicTenant(
            id=context.tenant.id,
            slug=context.tenant.slug,
            name=context.tenant.name,
        ),
        user=PublicUser(
            id=context.user.id,
            tenant_id=context.user.tenant_id,
            username=context.user.username,
            display_name=context.user.display_name,
            email=context.user.email,
            is_active=context.user.is_active,
        ),
    )


def current_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized("INVALID_ACCESS_TOKEN", "A valid access token is required")
    if len(credentials.credentials) > 4096:
        raise unauthorized("INVALID_ACCESS_TOKEN", "A valid access token is required")
    try:
        return service.resolve_context(credentials.credentials)
    except InvalidAccessTokenError as error:
        raise unauthorized("INVALID_ACCESS_TOKEN", "A valid access token is required") from error
    except TenantContextDeniedError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "TENANT_CONTEXT_DENIED",
                "message": "No active tenant context is available",
            },
        ) from error


@router.get("/setup/status", response_model=SetupStatusResponse)
def setup_status(
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> SetupStatusResponse:
    no_store(response)
    return SetupStatusResponse(needs_setup=service.needs_setup())


@router.post("/setup", response_model=IdentityResponse, status_code=status.HTTP_201_CREATED)
def setup(
    payload: SetupRequest,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> IdentityResponse:
    no_store(response)
    try:
        context = service.setup(
            tenant_slug=payload.tenant_slug,
            tenant_name=payload.tenant_name,
            username=payload.username,
            password=payload.password.get_secret_value(),
            display_name=payload.display_name,
        )
    except SetupAlreadyCompletedError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "SETUP_ALREADY_COMPLETED",
                "message": "System setup has already been completed",
            },
        ) from error
    return public_identity(context)


@router.post("/auth/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    no_store(response)
    try:
        grant = service.login(
            tenant_slug=payload.tenant_slug,
            username=payload.username,
            password=payload.password.get_secret_value(),
        )
    except InvalidCredentialsError as error:
        raise unauthorized("INVALID_CREDENTIALS", "Invalid username or password") from error
    return TokenResponse(access_token=grant.access_token, expires_in=grant.expires_in)


@router.get("/auth/me", response_model=IdentityResponse)
def me(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
) -> IdentityResponse:
    no_store(response)
    return public_identity(context)
