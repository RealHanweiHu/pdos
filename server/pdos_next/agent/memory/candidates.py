"""Memory candidates (P86 第 2、3、10 项; P121 第 8、9 项): 小Pai proposes, the owner confirms.

The server admits a model's ``memory_candidates`` in the Run's finalize with
deterministic checks only (length, the Run's own range, the owner's own words,
how often proposals may be made) and stores them as candidates. A candidate is
not memory: nothing reaches a note until the owner clicks “记住”, which writes
the note as the owner. “忽略” voids it; it expires after 7 days.

The frozen prompt 1.0.0 defines no ``memory_candidates`` output, so this is an
output-contract change that needs a new prompt version and Prompt A/B (memory
design §4.1). Only Runs whose main prompt version is listed in
``MEMORY_CANDIDATE_PROMPT_VERSIONS`` can have a model proposal admitted.

Write gate (P84 第 7 项), all deterministic:

* explicit: the trigger is a verbatim part of the owner's latest message (page
  material removed) and holds a fixed 面向小Pai 今后行为的明确说法 (``triggers``);
  a 叫法 may instead hold the owner's naming sentence ("我说的 X 就是 Y").
* proactive (纠正两次以上): the trigger quotes the owner's own words from at least
  two different Runs of this Session, every quote holds a fixed correction
  expression and shares a word with the proposed text; at most once per Session,
  and only while the owner and the administrator both allow proposals.
* text from originals, mail, IM or OCR can never trigger or fill a candidate.
* "这只是讨论，不算决定": the Session's pending candidates become void and nothing
  the owner said up to that Run can be proposed again (``memory_proposal_voids``).
* forgetting: what the owner purged is not proposed again from old records
  (``suppression``); an explicit instruction given after the forgetting is.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select
from sqlalchemy.exc import DBAPIError

from pdos_next.core.schema_base import StrictModel
from pdos_next.core.service import digest
from pdos_next.errors import DomainError

from . import triggers
from .models import MemoryCandidate, MemoryCandidateDecision, MemoryProposalVoid

# Prompt versions whose output contract defines ``memory_candidates`` and that passed
# Prompt A/B. A version listed here opens the path only for Runs that use it: 1.1.0
# passed on 2026-11-14 (docs/reports/evidence/pdos-next-memory-proposal-20261113) and
# takes effect only once it is activated by a named reviewer; the active 1.0.0 stays closed.
MEMORY_CANDIDATE_PROMPT_VERSIONS = frozenset({"1.1.0"})
PER_RUN_LIMIT = 3
TTL = timedelta(days=7)
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


KIND = "memory_candidate"  # Marks this module's entries in the Run's rejected proposals.
DECLINED_NOTE = (
    "小Pai 这次提议的记忆卡片没有通过系统核对（例如引用的不是你这条消息里的原话），"
    "没有生成卡片，也没有记住任何内容。需要的话请再明确说一遍，或在“我的记忆”里直接添加。"
)


def _reject(reason, **extra):
    return {"reason": reason, "kind": KIND, **extra}


def declined(run):
    """How many proposals of this Run the server refused, for the owner's eyes.

    The model writes its answer before admission, so it may say a card was proposed
    when none was stored; the Run's own view says so plainly (no text is kept).
    """
    rejected = ((run.versions or {}).get("work_state_proposals") or {}).get("rejected", [])
    count = sum(1 for item in rejected if isinstance(item, dict) and item.get("kind") == KIND
                and item.get("reason") != "memory_candidate_prompt_not_released")
    return {"count": count, "note": DECLINED_NOTE} if count else None


def discussion_marked(run, goals):
    """The owner's own words in this Run say it was only discussion, not a decision."""
    from pdos_next.agent.kernel.work_state import user_goal

    return triggers.discussion(user_goal(goals.get(str(run.id), "")))


def _mark_discussion(session, run, goals):
    """Record the void for this Run; never lets a refused insert break the finish."""
    from pdos_next.agent.kernel.models import AgentRun, AgentSession

    from .mode import run_is_off

    if (run.trigger != "conversation" or (run.versions or {}).get("dingtalk")
            or run_is_off(session, run) or not discussion_marked(run, goals)):
        return False
    if session.scalar(select(MemoryProposalVoid.id).where(MemoryProposalVoid.run_id == run.id)):
        return True
    if (session.scalar(select(AgentRun.state).where(AgentRun.id == run.id)) not in ACTIVE
            or session.scalar(select(AgentSession.owner_id).where(
                AgentSession.id == run.session_id)) != run.requester_id):
        return False
    # A connection savepoint: the Run's staged terminal state must not be flushed here.
    connection = session.connection()
    savepoint = connection.begin_nested()
    try:
        connection.execute(insert(MemoryProposalVoid).values(
            id=uuid4(), tenant_id=run.tenant_id, created_at=datetime.now(UTC),
            owner_id=run.requester_id, session_id=run.session_id, run_id=run.id))
        savepoint.commit()
    except DBAPIError:
        savepoint.rollback()
        return False
    return True


