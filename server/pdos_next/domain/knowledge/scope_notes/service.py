"""Scope-note commands in the shared atomic domain transaction (M2b).

The caller (``core.service.execute``) owns scope locks, category write access,
T0 qualification, the one confirmation and the common receipt. This module
decides what the command writes: the server binds the readable scope, object
versions, source authority, the confirmer and the review date; payload fields
never establish a permission or a state they are not entitled to.

P121 第 4 项: the AI writer identity reaches this module only through
``scope_note.observation.record`` executed inside its own qualified Run. It can
record a new unverified observation on that Run's own scope, or add evidence
links to an existing note there. Everything else is done by a named person.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select

from pdos_next.core.models import Artifact, Principal, Receipt
from pdos_next.core.service import command_digest, digest
from pdos_next.domain.categories.preproject.access import human

from . import reads
from .models import ScopeNote, ScopeNoteEvidence, ScopeNoteRelation, ScopeNoteVersion
from .reads import deny
from .schemas import OBSERVE, RETIRE, SAVE, SUBJECT, ObservePayload

RANK = {"xiaopai_generated": 0, "discussion": 1, "human_statement": 2, "original": 3,
        "verified_answer": 4, "published_rule": 5, "business_record": 6}
SOURCE_AUTHORITY = {"discussion": "discussion", "receipt": "business_record",
                    "original": "original", "business_object": "business_record", "run": None}
SIMILARITY = "scope-note-similarity/v1;jaccard>=0.34|shared>=2;same-anchor-or-category"
CONTENT = ("statement", "subject_kind", "subject_id", "subject_version", "customer_identity",
           "stage", "topic", "sensitivity", "epistemic", "confirmation", "formal_kind",
           "formal_id", "formal_version", "generated_by", "occurred_at", "valid_from",
           "valid_to", "review_due_at", "pinned", "confirmed_by", "run_id", "source_authority")


def requires_category_write(command):
    return True


def supports_confirmation(command):
    """A person can also record an observation or evidence, with one confirmation."""
    return command.operation == OBSERVE


def needs_confirmation(payload):
    return isinstance(payload, ObservePayload) and payload.confirmation_token is not None


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


@dataclass
class Plan:
    session: object
    transaction: object
    fingerprint: str
    primary: tuple  # (note_id, revision, lifecycle)
    visibility: str
    review: dict
    notes: list = field(default_factory=list)
    versions: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    relations: list = field(default_factory=list)
    result: dict = field(default_factory=dict)
    confirmation_id: object = None
    receipt_id: object = None
    writer: str = "human"
    used: bool = False


# ---------------------------------------------------------------------------
# Server-bound inputs.

def _writer(s, ctx):
    actor = s.get(Principal, ctx.actor_id)
    if actor is None or not actor.active:
        deny("FORBIDDEN_SCOPE", "scope_note_writer_inactive", "当前身份不可用。", 403)
    return actor.kind


def _run(s, ctx):
    from pdos_next.agent.kernel.models import AgentRun

    run = s.get(AgentRun, ctx.agent_run_id) if ctx.agent_run_id else None
    if run is None or run.tenant_id != ctx.tenant_id or run.category_id != ctx.category_id:
        deny("FORBIDDEN_SCOPE", "scope_note_run_unbound", "小Pai 写入须绑定服务器实际运行。", 403)
    return run


def drafted_run(s, ctx, command):
    """The requester's own Run that prefilled this command, from the server-issued key."""
    from pdos_next.agent.kernel.models import AgentRun

    parts = command.idempotency_key.split(":")
    if len(parts) != 5 or parts[0] != "agent" or parts[2] != "model" or (
        command.command_id != uuid5(NAMESPACE_URL, command.idempotency_key)
    ):
        return None
    try:
        run = s.get(AgentRun, UUID(parts[1]))
    except ValueError:
        return None
    if (run is None or run.tenant_id != ctx.tenant_id or run.category_id != ctx.category_id
            or run.requester_id != ctx.requester_id):
        return None
    return run


