"""纠正分流 (memory design §14.9; P88 第 2 项; D475 第 2 条, D481 第三条).

A correction is first recorded on the run (``memory_episode_marks``), then sent
where the error lies. Every destination only produces a candidate or a notice
that a person acts on; a correction never edits a prompt, a skill package, a
business fact or a memory item by itself:

==========  ===========================================  ==========================
错在哪       去处                                          谁看
==========  ===========================================  ==========================
事实错误     提示改业务对象或原件（记忆不替事实打补丁）        本人；本人可转给对象负责人
做法问题     做法信号，进每日汇总的技能修订候选（§6.4）        汇总后由管理员审核
个人偏好     个人条目的提议卡（P86），本人确认后才写入          本人
团队约定     范围条目的待确认候选（P87），有写权限的人确认      挂靠对象负责人
==========  ===========================================  ==========================

The first two routes follow the feedback categories by a fixed rule. The last
two exist only when the person who corrected asks for them, in their own words:
nothing here infers a preference or a team convention from a correction, and no
model is called. Every row is written by that person acting for themself; the
database refuses the AI writer identity (s0_0895).
"""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import select

from pdos_next.core.schema_base import StrictModel
from pdos_next.core.service import digest
from pdos_next.errors import DomainError

from .m3_models import MemoryReviewDecision, MemoryReviewItem

FACT = frozenset({"wrong_object", "wrong_value", "missing_source"})
PRACTICE = frozenset({"not_useful", "too_many_actions", "should_not_automate"})
MAIN_PROMPT = "xiaopai.main"
ROUTE_LABELS = {
    "fact": "事实错误：请改业务对象或原件",
    "skill": "做法问题：已计入技能修订信号",
    "personal": "个人偏好：个人条目提议卡",
    "team": "团队约定：范围条目待确认候选",
}


def _human(session, ctx):
    from pdos_next.agent.kernel.session_views import _human as current_human

    current_human(session, ctx, None)


def _key(*parts):
    return digest(["memory-review/v1", *[str(part) for part in parts]])


def run_scope(run):
    """The most specific object the Run was bound to (server facts, not model input)."""
    for kind in ("project", "proposal", "product"):
        identity = getattr(run, f"{kind}_id", None)
        if identity is not None:
            return kind, identity
    if getattr(run, "category_id", None) is not None:
        return "category", run.category_id
    return "global", None


def _prompt_version(session, run_id):
    from pdos_next.agent.kernel.models import AgentRun

    versions = session.scalar(select(AgentRun.versions).where(AgentRun.id == run_id)) or {}
    return ((versions.get("prompt_identities") or {}).get("main") or {}).get("version") \
        or "unversioned"


def _object_version(session, ctx, kind, identity):
    if kind == "global":
        return None
    from pdos_next.domain.knowledge.scope_notes.reads import resolve

    found = resolve(session, ctx.tenant_id, kind, identity)
    return found["revision"] if found else None


def route_feedback(session, ctx, run, mark, feedback):
    """The fixed-rule routes of one correction: 事实错误 → 本人; 做法问题 → 做法信号."""
    from pdos_next.agent.kernel.run_feedback import loaded_skills

    categories = sorted(set(feedback["categories"]))
    facts = [value for value in categories if value in FACT]
    practice = [value for value in categories if value in PRACTICE]
    scope_kind, scope_id = run_scope(run)
    base = {
        "tenant_id": ctx.tenant_id, "source": "correction", "assignee_id": ctx.requester_id,
        "raised_by": ctx.requester_id, "run_id": run.id, "mark_id": mark.id,
        "scope_kind": scope_kind, "scope_id": scope_id,
        "category_id": None if scope_kind == "global" else run.category_id,
        "request_key": UUID(feedback["idempotency_key"]),
    }
    rows = []
    if facts:
        rows.append(MemoryReviewItem(
            **base, kind="fact", reasons=facts,
            object_kind=None if scope_kind == "global" else scope_kind,
            object_id=scope_id,
            recorded_version=_object_version(session, ctx, scope_kind, scope_id),
            dedupe_key=_key("fact", mark.id)))
    if practice:
        skills = loaded_skills(session, run)
        chosen = feedback.get("skill_load_event_id")
        if chosen:
            skills = [item for item in skills if item["load_event_id"] == chosen] or skills
        targets = sorted({("skill_package", item["key"], item["version"]) for item in skills}) \
            or [("prompt", MAIN_PROMPT, _prompt_version(session, run.id))]
        rows.extend(MemoryReviewItem(
            **base, kind="skill", reasons=practice, target_kind=kind, target_key=key,
            target_version=version, dedupe_key=_key("skill", mark.id, kind, key, version))
            for kind, key, version in targets)
    for row in rows:
        row.id = uuid4()
        session.add(row)
    session.flush()
    return rows


