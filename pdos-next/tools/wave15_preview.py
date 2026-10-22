"""Use the independent synthetic person for local preview without changing old state."""

import json
import os
import sys
from uuid import UUID

from local_environment import ROOT, SERVER, environment, read_state, verified

sys.path.insert(0, str(SERVER))
from pdos_next.database import engine_for, tenant_session  # noqa: E402
from pdos_next.models import Grant, LoginSession, Principal, now  # noqa: E402
from pdos_next.service import digest  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

state = verified(read_state())
path = ROOT / ".local/wave15-seed.json"
assert path.stat().st_mode & 0o777 == 0o600
seed = json.loads(path.read_text())
assert seed["marker"] == str(state["marker"])
assert seed["tenant_id"] == str(state["preview_tenant_id"])
assert seed["product_id"] == str(state["preview_product_id"])
tenant, actor, product = UUID(seed["tenant_id"]), UUID(seed["actor_id"]), UUID(seed["product_id"])
with Session(engine_for(state["auth_url"])) as s:
    login = s.get(LoginSession, digest(seed["login_token"]))
    assert (
        login is not None
        and login.tenant_id == tenant
        and login.principal_id == actor
        and not login.revoked
        and login.expires_at > now()
    )
with tenant_session(engine_for(state["app_url"]), tenant) as s:
    principal = s.get(Principal, actor)
    grant = s.scalar(
        select(Grant).where(
            Grant.tenant_id == tenant, Grant.product_id == product, Grant.principal_id == actor
        )
    )
    assert principal is not None and principal.active and principal.kind == "human"
    assert grant is not None and grant.can_write and grant.expires_at > now()
env = environment(state)
env.update(PDOS_NEXT_API_URL="http://127.0.0.1:8898", PDOS_NEXT_LOCAL_SESSION=seed["login_token"])
os.chdir(ROOT / "web")
os.execvpe("pnpm", ["pnpm", "start", "--hostname", "127.0.0.1", "--port", "3028"], env)
