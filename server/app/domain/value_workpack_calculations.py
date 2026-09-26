"""Descriptive team effort and independent reception for preregistered scope.

Only the domain service's currently authorized observations enter these functions.
Complete totals require the full roster; missing people never contribute implicit zero.
"""

from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any

from app.domain.value_measurement_calculations import (
    _participant_totals,
    _valid_active,
    instant,
    number,
    sample_summary,
    seconds,
)

VERSION = "workpack-value-descriptive.v1"
STRATA = ("study_id", "evidence_kind", "scenario_id", "complexity_stratum", "workflow_version")


def _time(row: dict[str, Any], alias: str) -> Any:
    return instant(row.get(alias) or row.get("created_at"))


def workpack_summary(
    workpack: dict[str, Any],
    samples: list[dict[str, Any]],
    deliveries: list[dict[str, Any]],
    receptions: list[dict[str, Any]],
    closure: dict[str, Any] | None,
) -> dict[str, Any]:
    """Describe a fixed work scope without granting consent or declaring benefit."""
    by_person: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in samples:
        by_person[str(observation.get("participant_user_id"))].append(observation)
    roster = workpack.get("members", [])
    delivery_ids = {str(d["id"]) for d in deliveries}
    visible_receptions = [r for r in receptions if str(r.get("delivery_id")) in delivery_ids]
    ordered = sorted(deliveries, key=lambda d: int(d.get("round", 0)))
    decisions = {str(r["delivery_id"]): r for r in visible_receptions}
    latest = ordered[-1] if ordered else None
    latest_reception = decisions.get(str(latest["id"])) if latest else None
    first = next((d for d in ordered if d.get("round") == 1), None)
    first_reception = decisions.get(str(first["id"])) if first else None
    available = workpack.get("data_availability_complete") is True
    outcome = (
        "unavailable"
        if not available
        else closure["outcome"]
        if closure
        else "accepted"
        if latest_reception and latest_reception.get("decision") == "accepted"
        else "returned"
        if latest_reception
        else "awaiting_reception"
        if latest
        else "not_delivered"
    )
    terminal = outcome in {"accepted", "failed", "cancelled"}
    receipt_times = [_time(r, "received_at") for r in visible_receptions]
    latest_receipt_at = max((t for t in receipt_times if t is not None), default=None)
    delivery_times = [_time(d, "delivered_at") for d in ordered]
    latest_delivery_at = max((t for t in delivery_times if t is not None), default=None)
    people: list[dict[str, Any]] = []
    included: list[dict[str, Any]] = []
    for person in roster:
        user_id = str(person["user_id"])
        candidates = by_person.get(user_id, [])
        reasons: list[str] = []
        calculated = None
        sample = candidates[0] if len(candidates) == 1 else None
        if sample is None:
            reasons.append(
                "missing_or_unavailable_sample" if not candidates else "ambiguous_samples"
            )
        else:
            for field in ("study_id", "task_id", "mode", "complexity_stratum", "workflow_version"):
                if str(sample.get(field)) != str(workpack.get(field)):
                    reasons.append(f"mismatched_{field}")
            for field in ("role_id", "first_use"):
                if sample.get(field) != person.get(field):
                    reasons.append(f"mismatched_{field}")
            for field in ("evidence_kind", "scenario_id"):
                if sample.get(field) != workpack.get(field):
                    reasons.append(f"mismatched_{field}")
            began = instant(sample.get("started_at"))
            registered = instant(workpack.get("created_at"))
            if workpack.get("evidence_kind") == "real_business" and (
                began is None or registered is None or began < registered
            ):
                reasons.append("activity_precedes_workpack_registration")
            if sample.get("excluded_rule_id"):
                reasons.append("predeclared_exclusion")
            # Identity mismatches/exclusions cannot contribute even a partial team total.
            if not reasons:
                included.append(sample)
                calculated = sample_summary(sample)
                reasons.extend(calculated["missing_fields"])
                ended = instant(sample.get("ended_at"))
                if calculated["right_censored"] or sample.get("terminal_state") == "incomplete":
                    reasons.append("observation_not_ended")
                if (
                    user_id == str(workpack.get("receiver_user_id"))
                    and latest_receipt_at
                    and (ended is None or ended < latest_receipt_at)
                ):
                    reasons.append("receiver_activity_ends_before_reception")
                if (
                    user_id == str(workpack.get("deliverer_user_id"))
                    and latest_delivery_at
                    and (ended is None or ended < latest_delivery_at)
                ):
                    reasons.append("deliverer_activity_ends_before_delivery")
        people.append(
            {
                **person,
                "sample_id": sample.get("sample_id") if sample else None,
                "sample_revision_id": sample.get("id") if sample else None,
                "sample_version": sample.get("version") if sample else None,
                "terminal_state": sample.get("terminal_state") if sample else None,
                "status": "incomplete" if reasons else "observed",
                "reasons": reasons,
                "known_active_seconds": calculated["known_active_seconds"] if calculated else None,
                "active_seconds": calculated["active_seconds"]
                if calculated and not reasons
                else None,
                "activity": calculated,
            }
        )
    known, overlap = _participant_totals(included)
    complete_count = sum(p["status"] == "observed" for p in people)
    roster_valid = (
        len(roster) >= 2
        and len({str(p["user_id"]) for p in roster}) == len(roster)
        and workpack.get("full_roster_confirmed") is True
    )
    complete = roster_valid and complete_count == len(roster) and available and terminal
    start_times = [instant(s.get("started_at")) for s in included]
    end_times = [instant(s.get("ended_at")) for s in included]
    event_end = (
        _time(closure, "closed_at")
        if closure
        else _time(latest_reception, "received_at")
        if terminal and latest_reception
        else None
    )
    begin = min((t for t in start_times if t is not None), default=None)
    end = max((t for t in [*end_times, event_end] if t is not None), default=None)
    first_status = (
        "unavailable"
        if not available
        else first_reception["decision"]
        if first_reception
        else "pending"
        if first
        else "not_delivered"
    )
    return {
        "calculation_version": VERSION,
        "workpack_id": workpack.get("id"),
        **{k: workpack.get(k) for k in (*STRATA, "task_id", "mode", "pair_key")},
        "status": "observed" if complete else "incomplete",
        "outcome": outcome,
        "expected_participant_count": len(roster),
        "observed_participant_count": len(included),
        "complete_participant_count": complete_count,
        "missing_or_incomplete_participant_count": len(roster) - complete_count,
        "participants": people,
        "known_active_seconds": number(known) if included else None,
        "active_seconds": number(known) if complete else None,
        "cross_sample_overlap_seconds": number(overlap),
        "end_to_end_seconds": number(seconds(begin, end))
        if complete and begin and end and begin <= end
        else None,
        "right_censored": not terminal,
        "delivery_count": len(ordered),
        "reception_count": len(visible_receptions),
        "return_count": sum(r.get("decision") == "returned" for r in visible_receptions),
        "first_reception": first_status,
        "data_availability_complete": available,
        "unavailable_receipt_count": workpack.get("unavailable_receipt_count", 0),
        "acceptance_status": "not_assessed",
        "threshold_version": None,
        "interpretation": (
            "仅描述预先登记工作包范围的当前授权记录；同一实际人员重叠取并集，不同人员相加。"
            "全员活动结束且交付已接受或明确失败/取消后才列完整投入；首轮裁决独立统计。"
            "缺项/撤回/失败保留，时间差不代表因果收益或验收通过。"
        ),
    }


