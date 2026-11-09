"""Administrator account actions inside one tenant transaction (P78 / 08-20 contract).

Rules: only an administrator creates accounts; nobody changes their own administrator
role or deactivates themselves; the tenant keeps at least one active administrator;
deactivation and password reset revoke every session at once; links are single-use
and valid for 72 hours. The database repeats the self-rules as restrictive policies.

All actions of one tenant run under one advisory lock and re-check the actor after
taking it, so two administrators deactivating each other cannot both succeed.
"""

import secrets
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, literal_column, or_, select, text, update
from sqlalchemy.exc import IntegrityError

from pdos_next.core.clock import now
from pdos_next.core.models import (
    AccountEvent,
    AccountInvitation,
    HumanCredential,
    LoginSession,
    Principal,
)
from pdos_next.core.service import digest
from pdos_next.errors import DomainError

from . import passwords

INVITATION_LIFETIME = timedelta(hours=72)


def _administrators():
    from pdos_next.agent.kernel.models import TenantAdministrator

    return TenantAdministrator


def is_administrator(s) -> bool:
    return bool(s.scalar(text("SELECT public.account_administrator()")))


def require_administrator(s, ctx, *, lock=False):
    if lock:
        s.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"accounts:{ctx.tenant_id}"},
        )
    if (
        ctx.run_id
        or ctx.agent_run_id
        or ctx.actor_id != ctx.requester_id
        or not is_administrator(s)
    ):
        raise DomainError("ADMINISTRATOR_REQUIRED", "账户管理须由租户管理员本人办理。", 403)


def _person(s, ctx, principal_id: UUID, *, lock=False) -> Principal:
    query = select(Principal).where(
        Principal.tenant_id == ctx.tenant_id,
        Principal.id == principal_id,
        Principal.kind == "human",
    )
    person = s.scalar(query.with_for_update() if lock else query)
    if person is None:
        raise DomainError("ACCOUNT_NOT_FOUND", "此账户不在当前租户。", 404)
    return person


def _credential(s, ctx, principal_id: UUID):
    return s.execute(
        select(HumanCredential.login_name, HumanCredential.password_changed_at).where(
            HumanCredential.tenant_id == ctx.tenant_id,
            HumanCredential.principal_id == principal_id,
        )
    ).one_or_none()


def _event(s, ctx, subject: UUID, kind: str, **detail):
    s.add(
        AccountEvent(
            tenant_id=ctx.tenant_id,
            subject_id=subject,
            actor_id=ctx.actor_id,
            kind=kind,
            detail=detail,
        )
    )


def _revoke_sessions(s, ctx, principal_id: UUID) -> int:
    return s.execute(
        update(LoginSession)
        .where(
            LoginSession.tenant_id == ctx.tenant_id,
            LoginSession.principal_id == principal_id,
            LoginSession.revoked.is_(False),
        )
        .values(revoked=True)
        .execution_options(synchronize_session=False)
    ).rowcount


def _revoke_invitations(s, ctx, principal_id: UUID, instant) -> int:
    return s.execute(
        update(AccountInvitation)
        .where(
            AccountInvitation.tenant_id == ctx.tenant_id,
            AccountInvitation.principal_id == principal_id,
            AccountInvitation.used_at.is_(None),
            AccountInvitation.revoked_at.is_(None),
        )
        .values(revoked_at=instant)
        .execution_options(synchronize_session=False)
    ).rowcount


def _issue(s, ctx, principal_id: UUID, purpose: str) -> dict:
    """A new one-time link replaces any earlier unused one."""
    instant = now()
    _revoke_invitations(s, ctx, principal_id, instant)
    token = secrets.token_urlsafe(32)
    s.add(
        AccountInvitation(
            tenant_id=ctx.tenant_id,
            principal_id=principal_id,
            purpose=purpose,
            token_hash=digest(token),
            created_at=instant,
            expires_at=instant + INVITATION_LIFETIME,
            created_by=ctx.actor_id,
        )
    )
    s.flush()
    return {
        "token": token,
        "purpose": purpose,
        "expires_at": (instant + INVITATION_LIFETIME).isoformat(),
    }


def _remaining_administrators(s, ctx, without: UUID) -> int:
    TenantAdministrator = _administrators()
    return s.scalar(
        select(func.count())
        .select_from(TenantAdministrator)
        .join(
            Principal,
            (Principal.tenant_id == TenantAdministrator.tenant_id)
            & (Principal.id == TenantAdministrator.principal_id),
        )
        .where(
            TenantAdministrator.tenant_id == ctx.tenant_id,
            TenantAdministrator.active.is_(True),
            TenantAdministrator.principal_id != without,
            Principal.active.is_(True),
            Principal.kind == "human",
        )
    )


def _not_self(ctx, principal_id: UUID, message: str):
    if principal_id == ctx.actor_id:
        raise DomainError("ACCOUNT_SELF_CHANGE", message, 403)


