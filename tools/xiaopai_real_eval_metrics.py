"""Content-free, offline summaries of real AgentRun/AgentToolCall JSON exports.

No application imports, database access, provider requests, or LLM judging. Input
includes cache tokens; cache read/write are breakdowns and must not be added again.
Normalized cache zero is ambiguous because the adapter defaults missing fields to
zero. Preserve raw usage field presence to establish an explicitly reported zero.
"""

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

VERSION = "xiaopai-real-eval-metrics/v1"
EXPORT_VERSION = "xiaopai-real-eval-export/v1"
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens")
CHECK_KINDS = {"fact_value", "identifier", "source_binding", "error_code", "action"}


def _object(value, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value


def _integer(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def _number(value, name):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0):
        raise ValueError(f"{name} must be a finite nonnegative number")
    return value


def _rows(value, name):
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"{name} must be an array of objects")
    return value


def _optional_number(value, name):
    return None if value is None else _number(value, name)


def _quantiles(values):
    """Nearest-rank quantiles; absent measurements never become zero."""
    values = sorted(value for value in values if value is not None)
    return {
        "n": len(values),
        "p50": values[math.ceil(.50 * len(values)) - 1] if values else None,
        "p95": values[math.ceil(.95 * len(values)) - 1] if values else None,
        "min": values[0] if values else None,
        "max": values[-1] if values else None,
    }


def _measured_sum(values):
    values = list(values)
    measured = [value for value in values if value is not None]
    return {"known_sum": sum(measured) if measured else None,
            "known_count": len(measured), "unknown_count": len(values) - len(measured),
            "complete": len(measured) == len(values)}


def _latency(values):
    values = list(values)
    return {**_quantiles(values), "unknown_count": values.count(None)}


def _usage(call, metrics):
    result = _object(call.get("result") or {}, "call.result")
    normalized = result.get("usage")
    usage = dict.fromkeys(TOKEN_FIELDS)
    basis = "unavailable"
    cache_basis = "unavailable"
    # An unresolved/unknown outcome may carry a reservation and default zero columns.
    unresolved = call.get("state") in {"started", "unknown"} or (
        call.get("error_code") == "EXTERNAL_OUTCOME_UNKNOWN"
    )
    if normalized is not None and not unresolved:
        normalized = _object(normalized, "call.result.usage")
        for field in TOKEN_FIELDS:
            if normalized.get(field) is not None:
                usage[field] = _integer(normalized[field], f"usage.{field}")
        basis = "normalized_provider_usage"
        for field in ("cache_read_tokens", "cache_creation_tokens"):
            if usage[field] == 0:
                usage[field] = None
        cache_basis = "positive_usage_reported" if any(
            usage[key] is not None for key in TOKEN_FIELDS[2:]
        ) else "zero_or_unreported"
    elif metrics.get("usage_status") == "recorded" and not unresolved:
        for field in TOKEN_FIELDS[:2]:
            value = metrics.get("actual_" + field)
            if value is not None:
                usage[field] = _integer(value, "context_metrics.actual_" + field)
        basis = "durable_context_observation"
    elif call.get("cost_state") == "actual" and not unresolved and any(
        call.get("actual_" + field, 0) for field in TOKEN_FIELDS[:2]
    ):
        for field in TOKEN_FIELDS[:2]:
            value = call.get("actual_" + field)
            if value is not None:
                usage[field] = _integer(value, "call.actual_" + field)
        basis = "settled_ledger_nonzero_usage"

    raw = call.get("raw_usage")
    if raw is not None and not unresolved:
        raw = _object(raw, "call.raw_usage")
        protocol = call.get("protocol")
        raw_values = dict.fromkeys(TOKEN_FIELDS)
        if protocol == "openai-compatible":
            for source, target in (("prompt_tokens", "input_tokens"),
                                   ("completion_tokens", "output_tokens")):
                if raw.get(source) is not None:
                    raw_values[target] = _integer(raw[source], "raw_usage." + source)
            details = _object(raw.get("prompt_tokens_details") or {}, "prompt_tokens_details")
            for source, target in (("cached_tokens", "cache_read_tokens"),
                                   ("cache_write_tokens", "cache_creation_tokens")):
                if details.get(source) is not None:
                    raw_values[target] = _integer(details[source], "raw_usage." + source)
        elif protocol == "anthropic-native":
            for source, target in (("cache_read_input_tokens", "cache_read_tokens"),
                                   ("cache_creation_input_tokens", "cache_creation_tokens"),
                                   ("output_tokens", "output_tokens")):
                if raw.get(source) is not None:
                    raw_values[target] = _integer(raw[source], "raw_usage." + source)
            # Anthropic input_tokens excludes cache. Missing cache fields do not
            # establish an inclusive input total unless normalized usage supplies it.
            if raw.get("input_tokens") is not None and all(
                raw_values[key] is not None for key in TOKEN_FIELDS[2:]
            ):
                raw_values["input_tokens"] = _integer(raw["input_tokens"], "raw_usage.input_tokens")
                raw_values["input_tokens"] += sum(raw_values[key] for key in TOKEN_FIELDS[2:])
        else:
            raise ValueError("raw_usage requires an explicit supported call.protocol")
        for key, value in raw_values.items():
            if value is not None:
                if usage[key] is not None and usage[key] != value:
                    raise ValueError(f"Raw and normalized provider usage disagree: {key}")
                usage[key] = value
        basis = "raw_and_ledger_provider_usage"
        cache_basis = "explicit_provider_fields" if all(
            raw_values[key] is not None for key in TOKEN_FIELDS[2:]
        ) else "partial_provider_fields"
    if usage["input_tokens"] is not None:
        known_cache = sum(usage[key] or 0 for key in TOKEN_FIELDS[2:])
        if known_cache > usage["input_tokens"]:
            raise ValueError("Cache breakdown exceeds inclusive input_tokens")
    return {**usage, "basis": basis, "cache_reporting": cache_basis,
            "cache_read_hit": (usage["cache_read_tokens"] > 0
                               if usage["cache_read_tokens"] is not None else None),
            "cache_read_ratio": (usage["cache_read_tokens"] / usage["input_tokens"]
                                 if usage["input_tokens"] and
                                 usage["cache_read_tokens"] is not None else None)}


