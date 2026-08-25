"""Strict JWT issuance and validation for PDOS access tokens."""

from __future__ import annotations

import base64
import binascii
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


def _has_canonical_base64url_segments(token: str) -> bool:
    segments = token.split(".")
    if len(segments) != 3 or any(not segment for segment in segments):
        return False
    for segment in segments:
        try:
            padded = f"{segment}{'=' * (-len(segment) % 4)}"
            decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
            canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
        except (UnicodeEncodeError, UnicodeDecodeError, binascii.Error, ValueError):
            return False
        if not hmac.compare_digest(segment, canonical):
            return False
    return True


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: UUID
    tenant_id: UUID
    token_id: UUID
    auth_version: int
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
        auth_version: int = 1,
        issued_at: datetime | None = None,
    ) -> EncodedAccessToken:
        if auth_version < 1:
            raise ValueError("auth version must be positive")
        now = (issued_at or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
        expires_at = now + self._ttl
        payload = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": f"user:{user_id}",
            "tid": f"tenant:{tenant_id}",
            "typ": "access",
            "jti": str(uuid4()),
            "ver": auth_version,
            "iat": now,
            "nbf": now,
            "exp": expires_at,
        }
        encoded = jwt.encode(payload, self._signing_key, algorithm=ALGORITHM)
        return EncodedAccessToken(token=encoded, issued_at=now, expires_at=expires_at)

    def decode(self, token: str) -> AccessTokenClaims:
        if not _has_canonical_base64url_segments(token):
            raise InvalidAccessTokenError
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                self._signing_key,
                algorithms=[ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                leeway=5,
                options={
                    "require": [
                        "iss",
                        "aud",
                        "sub",
                        "tid",
                        "typ",
                        "jti",
                        "ver",
                        "iat",
                        "nbf",
                        "exp",
                    ]
                },
            )
            if payload["typ"] != "access":
                raise InvalidAccessTokenError
            subject = str(payload["sub"])
            tenant = str(payload["tid"])
            if not subject.startswith("user:") or not tenant.startswith("tenant:"):
                raise InvalidAccessTokenError
            auth_version = payload["ver"]
            if (
                not isinstance(auth_version, int)
                or isinstance(auth_version, bool)
                or auth_version < 1
            ):
                raise InvalidAccessTokenError
            return AccessTokenClaims(
                user_id=UUID(subject.removeprefix("user:")),
                tenant_id=UUID(tenant.removeprefix("tenant:")),
                token_id=UUID(str(payload["jti"])),
                auth_version=auth_version,
                expires_at=datetime.fromtimestamp(float(payload["exp"]), UTC),
            )
        except (InvalidTokenError, KeyError, TypeError, ValueError) as error:
            raise InvalidAccessTokenError from error
