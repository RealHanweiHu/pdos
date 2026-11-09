"""Password hashing with the standard library's scrypt; no extra dependency."""

import base64
import hashlib
import hmac
import re
import secrets

from pdos_next.errors import DomainError

# 2**15 x 8 x 1 needs 32 MiB per hash; about 0.1 s on a laptop.
N, R, P, LENGTH = 2**15, 8, 1, 32
MAX_MEMORY = 64 * 1024 * 1024
MIN_LENGTH, MAX_LENGTH = 10, 128
LOGIN_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode(), salt=salt, n=n, r=r, p=p, maxmem=MAX_MEMORY, dklen=LENGTH
    )


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(_derive(password, salt, N, R, P))}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant work whether or not an account exists, so timing reveals nothing."""
    try:
        _, n, r, p, salt, expected = (stored or DUMMY).split("$")
        actual = _derive(password, _unb64(salt), int(n), int(r), int(p))
        return stored is not None and hmac.compare_digest(actual, _unb64(expected))
    except (ValueError, TypeError):
        return False


DUMMY = hash_password(secrets.token_urlsafe(24))


def login_name(value: str) -> str:
    name = value.strip().lower()
    if not LOGIN_NAME.fullmatch(name):
        raise DomainError(
            "LOGIN_NAME_INVALID",
            "登录名为 3–64 位小写字母、数字或 . _ -，以字母或数字开头。",
            422,
        )
    return name


def check_password(password: str, name: str | None = None) -> str:
    if not MIN_LENGTH <= len(password) <= MAX_LENGTH:
        raise DomainError(
            "PASSWORD_POLICY", f"密码长度须为 {MIN_LENGTH}–{MAX_LENGTH} 个字符。", 422
        )
    if not password.strip() or (name and password.strip().lower() == name):
        raise DomainError("PASSWORD_POLICY", "密码不能为空白或与登录名相同。", 422)
    return password
