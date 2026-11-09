"""Replay open Temporal histories against the workflow code about to be released (D212).

A workflow that is waiting (a 小Pai run waiting for an answer, a maintenance timer,
a delivery retry) is resumed by replaying its whole history against the code of the
worker that picks it up. If the new code issues different commands for the same
history, the workflow task fails with a nondeterminism error and that work stalls.
Changes to workflow code therefore go behind ``workflow.patched(...)``; this check
proves it before the old worker is stopped. See docs/runbooks/release-and-rollback.md.

  export  --out DIR [--query Q]   save histories of matching workflows (default: running)
  replay  --from DIR              replay saved histories against this checkout's workflows
  check   [--query Q]             export to a private temp dir and replay in one step

The Temporal address and namespace come from PDOS_TEMPORAL_ADDRESS and
PDOS_TEMPORAL_NAMESPACE, or from this worktree's local workflow environment with
--local. Histories contain workflow inputs (identifiers only, never model text or
credentials), and are written with owner-only permissions.
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
DEFAULT_QUERY = 'ExecutionStatus="Running"'


def workflows():
    from pdos_next.workflows.worker import registered_workflows

    return registered_workflows()


def target(local: bool) -> tuple[str, str]:
    if local:
        sys.path.insert(0, str(ROOT / "tools"))
        from workflow_environment import read_verified

        value = read_verified()
        return f"127.0.0.1:{value['server_port']}", "pdos-next"
    return os.environ["PDOS_TEMPORAL_ADDRESS"], os.environ["PDOS_TEMPORAL_NAMESPACE"]


async def export(client, out: Path, query: str, limit: int) -> list[dict]:
    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    saved = []
    async for execution in client.list_workflows(query=query, limit=limit):
        handle = client.get_workflow_handle(execution.id, run_id=execution.run_id)
        history = await handle.fetch_history()
        name = f"{len(saved):05d}.json"
        path = out / name
        path.write_text(history.to_json())
        path.chmod(0o600)
        saved.append(
            {
                "file": name,
                "workflow_id": execution.id,
                "run_id": execution.run_id,
                "workflow_type": execution.workflow_type,
                "events": len(history.events),
            }
        )
    index = out / "index.json"
    index.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n")
    index.chmod(0o600)
    return saved


async def replay(directory: Path, classes=None) -> dict:
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    index = json.loads((directory / "index.json").read_text())
    histories = [
        WorkflowHistory.from_json(row["workflow_id"], (directory / row["file"]).read_text())
        for row in index
    ]
    classes = classes or workflows()
    known = {cls.__temporal_workflow_definition.name for cls in classes}
    unknown = sorted({row["workflow_type"] for row in index} - known)
    failures = []
    if histories:

        async def stream():
            for history in histories:
                yield history

        results = await Replayer(workflows=classes).replay_workflows(
            stream(), raise_on_replay_failure=False
        )
        for workflow_run_id, error in results.replay_failures.items():
            row = next((r for r in index if r["run_id"] == workflow_run_id), {})
            failures.append(
                {
                    "workflow_id": row.get("workflow_id"),
                    "workflow_type": row.get("workflow_type"),
                    "run_id": workflow_run_id,
                    "error": type(error).__name__,
                    "message": str(error).splitlines()[0][:300] if str(error) else "",
                }
            )
    return {
        "histories": len(histories),
        "workflow_types": sorted({row["workflow_type"] for row in index}),
        "unregistered_types": unknown,
        "failures": failures,
        "passed": not failures and not unknown,
    }


async def run(args) -> int:
    from temporalio.client import Client

    if args.action == "replay":
        report = await replay(args.from_dir)
    else:
        address, namespace = target(args.local)
        client = await Client.connect(address, namespace=namespace)
        if args.action == "export":
            saved = await export(client, args.out, args.query, args.limit)
            print(json.dumps({"exported": len(saved), "directory": str(args.out)}))
            return 0
        with tempfile.TemporaryDirectory(prefix="pdos-replay-") as scratch:
            await export(client, Path(scratch) / "histories", args.query, args.limit)
            report = await replay(Path(scratch) / "histories")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("export", "check"):
        command = sub.add_parser(name)
        command.add_argument("--query", default=DEFAULT_QUERY)
        command.add_argument("--limit", type=int, default=1000)
        command.add_argument("--local", action="store_true")
        if name == "export":
            command.add_argument("--out", type=Path, required=True)
    sub.add_parser("replay").add_argument("--from", dest="from_dir", type=Path, required=True)
    return asyncio.run(run(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
