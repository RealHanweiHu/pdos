"""Reuse participant interval arithmetic, preserving pre-project object strata."""

from collections import defaultdict
from typing import Any

from app.domain.value_measurement_calculations import sample_summary as participant_summary
from app.domain.value_measurement_calculations import study_summary as participant_study_summary

VERSION = "research-participant-value-descriptive.v1"


def sample_summary(sample: dict[str, Any]) -> dict[str, Any]:
    result = participant_summary(sample)
    result.update(
        {
            "calculation_version": VERSION,
            "scope": "own_preproject_participant_activity",
            "subject_kind": sample.get("subject_kind"),
            "subject_id": sample.get("subject_id"),
            "subject_series_id": sample.get("subject_series_id"),
        }
    )
    return result


def study_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        grouped[str(sample["subject_kind"])].append(sample)
    strata, pairs = [], []
    totals = {
        "missing_activity_count": 0,
        "without_pair_key_count": 0,
        "complete_pair_count": 0,
        "incomplete_pair_count": 0,
    }
    for kind, values in sorted(grouped.items()):
        # The shared arithmetic's comparison unit is a task. Supply a typed
        # series identity solely inside the calculator, never as a project FK.
        adapted = [{**s, "task_id": s["subject_series_id"]} for s in values]
        result = participant_study_summary(adapted)
        for name in totals:
            totals[name] += result[name]
        for stratum in result["strata"]:
            strata.append(
                {
                    **{k: v for k, v in stratum.items() if k != "task_count"},
                    "subject_kind": kind,
                    "subject_series_count": stratum["task_count"],
                }
            )
        for pair in result["pairs"]:
            pairs.append({**pair, "subject_kind": kind})
    return {
        "calculation_version": VERSION,
        "status": "descriptive_only" if samples else "not_assessed",
        "sample_count": len(samples),
        "participant_count": len({str(s["participant_user_id"]) for s in samples}),
        "subject_series_count": len(
            {(s["subject_kind"], str(s["subject_series_id"])) for s in samples}
        ),
        **totals,
        "strata": strata,
        "pairs": pairs,
        "acceptance_status": "not_assessed",
        "threshold_version": None,
        "interpretation": (
            "仅汇总当前授权的本人立项前活动；实际对象类型和系列分别计数，修订不增加独立业务样本。"
            "不同对象类型不配对；职责、复杂度、首次使用、流程及真实/回放/模拟继续分层。"
            "失败/取消/缺项保留，未包含全团队完整投入、独立接收率或阈值通过，不推定因果收益。"
        ),
    }
