"""Public approach summaries and observed work, never provider-private reasoning."""

from collections.abc import Callable
from time import monotonic
from typing import Any


class ReplyProgress:
    def __init__(self, send: Callable[[dict[str, Any]], None], run_id: str) -> None:
        self.send, self.run_id = send, run_id
        self.started = monotonic()
        self.steps: list[dict[str, Any]] = []
        self.earlier_steps_omitted = 0

    def snapshot(self, state: str = "running") -> dict[str, Any]:
        return {
            "state": state,
            "elapsed_ms": max(0, round((monotonic() - self.started) * 1000)),
            "steps": [dict(step) for step in self.steps],
            "earlier_steps_omitted": self.earlier_steps_omitted,
        }

    def step(self, key: str, label: str, detail: str = "", state: str = "running") -> None:
        existing = next((step for step in self.steps if step["key"] == key), None)
        if existing is None:
            if self.steps and self.steps[-1]["state"] == "running":
                self.steps[-1]["state"] = "completed"
            if len(self.steps) >= 16:
                self.steps.pop(0)
                self.earlier_steps_omitted += 1
            existing = {"key": key, "at_ms": self.snapshot()["elapsed_ms"]}
            self.steps.append(existing)
        if (existing.get("label"), existing.get("detail"), existing.get("state")) == (
            label,
            detail,
            state,
        ):
            return
        existing.update(label=label[:1024], detail=detail[:512], state=state)
        self.send(
            {
                "type": "status",
                "message": label,
                "run_id": self.run_id,
                "process": self.snapshot(),
            }
        )

    def emit(self, event: dict[str, Any]) -> None:
        if event.get("type") == "status":
            label = str(event["message"])
            self.step(
                str(event.get("step_key") or label),
                label,
                str(event.get("detail") or ""),
                str(event.get("step_state") or "running"),
            )
        else:
            self.send(event)

    def finish(self, result: dict[str, Any]) -> dict[str, Any]:
        state = (
            "completed"
            if result["status"] == "answered"
            else ("stopped" if result.get("error_code") == "REPLY_CANCELLED" else "failed")
        )
        if result.get("error_code") == "REPLY_SOURCE_CHANGED":
            self.earlier_steps_omitted = 0
            self.steps = [
                {
                    "key": "source_changed",
                    "label": "来源或权限已变化，处理停止",
                    "detail": "",
                    "state": "failed",
                    "at_ms": self.snapshot()["elapsed_ms"],
                }
            ]
        elif self.steps and self.steps[-1]["state"] == "running":
            self.steps[-1]["state"] = state
        return self.snapshot(state)
