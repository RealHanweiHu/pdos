"""Alert delivery to a DingTalk group robot, or to stdout when none is configured (D213).

The group robot's webhook URL and signing secret are credentials. They come from
environment variables named in the monitoring configuration, never from the file
itself, and are never printed. Until the DingTalk side is set up (D64) the probe
uses ``LogSink``. Messages carry the alert summary only: no business content.
"""

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
import urllib.request

ALLOWED_HOST = "oapi.dingtalk.com"


def signed_url(webhook: str, secret: str, timestamp_ms: int) -> str:
    """DingTalk custom robot signature: HMAC-SHA256 of "timestamp\\nsecret", base64."""
    parsed = urllib.parse.urlparse(webhook)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        raise ValueError("DingTalk robot webhook must be https://oapi.dingtalk.com/...")
    payload = f"{timestamp_ms}\n{secret}".encode()
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(digest))
    return f"{webhook}&timestamp={timestamp_ms}&sign={sign}"


def markdown(alerts, recovered, *, environment: str, mobiles=()) -> dict:
    lines = [f"### PDOS 告警 · {environment}"]
    for alert in alerts:
        level = "🔴" if alert.severity == "critical" else "🟠"
        lines.append(f"- {level} {alert.summary}（`{alert.key}`）")
    for key in recovered:
        lines.append(f"- ✅ 已恢复：`{key}`")
    lines.append("值班处理见 docs/runbooks/monitoring-and-on-call.md")
    if mobiles:
        lines.append(" ".join(f"@{m}" for m in mobiles))
    return {
        "msgtype": "markdown",
        "markdown": {"title": f"PDOS 告警 · {environment}", "text": "\n".join(lines)},
        "at": {"atMobiles": list(mobiles), "isAtAll": False},
    }


class LogSink:
    """No channel configured: one JSON line per round on stdout."""

    def __init__(self, stream=None):
        self.stream = stream or sys.stdout

    def deliver(self, alerts, recovered, *, environment: str):
        record = {
            "channel": "log",
            "environment": environment,
            "alerts": [
                {"key": a.key, "severity": a.severity, "summary": a.summary} for a in alerts
            ],
            "recovered": list(recovered),
        }
        self.stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.stream.flush()


class DingTalkRobotSink:
    def __init__(self, webhook: str, secret: str, *, mobiles=(), transport=None, clock=time.time):
        signed_url(webhook, secret, 0)  # validate the address early
        self.webhook, self.secret, self.mobiles = webhook, secret, tuple(mobiles)
        self.transport, self.clock = transport or self._post, clock

    @staticmethod
    def _post(url: str, body: bytes) -> dict:
        request = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read(1 << 16) or b"{}")

    def deliver(self, alerts, recovered, *, environment: str):
        url = signed_url(self.webhook, self.secret, int(self.clock() * 1000))
        body = json.dumps(
            markdown(alerts, recovered, environment=environment, mobiles=self.mobiles),
            ensure_ascii=False,
        ).encode()
        answer = self.transport(url, body)
        if answer.get("errcode", 0) != 0:
            # The probe keeps running; the failure is visible in its own log.
            raise RuntimeError(
                f"DingTalk robot rejected the alert: errcode {answer.get('errcode')}"
            )


def sink_from_environment(alerts_config: dict, environ=os.environ):
    webhook = environ.get(alerts_config.get("webhook_env", ""), "")
    secret = environ.get(alerts_config.get("secret_env", ""), "")
    if not webhook or not secret:
        return None
    mobiles = [
        m.strip()
        for m in environ.get(alerts_config.get("mention_mobiles_env", ""), "").split(",")
        if m.strip()
    ]
    return DingTalkRobotSink(webhook, secret, mobiles=mobiles)
