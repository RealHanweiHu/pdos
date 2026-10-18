"""Pure knowledge semantics; a hypothesis never silently becomes an applicable rule."""

from copy import deepcopy

from pdos_next.domain.work_management.rules import require


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"approval_token"})


def candidate_body(payload, identity, revision):
    return {
        "candidate_id": str(identity),
        "revision": revision,
        **{
            key: semantic(payload)[key]
            for key in (
                "title",
                "lesson",
                "evidence_summary",
                "applicability_hypothesis",
                "result_receipts",
            )
        },
    }


def assessment_body(payload, candidate, actor_id):
    require(
        payload.applicability.decision == "applicable",
        "未知、冲突或不适用的评估保留为候选，不能发布适用规则。",
        "MISSING_REQUIRED_EVIDENCE",
        422,
    )
    return {
        **payload.applicability.model_dump(mode="json"),
        "candidate_version": {"id": str(candidate.id), "revision": candidate.revision},
        "assessor_id": str(actor_id),
        "withdrawal_reason": None,
    }


def rule_body(payload, identity, revision, candidate, assessment_id, assessment, nature):
    return {
        "rule_id": str(identity),
        "revision": revision,
        "candidate": {"id": str(candidate.candidate_id), "revision": candidate.revision},
        "candidate_version_id": str(candidate.id),
        "assessment_id": str(assessment_id),
        "title": payload.title,
        "rule_text": payload.rule_text,
        "applicability": assessment,
        "nature": nature,
    }


def merge_artifacts(*groups):
    merged = {}
    for group in groups:
        for item in group:
            old = merged.get(item["id"])
            require(old is None or old == item, "固定内容来源版本不一致。", "SOURCE_STALE")
            merged[item["id"]] = deepcopy(item)
    return [merged[key] for key in sorted(merged)]


def usability(at, valid_from, valid_until, reasons):
    reasons = sorted(set(reasons))
    if reasons:
        return {"state": "needs_recheck", "reason_codes": reasons}
    if at < valid_from:
        return {"state": "not_yet_effective", "reason_codes": ["validity_not_started"]}
    if valid_until is not None and at >= valid_until:
        return {"state": "expired", "reason_codes": ["validity_ended"]}
    return {"state": "current", "reason_codes": []}
