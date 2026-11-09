"""Worker process metrics and their token-gated scrape listener (D349).

Same rules as the API's ``GET /ops/metrics`` (``metrics.py``): Prometheus text
format, the same ``PDOS_METRICS_TOKEN`` sent as a bearer, and no Activity name,
workflow, user or tenant label. Without a token of at least 32 characters the
listener is not opened at all. It binds ``PDOS_WORKER_METRICS_ADDRESS`` (default
``127.0.0.1:9464``) and answers only ``GET /ops/metrics``; keep it on the internal
network, for the monitoring probe.

Activity outcomes are counted by a Temporal interceptor, so no Activity changes.
"""

import asyncio
import logging
import os
import threading
import time
from collections.abc import Callable

from temporalio.exceptions import CancelledError
from temporalio.worker import ActivityInboundInterceptor, ExecuteActivityInput, Interceptor

from pdos_next.ops.metrics import MEDIA_TYPE, PATH, authorized, metrics_token

logger = logging.getLogger(__name__)

DEFAULT_ADDRESS = "127.0.0.1:9464"
BUCKETS = (0.1, 0.5, 1.0, 5.0, 15.0, 60.0, 300.0, 900.0, 3600.0)
OUTCOMES = ("completed", "failed", "cancelled")
HEAD_LIMIT = 16384
READ_SECONDS = 5


class WorkerMetrics:
    def __init__(self, *, slots: int):
        self.lock = threading.Lock()
        self.started = time.time()
        self.slots = slots
        self.running = 0
        self.outcomes = dict.fromkeys(OUTCOMES, 0)
        self.buckets = [0] * len(BUCKETS)
        self.duration_sum = 0.0
        self.duration_count = 0
        self.discovery_errors = 0

    def begin(self) -> None:
        with self.lock:
            self.running += 1

    def end(self, outcome: str, seconds: float) -> None:
        with self.lock:
            self.running -= 1
            self.outcomes[outcome] += 1
            self.duration_sum += seconds
            self.duration_count += 1
            for index, bound in enumerate(BUCKETS):
                if seconds <= bound:
                    self.buckets[index] += 1

    def discovery_error(self) -> None:
        with self.lock:
            self.discovery_errors += 1

    def render(self, *, database_up: int | None, stopping: bool) -> str:
        with self.lock:
            running, outcomes = self.running, dict(self.outcomes)
            buckets, total, count = list(self.buckets), self.duration_sum, self.duration_count
            errors = self.discovery_errors
        lines = [
            "# HELP pdos_up The worker process answered this scrape.",
            "# TYPE pdos_up gauge",
            "pdos_up 1",
            "# HELP pdos_process_start_time_seconds Unix time the worker process started.",
            "# TYPE pdos_process_start_time_seconds gauge",
            f"pdos_process_start_time_seconds {self.started:.3f}",
        ]
        if database_up is not None:
            lines += [
                "# HELP pdos_database_up The application role could run SELECT 1.",
                "# TYPE pdos_database_up gauge",
                f"pdos_database_up {database_up}",
            ]
        lines += [
            "# HELP pdos_worker_stopping 1 while the worker is shutting down (D348).",
            "# TYPE pdos_worker_stopping gauge",
            f"pdos_worker_stopping {int(stopping)}",
            "# HELP pdos_worker_activity_slots Activities the worker runs at once.",
            "# TYPE pdos_worker_activity_slots gauge",
            f"pdos_worker_activity_slots {self.slots}",
            "# HELP pdos_worker_activities_running Activities running now.",
            "# TYPE pdos_worker_activities_running gauge",
            f"pdos_worker_activities_running {running}",
            "# HELP pdos_worker_activities_total Finished Activity attempts by outcome.",
            "# TYPE pdos_worker_activities_total counter",
        ]
        lines += [f'pdos_worker_activities_total{{outcome="{k}"}} {v}' for k, v in outcomes.items()]
        lines += [
            "# HELP pdos_worker_activity_duration_seconds Activity attempt duration.",
            "# TYPE pdos_worker_activity_duration_seconds histogram",
        ]
        lines += [
            f'pdos_worker_activity_duration_seconds_bucket{{le="{bound}"}} {value}'
            for bound, value in zip(BUCKETS, buckets, strict=True)
        ]
        lines += [
            f'pdos_worker_activity_duration_seconds_bucket{{le="+Inf"}} {count}',
            f"pdos_worker_activity_duration_seconds_sum {total:.6f}",
            f"pdos_worker_activity_duration_seconds_count {count}",
            "# HELP pdos_worker_discovery_errors_total Failed rounds of a discovery step.",
            "# TYPE pdos_worker_discovery_errors_total counter",
            f"pdos_worker_discovery_errors_total {errors}",
        ]
        return "\n".join(lines) + "\n"


