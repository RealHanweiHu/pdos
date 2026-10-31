"""Provision a named acceptance account in one marked local environment.

An acceptance account is a real login for walking附录 B 的验收场景 by hand: a
Principal, a category Grant and a LoginSession token. It is environment-scoped
and synthetic.

P27 (2026-10-22) permits the owner to review G0 in an active pilot tenant.
This synthetic login still cannot prove the real person reviewed or accepted
a particular proposal: preserve that distinction in all acceptance evidence.

Usage (from pdos-next/):
    tools/acceptance_account.py create [--state FILE] [--name NAME] [--days N]
    tools/acceptance_account.py renew  [--state FILE] [--name NAME] [--days N]
    tools/acceptance_account.py list   [--state FILE]

Tokens are written into the environment's own state file next to its other
credentials. They are never printed.
"""

import argparse
import json
import re
import secrets
import sys
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
VERSIONS = SERVER / "migrations" / "versions"
sys.path.insert(0, str(SERVER))

from pdos_next.database import engine_for  # noqa: E402
from pdos_next.models import (  # noqa: E402
    Category,
    Grant,
    LoginSession,
    Principal,
    Product,
    now,
)
from pdos_next.service import digest  # noqa: E402


def repo_head():
    """The single current head in migrations/versions, by actual file content."""
    revisions, parents = set(), set()
    for path in VERSIONS.glob("*.py"):
        body = path.read_text(encoding="utf-8")
        revision = re.search(r'^revision = "([^"]+)"', body, re.M)
        parent = re.search(r'^down_revision = "([^"]+)"', body, re.M)
        if revision:
            revisions.add(revision.group(1))
        if parent:
            parents.add(parent.group(1))
    heads = revisions - parents
    if len(heads) != 1:
        raise RuntimeError(f"Expected one migration head, found {sorted(heads)}")
    return heads.pop()


def verified_state(path):
    """Reuse the shared target guard; no .env fallback and no unmarked database."""
    import os

    from pdos_next.safety import verify_test_target

    state = json.loads(Path(path).read_text())
    os.environ.update(
        TEST_DATABASE_URL=state["admin_url"],
        TEST_DATABASE_MARKER=state["marker"],
        TEST_DATABASE_PORT=str(state["port"]),
    )
    admin = engine_for(state["admin_url"])
    verify_test_target(admin)
    return state, admin


def at_head(admin):
    with Session(admin) as session:
        from sqlalchemy import text

        actual = session.scalars(text("SELECT version_num FROM alembic_version")).all()
    head = repo_head()
    if list(actual) != [head]:
        raise SystemExit(
            f"Refusing: this environment is at {list(actual) or 'no revision'}, the repository "
            f"head is {head}. An acceptance account on a stale schema produces acceptance "
            f"evidence for a schema nobody ships. Upgrade the environment first."
        )
    return head


def _scope(session, state):
    """The environment's own tenant/category, created once if it has none."""
    if state.get("preview_tenant_id") and state.get("preview_category_id"):
        tenant = UUID(state["preview_tenant_id"])
        category = UUID(state["preview_category_id"])
        found = session.scalar(
            select(Category).where(Category.tenant_id == tenant, Category.id == category)
        )
        assert found is not None, "This environment's category is gone"
        return tenant, category, False
    # Imported here: the kernel models resolve their FK metadata through
    # pdos_next.models, so they cannot be imported before it.
    from pdos_next.agent_kernel.models import TenantPilotAdmission

    tenant, category, person = uuid4(), uuid4(), uuid4()
    session.add(Principal(id=person, tenant_id=tenant, name="验收环境负责人", kind="human"))
    session.flush()
    session.add(
        TenantPilotAdmission(
            tenant_id=tenant,
            active=True,
            approval_reference="Local acceptance environment only; no pilot qualification",
        )
    )
    session.add(
        Category(
            id=category,
            tenant_id=tenant,
            name="汽车充气泵",
            purpose="验收演练品类范围，不代表真实品类资料",
            owner_id=person,
        )
    )
    session.flush()
    product = Product(
        id=uuid4(),
        tenant_id=tenant,
        category_id=category,
        name="验收演练型号",
        purpose="按附录 B 场景手工走流程，不代表真实产品定义。",
        owner_id=person,
    )
    session.add(product)
    session.flush()
    session.add(
        Grant(
            tenant_id=tenant,
            category_id=category,
            principal_id=person,
            can_write=True,
            product_manager=True,
            expires_at=now() + timedelta(days=30),
        )
    )
    state.update(
        preview_tenant_id=str(tenant),
        preview_category_id=str(category),
        preview_product_id=str(product.id),
        acceptance_owner_id=str(person),
    )
    return tenant, category, True


def _token(session, tenant, principal, days):
    token = secrets.token_urlsafe(32)
    expires = now() + timedelta(days=days)
    session.add(
        LoginSession(
            tenant_id=tenant,
            principal_id=principal,
            token_hash=digest(token),
            expires_at=expires,
        )
    )
    return token, expires