def _cost(call):
    pricing = _object(call.get("cost_pricing") or {}, "call.cost_pricing")
    state = call.get("cost_state", "unmetered")
    charged = call.get("cost_charged_micro_usd")
    reserved = call.get("cost_reserved_micro_usd")
    for value, name in ((charged, "cost_charged_micro_usd"),
                        (reserved, "cost_reserved_micro_usd")):
        if value is not None:
            _integer(value, name)
    return {"state": state, "currency": pricing.get("currency"),
            "price_card_digest": pricing.get("digest"),
            "configuration_version": pricing.get("configuration_version"),
            "provider": pricing.get("provider"), "model": pricing.get("model"),
            "price_source": pricing.get("source"),
            "actual_ledger_micro_usd": charged if state == "actual" else None,
            "estimated_unknown_micro_usd": charged if state == "estimated_unknown" else None,
            "reserved_micro_usd": reserved if state == "reserved" else None,
            "interpretation": "internal_rate_card_accounting_not_provider_invoice"}


def _context(budget, metric):
    """Only numeric metering metadata; no tool arguments or context bodies."""
    result = {}
    for name in ("window", "reserve", "focus", "estimated_input_tokens", "admission_tokens",
                 "cleanup_count", "estimation_error_ratio"):
        value = metric.get(name, budget.get(name))
        if name == "estimated_input_tokens" and value is None:
            value = budget.get("estimated_total")
        result[name] = _optional_number(value, "context." + name)
    segments = metric.get("segments", budget.get("segments", {}))
    result["segments"] = {}
    for name in ("system", "tools", "skills", "envelope", "history", "loop"):
        segment = segments.get(name) if isinstance(segments, dict) else None
        estimated = segment.get("estimated_tokens") if isinstance(segment, dict) else segment
        # Providers report only aggregate usage, never per-segment actuals.
        result["segments"][name] = {
            "estimated_tokens": _optional_number(estimated, "segment." + name),
            "actual_tokens": None,
        }
    result["work_state_revision"] = _optional_number(
        (metric.get("work_state") or {}).get("revision"), "work_state.revision",
    )
    result["history"] = {key: _optional_number((metric.get("history") or {}).get(key), key)
                         for key in ("carried", "kept", "updated", "hidden", "directories")}
    return result


