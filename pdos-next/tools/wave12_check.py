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

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave12-20261002"
REPORT.mkdir(parents=True, exist_ok=True)
state = verified(read_state())
workflows = read_verified()
env = {
    **environment(state),
    **state_environment(workflows),
    "CHECKPOINT_DATABASE_URL": workflows["checkpoint_url"],
}
action, paths = sys.argv[1], sys.argv[2:]


def function_shards(path, *, weighted=False):
    """Keep each complete parametrized function within its isolated process."""
    tree = ast.parse((SERVER / path).read_text())
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]
    if not nodes or len({node.name for node in nodes}) != len(nodes):
        raise RuntimeError(f"Test functions must be present and unique: {path}")
    if not weighted:
        return [[f"{path}::{node.name}" for node in nodes[shard::4]] for shard in range(4)]

    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = len(node.value.elts)

    def parameter_count(node):
        count = 1
        for decorator in node.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "parametrize"
            ):
                continue
            values = (
                decorator.args[1]
                if len(decorator.args) > 1
                else next(
                    (item.value for item in decorator.keywords if item.arg == "argvalues"),
                    None,
                )
            )
            if isinstance(values, (ast.List, ast.Tuple, ast.Set)):
                size = len(values.elts)
            elif isinstance(values, ast.Name) and values.id in constants:
                size = constants[values.id]
            else:
                raise RuntimeError(f"Cannot statically bound parameters: {path}::{node.name}")
            if size == 0:
                raise RuntimeError(f"Empty parameter selection: {path}::{node.name}")
            count *= size
        return count

    weighted_nodes = []
    for node in nodes:
        arguments = {argument.arg for argument in (*node.args.posonlyargs, *node.args.args)}
        cases = parameter_count(node)
        pg_cases = (
            cases if arguments & {"setup", "planned", "actual", "lot", "verification_work"} else 0
        )
        weighted_nodes.append((node, cases, pg_cases))
    bins = [[] for _ in range(4)]
    loads = [[0, 0] for _ in range(4)]
    for node, cases, pg_cases in sorted(
        weighted_nodes, key=lambda item: (-item[2], item[0].lineno)
    ):
        shard = min(range(4), key=lambda index: (*loads[index], index))
        bins[shard].append(f"{path}::{node.name}")
        loads[shard][0] += pg_cases
        loads[shard][1] += cases
    return bins


def validate_groups(groups, files):
    """Reject duplicate whole-file/node execution and missing split functions."""
    flat = [selection for group in groups.values() for selection in group]
    if len(flat) != len(set(flat)):
        raise RuntimeError("Joint test selections overlap")
    by_file = {}
    for selection in flat:
        path = selection.split("::", 1)[0]
        by_file.setdefault(path, []).append(selection)
    if set(by_file) != set(files):
        raise RuntimeError("Joint test files do not cover the frozen selection")
    for path, selections in by_file.items():
        if path in selections:
            if len(selections) != 1:
                raise RuntimeError(f"Whole file and function selections overlap: {path}")
            continue
        tree = ast.parse((SERVER / path).read_text())
        names = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        ]
        expected = {f"{path}::{name}" for name in names}
        if len(expected) != len(names) or set(selections) != expected:
            raise RuntimeError(f"Split functions do not cover the module exactly once: {path}")


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
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "next_0014"
        assert c.scalar(text("SELECT to_regclass('public.sample_readiness_facts')")) is None
    backup = ROOT / ".local/pre-wave12-next_0014.dump"
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
            ("upgrade", "next_0015"),
            ("downgrade", "next_0014"),
            ("upgrade", "next_0015"),
        ):
            run([sys.executable, "-m", "alembic", direction, target], log)
            log.write(f"{direction} {target}: passed\n")
            log.flush()
        run([sys.executable, "-m", "alembic", "check"], log)
    print("Verified own instance: backup, next_0015 up/down/up and schema passed.")
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
        (REPORT.parent / "pdos-next-wave11-20261002/integrated-test-selection.json").read_text()
    )
    selected = sorted(
        set(previous)
        | set(paths)
        | {
            "tests/sample_handoff",
            "tests/verification_handoff",
            "tests/test_handoff_common.py",
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
    heavy = ["tests/test_cost_execution.py"]
    # New transactional fixtures create complete fixed plans. Distribute their
    # independent tenant cases instead of serializing the entire heavy module.
    split = [
        "tests/build_start/test_transactions.py",
        "tests/build_operational_facts/test_transactions.py",
        "tests/sample_handoff/test_transactions.py",
        "tests/verification_handoff/test_transactions.py",
    ]
    weighted_split = [
        "tests/test_build_execution.py",
        "tests/test_verification_execution.py",
    ]
    extra = []
    for path in split:
        for shard, nodes in enumerate(function_shards(path)):
            extra.append((f"{Path(path).parent.name}-{shard}", nodes))
    for path in weighted_split:
        for shard, nodes in enumerate(function_shards(path, weighted=True)):
            extra.append((f"{Path(path).stem}-{shard}", nodes))
    queue = (
        [("pure", pure)]
        + extra
        + [
            (Path(path).parent.name + "-" + Path(path).stem, [path])
            for path in heavy
            + [
                path
                for path in pg
                if path not in heavy and path not in split and path not in weighted_split
            ]
        ]
    )
    groups = dict(queue) | {"lifecycle-isolated": isolated}
    if len(groups) != len(queue) + 1:
        raise RuntimeError("Joint test group names must be unique")
    validate_groups(groups, files)
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
    raise RuntimeError("Unknown Wave12 check action")
