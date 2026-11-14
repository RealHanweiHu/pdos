"""Resident personal notes in the Run envelope (P86 第 6 项, design §8, §14.3).

At the Run's first context assembly the server takes the requester's usable
notes for this range (global notes plus notes on the Run's own category,
product, proposal or project), splits them into the constraint zone (口径 and
叫法) and the background zone (背景, and anything marked 可能过期), and fixes the
selection for the Run. Nothing goes into the fixed prefix (不可协商项 4); no
model or embedding call is made; at most 1,000 tokens. Neither zone can be cited.

The Run row keeps which notes and revisions were chosen and where they go, never
their words (D481): the words are read from the note versions each time, so a
deleted note leaves nothing behind on the Run.
"""

import json

from sqlalchemy import select

from pdos_next.errors import DomainError

from .models import MemoryNoteDeletion, MemoryNoteVersion

KEY = "memory_notes_context"
ALIASES = "memory_aliases"
NOTES_TOKENS = 1000
LABEL = ("本人记忆：你本人确认过的口径、背景和叫法。不是业务事实，不能作为依据引用；"
         "与业务数据冲突时以业务数据为准，可以提示本人更新这条记忆。")
HOW_TO_USE = ("constraints 只约束表达方式和做法；aliases 是本人的叫法，写检索词时换成标准词；"
              "background 只作背景，需要依据时回到资料核实。"
              "还有未带入的条目时用 memory.search 查 kinds=[\"note\"]。")


def _scope(session, row):
    from .notes import scope_view

    value = scope_view(session, row)
    return {"kind": value["kind"], "title": value["title"]}


def build(session, run):
    """The envelope value and alias entries for this Run, or (None, [])."""
    from pdos_next.agent.kernel.context_budget import estimate_tokens

    from . import notes, policy
    from .recall import unavailable

    if unavailable(run, session) is not None or not policy.notes_enabled(policy.current(session)):
        return None, []
    rows = notes.usable(session, run)
    if not rows:
        return None, []
    rows.sort(key=lambda item: (item[0].scope_kind == "global", -item[0].created_at.timestamp(),
                                str(item[0].note_id)))
    value = {"zone_policy": {"constraints": "constraint", "aliases": "constraint",
                             "background": "background"},
             "label": LABEL, "constraints": [], "aliases": [], "background": [],
             "omitted": 0, "how_to_use": HOW_TO_USE}
    aliases = {item["note_id"]: item for item in notes.alias_entries(session, rows)}
    used = []
    for row, current in rows:
        entry = {"note_id": str(row.note_id), "revision": row.revision, "text": row.text,
                 "scope": _scope(session, row)}
        if row.kind == "alias":
            alias = aliases.get(str(row.note_id))
            if alias is None:
                continue
            entry.update(term=row.alias_term, means=alias["means"]["text"])
            zone = "aliases"
        elif row.kind == "convention" and current == "active":
            zone = "constraints"
        else:
            zone = "background"
        if current == "stale":
            entry["note"] = "引用的对象已有新版本，这条可能过期，只作背景"
        value[zone].append(entry)
        if estimate_tokens(json.dumps(value, ensure_ascii=False)) > NOTES_TOKENS:
            value[zone].pop()
            value["omitted"] += 1
            continue
        used.append({"note_id": str(row.note_id), "revision": row.revision, "zone": zone,
                     "scope": "global" if row.scope_kind == "global" else "scope"})
    if not used:
        return None, []
    entries = [alias for alias in aliases.values()
               if any(item["note_id"] == alias["note_id"] for item in used)]
    value["used"] = used
    return value, entries


BODY_KEYS = ("text", "term", "means")


def _versions(session, entries):
    keys = {(entry["note_id"], entry["revision"]) for entry in entries}
    if not keys:
        return {}
    rows = session.scalars(select(MemoryNoteVersion).where(
        MemoryNoteVersion.note_id.in_({note_id for note_id, _revision in keys}))).all()
    return {(str(row.note_id), row.revision): row for row in rows
            if (str(row.note_id), row.revision) in keys}


def _with_words(session, stored):
    """The envelope for the model: the chosen entries with their words read now.

    Words kept on a Run before D481 are ignored; an entry whose version is gone
    (the note was deleted) is left out.
    """
    from .notes import means

    zones = ("constraints", "aliases", "background")
    rows = _versions(session, [entry for zone in zones for entry in stored[zone]])
    value = {key: item for key, item in stored.items() if key not in zones}
    for zone in zones:
        value[zone] = []
        for entry in stored[zone]:
            row = rows.get((entry["note_id"], entry["revision"]))
            if row is None:
                continue
            item = {key: entry[key] for key in entry if key not in BODY_KEYS}
            item["text"] = row.text
            if zone == "aliases":
                meaning = means(session, row)
                if not meaning or not meaning.get("text") or meaning.get("readable") is False:
                    continue
                item.update(term=row.alias_term, means=meaning["text"])
            value[zone].append(item)
    return value


