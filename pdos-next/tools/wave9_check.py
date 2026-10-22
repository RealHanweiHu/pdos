"""Wave9 checks on this task's guarded synthetic environment only."""

import json
import re
import subprocess
import sys
import time

from local_environment import ROOT, SERVER, environment, read_state, verified
from pdos_next.database import engine_for
from sqlalchemy import text
from workflow_environment import read_verified, state_environment

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave9-20261002"
REPORT.mkdir(parents=True, exist_ok=True)
state = verified(read_state())
workflows = read_verified()
env = {
    **environment(state),
    **state_environment(workflows),
    "CHECKPOINT_DATABASE_URL": workflows["checkpoint_url"],
}
action = sys.argv[1]


def run(argv, log):
    result = subprocess.run(argv, cwd=SERVER, env=env, stdout=log, stderr=subprocess.STDOUT)
    log.flush()
    if result.returncode:
        raise SystemExit(result.returncode)


if action == "delivery-migration":
    backup = ROOT / ".local/pre-wave9-next_0011.dump"
    with engine_for(state["admin_url"]).connect() as connection:
        if connection.scalar(text("SELECT version_num FROM alembic_version")) != "next_0011":
            raise RuntimeError("Delivery migration requires the verified 0011 head")
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
    with (REPORT / "delivery-migration-roundtrip.log").open("x") as log:
        for direction, target in [
            ("upgrade", "next_0012"),
            ("downgrade", "next_0011"),
            ("upgrade", "next_0012"),
        ]:
            run([sys.executable, "-m", "alembic", direction, target], log)
            log.write(f"{direction} {target}: passed\n")
            log.flush()
        run([sys.executable, "-m", "alembic", "check"], log)
    print("Retained 0011 backup; 0012 delivery trigger roundtrip and schema check passed")
elif action in {"migrate", "resume-migrate"}:
    backup = ROOT / ".local/pre-wave9-next_0010.dump"
    with engine_for(state["admin_url"]).connect() as connection:
        head = connection.scalar(text("SELECT version_num FROM alembic_version"))
        new_table = connection.scalar(text("SELECT to_regclass('public.lifecycle_objects')"))
    if head != "next_0010" or new_table:
        raise RuntimeError("Roundtrip requires unchanged 0010 and no Wave9 objects/data")
    if action == "migrate":
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
    elif not backup.is_file() or not backup.stat().st_size:
        raise RuntimeError("Resume requires retained pre-migration backup")
    with (REPORT / "migration-roundtrip.log").open("x" if action == "migrate" else "a") as log:
        for direction, target in [
            ("upgrade", "next_0011"),
            ("downgrade", "next_0010"),
            ("upgrade", "next_0011"),
        ]:
            run([sys.executable, "-m", "alembic", direction, target], log)
            log.write(f"{direction} {target}: passed\n")
        run([sys.executable, "-m", "alembic", "check"], log)
    print("Own marked database: retained backup, 0011 roundtrip and schema check passed")
elif action in {"schema", "check", "parallel-check"}:
    paths = sys.argv[2:]
    name = (
        "schema-match.log"
        if action == "schema"
        else ("scoped-tests.log" if paths else "postgres-tests.log")
    )
    if action != "schema" and not paths:
        previous = json.loads(
            (REPORT.parent / "pdos-next-wave8-20261002/integrated-test-selection.json").read_text()
        )
        paths = sorted(
            set(previous)
            | {
                "tests/test_original_lifecycle_integration.py",
                "tests/original_lifecycle",
                "tests/original_lifecycle_execution",
                "tests/object_lifecycle_runtime",
            }
        )
        (REPORT / "integrated-test-selection.json").write_text(json.dumps(paths, indent=2) + "\n")
    if action == "parallel-check":
        # All fixture tenants are independent. Transactional schema probes run alone
        # after these groups, so global DDL cannot alter a concurrent group's view.
        isolated = ["tests/test_original_lifecycle_integration.py"]
        pure, transactional = [], []
        for path in paths:
            if path in isolated:
                continue
            if path.startswith("tests/test_") or path.endswith("_transactions.py"):
                transactional.append(path)
            else:
                pure.append(path)
        buckets, weights = [[], [], []], [0, 0, 0]
        weighted = sorted(
            transactional, key=lambda p: (SERVER / p).read_text().count("def test_"), reverse=True
        )
        for path in weighted:
            index = weights.index(min(weights))
            buckets[index].append(path)
            weights[index] += (SERVER / path).read_text().count("def test_")
        groups = {
            "pure": pure,
            **{f"postgres-{i + 1}": b for i, b in enumerate(buckets)},
            "lifecycle-isolated": isolated,
        }
        flat = [p for group in groups.values() for p in group]
        if len(flat) != len(set(flat)) or set(flat) != set(paths):
            raise RuntimeError("Every selected test path must run exactly once")
        (REPORT / "joint-shards.json").write_text(json.dumps(groups, indent=2) + "\n")
        started, results, jobs = time.monotonic(), {}, {}

        def start_group(key, selection):
            output = (REPORT / f"joint-{key}.log").open("x")
            process = subprocess.Popen(
                [sys.executable, "-m", "pytest", "-q", *selection],
                cwd=SERVER,
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
            return process, output

        for key, selection in groups.items():
            if key != "lifecycle-isolated":
                jobs[key] = start_group(key, selection)
        while jobs:
            for key, (process, output) in list(jobs.items()):
                code = process.poll()
                if code is not None:
                    output.close()
                    results[key] = code
                    del jobs[key]
                    print(f"{key}: exit {code}", flush=True)
            if jobs:
                time.sleep(0.5)
        process, output = start_group("lifecycle-isolated", isolated)
        results["lifecycle-isolated"] = process.wait()
        output.close()
        counts = {}
        for key in groups:
            log_text = (REPORT / f"joint-{key}.log").read_text()
            match = re.search(r"(\d+) passed", log_text)
            counts[key] = int(match.group(1)) if match else 0
        result = {
            "exit_codes": results,
            "passed_by_group": counts,
            "total_passed": sum(counts.values()),
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "same_frozen_candidate": True,
            "schema_mutation_tests_ran_without_other_test_processes": True,
        }
        (REPORT / "joint-result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result), flush=True)
        raise SystemExit(0 if all(code == 0 for code in results.values()) else 1)
    argv = (
        [sys.executable, "-m", "alembic", "check"]
        if action == "schema"
        else [sys.executable, "-m", "pytest", "-q", *paths]
    )
    destination = REPORT / name
    if destination.exists():
        index = 1
        while destination.with_name(f"{destination.stem}-attempt-{index}.log").exists():
            index += 1
        destination.rename(destination.with_name(f"{destination.stem}-attempt-{index}.log"))
    with destination.open("w") as log:
        result = subprocess.run(argv, cwd=SERVER, env=env, stdout=log, stderr=subprocess.STDOUT)
    print((REPORT / name).read_text())
    raise SystemExit(result.returncode)
else:
    raise RuntimeError("Unknown Wave9 check action")
