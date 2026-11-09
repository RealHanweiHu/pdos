"""Human sign-in and account lifecycle boundaries (D214, D86, D192; P78 judgments)."""

import secrets
import threading
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.models import TenantAdministrator
from pdos_next.core.accounts import management
from pdos_next.core.accounts.passwords import hash_password
from pdos_next.core.database import tenant_session
from pdos_next.core.models import (
    AccountEvent,
    AccountInvitation,
    HumanCredential,
    LoginSession,
    Principal,
    now,
)
from pdos_next.core.service import Context, digest
from pdos_next.errors import DomainError


def secret():
    return "synthetic-" + secrets.token_urlsafe(12)


def login_name(prefix="member"):
    return f"{prefix}-{uuid4().hex[:12]}"


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def sign_in(setup, name, password, source=None):
    return setup.client.post(
        "/v1/auth/sign-in",
        json={"login_name": name, "password": password},
        headers={"X-PDOS-Client-Address": source or f"synthetic-{uuid4()}"},
    )


@pytest.fixture
def accounts(setup):
    """setup.human becomes the tenant's administrator with a password of its own."""
    name, password = login_name("owner"), secret()
    with Session(setup.admin) as s, s.begin():
        s.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human))
        s.add(
            HumanCredential(
                tenant_id=setup.tenant,
                principal_id=setup.human,
                login_name=name,
                password_hash=hash_password(password),
                password_changed_at=now(),
                created_by=setup.human,
            )
        )
    response = sign_in(setup, name, password)
    assert response.status_code == 200, response.text
    setup.owner_login, setup.owner_password = name, password
    setup.owner = bearer(response.json()["session_token"])
    return setup


def invite(setup, name=None, display="合成成员"):
    response = setup.client.post(
        "/v1/accounts",
        headers=setup.owner,
        json={"display_name": display, "login_name": name or login_name()},
    )
    assert response.status_code == 201, response.text
    return response.json()


def accept(setup, token, password):
    return setup.client.post(
        "/v1/auth/invitations/accept", json={"token": token, "password": password}
    )


def member(setup):
    """An invited member who accepted the link and holds one session."""
    created, password = invite(setup), secret()
    response = accept(setup, created["link"]["token"], password)
    assert response.status_code == 200, response.text
    account = created["account"]
    return account, password, bearer(response.json()["session_token"])


def reason(response):
    return response.json()["detail"]["reason"]


def test_sign_in_issues_an_idle_bounded_password_session(accounts):
    session = accounts.client.get("/v1/session", headers=accounts.owner)
    assert session.status_code == 200
    assert session.json()["administrator"] is True
    assert session.json()["login_name"] == accounts.owner_login
    token = accounts.owner["Authorization"][7:]
    with Session(accounts.admin) as s:
        row = s.get(LoginSession, digest(token))
        assert row.origin == "password" and row.idle_timeout_seconds == 12 * 3600
        assert timedelta(days=6, hours=23) < row.expires_at - row.issued_at <= timedelta(days=7)
    for name, password in (
        (accounts.owner_login, "wrong-" + secret()),
        ("nobody-" + uuid4().hex[:8], accounts.owner_password),
    ):
        rejected = sign_in(accounts, name, password)
        assert rejected.status_code == 401 and reason(rejected) == "SIGN_IN_REJECTED"
        assert rejected.json()["message"] == "登录名或密码不正确。"
    # A tool-issued session from conftest has no credential and no admin role.
    tool = accounts.client.get(
        "/v1/session", headers={"Authorization": accounts.headers["Authorization"]}
    )
    assert tool.status_code == 200 and tool.json()["login_name"] == accounts.owner_login


def test_failed_sign_ins_throttle_by_name_and_by_source(accounts):
    account, password, _ = member(accounts)
    name = account["login_name"]
    for _ in range(5):
        assert sign_in(accounts, name, "wrong-" + secret()).status_code == 401
    # Even the right password waits once the name has five failures in 15 minutes.
    throttled = sign_in(accounts, name, password)
    assert throttled.status_code == 429 and reason(throttled) == "SIGN_IN_THROTTLED"
    source = f"synthetic-{uuid4()}"
    for _ in range(30):
        sign_in(accounts, "nobody-" + uuid4().hex[:8], "wrong-" + secret(), source)
    blocked = sign_in(accounts, accounts.owner_login, accounts.owner_password, source)
    assert blocked.status_code == 429
    assert sign_in(accounts, accounts.owner_login, accounts.owner_password).status_code == 200
    with Session(accounts.admin) as s:
        stored = set(s.scalars(text("SELECT login_key FROM sign_in_attempts")))
        assert name not in stored and digest("login:" + name) in stored


