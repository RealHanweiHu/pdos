"""Isolated owned-package checks; records real exit codes, no dependencies installed."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = Path(__file__).resolve().parent
SERVER = ROOT / "pdos-next/server"
WEB = ROOT / "pdos-next/web"
ENV = {"PATH": "/opt/homebrew/bin:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1",
       "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
CHECKS = [
    ("ruff", SERVER, [str(SERVER / ".venv/bin/ruff"), "check", "--no-cache",
        "pdos_next/model_configuration", "pdos_next/schemas/model_configuration",
        "tests/model_configuration"]),
    ("pytest", SERVER, [str(SERVER / ".venv/bin/python"), "-m", "pytest",
        "tests/model_configuration", "--confcutdir=tests/model_configuration",
        "-p", "no:cacheprovider", "-q"]),
    ("typescript", WEB, [str(WEB / "node_modules/.bin/tsc"), "--project",
        "src/components/model_configuration/tsconfig.check.json", "--incremental", "false",
        "--noEmit"]),
    ("eslint", WEB, [str(WEB / "node_modules/.bin/eslint"),
        "src/components/model_configuration"]),
    ("component", WEB, ["node", "--test",
        "src/components/model_configuration/render.test.mjs"]),
]
selected = set(sys.argv[1:])
previous = json.loads((EVIDENCE / "checks.json").read_text()) if selected else []
results = [row for row in previous if row["check"] not in selected]
for name, cwd, command in CHECKS:
    if selected and name not in selected:
        continue
    completed = subprocess.run(command, cwd=cwd, env=ENV, capture_output=True, text=True)
    (EVIDENCE / f"{name}.log").write_text(completed.stdout + completed.stderr)
    result = {"check": name, "cwd": str(cwd), "command": command,
              "exit_code": completed.returncode}
    results.append(result)
    print(f"{name}: {completed.returncode}")
    if completed.returncode:
        print(completed.stdout + completed.stderr)
(EVIDENCE / "checks.json").write_text(json.dumps(results, indent=2) + "\n")
raise SystemExit(any(result["exit_code"] for result in results))
