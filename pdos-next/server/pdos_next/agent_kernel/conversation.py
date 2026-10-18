"""Private task memory rebuilt from actual linked Runs, never from browser transcripts."""

from types import SimpleNamespace
from uuid import UUID

from pydantic import Field
from sqlalchemy import select

from pdos_next.contracts import SourceRead
from pdos_next.errors import DomainError
from pdos_next.schema_base import StrictModel
from pdos_next.service import digest

from .execution import scope_for_run
from .models import AgentRun, AgentSession, AgentToolCall
from .run_reconciliation import owner


class HistoryInput(StrictModel):
    before: UUID | None = None
    page_size: int = Field(default=10, ge=1, le=25)
    include_research_rows: bool = False


def prepare(session, ctx, data):
    identity = data.continue_from_run_id
    if identity is None:
        return data, None
    if (
        data.session_id
        or data.product_id
        or data.proposal_id
        or getattr(data, "project_id", None) is not None
        or data.sources
    ):
        raise DomainError(
            "VALIDATION_FAILED", "继续工作只需原运行和新目标，范围由服务器沿用。", 422
        )
    parent = session.scalar(select(AgentRun).where(AgentRun.id == identity).with_for_update())
    if parent is None:
        raise DomainError("FORBIDDEN_SCOPE", "原工作不在当前可读范围。", 403)
    owner(session, ctx, parent)
    if parent.reverted_at or parent.state not in {"completed", "partial", "failed", "cancelled"}:
        raise DomainError("VERSION_CONFLICT", "原工作尚未结束或已撤回，请先核对原运行。")
    existing = session.scalar(select(AgentRun.id).where(AgentRun.continued_from_id == parent.id))
    if existing:
        raise DomainError(
            "VERSION_CONFLICT",
            "原工作已有后续，请打开后续工作继续。",
            detail={"next_run_id": str(existing)},
        )
    conversation = session.scalar(
        select(AgentSession).where(AgentSession.id == parent.session_id).with_for_update()
    )
    if conversation is None or conversation.owner_id != ctx.requester_id:
        raise DomainError("FORBIDDEN_SCOPE", "原会话不在当前本人范围。", 403)
    effective = data.model_copy(
        update={
            "session_id": parent.session_id,
            "product_id": parent.product_id,
            "proposal_id": parent.proposal_id,
            "project_id": getattr(parent, "project_id", None),
            "sources": [
                SourceRead.model_validate(
                    {key: value for key, value in ref.items() if key != "product_id"}
                )
                for ref in parent.read_sources
            ],
        }
    )
    return effective, parent


def merge_binding(binding, parent):
    if parent is None:
        return binding
    return SimpleNamespace(
        **{
            **vars(binding),
            "private_context": binding.private_context or parent.private_context,
            "data_categories": tuple(
                sorted(set(binding.data_categories) | set(parent.data_categories))
            ),
            "customer_identities": tuple(
                sorted(set(binding.customer_identities) | set(parent.customer_identities))
            ),
        }
    )


def lineage(session, run):
    """One recursive metadata query; ordinary RLS must resolve every ancestor."""
    if run.continued_from_id is None:
        return []
    tree = (
        select(AgentRun.id, AgentRun.continued_from_id)
        .where(AgentRun.id == run.continued_from_id)
        .cte("conversation_lineage", recursive=True)
    )
    tree = tree.union_all(
        select(AgentRun.id, AgentRun.continued_from_id).join(
            tree, AgentRun.id == tree.c.continued_from_id
        )
    )
    fields = (
        "id",
        "tenant_id",
        "category_id",
        "product_id",
        "proposal_id",
        "project_id",
        "requester_id",
        "writer_id",
        "session_id",
        "cancel_epoch",
        "private_context",
        "data_categories",
        "customer_identities",
        "trigger",
        "goal",
        "state",
        "reverted_at",
        "read_sources",
        "continued_from_id",
    )
    rows = (
        session.execute(
            select(
                *(getattr(AgentRun, key) for key in fields),
                AgentRun.result["summary"].label("summary"),
                AgentRun.result["unfinished"].label("unfinished"),
            ).join(tree, AgentRun.id == tree.c.id)
        )
        .mappings()
        .all()
    )
    by_id = {}
    for raw in rows:
        values = dict(raw)
        values["result"] = {
            "summary": values.pop("summary"),
            "unfinished": values.pop("unfinished"),
        }
        by_id[values["id"]] = SimpleNamespace(**values)
    ordered, identity = [], run.continued_from_id
    while identity is not None:
        row = by_id.get(identity)
        if (
            row is None
            or row.session_id != run.session_id
            or row.requester_id != run.requester_id
            or row.category_id != run.category_id
            or row.product_id != run.product_id
            or row.proposal_id != run.proposal_id
            or getattr(row, "project_id", None) != getattr(run, "project_id", None)
            or row.reverted_at
            or row.state not in {"completed", "partial", "failed", "cancelled"}
        ):
            raise DomainError("FORBIDDEN_SCOPE", "原工作来源或会话范围已失效，请重新核对。", 403)
        ordered.append(row)
        identity = row.continued_from_id
    return ordered


