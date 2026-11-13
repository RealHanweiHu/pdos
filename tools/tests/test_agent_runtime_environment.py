"""D346: the local Agent runtime tool installs its schema under the realm the store accepts.

No Docker, database or Temporal: the container, connection and Temporal start are
replaced, and the store's own realm check decides whether the install is accepted.
"""

import importlib.util
import json
import stat
from pathlib import Path

import pytest
from pdos_agent_runtime.store import RuntimeStore


def load(tmp_path, monkeypatch):
    path = Path(__file__).parent.parent / "agent_runtime_environment.py"
    spec = importlib.util.spec_from_file_location("staged_agent_runtime_environment", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DIRECTORY", tmp_path / "agent-runtime")
    monkeypatch.setattr(module, "CONFIG", tmp_path / "agent-runtime" / "environment.json")
    return module


class Reached(Exception):
    """The store accepted the realm and went on to open its database."""


def store_install(calls):
    """Run the store's realm check, then stop where it would open the database."""

    def install(url, *, realm, marker):
        calls.append(realm)
        try:
            RuntimeStore(url, realm=realm, marker=marker)
        except Reached:
            return

    return install


class Connection:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, *args):
        return None

    def close(self):
        return None


@pytest.fixture
def faked(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    calls = []

    def reached(self):
        raise Reached

    monkeypatch.setattr(RuntimeStore, "connection", reached)
    monkeypatch.setattr(module, "install", store_install(calls))
    monkeypatch.setattr(module.shutil, "which", lambda name: "/fake/temporal")
    monkeypatch.setattr(
        module.subprocess, "run", lambda *a, **k: type("Done", (), {"returncode": 0})()
    )
    monkeypatch.setattr(module.subprocess, "check_output", lambda *a, **k: "container-id\n")
    monkeypatch.setattr(module.psycopg, "connect", lambda *a, **k: Connection())
    monkeypatch.setattr(module, "inspect_container", lambda value: None)
    monkeypatch.setattr(module, "start", lambda value: None)
    return module, calls


def test_new_environment_installs_schema_under_the_accepted_realm(faked, monkeypatch, capsys):
    module, calls = faked
    monkeypatch.setattr("sys.argv", ["agent_runtime_environment.py", "start"])
    module.main()
    assert calls == ["pdos-next"]
    saved = json.loads(module.CONFIG.read_text())
    assert saved["schema_installed"] is True
    assert stat.S_IMODE(module.CONFIG.stat().st_mode) == 0o600
    assert json.loads(capsys.readouterr().out)["schema_installed"] is True


def test_the_old_realm_is_still_refused_by_the_store(faked):
    """Guards the test itself: the fake install really runs the store's realm check."""
    module, _ = faked
    with pytest.raises(ValueError, match="Unknown runtime realm"):
        module.install("postgresql://unused", realm="pdos", marker="m")


def test_environment_left_without_schema_is_repaired_on_start_not_on_status(
    faked, monkeypatch, capsys
):
    """A pre-D346 configuration exists but its install failed: start finishes it."""
    module, calls = faked
    module.DIRECTORY.mkdir()
    value = {
        "container": "pdos-agent-state-abcdef12",
        "container_id": "container-id",
        "marker": "marker",
        "port": 1,
        "temporal_binary": "/fake/temporal",
        "temporal_port": 2,
        "environment": {
            "PDOS_AGENT_RUNTIME_DATABASE_URL": "postgresql://unused",
            "PDOS_AGENT_RUNTIME_DB_MARKER": "marker",
        },
    }
    module.private_write(module.CONFIG, value)

    monkeypatch.setattr("sys.argv", ["agent_runtime_environment.py", "status"])
    module.main()
    assert calls == []
    assert json.loads(capsys.readouterr().out)["schema_installed"] is False

    monkeypatch.setattr("sys.argv", ["agent_runtime_environment.py", "start"])
    module.main()
    assert calls == ["pdos-next"]
    assert json.loads(module.CONFIG.read_text())["schema_installed"] is True

    module.main()
    assert calls == ["pdos-next"], "an installed schema is not reinstalled"
