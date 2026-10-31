"""Run the frozen candidate keyword baseline on the verified local pdos_test DB."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import local_environment as local


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    destination = args.output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    # The existing verifier checks the container, exact DB name and marker.
    # It never falls back to .env or a production connection.
    state = local.verified(local.read_state())
    env = local.environment(state)
    root = Path(__file__).resolve().parents[1]
    env.update(
        PYTHONPATH=os.pathsep.join([
            str(root.parent / "packages/pdos-agent-runtime/src"),
            str(root / "server"), str(root / "server/tests"),
        ]),
        PYTHONUNBUFFERED="1",
        PDOS_XIAOPAI_EVAL_OUTPUT=str(destination / "baseline.json"),
    )
    command = [
        sys.executable, "-m", "pytest", "-vv", "-x",
        "tests/enterprise_search/test_question_set_v0_pg.py",
        "--junitxml=" + str(destination / "native.xml"),
    ]
    process = subprocess.Popen(
        command, cwd=root / "server", env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    with (destination / "native.log").open("x") as stream:
        for line in process.stdout:
            safe = re.sub(r"postgresql(?:\+psycopg)?://[^\s'\"]+", "[PRIVATE_DSN]", line)
            for key, value in state.items():
                if key.endswith(("url", "token")) and isinstance(value, str):
                    safe = safe.replace(value, "[PRIVATE]")
            stream.write(safe)
    code = process.wait()
    print(json.dumps({
        "execution_exit": code, "output_dir": str(destination),
        "database": "pdos_test", "port": state["port"],
        "scope": "synthetic artifact keyword retrieval; answer quality not evaluated",
    }))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
