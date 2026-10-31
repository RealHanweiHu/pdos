"""Public action history from persisted metadata, never provider text or tool arguments."""

import math
import re
from uuid import UUID, uuid4

from sqlalchemy import case, func, literal, select

from pdos_next.clock import now
from pdos_next.errors import DomainError
from pdos_next.models import Artifact

from .models import AgentEvent, AgentToolCall

KINDS = (
    "accepted",
    "skill_loaded",
    "context_projected",
    "context_observed",
    "context_admission_observed",
    "model_started",
    "tool_started",
    "tool_finished",
    "needs_input",
    "model_unavailable",
    "run_state",
    "reconciliation_required",
    "run_reconciled",
    "finished",
)
TERMINAL = {"completed", "partial", "cancelled", "failed"}

METRIC_KINDS = ("context_observed", "context_admission_observed")
WARNINGS = frozenset({"fixed_over_half_focus", "context_incomplete",
                      "cleanup_more_than_twice", "persistent_estimation_error"})
SEGMENTS = ("system", "tools", "skills", "envelope", "history", "loop")
WORK_ITEMS = ("constraints", "exclusions", "focus_objects", "completed", "candidates",
              "unfinished", "questions", "citations")
PATH = re.compile(
    r"(?:system|tool_definitions|output_schema|current_question|sources|"
    r"(?:work_state|context|conversation|proposal)\.[A-Za-z0-9_.\[\]/-]{1,180}|"
    r"(?:messages|skill_body|human_or_verification_message)\[\d+\])\Z"
)
METRIC_SHAPE = {
    "window": "count", "window_configured": "bool", "reserve": "count", "focus": "count",
    "segments": {key: {"estimated_tokens": "count", "actual_tokens": "count"}
                 for key in SEGMENTS},
    "estimated_input_tokens": "count", "admission_tokens": "count", "fixed_over_half": "bool",
    "actual_input_tokens": "count", "actual_output_tokens": "count",
    "estimation_error_ratio": "number", "estimation_error_streak": "count",
    "calibration_factor": "number",
    "estimation_basis": frozenset({"previous_actual_input", "first_call_estimate"}),
    "cache": {"read_tokens": "count", "creation_tokens": "count", "read_hit_ratio": "ratio",
              "input_includes_cache": "bool", "reporting": frozenset({
                  "positive_usage_reported", "zero_or_unreported",
              }), "status": frozenset({"not_recorded_for_failed_call"})},
    "cleanup": {"triggered": "bool", "applied": "bool", "minimum_tokens": "count",
                "before_tokens": "count", "after_tokens": "count", "saved_tokens": "count",
                "candidate_saved_tokens": "number", "eligible_results": "count",
                "protected_results": "count", "retained_latest_results": "count",
                "replaced_results": "count", "cache_invalidation_from_message": "count",
                "reason": frozenset({"within_focus", "no_eligible_results",
                    "no_controlled_compactor", "minimum_reached", "insufficient_eligible_tokens",
                    "legacy_call"})},
    "cleanup_count": "count",
    "history": {key: "count" for key in ("carried", "kept", "updated", "hidden",
                                        "unclassified", "truncated", "directories")},
    "work_state": {"revision": "count", "context_incomplete": "bool",
                   "item_counts": {key: "count" for key in WORK_ITEMS}},
    "run_budget": {key: "count" for key in ("limit", "used", "held", "remaining")},
    "context_incomplete": "bool",
    "call_state": frozenset({"completed", "failed", "unknown"}),
    "usage_status": frozenset({"recorded", "unavailable"}),
    "isolation": frozenset({"main", "research", "extract", "mcp", "assistant_extract",
                            "assistant_compare"}),
}
# SQL never selects the full event body, raw model result, execution binding or
# Run.versions. Nested sections are then projected to a closed scalar schema.
METRIC_KEYS = (*METRIC_SHAPE, "warnings", "reductions", "missing")


def _metric_value(value, shape):
    if isinstance(shape, dict):
        return {key: _metric_value(value.get(key), child) for key, child in shape.items()} \
            if isinstance(value, dict) else None
    if isinstance(shape, frozenset):
        return value if isinstance(value, str) and value in shape else None
    if shape == "bool":
        return value if type(value) is bool else None
    if shape == "count":
        return value if type(value) is int and 0 <= value <= 2**53 - 1 else None
    if shape in {"number", "ratio"}:
        if (type(value) not in {int, float} or abs(value) > 2**53 - 1
                or not math.isfinite(value) or value < 0):
            return None
        return value if shape != "ratio" or value <= 1 else None
    if shape == "path":
        return value if isinstance(value, str) and PATH.fullmatch(value) else None
    return None


