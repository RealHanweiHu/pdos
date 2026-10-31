"""Content-free per-call runtime metrics derived from the durable model ledger."""

import json
from uuid import UUID, uuid4

from sqlalchemy import func, select

from pdos_next.errors import DomainError

from .bindings import ModelBinding
from .models import AgentEvent, AgentToolCall

RUNTIME_KEY = "context_runtime_v1"
ADMISSION_SEGMENTS = ("system", "tools", "skills", "envelope", "history", "loop")


def carried_counts(messages):
    try:
        context = json.loads(messages[0]["content"]).get("context", {})
    except (IndexError, KeyError, TypeError, ValueError, AttributeError):
        context = {}
    turns = context.get("conversation", {}).get("turns", [])
    states = [row.get("outcome_state") for row in turns if isinstance(row, dict)]
    work = context.get("work_state", {})
    outcomes = [row.get("historical_outcome") or {} for row in turns if isinstance(row, dict)]
    return {
        "history": {"carried": len(turns),
                    "kept": sum(state in {"current", "updated"} for state in states),
                    "updated": states.count("updated"), "hidden": states.count("hidden"),
                    "unclassified": sum(state not in {"current", "updated", "hidden"}
                                        for state in states),
                    "truncated": sum(bool(outcome.get("truncated")) for outcome in outcomes),
                    "directories": sum("仅显示目录" in outcome.get("notes", [])
                                       for outcome in outcomes)},
        "work_state": {"revision": work.get("revision"),
                       "context_incomplete": bool(work.get("context_incomplete")),
                       "item_counts": {key: len(work.get(key, [])) for key in (
                           "constraints", "exclusions", "focus_objects", "completed",
                           "candidates", "unfinished", "questions", "citations",
                       ) if isinstance(work.get(key, []), list)}},
    }


def call_metrics(*, budget, usage, messages, cleanup_count=0, previous_error_streak=0):
    """Provider actuals are aggregate only; never fabricate actual segment tokens."""
    actual = usage.get("input_tokens", 0)
    estimated = budget.get("estimated_total", 0)
    ratio = abs(estimated - actual) / actual if actual > 0 else None
    streak = previous_error_streak + 1 if ratio is not None and ratio > .1 else 0
    cache_read = usage.get("cache_read_tokens", 0)
    cache_creation = usage.get("cache_creation_tokens", 0)
    warnings = []
    if budget.get("fixed_over_half"):
        warnings.append("fixed_over_half_focus")
    if cleanup_count > 2:
        warnings.append("cleanup_more_than_twice")
    if streak >= 2:
        warnings.append("persistent_estimation_error")
    return {
        "version": 1, "window": budget.get("window"),
        "window_configured": budget.get("window_configured"),
        "reserve": budget.get("reserve"), "focus": budget.get("focus"),
        "segments": {key: {"estimated_tokens": value, "actual_tokens": None}
                     for key, value in budget.get("segments", {}).items()},
        "actual_segment_tokens": "provider_not_reported",
        "estimated_input_tokens": estimated, "admission_tokens": budget.get("admission_tokens"),
        "actual_input_tokens": actual, "actual_output_tokens": usage.get("output_tokens", 0),
        "estimation_error_ratio": ratio, "estimation_error_streak": streak,
        "calibration_factor": budget.get("calibration_factor"),
        "estimation_basis": budget.get("estimation_basis"),
        "cache": {"read_tokens": cache_read, "creation_tokens": cache_creation,
                  "read_hit_ratio": cache_read / actual if actual > 0 and cache_read > 0 else None,
                  "reporting": "positive_usage_reported" if cache_read or cache_creation
                  else "zero_or_unreported",
                  "input_includes_cache": True},
        "cleanup": budget.get("cleanup", {"applied": False, "reason": "legacy_call"}),
        "cleanup_count": cleanup_count, "reductions": budget.get("reductions", []),
        **carried_counts(messages), "warnings": warnings,
    }


def _append(session, run, body):
    sequence = session.scalar(select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(
        AgentEvent.run_id == run.id,
    )) + 1
    session.add(AgentEvent(id=uuid4(), tenant_id=run.tenant_id, run_id=run.id,
                           sequence=sequence, body=body))


def record_call(store, scope, turn, messages):
    """Exactly once per completed real model row, including gateway replay.

    No result/usage is accepted from the provider's ModelTurn fields. Only the
    server-assigned ID locates the existing completed ledger row under this Run.
    """
    if turn.ledger_call_id is None:
        return None  # Pure graph ports and legacy model-less harnesses.
    with store.transaction(scope, lock=True) as (session, run):
        row = session.get(AgentToolCall, turn.ledger_call_id)
        if (row is None or row.tenant_id != scope.tenant_id or row.run_id != scope.run_id
                or row.tool != "model" or row.state != "completed" or row.error_code is not None):
            raise DomainError("FORBIDDEN_SCOPE", "上下文计量缺少本次实际模型账本。")
        binding = ModelBinding.model_validate(row.execution_binding)
        if binding.isolation != scope.isolation or binding.cancel_epoch != scope.cancel_epoch:
            raise DomainError("FORBIDDEN_SCOPE", "上下文计量不能跨运行隔离或取消边界。")
        result = row.result or {}
        if not result.get("context_budget") or not result.get("usage"):
            return None  # Historical calls may predate context metering.
        return _record_metric(session, run, scope, row, binding, result["context_budget"],
                              result["usage"], messages)