def _anchor(s, ctx, command, ref, *, run=None):
    found = reads.resolve(s, ctx.tenant_id, ref.kind, ref.id)
    if found is None or found["category_id"] != ctx.category_id:
        deny("FORBIDDEN_SCOPE", "scope_note_anchor_unreadable", "所选范围当前不可读。", 403)
    if command.product_id is not None and (
        found["kind"] == "proposal" or found["product_id"] not in (None, command.product_id)
    ):
        deny("FORBIDDEN_SCOPE", "scope_note_anchor_mismatch", "挂靠对象不在本次办理的型号范围内。",
             403)
    if run is not None and found["kind"] != "category" and found["id"] not in {
        run.product_id, run.proposal_id, getattr(run, "project_id", None),
    }:
        # 模型传参不作为政策事实: 小Pai writes only on its own Run's scope chain.
        deny("FORBIDDEN_SCOPE", "scope_note_outside_run", "小Pai 只能记在本次运行的范围上。", 403)
    return found


def _object(s, ctx, ref, *, formal=False):
    if ref is None:
        return None
    found = (reads.formal if formal else reads.resolve)(s, ctx.tenant_id, ref.kind, ref.id)
    if found is None or found["category_id"] != ctx.category_id:
        deny("FORBIDDEN_SCOPE", "scope_note_object_unreadable", "引用的对象当前不可读。", 403)
    return found


def _customer(s, ctx, anchor, customer):
    if customer is None:
        return None
    known = reads.anchor_customers(s, ctx.tenant_id, anchor)
    if anchor["kind"] == "proposal" and customer not in (known or []):
        deny("VALIDATION_FAILED", "scope_note_customer_unknown",
             "客户标签须是这个提案上已登记的客户标识。", 422)
    if anchor["kind"] == "project" and known and customer not in known:
        deny("VALIDATION_FAILED", "scope_note_customer_unknown",
             "客户标签须是这个项目来源提案上已登记的客户标识。", 422)
    return customer


def _evidence(s, ctx, items):
    """Each link is read now as the writer; the quote is reduced to a digest."""
    from pdos_next.agent.kernel.models import AgentRun
    from pdos_next.domain.projects.discussions.models import DiscussionThread

    rows, seen = [], set()
    for item in items:
        version = None
        if item.source_type == "business_object":
            found = _object(s, ctx, SimpleNamespace(kind=item.source_kind, id=item.source_id),
                            formal=True)
            root, version = found["id"], found["revision"]
        else:
            model = {"run": AgentRun, "discussion": DiscussionThread, "receipt": Receipt,
                     "original": Artifact}[item.source_type]
            row = s.get(model, item.source_id)
            if row is None or row.tenant_id != ctx.tenant_id or row.category_id != (
                    ctx.category_id):
                deny("FORBIDDEN_SCOPE", "scope_note_evidence_unreadable",
                     "证据来源当前不可读，或不在这个品类内。", 403)
            root = row.id
            if item.source_type == "receipt":
                root, version = row.subject_id, row.subject_revision
            elif item.source_type == "original":
                root, version = row.original_id or row.id, row.revision
        key = (item.source_type, item.source_id, digest(item.locator), item.stance)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "source_type": item.source_type, "source_kind": item.source_kind,
            "source_id": item.source_id, "source_version": version,
            "locator": dict(item.locator), "root_source_id": root, "stance": item.stance,
            "quote_sha256": digest(item.quote) if item.quote else None,
        })
    return rows


def authority(rows, *, by_xiaopai):
    """来源权威性 from the supporting links; never a payload field (§5.7)."""
    best = "xiaopai_generated" if by_xiaopai else "human_statement"
    for row in rows:
        value = SOURCE_AUTHORITY.get(row["source_type"]) if row["stance"] == "supports" else None
        if value is not None and RANK[value] > RANK[best]:
            best = value
    return best


def verifiable(rows):
    """§5.6.5: a published business record, or two independent root sources."""
    supports = [row for row in rows if row["stance"] == "supports" and row["source_type"] != "run"]
    return any(SOURCE_AUTHORITY[row["source_type"]] == "business_record" for row in supports) or (
        len({row["root_source_id"] for row in supports}) >= 2
    )


def _stored(rows):
    return [{"source_type": row.source_type, "source_id": row.source_id, "stance": row.stance,
             "root_source_id": row.root_source_id} for row in rows]


def claim_key(kind, anchor, subject, statement):
    return digest({"kind": kind, "anchor": [anchor["kind"], str(anchor["id"])],
                   "subject": [subject["kind"], str(subject["id"])] if subject else None,
                   "statement": "".join(statement.split()).casefold()})


