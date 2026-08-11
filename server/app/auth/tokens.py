"""Strict JWT issuance and validation for PDOS access tokens."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
from jwt.exceptions import InvalidTokenError

from app.auth.errors import InvalidAccessTokenError
from app.settings import Settings

ALGORITHM = "HS256"
KEY_CONTEXT = b"pdos/access-token/v1"


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: UUID
    tenant_id: UUID
    token_id: UUID
    expires_at: datetime


@dataclass(frozen=True)
class EncodedAccessToken:
    token: str
    issued_at: datetime
    expires_at: datetime


class TokenCodec:
    def __init__(self, settings: Settings) -> None:
        self._issuer = settings.jwt_issuer
        self._audience = settings.jwt_audience
        self._ttl = timedelta(minutes=settings.jwt_access_token_minutes)
        root_secret = settings.jwt_secret.get_secret_value().encode("utf-8")
        self._signing_key = hmac.new(root_secret, KEY_CONTEXT, hashlib.sha256).digest()

    def issue(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        issued_at: datetime | None = None,
    ) -> EncodedAccessToken:
        now = (issued_at or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
        expires_at = now + self._ttl
        payload = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": f"user:{user_id}",
            "tid": f"tenant:{tenant_id}",
            "typ": "access",
            "jti": str(uuid4()),
            "iat": now,
            "nbf": now,
            "exp": expires_at,
        }
        encoded = jwt.encode(payload, self._signing_key, algorithm=ALGORITHM)
        return EncodedAccessToken(token=encoded, issued_at=now, expires_at=expires_at)

    def decode(self, token: str) -> AccessTokenClaims:
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                self._signing_key,
                algorithms=[ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                leeway=5,
                options={
                    "require": ["iss", "aud", "sub", "tid", "typ", "jti", "iat", "nbf", "exp"]
                },
            )
            if payload["typ"] != "access":
                raise InvalidAccessTokenError
            subject = str(payload["sub"])
            tenant = str(payload["tid"])
            if not subject.startswith("user:") or not tenant.startswith("tenant:"):
                raise InvalidAccessTokenError
            return AccessTokenClaims(
                user_id=UUID(subject.removeprefix("user:")),
                tenant_id=UUID(tenant.removeprefix("tenant:")),
                token_id=UUID(str(payload["jti"])),
                expires_at=datetime.fromtimestamp(float(payload["exp"]), UTC),
            )
        except (InvalidTokenError, KeyError, TypeError, ValueError) as error:
            raise InvalidAccessTokenError from error