# ---------------------------------------------------------------------------
# The person who corrected asks for a further route, in their own words.


class RouteInput(StrictModel):
    request_key: UUID
    route: Literal["personal", "team", "forward"]
    text: str | None = Field(default=None, min_length=1, max_length=300)
    kind: Literal["convention", "background", "concern", "decision_context",
                  "observation"] | None = None
    # 个人条目: 全局，或本次运行的范围。团队条目永远挂在本次运行的范围上。
    scope: Literal["global", "run"] = "run"

    @model_validator(mode="after")
    def shaped(self):
        if self.route == "personal":
            if not self.text or len(self.text) > 200 or self.kind not in {
                    "convention", "background"}:
                raise ValueError("个人条目提议须写明内容（不超过 200 字），种类为口径或背景。")
        elif self.route == "team":
            if not self.text or self.kind in {None, "background"}:
                raise ValueError("团队条目候选须写明内容，种类为约定、关注点、决策背景或观察。")
        elif self.kind is not None:
            raise ValueError("转给对象负责人不带条目种类。")
        return self


def _deny(code, key, message, status=409):
    raise DomainError(code, message, status, detail={"reason_key": key})


def _lock(session, ctx, item_id):
    # Rows are append-only, so a decision is serialized with an advisory lock, not FOR UPDATE.
    from sqlalchemy import text

    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                    {"key": f"memory-review:{ctx.tenant_id}:{item_id}"})


def _own(session, ctx, item_id, *, lock=False):
    if lock:
        _lock(session, ctx, item_id)
    row = session.scalar(select(MemoryReviewItem).where(MemoryReviewItem.id == item_id))
    if row is None or row.source != "correction" or row.raised_by != ctx.requester_id:
        _deny("NOT_FOUND", "correction_not_found", "这条纠正不存在，或不是你本人记下的。", 404)
    return row


def _anchor(session, ctx, parent):
    from pdos_next.agent.kernel.models import AgentRun
    from pdos_next.domain.knowledge.scope_notes.reads import resolve

    run = session.get(AgentRun, parent.run_id)
    kind, identity = run_scope(run)
    if kind == "global":
        _deny("VALIDATION_FAILED", "team_route_needs_scope",
              "这次工作不在品类、产品、提案或项目范围里，不能记成团队条目。", 422)
    found = resolve(session, ctx.tenant_id, kind, identity)
    if found is None:
        _deny("FORBIDDEN_SCOPE", "team_route_scope_unreadable", "你现在读不到这次工作的范围。", 403)
    return run, kind, identity, found


def add_route(session, ctx, item_id, data):
    _human(session, ctx)
    parent = _own(session, ctx, item_id, lock=True)
    fingerprint = digest({"parent": parent.id, **data.model_dump(mode="json", exclude={
        "request_key"})})
    dedupe = _key("route", ctx.requester_id, data.request_key)
    previous = session.scalar(select(MemoryReviewItem).where(
        MemoryReviewItem.dedupe_key == dedupe))
    if previous is not None:
        if previous.parent_id != parent.id or previous.reasons != [fingerprint]:
            _deny("DUPLICATE_INTENT_CONFLICT", "route_request_changed", "请求编号对应不同的分流。")
        return view(session, ctx, previous)
    values = {"tenant_id": ctx.tenant_id, "source": "correction", "raised_by": ctx.requester_id,
              "run_id": parent.run_id, "mark_id": parent.mark_id, "parent_id": parent.id,
              "request_key": data.request_key, "dedupe_key": dedupe,
              # The fingerprint stands in for the reasons, so a replay can be checked.
              "reasons": [fingerprint]}
    if data.route == "forward":
        if parent.kind != "fact" or parent.object_id is None:
            _deny("VALIDATION_FAILED", "forward_needs_fact",
                  "只有事实错误的提示能转给对象负责人。", 422)
        _decided(session, parent)
        from pdos_next.domain.knowledge.scope_notes.reads import resolve

        found = resolve(session, ctx.tenant_id, parent.object_kind, parent.object_id)
        if found is None:
            _deny("FORBIDDEN_SCOPE", "object_unreadable", "你现在读不到这个对象，不能转交。", 403)
        if found["owner_id"] == ctx.requester_id:
            _deny("VALIDATION_FAILED", "already_owner", "你就是这个对象的负责人，请直接修改。", 422)
        row = MemoryReviewItem(
            **values, kind="fact", assignee_id=found["owner_id"], scope_kind=parent.scope_kind,
            category_id=parent.category_id, scope_id=parent.scope_id,
            object_kind=parent.object_kind, object_id=parent.object_id,
            recorded_version=parent.recorded_version, current_version=found["revision"],
            text=data.text)
        _write_decision(session, ctx, parent, "forwarded", {"forwarded_to": str(row.assignee_id)},
                        data.request_key)
    elif data.route == "personal":
        from pdos_next.agent.kernel.models import AgentRun

        run = session.get(AgentRun, parent.run_id)
        kind, identity = run_scope(run) if data.scope == "run" else ("global", None)
        row = MemoryReviewItem(
            **values, kind="personal", assignee_id=ctx.requester_id, scope_kind=kind,
            category_id=None if kind == "global" else run.category_id, scope_id=identity,
            text=data.text, proposed_kind=data.kind)
    else:
        run, kind, identity, found = _anchor(session, ctx, parent)
        row = MemoryReviewItem(
            **values, kind="team", assignee_id=found["owner_id"], scope_kind=kind,
            category_id=run.category_id, scope_id=identity, object_kind=kind,
            object_id=identity, current_version=found["revision"],
            text=data.text, proposed_kind=data.kind)
    row.id = uuid4()
    session.add(row)
    session.flush()
    return view(session, ctx, row)


