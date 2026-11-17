"""Memory M3 (P88; memory design §14.9, §7.5, §6.4): every route only yields a candidate.

Real Runs, real feedback, real scope-note commands, real roles. No model is called.
"""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.models import TenantAdministrator
from pdos_next.agent.memory import distillation, fanout
from pdos_next.agent.memory.m3_models import (
    MemoryMaintenanceLedger,
    MemoryReviewItem,
    SkillRevisionCandidate,
)
from pdos_next.agent.memory.models import MemoryNoteVersion
from pdos_next.core.database import tenant_session
from pdos_next.core.models import Category, Grant, Outbox, Product, Receipt, now
from pdos_next.domain.knowledge.scope_notes.models import ScopeNoteVersion
from tests.agent.memory.support import finish, start
from tests.knowledge.scope_notes.support import anchor, headers, save

BASE = "/v1/personal/memory"
POLICY = "/v1/personal/memory-policy"


def feedback(setup, run_id, *categories, comment=""):
    response = setup.client.post(
        f"/v1/categories/{setup.category}/agent-runs/{run_id}/feedback", headers=setup.headers,
        json={"idempotency_key": str(uuid4()), "categories": list(categories),
              "comment": comment})
    assert response.status_code == 200, response.text
    return response.json()


def corrected(setup, *categories, goal="比较三家气泵供应商的报价和交期"):
    run_id, _ = start(setup, goal=goal)
    finish(setup, run_id)
    feedback(setup, run_id, *categories, comment="交期单位应该是天，不是周")
    return run_id


def items(setup, person=None):
    response = setup.client.get(f"{BASE}/review-items", headers=headers(setup, person))
    assert response.status_code == 200, response.text
    return response.json()


def counts(setup):
    with Session(setup.admin) as session:
        return {
            "notes": session.scalar(select(func.count()).select_from(MemoryNoteVersion).where(
                MemoryNoteVersion.tenant_id == setup.tenant)),
            "scope_notes": session.scalar(select(func.count()).select_from(
                ScopeNoteVersion).where(ScopeNoteVersion.tenant_id == setup.tenant)),
            "category_revision": session.get(Category, setup.category).revision,
            "product_revision": session.get(Product, setup.product).revision,
        }


def admin(setup, person=None):
    with Session(setup.admin) as session, session.begin():
        session.add(TenantAdministrator(tenant_id=setup.tenant,
                                        principal_id=person or setup.human))


def route(setup, item_id, status=200, person=None, **body):
    response = setup.client.post(f"{BASE}/review-items/{item_id}/routes",
                                 headers=headers(setup, person),
                                 json={"request_key": str(uuid4()), **body})
    assert response.status_code == status, response.text
    return response.json()


def decide(setup, item_id, decision, status=200, person=None, **body):
    response = setup.client.post(f"{BASE}/review-items/{item_id}/decision",
                                 headers=headers(setup, person),
                                 json={"request_key": str(uuid4()), "decision": decision, **body})
    assert response.status_code == status, response.text
    return response.json()


# ---------------------------------------------------------------------------
# 纠正分流


def test_fixed_rule_routes_fact_to_the_owner_and_practice_to_signals_only(setup):
    before = counts(setup)
    corrected(setup, "wrong_value", "too_many_actions")
    raised = {item["kind"]: item for item in items(setup)["raised"]}
    assert set(raised) == {"fact", "skill"}
    fact = raised["fact"]
    assert fact["assignee"]["id"] == str(setup.human) and fact["status"] == "open"
    assert fact["object"]["kind"] == "category" and fact["reasons"] == ["wrong_value"]
    assert fact["text"] is None  # the private comment stays on the correction mark
    skill = raised["skill"]
    assert skill["target"] == {"kind": "prompt", "key": "xiaopai.main",
                               "version": skill["target"]["version"]}
    assert skill["reasons"] == ["too_many_actions"]
    # Only the fact notice waits on someone; the practice signal goes to the summary.
    assert [item["kind"] for item in items(setup)["items"]] == ["fact"]
    # Nothing changed: no memory, no team note, no business object.
    assert counts(setup) == before
    # Another person sees nothing of it.
    assert items(setup, setup.peer)["raised"] == [] and items(setup, setup.peer)["items"] == []


