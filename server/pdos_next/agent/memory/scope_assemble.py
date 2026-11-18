"""Team scope notes and scope recency in the Run envelope (M2b; P87, P121 第 3 项).

At the Run's first context assembly the server picks the scope notes this
person can read on the Run's own scope chain (category → product → proposal or
project), following the loaded skills' memory recipe, keeps same-customer notes
only, and stays inside the budget. Only an undegraded 约定 goes to the
constraint zone; everything else is background. Neither zone can be cited.

D481's lesson is applied here from the start: the Run row keeps only note IDs,
revisions and zones. The text is read from the version table at every
assembly, under the reader's current permissions, so a note that was retired,
withdrawn or put out of reach leaves no copy on the Run row and is not sent
again. Nothing goes into the fixed prefix (不可协商项 4); no model or embedding
call is made.
"""

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from pdos_next.errors import DomainError

KEY = "scope_notes_context"
USAGE = "scope_notes"
NOTES_TOKENS = 800   # P87 第 8 项
RECENT_TOKENS = 400  # P87 第 7 项
ANCHORS = ("project", "proposal", "product", "category")
DEFAULT_RECIPE = {
    "scope_notes": {"anchors": list(ANCHORS), "customer_tag": "same_only",
                    "budget_tokens": NOTES_TOKENS},
    "scope_recent": {"budget_tokens": RECENT_TOKENS},
}
LABEL = ("团队备忘：这个范围里成员确认或小Pai 记录的约定、关注点、决策背景和观察。不是业务事实，"
         "不能作为工程判据、批准依据或回答依据引用；与业务数据冲突时以业务数据为准，并提示成员更新备忘。")
HOW_TO_USE = ("conventions 只约束做法和表达方式；background 只作背景，"
              "需要依据时回到业务对象和资料核实。"
              "标了“未核实”“待复核”“对象已更新”“有争议”“未形成正式决定”的条目按标注对待。"
              "还有未带入的条目时用 memory.search 查 kinds=[\"scope_note\"]。")
FLAG_NOTES = {"review_due": "已过复核日期，待复核", "object_updated": "引用的对象已更新，待复核",
              "disputed": "有争议", "no_formal_decision": "未形成正式决定"}


