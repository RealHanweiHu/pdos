"""What a person can link to a scope note from the page (D509; P121 第 6 项).

The page offers evidence sources and formal objects from this list; it does not
decide permissions itself. Everything here is read under the reader's own
row-level security, so the list shows only what they can read now, and the
command (``scope_note.save`` / ``scope_note.observation.record``) checks each
link again when it is previewed and when it is confirmed. Titles only: no
original text, quote, Run answer or receipt payload leaves this module.
"""

from sqlalchemy import or_, select

from pdos_next.errors import DomainError

from . import reads

VERSION = "scope-note-sources/v1"
LIMIT = 10
SOURCE_LABELS = {"business_object": "业务对象", "proposal_decision": "G0 决定", "run": "小Pai 运行",
                 "discussion": "项目讨论", "receipt": "办理回执", "original": "资料原件"}
FORMAL_KINDS = ("category", "product", "proposal", "project", "proposal_decision")


def _goal(text):
    from pdos_next.agent.kernel.work_state import PAGE_MATERIAL_BOUNDARY

    words = " ".join((text or "").split(PAGE_MATERIAL_BOUNDARY)[0].split())
    return words[:60] + ("…" if len(words) > 60 else "")


def _when(value):
    return value.date().isoformat() if value else None


def title(s, tenant_id, source_type, source_kind, source_id):
    """The source's title as this reader may read it now, or None."""
    from pdos_next.agent.kernel.models import AgentRun
    from pdos_next.core.models import Artifact, Receipt
    from pdos_next.domain.projects.discussions.models import DiscussionThread

    if source_type == "business_object":
        found = reads.formal(s, tenant_id, source_kind, source_id)
        return found["title"] if found else None
    model = {"run": AgentRun, "discussion": DiscussionThread, "receipt": Receipt,
             "original": Artifact}[source_type]
    row = s.scalar(select(model).where(model.tenant_id == tenant_id, model.id == source_id))
    if row is None:
        return None
    if source_type == "run":
        return f"{_when(row.created_at)} {_goal(row.goal)}".strip()
    if source_type == "discussion":
        return row.title or "对象评论"
    if source_type == "receipt":
        return f"{row.operation} · {_when(row.created_at)}"
    return row.title


def _chain(s, tenant_id, anchor):
    """The attached object and the objects above it, as this reader may read them."""
    found = []
    for kind in ("project", "proposal", "product", "category"):
        identity = anchor[f"{kind}_id"]
        if identity is None:
            continue
        value = reads.resolve(s, tenant_id, kind, identity)
        if value is not None:
            found.append(value)
    return found


def _decisions(s, tenant_id, anchor):
    from pdos_next.domain.categories.preproject.models import ProposalDecision
    from pdos_next.domain.projects.models import Project

    ids = []
    if anchor["kind"] == "project":
        decided = s.scalar(select(Project.g0_decision_id).where(
            Project.tenant_id == tenant_id, Project.id == anchor["id"]))
        ids = [decided] if decided else []
    elif anchor["kind"] == "proposal":
        ids = list(s.scalars(select(ProposalDecision.id).where(
            ProposalDecision.tenant_id == tenant_id,
            ProposalDecision.proposal_id == anchor["id"],
        ).order_by(ProposalDecision.created_at.desc()).limit(LIMIT)))
    return [value for value in (reads.formal(s, tenant_id, "proposal_decision", identity)
                                for identity in ids) if value is not None]


def _object_option(value):
    kind = value["kind"]
    return {"source_type": "business_object", "source_kind": kind, "source_id": str(value["id"]),
            "type_label": SOURCE_LABELS["proposal_decision"] if kind == "proposal_decision"
            else reads.ANCHOR_LABELS[kind],
            "title": value["title"], "version": value["revision"]}


