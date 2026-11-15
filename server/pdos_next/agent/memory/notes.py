"""本人记忆条目 (M2a, P86): the owner's own free-text notes and personal aliases.

A note is never a business fact and never an authority. Only the human owner,
acting for themself, writes, revises or purges a note; the database refuses the
AI writer identity. Personal memory is not a business record, so these are not
T0/T1/T2 domain commands (design §5 第 4 条). Every rule here is deterministic:
conflicts are found by scope and word overlap, never by a model, and the owner
decides merge, replace or keep both (P86 第 4 项).
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import func, select, text

from pdos_next.core.schema_base import StrictModel
from pdos_next.core.service import digest
from pdos_next.errors import DomainError

from .models import (
    MemoryCandidate,
    MemoryCandidateDecision,
    MemoryNote,
    MemoryNoteDeletion,
    MemoryNoteVersion,
)

VERSION = "memory-notes/v1"
NOTE_LIMIT = 50
TEXT_LIMIT = 200
ALIAS_TERM_LIMIT = 40
CANONICAL_LIMIT = 80
SIMILARITY = "memory-note-similarity/v1;same-alias|jaccard>=0.34|shared>=2;scope=same-or-global"
KIND_LABELS = {"convention": "口径", "background": "背景", "alias": "叫法"}
Kind = Literal["convention", "background", "alias"]
ScopeKind = Literal["global", "category", "product", "proposal", "project"]
ObjectKind = Literal["category", "product", "proposal", "project"]


class ScopeRef(StrictModel):
    kind: ScopeKind = "global"
    id: UUID | None = None

    @model_validator(mode="after")
    def bound(self):
        if (self.kind == "global") != (self.id is None):
            raise ValueError("全局作用域不带对象；其他作用域必须指明对象。")
        return self


class ObjectRef(StrictModel):
    kind: ObjectKind
    id: UUID


class NoteDraft(StrictModel):
    kind: Kind
    text: str = Field(default="", max_length=400)
    scope: ScopeRef = Field(default_factory=ScopeRef)
    valid_until: datetime | None = None
    alias_term: str | None = Field(default=None, max_length=80)
    alias_canonical: str | None = Field(default=None, max_length=160)
    alias_target: ObjectRef | None = None

    @model_validator(mode="after")
    def shape(self):
        if self.kind == "alias":
            if not clean(self.alias_term or ""):
                raise ValueError("叫法须写明你说的词。")
            if bool(clean(self.alias_canonical or "")) == bool(self.alias_target):
                raise ValueError("叫法须指向一个标准词或一个对象，二选一。")
        elif self.alias_term or self.alias_canonical or self.alias_target:
            raise ValueError("只有叫法条目带叫法字段。")
        elif not clean(self.text):
            raise ValueError("条目内容不能为空。")
        return self


Resolution = Literal["keep_both", "replace", "merge"]


class ConflictChoice(StrictModel):
    resolution: Resolution
    note_ids: list[UUID] = Field(default_factory=list, max_length=10)
    expected_revisions: list[int] = Field(default_factory=list, max_length=10)
    merged_text: str | None = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def complete(self):
        if len(self.note_ids) != len(self.expected_revisions):
            raise ValueError("每条旧条目都要带当前版本号。")
        if len(set(self.note_ids)) != len(self.note_ids):
            raise ValueError("旧条目不能重复。")
        if self.resolution == "merge" and (len(self.note_ids) != 1 or not self.merged_text):
            raise ValueError("合并须指明一条旧条目并给出合并后的内容。")
        if self.resolution == "replace" and not self.note_ids:
            raise ValueError("替换须指明被替换的旧条目。")
        return self


class CreateNote(StrictModel):
    request_key: UUID
    note: NoteDraft
    conflict: ConflictChoice | None = None


class ReviseNote(StrictModel):
    request_key: UUID
    expected_revision: int = Field(ge=1, strict=True)
    note: NoteDraft


class DeleteNote(StrictModel):
    request_key: UUID
    expected_revision: int = Field(ge=1, strict=True)


def clean(value):
    return " ".join(str(value or "").split())


def _bounded(value, limit, label):
    value = clean(value)
    if not 1 <= len(value) <= limit:
        raise DomainError("VALIDATION_FAILED", f"{label}须为 1–{limit} 个字。", 422)
    return value


# ---------------------------------------------------------------------------
# Scope and object references: server-validated, readable now (§5 第 2 条).

def _models():
    from pdos_next.core.models import Category, Product
    from pdos_next.domain.categories.preproject.models import Proposal
    from pdos_next.domain.projects.models import Project

    return {
        "category": (Category, "name", Category.id),
        "product": (Product, "name", Product.category_id),
        "proposal": (Proposal, "title", Proposal.category_id),
        "project": (Project, "name", Project.category_id),
    }


def readable_object(session, kind, identity):
    """(category_id, title, revision) of an object readable now, or None."""
    model, column, category = _models()[kind]
    row = session.execute(
        select(category, getattr(model, column), model.revision)
        .where(model.id == identity, func.category_access(model.tenant_id, category))
    ).first()
    return None if row is None else (row[0], row[1], row[2])


def resolve_scope(session, scope):
    if scope.kind == "global":
        return {"kind": "global", "id": None, "category_id": None, "title": "全局"}
    found = readable_object(session, scope.kind, scope.id)
    if found is None:
        raise DomainError("FORBIDDEN_SCOPE", "所选作用域当前不可读。", 403)
    return {"kind": scope.kind, "id": scope.id, "category_id": found[0], "title": found[1]}


def scope_view(session, version):
    if version.scope_kind == "global":
        return {"kind": "global", "id": None, "title": "全局", "readable": True}
    found = readable_object(session, version.scope_kind, version.scope_id)
    return {"kind": version.scope_kind, "id": str(version.scope_id),
            "title": found[1] if found else None, "readable": found is not None}


def normalized(session, draft):
    """Server-side values for one draft; nothing comes from the model or the page."""
    scope = resolve_scope(session, draft.scope)
    values = {"kind": draft.kind, "scope_kind": scope["kind"], "scope_id": scope["id"],
              "category_id": scope["category_id"], "alias_term": None, "alias_canonical": None,
              "target_kind": None, "target_id": None, "target_version": None,
              "valid_until": draft.valid_until}
    if draft.valid_until is not None:
        until = draft.valid_until if draft.valid_until.tzinfo else draft.valid_until.replace(
            tzinfo=UTC)
        if until <= datetime.now(UTC):
            raise DomainError("VALIDATION_FAILED", "有效期须晚于现在。", 422)
        values["valid_until"] = until
    if draft.kind == "alias":
        term = _bounded(draft.alias_term, ALIAS_TERM_LIMIT, "叫法")
        values["alias_term"] = term
        if draft.alias_target is not None:
            found = readable_object(session, draft.alias_target.kind, draft.alias_target.id)
            if found is None:
                raise DomainError("FORBIDDEN_SCOPE", "叫法指向的对象当前不可读。", 403)
            values.update(target_kind=draft.alias_target.kind, target_id=draft.alias_target.id,
                          target_version=found[2])
            means = found[1]
        else:
            means = _bounded(draft.alias_canonical, CANONICAL_LIMIT, "标准词")
            values["alias_canonical"] = means
        values["text"] = (_bounded(draft.text, TEXT_LIMIT, "条目内容") if clean(draft.text)
                          else f"我说“{term}”指{means}")[:TEXT_LIMIT]
    else:
        values["text"] = _bounded(draft.text, TEXT_LIMIT, "条目内容")
    return values


# ---------------------------------------------------------------------------
# Reading the owner's own notes.

def _latest_versions(session, owner_id, *, note_ids=None):
    """The latest version of each of the owner's notes (≤50 notes, small history)."""
    query = (select(MemoryNoteVersion)
             .where(MemoryNoteVersion.owner_id == owner_id)
             .order_by(MemoryNoteVersion.note_id, MemoryNoteVersion.revision.desc()))
    if note_ids is not None:
        query = query.where(MemoryNoteVersion.note_id.in_(list(note_ids)))
    latest = {}
    for row in session.scalars(query):
        latest.setdefault(row.note_id, row)
    return list(latest.values())


