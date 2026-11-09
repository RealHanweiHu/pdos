"""D348: the worker stops taking work at once, lets running Activities finish within the
grace period, gives up on stuck ones within a hard limit, and repeated stop signals
start only one shutdown.

The Temporal cases run a private in-memory dev server from the inspected local binary
(skipped without it); no database, network service or model is used.
"""

import asyncio
import os
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from pdos_next.ops.worker_metrics import ActivityMetrics, WorkerMetrics
from pdos_next.workflows.shutdown import GracefulShutdown, grace_period, serve
from tests.workflows import shutdown_fixture as fixture

BINARY = Path(__file__).resolve().parents[3] / ".local/tools/temporal"
temporal = pytest.mark.skipif(not BINARY.is_file(), reason="local Temporal binary missing")


def test_grace_period_defaults_to_sixty_seconds(monkeypatch):
    monkeypatch.delenv("PDOS_WORKER_SHUTDOWN_GRACE_SECONDS", raising=False)
    assert grace_period() == timedelta(seconds=60)


@pytest.mark.parametrize("value,seconds", [("0", 0), ("120", 120), ("3600", 3600)])
def test_grace_period_is_configurable(monkeypatch, value, seconds):
    monkeypatch.setenv("PDOS_WORKER_SHUTDOWN_GRACE_SECONDS", value)
    assert grace_period() == timedelta(seconds=seconds)


@pytest.mark.parametrize("value", ["3601", "-1", "ten", "", "1.5"])
def test_invalid_grace_period_stops_the_worker(monkeypatch, value):
    monkeypatch.setenv("PDOS_WORKER_SHUTDOWN_GRACE_SECONDS", value)
    with pytest.raises(RuntimeError):
        grace_period()


def test_repeated_signals_start_one_shutdown():
    async def scenario():
        shutdown = GracefulShutdown(timedelta(seconds=1))
        loop = asyncio.get_running_loop()
        shutdown.install(loop)
        try:
            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.wait_for(shutdown.requested.wait(), 2)
            os.kill(os.getpid(), signal.SIGTERM)
            os.kill(os.getpid(), signal.SIGINT)
            await asyncio.sleep(0.2)
            assert shutdown.request("code") is False
        finally:
            loop.remove_signal_handler(signal.SIGTERM)
            loop.remove_signal_handler(signal.SIGINT)
        return shutdown

    shutdown = asyncio.run(scenario())
    assert shutdown.stopping and shutdown.reason == "SIGTERM" and shutdown.repeats == 3


async def _environment():
    from temporalio.testing import WorkflowEnvironment

    return await WorkflowEnvironment.start_local(dev_server_existing_path=str(BINARY))


def _worker(client, queue, executor, shutdown, metrics):
    from temporalio.worker import Worker

    return Worker(
        client,
        task_queue=queue,
        workflows=[fixture.RunOne],
        activities=fixture.ACTIVITIES,
        activity_executor=executor,
        max_concurrent_activities=2,
        graceful_shutdown_timeout=shutdown.grace,
        interceptors=[ActivityMetrics(metrics)],
    )


async def _started(seconds=10):
    for _ in range(int(seconds * 20)):
        if fixture.STARTED.is_set():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("fixture Activity did not start")


def _has(history, field):
    return any(event.HasField(field) for event in history.events)


@pytest.fixture
def released():
    fixture.STARTED.clear()
    fixture.RELEASE.clear()
    yield
    fixture.RELEASE.set()


