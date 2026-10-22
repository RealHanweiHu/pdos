"""Read only the old Link's current professional snapshot on the marked target."""

# Initialize local harness before server modules.
# ruff: noqa: I001
import asyncio
import json
import os
import sys
import traceback
from datetime import UTC, datetime
from uuid import UUID

from local_environment import ROOT
from wave17_migrate import target
from wave16_closeout import private_json
from pdos_next.api import create_app
from pdos_next.database import engine_for, tenant_session
from pdos_next.domain.capa_verification.models import RemediationLinkRecord
from pdos_next.domain.capa_verification import service as links
from pdos_next.domain.capa_verification.schemas import FixedRef, FollowupBasis, ResolvedOutputs
from pdos_next.errors import DomainError
from pdos_next.domain.professional_authority.service import recheck_snapshot
from pdos_next.original_store import OriginalStore
from pdos_next.security_bootstrap import local_runtime
from pdos_next.service import Context, now
from sqlalchemy import select


def differences(old, new, path=""):
    if type(old) is type(new) and isinstance(old, dict):
        found = []
        for key in sorted(old.keys() | new.keys()):
            found.extend(differences(old.get(key), new.get(key), f"{path}/{key}"))
        return found
    if type(old) is type(new) and isinstance(old, list) and len(old) == len(new):
        return [
            item
            for i, pair in enumerate(zip(old, new, strict=True))
            for item in differences(*pair, f"{path}/{i}")
        ]
    if old == new:
        return []
    return [
        {
            "path": path,
            "old_sha256": links.digest(old),
            "new_sha256": links.digest(new),
            "old_length": len(old) if isinstance(old, (dict, list, str)) else None,
            "new_length": len(new) if isinstance(new, (dict, list, str)) else None,
        }
    ]


async def main():
    state = target()
    seed = private_json(ROOT / ".local/wave15-seed.json")
    ids = private_json(ROOT / ".local/wave16-saved-ids.json")
    tenant, actor, pid = (UUID(seed[k]) for k in ("tenant_id", "actor_id", "product_id"))
    os.environ["PDOS_FILE_SECURITY_PROFILE"] = "local-synthetic-v1"
    store = OriginalStore(ROOT / ".local/objects")
    runtime = await local_runtime(store)
    engine = engine_for(state["app_url"])
    create_app(
        engine,
        engine_for(state["auth_url"]),
        object_store=store,
        security_runtime=runtime,
        lifecycle_enabled=True,
        professional_synthetic_scope={"tenant_id": str(tenant), "product_id": str(pid)},
        operational_synthetic_profile=private_json(
            ROOT / ".local/operational-synthetic-profile.json"
        ),
        test_resource_synthetic_profile=private_json(
            ROOT / ".local/test-resource-synthetic-profile.json"
        ),
        quality_synthetic_profile=private_json(ROOT / ".local/quality-synthetic-profile.json"),
        quality_followup_synthetic_profile=private_json(
            ROOT / ".local/quality-followup-synthetic-profile.json"
        ),
    )
    result = {
        "scope": "actual readonly Link professional fingerprint; no fact writes",
        "model_calls": 0,
    }
    try:
        with tenant_session(engine, tenant) as s:
            row = s.scalar(
                select(RemediationLinkRecord).where(
                    RemediationLinkRecord.issue_id == UUID(ids["issue"])
                )
            )
            assert row is not None
            ctx = Context(tenant, actor, actor)
            for retained in (False, True):
                value = recheck_snapshot(
                    s, ctx, pid, row.project_id, row.authority_snapshot, now(), retained=retained
                )
                result[str(retained)] = {
                    "current": value["current"],
                    "authorized": value["assessment"]["authorized"],
                    "qualified": value["assessment"]["qualified"],
                    "reason_codes": value["reason_codes"],
                }
            assert result["False"]["current"] is False and result["True"]["current"] is True
            if sys.argv[1:] in (["v2"], ["v3"], ["v4"]):
                try:
                    links._link(
                        s,
                        ctx,
                        pid,
                        FollowupBasis.model_validate(row.basis_snapshot),
                        FixedRef(id=row.id, revision=row.revision),
                    )
                    result["actual_link"] = {"current": True}
                except DomainError as error:
                    result["actual_link"] = {
                        "current": False,
                        "code": error.code,
                        "message": error.message,
                        "frames": [
                            {"file": frame.filename.split("/")[-1], "line": frame.lineno}
                            for frame in traceback.extract_tb(error.__traceback__)[-4:]
                        ],
                    }
                if sys.argv[1:] == ["v4"]:
                    assert result["actual_link"]["current"] is True
            if sys.argv[1:] == ["v3"]:
                resolved = ResolvedOutputs.model_validate(row.output_snapshot)
                current = links.resolve_followup_outputs(
                    s,
                    ctx,
                    pid,
                    FollowupBasis.model_validate(row.basis_snapshot),
                    row.action_id,
                    tuple(o.ref for o in resolved.outputs),
                )
                before = resolved.model_dump(mode="json")
                after = current.model_dump(mode="json")
                result["fixed_output_differences"] = differences(
                    {key: before[key] for key in ("outputs", "source_basis_sha256", "visibility")},
                    {key: after[key] for key in ("outputs", "source_basis_sha256", "visibility")},
                )
            s.rollback()
        result.update(status="PASS", finished_at=datetime.now(UTC).isoformat())
    finally:
        await runtime.scanner.close()
    tag = sys.argv[1] if sys.argv[1:] in (["v2"], ["v3"], ["v4"]) else "v1"
    out = (
        ROOT.parent
        / "docs/reports/evidence/pdos-next-wave17-20261003"
        / f"link-authority-actual-readonly-{tag}.json"
    )
    with out.open("x") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
