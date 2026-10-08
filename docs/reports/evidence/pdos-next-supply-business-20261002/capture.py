"""Explicit file-only evidence capture; no env, database, service or credential reads."""

import ast
import hashlib
import json
import sys
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parent
ROOT = EVIDENCE.parents[3]
OWNED = (
    "pdos-next/server/pdos_next/domain/supply_cost",
    "pdos-next/server/pdos_next/schemas/supply_cost",
    "pdos-next/server/tests/supply_cost_domain",
    "pdos-next/web/src/components/supply_cost",
)
INITIAL = json.loads((EVIDENCE / "consumed-initial.json").read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, value):
    (EVIDENCE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def candidate():
    rows = [
        {"path": str(path.relative_to(ROOT)), "sha256": sha(path)}
        for folder in OWNED
        for path in sorted((ROOT / folder).rglob("*"))
        if path.is_file() and path.suffix in {".py", ".ts", ".tsx"}
    ]
    aggregate = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {"candidate_sha256": aggregate, "files": rows}


def audit():
    imports = []
    for row in candidate()["files"]:
        if not row["path"].endswith(".py"):
            continue
        tree = ast.parse((ROOT / row["path"]).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend({"file": row["path"], "module": alias.name} for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append({"file": row["path"], "module": node.module or ""})
    forbidden = [
        row
        for row in imports
        if row["module"].startswith(
            (
                "app",
                "sqlalchemy",
                "psycopg",
                "dotenv",
                "httpx",
                "requests",
                "boto3",
                "pdos_next.models",
                "pdos_next.service",
                "pdos_next.api",
                "pdos_next.runtime",
            )
        )
    ]
    return {"imports": imports, "forbidden": forbidden, "passed": not forbidden}


if "--verify" in sys.argv:
    old = json.loads((EVIDENCE / "candidate.json").read_text())
    now = candidate()
    ok = old == now
    write(
        "final-consistency.json",
        {"candidate_unchanged": ok, "candidate_sha256": now["candidate_sha256"]},
    )
    print(json.dumps({"candidate_unchanged": ok, "files": len(now["files"])}))
    raise SystemExit(0 if ok else 1)
else:
    value = candidate()
    write("candidate.json", value)
    write("import-audit.json", audit())
    rows = [
        {"path": path, "initial_sha256": initial, "candidate_sha256": sha(ROOT / path)}
        for path, initial in INITIAL.items()
    ]
    write(
        "consumed-summary.json",
        {
            "initial_observation": "First focused source read in this package",
            "files": rows,
            "drifted": [
                row["path"] for row in rows if row["initial_sha256"] != row["candidate_sha256"]
            ],
            "interface": "BuildDemandPort not wired; imports alone are not a frozen interface",
            "old_app_reuse": "None; prior new-engine implementation is read-only reused",
        },
    )
    print(json.dumps({"candidate": value["candidate_sha256"], "files": len(value["files"])}))
