"""Close this checkpoint using only its marked synthetic instance and exact history."""

import hashlib
import json
import subprocess
import sys
from uuid import UUID

import httpx
from local_environment import ROOT, read_state, verified
from pdos_next.database import engine_for, tenant_session
from pdos_next.models import Base, Receipt
from pdos_next.service import digest
from sqlalchemy import select, text

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave13-20261002"
SEED = ROOT / ".local/wave13-seed.json"


def save(name, value):
    (REPORT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def manifest():
    ignored = {
        ".local",
        ".venv",
        "node_modules",
        ".next",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".git",
    }
    return {
        str(p.relative_to(ROOT.parent)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(ROOT.rglob("*"))
        if p.is_file()
        and not ignored.intersection(p.parts)
        and p.suffix not in {".pyc", ".tsbuildinfo"}
    }


action = sys.argv[1]
if action == "freeze":
    candidate = manifest()
    if (REPORT / "candidate.json").exists():
        raise RuntimeError("Keep prior candidate intact; use a distinct candidate after a repair")
    save("candidate.json", candidate)
    print(f"Frozen {len(candidate)} source/configuration files.")
elif action == "candidate-check":
    before = json.loads((REPORT / "candidate.json").read_text())
    actual = manifest()
    changed = [
        name for name in before.keys() | actual.keys() if before.get(name) != actual.get(name)
    ]
    save(
        "candidate-stability.json",
        {"passed": not changed, "files": len(actual), "changed": changed},
    )
    if changed:
        raise RuntimeError("Candidate changed; affected verification must be renewed")
    print("The exact verified candidate remains unchanged.")
elif action in {"business", "backup", "prestart"}:
    state = verified(read_state())
    if action == "backup":
        backup = ROOT / ".local/post-wave13-next_0018.dump"
        with backup.open("xb") as out:
            backup.chmod(0o600)
            subprocess.run(
                [
                    "docker",
                    "exec",
                    state["container"],
                    "pg_dump",
                    "-U",
                    "postgres",
                    "-d",
                    "pdos_test",
                    "-Fc",
                ],
                stdout=out,
                check=True,
            )
        with backup.open("rb") as data, (REPORT / "backup-directory.log").open("x") as out:
            subprocess.run(
                ["docker", "exec", "-i", state["container"], "pg_restore", "--list"],
                stdin=data,
                stdout=out,
                check=True,
            )
        save(
            "backup.json",
            {
                "result": "directory_check_passed",
                "path": str(backup.relative_to(ROOT.parent)),
                "mode": oct(backup.stat().st_mode & 0o777),
                "sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
                "restore_overwrite_performed": False,
                "marker": state["marker"],
                "port": state["port"],
            },
        )
        print("Private final backup and directory check saved; no restore overwrite.")
        sys.exit(0)
    seed = json.loads(SEED.read_text())
    tenant, product = UUID(state["preview_tenant_id"]), UUID(state["preview_product_id"])
    engine = engine_for(state["app_url"])
    if action == "prestart":
        verified(read_state())
        with tenant_session(engine, tenant) as s:
            counts = {
                table: s.scalar(
                    text(f"SELECT count(*) FROM {table} WHERE run_id=:rid"), {"rid": seed["run_id"]}
                )
                for table in ("test_resource_reservations", "sample_run_usages")
            }
            counts["operational_resource_occupancies"] = s.scalar(
                text(
                    "SELECT count(*) FROM operational_resource_occupancies WHERE test_run_id=:rid"
                ),
                {"rid": seed["run_id"]},
            )
            assert all(v == 0 for v in counts.values())
        save(
            "zero-effects-before-start.json",
            {
                "result": "passed",
                "phase": seed["phase"],
                "counts": counts,
                "port": state["port"],
                "marker": state["marker"],
            },
        )
        print("Fixed plan and named promise have zero own occupancy and sample use.")
        sys.exit(0)
    with httpx.Client(
        base_url="http://127.0.0.1:8898",
        trust_env=False,
        timeout=180,
        headers={"Authorization": "Bearer " + state["preview_token"]},
    ) as client:
        verified(read_state())
        response = client.get(
            f"/v1/products/{product}/verification-launch?build_id={seed['build_id']}"
        )
        response.raise_for_status()
        view = response.json()
    save("actual-preview.json", view)
    request = next(
        r
        for r in view["requests"]
        if r["id"] == view["current_by_request"][seed["request_id"]]["request_version_id"]
    )
    run = next(
        r
        for r in view["runs"]
        if r["id"] == view["current_by_run"][seed["run_id"]]["run_version_id"]
    )
    assert request["status"] == "executing" and request["revision"] == 7
    assert run["status"] == "running" and run["revision"] == 2 and run["result"] == "pending"
    assert run["run_snapshot"]["coverage"] == seed["launch_coverage"]
    assert len(run["occupancy"]) == 2 and len(run["sample_usage"]) == 1
    assert not run["zero_occupancy"]
    assert (
        run["occupancy_evaluation"] == "saved_committed_effects_current_qualification_not_evaluated"
    )
    assert request["coverage_gaps"]
    assert request["timeline"]["final_result"] is None and request["timeline"]["disposed"] is None
    assert request["timeline"]["actual_start"]["occurred_at"] == seed["start_event"][
        "occurred_at"
    ].replace("+00:00", "Z")
    verified(read_state())
    with tenant_session(engine, tenant) as s:
        baseline = json.loads((REPORT / "old-business-manifest.json").read_text())
        old_history = {}
        for table, old in baseline.items():
            rows = {
                str(identity): digest(value)
                for identity, value in s.execute(text(f"SELECT id, to_jsonb(t) FROM {table} t"))
            }
            assert all(rows.get(identity) == checksum for identity, checksum in old.items()), table
            old_history[table] = {"old_rows": len(old), "unchanged": True}
        receipts = s.scalars(
            select(Receipt).where(
                Receipt.product_id == product,
                Receipt.operation.in_(
                    ("test.run.plan", "verification.schedule.promise", "test.run.start")
                ),
            )
        ).all()
        assert len(receipts) == 3
        checks = []
        for receipt in receipts:
            counts = {
                table: s.scalar(
                    text(f"SELECT count(*) FROM {table} WHERE receipt_id=:rid"), {"rid": receipt.id}
                )
                for table in ("audit_entries", "outbox_events")
            }
            assert all(v == 1 for v in counts.values())
            checks.append(
                {
                    "id": str(receipt.id),
                    "operation": receipt.operation,
                    "subject_id": str(receipt.subject_id),
                    **counts,
                }
            )
            if receipt.operation == "test.run.start":
                seed["start_receipt"] = {
                    "id": str(receipt.id),
                    "subject_id": str(receipt.subject_id),
                    "operation": receipt.operation,
                }
        effects = {
            table: s.scalar(
                text(f"SELECT count(*) FROM {table} WHERE run_id=:rid"), {"rid": seed["run_id"]}
            )
            for table in (
                "test_resource_reservations",
                "sample_run_usages",
                "verification_launch_facts",
            )
        }
        assert effects == {
            "test_resource_reservations": 1,
            "sample_run_usages": 1,
            "verification_launch_facts": 3,
        }
        model_calls = s.scalar(
            text(
                "SELECT count(*) FROM model_invocations i JOIN runs r ON "
                "r.tenant_id=i.tenant_id AND r.id=i.run_id WHERE r.product_id=:pid"
            ),
            {"pid": product},
        )
        assert model_calls == 0
        original_availability = s.execute(
            text("SELECT id,availability FROM sample_units WHERE build_id=:bid"),
            {"bid": seed["build_id"]},
        ).all()
        assert len(original_availability) == 2 and all(
            value == "unknown" for _, value in original_availability
        )
    verified(read_state())
    with engine_for(state["admin_url"]).connect() as s:
        tables = sorted(Base.metadata.tables)
        writes = [
            table
            for table in tables
            if s.scalar(
                text(
                    "SELECT has_table_privilege('pdos_agent',:tbl,'INSERT,UPDATE,DELETE,TRUNCATE')"
                ),
                {"tbl": table},
            )
        ]
        assert not writes and len(tables) == 91
        head = s.scalar(text("SELECT version_num FROM alembic_version"))
        assert head == "next_0018"
        protected = s.execute(
            text(
                "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class "
                "WHERE relname=ANY(:names)"
            ),
            {
                "names": [
                    "test_resource_facts",
                    "test_resource_current",
                    "test_resource_reservations",
                    "sample_usage_sentinels",
                    "sample_run_usages",
                    "verification_run_identities",
                    "verification_run_versions",
                    "verification_current_runs",
                    "verification_launch_facts",
                ]
            },
        ).all()
        assert len(protected) == 9 and all(enabled and forced for _, enabled, forced in protected)
    seed["phase"] = "run_started"
    SEED.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n")
    SEED.chmod(0o600)
    save(
        "actual-launch-check.json",
        {
            "result": "passed",
            "synthetic_only": True,
            "old_history": old_history,
            "run_versions": [
                {"revision": r["revision"], "status": r["status"]} for r in view["runs"]
            ],
            "request_versions": [
                {"revision": r["revision"], "status": r["status"]} for r in view["requests"]
            ],
            "receipts": checks,
            "effects": effects,
            "own_resource_occupancies": len(run["occupancy"]),
            "unaccepted_gaps_remain": True,
            "model_calls": model_calls,
            "sample_original_availability": "unknown",
            "future_results_and_disposal_null": True,
            "agent_direct_write_tables": writes,
            "business_tables": len(tables),
            "new_tables_forced_rls": 9,
            "schema_head": head,
            "real_qualification_or_exit_granted": False,
            "marker": state["marker"],
            "port": state["port"],
        },
    )
    print("Checked exact synthetic start effects, receipts, old history and permissions.")
else:
    raise RuntimeError("Unsupported checkpoint closeout action")