def similar(s, ctx, anchor, statement, *, exclude=()):
    """Active notes on the same object or its category that read like this one."""
    from pdos_next.agent.memory.notes import words

    mine = words(statement)
    found = []
    for row in reads.in_scope(
        s, ctx.tenant_id, category_id=anchor["category_id"], product_id=anchor["product_id"],
        proposal_id=anchor["proposal_id"], project_id=anchor["project_id"],
        anchors=("category", anchor["kind"]),
    ):
        if row.note_id in exclude or reads.state(row, now=datetime.now(UTC)) != "active":
            continue
        other = words(row.statement)
        shared = mine & other
        if shared and (len(shared) >= 2 or len(shared) / len(mine | other) >= 0.34):
            found.append(row)
    return found


def _target(s, ctx, ref, *, action):
    """A note this person can read now, at exactly the revision they looked at."""
    row = reads.latest(s, [ref.id]).get(ref.id)
    if row is None or row.category_id != ctx.category_id or reads.view(s, row) is None:
        deny("NOT_FOUND", "scope_note_not_found", "这条备忘不存在，或当前不可读。", 404)
    if row.revision != ref.revision:
        deny("VERSION_CONFLICT", "scope_note_moved", f"这条备忘已变化，请刷新后再{action}。")
    if row.lifecycle != "active":
        deny("VERSION_CONFLICT", "scope_note_inactive", "已停用、撤回或被替代的备忘只能查看。")
    return row


def _copy(row, **changes):
    values = {name: getattr(row, name) for name in CONTENT}
    values.update(changes)
    return values


def _row(row, note, **values):
    """A new version of an existing note: same attachment and kind, new content."""
    return {"note_id": row.note_id, "revision": row.revision + 1,
            **{name: getattr(row, name) for name in (
                "category_id", "product_id", "proposal_id", "project_id", "anchor_kind", "kind")},
            **values}


def _first(note_id, anchor, kind, **values):
    return {"note_id": note_id, "revision": 1, "category_id": anchor["category_id"],
            "product_id": anchor["product_id"], "proposal_id": anchor["proposal_id"],
            "project_id": anchor["project_id"], "anchor_kind": anchor["kind"], "kind": kind,
            **values}


def _visibility(anchor):
    return "category" if anchor["kind"] == "category" or anchor["visibility"] == "category" else (
        "private")


def _similar_views(s, rows):
    return [item for item in (reads.view(s, row) for row in rows) if item is not None]


# ---------------------------------------------------------------------------
# Plans.

