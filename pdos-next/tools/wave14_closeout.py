"""Read-only checkpoint evidence for the owned synthetic Wave13/14 business chain."""

import hashlib
import json
import sys
from uuid import UUID

import httpx
from local_environment import ROOT, read_state, verified
from pdos_next.database import engine_for, tenant_session
from pdos_next.domain.verification_launch import service as launch
from pdos_next.domain.verification_launch.models import VerificationRunVersion
from pdos_next.models import Base, Receipt
from pdos_next.service import digest
from sqlalchemy import select, text

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave14-20261002"


def save(name, value):
    path = REPORT / name
    with path.open("x") as output:
        output.write(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def source_manifest():
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
        str(path.relative_to(ROOT.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(ROOT.rglob("*"))
        if path.is_file()
        and not ignored.intersection(path.parts)
        and path.suffix not in {".pyc", ".tsbuildinfo"}
    }


action = sys.argv[1]
if action == "freeze":
    prior = json.loads((REPORT / "candidate-final-source.json").read_text())["files"]
    files = source_manifest()
    changed = [
        name for name in sorted(prior.keys() | files.keys()) if prior.get(name) != files.get(name)
    ]
    save(
        "candidate-final-v3-source.json",
        {
            "files": files,
            "file_count": len(files),
            "head": "next_0022",
            "changes_from_intermediate": changed,
            "verification_scope": (
                "Impact selection and exact synthetic business closure; not whole-system Exit."
            ),
        },
    )
    print(f"Frozen {len(files)} source files; {len(changed)} deltas from intermediate candidate.")
elif action == "business":
    state = verified(read_state())
    prior = json.loads((ROOT / ".local/wave13-seed.json").read_text())
    seed = json.loads((ROOT / ".local/wave14-seed.json").read_text())
    tenant, product = UUID(state["preview_tenant_id"]), UUID(state["preview_product_id"])
    run_id = UUID(prior["run_id"])
    engine = engine_for(state["app_url"])
    with httpx.Client(
        base_url="http://127.0.0.1:8898",
        trust_env=False,
        timeout=180,
        headers={"Authorization": "Bearer " + state["preview_token"]},
    ) as client:
        verified(read_state())
        response = client.get(
            f"/v1/products/{product}/verification-results", params={"build_id": prior["build_id"]}
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Current business read unavailable ({response.status_code}); no write attempted"
            )
        view = response.json()
    save("actual-final-results-read.json", view)
    run_pointer = view["current_by_run"][str(run_id)]
    request_pointer = view["current_by_request"][prior["request_id"]]
    run = next(row for row in view["runs"] if row["id"] == run_pointer["run_version_id"])
    request = next(
        row for row in view["requests"] if row["id"] == request_pointer["request_version_id"]
    )
    assert (run["revision"], run["status"], run["result"]) == (6, "disposed", "indeterminate")
    assert (request["revision"], request["status"]) == (9, "executing")
    assert request["coverage_gaps"] and len(run["run_snapshot"]["coverage"]) == 1
    assert len(run["run_snapshot"]["measurements"]) == 1
    assert run["run_snapshot"]["measurements"][0]["raw_value"] == "  10.0  "
    fixed = json.loads((REPORT / "after-professional-events.json").read_text())
    fixed_row = next(row for row in fixed["runs"] if row["revision"] == 4)
    before = fixed_row["run_snapshot"]
    after = run["run_snapshot"]
    for key in (
        "actual_start",
        "actual_end",
        "preliminary_result",
        "final_result",
        "coverage",
        "measurements",
        "computed_results",
        "execution",
    ):
        assert after[key] == before[key], key
    assert after["professional_conclusion"] and after["disposition"]
    verified(read_state())
    with tenant_session(engine, tenant) as session:
        original = session.scalar(
            select(VerificationRunVersion).where(
                VerificationRunVersion.run_id == run_id, VerificationRunVersion.revision == 2
            )
        )
        original_run, original_plan = launch._snapshot(original)
        assert original.snapshot_sha256 == seed["original_start"]["sha256"]
        original_sha256 = original.snapshot_sha256
        assert original.intent_digest == seed["original_start"]["start_intent"]
        assert original_run.execution.model_dump(mode="json") == after["execution"]
        history = {}
        baseline = json.loads(
            (
                ROOT.parent
                / "docs/reports/evidence/pdos-next-wave13-20261002/old-business-manifest.json"
            ).read_text()
        )
        for table, rows in baseline.items():
            current = {
                str(identity): digest(value)
                for identity, value in session.execute(
                    text(f"SELECT id, to_jsonb(t) FROM {table} t")
                )
            }
            assert all(current.get(identity) == checksum for identity, checksum in rows.items()), (
                table
            )
            history[table] = {"exact_old_rows": len(rows), "unchanged": True}
        counts = {
            table: session.scalar(
                text(f"SELECT count(*) FROM {table} WHERE run_id=:rid"), {"rid": run_id}
            )
            for table in (
                "test_resource_reservations",
                "sample_run_usages",
                "test_measurements",
                "test_result_projections",
                "test_result_actions",
            )
        }
        counts["operational_resource_occupancies"] = session.scalar(
            text("SELECT count(*) FROM operational_resource_occupancies WHERE test_run_id=:rid"),
            {"rid": run_id},
        )
        assert counts == {
            "test_resource_reservations": 1,
            "sample_run_usages": 1,
            "test_measurements": 1,
            "test_result_projections": 2,
            "test_result_actions": 4,
            "operational_resource_occupancies": 2,
        }
        receipts = session.scalars(
            select(Receipt).where(
                Receipt.product_id == product,
                Receipt.operation.in_(
                    (
                        "test.results.import",
                        "test.result.compute",
                        "test.run.review",
                        "test.disposition.decide",
                    )
                ),
            )
        ).all()
        assert len(receipts) == 5
        receipt_checks = []
        for receipt in receipts:
            linked = {
                table: session.scalar(
                    text(f"SELECT count(*) FROM {table} WHERE receipt_id=:id"), {"id": receipt.id}
                )
                for table in ("audit_entries", "outbox_events")
            }
            assert all(value == 1 for value in linked.values())
            receipt_checks.append(
                {
                    "id": str(receipt.id),
                    "operation": receipt.operation,
                    "subject_id": str(receipt.subject_id),
                    **linked,
                }
            )
        model_calls = session.scalar(
            text(
                "SELECT count(*) FROM model_invocations i JOIN runs r ON "
                "r.tenant_id=i.tenant_id AND r.id=i.run_id WHERE r.product_id=:pid"
            ),
            {"pid": product},
        )
        assert model_calls == 0
    verified(read_state())
    with engine_for(state["admin_url"]).connect() as connection:
        tables = sorted(Base.metadata.tables)
        agent_writes = [
            table
            for table in tables
            if connection.scalar(
                text(
                    "SELECT has_table_privilege('pdos_agent',:tbl,'INSERT,UPDATE,DELETE,TRUNCATE')"
                ),
                {"tbl": table},
            )
        ]
        head = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert head == "next_0022" and len(tables) == 95 and not agent_writes
        rls = connection.execute(
            text(
                "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class "
                "WHERE relname=ANY(:names)"
            ),
            {
                "names": [
                    "measurement_import_captures",
                    "test_measurements",
                    "test_result_projections",
                    "test_result_actions",
                ]
            },
        ).all()
        assert len(rls) == 4 and all(enabled and forced for _, enabled, forced in rls)
    save(
        "actual-result-closure.json",
        {
            "passed": True,
            "synthetic_only": True,
            "run_revision": 6,
            "request_revision": 9,
            "result": "indeterminate",
            "request_gaps_retained": True,
            "original_start_sha256": original_sha256,
            "fixed_result_basis_unchanged": True,
            "exact_old_history": history,
            "counts": counts,
            "receipts": receipt_checks,
            "model_calls": model_calls,
            "schema_head": head,
            "business_tables": len(tables),
            "agent_direct_writes": agent_writes,
            "forced_rls": [row[0] for row in rls],
            "port": state["port"],
            "marker": state["marker"],
        },
    )
    print(
        "Synthetic original-value, separate review/disposition, "
        "unchanged execution/history and protected schema verified."
    )
else:
    raise RuntimeError("Unknown read-only closeout action")
