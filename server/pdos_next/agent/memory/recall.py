"""Recall of the owner's own episodes: memory.search, the recent catalog, rechecks.

Design §14.4 and P85. The server binds the person to the Run's requester and the
range to the Run's scope; arguments can only narrow it. Every item is rechecked
against current permissions and its dependency manifest before it is returned,
and a revoked item is dropped without saying it existed. All ranking is
deterministic; there is no model or embedding call on this path.
"""

import math
import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import func, or_, select, text

from pdos_next.core.schema_base import StrictModel
from pdos_next.errors import DomainError

from .models import MemoryEpisode, MemoryEpisodeMark, MemoryIndexEntry

VERSION = "memory-search/v1"
RANKING = ("memory-rrf/v3;keyword-sat-1.2;own-words+answer-side+object-titles;k=60;half-life-30d;"
           "receipt+0.25;pin+0.25;corrected*0.5")
KEYWORD_POOL = 50
PENDING_SCAN = 200
RECHECK_LIMIT = 30
RRF_K = 60
HALF_LIFE_DAYS = 30
CATALOG_SIZE = 3
CATALOG_TOKENS = 300
GOAL_CHARS = 80
CATALOG_GOAL_CHARS = 40
ANSWER_EXCERPT_CHARS = 200
ANSWER_LABEL = "小Pai 当时的回答（摘录）：只是当时的记录，不是业务事实，不能作为依据引用"
ACTIVE = frozenset({"queued", "running", "waiting_input"})
USAGE_LIMIT = 50
FACT_POLICY = (
    "情景记录是你本人以往的工作记录（as_of 为当时时间），不是业务事实，不能作为回答依据引用。"
    "卡片里的 answer 是小Pai 当时回答的摘录，同样只是记录；"
    "要看完整回答，用 conversation.history 并传 session_id；涉及当前事实须重新读取业务对象。"
)
SEMANTIC_OFF = {
    "status": "not_enabled",
    "reason": "本人会话记录未启用向量化，本次只做了关键词检索。",
}


class MemorySearchInput(StrictModel):
    query: str = Field(min_length=1, max_length=200)
    kinds: list[Literal["episode", "note", "scope_note"]] = Field(
        default_factory=lambda: ["episode"], min_length=1, max_length=3,
    )
    since: date | None = None
    until: date | None = None
    # P121 第 8 项: a query condition only (what was recorded or in effect up to the end of
    # that day); the person, the range and every permission recheck stay as of now.
    as_of: date | None = None
    narrow_to: Literal["current_session"] | None = None
    offset: int = Field(default=0, ge=0, le=40)
    page_size: int = Field(default=5, ge=1, le=10)

    @model_validator(mode="after")
    def ordered(self):
        if len(set(self.kinds)) != len(self.kinds):
            raise ValueError("kinds 不能重复。")
        if self.since and self.until and self.since > self.until:
            raise ValueError("since 不能晚于 until。")
        return self


def first_sentence(value, limit=GOAL_CHARS):
    head = re.split(r"[。！？!?\n]", value.strip(), maxsplit=1)[0].strip() or value.strip()
    return head if len(head) <= limit else head[: limit - 1] + "…"


def scope_filter(run):
    """The Run's own range (RAG 设计 §7.1). Personal-global runs read all own episodes."""
    if getattr(run, "project_id", None) is not None:
        return "project", MemoryEpisode.project_id == run.project_id
    if run.proposal_id is not None:
        return "proposal", MemoryEpisode.proposal_id == run.proposal_id
    if run.product_id is not None:
        return "product", MemoryEpisode.product_id == run.product_id
    if run.category_id is not None:
        return "category", MemoryEpisode.category_id == run.category_id
    return "personal", None


def _archived(session, tenant_id, session_ids):
    return {
        identity for identity in session_ids
        if session.scalar(text("SELECT public.memory_session_archived(:t,:s)"),
                          {"t": tenant_id, "s": identity})
    }


