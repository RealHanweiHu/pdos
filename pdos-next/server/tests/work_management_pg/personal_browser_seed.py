"""Finite read-only browser checkpoint with existing synthetic logins."""

import socket
import threading
import time
from datetime import datetime

import uvicorn
from release_policy_browser_seed.harness import _write_private_new

from pdos_next.models import now

from . import test_workflow as flow
from .browser_seed import _environment, _finished, _participants


def run(work, other, task_id, update_id):
    directory, port = _environment(work.setup)
    captured = now()
    _, _, actors = _participants(work, captured)
    deadline_at = min(datetime.fromisoformat(v["effective_until"]) for v in actors.values())
    duration = min(1200, (deadline_at - captured).total_seconds())
    assert duration > 0
    before = flow.snapshots(work)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", port))
    sock.listen(128)
    server = uvicorn.Server(
        uvicorn.Config(work.setup.client.app, log_level="warning", access_log=False)
    )
    errors = []

    def serve():
        try:
            server.run(sockets=[sock])
        except BaseException as error:
            errors.append(type(error).__name__)

    thread = threading.Thread(target=serve, daemon=True)
    try:
        thread.start()
        started_by = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < started_by:
            time.sleep(0.1)
        assert server.started and not errors
        _write_private_new(
            directory / "seed.json",
            {
                "synthetic": True,
                "database_head": "s0_0785",
                "actors": actors,
                "category_id": str(work.setup.category),
                "product_id": str(work.setup.product),
                "project_id": str(work.project_id),
                "other_category_id": str(other.setup.category),
                "other_project_id": str(other.project_id),
                "task_id": str(task_id),
                "update_id": str(update_id),
                "effective_until": deadline_at.isoformat(),
                "boundary": "Read personal queues and project summary only; no command POST.",
            },
        )
        print("Read-only personal work browser scope ready; API port", port, flush=True)
        deadline = time.monotonic() + duration
        while not _finished(directory / "finish") and time.monotonic() < deadline:
            assert thread.is_alive() and not errors
            time.sleep(0.2)
        assert _finished(directory / "finish"), "Read-only browser checkpoint elapsed"
    finally:
        server.should_exit = True
        thread.join(10)
        if thread.is_alive():
            server.force_exit = True
            thread.join(5)
        sock.close()
        (directory / "seed.json").unlink(missing_ok=True)
        assert not thread.is_alive()
    assert flow.snapshots(work) == before
    _write_private_new(
        directory / "result.json",
        {"read_only": True, "business_tables_unchanged": True, "preview_stopped": True},
    )
