"""本人记忆条目 (M2a, P86): the owner's own free-text notes and personal aliases.

A note is never a business fact and never an authority. Only the human owner,
acting for themself, writes, revises or purges a note; the database refuses the
AI writer identity. Personal memory is not a business record, so these are not
T0/T1/T2 domain commands (design §5 第 4 条). Every rule here is deterministic:
conflicts are found by scope and word overlap, never by a model, and the owner
decides merge, replace or keep both (P86 第 4 项).

Unified item contract (P121 第 6 项后半, target architecture §5.7, D512): each
version also carries when the thing happened, when it takes effect, its
confirmation state (always 本人确认), evidence links and the owner's own 冲突 / 重复
relations. 替代按生效时间判断: replacing a note takes effect at the new note's start,
and a draft that starts before the note it would replace only enters history.
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import func, select, text

from pdos_next.core.clock import now as clock_now
from pdos_next.core.schema_base import StrictModel
from pdos_next.core.service import digest
from pdos_next.domain.knowledge.scope_notes.schemas import EvidenceInput
from pdos_next.errors import DomainError

from .models import (
    NOTE_LINK_LIMIT,
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
SIMILARITY = ("memory-note-similarity/v2;same-alias|jaccard>=0.34|shared>=2;scope=same-or-global;"
              "valid-time=overlapping")
KIND_LABELS = {"convention": "口径", "background": "背景", "alias": "叫法"}
# Same value as the scope notes' 成员确认; for one's own note it reads 本人确认.
CONFIRMATION = "member_confirmed"
CONFIRMATION_LABELS = {CONFIRMATION: "本人确认"}
RELATION_LABELS = {"conflicts": "冲突", "duplicates": "重复", "supersedes": "替代了",
                   "superseded_by": "被替代"}
CONTENT = ("kind", "text", "scope_kind", "scope_id", "category_id", "alias_term",
           "alias_canonical", "target_kind", "target_id", "target_version", "valid_until",
           "occurred_at", "valid_from", "confirmation", "evidence", "relations")
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


class RelationRef(StrictModel):
    """冲突 / 重复 with another of the owner's own notes (替代 goes through the conflict choice)."""

    type: Literal["conflicts", "duplicates"]
    note_id: UUID


class NoteDraft(StrictModel):
    kind: Kind
    text: str = Field(default="", max_length=400)
    scope: ScopeRef = Field(default_factory=ScopeRef)
    valid_until: datetime | None = None
    alias_term: str | None = Field(default=None, max_length=80)
    alias_canonical: str | None = Field(default=None, max_length=160)
    alias_target: ObjectRef | None = None
    # Unified item contract (§5.7). On a revision a field left out keeps the current value;
    # ``valid_from`` left out means "from now" for a note in effect, its own start otherwise.
    occurred_at: datetime | None = None
    valid_from: datetime | None = None
    evidence: list[EvidenceInput] | None = Field(default=None, max_length=NOTE_LINK_LIMIT)
    relations: list[RelationRef] | None = Field(default=None, max_length=NOTE_LINK_LIMIT)

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


def as_utc(value):
    return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