def state(session, version, *, now=None):
    """active / replaced / expired / stale (可能过期) / unavailable (范围不可读)."""
    now = now or datetime.now(UTC)
    if version.status == "replaced":
        return "replaced"
    if version.valid_until is not None and version.valid_until <= now:
        return "expired"
    if version.category_id is not None and readable_object(
        session, version.scope_kind, version.scope_id
    ) is None:
        return "unavailable"
    if version.target_id is not None:
        found = readable_object(session, version.target_kind, version.target_id)
        if found is None:
            return "unavailable"
        if found[2] != version.target_version:
            return "stale"
    return "active"


def means(session, version):
    if version.kind != "alias":
        return None
    if version.target_id is None:
        return {"kind": "term", "text": version.alias_canonical}
    found = readable_object(session, version.target_kind, version.target_id)
    return {"kind": version.target_kind, "id": str(version.target_id),
            "text": found[1] if found else None, "readable": found is not None,
            "updated": bool(found and found[2] != version.target_version)}


def view(session, version, *, current=None):
    value = {
        "note_id": str(version.note_id),
        "revision": version.revision,
        "kind": version.kind,
        "kind_label": KIND_LABELS[version.kind],
        "text": version.text,
        "scope": scope_view(session, version),
        "state": current or state(session, version),
        "valid_until": version.valid_until.isoformat() if version.valid_until else None,
        "confirmed_at": version.created_at.isoformat(),
        "origin": version.origin,
        "replaced_by": str(version.replaced_by) if version.replaced_by else None,
    }
    if version.kind == "alias":
        value["alias"] = {"term": version.alias_term, "means": means(session, version)}
    return value


