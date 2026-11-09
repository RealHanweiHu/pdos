"""Monitoring probe: four signals, suggested thresholds, DingTalk group alerts (D213).

Signals and where each comes from:

- liveness: GET the API ``/health`` and the Web sign-in page; the worker counts as
  live when its own ``/ops/metrics`` answers (D349);
- error rate: 5xx share between two scrapes of the API's ``/ops/metrics`` counters,
  and failed Activity attempts between two scrapes of the worker's;
- queue backlog: undelivered domain events (``ops_health_counters`` through the
  technical dispatch role, numbers only) and the Temporal task queue's backlog,
  backlog age and poller count;
- model failure rate: failed or unknown 小Pai model calls in a time window, from the
  same counter function, plus calls left open for more than ten minutes.

Thresholds come from the configuration file; the shipped values are suggestions
awaiting the user's decision. Without a DingTalk webhook the probe writes alerts as
JSON lines to stdout only. It never calls a model and never sends business data.

  python -m pdos_next.ops.probe --config config/ops/monitoring.example.json --once
"""

import argparse
import asyncio
import json
import os
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import UUID

from pdos_next.ops.alerts import LogSink, sink_from_environment

SCHEMA_VERSION = "pdos-monitoring-v1"


@dataclass(frozen=True)
class Alert:
    key: str
    signal: str
    severity: str
    summary: str
    value: float | int | None = None
    threshold: float | int | None = None


@dataclass
class Signals:
    api_live: bool | None = None
    web_live: bool | None = None
    worker_live: bool | None = None
    responses: dict | None = None
    activities: dict | None = None
    tenants: dict = field(default_factory=dict)
    temporal: dict | None = None
    errors: list = field(default_factory=list)


# ---------------------------------------------------------------- collection


def http_ok(url: str, timeout: float = 5.0, headers=None) -> tuple[bool, str]:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 400, response.read(1 << 20).decode("utf-8", "replace")
    except Exception:
        return False, ""


def parse_responses(text: str) -> dict:
    """``pdos_http_responses_total{class="5xx"} 3`` lines into {"5xx": 3, ...}."""
    found = {}
    for line in text.splitlines():
        if line.startswith('pdos_http_responses_total{class="'):
            label, value = line.split("}", 1)
            found[label.split('"')[1]] = int(float(value.strip()))
    return found


def parse_activities(text: str) -> dict:
    """``pdos_worker_activities_total{outcome="failed"} 2`` lines into {"failed": 2, ...}."""
    found = {}
    for line in text.splitlines():
        if line.startswith('pdos_worker_activities_total{outcome="'):
            label, value = line.split("}", 1)
            found[label.split('"')[1]] = int(float(value.strip()))
    return found


def tenant_counters(dispatch_url: str, tenants: list[UUID], window_seconds: int) -> dict:
    from sqlalchemy import text

    from pdos_next.core.database import engine_for, tenant_session

    engine = engine_for(dispatch_url)
    result = {}
    try:
        for tenant in tenants:
            with tenant_session(engine, tenant) as session:
                row = (
                    session.execute(
                        text("SELECT * FROM ops_health_counters(:t,:w)"),
                        {"t": tenant, "w": window_seconds},
                    )
                    .mappings()
                    .one()
                )
            result[str(tenant)] = {key: float(value) for key, value in row.items()}
    finally:
        engine.dispose()
    return result


async def temporal_queue(address: str, namespace: str, task_queue: str) -> dict:
    from temporalio.api.enums.v1 import TaskQueueType
    from temporalio.api.taskqueue.v1 import TaskQueue
    from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
    from temporalio.client import Client

    client = await Client.connect(address, namespace=namespace)
    result = {}
    for name, kind in (
        ("workflow", TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW),
        ("activity", TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY),
    ):
        response = await client.workflow_service.describe_task_queue(
            DescribeTaskQueueRequest(
                namespace=namespace,
                task_queue=TaskQueue(name=task_queue),
                task_queue_type=kind,
                report_stats=True,
            )
        )
        stats = response.stats if response.HasField("stats") else None
        result[name] = {
            "pollers": len(response.pollers),
            "backlog_count": int(stats.approximate_backlog_count) if stats else 0,
            "backlog_age_seconds": (
                stats.approximate_backlog_age.ToTimedelta().total_seconds() if stats else 0.0
            ),
        }
    return result


