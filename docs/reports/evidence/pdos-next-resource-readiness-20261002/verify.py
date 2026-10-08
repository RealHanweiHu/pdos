"""Reproduce only this package's synthetic checks; no database or shared service."""
import argparse
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = Path(__file__).resolve().parent
SERVER = ROOT / "pdos-next/server"
WEB = ROOT / "pdos-next/web"
PYTHON = SERVER / ".venv/bin/python"
RUFF = SERVER / ".venv/bin/ruff"
TARGETS = ["pdos_next/domain/resource_readiness", "pdos_next/schemas/resource_readiness",
           "tests/resource_readiness"]
ENV = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1")
CHECKS = [
    ("pytest", SERVER, [str(PYTHON), "-m", "pytest", "tests/resource_readiness",
     "--confcutdir=tests/resource_readiness", "-p", "no:cacheprovider", "-q"]),
    ("ruff", SERVER, [str(RUFF), "check", "--no-cache", *TARGETS]),
    ("format", SERVER, [str(RUFF), "format", "--no-cache", "--check", *TARGETS]),
    ("typecheck", WEB, [str(WEB / "node_modules/.bin/tsc"), "--project",
     "src/components/resource_readiness/tsconfig.check.json", "--noEmit", "--incremental", "false"]),
    ("eslint", WEB, [str(WEB / "node_modules/.bin/eslint"), "--no-cache",
     "src/components/resource_readiness"]),
    ("components", WEB, ["node", "--test", "src/components/resource_readiness/render.test.mjs"]),
]


def run(check):
    name, cwd, command = check
    result = subprocess.run(command, cwd=cwd, env=ENV, text=True, capture_output=True, check=False)
    (EVIDENCE / f"{name}.log").write_text(result.stdout + result.stderr)
    return {"name": name, "cwd": str(cwd.relative_to(ROOT)), "command": command,
            "exit_code": result.returncode, "log": f"{name}.log"}


parser = argparse.ArgumentParser()
parser.add_argument("--only", nargs="+", choices=[item[0] for item in CHECKS])
args = parser.parse_args()
selected = [item for item in CHECKS if not args.only or item[0] in args.only]
with ThreadPoolExecutor(max_workers=4) as pool:
    results = list(pool.map(run, selected))
if args.only:
    prior = json.loads((EVIDENCE / "checks.json").read_text())["checks"]
    latest = {item["name"]: item for item in results}
    results = [latest.get(item["name"], item) for item in prior]
(EVIDENCE / "checks.json").write_text(json.dumps({"scope": "exclusive synthetic package only",
    "checks": results, "all_passed": all(r["exit_code"] == 0 for r in results)}, indent=2) + "\n")
for result in results:
    print(result["name"], result["exit_code"])
    if result["exit_code"]:
        print((EVIDENCE / result["log"]).read_text())
raise SystemExit(0 if all(r["exit_code"] == 0 for r in results) else 1)