def test_personal_route_is_a_proposal_card_until_the_owner_adopts_it(setup):
    corrected(setup, "not_useful")
    (skill,) = items(setup)["raised"]
    card = route(setup, skill["item_id"], route="personal", kind="convention",
                 text="交期一律按天写", scope="global")
    assert card["kind"] == "personal" and card["status"] == "open"
    assert counts(setup)["notes"] == 0
    # The peer cannot decide it, or even find it.
    decide(setup, card["item_id"], "adopted", status=404, person=setup.peer)
    adopted = decide(setup, card["item_id"], "adopted")
    assert adopted["status"] == "adopted" and adopted["result"]["note_id"]
    notes = setup.client.get(f"{BASE}/notes", headers=setup.headers).json()["notes"]
    assert [(note["text"], note["origin"]) for note in notes] == [("交期一律按天写", "manual")]
    decide(setup, card["item_id"], "dismissed", status=409)


def test_team_route_waits_for_a_confirmed_scope_note(setup):
    corrected(setup, "too_many_actions")
    (skill,) = items(setup)["raised"]
    candidate = route(setup, skill["item_id"], route="team", kind="convention",
                      text="给该客户的报告一律英文")
    assert candidate["scope"]["kind"] == "category"
    assert candidate["assignee"]["id"] == str(setup.human)  # the category owner
    assert counts(setup)["scope_notes"] == 0
    decide(setup, candidate["item_id"], "adopted", status=422)
    receipt = save(setup, "给该客户的报告一律英文")
    done = decide(setup, candidate["item_id"], "adopted", note_id=receipt["subject_id"])
    assert done["result"]["scope_note_id"] == receipt["subject_id"]


def peer_category(setup):
    """A second category the peer owns, with the same three members (owner is immutable)."""
    identity = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(Category(id=identity, tenant_id=setup.tenant, name="车载吸尘器",
                             purpose="隔离合成品类", owner_id=setup.peer))
        session.flush()
        session.add_all([Grant(tenant_id=setup.tenant, category_id=identity, principal_id=person,
                               can_write=True, expires_at=now() + timedelta(hours=1))
                         for person in (setup.human, setup.peer, setup.agent)])
    from copy import copy

    other = copy(setup)
    other.category = identity
    return other


def test_fact_route_can_be_forwarded_to_the_object_owner(setup):
    setup = peer_category(setup)
    corrected(setup, "wrong_object")
    (fact,) = items(setup)["items"]
    forwarded = route(setup, fact["item_id"], route="forward", text="规格表里的交期单位写错了")
    assert forwarded["assignee"]["id"] == str(setup.peer)
    mine = {item["item_id"]: item for item in items(setup)["raised"]}
    assert mine[fact["item_id"]]["status"] == "forwarded"
    (theirs,) = items(setup, setup.peer)["items"]
    assert theirs["item_id"] == forwarded["item_id"]
    assert theirs["text"] == "规格表里的交期单位写错了"
    resolved = decide(setup, theirs["item_id"], "resolved", person=setup.peer)
    assert resolved["status"] == "resolved"
    route(setup, fact["item_id"], route="forward", status=409)


def test_ai_identity_cannot_write_review_items_or_decisions(setup):
    corrected(setup, "wrong_value")
    with Session(setup.admin) as session:
        fact = session.scalar(select(MemoryReviewItem).where(
            MemoryReviewItem.tenant_id == setup.tenant))
    values = {column.name: getattr(fact, column.name) for column in fact.__table__.columns}
    values.update(id=uuid4(), kind="personal", text="以后都用英文", proposed_kind="convention",
                  dedupe_key="0" * 64, object_kind=None, object_id=None,
                  recorded_version=None)
    with pytest.raises(DBAPIError):
        with tenant_session(setup.engine, setup.tenant, actor_id=setup.agent,
                            requester_id=setup.human, category_id=setup.category) as session:
            session.add(MemoryReviewItem(**values))
            session.flush()
    # The system-rule sources cannot be inserted directly either, even by the owner.
    values.update(id=uuid4(), source="staleness", kind="object_updated", raised_by=None,
                  run_id=None, mark_id=None, request_key=None, text=None, proposed_kind=None,
                  note_kind="scope_note", note_id=uuid4(), note_revision=1,
                  object_kind="product", object_id=setup.product, current_version=2,
                  event_id=uuid4(), dedupe_key="1" * 64)
    with pytest.raises(DBAPIError):
        with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                            requester_id=setup.human, category_id=setup.category) as session:
            session.add(MemoryReviewItem(**values))
            session.flush()


# ---------------------------------------------------------------------------
# 改版标待复核、复核转交 (D508)


