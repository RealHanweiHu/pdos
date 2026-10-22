"""Run only this package's pure checks; save raw output without shared caches."""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parent
ROOT = EVIDENCE.parents[3]
SERVER = ROOT / "pdos-next/server"
SCOPES = ["pdos_next/engines/planning", "tests/planning_engine"]
CHECKS = {
    "ruff": [str(SERVER / ".venv/bin/ruff"), "check", "--no-cache", *SCOPES],
    "format": [
        str(SERVER / ".venv/bin/ruff"),
        "format",
        "--check",
        "--no-cache",
        *SCOPES,
    ],
    "pytest": [
        str(SERVER / ".venv/bin/python"),
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "--confcutdir=tests/planning_engine",
        "tests/planning_engine",
        "-q",
    ],
}
environment = dict(
    os.environ, PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
)
results = {}
for name, command in CHECKS.items():
    run = subprocess.run(
        command,
        cwd=SERVER,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log = EVIDENCE / f"{name}.log"
    log.write_text(run.stdout)
    results[name] = {
        "command": command,
        "cwd": str(SERVER),
        "returncode": run.returncode,
        "log": log.name,
    }
    print(f"{name}: {run.returncode}\n{run.stdout}")
summary = {
    "completed_at_utc": datetime.now(UTC).isoformat(),
    "python": sys.version,
    "isolation": "confcutdir; no pytest plugins, bytecode or shared caches",
    "results": results,
}
(EVIDENCE / "checks.json").write_text(json.dumps(summary, indent=2) + "\n")
sys.exit(0 if all(item["returncode"] == 0 for item in results.values()) else 1)
