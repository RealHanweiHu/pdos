"""Root-only replacement selection for the stopped Wave16 v3 transaction run."""

import concurrent.futures
import json
import subprocess
import sys
import time

from local_environment import SERVER, environment, read_state, verified
from wave16_check import REPORT, save, sha, source_files

TAG = "v4"
INDICES = (1, 8, 13, 14, 15, 16, 17, 18, 19)


def main():
    candidate = REPORT / f"backend-candidate-source-{TAG}.json"
    frozen = json.loads(candidate.read_text())
    if source_files() != frozen["files"]:
        raise RuntimeError("Replacement source identity changed")
    old = json.loads((REPORT / "pg-v3-selection.json").read_text())
    nodes = [old["nodes"][i] for i in INDICES]
    if len(nodes) != 9 or len(set(nodes)) != 9:
        raise RuntimeError("Unexpected replacement scope")
    save(
        "repair-v4-selection.json",
        {
            "nodes": nodes,
            "original_indices": INDICES,
            "candidate": candidate.name,
            "candidate_sha256": sha(candidate),
            "original_selection_sha256": sha(REPORT / "pg-v3-selection.json"),
            "concurrency": 6,
            "scope": (
                "Two v3 failures and all seven unfinished nodes; "
                "scoped replacement, no full-tree claim"
            ),
        },
    )

    def run(item):
        index, node = item
        state = verified(read_state())
        if state["port"] != 62513 or state["marker"] != "916f950f-2d2b-405d-b809-c15db75dc20c":
            raise RuntimeError("Unexpected marked replacement target")
        from pdos_next.database import engine_for
        from sqlalchemy import text

        engine = engine_for(state["admin_url"])
        with engine.connect() as connection:
            if connection.scalar(text("SELECT version_num FROM alembic_version")) != "next_0025":
                raise RuntimeError("Actual head25 required")
        engine.dispose()
        key, start = f"repair-v4-{index:02}", time.monotonic()
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
            "original_index": index,
            "exit_code": result.returncode,
            "seconds": round(time.monotonic() - start, 2),
            "source_stable": source_files() == frozen["files"],
            "candidate_sha256": sha(candidate),
            "log_sha256": sha(REPORT / (key + ".log")),
        }
        save(key + "-result.json", value)
        print(key, result.returncode, "source_stable", value["source_stable"], flush=True)
        return key, value

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        pending = [pool.submit(run, pair) for pair in zip(INDICES, nodes, strict=True)]
        for future in concurrent.futures.as_completed(pending):
            key, value = future.result()
            results[key] = value
    save("repair-v4-result.json", results)
    if any(value["exit_code"] or not value["source_stable"] for value in results.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