def collect(config: dict, environ=os.environ) -> Signals:
    targets, thresholds = config["targets"], config["thresholds"]
    signals = Signals()
    if url := targets.get("api_health_url"):
        signals.api_live = http_ok(url)[0]
    if url := targets.get("web_health_url"):
        signals.web_live = http_ok(url)[0]
    token = environ.get("PDOS_METRICS_TOKEN")
    if (url := targets.get("api_metrics_url")) and token:
        ok, body = http_ok(url, headers={"Authorization": f"Bearer {token}"})
        signals.responses = parse_responses(body) if ok else None
        if not ok:
            signals.errors.append("api_metrics_unavailable")
    if (url := targets.get("worker_metrics_url")) and token:
        # The worker has no other endpoint: an unanswered scrape is a liveness failure.
        ok, body = http_ok(url, headers={"Authorization": f"Bearer {token}"})
        signals.worker_live = ok
        signals.activities = parse_activities(body) if ok else None
    tenants = [UUID(v) for v in environ.get("PDOS_WORKFLOW_TENANTS", "").split(",") if v.strip()]
    if tenants and environ.get("DISPATCH_DATABASE_URL"):
        try:
            signals.tenants = tenant_counters(
                environ["DISPATCH_DATABASE_URL"], tenants, int(thresholds["model_window_seconds"])
            )
        except Exception as error:
            signals.errors.append(f"database_counters_unavailable:{type(error).__name__}")
    if environ.get("PDOS_TEMPORAL_ADDRESS") and targets.get("temporal_task_queue"):
        try:
            signals.temporal = asyncio.run(
                temporal_queue(
                    environ["PDOS_TEMPORAL_ADDRESS"],
                    environ.get("PDOS_TEMPORAL_NAMESPACE", "pdos-next"),
                    targets["temporal_task_queue"],
                )
            )
        except Exception as error:
            signals.errors.append(f"temporal_unavailable:{type(error).__name__}")
    return signals


# ---------------------------------------------------------------- evaluation


def evaluate(signals: Signals, state: dict, thresholds: dict) -> tuple[list[Alert], dict]:
    """Pure: alerts that hold now, and the state to keep for the next round."""
    alerts, new_state = [], {"failures": dict(state.get("failures", {}))}
    for name, live in (
        ("api", signals.api_live),
        ("web", signals.web_live),
        ("worker", signals.worker_live),
    ):
        if live is None:
            continue
        count = 0 if live else new_state["failures"].get(name, 0) + 1
        new_state["failures"][name] = count
        if count >= thresholds["liveness_consecutive_failures"]:
            alerts.append(
                Alert(
                    f"liveness:{name}",
                    "liveness",
                    "critical",
                    f"{name.upper()} 探活连续 {count} 次失败",
                    count,
                    thresholds["liveness_consecutive_failures"],
                )
            )
    for item in signals.errors:
        alerts.append(
            Alert(f"probe:{item.split(':')[0]}", "probe", "warning", f"探针取数失败：{item}")
        )
    if signals.responses is not None:
        new_state["responses"] = signals.responses
        previous = state.get("responses")
        if previous and sum(signals.responses.values()) >= sum(previous.values()):
            delta = {k: signals.responses.get(k, 0) - previous.get(k, 0) for k in signals.responses}
            total, errors = sum(delta.values()), delta.get("5xx", 0)
            if total >= thresholds["error_rate_min_requests"]:
                ratio = errors / total
                if ratio >= thresholds["error_rate_5xx_ratio"]:
                    alerts.append(
                        Alert(
                            "error_rate:api",
                            "error_rate",
                            "critical",
                            f"API 5xx 占比 {ratio:.1%}（{errors}/{total}）",
                            round(ratio, 4),
                            thresholds["error_rate_5xx_ratio"],
                        )
                    )
    if signals.activities is not None:
        new_state["activities"] = signals.activities
        alerts += _activity_failures(signals.activities, state.get("activities"), thresholds)
    for tenant, row in sorted(signals.tenants.items()):
        short = tenant[:8]
        if row["outbox_oldest_seconds"] >= thresholds["outbox_oldest_seconds"]:
            alerts.append(
                Alert(
                    f"backlog:outbox_age:{short}",
                    "queue_backlog",
                    "warning",
                    f"租户 {short} 最早未投递事件已等待 {int(row['outbox_oldest_seconds'])} 秒",
                    row["outbox_oldest_seconds"],
                    thresholds["outbox_oldest_seconds"],
                )
            )
        if row["outbox_pending"] >= thresholds["outbox_pending"]:
            alerts.append(
                Alert(
                    f"backlog:outbox_count:{short}",
                    "queue_backlog",
                    "warning",
                    f"租户 {short} 未投递事件 {int(row['outbox_pending'])} 条",
                    row["outbox_pending"],
                    thresholds["outbox_pending"],
                )
            )
        finished, failed = row["model_calls_finished"], row["model_calls_failed"]
        if finished >= thresholds["model_failure_min_calls"]:
            ratio = failed / finished
            if ratio >= thresholds["model_failure_ratio"]:
                alerts.append(
                    Alert(
                        f"model_failure:{short}",
                        "model_failure",
                        "warning",
                        f"租户 {short} 模型调用失败或结果未知 {ratio:.0%}"
                        f"（{int(failed)}/{int(finished)}）",
                        round(ratio, 4),
                        thresholds["model_failure_ratio"],
                    )
                )
        if row["model_calls_open_long"] >= thresholds["model_calls_open_long"]:
            alerts.append(
                Alert(
                    f"model_open:{short}",
                    "model_failure",
                    "warning",
                    f"租户 {short} 有 {int(row['model_calls_open_long'])} 个模型调用"
                    "超过 10 分钟未结束",
                    row["model_calls_open_long"],
                    thresholds["model_calls_open_long"],
                )
            )
    if signals.temporal is not None:
        for kind, row in signals.temporal.items():
            if row["pollers"] < thresholds["temporal_min_pollers"]:
                alerts.append(
                    Alert(
                        f"backlog:pollers:{kind}",
                        "queue_backlog",
                        "critical",
                        f"Temporal {kind} 队列没有 Worker 在取任务",
                        row["pollers"],
                        thresholds["temporal_min_pollers"],
                    )
                )
            if row["backlog_count"] >= thresholds["temporal_backlog_count"]:
                alerts.append(
                    Alert(
                        f"backlog:temporal_count:{kind}",
                        "queue_backlog",
                        "warning",
                        f"Temporal {kind} 队列积压 {row['backlog_count']} 个任务",
                        row["backlog_count"],
                        thresholds["temporal_backlog_count"],
                    )
                )
            if row["backlog_age_seconds"] >= thresholds["temporal_backlog_age_seconds"]:
                alerts.append(
                    Alert(
                        f"backlog:temporal_age:{kind}",
                        "queue_backlog",
                        "warning",
                        f"Temporal {kind} 队列最早任务已等待 {int(row['backlog_age_seconds'])} 秒",
                        row["backlog_age_seconds"],
                        thresholds["temporal_backlog_age_seconds"],
                    )
                )
    return alerts, new_state


