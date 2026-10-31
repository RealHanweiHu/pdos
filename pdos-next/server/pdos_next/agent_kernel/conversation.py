"""Private task memory rebuilt from actual linked Runs, never from browser transcripts."""

from types import SimpleNamespace
from uuid import UUID

from pydantic import Field
from sqlalchemy import select

from pdos_next.errors import DomainError
from pdos_next.schema_base import StrictModel

from .execution import scope_for_run
from .models import AgentRun, AgentSession
from .run_reconciliation import owner
from .session_bindings import current_proposal_id

RECENT_TURNS = 3
RECENT_ANSWER_CHARS = 600
DIRECTORY_CHARS = 60
HISTORY_ANSWER_CHARS = 8000
REVOKED_CODES = frozenset({"FORBIDDEN_SCOPE", "NOT_FOUND", "SOURCE_UNAVAILABLE"})
UPDATED_CODES = frozenset({"SOURCE_STALE", "VERSION_CONFLICT"})


class HistoryInput(StrictModel):
    before: UUID | None = None
    page_size: int = Field(default=10, ge=1, le=25)
    include_research_rows: bool = False


def prepare(session, ctx, data):
    identity = data.continue_from_run_id
    if identity is None:
        if getattr(data, "context_revision", None) is not None:
            raise DomainError("VALIDATION_FAILED", "资料纠正须从当前会话继续。", 422)
        return data, None
    if (
        data.session_id
        or data.product_id
        or data.proposal_id
        or getattr(data, "project_id", None) is not None
    ):
        raise DomainError(
            "VALIDATION_FAILED",
            "继续工作只需原运行、新目标和可选新增来源，其他范围由服务器沿用。",
            422,
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
        # Session keys are immutable. Serialize continuations while permitting
        # the FK KEY SHARE lock used by a concurrent human work-state append.
        select(AgentSession).where(AgentSession.id == parent.session_id)
        .with_for_update(key_share=True)
    )
    if conversation is None or conversation.owner_id != ctx.requester_id:
        raise DomainError("FORBIDDEN_SCOPE", "原会话不在当前本人范围。", 403)
    if parent.proposal_id is not None and parent.proposal_id != current_proposal_id(
        session, conversation
    ):
        raise DomainError("FORBIDDEN_SCOPE", "原工作与当前会话提案范围不一致。")
    from .context_corrections import selected_reads, values
    from .work_state import _lock, latest

    _lock(session, ctx.tenant_id, parent.session_id)
    state = latest(session, parent.session_id)
    expected_context = getattr(data, "context_revision", None)
    if expected_context is not None and (state is None or state.revision != expected_context):
        raise DomainError("VERSION_CONFLICT", "资料条件已变化，请按最新携带重新选择。")
    sources, selection = selected_reads(session, ctx, parent, state, data.sources)
    actual = values(selection)
    parent._explicit_context_binding = {
        "private_context": any(row["private"] for row in actual),
        "data_categories": ["customer_original"]
        if any(row["customer_original"] for row in actual) else [],
    }
    effective = data.model_copy(
        update={
            "session_id": parent.session_id,
            "product_id": parent.product_id,
            "proposal_id": current_proposal_id(session, conversation),
            "project_id": getattr(parent, "project_id", None),
            "sources": sources,
        }
    )
    return effective, parent


