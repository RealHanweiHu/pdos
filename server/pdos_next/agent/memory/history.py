"""conversation.history for the owner's other Sessions (P85 第 2 项, design §14.4).

The server checks the Session belongs to the Run's requester. Turns are shown
under P32: revoked sources hide the answer and keep the owner's words; changed
sources keep it with "资料已更新". A turn whose outbound class (private,
customer) is wider than this Run's binding is withheld. The page is a dated
memory record: its citations are never inherited as this Run's evidence.
"""

from sqlalchemy import select

from pdos_next.errors import DomainError

TERMINAL = ("completed", "partial", "failed", "cancelled")
ANSWER_CHARS = 8000


def _target_off(session, target):
    from .mode import latest

    current = latest(session, target.id)
    return bool(current and current.memory_off)


def other_session(store, scope, payload, readers):
    from pdos_next.agent.kernel.conversation import classify_turn
    from pdos_next.agent.kernel.conversation_acl import classify, manifests
    from pdos_next.agent.kernel.execution import scope_for_run
    from pdos_next.agent.kernel.models import AgentRun, AgentSession

    from .recall import FACT_POLICY, covered, record_usage, unavailable

    with store.transaction(scope, lock=True) as (session, run):
        blocked = unavailable(run, session)
        if blocked is not None:
            return {"session_id": str(payload.session_id), "memory_record": True,
                    "status": blocked[0], "message": blocked[1], "turns": [],
                    "next_before": None, "fact_policy": FACT_POLICY}
        target = session.scalar(select(AgentSession).where(AgentSession.id == payload.session_id))
        if target is None or target.owner_id != run.requester_id:
            raise DomainError("FORBIDDEN_SCOPE", "只能读取本人当前可读的会话。", 403)
        if _target_off(session, target):
            raise DomainError("FORBIDDEN_SCOPE", "该会话设为不进记忆，不能在其他会话里调取。", 403)
        rows = session.scalars(
            select(AgentRun).where(
                AgentRun.session_id == target.id,
                AgentRun.requester_id == run.requester_id,
                AgentRun.trigger == "conversation",
                AgentRun.state.in_(TERMINAL),
                AgentRun.reverted_at.is_(None),
            ).order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        ).all()
        rows = [row for row in rows if not (row.versions or {}).get("memory_mode", {}).get("off")]
        if payload.before is not None:
            ids = [row.id for row in rows]
            if payload.before not in ids:
                raise DomainError("FORBIDDEN_SCOPE", "历史游标不属于该会话。", 403)
            rows = rows[ids.index(payload.before) + 1:]
        selected = rows[: payload.page_size]
        sendable = [row for row in selected if covered(row, run)]
        access = manifests(session, sendable, consumer=run) if sendable else {}
        states = classify(session, access, consumer=run) if sendable else {}
        consumer = scope_for_run(run)
        turns = []
        for row in selected:
            if row not in sendable:
                turns.append({
                    "run_id": str(row.id), "goal": row.goal, "status": row.state,
                    "historical_outcome": None, "outcome_state": "hidden",
                    "note": "本次运行未绑定该轮的资料类别，回答未发送。", "sources": [],
                    "original_record": {"run_id": str(row.id), "session_id": str(row.session_id)},
                })
                continue
            classified = classify_turn(
                session, row, readers, consumer,
                include_research_rows=payload.include_research_rows,
                access=access, states=states,
            )
            outcome = classified["outcome"]
            if outcome is not None:
                outcome["truncated"] = len(outcome["summary"]) > ANSWER_CHARS
                outcome["summary"] = outcome["summary"][:ANSWER_CHARS]
            turns.append({
                "run_id": str(row.id),
                "goal": row.goal,
                "status": row.state,
                "historical_outcome": outcome,
                "outcome_state": classified["state"],
                "sources": [] if classified["state"] == "hidden" else row.read_sources,
                "original_record": {"run_id": str(row.id), "session_id": str(row.session_id)},
            })
        visible = {key: value for key, value in access.items() if states.get(key) != "hidden"}
        record_usage(run, sessions=[target.id], access=visible)
        return {
            "session_id": str(target.id),
            "memory_record": True,
            "status": "completed",
            "turns": turns,
            "next_before": str(selected[-1].id) if len(rows) > payload.page_size else None,
            "fact_policy": FACT_POLICY + "其他会话的回答只是当时的记录，其中的引用不能直接沿用。",
        }
