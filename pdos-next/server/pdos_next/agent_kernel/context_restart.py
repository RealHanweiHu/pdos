"""Explicit budget recovery: fresh history, server-owned state and exact provenance.

This is not conversation continuation. Its old references remain a closed set
from one immutable work-state revision; arbitrary cross-session reads stay denied.
"""

from copy import deepcopy
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select

from pdos_next.errors import DomainError
from pdos_next.service import digest

from .models import AgentEvent, AgentRun
from .work_state_models import AgentWorkState

KEY = "work_state_restart"


def existing(session, run):
    return session.scalar(select(AgentRun).where(
        AgentRun.requester_id == run.requester_id,
        AgentRun.versions[KEY]["source_run_id"].astext == str(run.id),
    ).limit(1))


def origin_ids(body):
    result = {
        item["run_id"]
        for field in ("constraints", "focus_objects", "completed", "candidates", "citations",
                      "skills")
        for item in body.get(field, [])
    }
    result.update(body[field]["run_id"] for field in ("root_goal", "current_goal")
                  if body.get(field))
    return result


def validate_body(body, goals):
    """Retain exact human proof and tombstones, never manufacture a new quote."""
    from .work_state import user_goal, validate_constraints

    for field in ("root_goal", "current_goal"):
        item = body.get(field)
        if item and (item["run_id"] not in goals
                     or item["text"] != user_goal(goals[item["run_id"]])):
            raise DomainError("SOURCE_UNAVAILABLE", "原工作目标无法与本人原话核对。")
    constraints = body.get("constraints", [])
    accepted, rejected = [], []
    for item in constraints:
        valid, invalid = validate_constraints(
            [{"run_id": item["run_id"], "text": item["text"]}],
            goals, set(body.get("removed_constraints", [])),
        )
        accepted.extend(valid)
        rejected.extend(invalid)
    if rejected or accepted != constraints:
        raise DomainError("SOURCE_UNAVAILABLE", "原工作约束缺少本人逐字证明或已被删除。")
    return deepcopy(body)


def eligible(session, run):
    if run.reverted_at or run.state != "partial":
        return False
    frozen = run.versions.get("work_state", {})
    if (frozen.get("context_incomplete")
            and digest(frozen) == run.versions.get("work_state_digest")):
        return True
    return session.scalar(select(AgentEvent.id).where(
        AgentEvent.run_id == run.id,
        AgentEvent.body["type"].astext == "context_incomplete",
    ).limit(1)) is not None


@dataclass(frozen=True)
class Restart:
    parent: object
    state: object
    body: dict
    access: dict


def access_state(session, run, access):
    """A restored model note carries all prior READ restrictions, even unquoted ones."""
    if not access:
        return "current"
    from .conversation_acl import classify

    states = classify(session, access, consumer=run).values()
    return "hidden" if "hidden" in states else "updated" if "updated" in states else "current"


def prepare(session, ctx, data):
    """Run/state locks and current owner/source checks precede any new session."""
    from .conversation import lineage
    from .conversation import prepare as prepare_continuation
    from .conversation_acl import manifests
    from .run_reconciliation import owner
    from .work_state import _lock, _project, latest

    if (data.continue_from_run_id is not None or data.session_id is not None
            or data.product_id is not None or data.proposal_id is not None
            or data.project_id is not None or data.sources or data.search_preferences is not None
            or data.verification_action is not None or data.work_followup_action is not None
            or data.lookup_depth is not None or data.context_revision is None):
        raise DomainError("INVALID_PAYLOAD", "预算恢复只接收原运行、携带版本与新目标。", 422)
    parent = session.scalar(select(AgentRun).where(
        AgentRun.id == data.restart_from_run_id,
    ).with_for_update())
    owner(session, ctx, parent)
    if not eligible(session, parent):
        raise DomainError("VERSION_CONFLICT", "只有因上下文预算停止的本人工作可保留携带另开会话。")
    recovered = existing(session, parent)
    if recovered is not None:
        raise DomainError("VERSION_CONFLICT", "原工作已有恢复会话，请打开已保存的新会话。",
                          detail={"next_run_id": str(recovered.id)})
    _lock(session, ctx.tenant_id, parent.session_id)
    state = latest(session, parent.session_id)
    if (state is None or state.revision != data.context_revision
            or state.body.get("current_goal", {}).get("run_id") != str(parent.id)):
        raise DomainError("VERSION_CONFLICT", "本次携带已变化，请刷新后再恢复。")
    # Existing continuation checks bind the actual scope/selection/read sources.
    effective, parent = prepare_continuation(session, ctx, data.model_copy(update={
        "continue_from_run_id": parent.id, "restart_from_run_id": None,
    }))
    full_access = manifests(session, [parent], ancestors=[parent, *lineage(session, parent)])
    fields = {"version", "run_id", "dependencies", "citations", "mcp", "projects",
              "project_dependencies", "project_unavailable", "unavailable"}
    access = {identity: {key: value for key, value in manifest.items() if key in fields}
              for identity, manifest in full_access.items()}
    if access_state(session, parent, access) == "hidden":
        raise DomainError("SOURCE_UNAVAILABLE", "原工作读取的资料已不可用，请先核对本次携带。")
    projected = _project(session, ctx, state, current_run=parent)
    if projected["notes"]:
        raise DomainError("SOURCE_UNAVAILABLE", "原工作含当前不可读资料，请先核对本次携带。")
    ids = origin_ids(state.body)
    rows = session.scalars(select(AgentRun).where(
        AgentRun.id.in_([UUID(identity) for identity in ids]),
        AgentRun.requester_id == ctx.requester_id,
    )).all()
    allowed = {str(row.id) for row in rows if row.session_id == parent.session_id}
    allowed.update(origin_ids(carried_body(session, parent)))
    if {str(row.id) for row in rows} != ids or not ids <= allowed:
        raise DomainError("FORBIDDEN_SCOPE", "携带的原始证明不在当前本人工作范围。", 403)
    body = validate_body(state.body, {str(row.id): row.goal for row in rows})
    return effective.model_copy(update={"session_id": None, "continue_from_run_id": None}), \
        Restart(parent, state, body, access)