def marks(session, episode_ids):
    """Latest pin/hide state and every correction, per episode."""
    if not episode_ids:
        return {}
    rows = session.scalars(
        select(MemoryEpisodeMark)
        .where(MemoryEpisodeMark.episode_id.in_(episode_ids))
        .order_by(MemoryEpisodeMark.created_at, MemoryEpisodeMark.id)
    ).all()
    state = {}
    for row in rows:
        value = state.setdefault(row.episode_id, {"pinned": False, "hidden": False,
                                                  "corrections": []})
        if row.kind in {"pin", "unpin"}:
            value["pinned"] = row.kind == "pin"
        elif row.kind in {"hide", "unhide"}:
            value["hidden"] = row.kind == "hide"
        elif row.kind == "correction":
            value["corrections"].append({
                "recorded_at": row.created_at.isoformat(),
                "categories": list(row.body.get("categories", [])),
                "destination": row.body.get("destination"),
                "comment": row.body.get("comment", "")[:200],
            })
    return state


def keyword_score(parsed, counts, codes):
    score = 0.0
    for term in parsed["terms"]:
        tf = counts.get(term, 0)
        if tf:
            score += tf / (tf + 1.2)
    score += sum(1.0 for code in parsed["codes"] if code in set(codes))
    return score


def _base(run, data):
    base = [MemoryEpisode.owner_id == run.requester_id, MemoryEpisode.run_id != run.id]
    _kind, condition = scope_filter(run)
    if condition is not None:
        base.append(condition)
    if data.narrow_to == "current_session":
        base.append(MemoryEpisode.session_id == run.session_id)
    if data.since:
        base.append(MemoryEpisode.created_at >= datetime.combine(data.since, time.min, UTC))
    if data.until:
        base.append(MemoryEpisode.created_at
                    < datetime.combine(data.until + timedelta(days=1), time.min, UTC))
    if data.as_of:
        base.append(MemoryEpisode.created_at
                    < datetime.combine(data.as_of + timedelta(days=1), time.min, UTC))
    return base


def _merged(found, episode, kind, counts, codes):
    entry = found.setdefault(episode.id, {"episode": episode, "counts": {}, "codes": set(),
                                          "matched": []})
    for term, count in counts.items():
        entry["counts"][term] = entry["counts"].get(term, 0) + count
    entry["codes"].update(codes)
    return entry


def _candidates(session, run, data, parsed, *, extra):
    """Keyword candidates over every index row of each episode (own words, answer, objects).

    Returns (ranked, pending count, {episode id: which side matched}).
    """
    from pdos_next.agent.enterprise_search.tokenizer import analyze, or_query, version

    from .index import KINDS, texts_for

    tokenizer = version()
    base = _base(run, data)
    base.extend(extra)
    found = {}
    if parsed["terms"] or parsed["codes"]:
        matches = []
        if parsed["terms"]:
            matches.append(MemoryIndexEntry.terms.op("@@")(
                func.to_tsquery("simple", or_query(parsed["terms"]))))
        if parsed["codes"]:
            matches.append(MemoryIndexEntry.codes.overlap(parsed["codes"]))
        rows = session.execute(
            select(MemoryEpisode, MemoryIndexEntry.source_kind, MemoryIndexEntry.term_counts,
                   MemoryIndexEntry.codes)
            .join(MemoryIndexEntry, MemoryIndexEntry.episode_id == MemoryEpisode.id)
            .where(*base, MemoryIndexEntry.tokenizer_version == tokenizer,
                   MemoryIndexEntry.profile_version == "none",
                   MemoryIndexEntry.source_kind.in_(KINDS), or_(*matches))
            .order_by(MemoryEpisode.created_at.desc(), MemoryEpisode.id)
            .limit(KEYWORD_POOL * 4 * len(KINDS))
        ).all()
        # A row that did not match holds none of the query's words, so merging the
        # matched rows scores the same as merging both.
        for episode, kind, counts, codes in rows:
            _merged(found, episode, kind, counts, codes)["matched"].append(kind)
    # Index lag must never look like "nothing found": episodes in range without every
    # row are scored here with the same tokenizer (the 伪零结果 gate for M1). All rows
    # of an episode are written in one transaction, so the newest kind stands for all.
    indexed = select(MemoryIndexEntry.episode_id).where(
        MemoryIndexEntry.episode_id == MemoryEpisode.id,
        MemoryIndexEntry.tokenizer_version == tokenizer,
        MemoryIndexEntry.source_kind == KINDS[-1],
    ).exists()
    pending = session.scalars(
        select(MemoryEpisode).where(*base, ~indexed)
        .order_by(MemoryEpisode.created_at.desc(), MemoryEpisode.id).limit(PENDING_SCAN)
    ).all()
    texts = texts_for(session, pending)
    for episode in pending:
        found.pop(episode.id, None)
        for kind in KINDS:
            words = analyze(texts[episode.id][kind])
            entry = _merged(found, episode, kind, words["counts"], words["codes"])
            if keyword_score(parsed, words["counts"], words["codes"]) > 0:
                entry["matched"].append(kind)
    scored = [(entry["episode"], keyword_score(parsed, entry["counts"], sorted(entry["codes"])))
              for entry in found.values()]
    ranked = sorted(((episode, score) for episode, score in scored if score > 0),
                    key=lambda item: (-item[1], -item[0].created_at.timestamp(),
                                      str(item[0].id)))[:KEYWORD_POOL]
    matched = {identity: sorted(set(entry["matched"])) for identity, entry in found.items()}
    return ranked, len(pending), matched


