"""Human-readable audit clauses and original approvals, with a retained source appendix."""

from typing import Any

from app.exports.definition_documents import value
from app.exports.engineering_report_text import Names, gate_sections, shown
from app.exports.weekly_report_text import moment

VERSION = "internal-audit-evidence.v2"
APPLICABILITY = {"applicable": "适用", "not_applicable": "具名说明不适用", "unconfirmed": "待确认"}
CLASSIFICATIONS = {"internal": "内部", "confidential": "机密", "restricted": "受限"}
KINDS = {"gate": "Gate 签核与裁决", "ecn": "ECN / ECR 签核", "document": "项目文件原件"}
STATES = {
    "draft": "草稿",
    "submitted": "已提交",
    "analyzing": "分析中",
    "approved": "已批准",
    "rejected": "已退回",
    "cancelled": "已取消",
    "pending": "待办理",
    "released": "已发布",
    "erp_handoff": "已转执行",
    "in_review": "审核中",
}


def sections(actual: dict[str, Any], people: list[dict[str, Any]]) -> list[tuple[str, str]]:
    names = Names(people)
    source_numbers = {(s["kind"], s["id"]): n for n, s in enumerate(actual["sources"], 1)}
    result: list[tuple[str, str]] = []
    for n, clause in enumerate(actual["clauses"], 1):
        refs = (
            "\n\n".join(
                f"依据 {source_numbers[(ref['kind'], ref['id'])]} · {KINDS[ref['kind']]}\n"
                f"原件位置：{ref['position']}\n条款对应：{ref['relevance']}\n"
                f"人工登记有效截止日：{shown(ref['valid_until'])}；"
                + (
                    "已过期，须补核"
                    if ref["expired"]
                    else "未登记有效期，不推定有效"
                    if not ref["valid_until"]
                    else "尚未超过登记日期，不代替有效性核实"
                )
                for ref in clause["evidence"]
            )
            or "尚未选择原依据。"
        )
        result.append(
            (
                f"条款 {n} · {clause['standard']} / {clause['clause']}",
                f"标准或客户要求版本：{clause['edition']}\n核对要求：{clause['requirement']}\n"
                f"适用性：{APPLICABILITY[clause['applicability']]}\n适用范围与判断依据：{clause['rationale']}\n"
                f"待补项与未覆盖范围：{clause['missing'] or '未登记缺项，不代表资料齐全'}\n"
                f"\n{refs}",
            )
        )
    for n, source in enumerate(actual["sources"], 1):
        body, kind = source["record"], source["kind"]
        prefix = f"依据 {n} · {KINDS[kind]}"
        if kind == "gate":
            result.extend(
                (prefix + " · " + title, text)
                for title, text in gate_sections(body["actual"], people)
                if title not in {"具名人员索引", "轮次政策、条件关联与原字段（供复核）"}
            )
        elif kind == "document":
            doc = body["document"]
            classification = CLASSIFICATIONS.get(doc["classification"], doc["classification"])
            result.append(
                (
                    prefix,
                    f"原文件：{doc['filename']}\n文件类型：{doc['media_type']}\n"
                    f"资料级别：{classification}\n"
                    f"登记时间：{moment(doc['created_at'])}\n原件编号：{doc['id']}\n"
                    f"原件校验：{doc['sha256']}\n完整文件须另行加入附件包；本报告只列原件索引。",
                )
            )
        else:
            for key, label in (("ecr", "原工程变更申请"), ("ecn", "工程变更通知")):
                record = body[key]
                actor = (
                    record.get("approved_by_user_id")
                    if key == "ecr"
                    else record.get("effectivity_decided_by_user_id")
                )
                when = (
                    record.get("approved_at")
                    if key == "ecr"
                    else record.get("effectivity_decided_at")
                )
                result.append(
                    (
                        prefix + " · " + label,
                        f"{record['title']}（{record['code']}）\n"
                        f"状态：{STATES.get(record['status'], record['status'])}\n"
                        f"批准/生效裁决人：{names.person(actor)}；时间：{moment(when)}\n"
                        f"原批准说明：{shown(record.get('approval_note'))}\n原对象编号：{record['id']}",
                    )
                )
            result.append(
                (
                    prefix + " · 原裁决",
                    "\n\n".join(
                        f"{shown(d.get('title'))}\n原结论：{shown(d.get('outcome'))}\n"
                        f"原理由：{shown(d.get('rationale'))}\n后续影响：{shown(d.get('consequence'))}\n"
                        f"具名人：{names.person(d.get('decided_by_user_id'))}；时间：{moment(d.get('decided_at'))}\n"
                        f"裁决编号：{d['id']}"
                        for d in body["decisions"]
                    )
                    or "尚无原裁决记录。",
                )
            )
            result.append(
                (
                    prefix + " · 办理历史",
                    "\n\n".join(
                        f"原动作：{log['action']}\n办理人：{names.person(log['actor_user_id'])}；时间：{moment(log['timestamp'])}\n"
                        f"原回执：{log['id']}\n办理前：{value(log['before_snapshot'])}\n办理后：{value(log['after_snapshot'])}"
                        for log in body["approval_history"]
                    )
                    or "尚无原办理历史，不从当前字段补造。",
                )
            )
        if body.get("warnings"):
            result.append((prefix + " · 缺项与限制", "\n".join(body["warnings"])))
    result.append(("原来源索引与条款对应（供复核）", value(actual)))
    result.append(("本次组包具名人员索引", names.index() or "尚无具名人员。"))
    return result