def validate_recipe(value):
    """A context contract's ``x-memory`` declaration; anything unknown is refused.

    Called when the skill catalog loads, so a recipe the server cannot honour
    stops the catalog instead of silently loading more or less memory.
    """
    allowed = {"personal", "scope_notes", "scope_recent", "knowledge"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError("Memory recipe declares a section the server does not load")
    notes = value.get("scope_notes")
    if notes is not None:
        if not isinstance(notes, dict) or set(notes) - {
                "anchors", "customer_tag", "budget_tokens", "pinned_only"}:
            raise ValueError("Memory recipe scope_notes has an unknown field")
        anchors = notes.get("anchors", list(ANCHORS))
        if (not isinstance(anchors, list) or not anchors or set(anchors) - set(ANCHORS)
                or len(set(anchors)) != len(anchors)):
            raise ValueError("Memory recipe anchors must be category, product, proposal, project")
        if notes.get("customer_tag", "same_only") != "same_only":
            # P87 第 9 项: other customers' notes load only by the person's own choice.
            raise ValueError("A recipe cannot widen customer-tagged notes")
        if type(notes.get("pinned_only", False)) is not bool:
            raise ValueError("Memory recipe pinned_only must be true or false")
    for key, limit in (("scope_notes", NOTES_TOKENS), ("scope_recent", RECENT_TOKENS)):
        section = value.get(key)
        if section is None:
            continue
        if not isinstance(section, dict) or (key == "scope_recent" and set(section) - {
                "budget_tokens"}):
            raise ValueError("Memory recipe scope_recent has an unknown field")
        budget = section.get("budget_tokens", limit)
        if type(budget) is not int or not 1 <= budget <= limit:
            raise ValueError(f"Memory recipe budget for {key} must be 1–{limit} tokens")
    for key in ("personal", "knowledge"):
        if key in value and (not isinstance(value[key], list) or not all(
                isinstance(item, str) for item in value[key])):
            raise ValueError("Memory recipe lists must be names")
    return value


def recipe(skills=()):
    """Union of the loaded skills' memory recipes; budgets take the declared maximum.

    A skill declares it under ``x-memory`` in its context contract (P87 第 8 项). The
    server caps every budget; with no declaration the default daily recipe applies.
    """
    declared = [value for value in (
        (getattr(skill, "metadata", {}) or {}).get("context_schema", {}).get("x-memory")
        for skill in skills) if isinstance(value, dict)]
    if not declared:
        return json.loads(json.dumps(DEFAULT_RECIPE))
    notes = [item["scope_notes"] for item in declared if isinstance(item.get("scope_notes"), dict)]
    recent = [item["scope_recent"] for item in declared
              if isinstance(item.get("scope_recent"), dict)]
    result = {}
    if notes:
        wanted = {kind for item in notes for kind in item.get("anchors", ANCHORS)}
        result["scope_notes"] = {
            "anchors": [kind for kind in ANCHORS if kind in wanted],
            "customer_tag": "same_only",
            "pinned_only": all(bool(item.get("pinned_only")) for item in notes),
            "budget_tokens": min(NOTES_TOKENS, max(
                int(item.get("budget_tokens", NOTES_TOKENS)) for item in notes)),
        }
    if recent:
        result["scope_recent"] = {"budget_tokens": min(RECENT_TOKENS, max(
            int(item.get("budget_tokens", RECENT_TOKENS)) for item in recent))}
    return result


def unavailable(run):
    """Team notes are business context: they load in memory-off Sessions too (P85 第 5 项)."""
    if run.category_id is None:
        return "personal_scope"
    if (run.versions or {}).get("dingtalk"):
        return "channel_excluded"  # 钉钉入口首期不带入 (design §9); P31 引文规则未接.
    return None


def leaf(run):
    """(kind, id) of the Run's own most specific scope object."""
    for kind in ("project", "proposal", "product"):
        value = getattr(run, f"{kind}_id", None)
        if value is not None:
            return kind, value
    return "category", run.category_id


def same_customer(version, run):
    """带客户标签的备忘只在同一客户的提案和项目里装载 (P87 第 9 项)."""
    return version.customer_identity is None or version.customer_identity in set(
        run.customer_identities or ())


def candidates(session, run, *, anchors=ANCHORS, pinned_only=False, now=None):
    """(version, state flags, zone) usable in this Run now, pinned and newest first."""
    from pdos_next.domain.knowledge.scope_notes import reads

    now = now or datetime.now(UTC)
    rows = reads.in_scope(
        session, run.tenant_id, category_id=run.category_id, product_id=run.product_id,
        proposal_id=run.proposal_id, project_id=getattr(run, "project_id", None),
        anchors=tuple(anchors),
    )
    found = []
    for row in rows:
        if reads.state(row, now=now) != "active" or not same_customer(row, run):
            continue
        if pinned_only and not row.pinned:
            continue
        if reads.anchor_view(session, row)[1] is None:
            continue
        labels = reads.flags(session, row, now=now)
        if labels is None:
            continue
        found.append((row, labels, reads.zone(row, "active", labels)))
    found.sort(key=lambda item: (not item[0].pinned, item[2] != "constraint",
                                 ANCHORS.index(item[0].anchor_kind),
                                 -item[0].created_at.timestamp(), str(item[0].note_id)))
    return found


def entry(session, row, labels):
    from pdos_next.domain.knowledge.scope_notes import reads

    anchor, _found = reads.anchor_view(session, row)
    if row.generated_by == "xiaopai":
        confirmed = "小Pai 记录，未核实"
    else:
        who = reads.person(session, row.tenant_id, row.confirmed_by) or {}
        confirmed = f"{who.get('name') or '成员'} {row.created_at.date().isoformat()} 确认"
    value = {"note_id": str(row.note_id), "revision": row.revision,
             "kind": reads.KIND_LABELS[row.kind], "statement": row.statement,
             "scope": {"kind": anchor["kind"], "title": anchor["title"]},
             "confirmed": confirmed, "status": reads.EPISTEMIC_LABELS[row.epistemic]}
    notes = [FLAG_NOTES[label] for label in labels if label in FLAG_NOTES]
    if notes:
        value["note"] = "；".join(notes)
    return value


def _envelope():
    return {"zone_policy": {"conventions": "constraint", "background": "background"},
            "label": LABEL, "conventions": [], "background": [], "omitted": 0,
            "how_to_use": HOW_TO_USE}


def build(session, run, *, skills=(), now=None):
    """Select within the recipe and budget: (envelope or None, used refs, omitted)."""
    from pdos_next.agent.kernel.context_budget import estimate_tokens

    plan = recipe(skills).get("scope_notes")
    if unavailable(run) is not None or plan is None:
        return None, [], 0
    value, used = _envelope(), []
    for row, labels, zone in candidates(session, run, anchors=plan["anchors"],
                                        pinned_only=plan.get("pinned_only", False), now=now):
        field = "conventions" if zone == "constraint" else "background"
        value[field].append(entry(session, row, labels))
        if estimate_tokens(json.dumps(value, ensure_ascii=False)) > plan["budget_tokens"]:
            value[field].pop()
            value["omitted"] += 1
            continue
        used.append({"note_id": str(row.note_id), "revision": row.revision, "zone": zone,
                     "pinned": bool(row.pinned)})
    return (value if used else None), used, value["omitted"]


def rebuild(session, run, frozen, *, now=None):
    """The envelope for refs frozen earlier, read again now; unusable notes drop out."""
    from pdos_next.domain.knowledge.scope_notes import reads
    from pdos_next.domain.knowledge.scope_notes.models import ScopeNoteVersion

    now = now or datetime.now(UTC)
    refs = frozen.get("used") or []
    if not refs:
        return None
    ids = [item["note_id"] for item in refs]
    versions = {(str(row.note_id), row.revision): row for row in session.scalars(
        select(ScopeNoteVersion).where(ScopeNoteVersion.note_id.in_(ids)))}
    heads = reads.latest(session, ids)
    value = _envelope()
    value["omitted"] = int(frozen.get("omitted", 0))
    for item in refs:
        row = versions.get((item["note_id"], item["revision"]))
        head = heads.get(row.note_id) if row is not None else None
        if row is None or head is None or head.lifecycle in {"retired", "withdrawn"}:
            continue  # stopped or out of reach since: never sent again
        if not same_customer(row, run) or reads.anchor_view(session, row)[1] is None:
            continue
        labels = reads.flags(session, row, now=now)
        if labels is None:
            continue
        value["conventions" if item["zone"] == "constraint" else "background"].append(
            entry(session, row, labels))
    return value if value["conventions"] or value["background"] else None


def _record(run, used):
    usage = dict(run.versions.get("memory_usage") or {})
    merged = list(usage.get(USAGE, []))
    seen = {item["note_id"] for item in merged}
    merged.extend({"note_id": item["note_id"], "revision": item["revision"],
                   "zone": item["zone"]} for item in used if item["note_id"] not in seen)
    usage[USAGE] = merged[:50]
    run.versions = {**run.versions, "memory_usage": usage}


def frozen(session, run, *, skills=()):
    """(team_memory, scope_recent) for this assembly; the selection is fixed per Run."""
    from .recall import ACTIVE

    stored = (run.versions or {}).get(KEY)
    if stored is None:
        if run.state not in ACTIVE:
            return None, None
        _value, used, omitted = build(session, run, skills=skills)
        plan = recipe(skills)
        stored = {"used": [{key: item[key] for key in ("note_id", "revision", "zone", "pinned")}
                           for item in used],
                  "omitted": omitted,
                  "recent": ({"as_of": datetime.now(UTC).isoformat(),
                              "budget_tokens": plan["scope_recent"]["budget_tokens"]}
                             if "scope_recent" in plan and unavailable(run) is None else None)}
        run.versions = {**run.versions, KEY: stored}
        if used:
            _record(run, used)
    return rebuild(session, run, stored), recent(session, run, stored.get("recent"))


def recent(session, run, frozen_recent):
    """范围近况 at the watermark frozen for this Run; computed again at every assembly."""
    if not frozen_recent or unavailable(run) is not None:
        return None
    from pdos_next.agent.kernel.context_budget import estimate_tokens
    from pdos_next.core.service import Context
    from pdos_next.domain.knowledge.scope_notes import reads
    from pdos_next.domain.knowledge.scope_notes import recent as view

    kind, identity = leaf(run)
    anchor = reads.resolve(session, run.tenant_id, kind, identity)
    if anchor is None:
        return None
    ctx = Context(run.tenant_id, run.writer_id, run.requester_id, category_id=run.category_id)
    try:
        # 范围近况 is optional background: a failed read leaves the Run without it and
        # never breaks context assembly (the savepoint keeps the transaction usable).
        with session.begin_nested():
            value = view.build(session, ctx, anchor,
                               as_of=datetime.fromisoformat(frozen_recent["as_of"]))
    except (DomainError, SQLAlchemyError):
        return None
    for field in ("activity", "note_changes"):
        while value[field] and estimate_tokens(json.dumps(value, ensure_ascii=False)) > int(
                frozen_recent["budget_tokens"]):
            value[field].pop()
    if not value["activity"] and not value["note_changes"]:
        return None
    return value


def recheck(session, run):
    """Before each model call: a note taken back or out of reach stops the Run.

    Already-sent text cannot be recalled from the model, so a Run that carried a
    note which was since retired, withdrawn or made unreadable for this person
    is stopped and started again without it. So is a Run whose note now reads
    differently (D507: the same rule as personal notes, D481). A newer version that
    left what the model was shown unchanged, such as added evidence, does not stop it.
    """
    from pdos_next.domain.knowledge.scope_notes import reads
    from pdos_next.domain.knowledge.scope_notes.models import ScopeNoteVersion

    used = ((run.versions or {}).get("memory_usage") or {}).get(USAGE) or []
    if not used:
        return
    heads = reads.latest(session, [item["note_id"] for item in used])
    shown = {(str(row.note_id), row.revision): row for row in session.scalars(
        select(ScopeNoteVersion).where(
            ScopeNoteVersion.note_id.in_([item["note_id"] for item in used])))}
    gone, changed = [], []
    for item in used:
        head = next((row for row in heads.values() if str(row.note_id) == item["note_id"]), None)
        if (head is None or head.lifecycle in {"retired", "withdrawn"}
                or reads.anchor_view(session, head)[1] is None
                or reads.flags(session, head, now=datetime.now(UTC)) is None):
            gone.append(item["note_id"])
        elif head.revision != item["revision"]:
            before = shown.get((item["note_id"], item["revision"]))
            if before is None or (before.kind, before.statement, before.epistemic) != (
                    head.kind, head.statement, head.epistemic):
                changed.append(item["note_id"])
    if gone or changed:
        said = "、".join(text for text, ids in (
            ("已修改", changed), ("已停用、撤回或已不可读", gone)) if ids)
        raise DomainError(
            "CONVERSATION_HISTORY_REVOKED",
            f"本次带入的团队备忘{said}，请重新发起。",
            detail={"scope_note_ids": sorted({*gone, *changed}),
                    "changed_note_ids": sorted(set(changed))},
        )


def usage(session, used):
    """Team notes a Run used, as this reader may see them now (“用到了 N 条记忆”)."""
    from pdos_next.domain.knowledge.scope_notes import reads

    heads = reads.latest(session, [item["note_id"] for item in used])
    result = []
    for item in used:
        head = next((row for row in heads.values() if str(row.note_id) == item["note_id"]), None)
        view = reads.view(session, head) if head is not None else None
        if view is None:
            continue
        result.append({"note_id": item["note_id"], "revision": item["revision"],
                       "zone": item["zone"], "kind_label": view["kind_label"],
                       "statement": view["statement"], "anchor": view["anchor"],
                       "state": view["state"],
                       "changed_since": view["revision"] != item["revision"]})
    return result


_ENTRY = {
    "type": "object",
    "additionalProperties": False,
    "required": ["note_id", "revision", "kind", "statement", "scope", "confirmed", "status"],
    "properties": {
        "note_id": {"type": "string"},
        "revision": {"type": "integer"},
        "kind": {"type": "string"},
        "statement": {"type": "string"},
        "scope": {"type": "object", "additionalProperties": False, "required": ["kind", "title"],
                  "properties": {"kind": {"type": "string"},
                                 "title": {"type": ["string", "null"]}}},
        "confirmed": {"type": "string"},
        "status": {"type": "string"},
        "note": {"type": "string"},
    },
}

CONTEXT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["zone_policy", "label", "conventions", "background", "omitted", "how_to_use"],
    "properties": {
        "zone_policy": {"type": "object", "additionalProperties": False,
                        "required": ["conventions", "background"],
                        "properties": {"conventions": {"const": "constraint"},
                                       "background": {"const": "background"}}},
        "label": {"type": "string"},
        "conventions": {"type": "array", "items": _ENTRY},
        "background": {"type": "array", "items": _ENTRY},
        "omitted": {"type": "integer", "minimum": 0},
        "how_to_use": {"type": "string"},
    },
}

_LINE = {"type": "object", "additionalProperties": False, "required": ["at", "what"],
         "properties": {"at": {"type": "string"}, "who": {"type": ["string", "null"]},
                        "what": {"type": "string"}, "subject": {"type": ["string", "null"]},
                        "note_id": {"type": "string"}, "revision": {"type": "integer"}}}

RECENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["zone", "label", "as_of", "scope", "activity", "note_changes"],
    "properties": {
        "zone": {"const": "background"},
        "label": {"type": "string"},
        "as_of": {"type": "string"},
        "scope": {"type": "object", "additionalProperties": False, "required": ["kind", "title"],
                  "properties": {"kind": {"type": "string"},
                                 "title": {"type": ["string", "null"]}}},
        "activity": {"type": "array", "items": _LINE},
        "note_changes": {"type": "array", "items": _LINE},
    },
}