def active_count(session, owner_id):
    return sum(1 for row in _latest_versions(session, owner_id) if row.status == "active")


def listing(session, ctx):
    from . import policy

    rows = _latest_versions(session, ctx.requester_id)
    notes = [view(session, row) for row in rows]
    order = {"active": 0, "stale": 1, "unavailable": 2, "expired": 3, "replaced": 4}
    notes.sort(key=lambda item: (order[item["state"]], item["kind"], item["confirmed_at"]),
               reverse=False)
    deleted = session.scalar(select(func.count()).select_from(MemoryNoteDeletion).where(
        MemoryNoteDeletion.owner_id == ctx.requester_id))
    current = policy.current(session)
    return {
        "version": VERSION,
        "enabled": policy.notes_enabled(current),
        "limit": NOTE_LIMIT,
        "text_limit": TEXT_LIMIT,
        "active_count": sum(1 for item in notes if item["state"] != "replaced"),
        "notes": notes,
        "deleted_count": deleted,
        "note": "仅你本人可见。条目不是业务事实，也不授予任何权限；"
                "和业务数据冲突时以业务数据为准。",
    }


def history(session, ctx, note_id):
    _note(session, ctx, note_id)
    rows = session.scalars(select(MemoryNoteVersion).where(
        MemoryNoteVersion.note_id == note_id).order_by(MemoryNoteVersion.revision.desc())).all()
    if not rows:
        raise DomainError("NOT_FOUND", "这条记忆已删除。", 404)
    return {"version": VERSION, "note_id": str(note_id),
            "versions": [view(session, row, current="history" if index else None)
                         for index, row in enumerate(rows)]}


# ---------------------------------------------------------------------------
# Deterministic conflict detection (P86 第 4 项).

def words(value):
    from pdos_next.agent.enterprise_search.tokenizer import analyze_query

    parsed = analyze_query(value)
    return {term for term in parsed["terms"] if len(term) >= 2} | set(parsed["codes"])


def _overlapping_scope(left_kind, left_id, right_kind, right_id):
    return "global" in {left_kind, right_kind} or (left_kind, left_id) == (right_kind, right_id)