def _create(s, ctx, command, payload, *, kind, body, writer, run, drafted):
    now = datetime.now(UTC)
    by_xiaopai = writer == "agent"
    anchor = _anchor(s, ctx, command, payload.anchor, run=run if by_xiaopai else None)
    subject = _object(s, ctx, body.subject)
    formal = None if by_xiaopai else _object(s, ctx, getattr(body, "formal", None), formal=True)
    links = _evidence(s, ctx, payload.evidence)
    relations = [] if by_xiaopai else list(getattr(payload, "relations", ()))
    kept = set() if by_xiaopai else set(getattr(payload, "kept_similar", ()))
    targets = {item.note.id: _target(s, ctx, item.note, action="关联") for item in relations}
    key = claim_key(kind, anchor, subject, body.statement)
    note_id = uuid5(command.command_id, "scope-note")
    lookalike = similar(s, ctx, anchor, body.statement, exclude=set(targets) | kept)
    same = [row for row in lookalike if s.scalar(
        select(ScopeNote.claim_key).where(ScopeNote.id == row.note_id)) == key]
    if same:
        deny("VERSION_CONFLICT", "scope_note_duplicate",
             "同一条备忘已经存在；需要时给它补充证据，不重复记录。",
             existing=[{"note_id": str(row.note_id), "revision": row.revision} for row in same])
    if lookalike:
        deny("VERSION_CONFLICT", "scope_note_similar_unresolved",
             "已有相似的备忘：请改为给已有条目补充证据。" if by_xiaopai
             else "已有相似或矛盾的备忘，请选择替代、标为冲突，或都保留。",
             similarity=SIMILARITY, similar=_similar_views(s, lookalike))
    epistemic = ("inferred" if body.inferred else "stated") if isinstance(
        body, ObservePayload) else body.epistemic
    if epistemic == "verified" and not verifiable(links):
        deny("VALIDATION_FAILED", "scope_note_verified_requires_sources",
             "标为“已核实”须关联一条业务记录，或两个相互独立的来源；小Pai 的运行不算来源。", 422)
    valid_from = reads.as_utc(getattr(body, "valid_from", None)) or now
    valid_to = reads.as_utc(getattr(body, "valid_until", None))
    if valid_to is not None and valid_to <= max(valid_from, now):
        deny("VALIDATION_FAILED", "scope_note_validity", "失效时间须晚于生效时间和现在。", 422)
    occurred = reads.as_utc(body.occurred_at)
    if occurred is not None and occurred > now:
        deny("VALIDATION_FAILED", "scope_note_occurred", "事情发生的时间不能晚于现在。", 422)
    customer = _customer(s, ctx, anchor, body.customer)
    if by_xiaopai:
        generated, confirmation, confirmed_by, run_id = "xiaopai", "proposed", None, run.id
    else:
        generated = "xiaopai_drafted" if drafted is not None else "human"
        confirmation = "formal_linked" if formal else getattr(
            body, "confirmation", "member_confirmed")
        confirmed_by, run_id = ctx.actor_id, drafted.id if drafted is not None else None
    content = {
        "statement": body.statement,
        "subject_kind": subject["kind"] if subject else None,
        "subject_id": subject["id"] if subject else None,
        "subject_version": subject["revision"] if subject else None,
        "customer_identity": customer, "stage": body.stage, "topic": body.topic,
        "sensitivity": "customer_private" if customer else "normal",
        "source_authority": authority(links, by_xiaopai=by_xiaopai),
        "epistemic": epistemic, "confirmation": confirmation,
        "formal_kind": formal["kind"] if formal else None,
        "formal_id": formal["id"] if formal else None,
        "formal_version": formal["revision"] if formal else None,
        "generated_by": generated, "occurred_at": occurred, "valid_from": valid_from,
        "valid_to": valid_to, "review_due_at": reads.review_due(s, now),
        "pinned": bool(getattr(body, "pinned", False)), "confirmed_by": confirmed_by,
        "run_id": run_id,
    }
    # P121 第 6 项: 替代按生效时间判断; 补录的旧信息只进历史.
    supersedes = [targets[item.note.id] for item in relations if item.type == "supersedes"]
    later = [row for row in supersedes if row.valid_from > valid_from]
    action, lifecycle = "create", "active"
    versions, links_between = [], []
    if later:
        action, lifecycle = "backfill", "superseded"
        content["valid_to"] = min(row.valid_from for row in later)
        content["pinned"] = False
    for item in relations:
        target = targets[item.note.id]
        if item.type != "supersedes":
            links_between.append((note_id, target.note_id, item.type))
        elif later:
            if target in later:
                links_between.append((target.note_id, note_id, "supersedes"))
        else:
            links_between.append((note_id, target.note_id, "supersedes"))
            versions.append(_row(target, None, action="supersede", lifecycle="superseded",
                                 reason=None, origin={"superseded_by": str(note_id)},
                                 **_copy(target, valid_to=max(valid_from, target.valid_from),
                                         pinned=False)))
    origin = {"entry": "xiaopai" if by_xiaopai else "drafted" if drafted is not None else "page"}
    shared = getattr(payload, "shared_from_note", None)
    if shared is not None:
        from pdos_next.agent.memory.models import MemoryNote

        # 分享到项目 (P86 第 8 项): only the owner shares their own note, and only by
        # this explicit command; the team note is a new record that just names its origin.
        if s.scalar(select(MemoryNote.owner_id).where(MemoryNote.id == shared)) != ctx.actor_id:
            deny("FORBIDDEN_SCOPE", "scope_note_share_not_owner", "只能分享你本人的记忆条目。", 403)
        origin = {"entry": "personal_note", "personal_note_id": str(shared)}
    versions.insert(0, _first(note_id, anchor, kind, action=action, lifecycle=lifecycle,
                              reason=None, origin=origin, **content))
    review = {
        "operation": command.operation,
        "effect": "新建一条团队备忘。" if action == "create"
        else "这条信息的生效时间早于它要替代的条目，只记入历史，不替代现有条目。",
        "anchor": {"kind": anchor["kind"], "id": str(anchor["id"]), "title": anchor["title"]},
        "audience": reads.audience(s, anchor),
        "kind": kind, "kind_label": reads.KIND_LABELS[kind], "statement": body.statement,
        "zone": "constraint" if kind == "convention" and epistemic != "disputed"
        and lifecycle == "active" else "background",
        "epistemic_label": reads.EPISTEMIC_LABELS[epistemic],
        "confirmation_label": reads.CONFIRMATION_LABELS[confirmation],
        "formal_status": None if kind != "decision_context" else (
            "linked" if formal else "no_formal_decision"),
        "source_authority": content["source_authority"],
        "customer": customer, "evidence_count": len(links), "review_days": reads.review_days(s),
        "supersedes": [str(row.note_id) for row in supersedes if not later],
        "relations": [{"type": item.type, "note_id": str(item.note.id)} for item in relations],
        "written_by": "xiaopai" if by_xiaopai else "person",
        "note": reads.FACT_POLICY,
    }
    plan = Plan(s, s.get_transaction(), command_digest(command), (note_id, 1, lifecycle),
                _visibility(anchor), review)
    plan.notes.append({"id": note_id, "category_id": anchor["category_id"],
                       "product_id": anchor["product_id"], "proposal_id": anchor["proposal_id"],
                       "project_id": anchor["project_id"], "anchor_kind": anchor["kind"],
                       "kind": kind, "claim_key": key})
    plan.versions = versions
    plan.evidence = [{**row, "note_id": note_id, "revision": 1, "category_id": anchor[
        "category_id"], "run_id": run.id if by_xiaopai else None} for row in links]
    plan.relations = [{"from_note_id": a, "to_note_id": b, "type": kind_, "category_id": anchor[
        "category_id"]} for a, b, kind_ in links_between]
    plan.result = {"note_id": str(note_id), "anchor_kind": anchor["kind"], "kind": kind,
                   "action": action}
    return plan


