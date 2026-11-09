"""Memory candidates (P86 第 2、3、10 项): 小Pai proposes, the owner confirms.

The server admits a model's ``memory_candidates`` in the Run's finalize with
deterministic checks only (length, the Run's own range, the owner's own words,
how often proposals may be made) and stores them as candidates. A candidate is
not memory: nothing reaches a note until the owner clicks “记住”, which writes
the note as the owner. “忽略” voids it; it expires after 7 days.

The frozen prompt 1.0.0 defines no ``memory_candidates`` output, so this is an
output-contract change that needs a new prompt version and Prompt A/B (memory
design §4.1). Until a released version is listed in
``MEMORY_CANDIDATE_PROMPT_VERSIONS`` no model proposal is admitted at all.

Write gate (P84 第 7 项): an explicit proposal must quote the owner's latest
message verbatim (page material removed) and contain a fixed "remember"
expression; a proactive one (纠正两次以上) must quote at least two of the owner's
own earlier messages in this Session, at most once per Session, and only while
the owner and the administrator both allow proposals. Text from originals,
mail, IM or OCR can never trigger or fill a candidate.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select

from pdos_next.core.schema_base import StrictModel
from pdos_next.core.service import digest
from pdos_next.errors import DomainError

from .models import MemoryCandidate, MemoryCandidateDecision

MEMORY_CANDIDATE_PROMPT_VERSIONS = frozenset()  # No released prompt defines the output yet.
PER_RUN_LIMIT = 3
TTL = timedelta(days=7)
NOTE_INTENT = (
    "记住", "记一下", "记下来", "帮我记", "以后都", "以后一律", "以后请", "每次都", "别忘了",
    "我说的", "我说“", "我说\"", "我习惯", "我一般",
)
ACTIVE = ("queued", "running", "waiting_input")


class Decision(StrictModel):
    request_key: UUID
    decision: Literal["adopt", "ignore"]
    note: dict | None = None  # NoteDraft overrides, validated by notes.NoteDraft
    conflict: dict | None = None  # notes.ConflictChoice


def prompt_version(run):
    return ((run.versions or {}).get("prompt_identities", {}).get("main") or {}).get("version")


def run_scope(run):
    for kind in ("project", "proposal", "product", "category"):
        identity = getattr(run, f"{kind}_id", None)
        if identity is not None:
            return kind, identity
    return "global", None


def _reject(reason, **extra):
    return {"reason": reason, **extra}


def admit(session, run, proposals, goals, *, page_material):
    """Store admissible candidates for this Run's owner; return rejected reasons."""
    from pdos_next.agent.kernel.work_state import user_goal

    from . import notes, policy, settings
    from .mode import run_is_off

    if not proposals:
        return []
    if prompt_version(run) not in MEMORY_CANDIDATE_PROMPT_VERSIONS:
        return [_reject("memory_candidate_prompt_not_released")]
    if (run.trigger != "conversation" or (run.versions or {}).get("dingtalk")
            or run_is_off(session, run)):
        return [_reject("memory_candidate_channel_excluded")]
    tenant = policy.current(session)
    if not policy.notes_enabled(tenant):
        return [_reject("memory_notes_disabled")]
    from pdos_next.agent.kernel.models import AgentRun

    if session.scalar(select(AgentRun.state).where(AgentRun.id == run.id)) not in ACTIVE:
        return [_reject("memory_candidate_run_not_active")]
    if not isinstance(proposals, list) or len(proposals) > PER_RUN_LIMIT:
        return [_reject("invalid_memory_candidates")]
    own = {key: user_goal(value) for key, value in goals.items()}
    current = own.get(str(run.id), "")
    proactive_used = session.scalar(select(func.count()).select_from(MemoryCandidate).where(
        MemoryCandidate.session_id == run.session_id, MemoryCandidate.origin == "proactive"))
    proactive_allowed = (policy.proposals_enabled(tenant)
                         and not settings.proactive_off(session, run.requester_id))
    scope_kind, scope_id = run_scope(run)
    rejected, stored = [], 0
    for proposal in proposals:
        reason = _shape(proposal)
        if reason:
            rejected.append(_reject(reason))
            continue
        origin, kind = proposal["origin"], proposal["kind"]
        if origin == "explicit":
            trigger = proposal["trigger"]
            if not isinstance(trigger, str) or not trigger.strip() or trigger not in current:
                rejected.append(_reject("trigger_not_owner_words"))
                continue
            if not any(expression in trigger for expression in NOTE_INTENT):
                rejected.append(_reject("trigger_not_explicit_remember"))
                continue
            quotes = [{"run_id": str(run.id), "text": trigger}]
        else:
            if not proactive_allowed:
                rejected.append(_reject("proactive_proposals_off"))
                continue
            if proactive_used:
                rejected.append(_reject("proactive_once_per_session"))
                continue
            triggers = proposal["trigger"]
            if (not isinstance(triggers, list) or not 2 <= len(triggers) <= 5
                    or any(not isinstance(item, dict) or set(item) != {"run_id", "text"}
                           or not isinstance(item["text"], str) or not item["text"].strip()
                           or item["text"] not in own.get(str(item["run_id"]), "")
                           for item in triggers)
                    or len({str(item["run_id"]) for item in triggers}) < 2):
                rejected.append(_reject("trigger_not_owner_corrections"))
                continue
            quotes = [{"run_id": str(item["run_id"]), "text": item["text"]} for item in triggers]
        text = notes.clean(proposal["text"])
        if not 1 <= len(text) <= notes.TEXT_LIMIT:
            rejected.append(_reject("invalid_memory_candidate_text"))
            continue
        if any(len(material) >= 6 and (text in material or material in text)
               for material in page_material):
            rejected.append(_reject("text_from_untrusted_material"))
            continue
        alias_term = alias_canonical = None
        if kind == "alias":
            alias_term = notes.clean(proposal.get("alias_term"))
            alias_canonical = notes.clean(proposal.get("alias_canonical"))
            if (not 1 <= len(alias_term) <= notes.ALIAS_TERM_LIMIT
                    or not 1 <= len(alias_canonical) <= notes.CANONICAL_LIMIT
                    or not any(alias_term in quote["text"] for quote in quotes)):
                rejected.append(_reject("alias_not_owner_words"))
                continue
        scope = ("global", None) if proposal["scope"] == "global" else (scope_kind, scope_id)
        category_id = None
        if scope[0] != "global":
            found = notes.readable_object(session, scope[0], scope[1])
            if found is None:
                rejected.append(_reject("memory_candidate_scope_unreadable"))
                continue
            category_id = found[0]
        key = digest(["memory-candidate/v1", str(run.id), kind, text, scope[0], str(scope[1]),
                      alias_term, alias_canonical])
        if session.scalar(select(MemoryCandidate.id).where(MemoryCandidate.candidate_key == key)):
            continue
        values = {"kind": kind, "text": text, "scope_kind": scope[0], "scope_id": scope[1],
                  "category_id": category_id, "alias_term": alias_term,
                  "alias_canonical": alias_canonical, "target_kind": None, "target_id": None,
                  "target_version": None, "valid_until": None}
        similar = notes.similar(session, run.requester_id, values)
        now = datetime.now(UTC)
        # Core insert: the Run's terminal state is staged but must not be flushed
        # before finish completes (terminal Runs are immutable).
        session.execute(insert(MemoryCandidate).values(
            id=uuid4(), tenant_id=run.tenant_id, created_at=now, owner_id=run.requester_id,
            session_id=run.session_id, run_id=run.id, candidate_key=key, origin=origin,
            kind=kind, text=text, scope_kind=scope[0], scope_id=scope[1],
            category_id=category_id, alias_term=alias_term, alias_canonical=alias_canonical,
            conflicts=[{"note_id": str(row.note_id), "revision": row.revision}
                       for row, _reason in similar],
            trigger=quotes, prompt_version=prompt_version(run) or "", expires_at=now + TTL,
        ))
        stored += 1
        if origin == "proactive":
            proactive_used = 1
    return rejected