# ---------------------------------------------------------------------------
# Decisions, by the assignee only.

ALLOWED = {
    "fact": {"resolved", "dismissed"},
    "personal": {"adopted", "dismissed"},
    "team": {"adopted", "dismissed"},
    "object_updated": {"resolved", "dismissed"},
    "author_departed": {"resolved", "dismissed"},
}


class DecisionInput(StrictModel):
    request_key: UUID
    decision: Literal["adopted", "dismissed", "resolved"]
    # 团队条目: the scope note the assignee saved through scope_note.save themself.
    note_id: UUID | None = None
    # 个人条目: the same three choices as the "我的记忆" page when similar notes exist.
    conflict: dict | None = None


def _decided(session, row):
    if session.scalar(select(MemoryReviewDecision.id).where(
            MemoryReviewDecision.item_id == row.id)):
        _deny("VERSION_CONFLICT", "already_decided", "这一项已经处理过了。")


def _write_decision(session, ctx, row, decision, result, request_key):
    session.add(MemoryReviewDecision(
        id=uuid4(), tenant_id=ctx.tenant_id, item_id=row.id, decided_by=ctx.requester_id,
        decision=decision, result=result, request_key=request_key,
        request_sha256=digest({"item": row.id, "decision": decision, "result": result})))
    session.flush()


def decide(session, ctx, item_id, data):
    _human(session, ctx)
    _lock(session, ctx, item_id)
    row = session.scalar(select(MemoryReviewItem).where(MemoryReviewItem.id == item_id))
    if row is None or row.assignee_id != ctx.requester_id:
        _deny("NOT_FOUND", "review_item_not_found", "这一项不存在，或不归你处理。", 404)
    replay = session.scalar(select(MemoryReviewDecision).where(
        MemoryReviewDecision.decided_by == ctx.requester_id,
        MemoryReviewDecision.request_key == data.request_key))
    if replay is not None:
        if replay.item_id != row.id or replay.decision != data.decision:
            _deny("DUPLICATE_INTENT_CONFLICT", "decision_request_changed",
                  "请求编号对应不同的决定。")
        return view(session, ctx, row)
    if data.decision not in ALLOWED.get(row.kind, set()):
        _deny("VALIDATION_FAILED", "decision_not_allowed", "这一项不能这样处理。", 422)
    _decided(session, row)
    result = {}
    if row.kind == "personal" and data.decision == "adopted":
        result = _adopt_personal(session, ctx, row, data)
    elif row.kind == "team" and data.decision == "adopted":
        result = _adopt_team(session, ctx, row, data)
    _write_decision(session, ctx, row, data.decision, result, data.request_key)
    return view(session, ctx, row)


def _adopt_personal(session, ctx, row, data):
    """本人确认后，以本人身份经“我的记忆”的同一路径写入（含相似条目三选一）。"""
    from .notes import ConflictChoice, CreateNote, NoteDraft, create

    scope = {"kind": row.scope_kind, "id": str(row.scope_id)} if row.scope_id else {
        "kind": "global"}
    note = create(session, ctx, CreateNote(
        request_key=data.request_key,
        note=NoteDraft.model_validate({"kind": row.proposed_kind, "text": row.text,
                                       "scope": scope}),
        conflict=ConflictChoice.model_validate(data.conflict) if data.conflict else None))
    return {"note_id": note["note"]["note_id"]}