def _revise(s, ctx, command, payload):
    now = datetime.now(UTC)
    prior = _target(s, ctx, payload.note, action="改")
    anchor = _anchor(s, ctx, command, payload.anchor)
    body = payload.body
    if (prior.anchor_kind, {"category": prior.category_id, "product": prior.product_id,
                            "proposal": prior.proposal_id, "project": prior.project_id}[
            prior.anchor_kind]) != (anchor["kind"], anchor["id"]) or body.kind != prior.kind:
        deny("VALIDATION_FAILED", "scope_note_identity_fixed",
             "备忘的挂靠对象和种类不能改；请停用后另记一条。", 422)
    subject = _object(s, ctx, body.subject)
    formal = _object(s, ctx, body.formal, formal=True)
    added = _evidence(s, ctx, payload.evidence)
    known = _stored(reads.evidence(s, prior.note_id))
    if body.epistemic == "verified" and not verifiable([*known, *added]):
        deny("VALIDATION_FAILED", "scope_note_verified_requires_sources",
             "标为“已核实”须关联一条业务记录，或两个相互独立的来源；小Pai 的运行不算来源。", 422)
    valid_from = reads.as_utc(body.valid_from) or prior.valid_from
    valid_to = reads.as_utc(body.valid_until)
    if valid_to is not None and valid_to <= max(valid_from, now):
        deny("VALIDATION_FAILED", "scope_note_validity", "失效时间须晚于生效时间和现在。", 422)
    customer = _customer(s, ctx, anchor, body.customer)
    content = _copy(
        prior, statement=body.statement,
        subject_kind=subject["kind"] if subject else None,
        subject_id=subject["id"] if subject else None,
        subject_version=subject["revision"] if subject else None,
        customer_identity=customer, stage=body.stage, topic=body.topic,
        sensitivity="customer_private" if customer else "normal",
        epistemic=body.epistemic,
        confirmation="formal_linked" if formal else body.confirmation,
        formal_kind=formal["kind"] if formal else None,
        formal_id=formal["id"] if formal else None,
        formal_version=formal["revision"] if formal else None,
        generated_by="human" if prior.generated_by == "human" else "xiaopai_drafted",
        occurred_at=reads.as_utc(body.occurred_at), valid_from=valid_from, valid_to=valid_to,
        review_due_at=reads.review_due(s, now), pinned=body.pinned, confirmed_by=ctx.actor_id,
        source_authority=authority([*known, *added], by_xiaopai=False),
    )
    unchanged = all(content[name] == getattr(prior, name) for name in CONTENT if name not in {
        "review_due_at", "confirmed_by", "generated_by", "source_authority"})
    if unchanged and not added and prior.review_due_at > now:
        deny("VALIDATION_FAILED", "scope_note_unchanged", "内容没有改动。", 422)
    review = {
        "operation": command.operation,
        "effect": "保存这条备忘的新版本，旧版本保留在历史里，复核日期重新起算。",
        "anchor": {"kind": anchor["kind"], "id": str(anchor["id"]), "title": anchor["title"]},
        "audience": reads.audience(s, anchor),
        "note_id": str(prior.note_id), "from_revision": prior.revision,
        "kind": prior.kind, "kind_label": reads.KIND_LABELS[prior.kind],
        "before": prior.statement, "statement": body.statement,
        "epistemic_label": reads.EPISTEMIC_LABELS[body.epistemic],
        "confirmation_label": reads.CONFIRMATION_LABELS[content["confirmation"]],
        "formal_status": None if prior.kind != "decision_context" else (
            "linked" if formal else "no_formal_decision"),
        "customer": customer, "evidence_added": len(added), "review_days": reads.review_days(s),
        "written_by": "person", "note": reads.FACT_POLICY,
    }
    plan = Plan(s, s.get_transaction(), command_digest(command),
                (prior.note_id, prior.revision + 1, "active"), _visibility(anchor), review)
    plan.versions = [_row(prior, None, action="revise", lifecycle="active", reason=None,
                          origin={"entry": "page"}, **content)]
    plan.evidence = [{**row, "note_id": prior.note_id, "revision": prior.revision + 1,
                      "category_id": prior.category_id, "run_id": None} for row in added]
    plan.result = {"note_id": str(prior.note_id), "anchor_kind": prior.anchor_kind,
                   "kind": prior.kind, "action": "revise"}
    return plan


