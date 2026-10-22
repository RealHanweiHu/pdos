"""Run only owned pure-kernel checks, preserving raw logs in this evidence directory."""

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

evidence = Path(__file__).resolve().parent
root = evidence.parents[3]
server = root / "pdos-next/server"
env = dict(os.environ)
env["PYTHONDONTWRITEBYTECODE"] = "1"
env.pop("TEST_DATABASE_URL", None)
env.pop("DATABASE_URL", None)
commands = {
    "cold-import": [
        sys.executable, "-B", "-c",
        "import sys; from pdos_next.engines.derivation import three_way, accept_changes; "
        "assert not any(n == 'app' or n.startswith('app.') or n in "
        "{'pdos_next.models','pdos_next.service','pdos_next.api','pdos_next.runtime','sqlalchemy'} "
        "for n in sys.modules); print('Independent import passed; no business/runtime/database modules')",
    ],
    "pytest": [
        sys.executable, "-B", "-m", "pytest", "tests/derivation_engine",
        "--confcutdir=tests/derivation_engine",
        "-o", f"cache_dir={evidence / '.pytest-cache'}", "-q",
    ],
    "ruff": [
        str(server / ".venv/bin/ruff"), "check", "--no-cache",
        "pdos_next/engines/derivation", "tests/derivation_engine",
    ],
    "format": [
        str(server / ".venv/bin/ruff"), "format", "--check", "--no-cache",
        "pdos_next/engines/derivation", "tests/derivation_engine",
    ],
}
owned = sorted(
    (root / "pdos-next/server/pdos_next/engines/derivation").glob("*.py")
) + sorted((root / "pdos-next/server/tests/derivation_engine").glob("*.py"))
dependencies = [
    root / "pdos-next/server/pdos_next/contracts.py",
    root / "pdos-next/server/pdos_next/schemas/products/definitions.py",
]


def fingerprints(paths):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


before = fingerprints(owned + dependencies)
results = []
for name, command in commands.items():
    result = subprocess.run(command, cwd=server, env=env, capture_output=True, text=True)
    (evidence / f"{name}.log").write_text(result.stdout + result.stderr)
    results.append({"name": name, "command": command, "exit_code": result.returncode})
    print(f"{name}: exit {result.returncode}\n{result.stdout}{result.stderr}")
(evidence / "verification.json").write_text(json.dumps(results, indent=2) + "\n")
after = fingerprints(owned + dependencies)
stable = before == after
candidate = {
    "schema_version": "derivation.v1",
    "owned_files": fingerprints(owned),
    "public_type_dependencies": fingerprints(dependencies),
    "stable_during_checks": stable,
    "candidate_sha256": hashlib.sha256(json.dumps(
        fingerprints(owned), sort_keys=True
    ).encode()).hexdigest(),
    "database_fixtures": "excluded by --confcutdir; no TEST_DATABASE_URL",
    "checks": results,
}
(evidence / "candidate.json").write_text(json.dumps(candidate, indent=2) + "\n")
source = root / "server/app/domain/definition_inheritance.py"
raw = source.read_bytes()
lines = raw.decode().splitlines(keepends=True)
functions = []
for node in ast.parse(raw).body:
    if isinstance(node, ast.FunctionDef) and node.name in {
        "merge_paths", "three_way", "accept_changes"
    }:
        segment = "".join(lines[node.lineno - 1:node.end_lineno]).encode()
        functions.append({
            "function": node.name, "line": node.lineno,
            "sha256": hashlib.sha256(segment).hexdigest(),
        })
references = [
    root / "pdos-next/server/pdos_next/domain/products/definitions.py",
    root / "pdos-next/web/src/lib/product-view.ts",
    root / "docs/design/2026-10-02-pdos-complete-target-architecture-v1.md",
    root / "docs/design/2026-10-02-pdos-next-execution-plan.md",
    root / "docs/design/2026-10-02-pdos-next-reuse-and-parallel-plan.md",
]
summary = {
    "source_file": str(source.relative_to(root)),
    "source_sha256": hashlib.sha256(raw).hexdigest(),
    "extracted_functions": functions,
    "extraction": "Stable-key path projection, three-way comparison, selective copy semantics; "
                  "rebuilt for specs/key and typed Decimal snapshots, not imported from old app",
    "adaptation_references": fingerprints(references),
}
(evidence / "source-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(f"Candidate {candidate['candidate_sha256']}; stable during checks: {stable}")
sys.exit(1 if any(row["exit_code"] for row in results) or not stable else 0)