def normalized(session, draft, *, owner_id=None, tenant_id=None, prior=None, stamp=None):
    """Server-side values for one draft; nothing comes from the model or the page.

    ``valid_from`` stays None when the draft leaves it to the default (see ``start``),
    so a retried request keeps the same fingerprint.
    """
    stamp = stamp or clock_now()
    given = draft.model_fields_set
    scope = resolve_scope(session, draft.scope)
    values = {"kind": draft.kind, "scope_kind": scope["kind"], "scope_id": scope["id"],
              "category_id": scope["category_id"], "alias_term": None, "alias_canonical": None,
              "target_kind": None, "target_id": None, "target_version": None,
              "valid_until": as_utc(draft.valid_until), "confirmation": CONFIRMATION}
    keep = prior is not None
    values["occurred_at"] = (as_utc(draft.occurred_at) if "occurred_at" in given or not keep
                             else prior.occurred_at)
    if values["occurred_at"] is not None and values["occurred_at"] > stamp:
        raise DomainError("VALIDATION_FAILED", "事情发生的时间不能晚于现在。", 422,
                          detail={"reason_key": "memory_note_occurred"})
    values["valid_from"] = as_utc(draft.valid_from)
    begins = values["valid_from"] or (prior.valid_from if keep and prior.valid_from > stamp
                                      else stamp)
    if values["valid_until"] is not None and values["valid_until"] <= max(begins, stamp):
        raise DomainError("VALIDATION_FAILED", "有效期须晚于生效起点和现在。", 422,
                          detail={"reason_key": "memory_note_validity"})
    if draft.evidence is not None or not keep:
        values["evidence"] = resolve_evidence(
            session, owner_id, tenant_id, draft.evidence or [],
            known=prior.evidence if keep else ())
    else:
        values["evidence"] = list(prior.evidence)
    if draft.relations is not None or not keep:
        values["relations"] = resolve_relations(session, owner_id, draft.relations or [],
                                                own=prior.note_id if keep else None)
    else:
        values["relations"] = list(prior.relations)
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


def start(values, prior, stamp):
    """生效起点: as given; otherwise now, except that a note not yet in effect keeps its start."""
    if values["valid_from"] is not None:
        return values["valid_from"]
    if prior is not None and prior.valid_from > stamp:
        return prior.valid_from
    return stamp


# ---------------------------------------------------------------------------
# Evidence links and relations (§5.7): references only, read now as the owner.

def _deny(code, key, message, status=403):
    raise DomainError(code, message, status, detail={"reason_key": key})


def _link_key(link):
    return (link["source_type"], str(link["source_id"]), digest(link.get("locator") or {}),
            link["stance"])


def _source(session, owner_id, tenant_id, source_type, source_kind, source_id):
    """(root, version, title) of a source the owner can read now, or None."""
    from pdos_next.agent.kernel.models import AgentRun
    from pdos_next.core.models import Artifact, Receipt
    from pdos_next.domain.knowledge.scope_notes import reads as scope_reads
    from pdos_next.domain.projects.discussions.models import DiscussionThread

    if source_type == "business_object":
        if source_kind == "proposal_decision":
            found = scope_reads.formal(session, tenant_id, source_kind, source_id)
            return None if found is None else (found["id"], found["revision"], found["title"])
        found = readable_object(session, source_kind, source_id)
        return None if found is None else (source_id, found[2], found[1])
    model = {"run": AgentRun, "discussion": DiscussionThread, "receipt": Receipt,
             "original": Artifact}[source_type]
    row = session.get(model, source_id)
    if row is None or row.tenant_id != tenant_id:
        return None
    if source_type == "run":
        # Only the owner's own conversations; another person's Run is never a source here.
        return None if row.requester_id != owner_id else (row.id, None, None)
    if source_type == "receipt":
        return row.subject_id, row.subject_revision, None
    if source_type == "original":
        return row.original_id or row.id, row.revision, None
    return row.id, None, getattr(row, "title", None)


def resolve_evidence(session, owner_id, tenant_id, items, *, known=()):
    """Each link is read now as the owner; a quote is reduced to its digest (as scope notes)."""
    previous = {_link_key(link): link for link in known}
    links, seen = [], set()
    for item in items:
        found = _source(session, owner_id, tenant_id, item.source_type, item.source_kind,
                        item.source_id)
        if found is None:
            _deny("FORBIDDEN_SCOPE", "memory_note_evidence_unreadable", "证据来源当前不可读。")
        link = {"source_type": item.source_type, "source_kind": item.source_kind,
                "source_id": str(item.source_id), "source_version": found[1],
                "locator": dict(item.locator), "root_source_id": str(found[0]),
                "stance": item.stance}
        key = _link_key(link)
        if key in seen:
            continue
        seen.add(key)
        # The page re-sends the links it shows without the quote: keep the digest it had.
        link["quote_sha256"] = digest(item.quote) if item.quote else (
            previous.get(key, {}).get("quote_sha256"))
        links.append(link)
    return links