def _add_evidence(s, ctx, command, payload, *, writer, run):
    prior = _target(s, ctx, payload.note, action="补充证据")
    anchor_view, anchor = reads.anchor_view(s, prior)
    if writer == "agent":
        _anchor(s, ctx, command, SimpleNamespace(kind=anchor["kind"], id=anchor["id"]), run=run)
    added = _evidence(s, ctx, payload.evidence)
    known = reads.evidence(s, prior.note_id)
    fresh = [row for row in added if not any(
        (row["source_type"], row["source_id"], row["stance"], row["locator"]) == (
            old.source_type, old.source_id, old.stance, old.locator) for old in known)]
    if not fresh:
        deny("VERSION_CONFLICT", "scope_note_evidence_known", "这些证据已经在这条备忘上。")
    review = {
        "operation": command.operation,
        "effect": "给这条备忘补充证据链接；内容和确认状态不变。",
        "anchor": anchor_view, "audience": reads.audience(s, anchor),
        "note_id": str(prior.note_id), "from_revision": prior.revision,
        "statement": prior.statement, "evidence_added": len(fresh),
        "written_by": "xiaopai" if writer == "agent" else "person", "note": reads.FACT_POLICY,
    }
    plan = Plan(s, s.get_transaction(), command_digest(command),
                (prior.note_id, prior.revision + 1, "active"), _visibility(anchor), review)
    content = _copy(prior, source_authority=authority(
        [*_stored(known), *fresh], by_xiaopai=prior.generated_by == "xiaopai"))
    if writer == "agent":
        content["run_id"] = run.id
    plan.versions = [_row(prior, None, action="add_evidence", lifecycle="active", reason=None,
                          origin={"entry": "xiaopai" if writer == "agent" else "page"},
                          **content)]
    plan.evidence = [{**row, "note_id": prior.note_id, "revision": prior.revision + 1,
                      "category_id": prior.category_id,
                      "run_id": run.id if writer == "agent" else None} for row in fresh]
    plan.result = {"note_id": str(prior.note_id), "anchor_kind": prior.anchor_kind,
                   "kind": prior.kind, "action": "add_evidence"}
    return plan


