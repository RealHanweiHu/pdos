"""Profile one real fresh start on its API worker thread; retain no arguments."""

import cProfile
import json
import os
import pstats
import sys
import time
from contextvars import ContextVar
from pathlib import Path

from local_environment import SERVER, environment, read_state, verified


def main():
    destination = Path(sys.argv[1]).resolve()
    if os.environ.get("S0_B8_TARGET") == "1":
        import s0_b8_environment as checkpoint

        checkpoint.state()
    state = verified(read_state())
    os.environ.update(environment(state))
    sys.path.insert(0, str(SERVER))
    sys.path.insert(0, str(SERVER / "tests"))
    os.chdir(SERVER)
    import pytest
    from pdos_next import service
    from sqlalchemy.engine.default import DefaultDialect

    actual = service.execute
    sampled = False
    pending_commit = ContextVar("s0_profile_commit", default=False)
    commits = []
    actual_commit = DefaultDialect.do_commit

    def commit(dialect, connection):
        selected = pending_commit.get()
        started = time.perf_counter()
        try:
            return actual_commit(dialect, connection)
        finally:
            if selected:
                commits.append({"seconds": time.perf_counter() - started})
                pending_commit.set(False)

    def execute(session, ctx, command, **options):
        nonlocal sampled
        if command.operation != "test.run.start" or sampled:
            pending_commit.set(False)
            return actual(session, ctx, command, **options)
        sampled = True
        pending_commit.set(True)
        profiler = cProfile.Profile()
        try:
            return profiler.runcall(actual, session, ctx, command, **options)
        finally:
            profiler.dump_stats(str(destination.with_suffix(".prof")))
            with destination.open("w") as output:
                pstats.Stats(profiler, stream=output).strip_dirs().sort_stats(
                    "cumulative"
                ).print_stats(55)
                pstats.Stats(profiler, stream=output).strip_dirs().sort_stats(
                    "tottime"
                ).print_stats(35)

    service.execute = execute
    DefaultDialect.do_commit = commit
    try:
        return pytest.main(sys.argv[2:])
    finally:
        service.execute = actual
        DefaultDialect.do_commit = actual_commit
        destination.with_suffix(".commit.json").write_text(json.dumps(commits, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
