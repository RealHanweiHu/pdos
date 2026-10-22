"""This checkpoint's checks use only the exact task-owned synthetic target."""

import ast
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from local_environment import ROOT, SERVER, environment, read_state, verified

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave13-20261002"
REPORT.mkdir(parents=True, exist_ok=True)


def target():
    return verified(read_state())


def run(arguments, log):
    state = target()
    with (REPORT / log).open("x") as output:
        subprocess.run(
            arguments,
            cwd=SERVER,
            env=environment(state),
            stdout=output,
            stderr=subprocess.STDOUT,
            check=True,
        )


def history():
    from pdos_next.database import engine_for
    from sqlalchemy import text

    state = target()
    tables = (
        "builds",
        "actual_configurations",
        "build_lots",
        "sample_units",
        "verification_preparations",
        "verification_formal_requests",
        "verification_actual_method_applicabilities",
        "verification_handoff_facts",
        "sample_readiness_facts",
        "build_starts",
        "operational_material_holds",
        "operational_resource_occupancies",
    )
    values = {}
    with engine_for(state["admin_url"]).connect() as connection:
        for table in tables:
            content = connection.scalar(
                text(
                    "SELECT COALESCE(jsonb_agg(to_jsonb(t)-'owner_kind'"
                    "-'build_start_id'-'test_run_id' ORDER BY id),'[]'::jsonb)::text "
                    f"FROM {table} t"
                )
            )
            values[table] = hashlib.sha256(content.encode()).hexdigest()
    return values


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


if sys.argv[1] == "migration":
    from pdos_next.database import engine_for
    from sqlalchemy import text

    state = target()
    with engine_for(state["admin_url"]).connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "next_0015"
    before = history()
    state = target()
    backup = ROOT / ".local/pre-wave13-next_0015.dump"
    if not backup.exists():
        with backup.open("xb") as output:
            backup.chmod(0o600)
            subprocess.run(
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
                stdout=output,
                stderr=subprocess.PIPE,
                check=True,
            )
    assert backup.stat().st_mode & 0o777 == 0o600
    for index, arguments in enumerate(
        (
            ["upgrade", "head"],
            ["check"],
            ["downgrade", "next_0015"],
            ["upgrade", "head"],
            ["check"],
        )
    ):
        run([sys.executable, "-m", "alembic", *arguments], f"migration-{index}.log")
    after = history()
    assert before == after, (
        "Old physical and handoff history must be unchanged by the schema roundtrip"
    )
    (REPORT / "migration-roundtrip.json").write_text(
        json.dumps(
            {
                "result": "passed",
                "steps": "next_0015 → next_0016 → next_0015 → next_0016",
                "before_business_writes": True,
                "old_history_hashes_unchanged": before,
                "backup": str(backup.relative_to(ROOT.parent)),
                "backup_mode": oct(backup.stat().st_mode & 0o777),
                "backup_sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
                "marker": state["marker"],
                "port": state["port"],
            },
            indent=2,
        )
        + "\n"
    )
    print("Migration up/down/up and final schema check passed; old physical history preserved.")
elif sys.argv[1] == "identity-migration":
    from pdos_next.database import engine_for
    from sqlalchemy import text

    state = target()
    with engine_for(state["admin_url"]).connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "next_0016"
        assert not connection.scalar(
            text("SELECT EXISTS(SELECT 1 FROM verification_run_versions WHERE status='running')")
        )
    before = history()
    state = target()
    backup = ROOT / ".local/pre-wave13-next_0016.dump"
    with backup.open("xb") as output:
        backup.chmod(0o600)
        subprocess.run(
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
            stdout=output,
            stderr=subprocess.PIPE,
            check=True,
        )
    for index, arguments in enumerate(
        (
            ["upgrade", "head"],
            ["check"],
            ["downgrade", "next_0016"],
            ["upgrade", "head"],
            ["check"],
        )
    ):
        run([sys.executable, "-m", "alembic", *arguments], f"identity-migration-{index}.log")
    assert before == history(), "Physical and request history must survive identity hardening"
    (REPORT / "identity-migration-roundtrip.json").write_text(
        json.dumps(
            {
                "result": "passed",
                "steps": "next_0016 → next_0017 → next_0016 → next_0017",
                "before_actual_test_start": True,
                "old_history_hashes_unchanged": before,
                "backup": str(backup.relative_to(ROOT.parent)),
                "backup_mode": "0o600",
                "backup_sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
                "marker": state["marker"],
                "port": state["port"],
            },
            indent=2,
        )
        + "\n"
    )
    print("Exact resource identity migration roundtrip/schema passed; historical rows unchanged.")
elif sys.argv[1] == "joint":
    from workflow_environment import read_verified, state_environment

    state = target()
    workflows = read_verified()
    env = {
        **environment(state),
        **state_environment(workflows),
        "CHECKPOINT_DATABASE_URL": workflows["checkpoint_url"],
    }
    paths = sys.argv[2:]
    previous = json.loads(
        (REPORT.parent / "pdos-next-wave12-20261002/integrated-test-selection.json").read_text()
    )
    selected = sorted(
        set(previous)
        | set(paths)
        | {
            "tests/test_resources",
            "tests/verification_launch",
            "tests/test_launch_common.py",
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
        "tests/test_resources/test_transactions.py",
        "tests/verification_launch/test_transactions.py",
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
    raise RuntimeError("Unsupported Wave13 check phase")
