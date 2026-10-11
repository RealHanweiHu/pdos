"""Run an explicit affected selection and retain exact nodes and source hashes."""

import json
import os
import sys
from pathlib import Path

from s0_source_manifest import snapshot


def main():
    destination, selection = (Path(value).resolve() for value in sys.argv[1:3])
    junit = destination.with_suffix(".xml")
    if destination.exists() or junit.exists():
        raise RuntimeError("Preserve completed affected validation evidence")
    selectors = json.loads(selection.read_text())
    if not selectors or any(not isinstance(value, str) for value in selectors):
        raise RuntimeError("Explicit nonempty affected test selection required")
    if os.environ.get("S0_PRIMARY_TARGET") == "1":
        import local_environment as local

        state = local.verified(local.read_state())
    else:
        import s0_b8_environment as checkpoint

        state, local = checkpoint.state(), checkpoint.local
    os.environ.update(local.environment(state))
    sys.path[:0] = [str(local.SERVER), str(local.SERVER / "tests")]
    os.chdir(local.SERVER)
    initial = snapshot()
    import pytest

    nodes, reports = [], []

    class Evidence:
        def pytest_collection_finish(self, session):
            nodes.extend(item.nodeid for item in session.items)

        def pytest_runtest_logreport(self, report):
            reports.append({"node": report.nodeid, "phase": report.when, "outcome": report.outcome})
            if report.failed:
                print(
                    "\nIMMEDIATE FAILURE " + report.nodeid + "\n" + str(report.longrepr), flush=True
                )

    code = 2
    try:
        code = pytest.main(
            [
                "-q",
                "--tb=short",
                "--maxfail=1",
                "--junitxml=" + str(junit),
                *selectors,
                *sys.argv[3:],
            ],
            plugins=[Evidence()],
        )
    finally:
        destination.write_text(
            json.dumps(
                {
                    "test_exit": int(code),
                    "collect_only": "--collect-only" in sys.argv[3:],
                    "database": {
                        "name": "pdos_test",
                        "port": state["port"],
                        "marker": state["marker"],
                    },
                    "selectors": selectors,
                    "collected_nodes": nodes,
                    "reports": reports,
                    "source_sha256": initial,
                    "source_unchanged": snapshot() == initial,
                },
                indent=2,
            )
            + "\n"
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