def test_idle_timeout_absolute_expiry_and_sign_out(accounts):
    account, password, headers = member(accounts)
    token = headers["Authorization"][7:]
    with Session(accounts.admin) as s, s.begin():
        s.execute(
            update(LoginSession)
            .where(LoginSession.token_hash == digest(token))
            .values(issued_at=now() - timedelta(minutes=5))
        )
    assert accounts.client.get("/v1/session", headers=headers).status_code == 200
    with Session(accounts.admin) as s, s.begin():
        row = s.get(LoginSession, digest(token))
        assert row.last_seen_at is not None  # touched after more than a minute
        row.last_seen_at = now() - timedelta(hours=12, seconds=1)
    idle = accounts.client.get("/v1/session", headers=headers)
    assert idle.status_code == 401 and reason(idle) == "UNAUTHENTICATED"

    name = account["login_name"]
    second = bearer(sign_in(accounts, name, password).json()["session_token"])
    with Session(accounts.admin) as s, s.begin():
        s.get(LoginSession, digest(second["Authorization"][7:])).expires_at = now()
    assert accounts.client.get("/v1/session", headers=second).status_code == 401

    third = bearer(sign_in(accounts, name, password).json()["session_token"])
    fourth = bearer(sign_in(accounts, name, password).json()["session_token"])
    ended = accounts.client.post("/v1/auth/sign-out", headers=third)
    assert ended.json() == {"status": "signed_out"}
    assert accounts.client.get("/v1/session", headers=third).status_code == 401
    assert accounts.client.get("/v1/session", headers=fourth).status_code == 200
    again = accounts.client.post("/v1/auth/sign-out", headers=third)
    assert again.json() == {"status": "already_ended"}


def test_invitation_link_is_single_use_and_valid_for_72_hours(accounts):
    created = invite(accounts, display="受邀合成成员")
    token = created["link"]["token"]
    assert created["account"]["status"] == "invited"
    view = accounts.client.post("/v1/auth/invitations/inspect", json={"token": token})
    assert view.status_code == 200
    assert view.json()["display_name"] == "受邀合成成员"
    assert view.json()["purpose"] == "invite"
    short = accept(accounts, token, "short")
    assert short.status_code == 422 and reason(short) == "PASSWORD_POLICY"
    first = accept(accounts, token, secret())
    assert first.status_code == 200
    assert (
        accounts.client.get(
            "/v1/session", headers=bearer(first.json()["session_token"])
        ).status_code
        == 200
    )
    # P78: the second use of a link is refused.
    for response in (
        accept(accounts, token, secret()),
        accounts.client.post("/v1/auth/invitations/inspect", json={"token": token}),
    ):
        assert response.status_code == 409 and reason(response) == "INVITATION_USED"

    stale = invite(accounts)
    with Session(accounts.admin) as s, s.begin():
        s.execute(
            update(AccountInvitation)
            .where(AccountInvitation.token_hash == digest(stale["link"]["token"]))
            .values(
                created_at=AccountInvitation.created_at - timedelta(hours=73),
                expires_at=AccountInvitation.expires_at - timedelta(hours=73),
            )
        )
    expired = accept(accounts, stale["link"]["token"], secret())
    assert expired.status_code == 409 and reason(expired) == "INVITATION_EXPIRED"
    reissued = accounts.client.post(
        f"/v1/accounts/{stale['account']['principal_id']}/invitation", headers=accounts.owner
    )
    assert reissued.status_code == 200
    replaced = invite(accounts)
    newer = accounts.client.post(
        f"/v1/accounts/{replaced['account']['principal_id']}/invitation", headers=accounts.owner
    ).json()["link"]["token"]
    revoked = accept(accounts, replaced["link"]["token"], secret())
    assert revoked.status_code == 409 and reason(revoked) == "INVITATION_REVOKED"
    assert accept(accounts, newer, secret()).status_code == 200
    missing = accept(accounts, secrets.token_urlsafe(32), secret())
    assert missing.status_code == 404 and reason(missing) == "INVITATION_INVALID"
    # The database itself refuses a link that lives longer than 72 hours.
    with pytest.raises(IntegrityError), Session(accounts.admin) as s, s.begin():
        instant = now()
        s.add(
            AccountInvitation(
                tenant_id=accounts.tenant,
                principal_id=accounts.peer,
                purpose="invite",
                token_hash=digest(secrets.token_urlsafe(32)),
                created_at=instant,
                expires_at=instant + timedelta(hours=72, seconds=1),
                created_by=accounts.human,
            )
        )


