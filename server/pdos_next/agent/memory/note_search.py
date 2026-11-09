"""memory.search over the requester's own notes (kinds=["note"], P85 第 2 项, P86).

The person is the Run's requester; the range is the Run's own (global notes plus
notes on the Run's category, product, proposal or project; a personal Run reads
all of the owner's notes). Each card is rechecked now: replaced, expired, purged
or out-of-reach notes never come back. Deterministic word overlap only.
"""

from datetime import UTC, datetime, time, timedelta

NOTE_PAGE = 5


def _score(query_words, query_text, row):
    from .notes import clean, words

    haystack = " ".join(filter(None, (row.text, row.alias_term, row.alias_canonical)))
    shared = query_words & words(haystack)
    score = float(len(shared))
    folded = clean(query_text).casefold()
    if row.alias_term and row.alias_term.casefold() in folded:
        score += 2.0
    if folded and folded in haystack.casefold():
        score += 1.0
    return score


def search_notes(session, run, data, *, extra="", now=None):
    from . import notes, policy
    from .recall import record_usage

    now = now or datetime.now(UTC)
    if not policy.notes_enabled(policy.current(session)):
        return {"notes": [], "notes_status": "notes_disabled",
                "notes_message": "管理员已关闭自由文本记忆，本次没有查个人记忆条目。"}
    if data.narrow_to == "current_session":
        return {"notes": [], "notes_status": "not_session_bound",
                "notes_message": "个人记忆条目不属于某个会话；去掉 narrow_to 才会查条目。"}
    personal = all(getattr(run, f"{kind}_id", None) is None
                   for kind in ("category", "product", "proposal", "project"))
    query = f"{data.query} {extra}".strip()
    query_words = notes.words(query)
    found = []
    for row in notes._latest_versions(session, run.requester_id):
        if not personal and not notes.in_range(row, run):
            continue
        if data.since and row.created_at < datetime.combine(data.since, time.min, UTC):
            continue
        if data.until and row.created_at >= datetime.combine(
            data.until + timedelta(days=1), time.min, UTC
        ):
            continue
        current = notes.state(session, row, now=now)
        if current not in {"active", "stale"}:
            continue
        score = _score(query_words, query, row)
        if score <= 0:
            continue
        found.append((score, row, current))
    found.sort(key=lambda item: (-item[0], -item[1].created_at.timestamp(), str(item[1].note_id)))
    cards = []
    for _score_value, row, current in found[:NOTE_PAGE]:
        scope = notes.scope_view(session, row)
        card = {
            "kind": "note",
            "note_id": str(row.note_id),
            "revision": row.revision,
            "note_kind": row.kind,
            "kind_label": notes.KIND_LABELS[row.kind],
            "zone": "constraint" if row.kind in {"convention", "alias"} and current == "active"
            else "background",
            "text": row.text,
            "scope": {"kind": scope["kind"], "title": scope["title"]},
            "confirmed_at": row.created_at.isoformat(),
            "state": current,
        }
        if row.kind == "alias":
            card["alias"] = {"term": row.alias_term, "means": notes.means(session, row)}
        if current == "stale":
            card["note"] = "引用的对象已有新版本，这条可能过期，只作背景"
        cards.append(card)
    record_usage(run, notes=[{"note_id": item["note_id"], "revision": item["revision"],
                              "zone": "search"} for item in cards])
    return {"notes": cards, "notes_status": "completed",
            "notes_policy": "个人记忆条目是你本人确认的口径、背景和叫法，"
                            "不是业务事实，不能作为依据引用。"}
