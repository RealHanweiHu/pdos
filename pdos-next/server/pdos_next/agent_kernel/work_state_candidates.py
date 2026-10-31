"""Readonly metadata from real candidate views; stored refs never assert adoption."""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import or_, select, tuple_

from pdos_next.database import require_context
from pdos_next.domain.preproject.access import human
from pdos_next.errors import DomainError
from pdos_next.service import Context

from .execution import check_run_binding, scope_for_run
from .models import AgentEvent, AgentRun

KINDS = {
    "domain_candidate": "domain",
    "category_candidate": "category",
    "snapshot_candidate": "snapshot",
    "verification_candidate": "verification_preparation",
}
STATES = {"pending", "adopted", "cancelled", "unavailable"}


def _references(values):
    refs = []
    for value in values:
        try:
            ref = (UUID(value["event_id"]), UUID(value["run_id"]))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if ref not in refs:
            refs.append(ref)
    return refs


def _summary(event, run, native):
    """Whitelist metadata only; no command, payload, quote, title or source proof."""
    state = native.get("state", "unavailable")
    receipt = native.get("receipt")
    receipt_id = native.get("receipt_id") or (
        receipt.get("id") if isinstance(receipt, dict) else None
    )
    if receipt_id is not None:
        receipt_id = str(UUID(str(receipt_id)))
    if (event.body.get("kind") == "work_followup"
        and native.get("kind") != "work_followup"):
        state = "unavailable"
    if state not in STATES or state == "adopted" and receipt_id is None:
        state = "unavailable"
    return {
        "event_id": str(event.id), "run_id": str(run.id),
        "kind": KINDS[event.body["type"]],
        "operation": native.get("operation") if state != "unavailable" else None,
        "state": state, "receipt_id": receipt_id if state == "adopted" else None,
    }


def _category(session, ctx, run, event):
    from .category_adoption import read_metadata as adopted
    from .category_candidate import read_metadata as pending

    if (run.reverted_at or run.state == "cancelled"
            or event.body.get("cancel_epoch") != run.cancel_epoch):
        return {"operation": "category.create", "state": "cancelled"}
    return adopted(session, ctx, run, event) or pending(session, ctx, run, event)


def _project(session, ctx, consumer, refs):
    human(session, ctx)
    from .context_restart import candidate_refs

    carried = candidate_refs(session, consumer)
    rows = session.execute(
        select(AgentEvent, AgentRun).join(
            AgentRun, (AgentRun.tenant_id == AgentEvent.tenant_id)
            & (AgentRun.id == AgentEvent.run_id),
        ).where(
            AgentRun.tenant_id == ctx.tenant_id,
            AgentRun.requester_id == ctx.requester_id,
            or_(AgentRun.session_id == consumer.session_id,
                tuple_(AgentEvent.id, AgentEvent.run_id).in_(carried)),
            tuple_(AgentEvent.id, AgentEvent.run_id).in_(refs),
            AgentEvent.body["type"].astext.in_(KINDS),
        )
    ).all()
    actual = {(event.id, run.id): (event, run) for event, run in rows}
    groups = defaultdict(list)
    for ref in refs:
        if ref in actual:
            event, run = actual[ref]
            groups[run.id].append(event)
    native = {}
    from .domain_candidates import project_rows

    for run_id, events in groups.items():
        run = next(actual[ref][1] for ref in refs if ref in actual and ref[1] == run_id)
        owner = Context(
            ctx.tenant_id, ctx.requester_id, ctx.requester_id, category_id=run.category_id,
        )
        ordinary = [event for event in events if event.body["type"] != "category_candidate"]
        if ordinary:
            try:
                native.update((UUID(value["event_id"]), value)
                              for value in project_rows(session, owner, run, ordinary))
            except DomainError:
                pass
        for event in events:
            if event.body["type"] != "category_candidate":
                continue
            try:
                native[event.id] = _category(session, owner, run, event)
            except (DomainError, KeyError, TypeError, ValueError):
                pass
    return [
        _summary(*actual[ref], native.get(ref[0], {}))
        for ref in refs if ref in actual
    ], len(actual) != len(refs)


def project(session, ctx, consumer, values):
    """Only this actual owned Run can derive an ordinary requester READ snapshot."""
    refs = _references(values)
    if not refs or consumer is None:
        return [], bool(refs)
    require_context(session, ctx)
    actual = session.get(AgentRun, consumer.id)
    if (actual is None or actual.tenant_id != ctx.tenant_id
            or actual.requester_id != ctx.requester_id
            or actual.session_id != consumer.session_id or actual.category_id != ctx.category_id
            or actual.trigger != "conversation"):
        raise DomainError("FORBIDDEN_SCOPE", "候选不在当前本人会话范围。", 403)
    if ctx.actor_id == ctx.requester_id:
        return _project(session, ctx, actual, refs)
    if (ctx.actor_id != actual.writer_id or ctx.agent_run_id != actual.id
            or ctx.run_id is not None or ctx.category_id != actual.category_id
            or ctx.cancel_epoch != actual.cancel_epoch):
        raise DomainError("FORBIDDEN_SCOPE", "候选摘要未绑定当前实际本人运行。", 403)
    scope = scope_for_run(actual)
    check_run_binding(actual, scope, for_write=False)
    from pdos_next.enterprise_search.assistant_sources import human_snapshot

    with human_snapshot(session.get_bind(), scope) as reading:
        retained = reading.get(AgentRun, actual.id)
        check_run_binding(retained, scope, for_write=False)
        owner = Context(actual.tenant_id, actual.requester_id, actual.requester_id,
                        category_id=actual.category_id)
        return _project(reading, owner, retained, refs)