class ActivityMetrics(Interceptor):
    def __init__(self, metrics: WorkerMetrics):
        self.metrics = metrics

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _CountingInbound(next, self.metrics)


class _CountingInbound(ActivityInboundInterceptor):
    def __init__(self, next: ActivityInboundInterceptor, metrics: WorkerMetrics):
        super().__init__(next)
        self.metrics = metrics

    async def execute_activity(self, input: ExecuteActivityInput):
        self.metrics.begin()
        started, outcome = time.monotonic(), "failed"
        try:
            result = await self.next.execute_activity(input)
            outcome = "completed"
            return result
        except (CancelledError, asyncio.CancelledError):
            outcome = "cancelled"
            raise
        finally:
            self.metrics.end(outcome, time.monotonic() - started)


def listen_address(environ=os.environ) -> tuple[str, int]:
    raw = environ.get("PDOS_WORKER_METRICS_ADDRESS", DEFAULT_ADDRESS)
    host, _, port = raw.rpartition(":")
    if not host or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise RuntimeError("PDOS_WORKER_METRICS_ADDRESS must be host:port")
    return host, int(port)


def _response(status: str, body: bytes = b"", headers: tuple[str, ...] = ()) -> bytes:
    head = [f"HTTP/1.1 {status}", f"Content-Length: {len(body)}", "Connection: close"]
    return ("\r\n".join([*head, *headers, "", ""])).encode() + body


async def serve_metrics(render: Callable[[], str], environ=os.environ) -> asyncio.Server | None:
    """Open the scrape listener, or return None when metrics are off.

    ``render`` may block (it checks the database), so it runs in a thread.
    """
    token = metrics_token(environ)
    if token is None:
        return None
    host, port = listen_address(environ)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            async with asyncio.timeout(READ_SECONDS):
                head = await reader.readuntil(b"\r\n\r\n")
            request, *fields = head.decode("latin-1").split("\r\n")
            method, target, *_ = request.split(" ") + ["", ""]
            headers = {
                name.strip().lower(): value.strip()
                for name, _, value in (line.partition(":") for line in fields if ":" in line)
            }
            if method != "GET" or target != PATH:
                writer.write(_response("404 Not Found"))
            elif not authorized(headers.get("authorization", ""), token):
                writer.write(_response("401 Unauthorized", headers=("WWW-Authenticate: Bearer",)))
            else:
                body = (await asyncio.to_thread(render)).encode()
                writer.write(
                    _response(
                        "200 OK",
                        body,
                        (f"Content-Type: {MEDIA_TYPE}", "Cache-Control: no-store"),
                    )
                )
            await writer.drain()
        except (TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            pass
        except Exception as error:
            logger.warning("Worker metrics scrape failed: %s", type(error).__name__)
        finally:
            writer.close()

    server = await asyncio.start_server(handle, host, port, limit=HEAD_LIMIT)
    logger.info("Worker metrics listening on %s:%s%s", host, port, PATH)
    return server
