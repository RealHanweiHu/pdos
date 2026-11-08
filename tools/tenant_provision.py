"""Open a tenant for human sign-in: first administrator, first category, invitation link.

D214. The administrator gets a 72-hour single-use link to set their own password; after
that, every further account is created by an administrator in Settings → 账户与邀请.

For now this runs only against this worktree's marked synthetic ``pdos_test``
environment, with the same marker and schema-head guards as acceptance_account.py.
Provisioning a real pilot tenant needs the deployment decision (D210) and separate
authorization first; this tool does not reach any other database.

The link carries a secret. It is written to the environment's private state file
(mode 0600) under ``tenant_provision_links.<name>`` and never printed.

    tenant_provision.py create --seed tools/seeds/sign-in-walkthrough.json
    tenant_provision.py create --name pilot --admin-login pilot-admin \\
        --admin-name "试点管理员" --category "轮胎充气泵"
    tenant_provision.py link --name pilot     # new link while no password is set
    tenant_provision.py list
"""

import argparse
import json
import secrets
import sys
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from acceptance_account import ROOT, at_head, verified_state
from pdos_next.core.accounts.passwords import login_name
from pdos_next.core.models import (
    AccountEvent,
    AccountInvitation,
    Category,
    Grant,
    HumanCredential,
    Principal,
    now,
)
from pdos_next.core.service import digest
from pdos_next.errors import DomainError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

LIFETIME = timedelta(hours=72)


def _save(path, state):
    target = Path(path)
    target.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    target.chmod(0o600)


def _link(session, tenant, person, base_url):
    instant = now()
    session.execute(
        update(AccountInvitation)
        .where(
            AccountInvitation.tenant_id == tenant,
            AccountInvitation.principal_id == person,
            AccountInvitation.used_at.is_(None),
            AccountInvitation.revoked_at.is_(None),
        )
        .values(revoked_at=instant)
    )
    token = secrets.token_urlsafe(32)
    session.add(
        AccountInvitation(
            tenant_id=tenant,
            principal_id=person,
            purpose="invite",
            token_hash=digest(token),
            created_at=instant,
            expires_at=instant + LIFETIME,
            created_by=person,
        )
    )
    session.add(
        AccountEvent(
            tenant_id=tenant,
            subject_id=person,
            actor_id=person,
            kind="invitation.issue",
            detail={"purpose": "invite", "by": "tenant_provision.py"},
        )
    )
    return f"{base_url.rstrip('/')}/invite#{token}", instant + LIFETIME


def _options(args):
    if args.seed:
        seed = json.loads(Path(args.seed).read_text())
        tenant, admin = seed["tenant"], seed["administrator"]
        return (
            args.name or tenant["name"],
            admin["login_name"],
            admin["display_name"],
            tenant["category"],
            tenant.get("purpose", ""),
        )
    if not (args.name and args.admin_login and args.admin_name and args.category):
        raise SystemExit("Give --seed, or all of --name --admin-login --admin-name --category.")
    return args.name, args.admin_login, args.admin_name, args.category, args.purpose


def create(args):
    from pdos_next.agent.kernel.models import TenantAdministrator

    state, admin = verified_state(args.state)
    head = at_head(admin)
    name, login, display, category_name, purpose = _options(args)
    try:
        login = login_name(login)
    except DomainError as error:
        raise SystemExit(f"Refusing: {error.message}") from None
    provisions = state.setdefault("tenant_provisions", {})
    if name in provisions:
        raise SystemExit(f"Refusing: tenant {name!r} already provisioned; use link for a new link.")
    tenant, person, category = uuid4(), uuid4(), uuid4()
    with Session(admin) as session, session.begin():
        if session.scalar(select(HumanCredential.id).where(HumanCredential.login_name == login)):
            raise SystemExit(f"Refusing: login name {login!r} is already taken.")
        session.add(Principal(id=person, tenant_id=tenant, name=display, kind="human"))
        session.flush()
        session.add_all(
            [
                TenantAdministrator(tenant_id=tenant, principal_id=person),
                HumanCredential(
                    tenant_id=tenant, principal_id=person, login_name=login, created_by=person
                ),
                Category(
                    id=category,
                    tenant_id=tenant,
                    name=category_name,
                    purpose=purpose,
                    owner_id=person,
                ),
                AccountEvent(
                    tenant_id=tenant,
                    subject_id=person,
                    actor_id=person,
                    kind="account.create",
                    detail={"login_name": login, "by": "tenant_provision.py"},
                ),
            ]
        )
        session.flush()
        session.add(
            Grant(
                tenant_id=tenant,
                category_id=category,
                principal_id=person,
                can_write=True,
                product_manager=True,
                expires_at=None,
            )
        )
        url, expires = _link(session, tenant, person, args.base_url)
    provisions[name] = {
        "tenant_id": str(tenant),
        "administrator_id": str(person),
        "administrator_login": login,
        "administrator_name": display,
        "category_id": str(category),
        "category_name": category_name,
        "link_expires_at": expires.isoformat(),
        "schema_head": head,
        "purpose": "local synthetic sign-in demonstration; no pilot admission or qualification",
    }
    state.setdefault("tenant_provision_links", {})[name] = url
    _save(args.state, state)
    print(f"Tenant {name!r} provisioned on schema {head}.")
    print(f"  administrator  {person}  ({display}, login {login})")
    print(f"  tenant         {tenant}")
    print(f"  category       {category}  ({category_name}, owner and product manager)")
    print(f"  link           72 hours, single use; kept in {args.state}")


def link(args):
    state, admin = verified_state(args.state)
    at_head(admin)
    entry = state.get("tenant_provisions", {}).get(args.name)
    if entry is None:
        raise SystemExit(f"No provisioned tenant named {args.name!r} in this environment.")
    tenant, person = UUID(entry["tenant_id"]), UUID(entry["administrator_id"])
    with Session(admin) as session, session.begin():
        credential = session.scalar(
            select(HumanCredential).where(
                HumanCredential.tenant_id == tenant, HumanCredential.principal_id == person
            )
        )
        if credential.password_hash is not None:
            raise SystemExit("Refusing: the administrator has a password; reset it in Settings.")
        url, expires = _link(session, tenant, person, args.base_url)
    entry["link_expires_at"] = expires.isoformat()
    state.setdefault("tenant_provision_links", {})[args.name] = url
    _save(args.state, state)
    print(f"New 72-hour link for {args.name!r}; earlier links stop working.")
    print(f"  kept in {args.state}")


def show(args):
    state = json.loads(Path(args.state).read_text())
    for name, entry in state.get("tenant_provisions", {}).items():
        print(
            f"{name}: {entry['administrator_name']} ({entry['administrator_login']}) · "
            f"{entry['category_name']} · link until {entry['link_expires_at'][:16]}"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["create", "link", "list"])
    parser.add_argument("--state", default=str(ROOT / ".local" / "runtime.json"))
    parser.add_argument("--seed")
    parser.add_argument("--name")
    parser.add_argument("--admin-login")
    parser.add_argument("--admin-name")
    parser.add_argument("--category")
    parser.add_argument("--purpose", default="")
    parser.add_argument("--base-url", default="http://127.0.0.1:3000")
    args = parser.parse_args()
    {"create": create, "link": link, "list": show}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())
