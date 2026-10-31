"""Verbatim owner goals from append-only work state, without reading hidden Run bodies.

Only current_goal.text is selected from body. This is a presentation fallback,
never a Run scope, model input authority, source permission or continuation proof.
"""

from sqlalchemy import String, and_, cast, func, select

from .work_state_models import AgentWorkState


def goal_rows(sessions):
    # Delay this router import until runtime; work_state depends on session_views.
    from .work_state import PAGE_MATERIAL_BOUNDARY

    current = AgentWorkState.body["current_goal"]
    return select(
        AgentWorkState.run_id,
        AgentWorkState.session_id,
        AgentWorkState.revision,
        AgentWorkState.created_at.label("recorded_at"),
        func.split_part(current["text"].astext, PAGE_MATERIAL_BOUNDARY, 1).label("goal"),
        sessions.c.category_id.label("session_category_id"),
        sessions.c.product_id.label("session_product_id"),
        sessions.c.proposal_id.label("session_proposal_id"),
        sessions.c.project_id.label("session_project_id"),
    ).join(sessions, and_(
        AgentWorkState.tenant_id == sessions.c.tenant_id,
        AgentWorkState.session_id == sessions.c.session_id,
        AgentWorkState.owner_id == sessions.c.owner_id,
    )).where(
        AgentWorkState.origin == "run", AgentWorkState.run_id.is_not(None),
        current["run_id"].astext == cast(AgentWorkState.run_id, String),
        func.jsonb_typeof(current["text"]) == "string",
    )


def goals(session, ctx, *, session_id=None, run_id=None):
    """Read only the current Human's ordinary readable Session scope, never person IDs."""
    from .session_views import _human, _sessions

    _human(session, ctx, None)
    query = goal_rows(_sessions(ctx, None))
    if session_id is not None:
        query = query.where(AgentWorkState.session_id == session_id)
    if run_id is not None:
        query = query.where(AgentWorkState.run_id == run_id)
    rows = session.execute(query.order_by(AgentWorkState.revision.desc())).mappings().all()
    return [dict(row) for row in rows]


def hidden_detail(goal):
    """No original status/clock/link is guessed from a work-state finish record."""
    return {
        "run_id": str(goal["run_id"]), "session_id": str(goal["session_id"]),
        "goal": goal["goal"], "status": "hidden", "history_hidden": True,
        "hidden_reason": "source_unavailable", "result": None,
        "hidden_message": "原回答所依据的资料已不可读，保留你的原话。",
        "recorded_at": goal["recorded_at"].isoformat(), "created_at": None,
        "product_id": str(goal["session_product_id"]) if goal["session_product_id"] else None,
        "project_id": str(goal["session_project_id"]) if goal["session_project_id"] else None,
        "proposal_id": None,
        "session_proposal_id": str(goal["session_proposal_id"])
        if goal["session_proposal_id"] else None,
        "conversation": {"previous_run_id": None, "next_run_id": None,
                         "links_unavailable": True},
        "error_code": None, "reconciliation": None, "process": None, "versions": {},
        "reverted": None, "reverted_at": None, "reverted_by": None,
        "revert_receipt_id": None, "cancel_epoch": None,
    }
