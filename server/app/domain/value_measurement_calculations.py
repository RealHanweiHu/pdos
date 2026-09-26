"""Descriptive participant measurements; never a study approval or benefit verdict.

Inputs are the current authorized sample revisions supplied by the domain service.
No identity discovery, database reads, thresholds, or implicit zero imputation here.
"""

from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

VERSION = "participant-value-descriptive.v1"
COUNT_FIELDS = (
    "duplicate_entry_count",
    "clarification_round_count",
    "omission_rework_count",
    "false_block_count",
)
ACTIVE_PHASES = {
    "prepare",
    "learn",
    "input",
    "review",
    "correct",
    "clarify",
    "execute",
    "handoff",
    "receive",
}


def instant(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def seconds(start: datetime, end: datetime) -> Decimal:
    delta = end - start
    return Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / 1000000


def union(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    result: list[tuple[datetime, datetime]] = []
    for start, end in sorted(intervals):
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result


def duration(intervals: list[tuple[datetime, datetime]]) -> Decimal:
    return sum((seconds(start, end) for start, end in union(intervals)), Decimal(0))


def number(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def sample_summary(sample: dict[str, Any]) -> dict[str, Any]:
    observed, start, end = (instant(sample.get(k)) for k in ("as_of", "started_at", "ended_at"))
    active: list[tuple[datetime, datetime]] = []
    passive: list[tuple[datetime, datetime]] = []
    phases: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    missing: list[str] = []
    for key in ("all_activity_confirmed", "review_confirmed", "correction_confirmed"):
        if sample.get(key) is not True:
            missing.append(key)
    segments = sample.get("segments", [])
    invalid = open_count = unverified = 0
    for segment in segments:
        a, b = instant(segment.get("start_at")), instant(segment.get("end_at"))
        phase = segment.get("phase")
        if b is None:
            open_count += 1
            continue
        if segment.get("participant_verified") is not True:
            unverified += 1
            continue
        if (
            a is None
            or b < a
            or start is None
            or observed is None
            or a < start
            or b > observed
            or (end is not None and b > end)
            or phase not in ACTIVE_PHASES | {"passive_wait"}
        ):
            invalid += 1
            continue
        phases[phase].append((a, b))
        (passive if phase == "passive_wait" else active).append((a, b))
    if open_count:
        missing.append("open_activity_segments")
    if unverified:
        missing.append("unverified_activity_segments")
    if invalid:
        missing.append("invalid_activity_segments")
    if (
        start is None
        or observed is None
        or observed < start
        or (end is not None and not start <= end <= observed)
    ):
        missing.append("observation_interval")
    overlaps = any(max(a, c) < min(b, d) for a, b in union(active) for c, d in union(passive))
    if overlaps:
        missing.append("active_passive_overlap")
    known = duration(active)
    complete = not missing
    cycle = seconds(start, end) if start and end and start <= end else None
    elapsed = seconds(start, observed) if start and observed and start <= observed else None
    return {
        "calculation_version": VERSION,
        "scope": "own_participant_activity",
        "status": "observed" if complete else "incomplete",
        "active_seconds": number(known) if complete else None,
        "known_active_seconds": number(known),
        "known_passive_seconds": number(duration(passive)),
        "phase_known_seconds": {p: number(duration(v)) for p, v in sorted(phases.items())},
        "missing_fields": missing,
        "open_segment_count": open_count,
        "unverified_segment_count": unverified,
        "invalid_segment_count": invalid,
        "end_to_end_seconds": number(cycle),
        "elapsed_observation_seconds": number(elapsed),
        "right_censored": end is None,
        "interpretation": (
            "仅本人已核对活动；同人重叠取并集，分阶段小计不可直接相加。"
            "其他参与者投入未据此视为零；不代表全流程净收益。"
        ),
    }


def _valid_active(sample: dict[str, Any]) -> list[tuple[datetime, datetime]]:
    start, end, observed = (instant(sample.get(k)) for k in ("started_at", "ended_at", "as_of"))
    intervals = []
    for segment in sample.get("segments", []):
        a, b = instant(segment.get("start_at")), instant(segment.get("end_at"))
        if (
            start is not None
            and observed is not None
            and a is not None
            and b is not None
            and start <= a <= b <= observed
            and (end is None or b <= end)
            and segment.get("participant_verified") is True
            and segment.get("phase") in ACTIVE_PHASES
        ):
            intervals.append((a, b))
    return union(intervals)


def _participant_totals(samples: list[dict[str, Any]]) -> tuple[Decimal, Decimal]:
    by_participant: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    raw = Decimal(0)
    for sample in samples:
        intervals = _valid_active(sample)
        raw += duration(intervals)
        by_participant[str(sample["participant_user_id"])].extend(intervals)
    merged = sum((duration(v) for v in by_participant.values()), Decimal(0))
    return merged, raw - merged


def _counts(samples: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for field in COUNT_FIELDS:
        values = [
            v[field]
            for v in samples
            if isinstance(v.get(field), int) and not isinstance(v.get(field), bool)
        ]
        result[field] = {
            "known_sum": sum(values) if values else None,
            "observed_count": len(values),
            "missing_count": len(samples) - len(values),
        }
    return result


def study_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep modes/roles/complexities/evidence kinds separate; retain all supplied rows."""
    assessed = [(sample, sample_summary(sample)) for sample in samples]
    strata: dict[tuple[Any, ...], list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    pairs: dict[tuple[Any, ...], list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    unpaired = 0
    for sample, calculated in assessed:
        key = tuple(
            sample.get(k)
            for k in (
                "study_id",
                "evidence_kind",
                "scenario_id",
                "role_id",
                "complexity_stratum",
                "first_use",
                "workflow_version",
            )
        )
        strata[(*key, sample.get("mode"))].append((sample, calculated))
        if sample.get("pair_key"):
            pairs[(*key, sample.get("participant_user_id"), sample["pair_key"])].append(
                (sample, calculated)
            )
        else:
            unpaired += 1
    values = []
    for key, grouped in sorted(strata.items(), key=lambda entry: str(entry[0])):
        actual = [s for s, _ in grouped]
        complete = [
            Decimal(c["active_seconds"]) for _, c in grouped if c["active_seconds"] is not None
        ]
        known_total, removed_overlap = _participant_totals(actual)
        complete_total, complete_overlap = _participant_totals(
            [s for s, c in grouped if c["active_seconds"] is not None]
        )
        values.append(
            {
                **dict(
                    zip(
                        (
                            "study_id",
                            "evidence_kind",
                            "scenario_id",
                            "role_id",
                            "complexity_stratum",
                            "first_use",
                            "workflow_version",
                            "mode",
                        ),
                        key,
                        strict=True,
                    )
                ),
                "sample_count": len(grouped),
                "participant_count": len(
                    {s["participant_user_id"] for s in actual if s.get("participant_user_id")}
                ),
                "task_count": len({s["task_id"] for s in actual if s.get("task_id")}),
                "complete_activity_count": len(complete),
                "missing_activity_count": len(grouped) - len(complete),
                "known_active_seconds": number(known_total),
                "cross_sample_overlap_seconds": number(removed_overlap),
                "complete_sample_active_seconds": number(complete_total),
                "mean_complete_active_seconds": number(complete_total / len(complete))
                if complete and complete_overlap == 0
                else None,
                "outcomes": dict(
                    Counter(str(s.get("terminal_state", "incomplete")) for s in actual)
                ),
                "right_censored_count": sum(c["right_censored"] for _, c in grouped),
                "counts": _counts(actual),
            }
        )
    comparisons: list[dict[str, Any]] = []
    for key, grouped in sorted(pairs.items(), key=lambda entry: str(entry[0])):
        baseline = [(s, c) for s, c in grouped if s.get("mode") == "baseline_without_ai"]
        assisted = [(s, c) for s, c in grouped if s.get("mode") == "assisted"]
        reasons = []
        if len(baseline) != 1 or len(assisted) != 1 or len(grouped) != 2:
            reasons.append("需要同一分层、同一参与者的一条基线和一条辅助记录；缺项或重复记录保留")
        saved = percent = None
        baseline_seconds = assisted_seconds = None
        baseline_sample = assisted_sample = None
        if not reasons:
            b, bc = baseline[0]
            a, ac = assisted[0]
            baseline_sample, assisted_sample = b.get("sample_id"), a.get("sample_id")
            if not b.get("matching_basis") or not a.get("matching_basis"):
                reasons.append("缺少任务配对依据")
            if key[1] == "real_business" and b.get("task_id") == a.get("task_id"):
                reasons.append("同一真实任务的重复办理不能视作两个独立业务样本")
            if any(max(x, y) < min(z, w) for x, z in _valid_active(b) for y, w in _valid_active(a)):
                reasons.append("同一参与者的基线和辅助主动活动时段重叠，不能作为独立对照投入")
            if bc["active_seconds"] is None or ac["active_seconds"] is None:
                reasons.append("基线或辅助活动记录尚不完整")
            if bc["right_censored"] or ac["right_censored"]:
                reasons.append("至少一项尚未终止，仅保留截至观察时点的投入")
            if not reasons:
                baseline_seconds, assisted_seconds = (
                    Decimal(bc["active_seconds"]),
                    Decimal(ac["active_seconds"]),
                )
                saved = baseline_seconds - assisted_seconds
                percent = saved / baseline_seconds * 100 if baseline_seconds > 0 else None
        comparisons.append(
            {
                "pair_key": key[-1],
                "participant_user_id": key[-2],
                **dict(
                    zip(
                        (
                            "study_id",
                            "evidence_kind",
                            "scenario_id",
                            "role_id",
                            "complexity_stratum",
                            "first_use",
                            "workflow_version",
                        ),
                        key[:-2],
                        strict=True,
                    )
                ),
                "status": "incomplete" if reasons else "observed",
                "sample_count": len(grouped),
                "baseline_sample_id": baseline_sample,
                "assisted_sample_id": assisted_sample,
                "baseline_active_seconds": number(baseline_seconds),
                "assisted_active_seconds": number(assisted_seconds),
                "active_seconds_difference": number(saved),
                "difference_percent": number(percent),
                "difference_percent_status": "incomplete"
                if reasons
                else "observed"
                if percent is not None
                else "not_applicable",
                "reasons": reasons,
                "outcomes": [
                    {
                        "mode": s.get("mode"),
                        "terminal_state": s.get("terminal_state"),
                        "reception_decision": s.get("reception_decision"),
                    }
                    for s, _ in grouped
                ],
            }
        )
    return {
        "calculation_version": VERSION,
        "status": "not_assessed" if not samples else "descriptive_only",
        "sample_count": len(samples),
        "participant_count": len(
            {s["participant_user_id"] for s in samples if s.get("participant_user_id")}
        ),
        "task_count": len({s["task_id"] for s in samples if s.get("task_id")}),
        "missing_activity_count": sum(c["status"] != "observed" for _, c in assessed),
        "without_pair_key_count": unpaired,
        "complete_pair_count": sum(p["status"] == "observed" for p in comparisons),
        "incomplete_pair_count": sum(p["status"] != "observed" for p in comparisons),
        "strata": values,
        "pairs": comparisons,
        "acceptance_status": "not_assessed",
        "threshold_version": None,
        "interpretation": (
            "按可读且当前授权的本人记录描述，真实业务、回放、模拟与职责分层分列；失败/取消保留。"
            "未计全体参与者完整投入，未校准阈值、独立接收率或因果收益，不作通过判定。"
        ),
    }
