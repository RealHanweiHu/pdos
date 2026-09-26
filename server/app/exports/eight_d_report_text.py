"""Readable 8D projection; original quality facts remain in the export snapshot."""

from typing import Any

from app.exports.definition_documents import value
from app.exports.weekly_report_text import SEVERITY, moment

VERSION = "internal-project-8d.v2"
STATUS = {
    "open": "已登记",
    "containment": "遏制办理",
    "root_cause": "根因调查与审核",
    "action": "措施执行",
    "verification": "有效性验证",
    "closed": "已关闭",
    "draft": "待审核",
    "approved": "已批准",
    "superseded": "已被修订替代",
    "planned": "已计划",
    "in_progress": "执行中",
    "completed": "已完成",
}
METHOD = {"5why": "5 Why", "fishbone": "鱼骨分析", "8d": "8D", "other": "其他方法"}
KINDS = {
    "document": "项目文件",
    "test_run": "实际测试",
    "event": "项目事件",
    "decision": "决策",
    "evidence_snapshot": "共享证据版本",
}


def people_ids(item: Any) -> set[str]:
    if isinstance(item, dict):
        return {
            str(v) for k, v in item.items() if k.endswith("_user_id") and v is not None
        } | set().union(*(people_ids(v) for v in item.values()))
    if isinstance(item, list):
        return set().union(*(people_ids(v) for v in item))
    return set()