def merge_binding(binding, parent):
    if parent is None:
        return binding
    selected = getattr(parent, "_explicit_context_binding", {})
    return SimpleNamespace(
        **{
            **vars(binding),
            "private_context": binding.private_context or parent.private_context
                or selected.get("private_context", False),
            "data_categories": tuple(
                sorted(set(binding.data_categories) | set(parent.data_categories)
                       | set(selected.get("data_categories", [])))
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
            "summary": values.pop("summary") or "",
            "unfinished": values.pop("unfinished") or [],
        }
        by_id[values["id"]] = SimpleNamespace(**values)
    conversation = session.get(AgentSession, run.session_id)
    current_proposal = (
        current_proposal_id(session, conversation) if conversation is not None else None
    )
    if (
        conversation is None
        or conversation.owner_id != run.requester_id
        or current_proposal != run.proposal_id
        and not (run.proposal_id is None and current_proposal is not None)
    ):
        raise DomainError("FORBIDDEN_SCOPE", "原工作与会话当前范围不一致。")
    ordered, identity = [], run.continued_from_id
    while identity is not None:
        row = by_id.get(identity)
        if (
            row is None
            or row.session_id != run.session_id
            or row.requester_id != run.requester_id
            or row.category_id != run.category_id
            or row.product_id != run.product_id
            or (row.proposal_id is not None and row.proposal_id != run.proposal_id)
            or getattr(row, "project_id", None) != getattr(run, "project_id", None)
            or row.reverted_at
            or row.state not in {"completed", "partial", "failed", "cancelled"}
        ):
            raise DomainError("FORBIDDEN_SCOPE", "原工作来源或会话范围已失效，请重新核对。", 403)
        ordered.append(row)
        identity = row.continued_from_id
    return ordered


def classify_turn(session, run, readers, consumer, *, include_research_rows=False,
                  access=None, states=None):
    from .conversation_acl import classify, manifests

    access = manifests(session, [run]) if access is None else access
    states = classify(session, access) if states is None else states
    manifest, state = access[str(run.id)], states[str(run.id)]
    if state == "hidden":
        return {"state": state, "outcome": None}
    notes = []
    if state == "updated":
        notes.append("资料已更新，回答中的事实需重新读取")
    if manifest["prepared"]:
        notes.append("该轮准备过候选，候选以当前页面状态为准")
    if manifest["unverified"]:
        notes.append("以下读取未复核：" + "、".join(manifest["unverified"]))
    research = []
    if state == "current":
        for item in manifest["research"]:
            research.append({"job_id": item["job_id"], "status": item["status"],
                             "snapshots": item["snapshots"], "row_count": len(item["ledger"]),
                             **({key: item[key] for key in ("ledger", "coverage", "failures")}
                                if include_research_rows else {})})
    return {"state": state, "outcome": {
        "summary": (run.result or {}).get("summary", ""),
        "unfinished": (run.result or {}).get("unfinished", []),
        "research": research, "notes": notes,
    }}


def memory(
    session, run, *, readers, before=None, page_size=10, include_research_rows=False, layered=True,
    access_out=None,
):
    rows = lineage(session, run)
    ancestors = rows
    root = rows[-1] if rows else run
    if before is not None:
        ids = [row.id for row in rows]
        if before not in ids:
            raise DomainError("FORBIDDEN_SCOPE", "历史游标不属于本次工作。", 403)
        rows = rows[ids.index(before) + 1 :]
    selected = rows[:page_size]
    from .conversation_acl import classify, manifests

    access = manifests(session, selected, ancestors=ancestors, consumer=run)
    states = classify(session, access, consumer=run)
    if access_out is not None:
        access_out.update({identity: value for identity, value in access.items()
                           if states[identity] != "hidden"})
    turns = []
    for index, row in enumerate(selected):
        classified = classify_turn(
            session, row, readers, scope_for_run(run), include_research_rows=include_research_rows,
            access=access, states=states,
        )
        outcome = classified["outcome"]
        directory = layered and index >= RECENT_TURNS
        if outcome is not None:
            limit = DIRECTORY_CHARS if directory else (
                RECENT_ANSWER_CHARS if layered else HISTORY_ANSWER_CHARS
            )
            truncated = len(outcome["summary"]) > limit
            outcome["summary"] = outcome["summary"][:limit]
            if truncated and layered and not directory:
                outcome["summary"] += "…（已截断，完整内容可用 conversation.history 读取）"
            outcome["truncated"] = truncated or directory
            if directory:
                outcome["unfinished"], outcome["research"] = [], []
                outcome["notes"].append("仅显示目录")
        turns.append(
            {
                "run_id": str(row.id),
                "goal": row.goal[:DIRECTORY_CHARS] if directory else row.goal,
                "status": row.state,
                "historical_outcome": outcome,
                "outcome_state": classified["state"],
                "sources": [] if classified["state"] == "hidden" else row.read_sources,
                "original_record": {"run_id": str(row.id), "session_id": str(row.session_id)},
            }
        )
    return {
        "session_id": str(run.session_id),
        "root_goal": root.goal,
        "root_run_id": str(root.id),
        "turns": turns,
        "next_before": str(selected[-1].id) if len(rows) > page_size else None,
        "fact_policy": 'Historical answers are dated records, not current domain facts. '
        'outcome_state "updated" means sources changed after that answer; '
        're-read exact objects before relying on its facts. "hidden" means the answer '
        'was withheld because its sources are no longer readable. '
        'Use conversation.history for full earlier answers; never infer missing constraints.',
    }


def links(session, run):
    child = session.scalar(select(AgentRun.id).where(AgentRun.continued_from_id == run.id))
    return {
        "previous_run_id": str(run.continued_from_id) if run.continued_from_id else None,
        "next_run_id": str(child) if child else None,
    }