def _shape(proposal):
    keys = {"origin", "kind", "text", "scope", "trigger"}
    if not isinstance(proposal, dict) or not keys <= set(proposal) or set(proposal) - (
        keys | {"alias_term", "alias_canonical"}
    ):
        return "invalid_memory_candidate_shape"
    if proposal["origin"] not in {"explicit", "proactive"}:
        return "invalid_memory_candidate_origin"
    if proposal["kind"] not in {"convention", "background", "alias"}:
        return "invalid_memory_candidate_kind"
    if proposal["scope"] not in {"global", "run"}:
        return "invalid_memory_candidate_scope"
    if not isinstance(proposal["text"], str):
        return "invalid_memory_candidate_text"
    if (proposal["kind"] == "alias") != bool(proposal.get("alias_term")):
        return "invalid_memory_candidate_alias"
    return None


# ---------------------------------------------------------------------------
# The owner's view and decision.

def _decisions(session, ids):
    if not ids:
        return {}
    return {row.candidate_id: row for row in session.scalars(
        select(MemoryCandidateDecision).where(MemoryCandidateDecision.candidate_id.in_(ids)))}


def status(row, decision, now):
    if decision is not None:
        return decision.decision
    return "expired" if row.expires_at <= now else "pending"


def view(session, row, decision, *, now=None):
    from . import notes

    now = now or datetime.now(UTC)
    values = {"kind": row.kind, "text": row.text, "scope_kind": row.scope_kind,
              "scope_id": row.scope_id, "alias_term": row.alias_term,
              "alias_canonical": row.alias_canonical}
    current = status(row, decision, now)
    conflicts = (notes.conflict_views(session, notes.similar(session, row.owner_id, values))
                 if current == "pending" else [])
    scope = {"kind": row.scope_kind, "id": str(row.scope_id) if row.scope_id else None,
             "title": "全局", "readable": True}
    if row.scope_kind != "global":
        found = notes.readable_object(session, row.scope_kind, row.scope_id)
        scope.update(title=found[1] if found else None, readable=found is not None)
    return {
        "candidate_id": str(row.id),
        "run_id": str(row.run_id),
        "session_id": str(row.session_id),
        "origin": row.origin,
        "kind": row.kind,
        "kind_label": notes.KIND_LABELS[row.kind],
        "text": row.text,
        "scope": scope,
        "alias": {"term": row.alias_term, "means": {"kind": "term", "text": row.alias_canonical}}
        if row.kind == "alias" else None,
        "trigger": row.trigger,
        "status": current,
        "proposed_at": row.created_at.isoformat(),
        "expires_at": row.expires_at.isoformat(),
        "note_id": str(decision.note_id) if decision and decision.note_id else None,
        "conflicts": conflicts,
        "choices": ["merge", "replace", "keep_both"] if conflicts else [],
        "label": "小Pai 只是提议，你点“记住”后才会写入；忽略即作废，7 天后过期。",
    }


