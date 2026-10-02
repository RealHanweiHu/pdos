"""Exercise local process cleanup with stub services, without opening a database."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("exiting_service", ["api", "web", "reminders"])
def test_dev_stops_remaining_services_when_any_service_exits(
    tmp_path: Path, exiting_service: str
) -> None:
    tmp_path = tmp_path / "product manager & local"
    tmp_path.mkdir()
    for directory in ("scripts", "server", "web", "bin"):
        (tmp_path / directory).mkdir()
    (tmp_path / ".env").write_text("PDOS_TEST_MODEL=file-model\n")
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
printf '%s\\0' "$@" > "$PDOS_TEST_UV_ARGS_DIRECTORY/$service.args"
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
        "PDOS_TEST_UV_ARGS_DIRECTORY": str(tmp_path),
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
    for service in ("api", "reminders"):
        arguments = (tmp_path / f"{service}.args").read_bytes().decode().split("\0")[:-1]
        assert arguments[0] == "run"
        file_argument = arguments[arguments.index("--env-file") + 1]
        assert (tmp_path / "server" / file_argument).resolve() == (tmp_path / ".env").resolve()


@pytest.mark.parametrize("process_model", [None, "process-model"])
def test_local_api_environment_reads_dotenv_without_executing_its_values(
    tmp_path: Path, process_model: str | None
) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("The local launcher requires the uv CLI")
    tmp_path = tmp_path / "synthetic root & local"
    tmp_path.mkdir()
    marker = tmp_path / "must-not-execute"
    key = f"synthetic-$(touch {marker})"
    env_file = tmp_path / "local.env"
    env_file.write_text(
        "\n".join(
            [
                "PDOS_LLM_PROVIDER=openai",
                f"PDOS_LLM_API_KEY='{key}'",
                "PDOS_LLM_MODEL=file-model",
                "PDOS_APPLICATION_MODEL_BUDGET_MODE=budgeted",
                "PDOS_APPLICATION_MODEL_BUDGET_PROFILE=short",
                f'PDOS_APPLICATION_MODEL_METER_PATH="{tmp_path / "unpublished-meter.json"}"',
                "PDOS_APPLICATION_MODEL_METER_SHA256=" + "a" * 64,
            ]
        )
    )
    environment = {"PATH": os.environ["PATH"], "PYTHONPATH": str(REPOSITORY_ROOT / "server")}
    if process_model is not None:
        environment["PDOS_LLM_MODEL"] = process_model
    environment["PDOS_TEST_LITERAL_KEY"] = key
    code = """
import json, os
from app.ai.model_catalog import ModelCatalog
from app.ai.budget_adoption import ApplicationBudgetConfiguration
catalog = ModelCatalog.from_environment(os.environ)
budget = ApplicationBudgetConfiguration.from_environment(os.environ)
print(json.dumps({
    'providers': len(catalog.configurations),
    'model': catalog.configurations[0].model,
    'literal_key': (
        catalog.configurations[0].api_key.get_secret_value() == os.environ['PDOS_TEST_LITERAL_KEY']
    ),
    'budget_profile': budget.profile.key,
    'meter_path': str(budget.meter_path),
    'meter_digest': budget.meter_sha256,
}))
"""
    result = subprocess.run(
        [
            uv,
            "run",
            "--no-project",
            "--offline",
            "--python",
            sys.executable,
            "--env-file",
            env_file.name,
            "python",
            "-c",
            code,
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "providers": 1,
        "model": process_model or "file-model",
        "literal_key": True,
        "budget_profile": "short",
        "meter_path": str(tmp_path / "unpublished-meter.json"),
        "meter_digest": "a" * 64,
    }
    assert not marker.exists()