def _adopt_team(session, ctx, row, data):
    """The assignee saved it through scope_note.save (preview, audience, one confirmation)."""
    from pdos_next.domain.knowledge.scope_notes.models import ScopeNote
    from pdos_next.domain.knowledge.scope_notes.reads import latest

    if data.note_id is None:
        _deny("VALIDATION_FAILED", "team_adopt_needs_note",
              "请先在团队备忘里确认记下这一条，再标为已采纳。", 422)
    note = session.scalar(select(ScopeNote).where(ScopeNote.id == data.note_id))
    current = latest(session, [data.note_id]).get(data.note_id) if note else None
    if (current is None or note.category_id != row.category_id
            or ctx.requester_id not in {current.writer_id, current.confirmed_by}):
        _deny("VALIDATION_FAILED", "team_note_not_confirmed_by_you",
              "这条团队备忘不在该范围，或不是你确认记下的。", 422)
    return {"scope_note_id": str(data.note_id), "revision": current.revision}


# ---------------------------------------------------------------------------
# Views


def _status(session, row):
    decision = session.scalar(select(MemoryReviewDecision).where(
        MemoryReviewDecision.item_id == row.id))
    return decision


def view(session, ctx, row):
    from pdos_next.domain.knowledge.scope_notes.reads import person, resolve

    decision = _status(session, row)
    value = {
        "item_id": str(row.id), "source": row.source, "kind": row.kind,
        "label": ROUTE_LABELS.get(row.kind) or {
            "object_updated": "对象已更新，待复核",
            "author_departed": "作者已离开，复核转交给你"}[row.kind],
        "assignee": person(session, ctx.tenant_id, row.assignee_id),
        "raised_by_me": row.raised_by == ctx.requester_id,
        "run_id": str(row.run_id) if row.run_id else None,
        "parent_id": str(row.parent_id) if row.parent_id else None,
        "scope": {"kind": row.scope_kind, "id": str(row.scope_id) if row.scope_id else None,
                  "category_id": str(row.category_id) if row.category_id else None},
        "reasons": [] if row.parent_id else list(row.reasons),
        "text": row.text, "proposed_kind": row.proposed_kind,
        "recorded_at": row.created_at.isoformat(),
        "status": decision.decision if decision else "open",
        "result": decision.result if decision else None,
        "choices": sorted(ALLOWED.get(row.kind, set())) if row.assignee_id == ctx.requester_id
        and decision is None else [],
    }
    if row.object_id is not None:
        found = resolve(session, ctx.tenant_id, row.object_kind, row.object_id) \
            if row.object_kind != "proposal_decision" else None
        value["object"] = {"kind": row.object_kind, "id": str(row.object_id),
                           "title": found["title"] if found else None,
                           "recorded_version": row.recorded_version,
                           "current_version": found["revision"] if found else
                           row.current_version}
    if row.target_kind is not None:
        value["target"] = {"kind": row.target_kind, "key": row.target_key,
                           "version": row.target_version}
    if row.note_id is not None:
        value["note"] = {"kind": row.note_kind, "id": str(row.note_id),
                         "revision": row.note_revision}
    return value


def _visible(session, ctx, row):
    """A note-bound item is shown only while its assignee can still read that note."""
    if row.note_kind == "scope_note":
        from pdos_next.domain.knowledge.scope_notes.reads import latest
        from pdos_next.domain.knowledge.scope_notes.reads import view as note_view

        current = latest(session, [row.note_id]).get(row.note_id)
        return current is not None and note_view(session, current) is not None
    if row.note_kind == "personal_note":
        return row.assignee_id == ctx.requester_id
    return True


def listing(session, ctx, *, limit=50):
    """我的工作 · 记忆复核: open items assigned to me, and what became of what I raised."""
    _human(session, ctx)
    assigned = session.scalars(select(MemoryReviewItem).where(
        MemoryReviewItem.assignee_id == ctx.requester_id, MemoryReviewItem.kind != "skill",
        ~select(MemoryReviewDecision.id).where(
            MemoryReviewDecision.item_id == MemoryReviewItem.id).exists(),
    ).order_by(MemoryReviewItem.created_at.desc()).limit(limit)).all()
    raised = session.scalars(select(MemoryReviewItem).where(
        MemoryReviewItem.raised_by == ctx.requester_id,
    ).order_by(MemoryReviewItem.created_at.desc()).limit(limit)).all()
    items = [view(session, ctx, row) for row in assigned if _visible(session, ctx, row)]
    return {"version": "memory-review-items/v1", "items": items, "count": len(items),
            "raised": [view(session, ctx, row) for row in raised],
            "note": "这些是待你复核或处理的记忆提示与候选。处理之前，什么都不会自动改。"}