def outbox(setup, receipt_id, kind, subject, revision):
    identity = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(Outbox(id=identity, tenant_id=setup.tenant, receipt_id=receipt_id,
                           category_id=setup.category, type=kind, subject_id=subject,
                           subject_revision=revision, actor_id=setup.human,
                           correlation_id=uuid4()))
    return identity


def handle(setup, event, handler="staleness", kind="proposal.item_patched", **ports):
    with tenant_session(setup.engine, setup.tenant) as session:
        return fanout.handle(session, {"tenant_id": str(setup.tenant), "event_id": str(event),
                                       "event_type": kind, "handler": handler}, **ports)


def test_object_revision_flags_referencing_notes_deterministically(setup):
    receipt = save(setup, "规格书一律引用当前基线",
                   subject={"kind": "product", "id": str(setup.product)})
    alias = setup.client.post(f"{BASE}/notes", headers=setup.headers, json={
        "request_key": str(uuid4()), "note": {"kind": "alias", "alias_term": "老王那个泵",
                                               "alias_target": {"kind": "product",
                                                                "id": str(setup.product)}}})
    assert alias.status_code == 200, alias.text
    unrelated = save(setup, "品类口径：价格带按出厂价")
    before = counts(setup)
    with Session(setup.admin) as session, session.begin():
        session.get(Product, setup.product).revision += 1
        revision = session.get(Product, setup.product).revision
    event = outbox(setup, UUID(receipt["id"]), "proposal.item_patched", setup.product,
                   revision)
    first = handle(setup, event)
    assert first["outcome"] == "done" and first["detail"] == {"flagged": 2} and first["new"]
    again = handle(setup, event)
    assert again["detail"] == {"flagged": 0} and not again["new"]
    flagged = {item["note"]["kind"]: item for item in items(setup)["items"]}
    assert set(flagged) == {"scope_note", "personal_note"}
    assert flagged["scope_note"]["note"]["id"] == receipt["subject_id"]
    assert flagged["scope_note"]["object"]["current_version"] == revision
    assert unrelated["subject_id"] not in {item["note"]["id"] for item in flagged.values()}
    # The notes themselves are untouched: same versions, same count.
    assert counts(setup)["scope_notes"] == before["scope_notes"]
    assert counts(setup)["notes"] == before["notes"]
    # The peer cannot see either flag (personal: owner only; scope: assignee only).
    assert items(setup, setup.peer)["items"] == []
    with Session(setup.admin) as session:
        assert session.scalar(select(func.count()).select_from(MemoryMaintenanceLedger).where(
            MemoryMaintenanceLedger.tenant_id == setup.tenant)) == 1
    resolved = decide(setup, flagged["scope_note"]["item_id"], "resolved")
    assert resolved["status"] == "resolved"


def test_change_effectivity_flags_notes_on_the_changed_product(setup):
    receipt = save(setup, "这个型号的测试工况按 25℃", at=anchor(setup, "product", setup.product),
                   product=setup.product, subject={"kind": "product", "id": str(setup.product)})
    with Session(setup.admin) as session:
        assert session.get(Receipt, UUID(receipt["id"])).product_id == setup.product
    event = outbox(setup, UUID(receipt["id"]), "change.effectivity_recorded", uuid4(), 1)
    assert handle(setup, event, kind="change.effectivity_recorded")["detail"]["flagged"] == 1


def test_departed_author_hands_review_to_the_object_owner(setup):
    receipt = save(setup, "最近三批气嘴来料毛刺偏多", kind="observation", person=setup.peer)
    with tenant_session(setup.engine, setup.tenant) as session:
        assert fanout.daily(session, setup.tenant, "departure", day="2026-11-15")["detail"] == {
            "handed_over": 0}
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(select(Grant).where(Grant.tenant_id == setup.tenant,
                                                   Grant.principal_id == setup.peer))
        grant.expires_at = now() - timedelta(minutes=1)
    with tenant_session(setup.engine, setup.tenant) as session:
        assert fanout.daily(session, setup.tenant, "departure", day="2026-11-16")["detail"] == {
            "handed_over": 1}
        assert fanout.daily(session, setup.tenant, "departure", day="2026-11-16")["new"] is False
    (handed,) = items(setup)["items"]
    assert handed["kind"] == "author_departed" and handed["note"]["id"] == receipt["subject_id"]


# ---------------------------------------------------------------------------
# 程序性汇总与审核