def similar(session, owner_id, values, *, exclude=()):
    """Active notes that look like duplicates or contradictions of a draft."""
    draft_words = words(values["text"] + " " + (values.get("alias_term") or ""))
    found = []
    for row in _latest_versions(session, owner_id):
        if row.note_id in exclude or row.status != "active":
            continue
        if not _overlapping_scope(values["scope_kind"], values["scope_id"],
                                  row.scope_kind, row.scope_id):
            continue
        if values["kind"] == "alias" and row.kind == "alias" and clean(
            row.alias_term
        ).casefold() == clean(values["alias_term"]).casefold():
            found.append((row, "same_alias"))
            continue
        other = words(row.text + " " + (row.alias_term or ""))
        shared = draft_words & other
        union = draft_words | other
        if shared and (len(shared) >= 2 or len(shared) / len(union) >= 0.34):
            found.append((row, "similar_text"))
    return found


def conflict_views(session, rows):
    return [{**view(session, row), "reason": reason} for row, reason in rows]


def conflicts(session, ctx, draft):
    from .policy import require_notes

    require_notes(session)
    values = normalized(session, draft)
    rows = similar(session, ctx.requester_id, values)
    return {"version": VERSION, "similarity": SIMILARITY,
            "conflicts": conflict_views(session, rows),
            "choices": ["merge", "replace", "keep_both"] if rows else []}


# ---------------------------------------------------------------------------
# Writing as the owner (human acting for themself).

def _lock(session, ctx):
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                    {"key": f"memory-notes:{ctx.tenant_id}:{ctx.requester_id}"})


def _note(session, ctx, note_id):
    row = session.get(MemoryNote, note_id)
    if row is None or row.owner_id != ctx.requester_id:
        raise DomainError("NOT_FOUND", "这条记忆不存在，或不属于你本人。", 404)
    if session.scalar(select(MemoryNoteDeletion.id).where(MemoryNoteDeletion.note_id == note_id)):
        raise DomainError("NOT_FOUND", "这条记忆已删除。", 404)
    return row


def _latest(session, note_id):
    return session.scalar(select(MemoryNoteVersion).where(MemoryNoteVersion.note_id == note_id)
                          .order_by(MemoryNoteVersion.revision.desc()).limit(1))


def _append(session, ctx, note_id, revision, values, *, status="active", origin="manual",
            replaced_by=None, candidate_id=None, request_key, fingerprint):
    row = MemoryNoteVersion(
        id=uuid4(), tenant_id=ctx.tenant_id, owner_id=ctx.requester_id, note_id=note_id,
        revision=revision, status=status, origin=origin, replaced_by=replaced_by,
        candidate_id=candidate_id, request_key=request_key, request_sha256=fingerprint,
        **{key: values[key] for key in (
            "kind", "text", "scope_kind", "scope_id", "category_id", "alias_term",
            "alias_canonical", "target_kind", "target_id", "target_version", "valid_until")},
    )
    session.add(row)
    session.flush()
    return row


def _replay(session, ctx, key, fingerprint):
    # One request may write the new note and mark old ones replaced; replay the new one.
    row = session.scalar(select(MemoryNoteVersion).where(
        MemoryNoteVersion.owner_id == ctx.requester_id, MemoryNoteVersion.request_key == key,
    ).order_by(MemoryNoteVersion.status == "replaced", MemoryNoteVersion.created_at.desc())
     .limit(1))
    if row is None:
        return None
    if row.request_sha256 != fingerprint:
        raise DomainError("DUPLICATE_INTENT_CONFLICT", "请求编号对应不同的记忆操作。")
    return row


def _copy(version, **changes):
    values = {key: getattr(version, key) for key in (
        "kind", "text", "scope_kind", "scope_id", "category_id", "alias_term",
        "alias_canonical", "target_kind", "target_id", "target_version", "valid_until")}
    values.update(changes)
    return values


