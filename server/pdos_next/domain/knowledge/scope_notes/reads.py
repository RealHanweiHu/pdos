"""Reading scope notes: audience, computed state, zone, views (M2b; P87, P121 第 3 项).

Everything is read under the reader's own row-level security. A note whose
attached object, subject or formal object the reader cannot read now is not
returned and nothing says it exists (target architecture §5.9). ``待复核`` and
``对象已更新`` are computed when read, never stored: a note past its review date
or pointing at an older object version stays usable but drops to the background
zone with a label (P87 第 4 项). Only 约定 can sit in the constraint zone.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from pdos_next.core.models import Category, Grant, Principal, Product
from pdos_next.errors import DomainError

from .models import ScopeNote, ScopeNoteEvidence, ScopeNoteRelation, ScopeNoteVersion

VERSION = "scope-notes/v1"
REVIEW_DAYS = 90  # P87 第 4 项 缺省 90 天; the tenant setting is a registered remainder.
KIND_LABELS = {"convention": "约定", "concern": "关注点", "decision_context": "决策背景",
               "observation": "观察"}
EPISTEMIC_LABELS = {"stated": "有人这样说", "verified": "已核实", "inferred": "推断",
                    "disputed": "有争议"}
CONFIRMATION_LABELS = {"discussion": "讨论", "proposed": "提议", "member_confirmed": "成员确认",
                       "formal_linked": "已关联正式记录"}
GENERATED_LABELS = {"human": "成员填写", "xiaopai_drafted": "小Pai 起草，成员确认",
                    "xiaopai": "小Pai 记录，未核实"}
ANCHOR_LABELS = {"category": "品类", "product": "产品", "proposal": "提案", "project": "项目"}
FACT_POLICY = ("团队备忘是成员确认或小Pai 记录的约定、关注点、决策背景和观察，不是业务事实，"
               "不能作为工程判据、批准依据或回答依据引用；与业务数据冲突时以业务数据为准。")
DEGRADING = frozenset({"review_due", "object_updated", "disputed"})
ORDER = {"active": 0, "expired": 1, "superseded": 2, "retired": 3, "withdrawn": 4}


def deny(code, key, message, status=409, **detail):
    raise DomainError(code, message, status, detail={"reason_key": key, **detail})


def as_utc(value):
    return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Objects a note is attached to or points at: read now, as this reader.

def _model(kind):
    from pdos_next.domain.categories.preproject.models import Proposal
    from pdos_next.domain.projects.models import Project

    return {"category": (Category, "name"), "product": (Product, "name"),
            "proposal": (Proposal, "title"), "project": (Project, "name")}[kind]


def chain(kind, row):
    """(category, product, proposal, project) of an object of this kind."""
    if kind == "category":
        return row.id, None, None, None
    if kind == "product":
        return row.category_id, row.id, None, None
    if kind == "proposal":
        return row.category_id, None, row.id, None
    return row.category_id, row.product_id, None, row.id


def is_open(s, tenant_id, category_id, product_id, proposal_id, project_id):
    return bool(s.scalar(
        text("SELECT public.scope_note_open(:t,:c,:product,:proposal,:project)"),
        {"t": tenant_id, "c": category_id, "product": product_id, "proposal": proposal_id,
         "project": project_id},
    ))


def resolve(s, tenant_id, kind, identity):
    """The object as this reader may read it now, or None."""
    cache = s.info.setdefault("scope_note_objects", {})
    key = (s.get_transaction(), tenant_id, kind, identity)
    if key in cache:
        return cache[key]
    model, title = _model(kind)
    row = s.scalar(select(model).where(model.tenant_id == tenant_id, model.id == identity))
    value = None
    if row is not None:
        category_id, product_id, proposal_id, project_id = chain(kind, row)
        if is_open(s, tenant_id, category_id, product_id, proposal_id, project_id):
            value = {
                "kind": kind, "id": row.id, "title": getattr(row, title),
                "revision": row.revision, "owner_id": row.owner_id,
                "category_id": category_id, "product_id": product_id,
                "proposal_id": proposal_id, "project_id": project_id,
                "visibility": getattr(row, "effective_visibility", None)
                or getattr(row, "visibility", "category"),
            }
    cache[key] = value
    return value


def formal(s, tenant_id, kind, identity):
    """A formal object: one of the four objects, or a G0 decision (no own revision)."""
    if kind != "proposal_decision":
        return resolve(s, tenant_id, kind, identity)
    from pdos_next.domain.categories.preproject.models import ProposalDecision

    row = s.scalar(select(ProposalDecision).where(
        ProposalDecision.tenant_id == tenant_id, ProposalDecision.id == identity))
    if row is None:
        return None
    owner = resolve(s, tenant_id, "proposal", row.proposal_id)
    if owner is None:
        return None
    return {"kind": kind, "id": row.id, "title": f"{owner['title']} 的 G0 决定", "revision": 1,
            "category_id": row.category_id, "product_id": None,
            "proposal_id": row.proposal_id, "project_id": None, "owner_id": row.decided_by}


def anchor_customers(s, tenant_id, anchor):
    """Customer identities the attached proposal or project already carries (P87 第 9 项)."""
    from pdos_next.domain.categories.preproject.models import Proposal, ProposalDecision
    from pdos_next.domain.projects.models import Project

    proposal_id = anchor["proposal_id"]
    if anchor["kind"] == "project":
        decision = s.scalar(select(Project.g0_decision_id).where(Project.id == anchor["id"]))
        proposal_id = s.scalar(select(ProposalDecision.proposal_id).where(
            ProposalDecision.id == decision)) if decision else None
    if proposal_id is None:
        return None
    values = s.scalar(select(Proposal.customer_identities).where(
        Proposal.tenant_id == tenant_id, Proposal.id == proposal_id))
    return None if values is None else [str(value) for value in values]


def anchor_view(s, version):
    kind = version.anchor_kind
    identity = {"category": version.category_id, "product": version.product_id,
                "proposal": version.proposal_id, "project": version.project_id}[kind]
    found = resolve(s, version.tenant_id, kind, identity)
    return {"kind": kind, "kind_label": ANCHOR_LABELS[kind], "id": str(identity),
            "title": found["title"] if found else None}, found


# ---------------------------------------------------------------------------
# Versions.

def latest(s, note_ids):
    """Latest readable version per note."""
    if not note_ids:
        return {}
    rows = s.scalars(select(ScopeNoteVersion).where(ScopeNoteVersion.note_id.in_(list(note_ids)))
                     .order_by(ScopeNoteVersion.note_id, ScopeNoteVersion.revision.desc()))
    found = {}
    for row in rows:
        found.setdefault(row.note_id, row)
    return found


def in_scope(s, tenant_id, *, category_id, product_id=None, proposal_id=None, project_id=None,
             anchors=("category", "product", "proposal", "project")):
    """Latest versions of notes attached on this scope chain (category → … → leaf)."""
    from sqlalchemy import and_, or_

    wanted = []
    if "category" in anchors:
        wanted.append(ScopeNote.anchor_kind == "category")
    for kind, column, value in (("product", ScopeNote.product_id, product_id),
                                ("proposal", ScopeNote.proposal_id, proposal_id),
                                ("project", ScopeNote.project_id, project_id)):
        if kind in anchors and value is not None:
            wanted.append(and_(ScopeNote.anchor_kind == kind, column == value))
    if not wanted:
        return []
    ids = s.scalars(select(ScopeNote.id).where(
        ScopeNote.tenant_id == tenant_id, ScopeNote.category_id == category_id, or_(*wanted)))
    return list(latest(s, list(ids)).values())


def evidence(s, note_id):
    """Evidence links of a note that were not taken back."""
    rows = s.scalars(select(ScopeNoteEvidence).where(ScopeNoteEvidence.note_id == note_id)
                     .order_by(ScopeNoteEvidence.created_at, ScopeNoteEvidence.id)).all()
    retracted = {row.retracts_id for row in rows if row.retracts_id is not None}
    return [row for row in rows if row.retracts_id is None and row.id not in retracted]


def relations(s, note_id):
    from sqlalchemy import or_

    return s.scalars(select(ScopeNoteRelation).where(or_(
        ScopeNoteRelation.from_note_id == note_id, ScopeNoteRelation.to_note_id == note_id,
    )).order_by(ScopeNoteRelation.created_at, ScopeNoteRelation.id)).all()


def flags(s, version, *, now, links=None):
    """Computed labels, or None when the note must stay hidden from this reader."""
    found = []
    for kind, identity, recorded in (
        (version.subject_kind, version.subject_id, version.subject_version),
        (version.formal_kind, version.formal_id, version.formal_version),
    ):
        if identity is None:
            continue
        current = formal(s, version.tenant_id, kind, identity)
        if current is None:
            return None
        if current["revision"] != recorded and "object_updated" not in found:
            found.append("object_updated")
    if version.review_due_at <= now:
        found.append("review_due")
    links = relations(s, version.note_id) if links is None else links
    conflicting = [row.to_note_id if row.from_note_id == version.note_id else row.from_note_id
                   for row in links if row.type == "conflicts"]
    if version.epistemic == "disputed" or any(
        row.lifecycle == "active" for row in latest(s, conflicting).values()
    ):
        found.append("disputed")
    if version.kind == "decision_context" and version.formal_id is None:
        found.append("no_formal_decision")
    return found


def state(version, *, now):
    if version.lifecycle != "active":
        return version.lifecycle
    if version.valid_to is not None and version.valid_to <= now:
        return "expired"
    return "active"


def zone(version, current, found):
    """Only an undegraded, active 约定 constrains; everything else is background."""
    if current == "active" and version.kind == "convention" and not DEGRADING & set(found):
        return "constraint"
    return "background"


def person(s, tenant_id, identity):
    if identity is None:
        return None
    row = s.scalar(select(Principal).where(Principal.tenant_id == tenant_id,
                                           Principal.id == identity))
    if row is None:
        return {"id": str(identity), "name": None, "kind": None}
    return {"id": str(row.id), "name": "小Pai" if row.kind == "agent" else row.name,
            "kind": row.kind}


def departed(s, version, author_id, anchor):
    """Whether the author left or was moved out (P87 第 5 项). 小Pai is never an author."""
    row = s.scalar(select(Principal).where(Principal.tenant_id == version.tenant_id,
                                           Principal.id == author_id))
    if row is None or row.kind != "human":
        return False
    if not row.active:
        return True
    grant = s.scalar(select(Grant).where(
        Grant.tenant_id == version.tenant_id, Grant.category_id == version.category_id,
        Grant.principal_id == author_id))
    if grant is None or (grant.expires_at is not None and grant.expires_at <= datetime.now(UTC)):
        return True
    if version.anchor_kind == "project" and anchor is not None and author_id != anchor[
            "owner_id"]:
        from pdos_next.domain.projects.team.models import ProjectMember

        stints = s.execute(select(ProjectMember.left_at).where(
            ProjectMember.tenant_id == version.tenant_id,
            ProjectMember.project_id == version.project_id,
            ProjectMember.principal_id == author_id)).all()
        return bool(stints) and all(left is not None for (left,) in stints)
    return False


def _reference(s, tenant_id, kind, identity, recorded):
    if identity is None:
        return None
    current = formal(s, tenant_id, kind, identity)
    return {"kind": kind, "id": str(identity), "version": recorded,
            "title": current["title"] if current else None,
            "updated": bool(current and current["revision"] != recorded)}


def evidence_view(row):
    return {"id": str(row.id), "source_type": row.source_type, "source_kind": row.source_kind,
            "source_id": str(row.source_id), "source_version": row.source_version,
            "locator": row.locator, "has_quote": row.quote_sha256 is not None,
            "stance": row.stance, "recorded_at": row.created_at.isoformat(),
            "by_xiaopai": row.run_id is not None}


def view(s, version, *, now=None, author_id=None, detail=False):
    """The reader's view of one version, or None when it must stay hidden."""
    now = now or datetime.now(UTC)
    anchor, found = anchor_view(s, version)
    if found is None:
        return None
    links = relations(s, version.note_id)
    labels = flags(s, version, now=now, links=links)
    if labels is None:
        return None
    current = state(version, now=now)
    if author_id is None:
        author_id = s.scalar(select(ScopeNote.author_id).where(ScopeNote.id == version.note_id))
    gone = departed(s, version, author_id, found)
    value = {
        "note_id": str(version.note_id),
        "revision": version.revision,
        "kind": version.kind,
        "kind_label": KIND_LABELS[version.kind],
        "statement": version.statement,
        "anchor": anchor,
        "state": current,
        "flags": labels,
        "zone": zone(version, current, labels),
        "epistemic": version.epistemic,
        "epistemic_label": EPISTEMIC_LABELS[version.epistemic],
        "confirmation": version.confirmation,
        "confirmation_label": CONFIRMATION_LABELS[version.confirmation],
        "generated_by": version.generated_by,
        "generated_label": GENERATED_LABELS[version.generated_by],
        "source_authority": version.source_authority,
        "subject": _reference(s, version.tenant_id, version.subject_kind, version.subject_id,
                              version.subject_version),
        "formal": _reference(s, version.tenant_id, version.formal_kind, version.formal_id,
                             version.formal_version),
        "tags": {"customer": version.customer_identity, "stage": version.stage,
                 "topic": version.topic},
        "sensitivity": version.sensitivity,
        "pinned": version.pinned,
        "occurred_at": version.occurred_at.isoformat() if version.occurred_at else None,
        "valid_from": version.valid_from.isoformat(),
        "valid_to": version.valid_to.isoformat() if version.valid_to else None,
        "review_due_at": version.review_due_at.isoformat(),
        "recorded_at": version.created_at.isoformat(),
        "action": version.action,
        "reason": version.reason,
        "author": {**(person(s, version.tenant_id, author_id) or {}), "departed": gone},
        "confirmed_by": person(s, version.tenant_id, version.confirmed_by),
        # 作者离开后复核责任转给对象负责人 (P87 第 5 项).
        "review_owner": person(s, version.tenant_id, found["owner_id"] if gone or (
            version.generated_by == "xiaopai") else author_id),
        "run_id": str(version.run_id) if version.run_id else None,
        "receipt_id": str(version.receipt_id),
        "evidence_count": len(evidence(s, version.note_id)),
        "relations": [
            {"type": row.type,
             "direction": "from" if row.from_note_id == version.note_id else "to",
             "note_id": str(row.to_note_id if row.from_note_id == version.note_id
                            else row.from_note_id)}
            for row in links
        ],
    }
    if detail:
        value["evidence"] = [evidence_view(row) for row in evidence(s, version.note_id)]
    return value


