"""Root-only frozen affected pure checks; no database or business commands."""

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
REPORT = REPO / "docs/reports/evidence/pdos-next-wave21-20261003"
PREVIOUS = REPO / "docs/reports/evidence/pdos-next-wave20-20261003/candidate-source-v3.json"
NEW_TESTS = (
    "pdos-next/server/tests/test_operational_bootstrap_profiles.py",
    "pdos-next/server/tests/test_test_resource_bootstrap_profiles.py",
    "pdos-next/server/tests/test_quality_bootstrap_profiles.py",
    "pdos-next/server/tests/quality_followup_root/test_completion_profiles.py",
    "pdos-next/server/tests/professional_authority/test_profiles.py",
    "pdos-next/server/tests/capa_effectiveness/test_rule_publisher_profiles.py",
    "pdos-next/server/tests/test_host_profile_choices.py",
    "pdos-next/tools/tests/test_local_host_profiles.py",
)
COMPATIBILITY = (
    "pdos-next/server/tests/professional_authority/test_assessment.py",
    "pdos-next/server/tests/quality_followup_bootstrap/test_pure.py",
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source():
    previous = json.loads(PREVIOUS.read_text())
    selected = sorted(set(previous["backend_test_files"]) | set(NEW_TESTS) | set(COMPATIBILITY))
    return {
        "schema_version": "pdos-next-wave21-frozen-candidate-v1",
        "previous_checkpoint": "../pdos-next-wave20-20261003/final-checkpoint-v1.json",
        "previous_manifest_sha256": sha(PREVIOUS),
        "runtime_files": {name: sha(REPO / name) for name in previous["runtime_files"]},
        "backend_test_files": {name: sha(REPO / name) for name in selected},
        "web_files": {name: sha(REPO / name) for name in previous["web_files"]},
        "tools": {
            name: sha(REPO / name)
            for name in (
                "pdos-next/tools/local_environment.py",
                "pdos-next/tools/wave21_check.py",
                "pdos-next/tools/wave21_host_readback.py",
            )
        },
    }


def main():
    if len(sys.argv) not in {2, 3} or sys.argv[1] != "run":
        raise RuntimeError("Explicit Root check required")
    tag = sys.argv[2] if len(sys.argv) == 3 else "v1"
    if not tag.startswith("v") or not tag[1:].isdigit():
        raise RuntimeError("A fresh numbered evidence tag is required")
    manifest = REPORT / f"candidate-source-{tag}.json"
    result_path = REPORT / f"affected-check-result-{tag}.json"
    if manifest.exists() or result_path.exists():
        raise RuntimeError("Frozen evidence must not be overwritten")
    frozen = source()
    manifest.write_text(json.dumps(frozen, indent=2) + "\n")
    previous = json.loads(PREVIOUS.read_text())
    assert frozen["web_files"] == previous["web_files"]
    selected = tuple(frozen["backend_test_files"])
    env = os.environ.copy()
    for key in ("DATABASE_URL", "TEST_DATABASE_URL", "PDOS_DATABASE_URL", "PDOS_AUTH_DATABASE_URL"):
        env.pop(key, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        str(ROOT / name)
        for name in ("server", "server/tests", "server/tests/capa_effectiveness", "tools")
    )
    argv = [sys.executable, "-m", "pytest", "--noconftest", "-q", "-o", "pythonpath=", *selected]
    log = REPORT / f"affected-pure-{tag}.log"
    with log.open("x") as output:
        process = subprocess.run(argv, cwd=REPO, env=env, stdout=output, stderr=subprocess.STDOUT)
    result = {
        "status": "PASS" if process.returncode == 0 and frozen == source() else "FAIL",
        "recorded_at": datetime.now(UTC).isoformat(),
        "scope": "Deduplicated affected pure selection; no conftest, DB, HTTP or business proof",
        "argv": argv,
        "selected_files": len(selected),
        "exit_code": process.returncode,
        "source_unchanged": frozen == source(),
        "manifest_sha256": sha(manifest),
        "log_sha256": sha(log),
        "web_unchanged_from_wave20_v3": frozen["web_files"] == previous["web_files"],
        "business_commands": 0,
        "model_calls": 0,
    }
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "report": str(result_path)}))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
