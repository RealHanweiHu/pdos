from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from app.auth.errors import InvalidAccessTokenError
from app.auth.passwords import PasswordService
from app.auth.tokens import TokenCodec
from app.settings import Settings

TEST_DATABASE_URL = "postgresql://pdos:pdos@localhost:55436/pdos_test"
TEST_JWT_SECRET = "test-only-jwt-secret-that-is-at-least-32-bytes"


def auth_settings(*, jwt_secret: SecretStr | None = None) -> Settings:
    return Settings(
        database_url=TEST_DATABASE_URL,
        jwt_secret=jwt_secret or SecretStr(TEST_JWT_SECRET),
        jwt_issuer="pdos-test",
        jwt_audience="pdos-test-client",
        jwt_access_token_minutes=30,
    )


def test_passwords_use_argon2id_and_verify_without_exposing_plaintext() -> None:
    service = PasswordService()

    password_hash = service.hash("correct horse battery staple")

    assert password_hash.startswith("$argon2id$")
    assert "correct horse battery staple" not in password_hash
    assert service.verify("correct horse battery staple", password_hash)
    assert not service.verify("wrong password", password_hash)


def test_auth_settings_reject_a_short_jwt_secret() -> None:
    with pytest.raises(ValidationError):
        auth_settings(jwt_secret=SecretStr("too-short"))


def test_access_token_round_trip_preserves_the_server_bound_scope() -> None:
    codec = TokenCodec(auth_settings())
    user_id = uuid4()
    tenant_id = uuid4()

    encoded = codec.issue(user_id=user_id, tenant_id=tenant_id)
    claims = codec.decode(encoded.token)

    assert claims.user_id == user_id
    assert claims.tenant_id == tenant_id
    assert claims.expires_at == encoded.expires_at


def test_expired_or_tampered_access_tokens_fail_closed() -> None:
    codec = TokenCodec(auth_settings())
    issued_in_the_past = datetime.now(UTC) - timedelta(hours=1)
    expired = codec.issue(
        user_id=uuid4(),
        tenant_id=uuid4(),
        issued_at=issued_in_the_past,
    )

    with pytest.raises(InvalidAccessTokenError):
        codec.decode(expired.token)

    valid = codec.issue(user_id=uuid4(), tenant_id=uuid4())
    replacement = "a" if valid.token[-1] != "a" else "b"
    tampered = f"{valid.token[:-1]}{replacement}"
    with pytest.raises(InvalidAccessTokenError):
        codec.decode(tampered)