def sort_key(item):
    return (ORDER[item["state"]], not item["pinned"], item["zone"] != "constraint",
            -datetime.fromisoformat(item["recorded_at"]).timestamp(), item["note_id"])


def can_write(s, tenant_id, category_id):
    return bool(s.scalar(text("SELECT public.category_access(:t,:c,true)"),
                         {"t": tenant_id, "c": category_id}))


def audience(s, anchor):
    """Who reads a note attached here, in words, for the confirmation card (§14.5)."""
    label = ANCHOR_LABELS[anchor["kind"]]
    if anchor["kind"] == "category" or anchor["visibility"] == "category":
        return {"kind": "category",
                "text": f"能读这个{label}的品类成员都能看到，也会进入他们的小Pai 上下文。"}
    return {"kind": "restricted",
            "text": f"只有这个{label}现有的受众能看到（负责人和被加入的成员）；"
                    "受众收窄时备忘随之收窄。"}


def listing(s, ctx, kind, identity, *, include_history=False):
    anchor = resolve(s, ctx.tenant_id, kind, identity)
    if anchor is None:
        deny("FORBIDDEN_SCOPE", "scope_note_anchor_unreadable", "所选范围当前不可读。", 403)
    now = datetime.now(UTC)
    rows = in_scope(s, ctx.tenant_id, category_id=anchor["category_id"],
                    product_id=anchor["product_id"], proposal_id=anchor["proposal_id"],
                    project_id=anchor["project_id"], anchors=(kind,))
    items = [item for item in (view(s, row, now=now) for row in rows) if item is not None]
    items.sort(key=sort_key)
    shown = [item for item in items if include_history or item["state"] in {"active", "expired"}]
    return {
        "version": VERSION,
        "anchor": {"kind": kind, "kind_label": ANCHOR_LABELS[kind], "id": str(identity),
                   "title": anchor["title"], "category_id": str(anchor["category_id"]),
                   "product_id": str(anchor["product_id"]) if anchor["product_id"] else None},
        "can_write": can_write(s, ctx.tenant_id, anchor["category_id"]),
        "audience": audience(s, anchor),
        "customers": anchor_customers(s, ctx.tenant_id, anchor),
        "statement_limit": 300,
        "review_days": REVIEW_DAYS,
        "notes": shown,
        "inactive_count": sum(1 for item in items if item["state"] not in {"active", "expired"}),
        "note": FACT_POLICY,
    }


