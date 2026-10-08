"""Root-selected Wave16 PG cases; independently seeded tenants run concurrently."""

import concurrent.futures
import hashlib
import json
import subprocess
import sys
import time

from local_environment import ROOT, SERVER, environment, read_state, verified

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave16-20261002"
SAVEPOINT = (
    "tests/quality_followup_root/test_savepoint.py::"
    "test_actual_followup_savepoint_commits_and_orphan_consumption_rolls_back"
)
EXPIRED_RECOVERY = (
    "tests/quality_followup_root/test_expired_recovery.py::"
    "test_expired_followup_proof_has_bound_no_saved_repreview_and_saved_replay"
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    with (REPORT / name).open("x") as output:
        json.dump(value, output, indent=2)
        output.write("\n")


def source_files():
    paths = [SERVER / "alembic.ini", SERVER / "pyproject.toml"]
    for directory in ("pdos_next", "migrations", "tests"):
        paths.extend((SERVER / directory).rglob("*.py"))
    return {
        str(path.relative_to(ROOT.parent)): sha(path)
        for path in sorted(set(paths))
        if path.is_file()
    }


def main():
    if len(sys.argv) not in {2, 3} or sys.argv[1] not in {"freeze", "priority", "remaining", "pg"}:
        raise RuntimeError("Explicit Wave16 source or case selection required")
    tag = sys.argv[2] if len(sys.argv) == 3 else ""
    if tag and (not tag.startswith("v") or not tag[1:].isdigit()):
        raise RuntimeError("Candidate tag must be an explicit numbered revision")
    suffix = "-" + tag if tag else ""
    candidate = REPORT / ("backend-candidate-source" + suffix + ".json")
    if sys.argv[1] == "freeze":
        save(
            candidate.name,
            {
                "head": "next_0025",
                "files": source_files(),
                "scope": "Wave16 source identity; selected validation, no full-tree claim",
            },
        )
        print("Wave16 backend source candidate saved")
        return
    frozen = json.loads(candidate.read_text())
    if source_files() != frozen["files"]:
        raise RuntimeError("Wave16 candidate no longer matches actual sources")
    selection = json.loads((REPORT / "quality-followup-transaction-selection.json").read_text())
    all_nodes = selection["nodes"]
    first = selection["root_first_selection"] + [SAVEPOINT, EXPIRED_RECOVERY]
    if len(all_nodes) != 18 or len(set(all_nodes)) != 18 or SAVEPOINT in all_nodes:
        raise RuntimeError("Unexpected exact transaction selection")
    ordered = first + [node for node in all_nodes if node not in first]
    mode = sys.argv[1]
    if mode == "priority":
        ordered = first
    elif mode == "remaining":
        ordered = [node for node in ordered if node not in first]
    save(
        mode + suffix + "-selection.json",
        {
            "nodes": ordered,
            "candidate": candidate.name,
            "candidate_sha256": sha(candidate),
            "upstream_selection_sha256": sha(
                REPORT / "quality-followup-transaction-selection.json"
            ),
            "concurrency": 6,
        },
    )

    def run(item):
        number, node = item
        state = verified(read_state())
        if state["port"] != 62513 or state["marker"] != "916f950f-2d2b-405d-b809-c15db75dc20c":
            raise RuntimeError("Unexpected marked Wave16 test target")
        from pdos_next.database import engine_for
        from sqlalchemy import text

        engine = engine_for(state["admin_url"])
        with engine.connect() as connection:
            if connection.scalar(text("SELECT version_num FROM alembic_version")) != "next_0025":
                raise RuntimeError("Actual Wave16 migration head required")
        engine.dispose()
        key = f"{mode}{suffix}-{number:02}"
        start = time.monotonic()
        with (REPORT / (key + ".log")).open("x") as output:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-rA", "--tb=short", node],
                cwd=SERVER,
                env=environment(state),
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        value = {
            "node": node,
            "exit_code": result.returncode,
            "seconds": round(time.monotonic() - start, 2),
            "source_stable": source_files() == frozen["files"],
            "candidate_sha256": sha(candidate),
            "log_file": key + ".log",
            "log_sha256": sha(REPORT / (key + ".log")),
        }
        save(key + "-result.json", value)
        print(key, result.returncode, "source_stable", value["source_stable"], flush=True)
        return key, value

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        pending = [pool.submit(run, item) for item in enumerate(ordered)]
        for future in concurrent.futures.as_completed(pending):
            key, value = future.result()
            results[key] = value
    save(mode + suffix + "-result.json", results)
    if any(value["exit_code"] or not value["source_stable"] for value in results.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
