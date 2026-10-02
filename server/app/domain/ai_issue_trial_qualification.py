"""Pure Issue trial criteria over trusted collected originals, never authority.

The caller verifies stored digests, source existence and provider attestations.
This function cannot turn a client boolean into proof. Failed/unhandled runs stay
in raw counts without adding an unapproved all-success requirement. Only matched
handled originals require verified provider evidence; uncertain handled targets
cannot silently disappear from the denominator. T0 sampling is operational, not
a prerequisite requiring historic T0 samples before the first automatic write.
"""

from copy import deepcopy
from typing import Any

from pydantic import AwareDatetime, TypeAdapter, ValidationError

from app.contracts.ai_issue_evaluation import IssueEvaluationBinding
from app.contracts.ai_issue_trial_protocol import IssueTrialChoices
from app.domain.product_workspace import digest

EVALUATOR_VERSION = "event-issue-trial-qualification-v1"
_TIME = TypeAdapter(AwareDatetime)
_MESSAGES = {
    "selection_incomplete": "固定窗口原运行尚未完整采集。",
    "non_business_evidence": "模拟或受控回放不能替代真实业务试运行。",
    "registration_not_prospective": "真实业务试运行未在窗口开始前登记。",
    "evaluation_unverified": "原独立评测的真实执行、完整版本或通过结论无法核实。",
    "evaluation_failed": "原独立能力评测未通过。",
    "model_version_unknown": "登记的模型修订版本尚不明确。",
    "provider_calls_unverified": "用于办理统计的原调用尚缺可信服务商执行证明。",
    "handled_target_unverified": "已办理的疑似目标运行无法核实版本或来源，不能从分母静默排除。",
    "empty_window": "登记窗口没有原运行。",
    "followup_incomplete": "窗口结束后的登记跟踪时长尚未满足。",
    "insufficient_handled_runs": "匹配原版本的办理数未达到登记要求。",
    "confirmation_denominator_empty": "尚无可计算确认比例的匹配办理分母。",
    "withdrawal_denominator_empty": "尚无可计算撤回比例的匹配自建问题分母。",
    "confirmation_not_met": "确认比例未达到原登记阈值。",
    "withdrawal_not_met": "撤回比例超过原登记阈值。",
}


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clearly_other(protocol: dict[str, Any], item: dict[str, Any]) -> bool:
    """Only explicit original controls or a verified full binding prove exclusion."""
    generation = _object(item.get("generation_binding"))
    for key, column in (
        ("policy", "policy_id"),
        ("scope", "scope_revision_id"),
        ("principal", "principal_id"),
    ):
        original_id = _object(generation.get(key)).get("id")
        if original_id is not None and original_id != protocol[column]:
            return True
    proof = _object(item.get("provenance"))
    if proof.get("provenance_verified") is True and isinstance(proof.get("binding"), dict):
        try:
            original = IssueEvaluationBinding.model_validate(proof["binding"])
        except ValidationError:
            return False
        return original != IssueEvaluationBinding.model_validate(protocol["binding"])
    return False