def _fuse(session, ranked, vector_ids):
    """RRF over the keyword and vector rankings (same k as enterprise search)."""
    scores, rows = {}, {}
    for rank, (episode, _score) in enumerate(ranked, start=1):
        scores[episode.id] = scores.get(episode.id, 0.0) + 1 / (RRF_K + rank)
        rows[episode.id] = episode
    missing = [identity for identity in vector_ids if identity not in rows]
    if missing:
        rows.update({row.id: row for row in session.scalars(
            select(MemoryEpisode).where(MemoryEpisode.id.in_(missing)))})
    for rank, identity in enumerate(vector_ids, start=1):
        if identity in rows:
            scores[identity] = scores.get(identity, 0.0) + 1 / (RRF_K + rank)
    return [(rows[identity], value) for identity, value in sorted(
        scores.items(), key=lambda item: (-item[1], -rows[item[0]].created_at.timestamp(),
                                          str(item[0])))]


def _final_order(ranked, state, now, *, fused=False):
    values = []
    for rank, (episode, score) in enumerate(ranked, start=1):
        age = max((now - episode.created_at).total_seconds() / 86400, 0)
        base = score if fused else 1 / (RRF_K + rank)
        value = base * math.pow(0.5, age / HALF_LIFE_DAYS)
        mark = state.get(episode.id, {})
        value *= 1 + 0.25 * bool(episode.body.get("receipts")) + 0.25 * bool(mark.get("pinned"))
        if mark.get("corrections"):
            value *= 0.5
        values.append((value, episode))
    return [episode for _value, episode in sorted(
        values, key=lambda item: (-item[0], -item[1].created_at.timestamp(), str(item[1].id)))]


def covered(origin, run):
    """A recalled record never imports a wider private/customer outbound class."""
    return not (
        (origin.private_context and not run.private_context)
        or set(origin.data_categories) - set(run.data_categories)
        or set(origin.customer_identities) - set(run.customer_identities)
    )


def _scope_title(session, ctx, episode):
    from pdos_next.core.models import Category, Product
    from pdos_next.domain.categories.preproject.models import Proposal
    from pdos_next.domain.projects.models import Project

    for kind, model, column in (("project", Project, "name"), ("proposal", Proposal, "title"),
                                ("product", Product, "name"), ("category", Category, "name")):
        identity = getattr(episode, f"{kind}_id")
        if identity is not None:
            title = session.scalar(select(getattr(model, column)).where(model.id == identity))
            if title is None:
                raise DomainError("FORBIDDEN_SCOPE", "情景范围已不可读。")
            return {"kind": kind, "id": str(identity), "title": title}
    return {"kind": "personal", "id": None, "title": "个人"}