def _voided_through(session, run, order):
    """Position (in the Session's Run order) up to which nothing may be proposed."""
    marked = session.scalars(select(MemoryProposalVoid.run_id).where(
        MemoryProposalVoid.session_id == run.session_id,
        MemoryProposalVoid.owner_id == run.requester_id)).all()
    return max((order[str(identity)] for identity in marked if str(identity) in order),
               default=-1)


def _corrections(triggers_value, own, text):
    """纠正两次以上: reason the quotes do not prove it, or None."""
    from . import notes

    if (not isinstance(triggers_value, list) or not 2 <= len(triggers_value) <= 5
            or any(not isinstance(item, dict) or set(item) != {"run_id", "text"}
                   or not isinstance(item["text"], str) or not item["text"].strip()
                   or item["text"] not in own.get(str(item["run_id"]), "")
                   for item in triggers_value)
            or len({str(item["run_id"]) for item in triggers_value}) < 2):
        return "trigger_not_owner_corrections"
    if not all(triggers.correction(item["text"]) for item in triggers_value):
        return "trigger_not_corrections"
    subject = notes.words(text)
    if not all(subject & notes.words(item["text"]) for item in triggers_value):
        return "corrections_not_same_matter"
    return None


def admit(session, run, proposals, goals, *, page_material):
    """Store admissible candidates for this Run's owner; return rejected reasons."""
    from pdos_next.agent.kernel.work_state import user_goal

    from . import notes, policy, settings, suppression
    from .mode import run_is_off

    # The owner's "这只是讨论" is a server fact from their own words: it is recorded
    # whether or not the model proposed anything and whatever the prompt version.
    _mark_discussion(session, run, goals)
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
    order = {key: position for position, key in enumerate(goals)}  # by creation time
    current = own.get(str(run.id), "")
    voided = _voided_through(session, run, order)
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
            if not (triggers.remember(current, trigger)
                    or kind == "alias" and triggers.alias(current, trigger)):
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
            reason = _corrections(proposal["trigger"], own, proposal["text"])
            if reason:
                rejected.append(_reject(reason))
                continue
            quotes = [{"run_id": str(item["run_id"]), "text": item["text"]}
                      for item in proposal["trigger"]]
        if any(order.get(quote["run_id"], -1) <= voided for quote in quotes):
            rejected.append(_reject("voided_as_discussion"))
            continue
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
        suppressed = suppression.blocked(
            session, run, origin=origin, values={"text": text, "alias_term": alias_term},
            quotes=quotes)
        if suppressed:
            rejected.append(_reject(suppressed))
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


def _voided(session, rows):
    """IDs of undecided candidates the owner later called only discussion."""
    sessions = {row.session_id for row in rows}
    if not sessions:
        return set()
    latest = dict(session.execute(
        select(MemoryProposalVoid.session_id, func.max(MemoryProposalVoid.created_at))
        .where(MemoryProposalVoid.session_id.in_(sessions))
        .group_by(MemoryProposalVoid.session_id)).all())
    return {row.id for row in rows
            if row.session_id in latest and latest[row.session_id] >= row.created_at}


def status(row, decision, now, *, voided=False):
    if decision is not None:
        return decision.decision
    if voided:
        return "voided"
    return "expired" if row.expires_at <= now else "pending"


def view(session, row, decision, *, now=None, voided=None):
    from . import notes

    now = now or datetime.now(UTC)
    if voided is None:
        voided = row.id in _voided(session, [row])
    values = {"kind": row.kind, "text": row.text, "scope_kind": row.scope_kind,
              "scope_id": row.scope_id, "alias_term": row.alias_term,
              "alias_canonical": row.alias_canonical}
    current = status(row, decision, now, voided=voided)
    conflicts = (notes.conflict_views(session, notes.similar(session, row.owner_id, values), values)
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
    voided = _voided(session, rows)
    items = [view(session, row, None, now=now, voided=False) for row in rows
             if row.id not in decided and row.id not in voided]
    return {"version": "memory-candidates/v1", "items": items, "count": len(items)}


def for_run(session, ctx, run):
    from pdos_next.agent.kernel.run_reconciliation import owner

    owner(session, ctx, run)
    rows = session.scalars(select(MemoryCandidate).where(MemoryCandidate.run_id == run.id)
                           .order_by(MemoryCandidate.created_at)).all()
    decided = _decisions(session, [row.id for row in rows])
    voided = _voided(session, rows)
    return {"version": "memory-candidates/v1", "run_id": str(run.id),
            "items": [view(session, row, decided.get(row.id), voided=row.id in voided)
                      for row in rows],
            "declined": declined(run)}


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
    if row.id in _voided(session, [row]):
        raise DomainError("VERSION_CONFLICT",
                          "你说过这只是讨论，这条提议已作废；需要的话可以重新交代，"
                          "或在“我的记忆”里直接添加。")
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