def test_deactivation_revokes_every_session_and_open_links(accounts):
    account, password, headers = member(accounts)
    name = account["login_name"]
    other = bearer(sign_in(accounts, name, password).json()["session_token"])
    pending = invite(accounts)
    response = accounts.client.post(
        f"/v1/accounts/{account['principal_id']}/deactivate", headers=accounts.owner
    )
    assert response.status_code == 200, response.text
    assert response.json()["sessions_revoked"] == 2
    assert response.json()["account"]["status"] == "deactivated"
    for session in (headers, other):
        assert accounts.client.get("/v1/session", headers=session).status_code == 401
    assert reason(sign_in(accounts, name, password)) == "SIGN_IN_REJECTED"
    accounts.client.post(
        f"/v1/accounts/{pending['account']['principal_id']}/deactivate", headers=accounts.owner
    )
    closed = accept(accounts, pending["link"]["token"], secret())
    assert closed.status_code == 409 and reason(closed) in {
        "INVITATION_REVOKED",
        "INVITATION_INACTIVE",
    }
    with Session(accounts.admin) as s:
        sessions = s.scalars(
            select(LoginSession.revoked).where(LoginSession.principal_id == account["principal_id"])
        ).all()
        assert sessions and all(sessions)
        details = s.scalars(
            select(AccountEvent.detail).where(AccountEvent.tenant_id == accounts.tenant)
        ).all()
        assert password not in str(details) and pending["link"]["token"] not in str(details)
    restored = accounts.client.post(
        f"/v1/accounts/{account['principal_id']}/reactivate", headers=accounts.owner
    )
    assert restored.json()["account"]["active"] is True
    assert accounts.client.get("/v1/session", headers=headers).status_code == 401
    assert sign_in(accounts, name, password).status_code == 200


def test_password_reset_ends_old_sessions_and_old_password(accounts):
    account, password, headers = member(accounts)
    reset = accounts.client.post(
        f"/v1/accounts/{account['principal_id']}/password-reset", headers=accounts.owner
    )
    assert reset.status_code == 200 and reset.json()["sessions_revoked"] == 1
    assert reset.json()["link"]["purpose"] == "reset"
    assert accounts.client.get("/v1/session", headers=headers).status_code == 401
    assert reason(sign_in(accounts, account["login_name"], password)) == "SIGN_IN_REJECTED"
    renewed = secret()
    assert accept(accounts, reset.json()["link"]["token"], renewed).status_code == 200
    assert sign_in(accounts, account["login_name"], renewed).status_code == 200
    forced = accounts.client.post(
        f"/v1/accounts/{account['principal_id']}/sessions/revoke", headers=accounts.owner
    )
    assert forced.json()["sessions_revoked"] == 2


def test_self_changes_and_non_administrators_are_refused(accounts):
    for path, body in (
        ("deactivate", None),
        ("administrator", {"administrator": False}),
    ):
        response = accounts.client.post(
            f"/v1/accounts/{accounts.human}/{path}", headers=accounts.owner, json=body
        )
        assert response.status_code == 403 and reason(response) == "ACCOUNT_SELF_CHANGE"
    assert accounts.client.get("/v1/session", headers=accounts.owner).status_code == 200
    account, _, headers = member(accounts)
    for method, path, body in (
        ("get", "/v1/accounts", None),
        ("post", "/v1/accounts", {"display_name": "x", "login_name": login_name()}),
        ("post", f"/v1/accounts/{account['principal_id']}/administrator", {"administrator": True}),
        ("post", f"/v1/accounts/{accounts.human}/deactivate", None),
    ):
        call = getattr(accounts.client, method)
        response = (
            call(path, headers=headers) if body is None else call(path, headers=headers, json=body)
        )
        assert response.status_code == 403 and reason(response) == "ADMINISTRATOR_REQUIRED"
    taken = accounts.client.post(
        "/v1/accounts",
        headers=accounts.owner,
        json={"display_name": "重名", "login_name": account["login_name"]},
    )
    assert taken.status_code == 409 and reason(taken) == "LOGIN_NAME_TAKEN"
    invalid = accounts.client.post(
        "/v1/accounts", headers=accounts.owner, json={"display_name": "x", "login_name": "A b"}
    )
    assert invalid.status_code == 422 and reason(invalid) == "LOGIN_NAME_INVALID"
    foreign = accounts.client.post(
        f"/v1/accounts/{accounts.other_human}/deactivate", headers=accounts.owner
    )
    assert foreign.status_code == 404 and reason(foreign) == "ACCOUNT_NOT_FOUND"


def scoped(setup, actor):
    return tenant_session(setup.engine, setup.tenant, actor_id=actor, requester_id=actor)


def violates_policy(action):
    with pytest.raises(DBAPIError) as error:
        action()
    assert getattr(error.value.orig, "sqlstate", None) == "42501"