def _quality(run):
    """Compare pre-extracted typed values only; never infer truth from answer prose."""
    checks = []
    for check in _rows(run.get("mechanical_checks", []), "run.mechanical_checks"):
        kind = check.get("kind")
        if kind not in CHECK_KINDS:
            raise ValueError("Unsupported mechanical check kind")
        identity = _text(check.get("id"), "mechanical_check.id")
        declared = check.get("status")
        if declared in {"not_run", "blocked", "not_applicable", "needs_case_revision"}:
            status = declared
        elif ("observed" not in check or check["observed"] is None
              or not check.get("evidence")):
            status = "not_run"
        else:
            if "expected" not in check or check["expected"] is None:
                raise ValueError("A mechanical comparison requires a known expected value")
            if check.get("observation_basis") not in {
                "native_ledger", "structured_output", "reviewed_extraction",
            }:
                raise ValueError("A mechanical comparison requires its observation basis")
            # JSON typed equality (Python otherwise treats False == 0).
            status = "passed" if json.dumps(check["observed"], sort_keys=True) == json.dumps(
                check["expected"], sort_keys=True
            ) else "failed"
        checks.append({"id": identity, "kind": kind, "status": status,
                       "observation_basis": check.get("observation_basis"),
                       "evidence": check.get("evidence", [])})
    review = run.get("review")
    if review is not None:
        review = _object(review, "run.review")
        if not review.get("reviewer") or not review.get("evidence"):
            raise ValueError("A semantic review requires reviewer identity and evidence")
        if review.get("method") not in {"human", "agent_review"}:
            raise ValueError("Only explicit human or agent reviews may be recorded")
        review = {key: review.get(key) for key in (
            "reviewer", "method", "rubric_version", "status", "dimensions", "task_score",
            "hard_fail", "hard_fail_types", "evidence", "correction_cost",
        )}
        if review.get("hard_fail") is True:
            review["task_score"] = 0
    return {"mechanical_checks": checks, "mechanical_statuses": dict(Counter(
        check["status"] for check in checks)), "semantic_review": review,
        "semantic_status": "recorded_review" if review else "pending_independent_review",
        "scope": "typed_comparisons_do_not_establish_semantic_fidelity_or_qualification"}


def _aggregate(calls):
    costs = defaultdict(list)
    for call in calls:
        cost = call["cost"]
        key = (cost["currency"], cost["price_card_digest"], cost["configuration_version"])
        costs[key].append(cost)
    return {
        "model_calls": len(calls), "call_states": dict(Counter(row["state"] for row in calls)),
        "tokens": {field: _measured_sum(row["usage"][field] for row in calls)
                   for field in TOKEN_FIELDS},
        "provider_cache_read": {
            "positive_calls": sum(row["usage"]["cache_read_hit"] is True for row in calls),
            "explicit_zero_calls": sum(row["usage"]["cache_read_hit"] is False for row in calls),
            "unknown_calls": sum(row["usage"]["cache_read_hit"] is None for row in calls),
            "ratio_on_known_input": (
                sum(row["usage"]["cache_read_tokens"] for row in calls) /
                sum(row["usage"]["input_tokens"] for row in calls)
                if calls and all(row["usage"]["cache_read_tokens"] is not None and
                                 row["usage"]["input_tokens"] is not None for row in calls)
                and sum(row["usage"]["input_tokens"] for row in calls) > 0 else None
            ),
        },
        "model_call_elapsed_ms": _latency(row["elapsed_ms"] for row in calls),
        "cost_buckets": [{"currency": key[0], "price_card_digest": key[1],
                          "configuration_version": key[2], "states": dict(Counter(
                              cost["state"] for cost in values)),
                          **{name: _measured_sum(cost[name] for cost in values
                                                if cost["state"] == state)
                             for name, state in (("actual_ledger_micro_usd", "actual"),
                                                 ("estimated_unknown_micro_usd",
                                                  "estimated_unknown"),
                                                 ("reserved_micro_usd", "reserved"))}}
                         for key, values in sorted(costs.items(), key=lambda item: str(item[0]))],
    }