def create(session, ctx, data, *, origin="manual", candidate_id=None):
    """Create a note; if similar notes exist the owner must have chosen how."""
    from .policy import require_notes

    require_notes(session)
    _lock(session, ctx)
    values = normalized(session, data.note)
    fingerprint = digest({"op": "create", "values": values, "candidate": candidate_id,
                          "conflict": data.conflict.model_dump(mode="json")
                          if data.conflict else None})
    replay = _replay(session, ctx, data.request_key, fingerprint)
    if replay is not None:
        return created_view(session, replay.note_id)
    found = similar(session, ctx.requester_id, values)
    choice = data.conflict
    chosen = dict(zip(choice.note_ids, choice.expected_revisions, strict=True)) if choice else {}
    if found and choice is None:
        raise DomainError(
            "VERSION_CONFLICT", "已有相似或矛盾的旧条目，请选择合并、替换或都保留。",
            detail={"reason_key": "memory_conflict_unresolved",
                    "conflicts": conflict_views(session, found)},
        )
    for note_id, revision in chosen.items():
        current = _latest(session, note_id)
        _note(session, ctx, note_id)
        if current is None or current.revision != revision or current.status != "active":
            raise DomainError("VERSION_CONFLICT", "旧条目已变化，请刷新后再选。")
    from .suppression import lift

    lift(session, ctx, values)  # The owner confirms it again: forgetting no longer applies.
    if choice and choice.resolution == "merge":
        (note_id, revision), = chosen.items()
        current = _latest(session, note_id)
        merged = _bounded(choice.merged_text, TEXT_LIMIT, "合并后的内容")
        if current.kind == "alias" and values["kind"] == "alias":
            merged_values = {**values, "text": merged}
        else:
            merged_values = _copy(current, text=merged, valid_until=values["valid_until"])
        _append(session, ctx, note_id, revision + 1, merged_values, origin="merge",
                candidate_id=candidate_id, request_key=data.request_key,
                fingerprint=fingerprint)
        return created_view(session, note_id, resolution="merge")
    if active_count(session, ctx.requester_id) - (
        len(chosen) if choice and choice.resolution == "replace" else 0
    ) >= NOTE_LIMIT:
        raise DomainError("VALIDATION_FAILED",
                          f"记忆条目最多 {NOTE_LIMIT} 条，请先删除或合并旧条目。",
                          422, detail={"reason_key": "memory_note_limit"})
    note = MemoryNote(id=uuid4(), tenant_id=ctx.tenant_id, owner_id=ctx.requester_id)
    session.add(note)
    session.flush()
    _append(session, ctx, note.id, 1, values, origin=origin, candidate_id=candidate_id,
            request_key=data.request_key, fingerprint=fingerprint)
    if choice and choice.resolution == "replace":
        now = datetime.now(UTC)
        for note_id, revision in chosen.items():
            current = _latest(session, note_id)
            _append(session, ctx, note_id, revision + 1,
                    _copy(current, valid_until=min(current.valid_until or now, now)),
                    status="replaced", origin=current.origin, replaced_by=note.id,
                    request_key=data.request_key, fingerprint=fingerprint)
    return created_view(session, note.id, resolution=choice.resolution if choice else None)


def created_view(session, note_id, *, resolution=None):
    return {"version": VERSION, "note": view(session, _latest(session, note_id)),
            "resolution": resolution}


def revise(session, ctx, note_id, data):
    from .policy import require_notes

    require_notes(session)
    _lock(session, ctx)
    _note(session, ctx, note_id)
    values = normalized(session, data.note)
    fingerprint = digest({"op": "revise", "note_id": note_id, "values": values,
                          "expected": data.expected_revision})
    replay = _replay(session, ctx, data.request_key, fingerprint)
    if replay is not None:
        return created_view(session, replay.note_id)
    current = _latest(session, note_id)
    if current.revision != data.expected_revision:
        raise DomainError("VERSION_CONFLICT", "这条记忆已变化，请刷新后再改。")
    if current.status != "active":
        raise DomainError("VERSION_CONFLICT", "已替换的条目只能查看或删除。")
    _append(session, ctx, note_id, current.revision + 1, values, origin=current.origin,
            request_key=data.request_key, fingerprint=fingerprint)
    return created_view(session, note_id)