def install(session, run, restart):
    """One create transaction copies the latest state; no old messages/checkpoints."""
    from .work_state import _append, user_goal

    proof = {
        "version": 1, "source_run_id": str(restart.parent.id),
        "source_session_id": str(restart.parent.session_id),
        "source_state_id": str(restart.state.id), "source_revision": restart.state.revision,
        "source_sha256": digest(restart.body), "origin_run_ids": sorted(origin_ids(restart.body)),
    }
    body = deepcopy(restart.body)
    body["_restart_access"] = deepcopy(restart.access)
    body["current_goal"] = {"run_id": str(run.id), "text": user_goal(run.goal)}
    _append(session, run, body, origin="human",
            key=uuid5(NAMESPACE_URL, f"pdos-context-restart:{run.id}"),
            fingerprint=digest(proof), revision=1)
    selection = body.get("context_selection")
    run.versions = {**run.versions, KEY: proof,
                    "requested_search_preferences": body["search_preferences"],
                    "requested_context_selection": selection,
                    "requested_context_selection_digest": digest(selection),
                    "context_selection_start_revision": 1}


def carried_body(session, run):
    """Only a server-created root in this actual session may authorize old refs."""
    if KEY in run.versions:
        root = run
    elif run.continued_from_id is None:
        return {}  # Reusing a session ID never establishes a continuation lineage.
    else:
        ancestors = select(AgentRun.id, AgentRun.continued_from_id).where(
            AgentRun.id == run.continued_from_id, AgentRun.session_id == run.session_id,
        ).cte("restart_ancestors", recursive=True)
        ancestors = ancestors.union_all(select(AgentRun.id, AgentRun.continued_from_id).join(
            ancestors, AgentRun.id == ancestors.c.continued_from_id,
        ).where(AgentRun.session_id == run.session_id))
        root = session.scalar(select(AgentRun).where(
            AgentRun.id.in_(select(ancestors.c.id)), AgentRun.session_id == run.session_id,
            AgentRun.requester_id == run.requester_id, AgentRun.versions.op("?")(KEY),
        ).limit(1))
    if root is None:
        return {}
    proof = root.versions.get(KEY, {})
    if (root.session_id != run.session_id or root.requester_id != run.requester_id
            or root.tenant_id != run.tenant_id or root.continued_from_id is not None
            or getattr(root, "reverted_at", None)
            or proof.get("version") != 1):
        raise DomainError("SOURCE_UNAVAILABLE", "恢复携带缺少当前会话的服务器证明。")
    try:
        source = session.get(AgentWorkState, UUID(proof["source_state_id"]))
        if (source is None or source.tenant_id != run.tenant_id
                or source.owner_id != run.requester_id
                or str(source.session_id) != proof["source_session_id"]
                or source.session_id == run.session_id
                or source.revision != proof["source_revision"]
                or source.body["current_goal"]["run_id"] != proof["source_run_id"]
                or digest(source.body) != proof["source_sha256"]
                or sorted(origin_ids(source.body)) != proof["origin_run_ids"]):
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise DomainError("SOURCE_UNAVAILABLE", "恢复携带的原始版本无法核对。") from None
    return deepcopy(source.body)


def candidate_refs(session, run):
    return [(UUID(item["event_id"]), UUID(item["run_id"]))
            for item in carried_body(session, run).get("candidates", [])]


def citation_roots(session, run):
    """Resolve only original CIDs explicitly present in the copied server state."""
    from pdos_next.enterprise_search import assistant_ledger

    from .execution import scope_for_run

    refs = carried_body(session, run).get("citations", [])
    roots = {}
    for identity in dict.fromkeys(item["run_id"] for item in refs):
        origin = session.get(AgentRun, UUID(identity))
        if origin is None or origin.requester_id != run.requester_id or origin.reverted_at:
            continue  # Current ordinary access is checked again before any preview.
        issued = assistant_ledger.search_issued(session, scope_for_run(origin), archive=True)
        for ref in refs:
            if ref["run_id"] == identity and ref["citation_id"] in issued:
                roots[ref["citation_id"]] = (identity, issued[ref["citation_id"]])
    return roots


def recovery_view(session, run):
    from .work_state import latest

    if not eligible(session, run):
        return None
    row = latest(session, run.session_id)
    if row is None or row.body.get("current_goal", {}).get("run_id") != str(run.id):
        return None
    recovered = existing(session, run)
    return {"expected_revision": row.revision,
            "existing": {"run_id": str(recovered.id), "session_id": str(recovered.session_id)}
            if recovered is not None else None}
