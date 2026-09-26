"""Exercise local process cleanup with stub services, without opening a database."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("exiting_service", ["api", "web", "reminders"])
def test_dev_stops_remaining_services_when_any_service_exits(
    tmp_path: Path, exiting_service: str
) -> None:
    for directory in ("scripts", "server", "web", "bin"):
        (tmp_path / directory).mkdir()
    dev = tmp_path / "scripts" / "dev.sh"
    dev.write_text((REPOSITORY_ROOT / "scripts" / "dev.sh").read_text())
    worker = tmp_path / "worker.sh"
    worker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
service="$1"
printf '%s started\\n' "$service" >> "$PDOS_TEST_LIFECYCLE_LOG"
trap 'printf "%s stopped\\n" "$service" >> "$PDOS_TEST_LIFECYCLE_LOG"; exit 0' TERM
if [[ "$service" == "$PDOS_TEST_EXIT_SERVICE" ]]; then
  until [[ "$(wc -l < "$PDOS_TEST_LIFECYCLE_LOG")" -ge 3 ]]; do sleep 0.05; done
  exit 7
fi
while :; do sleep 0.05; done
"""
    )
    uv = tmp_path / "bin" / "uv"
    uv.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case "$*" in
  *uvicorn*) service=api ;;
  *scripts.run_reminder_scheduler*) service=reminders ;;
  *) exit 99 ;;
esac
exec "$PDOS_TEST_LIFECYCLE_WORKER" "$service"
"""
    )
    pnpm = tmp_path / "scripts" / "pnpm.sh"
    pnpm.write_text('#!/usr/bin/env bash\nexec "$PDOS_TEST_LIFECYCLE_WORKER" web\n')
    for executable in (dev, worker, uv, pnpm):
        executable.chmod(0o755)
    log = tmp_path / "lifecycle.log"
    log.touch()
    environment = {
        **os.environ,
        "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
        "PDOS_TEST_LIFECYCLE_WORKER": str(worker),
        "PDOS_TEST_LIFECYCLE_LOG": str(log),
        "PDOS_TEST_EXIT_SERVICE": exiting_service,
    }
    result = subprocess.run(
        ["bash", str(dev)],
        env=environment,
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    lines = log.read_text().splitlines()
    assert sorted(line for line in lines if line.endswith(" started")) == [
        "api started",
        "reminders started",
        "web started",
    ]
    assert sorted(line for line in lines if line.endswith(" stopped")) == sorted(
        f"{service} stopped"
        for service in ("api", "web", "reminders")
        if service != exiting_service
    )
    for label in ("API", "web", "reminders"):
        assert f"PDOS {label} pid: " in result.stdout
