"""Pure interpretation of typed-node progress for schedule calculations."""

from datetime import UTC, date, datetime
from typing import Any


def certification_status(source: Any) -> str:
    status = str(source["status"])
    expiry = source.get("valid_until")
    expiry = date.fromisoformat(expiry) if isinstance(expiry, str) else expiry
    if status == "valid" and expiry is not None and expiry < datetime.now(UTC).date():
        return "expired"
    return status


def additional_state(node: dict[str, Any]) -> dict[str, Any]:
    actual = node.get("actual") or {}
    kind, status = node["node_kind"], node["source_status"]
    start, finish = actual.get("started_at"), actual.get("finished_at")
    unknown = []
    if actual.get("correction_conflict"):
        unknown.append(actual["correction_conflict"])
    state = "todo"
    if start:
        state = "in_progress"
    if finish:
        state = "done"
    if kind == "gate" and actual.get("successful") is not True:
        # A completed review with hold/rejection is not an approved gate output.
        finish = None
        if status in ("hold", "conditional", "rejected"):
            state = "blocked"
    if status in ("cancelled", "skipped", "aborted"):
        finish = None
        state = "skipped"
    if kind == "tooling" and status == "completed" and actual.get("successful") is not True:
        finish = None
        state = "blocked"
        unknown.append("工装本轮尚未无条件接受，请处理原条件或后续轮次")
    if kind == "task":
        state = status
        if status in ("in_progress", "blocked", "done"):
            unknown.append("此任务尚未纳入正式计划，缺少可用的排程实际时间；须先补齐实际依据")
    if kind == "test_run" and node.get("source_draft_state") != "confirmed":
        unknown.append("测试轮次仍是待确认草稿，不能按正式执行估算")
    if kind == "certification" and status == "valid" and not finish:
        unknown.append("认证已有效但实际完成时间未知，不能用有效期替代")
    if kind == "certification" and status in ("expired", "revoked"):
        state = "blocked"
        finish = None
        unknown.append("证书已失效，后续完成资格需重新认证；原办理实绩继续保留")
    return {
        "node_id": node["id"],
        "node_kind": kind,
        "task_id": node.get("task_id"),
        "status": state,
        "actual_start": start,
        "actual_finish": finish,
        "input_unknown": unknown,
        "source_status": status,
        "source_outcome": actual.get("successful"),
        "completion_basis": "approved_gate"
        if kind == "gate"
        else "accepted_tooling_round"
        if kind == "tooling"
        else "execution_end",
    }
