"""Freeze this package and its read-only extraction provenance; no shared changes."""

import ast
import hashlib
import json
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parent
ROOT = EVIDENCE.parents[3]
ENGINE = ROOT / "pdos-next/server/pdos_next/engines/planning"
TESTS = ROOT / "pdos-next/server/tests/planning_engine"
SOURCES = {
    "server/app/domain/working_time.py": [
        "ceil_minute",
        "minute_quantity",
        "WorkingTime",
    ],
    "server/app/domain/plan_scheduling.py": ["_schedule_plan", "schedule_plan"],
    "server/app/domain/schedule_forecast_engine.py": [
        "calculate_forecast",
        "_calculate",
    ],
    "server/app/domain/work_calendars.py": ["_zone_rules"],
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


source_summary = []
for relative, symbols in SOURCES.items():
    data = (ROOT / relative).read_bytes()
    content = data.decode()
    tree = ast.parse(content)
    selected = []
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.ClassDef)) and item.name in symbols:
            selected.append(
                {
                    "symbol": item.name,
                    "line": item.lineno,
                    "end_line": item.end_lineno,
                    "sha256": sha(ast.get_source_segment(content, item).encode()),
                }
            )
    assert len(selected) == len(symbols)
    source_summary.append(
        {
            "path": relative,
            "file_sha256": sha(data),
            "symbols": selected,
            "reuse": "Deterministic algorithm adapted to independent DTO v1",
        }
    )
(EVIDENCE / "source-summary.json").write_text(
    json.dumps(source_summary, indent=2) + "\n"
)

allowed_imports = {
    "__future__",
    "collections",
    "datetime",
    "decimal",
    "hashlib",
    "heapq",
    "importlib",
    "io",
    "json",
    "pathlib",
    "typing",
    "zoneinfo",
    "pydantic",
}
boundary = []
for path in sorted(ENGINE.glob("*.py")):
    for item in ast.walk(ast.parse(path.read_text())):
        if isinstance(item, ast.Import):
            imports = [name.name for name in item.names]
        elif isinstance(item, ast.ImportFrom) and item.level == 0:
            imports = [item.module or ""]
        else:
            continue
        for name in imports:
            assert name.split(".")[0] in allowed_imports, (
                f"Unexpected engine import {name}"
            )
    boundary.append(str(path.relative_to(ROOT)))
(EVIDENCE / "import-boundary.json").write_text(
    json.dumps(
        {
            "allowed_external_roots": sorted(allowed_imports),
            "checked_files": boundary,
            "legacy_or_business_imports": [],
            "status": "passed",
        },
        indent=2,
    )
    + "\n"
)

files = sorted(
    list(ENGINE.glob("*.py"))
    + list(TESTS.glob("*.py"))
    + [
        EVIDENCE / "verify.py",
        EVIDENCE / "example.py",
        EVIDENCE / "freeze.py",
        EVIDENCE / "result.md",
        EVIDENCE / "example.json",
        EVIDENCE / "checks.json",
        EVIDENCE / "source-summary.json",
        EVIDENCE / "import-boundary.json",
        EVIDENCE / "ruff.log",
        EVIDENCE / "format.log",
        EVIDENCE / "pytest.log",
    ]
)
entries = [
    {"path": str(path.relative_to(ROOT)), "sha256": sha(path.read_bytes())}
    for path in files
]
manifest = {
    "algorithm_version": "planning.minute_forecast.v1",
    "dto_version": "planning.v1",
    "package_candidate_sha256": sha(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    ),
    "files": entries,
    "scope": "Pure algorithms; no database, business writes, model calls, UI, migration or stage Exit",
}
(EVIDENCE / "candidate-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(f"Import boundary passed; {len(entries)} files frozen")
print(f"Package candidate SHA-256: {manifest['package_candidate_sha256']}")