def summarize(export):
    _object(export, "export")
    if export.get("version") != EXPORT_VERSION:
        raise ValueError(f"export.version must be {EXPORT_VERSION!r}")
    runs = _rows(export.get("runs"), "runs")
    cases = {}
    for case in _rows(export.get("cases", []), "cases"):
        case_id = _text(case.get("case_id"), "case.case_id")
        if case_id in cases:
            raise ValueError("Duplicate manifest case_id")
        cases[case_id] = case
    run_index = {}
    for run in runs:
        identity = _text(run.get("id"), "run.id")
        _text(run.get("case_id"), "run.case_id")
        if cases and run["case_id"] not in cases:
            raise ValueError("run.case_id is absent from the frozen case manifest")
        if identity in run_index:
            raise ValueError(f"Duplicate run id {identity}")
        run_index[identity] = run
    contexts = {}
    for event in _rows(export.get("events", []), "events"):
        body = _object(event.get("body") or {}, "event.body")
        if body.get("type") == "context_observed" and body.get("model_call_id"):
            key = (event.get("run_id"), body["model_call_id"])
            if key in contexts:
                raise ValueError("Duplicate context observation for one ledger call")
            contexts[key] = body
    calls, seen = [], set()
    for call in _rows(export.get("tool_calls"), "tool_calls"):
        identity = _text(call.get("id"), "tool_call.id")
        if identity in seen:
            raise ValueError(f"Duplicate ledger call id {identity}")
        seen.add(identity)
        if call.get("run_id") not in run_index:
            raise ValueError("tool_call.run_id must refer to an exported run")
        if call.get("tool") != "model":
            continue  # Token-count preflight and business tools are never generation usage.
        run = run_index[call["run_id"]]
        binding = _object(call.get("execution_binding") or {}, "call.execution_binding")
        metric = contexts.get((call["run_id"], identity), {})
        budget = _object((call.get("result") or {}).get("context_budget") or {}, "context_budget")
        calls.append({"id": identity, "run_id": call["run_id"], "case_id": run["case_id"],
                      "suite": run.get("suite", "unknown"), "state": call.get("state"),
                      "error_code": call.get("error_code"),
                      "isolation": binding.get("isolation", "unknown"),
                      "route_digest": binding.get("model_route_digest", "unknown"),
                      "model_version": binding.get("model_version"),
                      "prompt_digest": binding.get("prompt_digest"),
                      "tool_definitions_digest": binding.get("tool_definitions_digest"),
                      "created_at": call.get("created_at"),
                      "provider_request_id": call.get("provider_request_id"),
                      "elapsed_ms": _optional_number(call.get("elapsed_ms"), "call.elapsed_ms"),
                      "session_phase": ("continued_run" if run.get("continued_from_id")
                                        else "initial_run"),
                      "probe_phase": run.get("probe_phase"),
                      "focus": budget.get("focus", metric.get("focus", run.get("focus"))),
                      "usage": _usage(call, metric), "cost": _cost(call),
                      "context": _context(budget, metric)})
    calls.sort(key=lambda row: (row["run_id"], row["isolation"],
                               row["created_at"] or "", row["id"]))
    ordering = defaultdict(list)
    for call in calls:
        ordering[(call["run_id"], call["isolation"])].append(call["created_at"])
    ordinals = Counter()
    for call in calls:
        key = (call["run_id"], call["isolation"])
        ordinals[key] += 1
        times = ordering[key]
        known_order = None not in times and len(set(times)) == len(times)
        call["isolation_model_call_ordinal"] = ordinals[key] if known_order else None
        call["model_round"] = ("first" if ordinals[key] == 1 else "subsequent") \
            if known_order else "unknown"
    grouped = defaultdict(list)
    strata = defaultdict(list)
    dimensions = ("case_id", "run_id", "suite", "isolation", "route_digest", "focus",
                  "session_phase", "model_round", "probe_phase")
    for call in calls:
        for dimension in dimensions:
            grouped[(dimension, call[dimension])].append(call)
        strata[tuple(call[name] for name in (
            "case_id", "run_id", "isolation", "route_digest", "focus", "model_round",
        ))].append(call)
    run_results = []
    for run in runs:
        elapsed = _optional_number(run.get("elapsed_ms"), "run.elapsed_ms")
        first_visible = _optional_number(run.get("first_visible_ms"), "run.first_visible_ms")
        run_results.append({"id": run["id"], "case_id": run["case_id"],
                            "suite": run.get("suite", "unknown"), "state": run.get("state"),
                            "error_code": run.get("error_code"), "elapsed_ms": elapsed,
                            "first_visible_ms": first_visible,
                            "quality": _quality(run),
                            "metrics": _aggregate(grouped[("run_id", run["id"])])})
    return {"version": VERSION,
            "limitations": ["Synthetic candidate questions do not confer production qualification.",
                            "Internal rate-card costs are not provider invoices.",
                            "Unknown usage/cache/latency is not zero; inspect coverage counts.",
                            "Repeated requests alone do not demonstrate provider cache hits.",
                            "Nearest-rank p50/p95 are descriptive, with no significance claim.",
                            "Mechanical comparisons cannot replace semantic or audience review."],
            "summary": {"runs": len(runs), "cases_observed": len({r["case_id"] for r in runs}),
                        "expected_cases": len(cases) if cases else None,
                        "cases_without_run": sorted(set(cases) - {r["case_id"] for r in runs}),
                        "run_states": dict(Counter(r.get("state", "unknown") for r in runs)),
                        **_aggregate(calls),
                        "run_elapsed_ms": _latency(r["elapsed_ms"] for r in run_results),
                        "first_visible_ms": _latency(r["first_visible_ms"] for r in run_results)},
            "groups": [{"dimension": key[0], "value": key[1], **_aggregate(values)}
                       for key, values in sorted(grouped.items(), key=lambda item: str(item[0]))],
            "strata": [{**dict(zip(("case_id", "run_id", "isolation", "route_digest", "focus",
                                    "model_round"), key, strict=True)), **_aggregate(values)}
                       for key, values in sorted(strata.items(), key=lambda item: str(item[0]))],
            "runs": run_results, "model_calls": calls}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"Non-finite JSON constant: {value}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    raw = args.input.read_bytes()
    result = summarize(json.loads(raw, object_pairs_hook=_unique_object,
                                  parse_constant=_reject_constant))
    result["input_sha256"] = hashlib.sha256(raw).hexdigest()
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