def purge(session, ctx, note_id, data):
    """真删除: every version body and its source candidate go; a tombstone stays."""
    _lock(session, ctx)
    fingerprint = digest({"op": "delete", "note_id": note_id})
    replay = session.scalar(select(MemoryNoteDeletion).where(
        MemoryNoteDeletion.owner_id == ctx.requester_id,
        MemoryNoteDeletion.request_key == data.request_key))
    if replay is not None:
        if replay.request_sha256 != fingerprint:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "请求编号对应不同的记忆操作。")
        return deletion_view(replay)
    _note(session, ctx, note_id)
    current = _latest(session, note_id)
    if current is None or current.revision != data.expected_revision:
        raise DomainError("VERSION_CONFLICT", "这条记忆已变化，请刷新后再删。")
    versions = session.scalars(select(MemoryNoteVersion).where(
        MemoryNoteVersion.note_id == note_id)).all()
    candidates = {row.candidate_id for row in versions if row.candidate_id is not None}
    from .suppression import record as suppress

    suppress(session, ctx, note_id, versions)  # P121 第 8 项: a digest, never the text.
    for row in versions:
        session.delete(row)
    session.flush()
    for identity in candidates:
        for decision in session.scalars(select(MemoryCandidateDecision).where(
                MemoryCandidateDecision.candidate_id == identity)).all():
            session.delete(decision)
        session.flush()
        candidate = session.get(MemoryCandidate, identity)
        if candidate is not None:
            session.delete(candidate)
    session.flush()
    tombstone = MemoryNoteDeletion(
        id=uuid4(), tenant_id=ctx.tenant_id, owner_id=ctx.requester_id, note_id=note_id,
        purged_versions=len(versions), request_key=data.request_key, request_sha256=fingerprint,
    )
    session.add(tombstone)
    session.flush()
    return deletion_view(tombstone)


def deletion_view(row):
    return {"version": VERSION, "note_id": str(row.note_id), "deleted": True,
            "deleted_at": row.created_at.isoformat(), "purged_versions": row.purged_versions,
            # P94: say plainly what is gone now and what expires with checkpoints.
            "note": "正文与历史版本已清除，只保留“某时删除了一条”的记录。以往对话的运行检查点里"
                    "可能仍留有带入时的副本，最迟 30 天内随检查点清除。"}


# ---------------------------------------------------------------------------
# Use in a Run (§6.3 怎么用, §6.7 个人叫法). Owner = the Run's requester.

def in_range(version, run):
    if version.scope_kind == "global":
        return True
    return version.scope_id in {run.category_id, run.product_id, run.proposal_id,
                                getattr(run, "project_id", None)} - {None}


def usable(session, run, *, now=None):
    """(version, state) of the requester's notes usable in this Run's range now."""
    now = now or datetime.now(UTC)
    result = []
    for row in _latest_versions(session, run.requester_id):
        if not in_range(row, run):
            continue
        current = state(session, row, now=now)
        if current in {"active", "stale"}:
            result.append((row, current))
    return result


def alias_expansions(session, run, query, aliases):
    """Extra query words for the owner's own aliases found in the query (§6.7 第 2 项)."""
    applied, extra = [], []
    folded = clean(query).casefold()
    for item in aliases:
        if item["term"].casefold() in folded and item["expand"]:
            words_added = [word for word in item["expand"] if word.casefold() not in folded]
            if words_added:
                extra.extend(words_added)
                applied.append({"note_id": item["note_id"], "revision": item["revision"],
                                "term": item["term"], "expanded_with": words_added})
    return " ".join(extra), applied


def alias_entries(session, rows):
    entries = []
    for row, current in rows:
        if row.kind != "alias":
            continue
        meaning = means(session, row)
        if not meaning or not meaning.get("text") or meaning.get("readable") is False:
            continue
        entries.append({"note_id": str(row.note_id), "revision": row.revision,
                        "term": row.alias_term, "expand": [meaning["text"]],
                        "means": meaning, "state": current})
    return entries


def first_sentence(value, limit=80):
    head = re.split(r"[。！？!?\n]", value.strip(), maxsplit=1)[0].strip() or value.strip()
    return head if len(head) <= limit else head[: limit - 1] + "…"


def expires(created_at, days=7):
    return created_at + timedelta(days=days)
