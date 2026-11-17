"""memory.search over team scope notes (kinds=["scope_note"]; P85 第 2 项, P87).

The reader is the Run's requester; the range is the Run's own scope chain and
arguments cannot widen it. A personal Run has no business scope, so it finds
none. Every card is checked now under the reader's permissions: stopped,
withdrawn, expired, other-customer or out-of-reach notes never come back, and
nothing says they exist. Deterministic word overlap only; team notes are
business context, so a memory-off Session still searches them.
"""

from datetime import UTC, datetime, time, timedelta

PAGE = 5
POLICY = ("团队备忘是成员确认或小Pai 记录的约定、关注点、决策背景和观察，不是业务事实，"
          "不能作为依据引用；需要依据时回到业务对象和资料核实。")


def _score(query_words, query_text, row):
    from .notes import clean, words

    haystack = " ".join(filter(None, (row.statement, row.topic, row.stage,
                                      row.customer_identity)))
    score = float(len(query_words & words(haystack)))
    folded = clean(query_text).casefold()
    if folded and folded in haystack.casefold():
        score += 1.0
    return score + (0.25 if row.pinned and score > 0 else 0.0)


def search_scope_notes(session, run, data, *, extra="", now=None):
    """Result fields for the scope_note kind; never raises for an empty range."""
    from . import notes, scope_assemble
    from .recall import ACTIVE

    now = now or datetime.now(UTC)
    result = {"unavailable_kinds": [], "scope_notes": [], "scope_notes_policy": POLICY}
    blocked = scope_assemble.unavailable(run)
    if blocked is not None:
        return {**result, "scope_notes_status": blocked,
                "scope_notes_message": "个人范围的运行没有团队备忘；进入品类、提案或项目后再查。"
                if blocked == "personal_scope" else "这个入口首期不查团队备忘。"}
    if data.narrow_to == "current_session":
        return {**result, "scope_notes_status": "not_session_bound",
                "scope_notes_message": "团队备忘不属于某个会话；去掉 narrow_to 才会查备忘。"}
    query = f"{data.query} {extra}".strip()
    query_words = notes.words(query)
    found = []
    for row, labels, zone in scope_assemble.candidates(session, run, now=now):
        if data.since and row.created_at < datetime.combine(data.since, time.min, UTC):
            continue
        if data.until and row.created_at >= datetime.combine(
                data.until + timedelta(days=1), time.min, UTC):
            continue
        score = _score(query_words, query, row)
        if score > 0:
            found.append((score, row, labels, zone))
    found.sort(key=lambda item: (-item[0], -item[1].created_at.timestamp(),
                                 str(item[1].note_id)))
    cards = []
    for _value, row, labels, zone in found[:PAGE]:
        card = scope_assemble.entry(session, row, labels)
        cards.append({**card, "kind": "scope_note", "kind_label": card["kind"], "zone": zone,
                      "note_kind": row.kind, "confirmed_at": row.created_at.isoformat(),
                      "flags": labels})
    if cards and run.state in ACTIVE:
        scope_assemble._record(run, [{"note_id": card["note_id"], "revision": card["revision"],
                                      "zone": "search"} for card in cards])
    return {**result, "scope_notes": cards, "scope_notes_status": "completed"}