def resolve_relations(session, owner_id, items, *, own=None):
    relations, seen = [], set()
    for item in items:
        if item.note_id == own:
            _deny("VALIDATION_FAILED", "memory_note_relation_self", "条目不能和自己建立关系。", 422)
        if (item.type, item.note_id) in seen:
            continue
        seen.add((item.type, item.note_id))
        note = session.get(MemoryNote, item.note_id)
        if note is None or note.owner_id != owner_id or session.scalar(select(
                MemoryNoteDeletion.id).where(MemoryNoteDeletion.note_id == item.note_id)):
            _deny("NOT_FOUND", "memory_note_relation_unknown",
                  "关联的条目不存在，或不属于你本人。", 404)
        relations.append({"type": item.type, "note_id": str(item.note_id)})
    return relations


def evidence_view(session, version):
    result = []
    for link in version.evidence or []:
        found = _source(session, version.owner_id, version.tenant_id, link["source_type"],
                        link.get("source_kind"), UUID(link["source_id"]))
        result.append({
            "source_type": link["source_type"], "source_kind": link.get("source_kind"),
            "source_id": link["source_id"], "source_version": link.get("source_version"),
            "locator": link.get("locator") or {}, "stance": link["stance"],
            "quoted": bool(link.get("quote_sha256")), "readable": found is not None,
            "title": found[2] if found else None,
            "updated": bool(found and link.get("source_version") is not None
                            and found[1] != link["source_version"]),
        })
    return result


def relation_view(version, peers):
    """The note's relations with the owner's other notes that still exist (purged ones drop)."""
    def other(note_id, kind, direction):
        row = peers.get(note_id)
        return None if row is None else {
            "type": kind, "label": RELATION_LABELS[kind], "direction": direction,
            "note_id": str(note_id), "text": first_sentence(row.text, 40)}

    found = [other(UUID(item["note_id"]), item["type"], "out") for item in version.relations]
    for row in peers.values():
        if row.note_id == version.note_id:
            continue
        found += [other(row.note_id, item["type"], "in") for item in row.relations
                  if item["note_id"] == str(version.note_id)]
        if row.status == "replaced" and row.replaced_by == version.note_id:
            found.append(other(row.note_id, "supersedes", "out"))
    if version.status == "replaced" and version.replaced_by is not None:
        found.append(other(version.replaced_by, "superseded_by", "in"))
    return [item for item in found if item is not None]


def conflicted(rows):
    """Note ids marked 冲突 with another note in the same set."""
    present = {str(row.note_id) for row in rows}
    found = set()
    for row in rows:
        for item in row.relations:
            if item["type"] == "conflicts" and item["note_id"] in present:
                found.update({str(row.note_id), item["note_id"]})
    return found


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
    """pending (未生效) / active / replaced / expired / stale (可能过期) / unavailable (范围不可读).

    Valid time decides: a version is in effect from ``valid_from`` until ``valid_until``.
    A ``replaced`` version whose end is still ahead (the replacement starts later) is in
    effect until then; once it ends it reads as replaced, otherwise as expired.
    """
    now = now or clock_now()
    if version.valid_from > now:
        return "pending"
    if version.valid_until is not None and version.valid_until <= now:
        return "replaced" if version.status == "replaced" else "expired"
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


def _iso(value):
    return value.isoformat() if value else None


def peers_of(session, owner_id):
    return {row.note_id: row for row in _latest_versions(session, owner_id)}


