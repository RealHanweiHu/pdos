"""Deterministic cockpit rules (P34-6, §05.12.6; D37 ⑦, D76).

Every derived value in the single-project overview and the manager cockpit comes
from one of the rules below. Each rule is versioned and returned with the read
model, so a reader can see exactly how a number or a label was produced. No rule
calls a model, reads free text for meaning, or turns exit outcomes into a ratio.
"""

from datetime import UTC, date, datetime, timedelta

from pdos_next.domain.projects.governance.rules import HEALTH_RULES

DUE_SOON_DAYS = 7
DUTY_DAYS = 7

STAGE_NODES_MISSING = "阶段节点未建"
STAGE_NODES_REASON = (
    "阶段节点与框架出口成果尚未建立（W6 ④ D36，框架见 D34）；"
    "这里只列现行阶段模板的出口条件，不推算成果状态。"
)

RULES = (
    *(
        {
            "id": rule["id"],
            "version": rule["version"],
            "text": f"健康度“{rule['label']}”：{rule['when']}。",
        }
        for rule in HEALTH_RULES
    ),
    {
        "id": "cockpit.exit_conditions",
        "version": 1,
        "text": "出口按当前阶段模板的出口条件逐项显示规则结果（满足 / 有条件 / 未知 / 阻塞），"
        "不按任务、不按成果数量或比例计算；框架出口成果待阶段节点建成后接入。",
    },
    {
        "id": "cockpit.slip",
        "version": 1,
        "text": "节点滑期：关联门禁里程碑的预测最晚完成晚于基线，或晚于任一未履行的承诺；"
        "缺少预测、基线和承诺时为“未知”。只看当前值，不回溯本周内何时变化。",
    },
    {
        "id": "cockpit.actions",
        "version": 1,
        "text": "需要办理：阻塞（当前出口条件为阻塞、阻塞型外部等待未关闭）、"
        "待接收（任务已分派未承接、外部等待转交未接受）、"
        "待决定（阶段评审待具名决定、已提交成果待验收、承诺待接收人核对、任务待分派）。"
        "每条写明负责人；只列读者有权看到的记录。",
    },
    {
        "id": "cockpit.due_soon",
        "version": 1,
        "text": f"未来 {DUE_SOON_DAYS} 天到期：未履行承诺的承诺时间、G0 待办的期限落在今天起 "
        f"{DUE_SOON_DAYS} 天内；任务本身没有期限字段，不以计划预测充当期限。",
    },
    {
        "id": "cockpit.wait_overdue",
        "version": 1,
        "text": "超期外部等待：未关闭，且按已采用日历对方声明的承诺时间已过，或已到内部下次检查点；"
        "这不是正式违约判定。",
    },
    {
        "id": "cockpit.issues",
        "version": 1,
        "text": "问题：未关闭、未合并的品质问题，按记录的风险等级（严重、高、中、低、未分级）排序。"
        "P0/P1 分级尚未建立，不做映射。",
    },
    {
        "id": "cockpit.duty",
        "version": 1,
        "text": f"小Pai 值班摘要：近 {DUTY_DAYS} 天本项目中由小Pai 写入的业务回执，按操作计数；"
        "只读，不计入待办。",
    },
)

STATE_ORDER = {"BLOCKED": 0, "UNKNOWN": 1, "READY_WITH_CONDITIONS": 2, "READY": 3}
CONDITION_NAMES = {
    "READY": "满足",
    "READY_WITH_CONDITIONS": "有条件满足",
    "UNKNOWN": "未知",
    "BLOCKED": "阻塞",
}
ISSUE_RISK_ORDER = {"critical": 0, "high": 1, None: 2, "medium": 3, "low": 4}
ISSUE_RISK_NAMES = {
    "critical": "严重",
    "high": "高",
    "medium": "中",
    "low": "低",
    None: "未分级",
}
ACTION_KINDS = {"blocked": "阻塞", "receive": "待接收", "decide": "待决定"}
ACTION_ORDER = {"blocked": 0, "decide": 1, "receive": 2}


def aware(value):
    """Parse an ISO instant or date; a bare date means the start of that UTC day."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def exit_conditions(checks):
    """Gate checks as rule results with their own names; never summed or averaged."""
    return [
        {
            "key": check["key"],
            "label": check["label"],
            "state": check["state"],
            "state_label": CONDITION_NAMES.get(check["state"], "未知"),
        }
        for check in checks
    ]


def slip(timeline):
    """Compare the bound gate milestone's forecast with baseline and open commitments."""
    if not timeline:
        return {"state": "unknown", "reason": "尚未采用阶段模板或未关联门禁里程碑"}
    forecast = aware((timeline.get("forecast") or {}).get("latest_finish"))
    baseline = aware((timeline.get("baseline") or {}).get("latest_finish"))
    promised = [
        aware(c.get("promised_at"))
        for c in timeline.get("commitments") or []
        if c.get("promised_at") and not c.get("fulfilled")
    ]
    promised = [value for value in promised if value]
    if timeline.get("actual"):
        return {"state": "done", "reason": "节点已有具名阶段决定"}
    if forecast is None:
        return {"state": "unknown", "reason": "关联门禁里程碑没有可读预测"}
    against = []
    if baseline and forecast > baseline:
        against.append("基线")
    if any(forecast > value for value in promised):
        against.append("承诺")
    if against:
        return {"state": "late", "reason": f"预测晚于{'和'.join(against)}", "against": against}
    if baseline is None and not promised:
        return {"state": "unknown", "reason": "没有基线或承诺可比较"}
    return {"state": "on_track", "reason": "预测不晚于基线与承诺"}


def due_soon(at, value):
    """True when an instant or date falls between now and the window's end."""
    when = aware(value)
    return bool(when and at <= when <= at + timedelta(days=DUE_SOON_DAYS))


def overdue(at, value):
    when = aware(value)
    return bool(when and when < at)


def wait_overdue(clock):
    return bool(clock and clock.get("escalation") in {"claimed_commitment_due", "check_due"})


def issue_key(issue):
    return (ISSUE_RISK_ORDER.get(issue.get("risk"), 2), issue.get("recorded_at") or "")


def first_sentence(text):
    """The first sentence of a named status update, cut at Chinese or Western stops."""
    if not text:
        return None
    value = " ".join(str(text).split())
    for index, char in enumerate(value):
        if char in "。！？!?；;\n":
            return value[: index + 1]
        if char == "." and (index + 1 == len(value) or value[index + 1] == " "):
            return value[: index + 1]
    return value[:120]


def sort_actions(actions):
    return sorted(
        actions,
        key=lambda item: (
            ACTION_ORDER[item["kind"]],
            item.get("due_at") or "9999",
            item["title"],
        ),
    )


def summary(rows, *, principal_id):
    """Manager cockpit counts: whole projects or nodes, never percentages (P75-3)."""
    by_health = {rule["state"]: 0 for rule in HEALTH_RULES}
    for row in rows:
        state = row["health"]["state"]
        by_health[state] = by_health.get(state, 0) + 1
    return {
        "active": sum(1 for row in rows if row["project"]["status"] == "active"),
        "health": [
            {"state": rule["state"], "label": rule["label"], "count": by_health[rule["state"]]}
            for rule in HEALTH_RULES
        ],
        "slipped_nodes": sum(1 for row in rows if row["next_node"]["slip"]["state"] == "late"),
        "my_stage_decisions": sum(
            1
            for row in rows
            if row["review_pending"] and row["project"]["owner"]["id"] == str(principal_id)
        ),
    }
