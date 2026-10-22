"""Root actual synthetic anchor read: existing lock-taking owners, DML denied.

The caller transaction always rolls back. This is business read-only, not a
PostgreSQL READ ONLY transaction: unchanged owner gates take actual row locks.
"""

# Initialize public common contracts before staged owner imports.
# ruff: noqa: I001

import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from local_environment import ROOT, SERVER, read_state, verified
from wave16_check import source_files
from wave16_closeout import private_json


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


async def main():
    report = ROOT.parent / "docs/reports/evidence/pdos-next-wave17-20261003"
    output = report / "anchor-actual-business-readonly-v2.json"
    if output.exists():
        raise RuntimeError("Preserve previous actual anchor observations")
    state = private_json(ROOT / ".local/runtime.json")
    from sqlalchemy.engine import make_url

    if state != read_state() or state["marker"] != "916f950f-2d2b-405d-b809-c15db75dc20c":
        raise RuntimeError("Exact existing marked state required")
    for field in ("app_url", "admin_url", "auth_url"):
        url = make_url(state[field])
        if url.host != "127.0.0.1" or url.port != 62513 or url.database != "pdos_test":
            raise RuntimeError("Wrong explicit independent role endpoint")
    state = verified(state)
    seed_path = ROOT / ".local/wave15-seed.json"
    identities_path = ROOT / ".local/wave16-saved-ids.json"
    seed, identities = private_json(seed_path), private_json(identities_path)
    if seed["marker"] != state["marker"]:
        raise RuntimeError("Existing seed marker differs")
    tenant, actor, product_id = (UUID(seed[key]) for key in ("tenant_id", "actor_id", "product_id"))
    if str(tenant) != state["preview_tenant_id"] or str(product_id) != state["preview_product_id"]:
        raise RuntimeError("Existing caller scope differs")
    public_manifest = (
        ROOT.parent
        / "docs/reports/evidence/pdos-next-wave16-20261002/backend-candidate-source-v5.json"
    )
    public = json.loads(public_manifest.read_text())["files"]
    if public != source_files():
        raise RuntimeError("Frozen v5 public identity changed")
    dependencies = {
        str(path.relative_to(ROOT.parent)): sha(path)
        for path in (ROOT / "staging/wave17").glob("*.py")
        if not path.name.startswith("test_")
        and path.name not in {"candidate_commands.py", "candidate_prepare.py", "candidate_write.py"}
    }
    sys.path.insert(0, str(ROOT / "staging/wave17"))
    sys.path.insert(0, str(SERVER))
    from pdos_next.api import create_app
    from pdos_next.database import engine_for
    from pdos_next.domain.quality_execution.models import QualityIssueVersion
    from pdos_next.errors import DomainError
    from pdos_next.original_store import OriginalStore
    from pdos_next.security_bootstrap import local_runtime
    from pdos_next.service import Context
    from sqlalchemy import event, select, text
    from sqlalchemy.orm import Session
    from anchor import VersionRef
    from anchor_owner import read_anchor_from_actual_owner

    engine, auth = engine_for(state["app_url"]), engine_for(state["auth_url"])
    counts = {"select": 0, "show": 0, "set": 0, "rejected": 0, "flush_attempts": 0}

    def deny_writes(_conn, _cursor, statement, _parameters, _context, _executemany):
        word = statement.lstrip().split(None, 1)[0].lower()
        if word not in {"select", "show", "set"}:
            counts["rejected"] += 1
            raise RuntimeError("Business-read observation rejected non-read SQL")
        counts[word] += 1

    def deny_flush(_session, _context, _instances):
        counts["flush_attempts"] += 1
        raise RuntimeError("Business-read observation rejected ORM flush")

    event.listen(engine, "before_cursor_execute", deny_writes)
    event.listen(auth, "before_cursor_execute", deny_writes)
    security = None
    started = time.monotonic()
    result = {
        "status": "FAILED",
        "scope": "Actual existing synthetic original owner/bytes anchor read",
        "target": "127.0.0.1:62513/pdos_test",
        "marker": state["marker"],
        "observed_at": datetime.now(UTC).isoformat(),
        "public_candidate_sha256": sha(public_manifest),
        "staged_dependency_sha256": dependencies,
        "tool_sha256": sha(__file__),
        "saved_identity_source_sha256": sha(identities_path),
        "postgresql_read_only_transaction": False,
        "read_owners_keep_their_existing_row_locks": True,
        "business_dml_denied_at_driver": True,
        "caller_transaction_end": "rollback",
        "model_calls": 0,
        "business_commands": 0,
        "public_registration": False,
    }
    try:
        object_root = ROOT / ".local/objects"
        if not object_root.is_dir() or object_root.is_symlink():
            raise RuntimeError("Existing fixed local object directory required")
        store = OriginalStore(object_root)
        os.environ["PDOS_FILE_SECURITY_PROFILE"] = "local-synthetic-v1"
        security = await local_runtime(store)
        if security is None:
            raise RuntimeError("Existing actual local security runtime unavailable")

        def profile(name):
            return private_json(ROOT / ".local" / name)

        create_app(
            engine,
            auth,
            object_store=store,
            security_runtime=security,
            lifecycle_enabled=True,
            professional_synthetic_scope={"tenant_id": str(tenant), "product_id": str(product_id)},
            operational_synthetic_profile=profile("operational-synthetic-profile.json"),
            test_resource_synthetic_profile=profile("test-resource-synthetic-profile.json"),
            quality_synthetic_profile=profile("quality-synthetic-profile.json"),
            quality_followup_synthetic_profile=profile("quality-followup-synthetic-profile.json"),
        )
        with Session(engine) as session:
            event.listen(session, "before_flush", deny_flush)
            session.begin()
            try:
                with session.no_autoflush:
                    session.execute(text("SET LOCAL statement_timeout='120s'"))
                    session.execute(text("SET LOCAL lock_timeout='10s'"))
                    session.execute(
                        text("SELECT set_config('pdos.tenant_id', :tenant, true)"),
                        {"tenant": str(tenant)},
                    )
                    row = session.scalar(
                        select(QualityIssueVersion).where(
                            QualityIssueVersion.tenant_id == tenant,
                            QualityIssueVersion.product_id == product_id,
                            QualityIssueVersion.issue_id == UUID(identities["issue"]),
                            QualityIssueVersion.id == UUID(identities["complete_v6"]),
                        )
                    )
                    if row is None:
                        raise RuntimeError("Exact actual completed origin missing")
                    ref = VersionRef(
                        id=row.id, revision=row.revision, snapshot_sha256=row.snapshot_sha256
                    )
                    read = read_anchor_from_actual_owner(
                        session, Context(tenant, actor, actor), product_id, row.issue_id, ref
                    )
                    if session.new or session.dirty or session.deleted:
                        raise RuntimeError("Read path changed ORM business state")
                    result.update(
                        {
                            "status": "PASS",
                            "origin_revision": read.anchor.origin.ref.revision,
                            "anchor_sha256": read.anchor.anchor_sha256,
                            "full_failure_proofs_sha256": read.anchor.full_failure_proofs_sha256,
                            "stable_failure_material_sha256": (
                                read.anchor.stable_failure_material_sha256
                            ),
                            "failures": len(read.anchor.failures),
                            "complete_source_reads": len(
                                read.anchor.origin_required_source_read_set
                            ),
                            "needs_lineage_owner": read.needs_lineage_owner,
                            "missing_owners": read.missing_owners,
                            "current_evidence_authorized": read.current_evidence_authorized,
                            "same_uow_consumption_attested": read.same_uow_consumption_attested,
                            "new_dirty_deleted_all_empty": True,
                        }
                    )
            finally:
                session.rollback()
    except DomainError as failure:
        result["error"] = {"type": type(failure).__name__, "code": failure.code}
    except Exception as failure:
        result["error"] = {"type": type(failure).__name__}
    finally:
        engine.dispose()
        auth.dispose()
        if security is not None:
            close = getattr(getattr(security, "scanner", None), "close", None)
            if close:
                await close()
    result["seconds"] = round(time.monotonic() - started, 2)
    result["sql_counts"] = counts
    result["public_source_stable"] = source_files() == public
    result["staged_dependency_stable"] = dependencies == {
        name: sha(ROOT.parent / name) for name in dependencies
    }
    with output.open("x") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(result["status"], result.get("error", {}), result["seconds"], flush=True)
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