def recheck(session, run, episodes, *, limit):
    """Drop anything not readable now; return (cards input, access manifests)."""
    from pdos_next.agent.kernel.conversation_acl import classify, manifests
    from pdos_next.agent.kernel.models import AgentRun
    from pdos_next.core.models import Receipt

    if not episodes:
        return [], {}
    archived = _archived(session, run.tenant_id, {episode.session_id for episode in episodes})
    origins = {row.id: row for row in session.scalars(
        select(AgentRun).where(AgentRun.id.in_([episode.run_id for episode in episodes]))
    ).all()}
    kept = [episode for episode in episodes
            if episode.session_id not in archived
            and episode.run_id in origins
            and not origins[episode.run_id].reverted_at
            and covered(origins[episode.run_id], run)][: limit * 3]
    if not kept:
        return [], {}
    access = manifests(session, [origins[episode.run_id] for episode in kept], consumer=run)
    states = classify(session, access, consumer=run)
    ctx = None
    result = []
    for episode in kept:
        state = states.get(str(episode.run_id), "hidden")
        if state == "hidden":
            continue
        try:
            scope = _scope_title(session, ctx, episode)
        except DomainError:
            continue
        receipts = [UUID(item["receipt_id"]) for item in episode.body.get("receipts", [])]
        readable = set(session.scalars(select(Receipt.id).where(Receipt.id.in_(receipts))).all()
                       ) if receipts else set()
        result.append((episode, state, scope, [
            item for item in episode.body.get("receipts", [])
            if UUID(item["receipt_id"]) in readable
        ]))
        if len(result) >= limit:
            break
    kept_access = {str(item[0].run_id): access[str(item[0].run_id)] for item in result}
    return result, kept_access


# What a hit matched: the owner's own words, 小Pai's answer side, or the title of a
# specific object the Run focused on (the title itself is not returned).
SIDES = {"episode": "own_words", "answer": "answer", "object": "object_title"}


def card(episode, state, scope, receipts, mark, run, *, answer=None, matched=()):
    value = {
        "run_id": str(episode.run_id),
        "session_id": str(episode.session_id),
        "as_of": episode.created_at.isoformat(),
        "scope": scope,
        "goal": first_sentence(episode.goal),
        "status": episode.status,
        "receipts": [{"operation": item["operation"]} for item in receipts],
        "candidate_count": len(episode.body.get("candidates", [])),
        "skills": [item["key"] for item in episode.body.get("skills", [])],
        "same_session": episode.session_id == run.session_id,
        "pinned": bool(mark.get("pinned")),
        "corrections": mark.get("corrections", []),
    }
    if matched:
        value["matched_in"] = [SIDES[kind] for kind in matched]
    if answer:
        value["answer"] = {
            "label": ANSWER_LABEL,
            "excerpt": answer[:ANSWER_EXCERPT_CHARS],
            "truncated": len(answer) > ANSWER_EXCERPT_CHARS,
        }
    if state == "updated":
        value["note"] = "当时读过的资料已更新，涉及事实须重新读取"
    if mark.get("corrections"):
        value["note"] = "这次工作被你纠正过，排序已降低；纠正内容见 corrections"
    return value


def record_usage(run, *, episodes=(), sessions=(), access=None, retrieval=None, catalog=None,
                 notes=()):
    """Server-fact usage list for "用到了 N 条记忆", the episode record and rechecks."""
    if run.state not in ACTIVE:
        return
    usage = dict(run.versions.get("memory_usage") or {})
    for key, values in (("episodes", episodes), ("sessions", sessions)):
        merged = list(usage.get(key, []))
        merged.extend(value for value in map(str, values) if value not in merged)
        usage[key] = merged[:USAGE_LIMIT]
    if notes:
        merged = list(usage.get("notes", []))
        seen = {item["note_id"] for item in merged}
        merged.extend({"note_id": str(item["note_id"]), "revision": item["revision"],
                       "zone": item.get("zone", "search")}
                      for item in notes if str(item["note_id"]) not in seen)
        usage["notes"] = merged[:USAGE_LIMIT]
    if access:
        usage["access"] = {**usage.get("access", {}), **access}
    if retrieval is not None:
        usage["retrieval"] = retrieval
    if catalog is not None:
        usage["catalog"] = [str(value) for value in catalog]
    run.versions = {**run.versions, "memory_usage": usage}


def unavailable(run, session):
    """Reasons this Run reads no personal memory at all (P85 第 5、8 项)."""
    from .mode import run_is_off

    if run.trigger != "conversation":
        return "not_conversation", "自动化运行不读个人记忆。"
    if (run.versions or {}).get("dingtalk"):
        return "channel_excluded", "钉钉入口首期不读个人记忆。"
    if run_is_off(session, run):
        if run.state in ACTIVE and not (run.versions or {}).get("memory_mode", {}).get("off"):
            # Freeze "off" for the rest of this Run, so turning memory back on
            # mid-run cannot record it.
            run.versions = {**run.versions, "memory_mode": {"off": True}}
        return "memory_off", "本会话已设为不进记忆，未读取个人记忆。"
    return None