def frozen(session, run):
    """Fixed at the Run's first assembly, including after skill.load."""
    from .recall import ACTIVE, record_usage

    if KEY in run.versions:
        stored = run.versions[KEY]
        return None if stored is None else _with_words(session, stored)
    value, aliases = build(session, run)
    if run.state in ACTIVE:
        envelope = stored = None
        if value is not None:
            envelope = {key: item for key, item in value.items() if key != "used"}
            stored = {key: ([{name: entry[name] for name in entry if name not in BODY_KEYS}
                             for entry in item] if isinstance(item, list) else item)
                      for key, item in envelope.items()}
        run.versions = {**run.versions, KEY: stored,
                        ALIASES: [{key: item[key] for key in ("note_id", "revision")}
                                  for item in aliases]}
        if value is not None:
            record_usage(run, notes=value["used"])
        return envelope
    return None


def frozen_aliases(session, run):
    """The owner's aliases chosen for this Run, with their words read now."""
    from .notes import alias_entries

    stored = list((run.versions or {}).get(ALIASES) or [])
    rows = _versions(session, stored)
    found = [(rows[key], "active") for key in ((item["note_id"], item["revision"])
                                                for item in stored) if key in rows]
    return [{key: item[key] for key in ("note_id", "revision", "term", "expand")}
            for item in alias_entries(session, found)]


STOPPED = {
    "deleted": "已删除", "revised": "已修改或替换", "replaced": "已替换", "expired": "已过期",
    "unavailable": "范围已不可读",
}


def recheck(session, run, *, now=None):
    """Before each model call: a note that is no longer the one this Run took stops the Run.

    Deleted, revised or replaced (a newer version exists), expired, or out of
    reach. The model has already seen the old words, so dropping them from the
    next context would not undo that; the Run stops and the owner starts again.
    """
    from .notes import _latest_versions, state

    used = ((run.versions or {}).get("memory_usage") or {}).get("notes") or []
    if not used:
        return
    ids = [item["note_id"] for item in used]
    deleted = set(map(str, session.scalars(select(MemoryNoteDeletion.note_id).where(
        MemoryNoteDeletion.note_id.in_(ids))).all()))
    versions = {(str(row.note_id), row.revision): row for row in session.scalars(
        select(MemoryNoteVersion).where(MemoryNoteVersion.note_id.in_(ids))).all()}
    latest = {str(row.note_id): row.revision
              for row in _latest_versions(session, run.requester_id, note_ids=ids)}
    reasons = {}
    for item in used:
        identity = item["note_id"]
        row = versions.get((identity, item["revision"]))
        if identity in deleted or row is None:
            reasons[identity] = "deleted"
        elif latest.get(identity) != item["revision"]:
            reasons[identity] = "revised"
        else:
            current = state(session, row, now=now)
            if current in {"replaced", "expired", "unavailable"}:
                reasons[identity] = current
    if reasons:
        said = "、".join(dict.fromkeys(STOPPED[reason] for reason in reasons.values()))
        raise DomainError(
            "CONVERSATION_HISTORY_REVOKED",
            f"本次带入的个人记忆{said}，请重新发起。",
            detail={"note_ids": sorted(reasons), "reasons": reasons},
        )


_ENTRY = {
    "type": "object",
    "additionalProperties": False,
    "required": ["note_id", "revision", "text", "scope"],
    "properties": {
        "note_id": {"type": "string"},
        "revision": {"type": "integer"},
        "text": {"type": "string"},
        "scope": {"type": "object", "additionalProperties": False,
                  "required": ["kind", "title"],
                  "properties": {"kind": {"type": "string"},
                                 "title": {"type": ["string", "null"]}}},
        "term": {"type": "string"},
        "means": {"type": "string"},
        "note": {"type": "string"},
    },
}

CONTEXT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["zone_policy", "label", "constraints", "aliases", "background", "omitted",
                 "how_to_use"],
    "properties": {
        "zone_policy": {"type": "object", "additionalProperties": False,
                        "required": ["constraints", "aliases", "background"],
                        "properties": {"constraints": {"const": "constraint"},
                                       "aliases": {"const": "constraint"},
                                       "background": {"const": "background"}}},
        "label": {"type": "string"},
        "constraints": {"type": "array", "items": _ENTRY},
        "aliases": {"type": "array", "items": _ENTRY},
        "background": {"type": "array", "items": _ENTRY},
        "omitted": {"type": "integer", "minimum": 0},
        "how_to_use": {"type": "string"},
    },
}