def cached_outcome(session, run, readers, consumer, *, include_research_rows=False):
    """Only local registered reads may revalidate a summary; never repeat network/model work."""
    calls = session.execute(
        select(
            AgentToolCall.id,
            AgentToolCall.tool,
            AgentToolCall.state,
            AgentToolCall.receipt_id,
            AgentToolCall.execution_binding,
        ).where(AgentToolCall.run_id == run.id, AgentToolCall.tool != "model")
    ).all()
    research = []
    for call in calls:
        binding = call.execution_binding or {}
        if binding.get("isolation") not in {None, "main"}:
            continue  # The parent main read's restore owns its isolated source closure.
        if binding.get("kind") != "read":
            # Prepared candidates grant no authority. Check real business receipts below.
            if binding.get("kind") != "domain_t0":
                return None
            from pdos_next.models import Receipt

            if (
                call.receipt_id is None
                or session.scalar(select(Receipt.id).where(Receipt.id == call.receipt_id)) is None
            ):
                return None
            continue
        callback = readers.get(call.tool)
        if callback is None or call.state != "completed":
            return None
        try:
            model_calls = session.scalar(
                select(AgentToolCall.result["calls"]).where(
                    AgentToolCall.id == UUID(binding["model_call_id"])
                )
            )
            request = model_calls[binding["response_index"]]
            previous = session.scalar(
                select(AgentToolCall.result).where(AgentToolCall.id == call.id)
            )
            current = callback(scope_for_run(run), request["arguments"], previous, consumer)
            if request["name"] != call.tool or digest(current) != digest(previous):
                return None
            if call.tool == "research.fanout":
                research.append(
                    {
                        "job_id": current["job_id"],
                        "status": current["status"],
                        "snapshots": current["snapshots"],
                        "row_count": len(current["ledger"]),
                        **(
                            {
                                "ledger": current["ledger"],
                                "coverage": current["coverage"],
                                "failures": current["failures"],
                            }
                            if include_research_rows
                            else {}
                        ),
                    }
                )
        except (DomainError, KeyError, TypeError, ValueError, AttributeError):
            return None
    result = run.result or {}
    return {
        "summary": result.get("summary", ""),
        "unfinished": result.get("unfinished", []),
        "research": research,
    }


def memory(session, run, *, readers, before=None, page_size=10, include_research_rows=False):
    rows = lineage(session, run)
    root = rows[-1] if rows else run
    if before is not None:
        ids = [row.id for row in rows]
        if before not in ids:
            raise DomainError("FORBIDDEN_SCOPE", "历史游标不属于本次工作。", 403)
        rows = rows[ids.index(before) + 1 :]
    selected = rows[:page_size]
    turns = []
    for row in selected:
        outcome = cached_outcome(
            session, row, readers, scope_for_run(run), include_research_rows=include_research_rows
        )
        turns.append(
            {
                "run_id": str(row.id),
                "goal": row.goal,
                "status": row.state,
                "historical_outcome": outcome,
                "outcome_state": "historical_cache"
                if outcome is not None
                else "rebuild_from_sources",
                "sources": row.read_sources,
                "original_record": {"run_id": str(row.id), "session_id": str(row.session_id)},
            }
        )
    return {
        "session_id": str(run.session_id),
        "root_goal": root.goal,
        "root_run_id": str(root.id),
        "turns": turns,
        "next_before": str(selected[-1].id) if len(rows) > page_size else None,
        "fact_policy": "Historical summaries are caches, not current domain facts. "
        "Re-read exact objects and sources before acting. "
        "Use conversation.history for earlier requests; never infer missing constraints.",
    }


def links(session, run):
    child = session.scalar(select(AgentRun.id).where(AgentRun.continued_from_id == run.id))
    return {
        "previous_run_id": str(run.continued_from_id) if run.continued_from_id else None,
        "next_run_id": str(child) if child else None,
    }
