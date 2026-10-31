"""Versioned stage paths; a stage decision never substitutes professional approval."""

from copy import deepcopy

STAGES = {
    "concept": ("概念", ["g0"]),
    "planning": ("计划", ["baseline"]),
    "design": ("设计", ["engineering"]),
    "evt": ("EVT", ["engineering"]),
    "dvt": ("DVT", ["engineering", "manufacturing"]),
    "pvt": ("PVT", ["engineering", "manufacturing", "delivery"]),
    "mp": ("量产导入", ["engineering", "manufacturing", "delivery"]),
}
TEMPLATES = {
    "standard@1": ("完整开发", ["concept", "planning", "design", "evt", "dvt", "pvt", "mp"]),
    "derivative@1": ("派生项目", ["planning", "design", "dvt", "pvt"]),
    "small-change@1": ("小改项目", ["planning", "design", "dvt"]),
}
ENTRY = {
    "concept": ["g0"],
    "planning": ["g0"],
    "design": ["baseline"],
    "evt": ["engineering"],
    "dvt": ["engineering"],
    "pvt": ["manufacturing"],
    "mp": ["manufacturing", "delivery"],
}
LABELS = {
    "g0": "G0 立项决定与定义来源",
    "baseline": "当前计划的具名批准基线",
    "engineering": "当前用途的工程签核与产品验证条件",
    "manufacturing": "当前用途的制造签核与准备条件",
    "delivery": "交付数量、地点或地区与适用范围",
}


def templates():
    return [
        {
            "id": key,
            "name": name,
            "stages": [
                {"key": s, "name": STAGES[s][0], "rules": STAGES[s][1], "entry_rules": ENTRY[s]}
                for s in keys
            ],
        }
        for key, (name, keys) in TEMPLATES.items()
    ]


def aggregate(states):
    for state in ("BLOCKED", "UNKNOWN", "READY_WITH_CONDITIONS"):
        if state in states:
            return state
    return "READY" if states else "UNKNOWN"


def health(*, gate_state, overdue, pending, adopted):
    # Fixed, rule-only priority. Missing required evidence remains unknown.
    if gate_state == "BLOCKED":
        return {"state": "blocked", "label": "受阻", "reason": "当前出口存在硬阻塞"}
    if gate_state == "UNKNOWN" or not adopted:
        return {"state": "unknown", "label": "待核对", "reason": "当前必需依据不完整或已失效"}
    if overdue:
        return {
            "state": "risk",
            "label": "有风险",
            "reason": f"{overdue} 项当前承诺已逾期且未确认履行",
        }
    if pending:
        return {
            "state": "pending_approval",
            "label": "待批准",
            "reason": "出口条件已具备，等待具名阶段决定",
        }
    if gate_state == "READY_WITH_CONDITIONS":
        return {"state": "risk", "label": "有条件", "reason": "当前出口仍受固定例外条件约束"}
    return {"state": "normal", "label": "正常", "reason": "当前出口依据齐全且无已知逾期承诺"}


def stable(value):
    """Strip computation timestamps only; retain expiry/validity and all evidence."""
    if isinstance(value, dict):
        return {k: stable(v) for k, v in value.items() if k not in {"checked_at", "as_of"}}
    if isinstance(value, list):
        return [stable(v) for v in value]
    return deepcopy(value)