def create(args):
    state, admin = verified_state(args.state)
    head = at_head(admin)
    accounts = state.setdefault("acceptance_accounts", {})
    if args.name in accounts:
        raise SystemExit(f"Refusing: {args.name!r} already exists; use renew to issue a token.")
    with Session(admin) as session, session.begin():
        tenant, category, fresh = _scope(session, state)
        principal = uuid4()
        session.add(Principal(id=principal, tenant_id=tenant, name=args.display_name, kind="human"))
        session.flush()
        session.add(
            Grant(
                tenant_id=tenant,
                category_id=category,
                principal_id=principal,
                can_write=True,
                product_manager=args.product_manager,
                expires_at=now() + timedelta(days=args.days),
            )
        )
        token, expires = _token(session, tenant, principal, args.days)
    accounts[args.name] = {
        "principal_id": str(principal),
        "display_name": args.display_name,
        "tenant_id": str(tenant),
        "category_id": str(category),
        "product_manager": args.product_manager,
        "expires_at": expires.isoformat(),
        "schema_head": head,
        "purpose": (
            "manual synthetic acceptance walkthrough; "
            "personal G0 review requires actual user action (P27)"
        ),
    }
    state.setdefault("acceptance_tokens", {})[args.name] = token
    Path(args.state).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    print(f"Acceptance account {args.name!r} created on schema {head}.")
    print(f"  principal   {principal}  ({args.display_name})")
    print(f"  tenant      {tenant}")
    print(f"  category    {category}{'  (new acceptance scope)' if fresh else ''}")
    print(f"  grant       can_write=True product_manager={args.product_manager}")
    print(f"  expires     {expires.isoformat()}")
    print(f"  token       stored in {args.state} under acceptance_tokens.{args.name}")
    print("P27 allows pilot owner review; this login alone does not prove personal acceptance.")


def renew(args):
    state, admin = verified_state(args.state)
    at_head(admin)
    account = state.get("acceptance_accounts", {}).get(args.name)
    if account is None:
        raise SystemExit(f"Refusing: no acceptance account named {args.name!r}.")
    tenant, principal = UUID(account["tenant_id"]), UUID(account["principal_id"])
    with Session(admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(
                Grant.tenant_id == tenant,
                Grant.category_id == UUID(account["category_id"]),
                Grant.principal_id == principal,
            )
        )
        if grant is None:
            raise SystemExit("Refusing: the category grant is gone; create a new account.")
        grant.expires_at = now() + timedelta(days=args.days)
        token, expires = _token(session, tenant, principal, args.days)
    account["expires_at"] = expires.isoformat()
    state.setdefault("acceptance_tokens", {})[args.name] = token
    Path(args.state).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    print(f"Renewed {args.name!r} until {expires.isoformat()}; the earlier token stays valid")
    print(f"until its own expiry. New token stored in {args.state}.")


def admit(args):
    """Record this environment's tenant as locally admitted to the pilot.

    tenant_pilot_admissions gates skill enablement and the Xiaopai flows. A
    synthetic local environment holds no real pilot approval, and the reference
    says exactly that; it never stands in for one.
    """
    from pdos_next.agent_kernel.models import TenantPilotAdmission

    state, admin = verified_state(args.state)
    at_head(admin)
    tenant = state.get("preview_tenant_id")
    if tenant is None:
        raise SystemExit("Refusing: this environment has no tenant yet; create an account first.")
    with Session(admin) as session, session.begin():
        row = session.get(TenantPilotAdmission, UUID(tenant))
        if row is None:
            session.add(
                TenantPilotAdmission(
                    tenant_id=UUID(tenant),
                    active=True,
                    approval_reference=(
                        "Local acceptance environment only; no pilot qualification"
                    ),
                )
            )
            print(f"Recorded a local pilot admission for tenant {tenant}.")
        else:
            row.active = True
            print(f"Tenant {tenant} was already admitted; active is now True.")


def show(args):
    state = json.loads(Path(args.state).read_text())
    accounts = state.get("acceptance_accounts", {})
    if not accounts:
        print(f"No acceptance account in {args.state}.")
        return
    for name, account in sorted(accounts.items()):
        print(f"{name}: {account['display_name']} · principal {account['principal_id']}")
        print(
            f"    tenant {account['tenant_id']} · category {account['category_id']} · "
            f"product_manager={account['product_manager']} · expires {account['expires_at']}"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "renew", "list", "admit"])
    parser.add_argument("--state", default=str(ROOT / ".local" / "runtime.json"))
    parser.add_argument("--name", default="acceptance")
    parser.add_argument("--display-name", default="验收账号（仅验收演练）")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--no-product-manager", dest="product_manager", action="store_false")
    parser.set_defaults(product_manager=True)
    args = parser.parse_args()
    {"create": create, "renew": renew, "list": show, "admit": admit}[args.action](args)


if __name__ == "__main__":
    main()