def view(session, version, *, current=None, peers=None):
    if peers is None:
        peers = peers_of(session, version.owner_id)
    value = {
        "note_id": str(version.note_id),
        "revision": version.revision,
        "kind": version.kind,
        "kind_label": KIND_LABELS[version.kind],
        "text": version.text,
        "scope": scope_view(session, version),
        "state": current or state(session, version),
        "valid_until": _iso(version.valid_until),
        "confirmed_at": version.created_at.isoformat(),
        "origin": version.origin,
        "replaced_by": str(version.replaced_by) if version.replaced_by else None,
        # Unified item contract (§5.7).
        "occurred_at": _iso(version.occurred_at),
        "valid_from": version.valid_from.isoformat(),
        "confirmation": version.confirmation,
        "confirmation_label": CONFIRMATION_LABELS[version.confirmation],
        "evidence": evidence_view(session, version),
        "relations": relation_view(version, peers),
    }
    if version.kind == "alias":
        value["alias"] = {"term": version.alias_term, "means": means(session, version)}
    return value


def active_count(session, owner_id):
    return sum(1 for row in _latest_versions(session, owner_id) if row.status == "active")


def listing(session, ctx):
    from . import policy

    rows = _latest_versions(session, ctx.requester_id)
    peers = {row.note_id: row for row in rows}
    notes = [view(session, row, peers=peers) for row in rows]
    order = {"active": 0, "stale": 1, "pending": 2, "unavailable": 3, "expired": 4,
             "replaced": 5}
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
        "confirmation_label": CONFIRMATION_LABELS[CONFIRMATION],
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
    peers = peers_of(session, ctx.requester_id)
    return {"version": VERSION, "note_id": str(note_id),
            "versions": [view(session, row, current="history" if index else None, peers=peers)
                         for index, row in enumerate(rows)]}


# ---------------------------------------------------------------------------
# Deterministic conflict detection (P86 第 4 项).

def words(value):
    from pdos_next.agent.enterprise_search.tokenizer import analyze_query

    parsed = analyze_query(value)
    return {term for term in parsed["terms"] if len(term) >= 2} | set(parsed["codes"])


def _overlapping_scope(left_kind, left_id, right_kind, right_id):
    return "global" in {left_kind, right_kind} or (left_kind, left_id) == (right_kind, right_id)


def _overlapping_time(values, row, stamp):
    """Two notes can only contradict each other while both are in effect (valid time)."""
    begins = values.get("valid_from") or stamp
    ends = values.get("valid_until")
    return (ends is None or row.valid_from < ends) and (
        row.valid_until is None or begins < row.valid_until)


def similar(session, owner_id, values, *, exclude=(), stamp=None):
    """Active notes that look like duplicates or contradictions of a draft."""
    stamp = stamp or clock_now()
    draft_words = words(values["text"] + " " + (values.get("alias_term") or ""))
    found = []
    for row in _latest_versions(session, owner_id):
        if row.note_id in exclude or row.status != "active":
            continue
        if not _overlapping_scope(values["scope_kind"], values["scope_id"],
                                  row.scope_kind, row.scope_id):
            continue
        if not _overlapping_time(values, row, stamp):
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


def conflict_views(session, rows, values=None):
    """Each similar note, and what 替换 would do given the draft's start (P121 第 6 项)."""
    begins = (values or {}).get("valid_from") or clock_now()
    return [{**view(session, row), "reason": reason,
             "replace_effect": "history_only" if row.valid_from > begins else "replaces"}
            for row, reason in rows]


