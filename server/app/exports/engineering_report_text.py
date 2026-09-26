"""Readable engineering reports over retained source versions and decisions."""

import json
from typing import Any

from app.exports.definition_documents import value
from app.exports.weekly_report_text import STATUS as WORK_STATUS
from app.exports.weekly_report_text import moment

VERSIONS = {"dfmea": "internal-project-dfmea.v2", "gate": "internal-project-gate.v2"}
GATE_STATUS = {
    "preparing": "准备中",
    "reviewing": "评审中",
    "pending": "待办理",
    "in_review": "评审中",
    "approved": "通过",
    "conditional": "有条件通过",
    "rejected": "退回",
    "hold": "暂缓",
    "open": "本轮开放",
    "completed": "本轮已结束",
    "superseded": "已被替代",
    "not_applicable": "不适用",
}
SLOTS = {"product": "产品", "engineering": "工程", "quality": "品质"}
REQUIREMENTS = {"required": "必签", "conditional": "按条件签核", "not_applicable": "不适用"}
CAUSE = {"unknown": "未知", "hypothesis": "待验证假设", "evidence_supported": "有引用依据支持"}


def shown(item: Any) -> str:
    return "未记录" if item is None or item == "" else str(item)


class Names:
    def __init__(self, people: list[dict[str, Any]]) -> None:
        self.names = {str(p["id"]): str(p["display_name"]) for p in people}

    def person(self, identity: Any) -> str:
        if identity is None:
            return "未指定"
        return self.names.get(str(identity), "原人员资料不可用（见来源索引）")

    def index(self) -> str:
        return "\n".join(f"{name}：{identity}" for identity, name in self.names.items())