def evaluate(protocol: dict[str, Any], collection: dict[str, Any]) -> dict[str, Any]:
    """Recompute current criteria from a protocol and immutable collection-shaped facts.

    Malformed scope/time/count contracts raise ValueError. Well-shaped but missing
    evidence returns insufficient_evidence. No clock, database, model or mutation.
    Current policy/publication validity and authorization belong to the caller.
    """
    # Local import keeps the pure evaluator usable from collection/current readers.
    from app.domain.ai_issue_trial_collections import match_run, summarize

    if (
        protocol.get("version") != "event-issue-trial-protocol-v1"
        or collection.get("version", "event-issue-trial-collection-v1")
        != "event-issue-trial-collection-v1"
    ):
        raise ValueError("issue_trial_original_version_invalid")
    if any(
        collection.get(key) != protocol.get(key) for key in ("tenant_id", "project_id")
    ) or collection.get("protocol_id") != protocol.get("id"):
        raise ValueError("issue_trial_original_scope_mismatch")
    if collection.get("protocol_digest") != digest(protocol):
        raise ValueError("issue_trial_protocol_digest_mismatch")
    start, end, as_of, captured = (
        _TIME.validate_python(value)
        for value in (
            protocol["window_start"],
            protocol["window_end"],
            collection["as_of"],
            collection.get("created_at", collection["as_of"]),
        )
    )
    if not start < end <= as_of <= captured or any(
        _TIME.validate_python(collection[key]) != _TIME.validate_python(protocol[key])
        for key in ("window_start", "window_end")
    ):
        raise ValueError("issue_trial_original_window_mismatch")
    items = deepcopy(collection["items"])
    if (
        not isinstance(items, list)
        or type(collection.get("total_runs")) is not int
        or collection["total_runs"] != len(items)
    ):
        raise ValueError("issue_trial_original_count_mismatch")
    if type(collection.get("selection_complete")) is not bool:
        raise ValueError("issue_trial_selection_flag_invalid")
    binding = IssueEvaluationBinding.model_validate(protocol["binding"])
    cfg = protocol["configuration"]
    choices = IssueTrialChoices.model_validate(
        {key: cfg[key] for key in IssueTrialChoices.model_fields}
    )
    for key, low, high in (
        ("minimum_confirmation_basis_points", 9000, 10000),
        ("maximum_retraction_basis_points", 0, 500),
    ):
        if type(cfg.get(key)) is not int or not low <= cfg[key] <= high:
            raise ValueError("issue_trial_threshold_invalid")
    missing: set[str] = set()
    failed: set[str] = set()
    uncertain_runs, provider_runs = [], []
    if collection["selection_complete"] is not True:
        missing.add("selection_incomplete")
    if protocol["evidence_kind"] != "real_business":
        missing.add("non_business_evidence")
    elif _TIME.validate_python(protocol["created_at"]) >= start:
        missing.add("registration_not_prospective")
    if binding.model_version is None or binding.model_version.casefold() in {
        "unknown",
        "unspecified",
        "unavailable",
        "latest",
        "default",
        "未知",
        "未登记",
    }:
        missing.add("model_version_unknown")
    evaluation = _object(_object(protocol.get("evaluation_publication")).get("evaluation"))
    if (
        evaluation.get("binding") != protocol["binding"]
        or evaluation.get("execution_source") != "live_model_evaluation"
        or evaluation.get("real_provider_call") is not True
        or evaluation.get("outcome") not in {"passed", "failed"}
    ):
        missing.add("evaluation_unverified")
    elif evaluation["outcome"] == "failed":
        failed.add("evaluation_failed")
    for item in items:
        if not start <= _TIME.validate_python(item["created_at"]) < end:
            raise ValueError("issue_trial_run_outside_window")
        proof = _object(item.get("provenance"))
        item["match"] = match_run(protocol, item, proof, as_of)
        handled = item["application_kind"] is not None or item["review_state"] == "declined"
        if handled and item["match"]["matches_protocol"]:
            if proof.get("provider_verified") is not True:
                missing.add("provider_calls_unverified")
                provider_runs.append(item["run_id"])
        elif handled and not _clearly_other(protocol, item):
            missing.add("handled_target_unverified")
            uncertain_runs.append(item["run_id"])
    summary = summarize(protocol, items, as_of)
    criteria = summary["criteria"]
    if not items:
        missing.add("empty_window")
    if not criteria["followup_complete"]:
        missing.add("followup_incomplete")
    if not criteria["minimum_handled_runs"]["met"]:
        missing.add("insufficient_handled_runs")
    for key in ("confirmation", "withdrawal"):
        if criteria[key]["met"] is None:
            missing.add(key + "_denominator_empty")
        elif not criteria[key]["met"]:
            failed.add(key + "_not_met")
    return {
        "evaluator_version": EVALUATOR_VERSION,
        "status": "insufficient_evidence"
        if missing
        else "does_not_meet_criteria"
        if failed
        else "meets_candidate_criteria",
        "total_runs": summary["total_runs"],
        "matching_runs": summary["matching_runs"],
        "counts": summary["counts"],
        "matching_counts": summary["matching_counts"],
        "criteria": criteria,
        "formula": summary["formula"],
        "reasons": [
            {"code": code, "message": _MESSAGES[code]} for code in sorted(missing | failed)
        ],
        "uncertain_handled_run_ids": sorted(uncertain_runs),
        "provider_unverified_handled_run_ids": sorted(provider_runs),
        "operational_requirements": [
            {
                "code": "t0_continuous_sampling",
                "message": "进入T0后按登记比例持续抽检；不要求T1阶段已有T0抽检历史。",
                "sampling_basis_points": choices.sampling_basis_points,
                "recovery_protocol_version": choices.recovery_protocol_version,
                "recovery_conditions": choices.recovery_conditions,
            }
        ],
        "qualification_granted": False,
    }