def history(s, ctx, note_id):
    rows = s.scalars(select(ScopeNoteVersion).where(
        ScopeNoteVersion.tenant_id == ctx.tenant_id, ScopeNoteVersion.note_id == note_id,
    ).order_by(ScopeNoteVersion.revision.desc())).all()
    head = view(s, rows[0], detail=True) if rows else None
    if head is None:
        deny("NOT_FOUND", "scope_note_not_found", "这条备忘不存在，或当前不可读。", 404)
    versions = [
        {"revision": row.revision, "action": row.action, "lifecycle": row.lifecycle,
         "statement": row.statement, "epistemic_label": EPISTEMIC_LABELS[row.epistemic],
         "confirmation_label": CONFIRMATION_LABELS[row.confirmation],
         "generated_label": GENERATED_LABELS[row.generated_by], "reason": row.reason,
         "recorded_at": row.created_at.isoformat(), "valid_from": row.valid_from.isoformat(),
         "valid_to": row.valid_to.isoformat() if row.valid_to else None,
         "by": person(s, ctx.tenant_id, row.writer_id), "receipt_id": str(row.receipt_id)}
        for row in rows
    ]
    return {"version": VERSION, "note": head, "versions": versions}


def review_due(now=None):
    return (now or datetime.now(UTC)) + timedelta(days=REVIEW_DAYS)