def _activity_failures(current: dict, previous: dict | None, thresholds: dict) -> list[Alert]:
    """Failed share of Activity attempts finished since the last scrape.

    Cancelled attempts (worker shutdown, D348) are not failures. A restarted worker
    starts its counters at zero, so a drop in the total skips that round.
    """
    if not previous or sum(current.values()) < sum(previous.values()):
        return []
    failed = current.get("failed", 0) - previous.get("failed", 0)
    finished = failed + current.get("completed", 0) - previous.get("completed", 0)
    minimum = thresholds.get("activity_failure_min_count", 5)
    ratio_threshold = thresholds.get("activity_failure_ratio", 0.2)
    if finished < minimum or failed / finished < ratio_threshold:
        return []
    ratio = failed / finished
    return [
        Alert(
            "activity_failure:worker",
            "error_rate",
            "warning",
            f"Worker Activity 失败 {ratio:.0%}（{failed}/{finished}）",
            round(ratio, 4),
            ratio_threshold,
        )
    ]


def route(
    alerts: list[Alert], state: dict, repeat_seconds: int, now: float
) -> tuple[list, list, dict]:
    """Which alerts to send now, which recovered, and the active set to remember."""
    active = dict(state.get("active", {}))
    current = {alert.key: alert for alert in alerts}
    send = [a for a in alerts if a.key not in active or now - active[a.key] >= repeat_seconds]
    recovered = sorted(key for key in active if key not in current)
    for alert in send:
        active[alert.key] = now
    for key in recovered:
        active.pop(key)
    return send, recovered, active


def run_once(config: dict, state_path: Path, sink, environ=os.environ, now=None) -> dict:
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    signals = collect(config, environ)
    alerts, new_state = evaluate(signals, state, config["thresholds"])
    now = time.time() if now is None else now
    send, recovered, active = route(
        alerts, state, int(config["alerts"]["repeat_minutes"]) * 60, now
    )
    if send or recovered:
        sink.deliver(send, recovered, environment=config.get("environment_label", "pdos"))
    new_state["active"] = active
    state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    state_path.write_text(json.dumps(new_state, ensure_ascii=False, indent=2) + "\n")
    state_path.chmod(0o600)
    return {
        "signals": asdict(signals),
        "alerts": [asdict(a) for a in alerts],
        "sent": [a.key for a in send],
        "recovered": recovered,
    }


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text())
    if config.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unknown monitoring configuration version")
    required = {
        "liveness_consecutive_failures",
        "error_rate_5xx_ratio",
        "error_rate_min_requests",
        "outbox_oldest_seconds",
        "outbox_pending",
        "temporal_backlog_count",
        "temporal_backlog_age_seconds",
        "temporal_min_pollers",
        "model_failure_ratio",
        "model_failure_min_calls",
        "model_window_seconds",
        "model_calls_open_long",
    }
    missing = required - set(config["thresholds"])
    if missing:
        raise ValueError(f"Monitoring thresholds missing: {sorted(missing)}")
    return config


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--state",
        type=Path,
        default=Path(os.environ.get("PDOS_PROBE_STATE", ".local/ops/probe-state.json")),
    )
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    sink = sink_from_environment(config["alerts"]) or LogSink()
    while True:
        result = run_once(config, args.state, sink)
        print(
            json.dumps(
                {
                    "alerts": result["alerts"],
                    "sent": result["sent"],
                    "recovered": result["recovered"],
                },
                ensure_ascii=False,
            )
        )
        if args.once:
            return 0
        time.sleep(int(config.get("interval_seconds", 60)))


if __name__ == "__main__":
    raise SystemExit(main())