def options(s, ctx, kind, identity):
    """Evidence sources and formal objects for a note attached here (titles only)."""
    from pdos_next.agent.kernel.models import AgentRun
    from pdos_next.core.models import Artifact, Receipt
    from pdos_next.domain.projects.discussions.models import DiscussionThread

    anchor = reads.resolve(s, ctx.tenant_id, kind, identity)
    if anchor is None:
        raise DomainError("FORBIDDEN_SCOPE", "所选范围当前不可读。", 403,
                          detail={"reason_key": "scope_note_anchor_unreadable"})
    objects = [_object_option(value) for value in (
        *_chain(s, ctx.tenant_id, anchor), *_decisions(s, ctx.tenant_id, anchor))]
    ids = [value["id"] for value in _chain(s, ctx.tenant_id, anchor)]
    runs = s.scalars(select(AgentRun).where(
        AgentRun.tenant_id == ctx.tenant_id, AgentRun.category_id == anchor["category_id"],
        AgentRun.requester_id == ctx.requester_id, AgentRun.reverted_at.is_(None),
        AgentRun.state.in_(("completed", "partial")),
        *[getattr(AgentRun, f"{level}_id") == anchor[f"{level}_id"]
          for level in ("product", "proposal", "project") if anchor[f"{level}_id"] is not None],
    ).order_by(AgentRun.created_at.desc()).limit(LIMIT)).all()
    threads = s.scalars(select(DiscussionThread).where(
        DiscussionThread.tenant_id == ctx.tenant_id,
        DiscussionThread.project_id == anchor["project_id"],
    ).order_by(DiscussionThread.created_at.desc()).limit(LIMIT)).all() if (
        anchor["project_id"] is not None) else []
    # Receipts of the objects on this chain, of its G0 decision and of the proposal
    # that decision closed (a project's own source proposal).
    decided = _decisions(s, ctx.tenant_id, anchor)
    subjects = {*ids, *(value["id"] for value in decided),
                *(value["proposal_id"] for value in decided)}
    receipts = s.scalars(select(Receipt).where(
        Receipt.tenant_id == ctx.tenant_id, Receipt.category_id == anchor["category_id"],
        Receipt.subject_id.in_(list(subjects)),
    ).order_by(Receipt.created_at.desc()).limit(LIMIT)).all()
    product = anchor["product_id"]
    originals = s.scalars(select(Artifact).where(
        Artifact.tenant_id == ctx.tenant_id, Artifact.category_id == anchor["category_id"],
        Artifact.status == "active",
        # A product-level scope also offers the category's own materials.
        *([or_(Artifact.product_id == product, Artifact.product_id.is_(None))]
          if product is not None else []),
    ).order_by(Artifact.created_at.desc()).limit(LIMIT)).all()
    sources = [
        *objects,
        *({"source_type": "run", "source_kind": None, "source_id": str(row.id),
           "type_label": SOURCE_LABELS["run"], "title": title(s, ctx.tenant_id, "run", None,
                                                              row.id), "version": None}
          for row in runs),
        *({"source_type": "discussion", "source_kind": None, "source_id": str(row.id),
           "type_label": SOURCE_LABELS["discussion"], "title": row.title or "对象评论",
           "version": None} for row in threads),
        *({"source_type": "receipt", "source_kind": None, "source_id": str(row.id),
           "type_label": SOURCE_LABELS["receipt"],
           "title": f"{row.operation} · {_when(row.created_at)}",
           "version": row.subject_revision} for row in receipts),
        *({"source_type": "original", "source_kind": None, "source_id": str(row.id),
           "type_label": SOURCE_LABELS["original"], "title": row.title,
           "version": row.revision} for row in originals),
    ]
    return {
        "version": VERSION,
        "anchor": {"kind": kind, "id": str(identity), "title": anchor["title"]},
        "formal": [item for item in objects if item["source_kind"] in FORMAL_KINDS],
        "sources": sources,
        "note": "这里只列你现在能读到的对象；保存时服务器按当前权限逐条再核对。"
                "引文原文不保存，只存摘要，之后按读者自己的权限重新读取。",
    }
