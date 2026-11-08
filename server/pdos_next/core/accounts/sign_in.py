"""Steps before a tenant is known, on the auth role only (database functions of s0_0855).

The lifetime, idle timeout and throttle limits are enforced inside those functions;
the constants here mirror them for messages and checks, and are never sent to the
database as policy.
"""

import re
import secrets
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from pdos_next.core.clock import now
from pdos_next.core.models import LoginSession
from pdos_next.core.service import digest
from pdos_next.errors import DomainError

from . import passwords

SESSION_LIFETIME = timedelta(days=7)
IDLE_TIMEOUT = timedelta(hours=12)
THROTTLE_MINUTES = 15
TOUCH_AFTER = timedelta(seconds=60)
TOKEN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


def _keys(name: str, source: str | None) -> tuple[str, str]:
    # Typed values are hashed before storage, so a password typed into the name
    # field never lands in the throttle ledger.
    return digest("login:" + name), digest("source:" + (source or "unknown"))


def _issued(token: str, row) -> dict:
    return {
        "session_token": token,
        "expires_at": row["session_expires"].isoformat(),
        "idle_timeout_seconds": row["session_idle"],
    }


def sign_in(auth_engine, login_name: str, password: str, source: str | None) -> dict:
    name = login_name.strip().lower()
    login_key, source_key = _keys(name, source)
    with auth_engine.begin() as connection:
        found = (
            connection.execute(
                text("SELECT * FROM auth_sign_in_lookup(:login, :login_key, :source_key)"),
                {"login": name, "login_key": login_key, "source_key": source_key},
            )
            .mappings()
            .one()
        )
    if found["throttled"]:
        raise DomainError(
            "SIGN_IN_THROTTLED", f"尝试次数过多，请 {THROTTLE_MINUTES} 分钟后再试。", 429
        )
    # An unknown name still pays for one scrypt, so timing does not reveal accounts.
    verified = passwords.verify_password(password, found["found_hash"])
    token = secrets.token_urlsafe(32)
    with auth_engine.begin() as connection:
        if verified:
            issued = (
                connection.execute(
                    text(
                        "SELECT * FROM auth_sign_in_issue(:login_key, :source_key, :tenant, "
                        ":principal, :hash, :token_hash)"
                    ),
                    {
                        "login_key": login_key,
                        "source_key": source_key,
                        "tenant": found["found_tenant"],
                        "principal": found["found_principal"],
                        "hash": found["found_hash"],
                        "token_hash": digest(token),
                    },
                )
                .mappings()
                .one_or_none()
            )
        else:
            connection.execute(
                text("SELECT auth_sign_in_failed(:login_key, :source_key)"),
                {"login_key": login_key, "source_key": source_key},
            )
            issued = None
    if issued is None:
        raise DomainError("SIGN_IN_REJECTED", "登录名或密码不正确。", 401)
    return _issued(token, issued)


def resolve(auth_engine, token: str) -> LoginSession | None:
    """The current session for a bearer token, or None when ended, expired or idle."""
    token_hash = digest(token)
    with Session(auth_engine) as session:
        login = session.get(LoginSession, token_hash)
        if login is not None:
            session.expunge(login)
    instant = now()
    if not login or login.revoked or login.expires_at <= instant:
        return None
    if login.idle_timeout_seconds is not None:
        seen = login.last_seen_at or login.issued_at
        if seen + timedelta(seconds=login.idle_timeout_seconds) <= instant:
            return None
        if seen < instant - TOUCH_AFTER:
            with auth_engine.begin() as connection:
                connection.execute(text("SELECT auth_session_touch(:h)"), {"h": token_hash})
    return login


def end_session(auth_engine, token: str) -> bool:
    with auth_engine.begin() as connection:
        return bool(connection.scalar(text("SELECT auth_session_end(:h)"), {"h": digest(token)}))


def _token(value: str) -> str:
    if not TOKEN.fullmatch(value or ""):
        raise DomainError("INVITATION_INVALID", "邀请链接无效，请向管理员索取新的链接。", 404)
    return value


STATES = {
    "missing": ("INVITATION_INVALID", "邀请链接无效，请向管理员索取新的链接。", 404),
    "used": ("INVITATION_USED", "此链接已经用过。如需重新设置密码，请联系管理员。", 409),
    "expired": ("INVITATION_EXPIRED", "此链接已过期（72 小时有效），请联系管理员重新发送。", 409),
    "revoked": ("INVITATION_REVOKED", "此链接已被更新的链接取代，请使用最新收到的链接。", 409),
    "inactive": ("INVITATION_INACTIVE", "此账户已停用，请联系管理员。", 409),
}


def inspect_invitation(auth_engine, token: str) -> dict:
    with auth_engine.begin() as connection:
        row = (
            connection.execute(
                text("SELECT * FROM auth_invitation_view(:h)"), {"h": digest(_token(token))}
            )
            .mappings()
            .one_or_none()
        )
    state = row["invitation_state"] if row else "missing"
    if state != "valid":
        raise DomainError(*STATES[state])
    return {
        "purpose": row["invitation_purpose"],
        "display_name": row["person_name"],
        "login_name": row["person_login"],
        "expires_at": row["invitation_expires"].isoformat(),
    }


def accept_invitation(auth_engine, token: str, password: str) -> dict:
    view = inspect_invitation(auth_engine, token)
    password_hash = passwords.hash_password(passwords.check_password(password, view["login_name"]))
    session_token = secrets.token_urlsafe(32)
    with auth_engine.begin() as connection:
        row = (
            connection.execute(
                text("SELECT * FROM auth_invitation_accept(:h, :password_hash, :session_hash)"),
                {
                    "h": digest(token),
                    "password_hash": password_hash,
                    "session_hash": digest(session_token),
                },
            )
            .mappings()
            .one()
        )
    if row["invitation_state"] != "accepted":
        raise DomainError(*STATES[row["invitation_state"]])
    return _issued(session_token, row)