def _end(row, action, reason, now):
    return _row(row, None, action=action,
                lifecycle="retired" if action == "retire" else "withdrawn", reason=reason,
                origin={"entry": "page"},
                **_copy(row, valid_to=max(min(row.valid_to or now, now), row.valid_from),
                        pinned=False))


def _retire(s, ctx, command, payload):
    now = datetime.now(UTC)
    if payload.note is not None:
        prior = _target(s, ctx, payload.note, action="停用")
        anchor_view, anchor = reads.anchor_view(s, prior)
        review = {
            "operation": command.operation,
            "effect": "停用这条备忘：不再带入任何人的小Pai 上下文，版本历史保留。"
            if payload.action == "retire"
            else "撤回这条备忘：标为不成立，不再带入任何人的小Pai 上下文，记录和原因保留。",
            "anchor": anchor_view, "note_id": str(prior.note_id),
            "from_revision": prior.revision, "statement": prior.statement,
            "action": payload.action, "reason": payload.reason,
        }
        plan = Plan(s, s.get_transaction(), command_digest(command),
                    (prior.note_id, prior.revision + 1,
                     "retired" if payload.action == "retire" else "withdrawn"),
                    _visibility(anchor), review)
        plan.versions = [_end(prior, payload.action, payload.reason, now)]
        plan.result = {"note_id": str(prior.note_id), "anchor_kind": prior.anchor_kind,
                       "kind": prior.kind, "action": payload.action}
        return plan
    # 按运行撤回 (P121 第 4 项): everything 小Pai wrote by itself in that Run and nobody took over.
    written = s.scalars(select(ScopeNoteVersion.note_id).where(
        ScopeNoteVersion.tenant_id == ctx.tenant_id, ScopeNoteVersion.run_id == payload.run_id,
        ScopeNoteVersion.category_id == ctx.category_id,
        ScopeNoteVersion.generated_by == "xiaopai", ScopeNoteVersion.action == "create")).all()
    heads = reads.latest(s, written)
    mine = [row for row in heads.values()
            if row.lifecycle == "active" and row.generated_by == "xiaopai"]
    taken_over = [row for row in heads.values()
                  if row.lifecycle == "active" and row.generated_by != "xiaopai"]
    links = s.scalars(select(ScopeNoteEvidence).where(
        ScopeNoteEvidence.tenant_id == ctx.tenant_id, ScopeNoteEvidence.run_id == payload.run_id,
        ScopeNoteEvidence.category_id == ctx.category_id,
        ScopeNoteEvidence.retracts_id.is_(None))).all()
    retracted = set(s.scalars(select(ScopeNoteEvidence.retracts_id).where(
        ScopeNoteEvidence.retracts_id.in_([row.id for row in links]))).all()) if links else set()
    gone = {row.note_id for row in mine}
    links = [row for row in links if row.id not in retracted and row.note_id not in gone]
    if not mine and not links:
        deny("NOT_FOUND", "scope_note_run_nothing",
             "这次运行没有可撤回的小Pai 记录（可能已撤回，或已被成员接手）。", 404)
    mine.sort(key=lambda row: str(row.note_id))
    links.sort(key=lambda row: str(row.id))
    review = {
        "operation": command.operation,
        "effect": "撤回小Pai 在这次运行里自动记下的观察和证据链接；成员已接手的条目不动。",
        "run_id": str(payload.run_id), "action": "withdraw", "reason": payload.reason,
        "observations": [{"note_id": str(row.note_id), "from_revision": row.revision,
                          "statement": row.statement} for row in mine],
        "evidence_links": len(links),
        "kept": [str(row.note_id) for row in sorted(taken_over, key=lambda r: str(r.note_id))],
    }
    head = mine[0] if mine else heads.get(links[0].note_id) or reads.latest(
        s, [links[0].note_id])[links[0].note_id]
    plan = Plan(s, s.get_transaction(), command_digest(command),
                (head.note_id, head.revision + 1 if mine else head.revision,
                 "withdrawn" if mine else head.lifecycle), "private", review)
    plan.versions = [_end(row, "withdraw", payload.reason, now) for row in mine]
    plan.evidence = [{
        "source_type": row.source_type, "source_kind": row.source_kind,
        "source_id": row.source_id, "source_version": row.source_version, "locator": row.locator,
        "root_source_id": row.root_source_id, "stance": row.stance,
        "quote_sha256": row.quote_sha256, "note_id": row.note_id, "revision": row.revision,
        "category_id": row.category_id, "run_id": None, "retracts_id": row.id,
    } for row in links]
    plan.result = {"note_id": str(head.note_id), "action": "withdraw_run",
                   "run_id": str(payload.run_id), "withdrawn": len(mine),
                   "evidence_retracted": len(links)}
    return plan


