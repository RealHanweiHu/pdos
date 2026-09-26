"""Reuse team arithmetic with actual research series and separate object strata."""

from collections import defaultdict
from typing import Any

from app.domain.value_workpack_calculations import workpack_study_summary as team_study_summary
from app.domain.value_workpack_calculations import workpack_summary as team_summary

VERSION = "research-workpack-value-descriptive.v1"
IDENTITY = ("subject_kind", "subject_id", "subject_series_id")


def _unit(value: dict[str, Any]) -> dict[str, Any]:
    return {**value, "task_id": f"{value.get('subject_kind')}:{value.get('subject_series_id')}"}


def _adapt(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        **entry,
        "workpack": _unit(entry["workpack"]),
        "samples": [_unit(s) for s in entry["samples"]],
    }


def workpack_summary(
    workpack: dict[str, Any],
    samples: list[dict[str, Any]],
    deliveries: list[dict[str, Any]],
    receptions: list[dict[str, Any]],
    closure: dict[str, Any] | None,
) -> dict[str, Any]:
    result = team_summary(
        **_adapt(
            {
                "workpack": workpack,
                "samples": samples,
                "deliveries": deliveries,
                "receptions": receptions,
                "closure": closure,
            }
        )
    )
    result.pop("task_id", None)
    result.update({k: workpack.get(k) for k in IDENTITY})
    result["calculation_version"] = VERSION
    result["interpretation"] = (
        "按实际立项前工作系列及事前团队范围核对；同人重叠取并集，不同人员相加。"
        "全员活动结束且交付已接受或明确失败/取消后才列完整投入；缺项、撤回及失败保留。"
        "独立接收是测量回执，不代替业务发布或专业批准；未校准阈值，不推定因果收益。"
    )
    by_id = {str(s.get("sample_id")): s for s in samples}
    for person in result["participants"]:
        sample = by_id.get(str(person.get("sample_id")), {})
        person.update({k: sample.get(k) for k in IDENTITY})
        if person.get("activity"):
            person["activity"]["scope"] = "own_preproject_participant_activity"
        person["reasons"] = [
            "mismatched_subject_series" if r == "mismatched_task_id" else r
            for r in person["reasons"]
        ]
    return result


def workpack_study_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        grouped[str(entry["workpack"]["subject_kind"])].append(entry)
    strata: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    totals = {"without_pair_key_count": 0, "complete_pair_count": 0, "incomplete_pair_count": 0}
    for kind, values in sorted(grouped.items()):
        result = team_study_summary([_adapt(e) for e in values])
        originals = {str(e["workpack"]["id"]): e["workpack"] for e in values}
        for name in totals:
            totals[name] += result[name]
        strata.extend({**s, "subject_kind": kind} for s in result["strata"])
        for pair in result["pairs"]:
            for pack in pair["workpacks"]:
                original = originals[str(pack["workpack_id"])]
                pack.pop("task_id", None)
                pack.update({k: original.get(k) for k in IDENTITY})
            pairs.append({**pair, "subject_kind": kind})
    return {
        "calculation_version": VERSION,
        "status": "descriptive_only" if entries else "not_assessed",
        "workpack_count": len(entries),
        **totals,
        "strata": strata,
        "pairs": pairs,
        "acceptance_status": "not_assessed",
        "threshold_version": None,
        "interpretation": (
            "按对象类别、证据类别、场景、复杂度、流程版本和职责/首次使用构成分层；"
            "同系列修订不增加独立业务样本，跨对象类别不配对。"
            "首轮接受率分母为已有首轮裁决的交付，待接收、未交付与不可读另列；失败与取消保留。"
            "描述差额不等于因果收益、业务批准或阶段验收通过。"
        ),
    }