def sections(actual: dict[str, Any], people: list[dict[str, Any]]) -> list[tuple[str, str]]:
    chain = actual["quality_chain"]
    ncr, roots, actions, reviews = (chain[k] for k in ("ncr", "root_causes", "actions", "reviews"))
    names = {str(p["id"]): p["display_name"] for p in people}

    def person(identity: Any) -> str:
        return names.get(str(identity), "原人员资料不可用（见来源索引）") if identity else "未指定"

    def show(item: Any) -> str:
        return "未记录" if item is None or item == "" else str(item)

    refs = list(
        dict.fromkeys(
            (r["kind"], r["reference"])
            for item in [*roots, *actions, *reviews]
            for r in item["evidence_refs"]
        )
    )
    ref_numbers = {ref: i for i, ref in enumerate(refs, 1)}

    def citations(item: dict[str, Any]) -> str:
        numbers = [str(ref_numbers[(r["kind"], r["reference"])]) for r in item["evidence_refs"]]
        return "依据：" + ("证据 " + "、".join(numbers) if numbers else "未登记引用")

    def action_text(a: dict[str, Any]) -> str:
        return (
            f"{'纠正措施' if a['action_type'] == 'corrective' else '预防措施'}："
            f"{a['description']}\n"
            f"负责人：{person(a['owner_user_id'])}；登记人：{person(a['created_by_user_id'])}\n"
            f"状态：{STATUS.get(a['status'], a['status'])}；目标日期：{moment(a['due_date'])}\n"
            f"实际开始：{moment(a['started_at'])}；实际完成：{moment(a['completed_at'])}\n"
            f"完成说明：{show(a['completion_summary'])}\n{citations(a)}"
        )

    root_text = [
        f"版本 {r['version']} · {STATUS.get(r['status'], r['status'])}\n"
        f"分析人：{person(r['analyst_user_id'])}；方法：{METHOD.get(r['method'], r['method'])}\n"
        f"调查过程：{r['analysis']}\n根因判断：{r['root_cause']}\n"
        f"批准人：{person(r['approved_by_user_id'])}；批准时间：{moment(r['approved_at'])}\n"
        f"登记时间：{moment(r['created_at'])}；被替代时间：{moment(r['superseded_at'])}\n{citations(r)}"
        for r in roots
    ]
    review_text = [
        f"第 {r['review_number']} 次复核 · "
        f"{'有效' if r['result'] == 'effective' else '无效，需补充措施'}\n"
        f"独立复核人：{person(r['reviewer_user_id'])}；复核时间：{moment(r['reviewed_at'])}\n"
        f"原判据：{r['criteria']}\n原观察结束时间：{moment(r['observation_due_at'])}\n"
        f"实际结果和未覆盖范围：{r['actual_result']}\n{citations(r)}"
        for r in reviews
    ]
    root = actual["current_approved_root"]
    current_root = (
        f"当前有效已批准根因：版本 {root['version']}。"
        if root
        else "当前没有有效已批准根因，草稿和已替代记录仅供追溯。"
    )
    corrective = [action_text(a) for a in actions if a["action_type"] == "corrective"]
    preventive = [action_text(a) for a in actions if a["action_type"] == "preventive"]
    completed = [action_text(a) for a in actions if a["status"] == "completed"]
    evidence = []
    for ref in actual["evidence"]:
        record = ref["current_record"]
        identity = (ref["kind"], ref["reference"])
        number = ref_numbers.get(identity)
        evidence.append(
            f"证据 {number} · {KINDS.get(ref['kind'], ref['kind'])}\n"
            + (
                "原判断后有变化，以下当前值不能替代原判断时的版本。\n"
                if ref["changed_since_quality_basis"]
                else "以下为本次读取的当前记录。\n"
            )
            + value(record)
        )
    missing = [
        f"证据 {ref_numbers.get((r['kind'], r['reference']))} · {KINDS.get(r['kind'], r['kind'])}："
        "当前不可采用或判断后有变化，须补充核对。"
        for r in actual["missing_evidence"]
    ]
    index = [f"NCR：{ncr['id']}；原投诉：{ncr['complaint_id']}"]
    index.extend(f"根因版本 {r['version']}：{r['id']}" for r in roots)
    index.extend(f"措施 {i}：{a['id']}" for i, a in enumerate(actions, 1))
    index.extend(f"复核 {r['review_number']}：{r['id']}" for r in reviews)
    index.extend(
        f"证据 {i} · {KINDS.get(kind, kind)}：{reference}"
        for i, (kind, reference) in enumerate(refs, 1)
    )
    index.extend(f"人员 {person(identity)}：{identity}" for identity in sorted(people_ids(actual)))
    return [
        (
            "D1 团队及职责",
            f"NCR负责人：{person(ncr['owner_user_id'])}\n"
            f"登记人：{person(ncr['created_by_user_id'])}\n"
            f"专门8D团队确认：未登记。实际调查、措施及复核人员按以下具名记录列示。",
        ),
        (
            "D2 问题描述",
            f"编号：{ncr['code']}\n"
            f"不符合事实：{ncr['nonconformity']}\n"
            f"原要求：{ncr['requirement_reference']}\n"
            f"严重度：{SEVERITY.get(ncr['severity'], ncr['severity'])}\n"
            f"影响范围：{show(ncr['affected_scope'])}；影响数量：{show(ncr['affected_quantity'])}\n"
            f"登记：{moment(ncr['created_at'])}；目标日期：{moment(ncr['target_date'])}",
        ),
        (
            "D3 临时遏制",
            f"实际遏制：{show(ncr['containment_action'])}\n"
            f"完成时间：{moment(ncr['containment_completed_at'])}",
        ),
        ("D4 根因分析与批准", current_root + "\n\n" + ("\n\n".join(root_text) or "尚无调查记录。")),
        ("D5 纠正措施计划与原选择", "\n\n".join(corrective) or "尚无纠正措施记录。"),
        (
            "D6 实施和有效性验证",
            "已完成措施\n" + ("\n\n".join(completed) or "尚无完成记录。") + f"\n"
            f"\n"
            f"当前有效性判据：{show(ncr['effectiveness_criteria'])}\n"
            f"观察结束：{moment(ncr['observation_due_at'])}\n"
            f"\n"
            f"完整复核历史\n"
            f"" + ("\n\n".join(review_text) or "尚无独立有效性复核，不能由措施完成推定有效。"),
        ),
        (
            "D7 预防措施",
            ("\n\n".join(preventive) or "尚无预防措施记录。") + f"\n"
            f"\n"
            f"不适用依据：{show(ncr['preventive_not_applicable_reason'])}\n"
            f"不适用裁决人：{person(ncr['preventive_disposition_approved_by_user_id'])}；时间：{moment(ncr['preventive_disposition_approved_at'])}",
        ),
        (
            "D8 关闭记录及待补认可",
            f"NCR状态：{STATUS.get(ncr['status'], ncr['status'])}\n"
            f"关闭人：{person(ncr['closed_by_user_id'])}；关闭时间：{moment(ncr['closed_at'])}\n"
            f"专门8D团队认可：未登记。NCR关闭不代表8D报告已获批准。",
        ),
        (
            "缺失或变化的依据",
            "\n".join(missing) or "本次读取未发现上述当前依据缺项；不代表完整8D验收。",
        ),
        ("来源索引（供回查）", "\n".join(index)),
        ("当前证据原字段（供复核）", "\n\n".join(evidence) or "当前没有可读取的结果依据。"),
    ]