def conflicts(session, ctx, draft):
    from .policy import require_notes

    require_notes(session)
    values = normalized(session, draft, owner_id=ctx.requester_id, tenant_id=ctx.tenant_id)
    rows = similar(session, ctx.requester_id, values)
    return {"version": VERSION, "similarity": SIMILARITY,
            "conflicts": conflict_views(session, rows, values),
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
            replaced_by=None, candidate_id=None, request_key, fingerprint, stamp):
    # The record time is the same instant a defaulted 生效起点 takes (s0_0893 downgrade guard).
    row = MemoryNoteVersion(
        id=uuid4(), tenant_id=ctx.tenant_id, owner_id=ctx.requester_id, note_id=note_id,
        revision=revision, status=status, origin=origin, replaced_by=replaced_by,
        candidate_id=candidate_id, request_key=request_key, request_sha256=fingerprint,
        created_at=stamp, **{key: values[key] for key in CONTENT},
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
    values = {key: getattr(version, key) for key in CONTENT}
    values.update(changes)
    return values


def _merge_links(left, right):
    merged, seen = [], set()
    for link in [*left, *right]:
        key = (link["type"], link["note_id"]) if "type" in link else _link_key(link)
        if key not in seen:
            seen.add(key)
            merged.append(link)
    if len(merged) > NOTE_LINK_LIMIT:
        raise DomainError("VALIDATION_FAILED",
                          f"合并后的证据链接或关系超过 {NOTE_LINK_LIMIT} 条，请先删掉一些。", 422)
    return merged


def create(session, ctx, data, *, origin="manual", candidate_id=None):
    """Create a note; if similar notes exist the owner must have chosen how.

    替代按生效时间判断 (P121 第 6 项): 替换 ends each old note at the new note's start.
    When the new note starts before an old note it would replace, it is older
    information: it goes into history (ending where that old note starts) and the old
    note stays current.
    """
    from .policy import require_notes

    require_notes(session)
    _lock(session, ctx)
    stamp = clock_now()
    values = normalized(session, data.note, owner_id=ctx.requester_id, tenant_id=ctx.tenant_id,
                        stamp=stamp)
    fingerprint = digest({"op": "create", "values": values, "candidate": candidate_id,
                          "conflict": data.conflict.model_dump(mode="json")
                          if data.conflict else None})
    replay = _replay(session, ctx, data.request_key, fingerprint)
    if replay is not None:
        return created_view(session, replay.note_id)
    values["valid_from"] = start(values, None, stamp)
    found = similar(session, ctx.requester_id, values, stamp=stamp)
    choice = data.conflict
    chosen = dict(zip(choice.note_ids, choice.expected_revisions, strict=True)) if choice else {}
    if found and choice is None:
        raise DomainError(
            "VERSION_CONFLICT", "已有相似或矛盾的旧条目，请选择合并、替换或都保留。",
            detail={"reason_key": "memory_conflict_unresolved",
                    "conflicts": conflict_views(session, found, values)},
        )
    current = {}
    for note_id, revision in chosen.items():
        _note(session, ctx, note_id)
        row = _latest(session, note_id)
        if row is None or row.revision != revision or row.status != "active":
            raise DomainError("VERSION_CONFLICT", "旧条目已变化，请刷新后再选。")
        current[note_id] = row
    from .suppression import lift

    lift(session, ctx, values)  # The owner confirms it again: forgetting no longer applies.
    if choice and choice.resolution == "merge":
        (note_id, revision), = chosen.items()
        target = current[note_id]
        merged = _bounded(choice.merged_text, TEXT_LIMIT, "合并后的内容")
        base = values if target.kind == "alias" and values["kind"] == "alias" else _copy(
            target, valid_until=values["valid_until"])
        # 合并 rewrites the old note: its start follows the revision rule (start given, or
        # now for a note in effect); links of both are kept.
        merged_values = {
            **base, "text": merged,
            "valid_from": start({"valid_from": as_utc(data.note.valid_from)}, target, stamp),
            "occurred_at": values["occurred_at"] or target.occurred_at,
            "evidence": _merge_links(target.evidence, values["evidence"]),
            "relations": [item for item in _merge_links(target.relations, values["relations"])
                          if item["note_id"] != str(note_id)],
        }
        _check_start(merged_values, target, stamp)
        _append(session, ctx, note_id, revision + 1, merged_values, origin="merge",
                candidate_id=candidate_id, request_key=data.request_key,
                fingerprint=fingerprint, stamp=stamp)
        return created_view(session, note_id, resolution="merge")
    replacing = choice is not None and choice.resolution == "replace"
    later = [row for row in current.values() if row.valid_from > values["valid_from"]]
    backfill = replacing and bool(later)
    if not backfill and active_count(session, ctx.requester_id) - (
        len(chosen) if replacing else 0
    ) >= NOTE_LIMIT:
        raise DomainError("VALIDATION_FAILED",
                          f"记忆条目最多 {NOTE_LIMIT} 条，请先删除或合并旧条目。",
                          422, detail={"reason_key": "memory_note_limit"})
    note = MemoryNote(id=uuid4(), tenant_id=ctx.tenant_id, owner_id=ctx.requester_id)
    session.add(note)
    session.flush()
    if backfill:
        # 补录: in effect from its own start until the earliest old note it predates.
        first = min(later, key=lambda row: row.valid_from)
        ends = min(values["valid_until"] or first.valid_from, first.valid_from)
        _append(session, ctx, note.id, 1, {**values, "valid_until": ends}, status="replaced",
                origin=origin, replaced_by=first.note_id, candidate_id=candidate_id,
                request_key=data.request_key, fingerprint=fingerprint, stamp=stamp)
        return created_view(session, note.id, resolution="replace", effect="history_only")
    _append(session, ctx, note.id, 1, values, origin=origin, candidate_id=candidate_id,
            request_key=data.request_key, fingerprint=fingerprint, stamp=stamp)
    if replacing:
        begins = values["valid_from"]
        for note_id, revision in chosen.items():
            row = current[note_id]
            # The old note stays in effect until the new one starts (which may be ahead).
            _append(session, ctx, note_id, revision + 1,
                    _copy(row, valid_until=min(row.valid_until or begins, begins)),
                    status="replaced", origin=row.origin, replaced_by=note.id,
                    request_key=data.request_key, fingerprint=fingerprint, stamp=stamp)
    return created_view(session, note.id, resolution=choice.resolution if choice else None,
                        effect="replaces" if replacing else None)


def created_view(session, note_id, *, resolution=None, effect=None):
    value = {"version": VERSION, "note": view(session, _latest(session, note_id)),
             "resolution": resolution}
    if effect is not None:
        value["effect"] = effect
        if effect == "history_only":
            value["note_text"] = "这条的生效起点早于现有条目，只记入历史，没有替换现有条目。"
    return value


def _check_start(values, prior, stamp):
    """A note already in effect is not moved to a later start: that is a new note."""
    if prior.valid_from <= stamp and values["valid_from"] > stamp:
        raise DomainError(
            "VALIDATION_FAILED",
            "这条记忆已经生效；要从将来某天起换一种说法，请新建一条，并选择替换这条。", 422,
            detail={"reason_key": "memory_note_future_start"})


def revise(session, ctx, note_id, data):
    from .policy import require_notes

    require_notes(session)
    _lock(session, ctx)
    _note(session, ctx, note_id)
    current = _latest(session, note_id)
    stamp = clock_now()
    values = normalized(session, data.note, owner_id=ctx.requester_id, tenant_id=ctx.tenant_id,
                        prior=current, stamp=stamp)
    fingerprint = digest({"op": "revise", "note_id": note_id, "values": values,
                          "expected": data.expected_revision})
    replay = _replay(session, ctx, data.request_key, fingerprint)
    if replay is not None:
        return created_view(session, replay.note_id)
    if current.revision != data.expected_revision:
        raise DomainError("VERSION_CONFLICT", "这条记忆已变化，请刷新后再改。")
    if current.status != "active":
        raise DomainError("VERSION_CONFLICT", "已替换的条目只能查看或删除。")
    values["valid_from"] = start(values, current, stamp)
    _check_start(values, current, stamp)
    _append(session, ctx, note_id, current.revision + 1, values, origin=current.origin,
            request_key=data.request_key, fingerprint=fingerprint, stamp=stamp)
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
    now = now or clock_now()
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