def test_database_refuses_self_elevation_self_deactivation_and_secret_reads(accounts):
    account, _, _ = member(accounts)
    person = account["principal_id"]

    def elevate_self():
        with scoped(accounts, person) as s:
            s.add(TenantAdministrator(tenant_id=accounts.tenant, principal_id=person))
            s.flush()

    def administrator_elevates_self_again():
        with scoped(accounts, accounts.human) as s:
            s.execute(
                update(TenantAdministrator)
                .where(TenantAdministrator.principal_id == accounts.human)
                .values(active=True)
            )

    def deactivate_self():
        with scoped(accounts, accounts.human) as s:
            s.execute(update(Principal).where(Principal.id == accounts.human).values(active=False))

    def set_password():
        with scoped(accounts, accounts.human) as s:
            s.execute(
                update(HumanCredential)
                .where(HumanCredential.principal_id == person)
                .values(password_hash=hash_password(secret()), password_changed_at=now())
            )

    def read_hash():
        with scoped(accounts, accounts.human) as s:
            s.execute(select(HumanCredential.password_hash)).all()

    def read_token_hash():
        with scoped(accounts, accounts.human) as s:
            s.execute(select(AccountInvitation.token_hash)).all()

    for action in (
        elevate_self,
        administrator_elevates_self_again,
        deactivate_self,
        set_password,
        read_hash,
        read_token_hash,
    ):
        violates_policy(action)
    with accounts.auth.connect() as connection:
        for table in ("human_credentials", "account_invitations", "sign_in_attempts"):
            with pytest.raises(DBAPIError) as error:
                connection.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))
            assert error.value.orig.sqlstate == "42501"
            connection.rollback()


def test_two_administrators_cannot_deactivate_each_other(accounts):
    account, _, _ = member(accounts)
    second = account["principal_id"]
    granted = accounts.client.post(
        f"/v1/accounts/{second}/administrator", headers=accounts.owner, json={"administrator": True}
    )
    assert granted.json()["account"]["administrator"] is True
    barrier, outcomes = threading.Barrier(2), []

    def deactivate(actor, target):
        barrier.wait()
        try:
            with scoped(accounts, actor) as s:
                management.deactivate(s, Context(accounts.tenant, actor, actor), target)
            outcomes.append("ok")
        except DomainError as error:
            outcomes.append(error.reason)

    threads = [
        threading.Thread(target=deactivate, args=(accounts.human, second)),
        threading.Thread(target=deactivate, args=(second, accounts.human)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["ADMINISTRATOR_REQUIRED", "ok"]
    with Session(accounts.admin) as s:
        remaining = s.scalar(
            select(text("count(*)"))
            .select_from(TenantAdministrator)
            .join(Principal, Principal.id == TenantAdministrator.principal_id)
            .where(
                TenantAdministrator.tenant_id == accounts.tenant,
                TenantAdministrator.active.is_(True),
                Principal.active.is_(True),
            )
        )
        assert remaining == 1


def test_last_administrator_is_kept_even_without_the_self_rule(accounts, monkeypatch):
    ctx = Context(accounts.tenant, accounts.human, accounts.human)
    with scoped(accounts, accounts.human) as s:
        assert management._remaining_administrators(s, ctx, accounts.human) == 0
    # The self-rule normally answers first; the count is the independent guard.
    monkeypatch.setattr(management, "_not_self", lambda *args: None)
    for action in (
        lambda s: management.deactivate(s, ctx, accounts.human),
        lambda s: management.set_administrator(s, ctx, accounts.human, False),
    ):
        with pytest.raises(DomainError) as error, scoped(accounts, accounts.human) as s:
            action(s)
        assert error.value.reason == "LAST_ADMINISTRATOR"
    session = accounts.client.get("/v1/session", headers=accounts.owner)
    assert session.status_code == 200 and session.json()["administrator"] is True


def test_a_reset_between_password_check_and_issue_wins(accounts):
    account, password, _ = member(accounts)
    name, source = account["login_name"], digest("source:race")
    with accounts.auth.begin() as connection:
        found = (
            connection.execute(
                text("SELECT * FROM auth_sign_in_lookup(:n, :l, :s)"),
                {"n": name, "l": digest("login:" + name), "s": source},
            )
            .mappings()
            .one()
        )
    assert found["found_hash"] and not found["throttled"]
    reset = accounts.client.post(
        f"/v1/accounts/{account['principal_id']}/password-reset", headers=accounts.owner
    )
    assert reset.status_code == 200
    with accounts.auth.begin() as connection:
        issued = connection.execute(
            text("SELECT * FROM auth_sign_in_issue(:l, :s, :t, :p, :h, :th)"),
            {
                "l": digest("login:" + name),
                "s": source,
                "t": found["found_tenant"],
                "p": found["found_principal"],
                "h": found["found_hash"],
                "th": digest(secrets.token_urlsafe(32)),
            },
        ).all()
    assert issued == []
    assert reason(sign_in(accounts, name, password)) == "SIGN_IN_REJECTED"
