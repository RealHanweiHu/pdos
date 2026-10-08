"""One verified, scoped read profile for the observed graph-expiry failure."""

import asyncio
import cProfile
import io
import json
import os
import pstats
import sys
import time
from uuid import UUID

from local_environment import ROOT, SERVER, environment, read_state, verified

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave15-20261002"
sys.path.insert(0, str(SERVER))


async def main():
    from pdos_next.api import create_app
    from pdos_next.database import engine_for, tenant_session
    from pdos_next.domain.quality_execution.service import get_issue
    from pdos_next.original_store import OriginalStore
    from pdos_next.security_bootstrap import local_runtime
    from pdos_next.service import Context
    from workflow_environment import read_verified, state_environment

    state = verified(read_state())
    assert state["port"] == 62513
    seed = json.loads((ROOT / ".local/wave15-seed.json").read_text())
    assert seed["marker"] == state["marker"]
    env = {**environment(state), **state_environment(read_verified())}
    os.environ.update(env)
    store = OriginalStore(env["PDOS_OBJECT_ROOT"])
    security = await local_runtime(store)
    engine = engine_for(state["app_url"])
    auth_engine = engine_for(state["auth_url"])

    def profile(name):
        path = ROOT / ".local" / name
        return json.loads(path.read_text()) if path.exists() else None

    create_app(
        engine, auth_engine, object_store=store, security_runtime=security,
        lifecycle_enabled=True,
        professional_synthetic_scope={
            "tenant_id": seed["tenant_id"], "product_id": seed["product_id"]
        },
        operational_synthetic_profile=profile("operational-synthetic-profile.json"),
        test_resource_synthetic_profile=profile("test-resource-synthetic-profile.json"),
        quality_synthetic_profile=profile("quality-synthetic-profile.json"),
    )
    profiler = cProfile.Profile()
    start = time.monotonic()
    result = {"status": "failed", "read_only_business_facts": True,
              "selected_issue_id": seed["issue_id"], "port": 62513}
    try:
        with tenant_session(engine, UUID(seed["tenant_id"])) as session:
            ctx = Context(UUID(seed["tenant_id"]), UUID(seed["actor_id"]), UUID(seed["actor_id"]))
            profiler.enable()
            row, view = get_issue(session, ctx, UUID(seed["product_id"]), UUID(seed["issue_id"]))
            profiler.disable()
            result.update(status="passed" if view.source_status == "current" else "incomplete",
                          revision=row.revision, source_status=view.source_status)
    except Exception as error:
        profiler.disable()
        result["error_code"] = getattr(error, "code", type(error).__name__)
    finally:
        result["seconds"] = round(time.monotonic() - start, 3)
        output = io.StringIO()
        pstats.Stats(profiler, stream=output).strip_dirs().sort_stats("cumulative").print_stats(45)
        with (REPORT / "issue-owner-profile-v3-security.log").open("x") as handle:
            handle.write(output.getvalue())
        with (REPORT / "issue-owner-profile-v3-security.json").open("x") as handle:
            json.dump(result, handle, indent=2)
            handle.write("\n")
        engine.dispose()
        auth_engine.dispose()
        close = getattr(getattr(security, "scanner", None), "close", None)
        if close:
            await close()
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