# ---------------------------------------------------------------------------
# Handler protocol (core.service).

def validate(s, ctx, command, scope, payload):
    key = ("scope-note-command", digest(vars(ctx)), command_digest(command),
           str(command.command_id))
    cached = s.info.get(key)
    if cached is not None and cached.transaction is s.get_transaction() and not cached.used:
        return cached
    writer = _writer(s, ctx)
    if writer != "agent" or command.operation != OBSERVE:
        human(s, ctx)  # a named person acting for themself; 小Pai never executes T1.
    run = _run(s, ctx) if writer == "agent" else None
    drafted = drafted_run(s, ctx, command) if writer == "human" else None
    if command.operation == SAVE:
        plan = (_revise(s, ctx, command, payload) if payload.note is not None else _create(
            s, ctx, command, payload, kind=payload.body.kind, body=payload.body, writer=writer,
            run=None, drafted=drafted))
    elif command.operation == RETIRE:
        plan = _retire(s, ctx, command, payload)
    else:
        plan = (_create(s, ctx, command, payload, kind="observation", body=payload,
                        writer=writer, run=run, drafted=drafted)
                if payload.mode == "observation"
                else _add_evidence(s, ctx, command, payload, writer=writer, run=run))
    plan.writer = writer
    s.info[key] = plan
    return plan


def preview_view(s, ctx, command, scope, payload):
    return validate(s, ctx, command, scope, payload).review


def apply_validated(s, ctx, command, scope, payload, plan):
    if (plan.session is not s or plan.transaction is not s.get_transaction()
            or plan.fingerprint != command_digest(command) or plan.used):
        deny("INTEGRITY_MISMATCH", "scope_note_plan_stale", "缺少本次事务的实际核对。")
    if plan.writer == "human" and plan.confirmation_id is None:
        # A person's write always carries their one confirmation, on the T0 lane too:
        # only 小Pai's own qualified Run writes an observation without one.
        deny("CONFIRMATION_REQUIRED", "scope_note_confirmation_required",
             "请先查看实际内容和受众，确认一次。")
    plan.used = True
    plan.receipt_id = uuid4()
    common = {"tenant_id": ctx.tenant_id, "writer_id": ctx.actor_id,
              "requester_id": ctx.requester_id, "operation": command.operation,
              "command_id": command.command_id, "receipt_id": plan.receipt_id,
              "request_digest": command_digest(command)}
    for values in plan.notes:
        s.add(ScopeNote(tenant_id=ctx.tenant_id, author_id=ctx.actor_id, **values))
    s.flush()
    for values in plan.versions:
        s.add(ScopeNoteVersion(id=uuid4(), **common, **values))
    s.flush()
    for values in plan.evidence:
        s.add(ScopeNoteEvidence(id=uuid4(), tenant_id=ctx.tenant_id, writer_id=ctx.actor_id,
                                receipt_id=plan.receipt_id, **{"retracts_id": None, **values}))
    for values in plan.relations:
        s.add(ScopeNoteRelation(id=uuid4(), tenant_id=ctx.tenant_id, created_by=ctx.actor_id,
                                receipt_id=plan.receipt_id, **values))
    s.flush()
    note_id, revision, lifecycle = plan.primary
    subject = SimpleNamespace(id=note_id, revision=revision, status=lifecycle,
                              prepared_receipt_id=plan.receipt_id, action_result=plan.result,
                              confirmation_id=plan.confirmation_id)
    return subject, SUBJECT, plan.visibility


def finalize_receipt(s, ctx, command, scope, payload, subject, receipt):
    if receipt.id != subject.prepared_receipt_id or receipt.subject_type != SUBJECT:
        deny("INTEGRITY_MISMATCH", "scope_note_receipt_mismatch", "备忘写入缺少同事务共同回执。")
