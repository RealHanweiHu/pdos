"""Public action history from persisted metadata, never provider text or tool arguments."""

from uuid import UUID, uuid4

from sqlalchemy import func, select

from pdos_next.clock import now
from pdos_next.errors import DomainError
from pdos_next.models import Artifact

from .models import AgentEvent, AgentToolCall

KINDS = (
    "accepted",
    "skill_loaded",
    "context_projected",
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
            }
            for row in reversed(visible)
        ],
        "next_before": visible[-1].sequence if len(rows) > page_size else None,
    }
