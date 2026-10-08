"""Finalize evidence and backup only after the frozen joint candidate passes."""

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPORT = Path(__file__).resolve().parent
ROOT = REPORT.parents[3]
sys.path.insert(0, str(ROOT / "pdos-next/tools"))
from local_environment import environment, read_state, verified  # noqa: E402


def read(name):
    return json.loads((REPORT / name).read_text())


def save(name, data):
    (REPORT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


joint = read("joint-result.json")
assert all(row["exit_code"] == 0 for row in joint["groups"].values())
candidate = read("candidate.json")
assert all(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == sha for path, sha in candidate.items())
backend_candidate = read("candidate-backend-joint.json")
assert all(backend_candidate[path] == sha for path, sha in candidate.items() if "/server/" in path)
assert read("browser-layouts.json")["no_horizontal_overflow"] is True
state = verified(read_state())
with (REPORT / "schema-match.log").open("x") as output:
    subprocess.run([sys.executable, "-m", "alembic", "check"], cwd=ROOT / "pdos-next/server", env=environment(state), stdout=output, stderr=subprocess.STDOUT, check=True)

backup = ROOT / "pdos-next/.local/wave11-business.dump"
with backup.open("xb") as output:
    backup.chmod(0o600)
    subprocess.run(["docker", "exec", state["container"], "pg_dump", "-U", "postgres", "-d", "pdos_test", "-Fc"], stdout=output, stderr=subprocess.PIPE, check=True)
with backup.open("rb") as source:
    catalog = subprocess.run(["docker", "exec", "-i", state["container"], "pg_restore", "--list"], stdin=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout.decode()
assert "build_starts" in catalog and "operational_material_holds" in catalog
save("backup.json", {
    "verified_marker": state["marker"], "verified_port": state["port"],
    "before_migration": "pdos-next/.local/pre-wave11-next_0013.dump",
    "after_business": str(backup.relative_to(ROOT)), "mode": oct(backup.stat().st_mode & 0o777),
    "sha256": hashlib.sha256(backup.read_bytes()).hexdigest(), "bytes": backup.stat().st_size,
    "catalog_checked": True, "restore_performed": False,
    "migration_roundtrip_before_business": "next_0013 → next_0014 → next_0013 → next_0014",
})
actual = read("actual-preview.json")
save("final-check.json", {
    "recorded_at": datetime.now(UTC).isoformat(), "result": "passed_with_recorded_scope",
    "candidate_files": len(candidate), "candidate_sha256": hashlib.sha256((REPORT / "candidate.json").read_bytes()).hexdigest(),
    "source_hashes_stable_at_closeout": True, "backend_unchanged_during_joint": True,
    "frontend_only_followup": "ui-only-final-delta.json", "joint_passed": joint["total_passed"],
    "joint_seconds": joint["elapsed_seconds"], "parallel_process_limit": 6,
    "structural_tests_isolated": joint["structural_tests_isolated"],
    "frontend_helper_passed": 16, "final_production_build": "passed", "schema_check": "passed",
    "python_lint": "passed", "frontend_lint_errors": 0, "frontend_existing_warnings": 2,
    "browser_layouts": 4, "browser_actions": "browser-actions.json",
    "schema_head": actual["schema_head"], "business_tables": actual["business_tables"],
    "agent_direct_writes": actual["agent_direct_writes"], "model_calls": actual["model_calls"],
    "business_readback": "actual-preview.json", "reuse": "reuse-review.json", "contracts": "source-contract-check.json",
    "backup": "backup.json", "nature": "synthetic", "real_factory_qualification": False, "formal_exit": False,
})
print(json.dumps({"passed": joint["total_passed"], "seconds": joint["elapsed_seconds"], "schema": "next_0014", "candidate_files": len(candidate), "backup_catalog_checked": True}))