def listing(s, ctx, only: UUID | None = None) -> list[dict]:
    require_administrator(s, ctx)
    TenantAdministrator = _administrators()
    instant = now()
    people = select(Principal.id, Principal.name, Principal.active, Principal.created_at).where(
        Principal.tenant_id == ctx.tenant_id, Principal.kind == "human"
    )
    if only is not None:
        people = people.where(Principal.id == only)
    rows = s.execute(people.order_by(Principal.created_at, Principal.id)).all()
    ids = [row.id for row in rows]
    credentials = {
        row.principal_id: row
        for row in s.execute(
            select(
                HumanCredential.principal_id,
                HumanCredential.login_name,
                HumanCredential.password_changed_at,
            ).where(
                HumanCredential.tenant_id == ctx.tenant_id, HumanCredential.principal_id.in_(ids)
            )
        )
    }
    administrators = set(
        s.scalars(
            select(TenantAdministrator.principal_id).where(
                TenantAdministrator.tenant_id == ctx.tenant_id,
                TenantAdministrator.active.is_(True),
                TenantAdministrator.principal_id.in_(ids),
            )
        )
    )
    pending = {
        row.principal_id: row
        for row in s.execute(
            select(
                AccountInvitation.principal_id,
                AccountInvitation.purpose,
                AccountInvitation.expires_at,
            ).where(
                AccountInvitation.tenant_id == ctx.tenant_id,
                AccountInvitation.principal_id.in_(ids),
                AccountInvitation.used_at.is_(None),
                AccountInvitation.revoked_at.is_(None),
                AccountInvitation.expires_at > instant,
            )
        )
    }
    seen = func.coalesce(LoginSession.last_seen_at, LoginSession.issued_at)
    live = s.execute(
        select(LoginSession.principal_id, func.count())
        .where(
            LoginSession.tenant_id == ctx.tenant_id,
            LoginSession.principal_id.in_(ids),
            LoginSession.revoked.is_(False),
            LoginSession.expires_at > instant,
            or_(
                LoginSession.idle_timeout_seconds.is_(None),
                seen + LoginSession.idle_timeout_seconds * literal_column("interval '1 second'")
                > instant,
            ),
        )
        .group_by(LoginSession.principal_id)
    ).all()
    sessions = dict(live)
    last = dict(
        s.execute(
            select(LoginSession.principal_id, func.max(LoginSession.issued_at))
            .where(
                LoginSession.tenant_id == ctx.tenant_id,
                LoginSession.principal_id.in_(ids),
                LoginSession.origin == "password",
            )
            .group_by(LoginSession.principal_id)
        ).all()
    )
    items = []
    for row in rows:
        credential = credentials.get(row.id)
        invitation = pending.get(row.id)
        password_set = bool(credential and credential.password_changed_at)
        status = (
            "deactivated"
            if not row.active
            else "no_sign_in"
            if credential is None
            else "active"
            if password_set
            else "invited"
            if invitation
            else "link_expired"
        )
        items.append(
            {
                "principal_id": str(row.id),
                "name": row.name,
                "login_name": credential.login_name if credential else None,
                "status": status,
                "active": row.active,
                "administrator": row.id in administrators,
                "self": row.id == ctx.actor_id,
                "password_set": password_set,
                "pending_link": {
                    "purpose": invitation.purpose,
                    "expires_at": invitation.expires_at.isoformat(),
                }
                if invitation
                else None,
                "active_sessions": sessions.get(row.id, 0),
                "last_sign_in_at": last[row.id].isoformat() if row.id in last else None,
                "created_at": row.created_at.isoformat(),
            }
        )
    return items


def _view(s, ctx, principal_id: UUID) -> dict:
    return listing(s, ctx, only=principal_id)[0]


def create_account(s, ctx, display_name: str, login_name: str) -> dict:
    require_administrator(s, ctx, lock=True)
    name = passwords.login_name(login_name)
    person = uuid4()
    try:
        with s.begin_nested():
            s.add(Principal(id=person, tenant_id=ctx.tenant_id, name=display_name, kind="human"))
            s.flush()
            s.add(
                HumanCredential(
                    tenant_id=ctx.tenant_id,
                    principal_id=person,
                    login_name=name,
                    created_by=ctx.actor_id,
                )
            )
            s.flush()
    except IntegrityError as error:
        if getattr(error.orig, "sqlstate", None) == "23505":
            raise DomainError("LOGIN_NAME_TAKEN", "这个登录名已被使用，请换一个。", 409) from None
        raise
    _event(s, ctx, person, "account.create", login_name=name)
    link = _issue(s, ctx, person, "invite")
    _event(s, ctx, person, "invitation.issue", purpose="invite")
    s.flush()
    return {"account": _view(s, ctx, person), "link": link}


