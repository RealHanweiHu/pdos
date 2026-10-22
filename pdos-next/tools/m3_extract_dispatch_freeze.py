"""Freeze the extract-dispatch segment sources: per-file sha256 manifest, no credentials."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / os.environ.get(
    "M3_SEGMENT_REPORT",
    "docs/reports/evidence/pdos-next-m3-20261010/extract-dispatch",
)

INCLUDE_TOP = ("docs/design", "pdos-next", "packages", "tasks")
PRUNE_DIRS = {
    ".git",
    ".local",
    ".next",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}
PRUNE_PREFIXES = ("docs/reports",)  # evidence is output, never source
PRUNE_FILES = {".env"}  # credentials are never source


def main():
    entries = {}
    for top in INCLUDE_TOP:
        base = ROOT / top
        if not base.exists():
            continue
        for current, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in PRUNE_DIRS)
            for name in sorted(files):
                path = Path(current) / name
                rel = path.relative_to(ROOT).as_posix()
                if rel.startswith(PRUNE_PREFIXES) or name in PRUNE_FILES:
                    continue
                entries[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    head = os.environ.get(
        "M3_SEGMENT_PREDECESSOR",
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip(),
    )
    manifest = {
        "user_date": "2026-10-13",
        "baseline_commit": "0eccfe0376d387de7a5211c2852f50f2432ca7b4",
        "source_digest_algorithm": "sha256(canonical JSON sorted keys, separators comma/colon, UTF-8)",
        "excluded": [
            "private local state",
            "virtual environments",
            "evidence",
            "node_modules and generated build/browser outputs",
            "credential files",
        ],
        "schema_head": "s0_0757",
        "predecessor_m3_commit": head,
        "source_count": len(entries),
        "source_digest": hashlib.sha256(
            json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "source_sha256": entries,
    }
    REPORT.mkdir(parents=True, exist_ok=True)
    target = REPORT / "source-manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")
    print(f"frozen {len(entries)} sources -> {target}")


if __name__ == "__main__":
    main()