def pending(session, ctx):
    now = datetime.now(UTC)
    rows = session.scalars(select(MemoryCandidate).where(
        MemoryCandidate.owner_id == ctx.requester_id, MemoryCandidate.expires_at > now,
    ).order_by(MemoryCandidate.created_at.desc()).limit(50)).all()
    decided = _decisions(session, [row.id for row in rows])
    items = [view(session, row, None, now=now) for row in rows if row.id not in decided]
    return {"version": "memory-candidates/v1", "items": items, "count": len(items)}


def for_run(session, ctx, run):
    from pdos_next.agent.kernel.run_reconciliation import owner

    owner(session, ctx, run)
    rows = session.scalars(select(MemoryCandidate).where(MemoryCandidate.run_id == run.id)
                           .order_by(MemoryCandidate.created_at)).all()
    decided = _decisions(session, [row.id for row in rows])
    return {"version": "memory-candidates/v1", "run_id": str(run.id),
            "items": [view(session, row, decided.get(row.id)) for row in rows]}


def decide(session, ctx, candidate_id, data):
    from . import notes

    row = session.get(MemoryCandidate, candidate_id)
    if row is None or row.owner_id != ctx.requester_id:
        raise DomainError("NOT_FOUND", "这条提议不存在，或不属于你本人。", 404)
    fingerprint = digest({"candidate_id": candidate_id, "decision": data.decision,
                          "note": data.note, "conflict": data.conflict})
    replay = session.scalar(select(MemoryCandidateDecision).where(
        MemoryCandidateDecision.owner_id == ctx.requester_id,
        MemoryCandidateDecision.request_key == data.request_key))
    if replay is not None:
        if replay.request_sha256 != fingerprint:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "请求编号对应不同的记忆操作。")
        return view(session, row, replay)
    if _decisions(session, [row.id]):
        raise DomainError("VERSION_CONFLICT", "这条提议已经处理过。")
    if row.expires_at <= datetime.now(UTC):
        raise DomainError("VERSION_CONFLICT",
                          "这条提议已过期（7 天），可以在“我的记忆”里直接添加。")
    note_id = None
    if data.decision == "adopt":
        draft = {"kind": row.kind, "text": row.text,
                 "scope": {"kind": row.scope_kind, "id": str(row.scope_id) if row.scope_id
                           else None}}
        if row.kind == "alias":
            draft.update(alias_term=row.alias_term, alias_canonical=row.alias_canonical)
        draft.update(data.note or {})
        try:
            payload = notes.CreateNote(
                request_key=data.request_key, note=notes.NoteDraft.model_validate(draft),
                conflict=notes.ConflictChoice.model_validate(data.conflict)
                if data.conflict else None,
            )
        except ValueError as error:
            raise DomainError("VALIDATION_FAILED", "记忆内容不符合要求。", 422,
                              detail={"errors": str(error)[:500]}) from None
        created = notes.create(session, ctx, payload, origin="candidate", candidate_id=row.id)
        note_id = UUID(created["note"]["note_id"])
    decision = MemoryCandidateDecision(
        id=uuid4(), tenant_id=ctx.tenant_id, owner_id=ctx.requester_id, candidate_id=row.id,
        decision="adopted" if data.decision == "adopt" else "ignored", note_id=note_id,
        request_key=data.request_key, request_sha256=fingerprint,
    )
    session.add(decision)
    session.flush()
    return view(session, row, decision)
