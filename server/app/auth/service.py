"""Authentication use cases independent from HTTP transport."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.auth.errors import (
    InvalidAccessTokenError,
    InvalidCredentialsError,
    InvalidCurrentPasswordError,
    LocalPasswordUnavailableError,
    PasswordReuseError,
    TenantContextDeniedError,
)
from app.auth.passwords import PasswordService
from app.auth.repository import AuthContext, AuthRepository
from app.auth.tokens import TokenCodec
from app.settings import Settings


@dataclass(frozen=True)
class TokenGrant:
    access_token: str
    expires_in: int


class AuthService:
    def __init__(
        self,
        *,
        repository: AuthRepository,
        passwords: PasswordService,
        tokens: TokenCodec,
        settings: Settings,
    ) -> None:
        self._repository = repository
        self._passwords = passwords
        self._tokens = tokens
        self._token_ttl_seconds = settings.jwt_access_token_minutes * 60

    def needs_setup(self) -> bool:
        return self._repository.needs_setup()

    def setup(
        self,
        *,
        tenant_slug: str,
        tenant_name: str,
        username: str,
        password: str,
        display_name: str,
    ) -> AuthContext:
        password_hash = self._passwords.hash(password)
        return self._repository.create_initial_context(
            tenant_slug=tenant_slug,
            tenant_name=tenant_name,
            username=username,
            display_name=display_name,
            password_hash=password_hash,
        )

    def login(self, *, tenant_slug: str, username: str, password: str) -> TokenGrant:
        context = self._repository.find_login_context(
            tenant_slug=tenant_slug,
            username=username,
        )
        password_matches = self._passwords.verify(
            password,
            context.user.password_hash if context is not None else None,
        )
        if context is None or not password_matches:
            raise InvalidCredentialsError

        signed_in_at = datetime.now(UTC)
        self._repository.record_successful_login(
            tenant_id=context.tenant.id,
            user_id=context.user.id,
            signed_in_at=signed_in_at,
        )
        encoded = self._tokens.issue(
            user_id=context.user.id,
            tenant_id=context.tenant.id,
            auth_version=context.user.auth_version,
            issued_at=signed_in_at,
        )
        return TokenGrant(
            access_token=encoded.token,
            expires_in=self._token_ttl_seconds,
        )

    def resolve_context(self, token: str) -> AuthContext:
        claims = self._tokens.decode(token)
        context = self._repository.find_user_context(claims.user_id)
        if context is None or not context.user.is_active:
            raise InvalidAccessTokenError
        if context.user.tenant_id != claims.tenant_id or context.tenant.id != claims.tenant_id:
            raise TenantContextDeniedError
        if context.user.auth_version != claims.auth_version:
            raise InvalidAccessTokenError
        if context.tenant.status != "active":
            raise TenantContextDeniedError
        return context

    def change_password(
        self,
        *,
        context: AuthContext,
        current_password: str,
        new_password: str,
    ) -> None:
        if context.user.password_hash is None:
            raise LocalPasswordUnavailableError
        if not self._passwords.verify(current_password, context.user.password_hash):
            raise InvalidCurrentPasswordError
        if self._passwords.verify(new_password, context.user.password_hash):
            raise PasswordReuseError
        try:
            self._repository.change_password(
                tenant_id=context.tenant.id,
                user_id=context.user.id,
                expected_auth_version=context.user.auth_version,
                password_hash=self._passwords.hash(new_password),
                changed_at=datetime.now(UTC),
            )
        except InvalidCredentialsError as error:
            raise InvalidAccessTokenError from error

    def issue_external_login(
        self, context: AuthContext, *, authentication_method: str
    ) -> TokenGrant:
        if not context.user.is_active or context.tenant.status != "active":
            raise InvalidCredentialsError
        signed_in_at = datetime.now(UTC)
        self._repository.record_successful_login(
            tenant_id=context.tenant.id,
            user_id=context.user.id,
            signed_in_at=signed_in_at,
            authentication_method=authentication_method,
        )
        encoded = self._tokens.issue(
            user_id=context.user.id,
            tenant_id=context.tenant.id,
            auth_version=context.user.auth_version,
            issued_at=signed_in_at,
        )
        return TokenGrant(access_token=encoded.token, expires_in=self._token_ttl_seconds)
