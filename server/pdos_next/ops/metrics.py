"""Request counters and a token-gated Prometheus endpoint for the API process (D213).

Counts every HTTP response by status class and records latency, with no path,
user or tenant label. ``GET /ops/metrics`` is off unless PDOS_METRICS_TOKEN is set,
then needs that token as a bearer. It is not in the OpenAPI document, and the Web
BFF does not forward it: only the monitoring probe on the internal network reads it.
"""

import hmac
import os
import threading
import time

from fastapi import Request
from fastapi.responses import PlainTextResponse, Response

PATH = "/ops/metrics"
BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0)
MEDIA_TYPE = "text/plain; version=0.0.4"


def metrics_token(environ=os.environ) -> str | None:
    """The scrape token, or None when metrics are off (unset or under 32 characters)."""
    value = environ.get("PDOS_METRICS_TOKEN", "")
    return value if len(value) >= 32 else None


def authorized(header: str, token: str) -> bool:
    return hmac.compare_digest(header.encode(), f"Bearer {token}".encode())


class RequestMetrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.started = time.time()
        self.responses = {f"{n}xx": 0 for n in range(1, 6)}
        self.buckets = [0] * len(BUCKETS)
        self.duration_sum = 0.0
        self.duration_count = 0

    def observe(self, status: int, seconds: float) -> None:
        group = f"{min(max(status // 100, 1), 5)}xx"
        with self.lock:
            self.responses[group] += 1
            self.duration_sum += seconds
            self.duration_count += 1
            for index, bound in enumerate(BUCKETS):
                if seconds <= bound:
                    self.buckets[index] += 1

    def render(self, *, database_up: int | None) -> str:
        with self.lock:
            responses = dict(self.responses)
            buckets, total, count = list(self.buckets), self.duration_sum, self.duration_count
        lines = [
            "# HELP pdos_up The API process answered this scrape.",
            "# TYPE pdos_up gauge",
            "pdos_up 1",
            "# HELP pdos_process_start_time_seconds Unix time the API process started.",
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
            "# HELP pdos_http_responses_total HTTP responses by status class.",
            "# TYPE pdos_http_responses_total counter",
        ]
        lines += [f'pdos_http_responses_total{{class="{k}"}} {v}' for k, v in responses.items()]
        lines += [
            "# HELP pdos_http_request_duration_seconds HTTP request latency.",
            "# TYPE pdos_http_request_duration_seconds histogram",
        ]
        lines += [
            f'pdos_http_request_duration_seconds_bucket{{le="{bound}"}} {value}'
            for bound, value in zip(BUCKETS, buckets, strict=True)
        ]
        lines += [
            f'pdos_http_request_duration_seconds_bucket{{le="+Inf"}} {count}',
            f"pdos_http_request_duration_seconds_sum {total:.6f}",
            f"pdos_http_request_duration_seconds_count {count}",
        ]
        return "\n".join(lines) + "\n"


class CountingMiddleware:
    """Pure ASGI wrapper; the response itself is passed through unchanged."""

    def __init__(self, app, metrics: RequestMetrics):
        self.app, self.metrics = app, metrics

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") == PATH:
            await self.app(scope, receive, send)
            return
        started, status = time.monotonic(), 500

        async def observed(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, observed)
        finally:
            self.metrics.observe(status, time.monotonic() - started)


def database_up(engine) -> int:
    """1 when the application role can run SELECT 1, else 0."""
    from sqlalchemy import text

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return 1
    except Exception:
        return 0


def register_metrics(app, engine) -> RequestMetrics:
    metrics = RequestMetrics()
    app.add_middleware(CountingMiddleware, metrics=metrics)
    app.state.request_metrics = metrics

    @app.get(PATH, include_in_schema=False)
    def ops_metrics(request: Request):
        expected = metrics_token()
        if expected is None:
            return Response(status_code=404)
        if not authorized(request.headers.get("authorization", ""), expected):
            return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
        return PlainTextResponse(
            metrics.render(database_up=database_up(engine) if engine is not None else None),
            media_type=MEDIA_TYPE,
            headers={"Cache-Control": "no-store"},
        )

    return metrics
