"""Restart a local preview process whenever its source files change.

Usage: dev_reload.py --watch DIR [--watch DIR ...] -- COMMAND [ARGS ...]
Polls file mtimes (stdlib only); schema migrations are never run here.
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def snapshot(roots):
    state = {}
    for root in roots:
        for directory, names, files in os.walk(root):
            names[:] = [n for n in names if n != "__pycache__" and not n.startswith(".")]
            for name in files:
                if name.endswith((".pyc", ".log")) or name.startswith("."):
                    continue
                path = os.path.join(directory, name)
                try:
                    stat = os.stat(path)
                except FileNotFoundError:
                    continue
                state[path] = (stat.st_mtime_ns, stat.st_size)
    return state


def stop(child):
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="append", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("missing command after --")
    child = None

    def shutdown(signum, _frame):
        if child is not None:
            stop(child)
        sys.exit(128 + signum)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    seen = snapshot(args.watch)
    while True:
        child = subprocess.Popen(command)
        while True:
            time.sleep(args.interval)
            current = snapshot(args.watch)
            if current != seen:
                time.sleep(0.5)  # let editors finish multi-file saves
                latest = snapshot(args.watch)
                changed = [p for p in latest.keys() | seen.keys() if latest.get(p) != seen.get(p)]
                seen = latest
                print(f"[dev_reload] {len(changed)} source files changed, restarting", flush=True)
                stop(child)
                break
            if child.poll() is not None:
                code = child.returncode
                print(f"[dev_reload] exited with {code}; waiting for a source change", flush=True)
                while snapshot(args.watch) == seen:
                    time.sleep(args.interval)
                seen = snapshot(args.watch)
                break


if __name__ == "__main__":
    main()
