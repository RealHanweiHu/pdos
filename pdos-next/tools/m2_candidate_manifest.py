"""Freeze reproducible independent M2 source/evidence hashes, without credentials."""

import hashlib
import json
import re

from m2_verify import REPORT, ROOT
from pdos_next.agent_kernel.tools import default_registry


def entry(path):
    raw = path.read_bytes()
    return {
        "path": str(path.relative_to(ROOT)), "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def main():
    previous = json.loads((REPORT / "candidate-manifest.json").read_text())
    paths = {ROOT / item["path"] for item in previous["owned_sources"]}
    for folder in (
        "packages/pdos-agent-runtime/src", "pdos-next/server/pdos_next/agent_kernel",
        "pdos-next/server/pdos_next/research", "pdos-next/server/pdos_next/providers",
        "pdos-next/server/pdos_next/model_configuration", "pdos-next/server/tests/agent_kernel",
    ):
        paths.update((ROOT / folder).rglob("*.py"))
    for folder, pattern in (
        ("pdos-next/tools", "m2_*.py"),
        ("pdos-next/server/migrations", "schema_s0_07*.py"),
        ("pdos-next/server/migrations/versions", "s0_07*.py"),
        ("pdos-next/server/pdos_next/skill_packages", "*.md"),
    ):
        paths.update((ROOT / folder).glob(pattern))
    owned = [entry(p) for p in sorted(paths) if p.exists() and "__pycache__" not in p.parts]
    regression = re.search(
        r"(\d+) passed, (\d+) deselected in ([\d.]+)s", (REPORT / "kernel-final.log").read_text()
    )
    final_line = (REPORT / "kernel-final.log").read_text().splitlines()[-1]
    if regression is None or "failed" in final_line:
        raise RuntimeError("Final independent candidate regression did not pass")
    registry = default_registry()
    footprint = {
        "tools": len(registry.definitions()),
        "definition_utf8_bytes": len(
            json.dumps(registry.definitions(), ensure_ascii=False).encode()
        ),
        "registry_version": registry.version,
        "research_child_tools": len(registry.definitions("research")),
    }
    shared_paths = {ROOT / r["path"] for r in previous["shared_dependencies_observed_after_check"]}
    shared_paths.update(ROOT / path for path in (
        "pdos-next/server/pdos_next/run_revert.py", "pdos-next/server/pdos_next/category_scope.py",
        "pdos-next/server/pdos_next/api.py", "pdos-next/server/pyproject.toml",
        "pdos-next/server/uv.lock",
        "pdos-next/server/migrations/schema_s0_0406.py",
        "pdos-next/server/migrations/schema_s0_0407.py",
        "pdos-next/server/migrations/schema_s0_0408.py",
        "pdos-next/server/migrations/schema_s0_0409.py",
    ))
    manifest = {
        "candidate": "M2 independent synthetic, 2026-10-08",
        "migration_head": "s0_0715",
        "owned_source_digest": hashlib.sha256(
            json.dumps(owned, sort_keys=True).encode()
        ).hexdigest(),
        "owned_sources": owned,
        "shared_dependencies_observed_after_check": [
            entry(p) for p in sorted(shared_paths) if p.exists()
        ],
        "shared_fixture_copy": json.loads((REPORT / "common-fixture-sync.json").read_text()),
        "regression": {
            "passed": int(regression[1]), "deselected": int(regression[2]),
            "seconds": float(regression[3]),
            "log": "kernel-final.log", "selection": previous["regression"]["selection"],
        },
        "m2_owned_table_count": 12,
        "root_receipt_fk_installed_validated": True,
        "real_model_calls": 0,
        "public_http_temporal_join_passed": False,
        "public_human_run_revert_http_fixture_passed": True,
        "actual_model_qualification_passed": False,
        "tool_footprint": footprint,
    }
    (REPORT / "candidate-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    (REPORT / "tool-footprint.json").write_text(json.dumps(footprint, indent=2) + "\n")
    print(f"M2 candidate manifest recorded: {len(owned)} owned source files, credentials withheld.")


if __name__ == "__main__":
    main()