def search(session, run, data, *, now=None, semantic=None):
    from pdos_next.agent.enterprise_search.tokenizer import analyze_query

    from .assemble import frozen_aliases
    from .notes import alias_expansions

    now = now or datetime.now(UTC)
    kind, _condition = scope_filter(run)
    response = {
        "version": VERSION,
        "scope": {"kind": kind, "narrowed_to": data.narrow_to},
        "items": [],
        "returned": 0,
        "next_offset": None,
        "unavailable_kinds": [value for value in data.kinds if value == "scope_note"],
        "retrieval": {"channels": ["keyword"], "semantic": SEMANTIC_OFF,
                      "ranking_version": RANKING, "index_pending": 0},
        "fact_policy": FACT_POLICY,
    }
    if response["unavailable_kinds"]:
        from .scope_note_search import search_scope_notes

        response.update(search_scope_notes(session, run, data, now=now))
    blocked = unavailable(run, session)
    if blocked is not None:
        response.update(status=blocked[0], message=blocked[1])
        return response
    # P86 第 5 项: the owner's own aliases expand only the owner's own search.
    extra, applied = alias_expansions(session, run, data.query, frozen_aliases(session, run))
    if applied:
        response["retrieval"]["alias_expansion"] = applied
    if "note" in data.kinds:
        from .note_search import search_notes

        response.update(search_notes(session, run, data, extra=extra, now=now))
    if "episode" not in data.kinds:
        response["status"] = "completed"
        return response
    parsed = analyze_query(f"{data.query} {extra}".strip())
    ranked, pending, matched = _candidates(session, run, data, parsed, extra=[])
    fused = False
    if semantic is not None:
        # P85 第 3 项: vectors only when “本人会话记录” is selected; otherwise, or when
        # the query embedding failed, the result says 仅关键词 instead of looking empty.
        from .vectors import nearest

        if semantic.get("status") == "ready":
            vector_ids = nearest(session, run, semantic["vector"],
                                 semantic["profile_version_id"], _base(run, data))
            ranked, fused = _fuse(session, ranked, vector_ids), True
            response["retrieval"]["channels"] = ["keyword", "vector"]
            response["retrieval"]["semantic"] = {
                "status": "queried", "profile_version_id": str(semantic["profile_version_id"]),
                # Partial: the space is still catching up; keyword results cover the rest.
                **{key: semantic[key] for key in ("coverage", "vector_pending", "switching")
                   if key in semantic}}
        else:
            response["retrieval"]["semantic"] = {
                "status": "unavailable", "reason": semantic.get("status"),
                "message": "本次只做了关键词检索（向量检索不可用）。"}
    state = marks(session, [episode.id for episode, _score in ranked])
    ranked = [(episode, score) for episode, score in ranked
              if not state.get(episode.id, {}).get("hidden")]
    ordered = _final_order(ranked, state, now, fused=fused)
    window = ordered[data.offset:]
    kept, access = recheck(session, run, window[:RECHECK_LIMIT], limit=data.page_size)
    # Only records that passed the recheck above (covered, sources still readable).
    from .index import summaries

    answers = summaries(session, [item[0] for item in kept])
    response["items"] = [card(episode, item_state, scope, receipts, state.get(episode.id, {}), run,
                              answer=answers.get(episode.run_id),
                              matched=matched.get(episode.id, ()))
                         for episode, item_state, scope, receipts in kept]
    response["returned"] = len(response["items"])
    response["retrieval"]["index_pending"] = pending
    if len(window) > data.page_size and data.offset + data.page_size <= 40:
        response["next_offset"] = data.offset + data.page_size
    response["status"] = "completed"
    record_usage(run, episodes=[item["run_id"] for item in response["items"]], access=access,
                 retrieval={"channels": response["retrieval"]["channels"],
                            "semantic": response["retrieval"]["semantic"]["status"],
                            "index_pending": pending})
    return response