def public_context_metrics(value, kind):
    """Only bounded, content-free recorded metadata reaches the public process."""
    if kind not in METRIC_KINDS or not isinstance(value, dict):
        return None
    result = {key: _metric_value(value.get(key), shape) for key, shape in METRIC_SHAPE.items()}
    result["version"] = 1  # Public projection version, not a fabricated provider fact.
    result["context_incomplete"] = kind == "context_admission_observed" or (
        result["context_incomplete"] is True
    )
    warnings = value.get("warnings", [])
    result["warnings"] = list(dict.fromkeys(item for item in warnings
        if isinstance(item, str) and item in WARNINGS)) if isinstance(warnings, list) else []
    reductions = value.get("reductions")
    result["reductions_count"] = len(reductions) if isinstance(reductions, list) else None
    result["reductions"] = [{
        "kind": _metric_value(item.get("kind"), frozenset({"history_directory",
            "history_answer_preview", "older_tool_result", "object_detail_directory"})),
        "field": _metric_value(item.get("field"), "path"),
        # This is display metadata, never permission or a tool dispatch.
        "recoverable": isinstance(item.get("read_more"), dict)
        and item["read_more"].get("tool") in {
            "result.read", "conversation.history", "proposal.items.read",
        },
    } for item in reductions[:100] if isinstance(item, dict)] \
        if isinstance(reductions, list) else []
    missing = value.get("missing")
    result["missing_count"] = len(missing) if isinstance(missing, list) else None
    result["missing"] = [{"field": _metric_value(item.get("field"), "path"),
                          "estimated_tokens": _metric_value(item.get("estimated_tokens"), "count")}
                         for item in missing[:256] if isinstance(item, dict)] \
        if isinstance(missing, list) else []
    return result


def _metric_columns(kind):
    return case((kind.in_(METRIC_KINDS), func.jsonb_build_object(*[
        part for key in METRIC_KEYS for part in (literal(key), AgentEvent.body[key])
    ])), else_=None).label("context_metric_data")


def record_state(session, run):
    """Called inside the existing locked Run transaction; no separate work or model call."""
    sequence = (
        session.scalar(
            select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(
                AgentEvent.run_id == run.id
            )
        )
        + 1
    )
    session.add(
        AgentEvent(
            id=uuid4(),
            tenant_id=run.tenant_id,
            run_id=run.id,
            sequence=sequence,
            body={"type": "run_state", "status": run.state, "error_code": run.error_code},
        )
    )


