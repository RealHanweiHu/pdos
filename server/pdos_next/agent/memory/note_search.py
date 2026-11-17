"""memory.search over the requester's own notes (kinds=["note"], P85 第 2 项, P86).

The person is the Run's requester; the range is the Run's own (global notes plus
notes on the Run's category, product, proposal or project; a personal Run reads
all of the owner's notes). Each card is rechecked now: replaced, expired, purged
or out-of-reach notes never come back. Deterministic word overlap only.

``as_of`` (P121 第 8 项) is a query condition, never a permission or range input:
it returns the version of each note that was in effect at the end of that day.
In effect is valid time (P121 第 6 项): the latest version whose 生效起点 had come
by then, still within its 有效期, so a back-filled older note answers for the
time it covered even though it was recorded later. A version revised before it
ever took effect never answers. The note must still be readable now (a purged
note has no versions left; a note whose range is no longer readable is dropped),
and a version that is no longer the current one is background only, marked with
what it is now. Notes not yet in effect are never returned.
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


def effective(rows, at):
    """The version of one note in effect at ``at`` by valid time, or None.

    ``rows`` are that note's versions. The latest revision whose start had come wins;
    a version revised before its own start never took effect. A ``replaced`` marker only
    records when the version before it ended: while that end is still ahead of ``at``,
    the version it closes is the one in effect (as it was before s0_0893).
    """
    chosen, previous = None, None
    ordered = sorted(rows, key=lambda row: row.revision)
    for index, row in enumerate(ordered):
        if row.valid_from >= at:
            continue
        if any(later.created_at <= row.valid_from for later in ordered[index + 1:]):
            continue
        chosen, previous = row, ordered[index - 1] if index else None
    if (chosen is not None and chosen.status == "replaced" and previous is not None
            and previous.revision == chosen.revision - 1
            and previous.valid_from == chosen.valid_from
            and (chosen.valid_until is None or chosen.valid_until > at)):
        return previous
    return chosen


def _versions_before(session, owner_id, cutoff):
    """For each of the owner's notes, the version in effect just before ``cutoff``."""
    from sqlalchemy import select

    from .models import MemoryNoteVersion

    by_note = {}
    for row in session.scalars(
        select(MemoryNoteVersion).where(MemoryNoteVersion.owner_id == owner_id)
    ):
        by_note.setdefault(row.note_id, []).append(row)
    return [row for row in (effective(rows, cutoff) for rows in by_note.values())
            if row is not None]


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
    as_of = getattr(data, "as_of", None)
    cutoff = datetime.combine(as_of + timedelta(days=1), time.min, UTC) if as_of else None
    historical = cutoff is not None and cutoff < now
    latest = {row.note_id: row for row in notes._latest_versions(session, run.requester_id)}
    rows = _versions_before(session, run.requester_id, cutoff) if historical else latest.values()
    found = []
    for row in rows:
        if not personal and not notes.in_range(row, run):
            continue
        if data.since and row.created_at < datetime.combine(data.since, time.min, UTC):
            continue
        if data.until and row.created_at >= datetime.combine(
            data.until + timedelta(days=1), time.min, UTC
        ):
            continue
        current = notes.state(session, row, now=cutoff if historical else now)
        if current not in {"active", "stale"}:
            continue
        today = notes.state(session, latest[row.note_id], now=now) if historical else current
        if today == "unavailable":
            continue  # Not readable now: as_of never widens what can be read.
        score = _score(query_words, query, row)
        if score <= 0:
            continue
        found.append((score, row, current, today))
    found.sort(key=lambda item: (-item[0], -item[1].created_at.timestamp(), str(item[1].note_id)))
    disputed = notes.conflicted(latest.values())
    cards = []
    for _score_value, row, current, today in found[:NOTE_PAGE]:
        scope = notes.scope_view(session, row)
        superseded = historical and (
            latest[row.note_id].revision != row.revision or today not in {"active", "stale"})
        card = {
            "kind": "note",
            "note_id": str(row.note_id),
            "revision": row.revision,
            "note_kind": row.kind,
            "kind_label": notes.KIND_LABELS[row.kind],
            "zone": "constraint" if row.kind in {"convention", "alias"} and current == "active"
            and not superseded and (row.kind == "alias" or str(row.note_id) not in disputed)
            else "background",
            "text": row.text,
            "scope": {"kind": scope["kind"], "title": scope["title"]},
            "confirmed_at": row.created_at.isoformat(),
            "state": current,
            # Unified item contract (§5.7): when it holds from, how far it is confirmed.
            "valid_from": row.valid_from.isoformat(),
            "confirmation_label": notes.CONFIRMATION_LABELS[row.confirmation],
        }
        if row.occurred_at is not None:
            card["occurred_at"] = row.occurred_at.isoformat()
        if row.kind == "alias":
            card["alias"] = {"term": row.alias_term, "means": notes.means(session, row)}
        if current == "stale":
            card["note"] = "引用的对象已有新版本，这条可能过期，只作背景"
        elif row.kind != "alias" and str(row.note_id) in disputed:
            card["note"] = "你把这条和另一条记忆标为冲突，只作背景"
        if historical:
            card["as_of"] = as_of.isoformat()
        if superseded:
            card["current"] = {"state": today, "revision": latest[row.note_id].revision}
            card["note"] = ("这是当时有效的版本，之后已修改、替换或过期，只作背景；"
                            "现在的状态见 current")
        cards.append(card)
    record_usage(run, notes=[{"note_id": item["note_id"], "revision": item["revision"],
                              "zone": "search"} for item in cards])
    return {"notes": cards, "notes_status": "completed",
            **({"notes_as_of": as_of.isoformat()} if as_of else {}),
            "notes_policy": "个人记忆条目是你本人确认的口径、背景和叫法，"
                            "不是业务事实，不能作为依据引用。"}