def _roster_key(workpack: dict[str, Any], *, identities: bool = False) -> tuple[Any, ...]:
    return tuple(
        sorted(
            (str(p["user_id"]) if identities else "", str(p["role_id"]), bool(p["first_use"]))
            for p in workpack.get("members", [])
        )
    )


def workpack_study_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """First-round decisions use decided deliveries only; pending/unknown remain visible."""
    assessed = [(e, workpack_summary(**e)) for e in entries]
    strata: dict[tuple[Any, ...], list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    pairs: dict[tuple[Any, ...], list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for entry, summary in assessed:
        w = entry["workpack"]
        key = tuple(w.get(k) for k in STRATA)
        strata[(*key, w.get("mode"), _roster_key(w))].append((entry, summary))
        if w.get("pair_key"):
            pairs[(*key, w["pair_key"])].append((entry, summary))
    groups = []
    for key, grouped in sorted(strata.items(), key=lambda item: str(item[0])):
        first = Counter(s["first_reception"] for _, s in grouped)
        decided = first["accepted"] + first["returned"]
        complete = [(e, s) for e, s in grouped if s["active_seconds"] is not None]
        complete_samples = [sample for e, _ in complete for sample in e["samples"]]
        unique_total, overlap = _participant_totals(complete_samples)
        groups.append(
            {
                **dict(zip((*STRATA, "mode"), key[:-1], strict=True)),
                "participant_roles": [
                    {"role_id": role, "first_use": first_use} for _, role, first_use in key[-1]
                ],
                "workpack_count": len(grouped),
                "complete_workpack_count": len(complete),
                "incomplete_workpack_count": len(grouped) - len(complete),
                "outcomes": dict(Counter(s["outcome"] for _, s in grouped)),
                "first_reception_counts": dict(first),
                "first_acceptance_numerator": first["accepted"],
                "first_acceptance_denominator": decided,
                "first_acceptance_percent": number(Decimal(first["accepted"]) / decided * 100)
                if decided
                else None,
                "first_acceptance_status": "observed"
                if decided
                else "incomplete"
                if first["unavailable"] or first["pending"]
                else "not_applicable",
                "complete_workpack_active_seconds": number(unique_total) if complete else None,
                "cross_workpack_overlap_seconds": number(overlap),
                "mean_complete_active_seconds": number(unique_total / len(complete))
                if complete and overlap == 0
                else None,
            }
        )
    comparisons = []
    for key, grouped in sorted(pairs.items(), key=lambda item: str(item[0])):
        b = [(e, s) for e, s in grouped if e["workpack"].get("mode") == "baseline_without_ai"]
        a = [(e, s) for e, s in grouped if e["workpack"].get("mode") == "assisted"]
        reasons = []
        difference = percent = None
        if len(b) != 1 or len(a) != 1 or len(grouped) != 2:
            reasons.append("每个任务对需要同一分层的一份基线工作包和一份辅助工作包")
        else:
            be, bs = b[0]
            ae, ass = a[0]
            bw, aw = be["workpack"], ae["workpack"]
            if _roster_key(bw, identities=True) != _roster_key(aw, identities=True):
                reasons.append("实际参与者、主职责或首次使用构成不同")
            if not bw.get("matching_basis") or not aw.get("matching_basis"):
                reasons.append("缺少预登记匹配依据")
            if bw.get("evidence_kind") == "real_business" and bw.get("task_id") == aw.get(
                "task_id"
            ):
                reasons.append("同一真实任务重复办理不能作为独立业务对照")
            if bs["active_seconds"] is None or ass["active_seconds"] is None:
                reasons.append("至少一个工作包的全员活动或交付结果尚不完整")
            for left in be["samples"]:
                for right in ae["samples"]:
                    if str(left.get("participant_user_id")) == str(
                        right.get("participant_user_id")
                    ) and any(
                        max(x, y) < min(z, v)
                        for x, z in _valid_active(left)
                        for y, v in _valid_active(right)
                    ):
                        reasons.append("同一实际参与者的基线及辅助主动时段重叠")
            if not reasons:
                baseline = Decimal(bs["active_seconds"])
                difference = baseline - Decimal(ass["active_seconds"])
                percent = difference / baseline * 100 if baseline > 0 else None
        comparisons.append(
            {
                **dict(zip(STRATA, key[:-1], strict=True)),
                "pair_key": key[-1],
                "status": "incomplete" if reasons else "observed",
                "reasons": list(dict.fromkeys(reasons)),
                "active_seconds_difference": number(difference),
                "difference_percent": number(percent),
                "difference_percent_status": "incomplete"
                if reasons
                else "observed"
                if percent is not None
                else "not_applicable",
                "workpacks": [
                    {
                        k: s[k]
                        for k in (
                            "workpack_id",
                            "task_id",
                            "mode",
                            "outcome",
                            "active_seconds",
                            "first_reception",
                        )
                    }
                    for _, s in grouped
                ],
            }
        )
    return {
        "calculation_version": VERSION,
        "status": "descriptive_only" if entries else "not_assessed",
        "workpack_count": len(entries),
        "strata": groups,
        "pairs": comparisons,
        "without_pair_key_count": sum(not e["workpack"].get("pair_key") for e in entries),
        "complete_pair_count": sum(p["status"] == "observed" for p in comparisons),
        "incomplete_pair_count": sum(p["status"] != "observed" for p in comparisons),
        "acceptance_status": "not_assessed",
        "threshold_version": None,
        "interpretation": (
            "首轮接受率分母为已有首轮接收裁决的交付；待接收、未交付及不可读分别列示。"
            "按证据类别、场景、复杂度、流程版本和职责/首次使用构成分层；失败与取消保留。"
            "时间差为描述性对照；不据此推定因果效果、阈值通过或完整试点验收。"
        ),
    }