def read_process(
    session, run, *, before=None, source_cursor=None, receipt_cursor=None, page_size=25
):
    kind = AgentEvent.body["type"].astext
    query = select(
        AgentEvent.id,
        AgentEvent.sequence,
        AgentEvent.created_at,
        kind.label("kind"),
        AgentEvent.body["tool"].astext.label("tool"),
        AgentEvent.body["key"].astext.label("skill"),
        AgentEvent.body["version"].astext.label("version"),
        AgentEvent.body["status"].astext.label("status"),
        AgentEvent.body["fields"].label("context_fields"),
        AgentEvent.body["omitted"].label("context_omitted"),
        AgentEvent.body["issues"].label("context_issues"),
        _metric_columns(kind),
    ).where(AgentEvent.run_id == run.id, kind.in_(KINDS))
    if before is not None:
        if not session.scalar(
            select(AgentEvent.id).where(
                AgentEvent.run_id == run.id, AgentEvent.sequence == before, kind.in_(KINDS)
            )
        ):
            raise DomainError("FORBIDDEN_SCOPE", "过程游标不属于当前运行的公开步骤。", 403)
        query = query.where(AgentEvent.sequence < before)
    rows = session.execute(query.order_by(AgentEvent.sequence.desc()).limit(page_size + 1)).all()
    visible = rows[:page_size]
    counts = dict(
        session.execute(
            select(AgentToolCall.state, func.count(AgentToolCall.id))
            .where(AgentToolCall.run_id == run.id)
            .group_by(AgentToolCall.state)
        ).all()
    )
    # Provider deltas can be numerous and can contain private reasoning. Read only
    # selected JSON keys, filter the event types in SQL and bound each page.
    end = (
        session.scalar(
            select(func.max(AgentEvent.created_at)).where(
                AgentEvent.run_id == run.id,
                (kind.in_(["finished", "run_reconciled"]))
                | ((kind == "run_state") & AgentEvent.body["status"].astext.in_(TERMINAL)),
            )
        )
        if run.state in TERMINAL
        else None
    )
    latest = session.scalar(
        select(func.max(AgentEvent.created_at)).where(AgentEvent.run_id == run.id, kind.in_(KINDS))
    )
    from .run_reconciliation import _receipts

    receipts = _receipts(session, run)
    source_ids = {UUID(ref["artifact_id"]): ref["expected_revision"] for ref in run.read_sources}
    if source_cursor is not None and source_cursor not in source_ids:
        raise DomainError("FORBIDDEN_SCOPE", "依据游标不属于当前运行。", 403)
    if receipt_cursor is not None and receipt_cursor not in {row.id for row in receipts}:
        raise DomainError("FORBIDDEN_SCOPE", "提交记录游标不属于当前运行。", 403)
    receipt_page = [row for row in receipts if receipt_cursor is None or row.id > receipt_cursor]
    sources = (
        session.execute(
            select(Artifact.id, Artifact.title, Artifact.revision)
            .where(
                Artifact.id.in_(
                    [
                        identity
                        for identity in source_ids
                        if source_cursor is None or identity > source_cursor
                    ]
                ),
                Artifact.tenant_id == run.tenant_id,
                Artifact.category_id == run.category_id,
            )
            .order_by(Artifact.id)
            .limit(page_size + 1)
        ).all()
        if source_ids
        else []
    )
    # The page uses a snapshot time for running/waiting age. Only a real terminal
    # event fixes the end; legacy histories without one keep an explicit unknown.
    return {
        "run_id": str(run.id),
        "status": run.state,
        "reverted": run.reverted_at is not None,
        "error_code": run.error_code,
        "started_at": run.created_at.isoformat(),
        "observed_at": now().isoformat(),
        "last_recorded_at": latest.isoformat() if latest else None,
        "ended_at": end.isoformat() if end else None,
        "elapsed_seconds": max(0, (end - run.created_at).total_seconds()) if end else None,
        "call_counts": {
            "total": sum(counts.values()),
            "completed": counts.get("completed", 0),
            "pending": counts.get("started", 0) + counts.get("unknown", 0),
            "failed": counts.get("failed", 0),
        },
        "source_count": len(run.read_sources),
        "sources": [
            {
                "id": str(row.id),
                "title": row.title,
                "bound_revision": source_ids[row.id],
                "current_revision": row.revision,
            }
            for row in sources[:page_size]
        ],
        "next_source_cursor": str(sources[page_size - 1].id) if len(sources) > page_size else None,
        "business_receipt_count": len(receipts),
        "receipts": [
            {
                "id": str(row.id),
                "operation": row.operation,
                "subject_id": str(row.subject_id),
                "subject_revision": row.subject_revision,
            }
            for row in receipt_page[:page_size]
        ],
        "next_receipt_cursor": str(receipt_page[page_size - 1].id)
        if len(receipt_page) > page_size
        else None,
        "steps": [
            {
                "id": str(row.id),
                "sequence": row.sequence,
                "at": row.created_at.isoformat(),
                "kind": row.kind,
                "tool": row.tool if row.kind in {"tool_started", "tool_finished"} else None,
                "skill": row.skill if row.kind == "skill_loaded" else None,
                "version": row.version if row.kind == "skill_loaded" else None,
                "status": row.status
                if row.kind in {"finished", "run_state", "context_projected"} else None,
                **({"context_fields": row.context_fields or [],
                    "context_omitted": row.context_omitted or [],
                    "context_issues": row.context_issues or []}
                   if row.kind == "context_projected" else {}),
                **({"context_metrics": public_context_metrics(row.context_metric_data, row.kind)}
                   if row.kind in METRIC_KINDS else {}),
            }
            for row in reversed(visible)
        ],
        "next_before": visible[-1].sequence if len(rows) > page_size else None,
    }