def source_appendix(entry: dict[str, Any]) -> str:
    # Identical values share a display entry; every version/current association stays explicit.
    originals: dict[str, int] = {}

    def refs(items: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
        projected = []
        for ref in items:
            original = ref[field]
            number = None
            if original is not None:
                key = json.dumps(original, ensure_ascii=False, sort_keys=True)
                number = originals.setdefault(key, len(originals) + 1)
            projected.append(
                {
                    **{k: v for k, v in ref.items() if k != field},
                    field + "_原值编号": number,
                }
            )
        return projected

    associations = {
        "各版保存时来源": [
            {"版本": v["version"], "引用": refs(v["sources"], "value")} for v in entry["versions"]
        ],
        "最新修订当前来源": refs(entry["latest_sources"], "current_value"),
        "最新修订缺项": entry["latest_source_gaps"],
        "发布版当前来源": refs(entry["published_sources"], "current_value"),
        "发布版缺项": entry["published_source_gaps"],
    }
    return (
        "保存时来源与本次读取的对应关系；相同原值只展开一次，变化后的当前值独立编号。"
        "空编号表示当前不可读取，不补原值。\n"
        + value(associations)
        + "\n\n"
        + "\n\n".join(
            f"原值 {number}\n{value(json.loads(original))}"
            for original, number in originals.items()
        )
    )


def dfmea_sections(
    entries: list[dict[str, Any]], people: list[dict[str, Any]]
) -> list[tuple[str, str]]:
    names = Names(people)
    result: list[tuple[str, str]] = []
    for entry in entries:
        latest, published = entry["latest"], entry["published_version"]
        prefix = latest["body"]["title"]
        result.append(
            (
                prefix + " · 当前与发布版",
                f"最新修订：版本 {latest['version']}\n"
                + (
                    f"当前发布版：版本 {published['version']}"
                    if published
                    else "当前发布版：尚未发布"
                )
                + (
                    "\n最新修订已发布。"
                    if published and published["id"] == latest["id"]
                    else "\n最新修订与当前发布版分列；未发布修订不代替已发布内容。"
                )
                + f"\n最新修订来源待重核：{len(entry['latest_source_gaps'])} 项"
                + f"\n发布版来源待重核：{len(entry['published_source_gaps'])} 项"
                "\n仅覆盖本次所选条目。",
            )
        )
        for version in entry["versions"]:
            b = version["body"]
            controls = (
                "\n\n".join(
                    f"控制 {i} · {'预防' if ctl['kind'] == 'prevention' else '检测'}："
                    f"{ctl['description']}\n"
                    f"原验证安排：{ctl['verification']}\n控制编号：{ctl['key']}"
                    for i, ctl in enumerate(b["controls"], 1)
                )
                or "尚无控制措施记录。"
            )
            refs = (
                "\n\n".join(
                    f"引用 {i} · {r['kind']}：{r['id']}\n关联依据：{r['relationship']}\n"
                    f"原件位置：{shown(r['locator'])}"
                    for i, r in enumerate(b["references"], 1)
                )
                or "尚无引用依据。"
            )
            result.append(
                (
                    f"{prefix} · 修订 {version['version']} 完整风险判断",
                    f"本版名称：{b['title']}\n修订人：{names.person(version['created_by_user_id'])}；"
                    f"修订时间：{moment(version['created_at'])}\n设计功能：{b['design_function']}\n"
                    f"失效模式：{b['failure_mode']}\n失效影响：{b['effect']}\n可能原因：{b['possible_cause']}\n"
                    f"原因状态：{CAUSE.get(b['cause_status'], b['cause_status'])}\n\n{controls}\n\n"
                    f"控制缺口：{b['control_gaps']}\n严重度 S：{shown(b['severity'])}；"
                    f"发生度 O：{shown(b['occurrence'])}；探测度 D：{shown(b['detection'])}\n"
                    f"评分方法：{b['scoring_method']}\n评分依据：{b['scoring_basis']}\n"
                    f"未评分说明：{shown(b['unknown_reason'])}\n下一步：{b['next_action']}\n"
                    f"修订依据：{b['reason']}\n\n{refs}",
                )
            )
        versions = {v["id"]: v["version"] for v in entry["versions"]}
        result.append(
            (
                prefix + " · 完整发布历史",
                "\n\n".join(
                    f"发布版本：{versions.get(p['version_id'], '原版本不可用')}\n"
                    f"发布人：{names.person(p['published_by_user_id'])}；"
                    f"时间：{moment(p['published_at'])}\n"
                    f"发布依据：{p['reason']}\n发布回执：{p['id']}"
                    for p in entry["publications"]
                )
                or "尚无具名发布记录；修订保存不代表发布。",
            )
        )
        result.append(
            (
                prefix + " · 来源版本索引与原值（供复核）",
                f"条目：{entry['entry_id']}\n"
                + "\n".join(f"修订 {v['version']}：{v['id']}" for v in entry["versions"])
                + "\n\n"
                + source_appendix(entry),
            )
        )
    result.append(("具名人员索引", names.index() or "尚无具名人员。"))
    return result


def gate_sections(actual: dict[str, Any], people: list[dict[str, Any]]) -> list[tuple[str, str]]:
    names, gate = Names(people), actual["gate"]
    rounds = {r["id"]: r["round_number"] for r in actual["rounds"]}
    result = [
        (
            "Gate当前记录",
            f"{gate['name']}（{gate['code']}）\n"
            f"状态：{GATE_STATUS.get(gate['status'], gate['status'])}\n"
            f"评审期限：{moment(gate['review_due_at'])}\n裁决人：{names.person(gate['decided_by_user_id'])}；"
            f"裁决时间：{moment(gate['decided_at'])}\n未重新计算当前就绪情况，以下按原记录与轮次阅读。",
        )
    ]
    for r in actual["rounds"]:
        signoffs = [s for s in actual["signoffs"] if s["round_id"] == r["id"]]
        assigned = r["routing_snapshot"].get("assignment", {}).get("signers", {})
        signatures = (
            "\n\n".join(
                f"{SLOTS.get(s['slot'], s['slot'])}席 · "
                f"{REQUIREMENTS.get(s['requirement'], s['requirement'])}\n"
                f"本轮原分派：{shown(assigned.get(s['slot'], {}).get('display_name'))}\n"
                f"结果：{GATE_STATUS.get(s['status'], s['status'])}；"
                f"签核人：{names.person(s['signed_by_user_id'])}\n"
                f"签核时间：{moment(s['signed_at'])}\n原意见：{shown(s['note'])}\n签核回执：{s['id']}"
                for s in signoffs
            )
            or "本轮没有签核记录。"
        )
        result.append(
            (
                f"正式第 {r['round_number']} 轮 · {GATE_STATUS.get(r['status'], r['status'])}",
                f"原政策版本：{r['policy_version']}\n发起人：{names.person(r['opened_by_user_id'])}；"
                f"发起时间：{moment(r['opened_at'])}\n结束人：{names.person(r['completed_by_user_id'])}；"
                f"结束时间：{moment(r['completed_at'])}\n替代人：{names.person(r['superseded_by_user_id'])}；"
                f"替代时间：{moment(r['superseded_at'])}\n"
                f"替代理由：{shown(r['supersede_reason'])}\n\n{signatures}",
            )
        )
    if not actual["rounds"]:
        result.append(("正式签核轮次", "尚无正式签核轮次；迁入记录不补造签核。"))
    legacy = [s for s in actual["signoffs"] if s["round_id"] not in rounds]
    if legacy:
        result.append(("未关联本报告正式轮次的签核（单列）", value(legacy)))
    result.append(
        (
            "原裁决与执行说明",
            "\n\n".join(
                f"{d['title']}\n"
                f"裁决人：{names.person(d['decided_by_user_id'])}；时间：{moment(d['decided_at'])}\n"
                f"原结论：{GATE_STATUS.get(d['outcome'], shown(d['outcome']))}\n"
                f"理由：{shown(d['rationale'])}\n"
                f"后续影响：{shown(d['consequence'])}\n"
                f"原执行说明：{shown(d['follow_up_note'])}\n裁决编号：{d['id']}"
                for d in actual["decisions"]
            )
            or "尚无正式裁决记录。",
        )
    )
    result.append(
        (
            "条件任务当前落实（与原裁决分列）",
            "以下为本次读取当前值；任务完成不改变原Gate裁决，旧条件原文未完整保存时不以当前值补造。\n\n"
            + (
                "\n\n".join(
                    f"{t['title']}\n负责人：{names.person(t['assignee_user_id'])}；"
                    f"状态：{WORK_STATUS.get(t['status'], t['status'])}\n"
                    f"目标日：{moment(t['due_date'])}；"
                    f"实际完成：{moment(t['completed_at'])}\n当前关闭依据要求：{shown(t['expected_output'])}\n"
                    f"任务编号：{t['id']}"
                    for t in actual["condition_tasks"]
                )
                or "没有读取到关联条件任务，不推定没有原条件。"
            ),
        )
    )
    result.append(
        (
            "加签要求",
            "\n\n".join(
                f"{SLOTS.get(a['slot'], a['slot'])}席 · "
                f"{REQUIREMENTS.get(a['requirement'], a['requirement'])}\n"
                f"当前{'启用' if a['active'] else '停用'}；"
                f"提出人：{names.person(a['added_by_user_id'])}\n"
                f"原依据：{a['reason']}\n登记时间：{moment(a['created_at'])}；最后更新：{moment(a['updated_at'])}"
                for a in actual["additions"]
            )
            or "尚无加签记录。",
        )
    )
    result.append(
        (
            "历史豁免",
            "\n\n".join(
                f"原要求：{a['requirement_key']}；原政策：{a['policy_version']}\n"
                f"批准人：{names.person(a['approved_by_user_id'])}；时间：{moment(a['created_at'])}\n"
                f"原依据：{a['reason']}"
                for a in actual["exemptions"]
            )
            or "尚无历史豁免记录。",
        )
    )
    result.append(
        (
            "迁入历史记录（不作正式签核）",
            "\n\n".join(
                f"原第 {h['round_number']} 轮 · {GATE_STATUS.get(h['decision'], h['decision'])}\n"
                f"原参与人：{shown(h['participants'])}\n核对人：{names.person(h['reviewed_by_user_id'])}；"
                f"评审时间：{moment(h['reviewed_at'])}\n"
                f"原条件：{shown(h['conditions'])}\n原说明：{shown(h['notes'])}\n"
                f"来源：{h['source_system']} / {h['source_id']}"
                for h in actual["historical_records"]
            )
            or "没有迁入历史记录。",
        )
    )
    tasks = {t["id"]: t for t in actual["condition_tasks"]}
    links = []
    for audit in actual["condition_links"]:
        context = audit["context"]
        related = (
            "、".join(
                tasks[identity]["title"] if identity in tasks else f"原任务当前不可用：{identity}"
                for identity in context.get("condition_task_ids", [])
            )
            or "原回执未登记条件任务"
        )
        original = (
            "\n\n".join(
                f"原条件：{item['title']}\n原负责人：{names.person(item['owner_user_id'])}；"
                f"原期限：{item['due_date']}\n原关闭依据要求：{item['closure_evidence']}\n"
                f"关联任务：{item['task_id']}"
                for item in context.get("conditions", [])
            )
            or "旧回执未保存原条件正文，不用当前任务内容替代。"
        )
        links.append(
            f"原轮次：{rounds.get(context.get('round_id'), '未关联本报告轮次')}；"
            f"裁决：{shown(context.get('decision_id'))}\n"
            f"原裁决关联任务（名称按本次读取）：{related}\n{original}\n"
            f"办理人：{names.person(audit['actor_user_id'])}；时间：{moment(audit['timestamp'])}"
        )
    result.append(("原条件裁决与任务关联", "\n\n".join(links) or "没有原条件裁决关联回执。"))
    result.append(("具名人员索引", names.index() or "尚无具名人员。"))
    result.append(("轮次政策、条件关联与原字段（供复核）", value(actual)))
    return result
