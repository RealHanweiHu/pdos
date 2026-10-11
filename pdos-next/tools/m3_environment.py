"""Run M3 checks only in this worktree's marked synthetic database."""

import argparse
import re
import subprocess
import sys

import local_environment as local

local.STATE = local.ROOT / ".local/m3-runtime.json"
REPORT = local.ROOT.parent / "docs/reports/evidence/pdos-next-m3-20261010/migration"


def state():
    current = local.verified(local.read_state())
    if current.get("purpose") != "m3-after-b8":
        raise RuntimeError("A separately marked M3 environment is required")
    return current


def run(arguments, name):
    current = state()
    env = local.environment(current)
    if "m3_checkpoint_url" in current:
        env["M2_TEST_CHECKPOINT_URL"] = current["m3_checkpoint_url"]
        env["PDOS_STATE_DB_PORT"] = str(current["port"])
        env["PDOS_STATE_DB_MARKER"] = current["marker"]
    env["PYTHONPATH"] = (
        str(local.ROOT.parent / "packages/pdos-agent-runtime/src") + ":" + str(local.SERVER)
    )
    REPORT.mkdir(parents=True, exist_ok=True)
    target = REPORT / name
    if target.exists():
        raise RuntimeError("Preserve existing evidence; choose a new output name")
    result = subprocess.run(
        [sys.executable, *arguments], cwd=local.SERVER, env=env, capture_output=True, text=True
    )
    output = re.sub(
        r"postgresql(?:\+psycopg)?://[^\s'\"]+", "[PRIVATE_DSN]", result.stdout + result.stderr
    )
    for key, value in current.items():
        if (key.endswith("url") or key.endswith("token")) and isinstance(value, str):
            output = output.replace(value, "[PRIVATE]")
    target.write_text(output)
    print(f"{name}: exit {result.returncode}; verified M3 port {current['port']}/pdos_test")
    return result.returncode


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.arguments[:1] == ["--"]:
        args.arguments = args.arguments[1:]
    if not args.arguments:
        parser.error("An explicit check command is required")
    raise SystemExit(run(args.arguments, args.name))