def _record_metric(session, run, scope, row, binding, budget, usage, messages, *,
                   usage_known=True, cache_known=True):
    runtime = run.versions.get(RUNTIME_KEY, {})
    calls = runtime.get("calls", {})
    key = str(row.id)
    if key in calls:
        return calls[key]
    counter = runtime.get("cleanup_count", 0)
    if budget.get("cleanup", {}).get("applied"):
        counter += 1
    route_key = scope.isolation + ":" + binding.model_route_digest
    previous = runtime.get("routes", {}).get(route_key, {})
    metrics = call_metrics(
        budget=budget, usage=usage, messages=messages, cleanup_count=counter,
        previous_error_streak=previous.get("error_streak", 0),
    )
    if not usage_known:
        # charged_tokens can be a held upper bound for unknown outcomes. It is
        # never passed off as provider-measured input/output or a cache miss.
        metrics.update(actual_input_tokens=None, actual_output_tokens=None,
                       estimation_error_ratio=None, estimation_error_streak=0)
    if not cache_known:
        metrics["cache"] = {"read_tokens": None, "creation_tokens": None,
                            "read_hit_ratio": None, "input_includes_cache": True,
                            "status": "not_recorded_for_failed_call"}
    metrics["call_state"] = row.state
    metrics["usage_status"] = "recorded" if usage_known else "unavailable"
    limits = {key: getattr(run, column, None) for key, column in (
        ("limit", "token_limit"), ("used", "used_tokens"), ("held", "held_tokens"),
    )}
    metrics["run_budget"] = {**limits, "remaining": max(
        0, limits["limit"] - limits["used"] - limits["held"],
    ) if all(type(value) is int for value in limits.values()) else None}
    body = {"type": "context_observed", "model_call_id": key,
            "isolation": scope.isolation, "route_digest": binding.model_route_digest,
            **metrics}
    _append(session, run, body)
    run.versions = {**run.versions, RUNTIME_KEY: {
        **runtime, "cleanup_count": counter, "calls": {**calls, key: metrics},
        "routes": {**runtime.get("routes", {}), route_key: {
            "error_streak": metrics["estimation_error_streak"],
        }},
    }}
    return metrics


def record_failed(store, scope, error, messages, budget):
    """Observe an actual failed/unknown model row; no retry or guessed usage."""
    try:
        identity = UUID(error.detail["call_id"])
    except (KeyError, TypeError, ValueError):
        return None  # Authorization/preclaim errors are not provider calls.
    with store.transaction(scope, lock=True) as (session, run):
        row = session.get(AgentToolCall, identity)
        if (row is None or row.tenant_id != scope.tenant_id or row.run_id != scope.run_id
                or row.tool != "model" or row.state not in {"failed", "unknown"}):
            return None
        binding = ModelBinding.model_validate(row.execution_binding)
        if binding.isolation != scope.isolation or binding.cancel_epoch != scope.cancel_epoch:
            raise DomainError("FORBIDDEN_SCOPE", "失败调用计量不能跨隔离或取消边界。")
        known = row.cost_state == "actual" and row.state == "failed"
        usage = {"input_tokens": row.actual_input_tokens or 0,
                 "output_tokens": row.actual_output_tokens or 0} if known else {}
        return _record_metric(session, run, scope, row, binding, budget, usage, messages,
                              usage_known=known, cache_known=False)


def record_incomplete(store, scope, error, messages):
    """A failed admission has no model row and never reserves or calls a model."""
    from pdos_next.service import digest

    budget = error.detail.get("context_budget", {})
    key = digest([scope.isolation, messages, budget])
    with store.transaction(scope, lock=True) as (session, run):
        runtime = run.versions.get(RUNTIME_KEY, {})
        failures = runtime.get("incomplete", [])
        if key in failures:
            return
        estimates = budget.get("segments")
        # The failed admission has no provider usage. Persist only its actual
        # numeric meter fields, not arbitrary budget/error content or text.
        measured_segments = {key: {
            "estimated_tokens": estimates.get(key)
            if type(estimates.get(key)) is int and estimates[key] >= 0 else None,
            "actual_tokens": None,
        } for key in ADMISSION_SEGMENTS} if isinstance(estimates, dict) else None
        total = budget.get("estimated_total")
        fixed = budget.get("fixed_over_half")
        _append(session, run, {
            "type": "context_admission_observed", "isolation": scope.isolation,
            "context_incomplete": True, "window": budget.get("window"),
            "reserve": budget.get("reserve"), "focus": budget.get("focus"),
            "admission_tokens": budget.get("admission_tokens"),
            "segments": measured_segments,
            "estimated_input_tokens": total if type(total) is int and total >= 0 else None,
            "fixed_over_half": fixed if type(fixed) is bool else None,
            "cleanup": budget.get("cleanup"), "reductions": budget.get("reductions", []),
            "missing": error.detail.get("missing", []),
            **carried_counts(messages), "warnings": ["context_incomplete", *(
                ["fixed_over_half_focus"] if fixed is True else []
            )],
        })
        run.versions = {**run.versions, RUNTIME_KEY: {**runtime, "incomplete": [*failures, key]}}
