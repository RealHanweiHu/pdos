"""Personal accounts for local development.

People sign in on /login with a password (D214, tenant_provision.py opens a tenant).
For local development a browser session can still come from a token issued here. `create` makes a person in a tenant of their own, with one
empty category they own and manage as product manager, and keeps the session
token in the environment's private state file. `local_environment.py serve-dev
<name>` then serves the app signed in as that person.

This is local development only: not acceptance evidence, not a pilot admission
and not a model qualification. It uses the same marked-database and schema-head
guards as acceptance_account.py, and never prints the token.

    dev_account.py create --name hanwei --display-name "Hanwei Hu" --category 轮胎充气泵
    dev_account.py renew --name hanwei
    dev_account.py list
"""

import argparse
import json
from pathlib import Path
from uuid import UUID, uuid4

from acceptance_account import ROOT, _token, at_head, verified_state
from pdos_next.core.models import Category, Grant, Principal
from sqlalchemy.orm import Session


def _save(path, state):
    Path(path).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def create(args):
    state, admin = verified_state(args.state)
    head = at_head(admin)
    accounts = state.setdefault("dev_accounts", {})
    if args.name in accounts:
        raise SystemExit(f"Refusing: {args.name!r} already exists; use renew to issue a token.")
    tenant, person, category = uuid4(), uuid4(), uuid4()
    with Session(admin) as session, session.begin():
        session.add(Principal(id=person, tenant_id=tenant, name=args.display_name, kind="human"))
        session.flush()
        session.add(
            Category(
                id=category,
                tenant_id=tenant,
                name=args.category,
                purpose=args.purpose,
                owner_id=person,
            )
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
        token, expires = _token(session, tenant, person, args.days)
    accounts[args.name] = {
        "principal_id": str(person),
        "display_name": args.display_name,
        "tenant_id": str(tenant),
        "category_id": str(category),
        "category_name": args.category,
        "session_expires_at": expires.isoformat(),
        "schema_head": head,
        "purpose": "local development account; no pilot admission or qualification",
    }
    state.setdefault("dev_tokens", {})[args.name] = token
    _save(args.state, state)
    print(f"Development account {args.name!r} created on schema {head}.")
    print(f"  person      {person}  ({args.display_name})")
    print(f"  tenant      {tenant}  (own tenant)")
    print(f"  category    {category}  ({args.category}, owner and product manager)")
    print(f"  session     until {expires:%Y-%m-%d}; token kept in {args.state}")


def renew(args):
    state, admin = verified_state(args.state)
    at_head(admin)
    account = state.get("dev_accounts", {}).get(args.name)
    if account is None:
        raise SystemExit(f"No development account named {args.name!r} in this environment.")
    with Session(admin) as session, session.begin():
        token, expires = _token(
            session, UUID(account["tenant_id"]), UUID(account["principal_id"]), args.days
        )
    account["session_expires_at"] = expires.isoformat()
    state["dev_tokens"][args.name] = token
    _save(args.state, state)
    print(f"New session for {args.name!r} until {expires:%Y-%m-%d}.")


def show(args):
    state = json.loads(Path(args.state).read_text())
    for name, account in state.get("dev_accounts", {}).items():
        print(
            f"{name}: {account['display_name']} · {account['category_name']} · "
            f"session until {account['session_expires_at'][:10]}"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["create", "renew", "list"])
    parser.add_argument("--state", default=str(ROOT / ".local" / "runtime.json"))
    parser.add_argument("--name", default="dev")
    parser.add_argument("--display-name", default="本地开发者")
    parser.add_argument("--category", default="我的品类")
    parser.add_argument("--purpose", default="")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    {"create": create, "renew": renew, "list": show}[args.action](args)


if __name__ == "__main__":
    main()
