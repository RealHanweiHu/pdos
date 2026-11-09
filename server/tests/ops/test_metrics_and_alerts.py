"""Request counters, token gate, alert rules and DingTalk robot format (D213). No database."""

import base64
import hashlib
import hmac
import io
import json
import urllib.parse
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from pdos_next.ops import alerts as alert_module
from pdos_next.ops import probe
from pdos_next.ops.metrics import PATH, register_metrics

TOKEN = "t" * 40
CONFIG = Path(__file__).resolve().parents[3] / "config/ops/monitoring.example.json"


def _app():
    app = FastAPI()
    register_metrics(app, None)

    @app.get("/ok")
    def ok():
        return {"ok": True}

    @app.get("/boom")
    def boom():
        raise HTTPException(500, "synthetic")

    return app


def test_metrics_endpoint_is_off_without_a_token_and_hidden_from_openapi(monkeypatch):
    monkeypatch.delenv("PDOS_METRICS_TOKEN", raising=False)
    client = TestClient(_app())
    assert client.get(PATH).status_code == 404
    monkeypatch.setenv("PDOS_METRICS_TOKEN", "short")
    assert client.get(PATH).status_code == 404
    assert PATH not in client.get("/openapi.json").json()["paths"]


def test_counts_responses_by_class_without_paths(monkeypatch):
    monkeypatch.setenv("PDOS_METRICS_TOKEN", TOKEN)
    client = TestClient(_app(), raise_server_exceptions=False)
    for path in ("/ok", "/ok", "/boom", "/missing"):
        client.get(path)
    assert client.get(PATH, headers={"Authorization": "Bearer wrong"}).status_code == 401
    response = client.get(PATH, headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    counts = probe.parse_responses(response.text)
    # Reads of the metrics endpoint itself are not counted.
    assert counts == {"1xx": 0, "2xx": 2, "3xx": 0, "4xx": 1, "5xx": 1}
    assert "/ok" not in response.text and "/boom" not in response.text
    assert "pdos_http_request_duration_seconds_count 4" in response.text


def _config():
    return probe.load_config(CONFIG)


def test_shipped_configuration_loads_and_leaves_user_decisions_open():
    config = _config()
    assert (
        config["on_call"]["primary"] is None
        and config["on_call"]["critical_response_minutes"] is None
    )
    assert config["pending_user_decision"]
    assert "PDOS_ALERT_DINGTALK_WEBHOOK" == config["alerts"]["webhook_env"]


def test_liveness_needs_consecutive_failures_and_recovers():
    thresholds = _config()["thresholds"]
    state = {}
    for _ in range(2):
        alerts, state = probe.evaluate(
            probe.Signals(api_live=False, web_live=True), state, thresholds
        )
        assert alerts == []
    alerts, state = probe.evaluate(probe.Signals(api_live=False, web_live=True), state, thresholds)
    assert [a.key for a in alerts] == ["liveness:api"] and alerts[0].severity == "critical"
    alerts, state = probe.evaluate(probe.Signals(api_live=True, web_live=True), state, thresholds)
    assert alerts == [] and state["failures"] == {"api": 0, "web": 0}


def test_error_rate_uses_the_difference_between_two_scrapes():
    thresholds = _config()["thresholds"]
    first = {"1xx": 0, "2xx": 100, "3xx": 0, "4xx": 5, "5xx": 1}
    alerts, state = probe.evaluate(probe.Signals(responses=first), {}, thresholds)
    assert alerts == []
    second = {**first, "2xx": 118, "5xx": 3}  # 20 new responses, 2 of them 5xx = 10 %
    alerts, state = probe.evaluate(probe.Signals(responses=second), state, thresholds)
    assert [a.key for a in alerts] == ["error_rate:api"] and alerts[0].value == 0.1
    restarted = {"1xx": 0, "2xx": 3, "3xx": 0, "4xx": 0, "5xx": 3}  # counters reset
    alerts, _ = probe.evaluate(probe.Signals(responses=restarted), state, thresholds)
    assert alerts == []


def test_backlog_and_model_failure_rules():
    thresholds = _config()["thresholds"]
    tenant = "12345678-0000-0000-0000-000000000000"
    row = {
        "outbox_pending": 250.0,
        "outbox_retrying": 3.0,
        "outbox_oldest_seconds": 600.0,
        "model_calls_finished": 10.0,
        "model_calls_failed": 3.0,
        "model_calls_open_long": 1.0,
    }
    temporal = {
        "workflow": {"pollers": 0, "backlog_count": 5, "backlog_age_seconds": 10.0},
        "activity": {"pollers": 2, "backlog_count": 150, "backlog_age_seconds": 400.0},
    }
    alerts, _ = probe.evaluate(
        probe.Signals(tenants={tenant: row}, temporal=temporal), {}, thresholds
    )
    assert sorted(a.key for a in alerts) == [
        "backlog:outbox_age:12345678",
        "backlog:outbox_count:12345678",
        "backlog:pollers:workflow",
        "backlog:temporal_age:activity",
        "backlog:temporal_count:activity",
        "model_failure:12345678",
        "model_open:12345678",
    ]
    quiet = {
        **row,
        "outbox_pending": 1.0,
        "outbox_oldest_seconds": 2.0,
        "model_calls_finished": 4.0,
        "model_calls_open_long": 0.0,
    }
    alerts, _ = probe.evaluate(probe.Signals(tenants={tenant: quiet}), {}, thresholds)
    assert alerts == []  # four calls are below the minimum sample for a failure rate


def test_route_sends_once_repeats_after_the_interval_and_reports_recovery():
    alert = probe.Alert("liveness:api", "liveness", "critical", "API 探活连续 3 次失败")
    send, recovered, active = probe.route([alert], {}, 1800, now=1000.0)
    assert send == [alert] and recovered == []
    send, recovered, active = probe.route([alert], {"active": active}, 1800, now=1600.0)
    assert send == [] and recovered == []
    send, recovered, active = probe.route([alert], {"active": active}, 1800, now=2900.0)
    assert send == [alert]
    send, recovered, active = probe.route([], {"active": active}, 1800, now=3000.0)
    assert send == [] and recovered == ["liveness:api"] and active == {}


def test_dingtalk_signature_matches_the_documented_algorithm():
    webhook = "https://oapi.dingtalk.com/robot/send?access_token=synthetic"
    secret, timestamp = "SECsynthetic", 1700000000000
    expected = base64.b64encode(
        hmac.new(secret.encode(), f"{timestamp}\n{secret}".encode(), hashlib.sha256).digest()
    )
    url = alert_module.signed_url(webhook, secret, timestamp)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["timestamp"] == [str(timestamp)] and query["sign"] == [expected.decode()]
    with pytest.raises(ValueError):
        alert_module.signed_url("http://oapi.dingtalk.com/robot/send?x=1", secret, timestamp)
    with pytest.raises(ValueError):
        alert_module.signed_url("https://example.com/robot/send?x=1", secret, timestamp)


def test_robot_sink_posts_markdown_and_never_without_configuration():
    assert alert_module.sink_from_environment(_config()["alerts"], environ={}) is None
    sent = []
    sink = alert_module.DingTalkRobotSink(
        "https://oapi.dingtalk.com/robot/send?access_token=synthetic",
        "SECsynthetic",
        mobiles=["13800000000"],
        transport=lambda url, body: sent.append((url, json.loads(body))) or {"errcode": 0},
        clock=lambda: 1700000000.0,
    )
    alert = probe.Alert("model_failure:12345678", "model_failure", "warning", "模型失败 30%")
    sink.deliver([alert], ["liveness:api"], environment="pilot")
    [(url, body)] = sent
    assert "sign=" in url and body["msgtype"] == "markdown"
    assert "模型失败 30%" in body["markdown"]["text"] and "已恢复" in body["markdown"]["text"]
    assert body["at"] == {"atMobiles": ["13800000000"], "isAtAll": False}
    rejecting = alert_module.DingTalkRobotSink(
        "https://oapi.dingtalk.com/robot/send?access_token=synthetic",
        "SECsynthetic",
        transport=lambda url, body: {"errcode": 310000},
    )
    with pytest.raises(RuntimeError, match="310000"):
        rejecting.deliver([alert], [], environment="pilot")


def test_run_once_without_channel_writes_json_lines_and_keeps_state(tmp_path, monkeypatch):
    config = _config()
    config["targets"] = {"api_health_url": "http://127.0.0.1:9/health"}  # nothing listens
    stream, state = io.StringIO(), tmp_path / "state.json"
    sink = alert_module.LogSink(stream)
    for round_number in range(3):
        result = probe.run_once(config, state, sink, environ={}, now=100.0 + round_number)
    assert result["sent"] == ["liveness:api"]
    [line] = stream.getvalue().splitlines()
    record = json.loads(line)
    assert record["channel"] == "log" and record["alerts"][0]["key"] == "liveness:api"
    assert state.stat().st_mode & 0o077 == 0
