"""D349: the worker's own metrics, scraped like the API's ``/ops/metrics``.

Same token and format, no Activity, workflow, user or tenant label, and no listener at
all without a token. The outcome counts come from a real worker on a private in-memory
Temporal dev server (inspected local binary; skipped without it). No database.
"""

import asyncio
import socket
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from pdos_next.ops import probe
from pdos_next.ops.metrics import PATH
from pdos_next.ops.worker_metrics import (
    ActivityMetrics,
    WorkerMetrics,
    listen_address,
    serve_metrics,
)
from tests.workflows import shutdown_fixture as fixture

TOKEN = "w" * 40
BINARY = Path(__file__).resolve().parents[3] / ".local/tools/temporal"
CONFIG = Path(__file__).resolve().parents[3] / "config/ops/monitoring.example.json"


def _port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _get(url, token=None, method="GET"):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, dict(response.headers), response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), ""


def test_no_listener_without_a_long_enough_token():
    async def opened(environ):
        return await serve_metrics(lambda: "", environ=environ)

    assert asyncio.run(opened({})) is None
    assert asyncio.run(opened({"PDOS_METRICS_TOKEN": "short"})) is None


@pytest.mark.parametrize("value", ["9464", "host:", "host:0", "host:70000", "host:x"])
def test_listen_address_must_be_host_and_port(value):
    with pytest.raises(RuntimeError):
        listen_address({"PDOS_WORKER_METRICS_ADDRESS": value})


def test_scrape_needs_the_token_and_only_answers_the_metrics_path():
    port = _port()
    metrics = WorkerMetrics(slots=4)
    metrics.begin()
    metrics.end("failed", 0.3)
    metrics.discovery_error()
    environ = {"PDOS_METRICS_TOKEN": TOKEN, "PDOS_WORKER_METRICS_ADDRESS": f"127.0.0.1:{port}"}

    async def scenario():
        server = await serve_metrics(
            lambda: metrics.render(database_up=1, stopping=False), environ=environ
        )
        base = f"http://127.0.0.1:{port}"
        try:
            return [
                await asyncio.to_thread(_get, base + PATH),
                await asyncio.to_thread(_get, base + PATH, "wrong"),
                await asyncio.to_thread(_get, base + "/health", TOKEN),
                await asyncio.to_thread(_get, base + PATH, TOKEN, "POST"),
                await asyncio.to_thread(_get, base + PATH, TOKEN),
            ]
        finally:
            server.close()
            await server.wait_closed()

    missing, wrong, other, post, ok = asyncio.run(scenario())
    assert missing[0] == wrong[0] == 401 and wrong[1]["WWW-Authenticate"] == "Bearer"
    assert other[0] == post[0] == 404
    status, headers, body = ok
    assert status == 200 and headers["Cache-Control"] == "no-store"
    assert headers["Content-Type"] == "text/plain; version=0.0.4"
    assert "pdos_up 1" in body and "pdos_database_up 1" in body
    assert "pdos_worker_activity_slots 4" in body and "pdos_worker_stopping 0" in body
    assert "pdos_worker_discovery_errors_total 1" in body
    assert probe.parse_activities(body) == {"completed": 0, "failed": 1, "cancelled": 0}
    labels = {line.split("{", 1)[1].split("=")[0] for line in body.splitlines() if "{" in line}
    assert labels == {"outcome", "le"}


@pytest.mark.skipif(not BINARY.is_file(), reason="local Temporal binary missing")
def test_real_worker_counts_attempts_by_outcome():
    from temporalio.client import WorkflowFailureError
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    async def scenario():
        environment = await WorkflowEnvironment.start_local(dev_server_existing_path=str(BINARY))
        metrics = WorkerMetrics(slots=2)
        try:
            queue = "metrics-" + str(uuid4())
            with ThreadPoolExecutor(max_workers=2) as executor:
                async with Worker(
                    environment.client,
                    task_queue=queue,
                    workflows=[fixture.RunOne],
                    activities=fixture.ACTIVITIES,
                    activity_executor=executor,
                    max_concurrent_activities=2,
                    graceful_shutdown_timeout=timedelta(seconds=5),
                    interceptors=[ActivityMetrics(metrics)],
                ):
                    for name in ("shutdown_fixture_cooperative", "shutdown_fixture_fail"):
                        try:
                            await environment.client.execute_workflow(
                                fixture.RunOne.run,
                                args=[name, 0.1],
                                id=f"{name}-{uuid4()}",
                                task_queue=queue,
                            )
                        except WorkflowFailureError:
                            pass
            return metrics
        finally:
            await environment.shutdown()

    metrics = asyncio.run(scenario())
    assert metrics.outcomes == {"completed": 1, "failed": 1, "cancelled": 0}
    assert metrics.running == 0 and metrics.duration_count == 2


def _thresholds():
    return probe.load_config(CONFIG)["thresholds"]


def test_probe_reads_the_worker_and_alerts_when_it_stops_answering():
    thresholds = _thresholds()
    state = {}
    for _ in range(thresholds["liveness_consecutive_failures"]):
        alerts, state = probe.evaluate(probe.Signals(worker_live=False), state, thresholds)
    assert [a.key for a in alerts] == ["liveness:worker"] and alerts[0].severity == "critical"
    alerts, state = probe.evaluate(probe.Signals(worker_live=True), state, thresholds)
    assert alerts == [] and state["failures"]["worker"] == 0


def test_activity_failure_rate_uses_two_scrapes_and_ignores_cancellations():
    thresholds = _thresholds()
    first = {"completed": 50, "failed": 1, "cancelled": 0}
    alerts, state = probe.evaluate(probe.Signals(activities=first), {}, thresholds)
    assert alerts == []
    second = {"completed": 58, "failed": 3, "cancelled": 9}  # 2 of 10 finished = 20 %
    alerts, state = probe.evaluate(probe.Signals(activities=second), state, thresholds)
    assert [a.key for a in alerts] == ["activity_failure:worker"] and alerts[0].value == 0.2
    quiet = {"completed": 61, "failed": 4, "cancelled": 30}  # 1 of 4: below the sample
    alerts, state = probe.evaluate(probe.Signals(activities=quiet), state, thresholds)
    assert alerts == []
    restarted = {"completed": 0, "failed": 2, "cancelled": 0}
    alerts, _ = probe.evaluate(probe.Signals(activities=restarted), state, thresholds)
    assert alerts == []


def test_probe_collects_the_worker_scrape_with_the_metrics_token(monkeypatch):
    seen = []

    def fake(url, timeout=5.0, headers=None):
        seen.append((url, headers))
        return True, 'pdos_worker_activities_total{outcome="completed"} 7\n'

    monkeypatch.setattr(probe, "http_ok", fake)
    config = {
        "targets": {"worker_metrics_url": "http://127.0.0.1:9464/ops/metrics"},
        "thresholds": _thresholds(),
    }
    signals = probe.collect(config, environ={"PDOS_METRICS_TOKEN": TOKEN})
    assert signals.worker_live is True and signals.activities == {"completed": 7}
    assert seen == [("http://127.0.0.1:9464/ops/metrics", {"Authorization": f"Bearer {TOKEN}"})]
    assert probe.collect(config, environ={}).worker_live is None