def reissue_invitation(s, ctx, principal_id: UUID) -> dict:
    require_administrator(s, ctx, lock=True)
    person = _person(s, ctx, principal_id, lock=True)
    credential = _credential(s, ctx, principal_id)
    if not person.active:
        raise DomainError("ACCOUNT_INACTIVE", "账户已停用，请先启用。", 409)
    if credential is None:
        raise DomainError("ACCOUNT_NOT_FOUND", "此成员没有登录账户。", 404)
    if credential.password_changed_at is not None:
        raise DomainError(
            "INVITATION_NOT_NEEDED", "此账户已设置密码；如需更换，请使用“重置密码”。", 409
        )
    link = _issue(s, ctx, principal_id, "invite")
    _event(s, ctx, principal_id, "invitation.issue", purpose="invite")
    s.flush()
    return {"account": _view(s, ctx, principal_id), "link": link}


def reset_password(s, ctx, principal_id: UUID) -> dict:
    require_administrator(s, ctx, lock=True)
    person = _person(s, ctx, principal_id, lock=True)
    if not person.active:
        raise DomainError("ACCOUNT_INACTIVE", "账户已停用，请先启用。", 409)
    if _credential(s, ctx, principal_id) is None:
        raise DomainError("ACCOUNT_NOT_FOUND", "此成员没有登录账户。", 404)
    # The old password stops working and every session ends at once (P78).
    s.execute(
        update(HumanCredential)
        .where(
            HumanCredential.tenant_id == ctx.tenant_id,
            HumanCredential.principal_id == principal_id,
        )
        .values(password_hash=None, password_changed_at=None)
        .execution_options(synchronize_session=False)
    )
    ended = _revoke_sessions(s, ctx, principal_id)
    link = _issue(s, ctx, principal_id, "reset")
    _event(s, ctx, principal_id, "password.reset", sessions_revoked=ended)
    s.flush()
    return {"account": _view(s, ctx, principal_id), "link": link, "sessions_revoked": ended}


def deactivate(s, ctx, principal_id: UUID) -> dict:
    require_administrator(s, ctx, lock=True)
    _not_self(ctx, principal_id, "不能停用自己的账户。")
    person = _person(s, ctx, principal_id, lock=True)
    ended = 0
    if person.active:
        TenantAdministrator = _administrators()
        administrator = s.scalar(
            select(TenantAdministrator.id).where(
                TenantAdministrator.tenant_id == ctx.tenant_id,
                TenantAdministrator.principal_id == principal_id,
                TenantAdministrator.active.is_(True),
            )
        )
        if administrator and not _remaining_administrators(s, ctx, principal_id):
            raise DomainError("LAST_ADMINISTRATOR", "租户至少要保留一位启用的管理员。", 409)
        person.active = False
        person.access_epoch += 1
        ended = _revoke_sessions(s, ctx, principal_id)
        _revoke_invitations(s, ctx, principal_id, now())
        _event(s, ctx, principal_id, "account.deactivate", sessions_revoked=ended)
        s.flush()
    return {"account": _view(s, ctx, principal_id), "sessions_revoked": ended}


def reactivate(s, ctx, principal_id: UUID) -> dict:
    require_administrator(s, ctx, lock=True)
    person = _person(s, ctx, principal_id, lock=True)
    if not person.active:
        person.active = True
        person.access_epoch += 1
        _event(s, ctx, principal_id, "account.reactivate")
        s.flush()
    return {"account": _view(s, ctx, principal_id)}


def revoke_sessions(s, ctx, principal_id: UUID) -> dict:
    """Force sign-out everywhere without deactivating the account."""
    require_administrator(s, ctx, lock=True)
    _person(s, ctx, principal_id, lock=True)
    ended = _revoke_sessions(s, ctx, principal_id)
    _event(s, ctx, principal_id, "sessions.revoke", sessions_revoked=ended)
    s.flush()
    return {"account": _view(s, ctx, principal_id), "sessions_revoked": ended}


def set_administrator(s, ctx, principal_id: UUID, value: bool) -> dict:
    require_administrator(s, ctx, lock=True)
    _not_self(ctx, principal_id, "不能更改自己的管理员身份。")
    person = _person(s, ctx, principal_id, lock=True)
    TenantAdministrator = _administrators()
    row = s.scalar(
        select(TenantAdministrator)
        .where(
            TenantAdministrator.tenant_id == ctx.tenant_id,
            TenantAdministrator.principal_id == principal_id,
        )
        .with_for_update()
    )
    current = bool(row and row.active)
    if value and not current:
        if not person.active:
            raise DomainError("ACCOUNT_INACTIVE", "账户已停用，请先启用。", 409)
        if row is None:
            s.add(TenantAdministrator(tenant_id=ctx.tenant_id, principal_id=principal_id))
        else:
            row.active = True
        _event(s, ctx, principal_id, "administrator.grant")
    elif not value and current:
        if not _remaining_administrators(s, ctx, principal_id):
            raise DomainError("LAST_ADMINISTRATOR", "租户至少要保留一位启用的管理员。", 409)
        row.active = False
        _event(s, ctx, principal_id, "administrator.revoke")
    s.flush()
    return {"account": _view(s, ctx, principal_id)}


def own_account(s, ctx) -> dict:
    """What the session endpoint adds about the signed-in person."""
    credential = _credential(s, ctx, ctx.actor_id)
    return {
        "login_name": credential.login_name if credential else None,
        "administrator": is_administrator(s),
    }