def catalog(session, run):
    """Up to 3 one-line entries from the same scope, other Sessions only; SQL only (§6.2)."""
    from pdos_next.agent.kernel.context_budget import estimate_tokens

    kind, condition = scope_filter(run)
    if kind == "personal" or condition is None or unavailable(run, session) is not None:
        return None
    rows = session.scalars(
        select(MemoryEpisode)
        .where(MemoryEpisode.owner_id == run.requester_id, condition,
               MemoryEpisode.session_id != run.session_id)
        .order_by(MemoryEpisode.created_at.desc(), MemoryEpisode.id).limit(CATALOG_SIZE * 4)
    ).all()
    state = marks(session, [row.id for row in rows])
    rows = [row for row in rows if not state.get(row.id, {}).get("hidden")]
    kept, access = recheck(session, run, rows, limit=CATALOG_SIZE)
    if not kept:
        return None
    value = {
        "zone": "background",
        "label": "历史（as_of）：你本人在当前范围最近几次工作的目录，"
                 "不是业务事实，不能作为依据引用。",
        "how_to_use": "需要细节时用 memory.search 或 conversation.history(session_id=…)。",
        "recent_episodes": [
            {"run_id": str(episode.run_id), "session_id": str(episode.session_id),
             "as_of": episode.created_at.date().isoformat(),
             "goal": first_sentence(episode.goal, CATALOG_GOAL_CHARS)}
            for episode, _state, _scope, _receipts in kept
        ],
    }
    import json

    while value["recent_episodes"] and estimate_tokens(
        json.dumps(value, ensure_ascii=False)
    ) > CATALOG_TOKENS:
        value["recent_episodes"].pop()
    if not value["recent_episodes"]:
        return None
    record_usage(run, episodes=[item["run_id"] for item in value["recent_episodes"]],
                 access={key: access[key] for key in access
                         if key in {item["run_id"] for item in value["recent_episodes"]}},
                 catalog=[item["run_id"] for item in value["recent_episodes"]])
    return value


def recheck_frozen(session, run):
    """Before each model call: stop sending recalled records whose sources were revoked."""
    from pdos_next.agent.kernel.conversation_acl import classify

    access = (run.versions.get("memory_usage") or {}).get("access") or {}
    if not access:
        return
    hidden = sorted(identity for identity, state in classify(session, access, consumer=run).items()
                    if state == "hidden")
    if hidden:
        raise DomainError(
            "CONVERSATION_HISTORY_REVOKED", "调取过的以往工作记录引用的资料已无权读取或已撤回。",
            detail={"run_ids": hidden},
        )


def matching_runs(q):
    """Episode Run IDs whose owner's own words contain every query word (list search).

    Used inside the owner's already RLS-filtered Session list, with the same
    tokenizer as memory.search, so "气泵 供应商" also finds "比较三家气泵供应商".
    """
    from pdos_next.agent.enterprise_search.tokenizer import analyze_query, version

    parsed = analyze_query(q)
    terms = [term for term in parsed["terms"] if re.fullmatch(r"\w+", term, flags=re.UNICODE)]
    if not terms and not parsed["codes"]:
        return None
    matches = []
    if terms:
        matches.append(MemoryIndexEntry.terms.op("@@")(
            func.to_tsquery("simple", " & ".join("'" + term + "'" for term in terms))))
    if parsed["codes"]:
        matches.append(MemoryIndexEntry.codes.overlap(parsed["codes"]))
    return (
        select(MemoryEpisode.run_id)
        .join(MemoryIndexEntry, MemoryIndexEntry.episode_id == MemoryEpisode.id)
        # Own words only: the answer rows stay out of the list search (see index.py).
        .where(MemoryIndexEntry.tokenizer_version == version(),
               MemoryIndexEntry.source_kind == "episode", or_(*matches))
    )


CONTEXT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["zone", "label", "how_to_use", "recent_episodes"],
    "properties": {
        "zone": {"const": "background"},
        "label": {"type": "string"},
        "how_to_use": {"type": "string"},
        "recent_episodes": {
            "type": "array",
            "maxItems": CATALOG_SIZE,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["run_id", "session_id", "as_of", "goal"],
                "properties": {
                    "run_id": {"type": "string"},
                    "session_id": {"type": "string"},
                    "as_of": {"type": "string"},
                    "goal": {"type": "string"},
                },
            },
        },
    },
}


def frozen_catalog(session, run):
    """The catalog a Run used is fixed at its first assembly, including after skill.load."""
    if "memory_context" in run.versions:
        return run.versions["memory_context"]
    value = catalog(session, run)
    if run.state in ACTIVE:
        run.versions = {**run.versions, "memory_context": value}
    return value
