"""Checks confined to this task's verified synthetic instance and a frozen candidate."""

import ast
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from local_environment import ROOT, SERVER, environment, read_state, verified
from pdos_next.database import engine_for
from sqlalchemy import text
from workflow_environment import read_verified, state_environment

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave11-20261002"
REPORT.mkdir(parents=True, exist_ok=True)
state = verified(read_state())
workflows = read_verified()
env = {
    **environment(state),
    **state_environment(workflows),
    "CHECKPOINT_DATABASE_URL": workflows["checkpoint_url"],
}
action, paths = sys.argv[1], sys.argv[2:]


def destination(name):
    path = REPORT / name
    if path.exists():
        number = 1
        while path.with_name(f"{path.stem}-attempt-{number}{path.suffix}").exists():
            number += 1
        path.rename(path.with_name(f"{path.stem}-attempt-{number}{path.suffix}"))
    return path


def run(argv, output):
    result = subprocess.run(argv, cwd=SERVER, env=env, stdout=output, stderr=subprocess.STDOUT)
    output.flush()
    if result.returncode:
        raise SystemExit(result.returncode)


if action == "migrate":
    with engine_for(state["admin_url"]).connect() as c:
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "next_0013"
        assert c.scalar(text("SELECT to_regclass('public.build_starts')")) is None
    backup = ROOT / ".local/pre-wave11-next_0013.dump"
    with backup.open("xb") as output:
        backup.chmod(0o600)
        run(
            [
                "docker",
                "exec",
                state["container"],
                "pg_dump",
                "-U",
                "postgres",
                "-d",
                "pdos_test",
                "-Fc",
            ],
            output,
        )
    with destination("migration-roundtrip.log").open("w") as log:
        for direction, target in (
            ("upgrade", "next_0014"),
            ("downgrade", "next_0013"),
            ("upgrade", "next_0014"),
        ):
            run([sys.executable, "-m", "alembic", direction, target], log)
            log.write(f"{direction} {target}: passed\n")
            log.flush()
        run([sys.executable, "-m", "alembic", "check"], log)
    print("Verified own instance: backup, next_0014 up/down/up and schema passed.")
elif action in {"schema", "check"}:
    if action == "check" and not paths:
        raise RuntimeError("Scoped checks require explicit paths; use joint for the frozen union")
    target = destination("schema-match.log" if action == "schema" else "scoped-tests.log")
    with target.open("w") as log:
        run(
            [sys.executable, "-m", "alembic", "check"]
            if action == "schema"
            else [sys.executable, "-m", "pytest", "-q", *paths],
            log,
        )
    print(target.read_text())
elif action == "joint":
    previous = json.loads(
        (REPORT.parent / "pdos-next-wave10-20261002/integrated-test-selection.json").read_text()
    )
    selected = sorted(
        set(previous)
        | set(paths)
        | {
            "tests/build_operational_facts",
            "tests/build_start",
            "tests/test_build_start_common.py",
        }
    )
    files = set()
    for path in selected:
        resolved = SERVER / path
        if resolved.is_dir():
            files.update(str(p.relative_to(SERVER)) for p in resolved.rglob("test_*.py"))
        elif resolved.is_file():
            files.add(path)
        else:
            raise RuntimeError(f"Selected test path is missing: {path}")
    isolated = ["tests/test_original_lifecycle_integration.py"]
    pure, pg = [], []
    for path in sorted(files):
        if path in isolated:
            continue
        if path.startswith("tests/test_") or path.endswith("_transactions.py"):
            pg.append(path)
        else:
            pure.append(path)
    # Prior Wave9 process evidence exposed skew from keeping these heavy modules together.
    heavy = [
        "tests/test_build_execution.py",
        "tests/test_cost_execution.py",
        "tests/test_verification_execution.py",
    ]
    # New transactional fixtures create complete fixed plans. Distribute their
    # independent tenant cases instead of serializing the entire heavy module.
    split = [
        "tests/build_start/test_transactions.py",
        "tests/build_operational_facts/test_transactions.py",
    ]
    extra = []
    for path in split:
        nodes = [
            node.name
            for node in ast.parse((SERVER / path).read_text()).body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        ]
        for shard in range(4):
            extra.append(
                (
                    f"{Path(path).parent.name}-{shard}",
                    [f"{path}::{name}" for name in nodes[shard::4]],
                )
            )
    queue = (
        [("pure", pure)]
        + extra
        + [
            (Path(path).parent.name + "-" + Path(path).stem, [path])
            for path in heavy + [path for path in pg if path not in heavy and path not in split]
        ]
    )
    groups = dict(queue) | {"lifecycle-isolated": isolated}
    flat = [path for group in groups.values() for path in group]
    assert len(flat) == len(set(flat)) and {p.split("::")[0] for p in flat} == files
    (REPORT / "integrated-test-selection.json").write_text(json.dumps(selected, indent=2) + "\n")
    (REPORT / "joint-shards.json").write_text(json.dumps(groups, indent=2) + "\n")
    started, jobs, results = time.monotonic(), {}, {}

    def start(key, selection):
        log = (REPORT / f"joint-{key}.log").open("x")
        proc = subprocess.Popen(
            [sys.executable, "-m", "pytest", "-q", *selection],
            cwd=SERVER,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        return proc, log, time.monotonic()

    while queue or jobs:
        while queue and len(jobs) < 6:
            key, selection = queue.pop(0)
            jobs[key] = start(key, selection)
        for key, (proc, log, began) in list(jobs.items()):
            if proc.poll() is not None:
                log.close()
                results[key] = {
                    "exit_code": proc.returncode,
                    "elapsed_seconds": round(time.monotonic() - began, 2),
                }
                del jobs[key]
                print(f"{key}: exit {proc.returncode}", flush=True)
        if jobs:
            time.sleep(0.5)
    proc, log, began = start("lifecycle-isolated", isolated)
    code = proc.wait()
    log.close()
    results["lifecycle-isolated"] = {
        "exit_code": code,
        "elapsed_seconds": round(time.monotonic() - began, 2),
    }
    for key in results:
        match = re.search(r"(\d+) passed", (REPORT / f"joint-{key}.log").read_text())
        results[key]["passed"] = int(match.group(1)) if match else 0
    outcome = {
        "groups": results,
        "total_passed": sum(v["passed"] for v in results.values()),
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "structural_tests_isolated": True,
    }
    (REPORT / "joint-result.json").write_text(json.dumps(outcome, indent=2) + "\n")
    print(json.dumps(outcome), flush=True)
    raise SystemExit(0 if all(v["exit_code"] == 0 for v in results.values()) else 1)
else:
    raise RuntimeError("Unknown Wave11 check action")