@temporal
def test_running_activity_finishes_and_no_new_task_is_taken(released):
    async def scenario():
        environment = await _environment()
        try:
            client, queue = environment.client, "shutdown-" + str(uuid4())
            shutdown = GracefulShutdown(timedelta(seconds=20))
            metrics = WorkerMetrics(slots=2)
            intake_stopped = asyncio.Event()

            async def stop_intake():
                intake_stopped.set()

            with ThreadPoolExecutor(max_workers=2) as executor:
                worker = _worker(client, queue, executor, shutdown, metrics)
                serving = asyncio.create_task(serve(worker, shutdown, stop_intake=stop_intake))
                first = await client.start_workflow(
                    fixture.RunOne.run,
                    args=["shutdown_fixture_hold", 30.0],
                    id="running-" + str(uuid4()),
                    task_queue=queue,
                )
                await _started()
                assert shutdown.request("test") is True
                assert shutdown.request("test-again") is False
                await asyncio.sleep(0.5)
                assert intake_stopped.is_set() and metrics.running == 1
                # Arrives while the first Activity is still running: nobody takes it.
                second = await client.start_workflow(
                    fixture.RunOne.run,
                    args=["shutdown_fixture_cooperative", 0.1],
                    id="late-" + str(uuid4()),
                    task_queue=queue,
                )
                await asyncio.sleep(1.0)
                assert not serving.done()
                fixture.RELEASE.set()
                clean = await asyncio.wait_for(serving, 15)
            return (
                clean,
                await first.fetch_history(),
                await second.fetch_history(),
                metrics,
            )
        finally:
            await environment.shutdown()

    clean, first, second, metrics = asyncio.run(scenario())
    assert clean is True
    assert _has(first, "activity_task_completed_event_attributes")
    assert not _has(second, "workflow_task_started_event_attributes")
    assert metrics.outcomes == {"completed": 1, "failed": 0, "cancelled": 0}
    assert metrics.running == 0


@temporal
def test_cooperative_activity_is_cancelled_after_the_grace_period(released):
    async def scenario():
        environment = await _environment()
        try:
            client, queue = environment.client, "shutdown-" + str(uuid4())
            shutdown = GracefulShutdown(timedelta(seconds=0.5), cancel_window=timedelta(seconds=5))
            metrics = WorkerMetrics(slots=2)

            async def stop_intake():
                return None

            with ThreadPoolExecutor(max_workers=2) as executor:
                worker = _worker(client, queue, executor, shutdown, metrics)
                serving = asyncio.create_task(serve(worker, shutdown, stop_intake=stop_intake))
                await client.start_workflow(
                    fixture.RunOne.run,
                    args=["shutdown_fixture_cooperative", 60.0],
                    id="cooperative-" + str(uuid4()),
                    task_queue=queue,
                )
                await _started()
                started = time.monotonic()
                shutdown.request("test")
                clean = await asyncio.wait_for(serving, 15)
                return clean, time.monotonic() - started, metrics
        finally:
            await environment.shutdown()

    clean, seconds, metrics = asyncio.run(scenario())
    assert clean is True and seconds < 5.5
    assert metrics.outcomes["cancelled"] == 1 and metrics.running == 0


@temporal
def test_activity_that_ignores_cancellation_is_abandoned_within_the_limit(released):
    async def scenario():
        environment = await _environment()
        executor = ThreadPoolExecutor(max_workers=2)
        try:
            client, queue = environment.client, "shutdown-" + str(uuid4())
            shutdown = GracefulShutdown(timedelta(seconds=0.5), cancel_window=timedelta(seconds=1))
            metrics = WorkerMetrics(slots=2)

            async def stop_intake():
                return None

            worker = _worker(client, queue, executor, shutdown, metrics)
            serving = asyncio.create_task(serve(worker, shutdown, stop_intake=stop_intake))
            await client.start_workflow(
                fixture.RunOne.run,
                args=["shutdown_fixture_hold", 60.0],
                id="stuck-" + str(uuid4()),
                task_queue=queue,
            )
            await _started()
            started = time.monotonic()
            shutdown.request("test")
            clean = await asyncio.wait_for(serving, 10)
            seconds = time.monotonic() - started
            # Free the thread so this test process can finish its own cleanup.
            fixture.RELEASE.set()
            await asyncio.wait_for(worker.shutdown(), 10)
            return clean, seconds
        finally:
            executor.shutdown(wait=True)
            await environment.shutdown()

    clean, seconds = asyncio.run(scenario())
    assert clean is False
    assert 1.5 <= seconds < 4.0
