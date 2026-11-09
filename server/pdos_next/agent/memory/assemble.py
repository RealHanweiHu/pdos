"""Resident personal notes in the Run envelope (P86 第 6 项, design §8, §14.3).

At the Run's first context assembly the server takes the requester's usable
notes for this range (global notes plus notes on the Run's own category,
product, proposal or project), splits them into the constraint zone (口径 and
叫法) and the background zone (背景, and anything marked 可能过期), and freezes
the result for the Run. Nothing goes into the fixed prefix (不可协商项 4); no
model or embedding call is made; at most 1,000 tokens. Neither zone can be cited.
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


def frozen(session, run):
    """Fixed at the Run's first assembly, including after skill.load."""
    from .recall import ACTIVE, record_usage

    if KEY in run.versions:
        return run.versions[KEY]
    value, aliases = build(session, run)
    if run.state in ACTIVE:
        envelope = None
        if value is not None:
            envelope = {key: item for key, item in value.items() if key != "used"}
        run.versions = {**run.versions, KEY: envelope,
                        ALIASES: [{key: item[key] for key in ("note_id", "revision", "term",
                                                               "expand")} for item in aliases]}
        if value is not None:
            record_usage(run, notes=value["used"])
        return envelope
    return None


def frozen_aliases(run):
    return list((run.versions or {}).get(ALIASES) or [])


def recheck(session, run):
    """Before each model call: a note deleted, replaced or out of reach stops the Run."""
    from .notes import state

    used = ((run.versions or {}).get("memory_usage") or {}).get("notes") or []
    if not used:
        return
    ids = [item["note_id"] for item in used]
    deleted = set(map(str, session.scalars(select(MemoryNoteDeletion.note_id).where(
        MemoryNoteDeletion.note_id.in_(ids))).all()))
    versions = {(str(row.note_id), row.revision): row for row in session.scalars(
        select(MemoryNoteVersion).where(MemoryNoteVersion.note_id.in_(ids))).all()}
    for item in used:
        row = versions.get((item["note_id"], item["revision"]))
        if item["note_id"] in deleted or row is None or state(session, row) == "unavailable":
            raise DomainError(
                "CONVERSATION_HISTORY_REVOKED",
                "本次带入的个人记忆已删除或范围已不可读，请重新发起。",
                detail={"note_ids": sorted({item["note_id"]})},
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