def test_procedural_summary_yields_a_candidate_and_adoption_only_names_a_draft(setup):
    for _ in range(5):
        corrected(setup, "too_many_actions")
    corrected(setup, "should_not_automate")
    with tenant_session(setup.engine, setup.tenant) as session:
        assert fanout.daily(session, setup.tenant, "procedural", day="d1")["detail"] == {
            "candidates": 1}
        assert fanout.daily(session, setup.tenant, "procedural", day="d2")["detail"] == {
            "candidates": 0}  # an undecided candidate already covers the group
    assert setup.client.get(f"{POLICY}/skill-revisions",
                            headers=setup.headers).status_code == 403
    admin(setup)
    page = setup.client.get(f"{POLICY}/skill-revisions", headers=setup.headers).json()
    (candidate,) = page["items"]
    assert candidate["reason"] == "too_many_actions" and candidate["signal_count"] == 5
    assert candidate["target"]["kind"] == "prompt" and len(candidate["sample_run_ids"]) == 5
    summary = {item["reason"]: item for item in page["summary"]}
    assert summary["should_not_automate"]["signal_count"] == 1
    assert not summary["should_not_automate"]["reaches_threshold"]
    decided = setup.client.post(
        f"{POLICY}/skill-revisions/{candidate['candidate_id']}/decision", headers=setup.headers,
        json={"request_key": str(uuid4()), "decision": "adopt", "note": "动作太多，先收紧"})
    assert decided.status_code == 200, decided.text
    draft = decided.json()["draft"]
    assert draft["draft_version"].endswith("-draft") and draft["status"] == "to_prepare"
    assert "activated" not in draft
    with tenant_session(setup.engine, setup.tenant) as session:
        assert fanout.daily(session, setup.tenant, "procedural", day="d3")["detail"] == {
            "candidates": 0}  # signals up to the decided window are not counted again
    # The peer, not an administrator, can neither read nor decide.
    assert setup.client.get(f"{POLICY}/skill-revisions",
                            headers=headers(setup, setup.peer)).status_code == 403
    with Session(setup.admin) as session:
        assert session.scalar(select(func.count()).select_from(SkillRevisionCandidate).where(
            SkillRevisionCandidate.tenant_id == setup.tenant)) == 1
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.peer,
                        requester_id=setup.peer) as session:
        with pytest.raises(DBAPIError):
            session.execute(text("SELECT * FROM public.memory_procedural_overview(:t, now())"),
                            {"t": setup.tenant})


# ---------------------------------------------------------------------------
# 经验沉淀与系统规则


def test_distillation_trigger_is_held_while_the_skill_is_a_draft(setup):
    receipt = save(setup, "客户 A 评审必问跌落测试", kind="concern")
    event = outbox(setup, UUID(receipt["id"]), "proposal.g0_decided", uuid4(), 1)
    started = []
    result = handle(setup, event, handler="distillation", kind="proposal.g0_decided",
                    start_distillation=started.append)
    assert result["outcome"] == "held" and started == []
    assert result["detail"]["rules"] == [{"rule": "distill_g0", "reason": "skill_draft_only"}]
    other = outbox(setup, UUID(receipt["id"]), "proposal.item_patched", uuid4(), 1)
    assert handle(setup, other, handler="distillation")["outcome"] == "skipped"
    for handler in ("scope_recent", "index"):
        assert handle(setup, other, handler=handler)["outcome"] == "skipped"
    admin(setup)
    rules = setup.client.get(f"{POLICY}/system-rules", headers=setup.headers).json()
    assert rules["skill"]["state"] == "skill_draft_only"
    assert {rule["key"] for rule in rules["rules"]} == set(distillation.RULES)
    stopped = setup.client.post(f"{POLICY}/system-rules/distill_g0", headers=setup.headers,
                                json={"request_key": str(uuid4()), "enabled": False})
    assert stopped.status_code == 200, stopped.text
    again = outbox(setup, UUID(receipt["id"]), "proposal.g0_decided", uuid4(), 1)
    assert handle(setup, again, handler="distillation", kind="proposal.g0_decided")[
        "detail"]["rules"] == [{"rule": "distill_g0", "reason": "rule_stopped"}]
    # The rule text cannot be rewritten: the payload only has "enabled".
    assert setup.client.post(f"{POLICY}/system-rules/distill_g0", headers=setup.headers, json={
        "request_key": str(uuid4()), "enabled": True, "events": ["x"]}).status_code == 422
    assert setup.client.post(f"{POLICY}/system-rules/distill_g0", headers=headers(
        setup, setup.peer), json={"request_key": str(uuid4()),
                                  "enabled": True}).status_code == 403
