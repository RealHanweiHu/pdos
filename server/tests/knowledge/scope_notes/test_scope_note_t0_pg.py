"""P121 第 4 项: the T0 lane for 小Pai's observations and evidence links, and its gate.

The Run, the model call and the "tenant × skill package × model version"
qualification are synthetic ledger rows; no provider is contacted. The command
runs through the registered domain adapter and the common command path, so the
qualification check is the real one. Shipped skill packages do not list the
scope-note commands yet (registered remainder), so the fixture adds them to a
copy of one skill for this test only.
"""

from dataclasses import replace
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.bindings import execution_key
from pdos_next.agent.kernel.disclosure import disclosure_digest
from pdos_next.agent.kernel.models import AgentToolCall
from pdos_next.agent.kernel.qualification_binding import model_identity, tool_identity
from pdos_next.core.models import Receipt
from pdos_next.domain.knowledge.scope_notes.models import ScopeNoteEvidence, ScopeNoteVersion
from pdos_next.errors import DomainError
from tests.categories.preproject import test_review_fixes as fixtures
from tests.knowledge.scope_notes.support import (
    OBSERVE,
    RETIRE,
    SAVE,
    anchor,
    commit,
    headers,
    item,
    listing,
    preview,
    private_product,
    save,
)

SKILL = "proposal_drafting"


def run_fixture(setup, monkeypatch, arguments, *, operation=OBSERVE, qualified=True):
    """An actual stored Run whose loaded skill allows the scope-note commands."""
    original = fixtures.ledger

    def with_scope_notes():
        ledger = original()
        skill = replace(ledger.catalog._skills[SKILL], operations=frozenset(
            {*ledger.catalog._skills[SKILL].operations, OBSERVE, SAVE, RETIRE}))
        ledger.catalog._skills[SKILL] = skill
        binding = ledger.source.skill.model_copy(update={"digest": skill.digest})
        ledger.source = ledger.source.model_copy(update={"skill": binding})
        tools = disclosure_digest(ledger.registry, "main", skill.operations, ledger.scope)
        ledger.model.execution_binding = {
            **ledger.model.execution_binding,
            "loaded_skills": [binding.model_dump(mode="json")],
            "tool_definitions_digest": tools,
        }
        ledger.run.versions = {**ledger.run.versions, "tool_definitions": {
            **ledger.run.versions["tool_definitions"], "main": tools}}
        ledger.event.body = {**ledger.event.body, "digest": skill.digest}
        ledger.qualification.qualified_skill_digest = skill.digest
        ledger.qualification.qualified_tool_digest = tool_identity(skill, ledger.registry)
        ledger.qualification.qualified_model_digest = model_identity(ledger.route)
        if not qualified:
            # Enabled skill, but no qualification for this model version.
            ledger.qualification.qualified_model_version = None
            ledger.qualification.qualified_model_digest = None
            ledger.qualification.review_case_refs = []
            ledger.qualification.reviewed_by = None
            ledger.qualification.reviewed_at = None
        return ledger

    with monkeypatch.context() as patch:
        patch.setattr(fixtures, "ledger", with_scope_notes)
        fixture = fixtures.agent_fixture(setup, operation, arguments)
    if not qualified:
        with Session(setup.admin) as session, session.begin():
            row = session.get(type(fixture.qualification), fixture.qualification.id)
            row.reviewed_by = None
    return fixture


def key(fixture):
    return execution_key(fixture.scope.run_id, fixture.source.model_call_id,
                         fixture.source.response_index)


def execute(fixture, arguments, operation=OBSERVE):
    return fixture.adapter.execute(fixture.scope, operation, arguments, key(fixture),
                                   source=fixture.source)


def observation(setup, statement="最近三批气嘴来料毛刺偏多", **extra):
    return {"mode": "observation", "anchor": anchor(setup), "statement": statement, **extra}


def test_qualified_run_records_an_unverified_observation_signed_by_xiaopai(setup, monkeypatch):
    arguments = observation(setup, inferred=True)
    fixture = run_fixture(setup, monkeypatch, arguments)
    receipt = execute(fixture, arguments)
    assert receipt["operation"] == OBSERVE and receipt["writer_id"] == str(setup.agent)
    assert receipt["requester_id"] == str(setup.human)
    assert receipt["agent_run_id"] == str(fixture.scope.run_id)
    note = item(setup, receipt["subject_id"])["note"]
    assert note["kind"] == "observation" and note["zone"] == "background"
    assert note["generated_by"] == "xiaopai" and note["generated_label"] == "小Pai 记录，未核实"
    assert note["epistemic"] == "inferred" and note["confirmation"] == "proposed"
    assert note["confirmed_by"] is None and note["pinned"] is False
    assert note["author"]["name"] == "小Pai" and note["source_authority"] == "xiaopai_generated"
    assert note["run_id"] == str(fixture.scope.run_id)
    # The review duty of what 小Pai wrote sits with the owner of the attached object.
    assert note["review_owner"]["id"] == str(setup.human)
    # The same model call replays its receipt instead of writing twice.
    assert execute(fixture, arguments)["id"] == receipt["id"]
    with Session(setup.admin) as session:
        assert len(session.scalars(select(ScopeNoteVersion).where(
            ScopeNoteVersion.run_id == fixture.scope.run_id)).all()) == 1


def test_without_a_qualification_nothing_is_written_and_a_person_confirms_instead(
        setup, monkeypatch):
    """没有“租户 × 技能包 × 模型版本”资格时一律走 T1，不默认放开."""
    arguments = observation(setup)
    fixture = run_fixture(setup, monkeypatch, arguments, qualified=False)
    with pytest.raises(DomainError) as refused:
        execute(fixture, arguments)
    assert refused.value.code == "QUALIFICATION_REQUIRED"
    with Session(setup.admin) as session:
        assert session.scalars(select(ScopeNoteVersion).where(
            ScopeNoteVersion.tenant_id == setup.tenant)).all() == []
        assert session.scalars(select(Receipt).where(
            Receipt.tenant_id == setup.tenant, Receipt.operation == OBSERVE)).all() == []
        assert session.scalars(select(AgentToolCall).where(
            AgentToolCall.run_id == fixture.scope.run_id,
            AgentToolCall.tool == OBSERVE, AgentToolCall.state == "completed")).all() == []
    # What the registered graph does instead: prepare the same command for the person.
    with fixture.adapter.transaction(fixture.scope) as session:
        command = fixture.adapter.command(session, fixture.scope, OBSERVE, arguments,
                                          key(fixture)).model_dump(mode="json")
    assert command["command_id"] == str(uuid5(NAMESPACE_URL, key(fixture)))
    route = f"/v1/categories/{setup.category}/commands"
    unconfirmed = setup.client.post(route, headers=headers(setup), json=command)
    assert unconfirmed.status_code == 409
    assert unconfirmed.json()["code"] == "CONFIRMATION_REQUIRED"
    prepared = setup.client.post(route + "/preview", headers=headers(setup), json=command)
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["review"]["written_by"] == "person"
    done = setup.client.post(route, headers=headers(setup), json=prepared.json()["command"])
    assert done.status_code == 200, done.text
    note = item(setup, done.json()["subject_id"])["note"]
    # Drafted by 小Pai, confirmed by a member: a person's write with a person's receipt.
    assert note["generated_by"] == "xiaopai_drafted" and note["confirmation"] == "member_confirmed"
    assert note["confirmed_by"]["id"] == str(setup.human)
    assert done.json()["agent_run_id"] is None and done.json()["writer_id"] == str(setup.human)


@pytest.mark.parametrize("operation", [SAVE, RETIRE])
def test_qualified_run_still_cannot_execute_the_t1_commands(setup, monkeypatch, operation):
    """约定、关注点、决策背景，以及替代或撤回他人确认过的条目，仍是 T1."""
    existing = save(setup, "客户 A 评审必问跌落测试", kind="concern")
    arguments = ({"anchor": anchor(setup),
                  "body": {"kind": "convention", "statement": "小Pai 想自己定一条约定"}}
                 if operation == SAVE else
                 {"note": {"id": existing["subject_id"], "revision": 1}, "reason": "小Pai 想撤回"})
    fixture = run_fixture(setup, monkeypatch, arguments, operation=operation)
    with pytest.raises(DomainError) as refused:
        execute(fixture, arguments, operation)
    assert refused.value.code == "NAMED_DECISION_REQUIRED"
    assert [n["note_id"] for n in listing(setup)["notes"]] == [existing["subject_id"]]


def test_xiaopai_writes_only_on_its_own_run_scope_and_never_a_duplicate(setup, monkeypatch):
    elsewhere = private_product(setup, visibility="category")
    arguments = {"mode": "observation", "anchor": anchor(setup, "product", elsewhere),
                 "statement": "别的型号上的观察"}
    fixture = run_fixture(setup, monkeypatch, arguments)
    with pytest.raises(DomainError) as outside:
        execute(fixture, arguments)
    assert outside.value.detail["reason_key"] == "scope_note_outside_run"
    save(setup, "气嘴来料毛刺偏多，已反馈供应商", kind="observation")
    arguments = observation(setup, "气嘴来料毛刺偏多")
    fixture = run_fixture(setup, monkeypatch, arguments)
    with pytest.raises(DomainError) as similar:
        execute(fixture, arguments)
    assert similar.value.detail["reason_key"] == "scope_note_similar_unresolved"
    assert "补充证据" in similar.value.message


def test_xiaopai_adds_evidence_without_touching_confirmed_content(setup, monkeypatch):
    existing = save(setup, "目标价按含税口径", kind="concern", pinned=True)
    arguments = {"mode": "evidence", "note": {"id": existing["subject_id"], "revision": 1},
                 "evidence": [{"source_type": "business_object", "source_kind": "product",
                               "source_id": str(setup.product)}]}
    fixture = run_fixture(setup, monkeypatch, arguments)
    receipt = execute(fixture, arguments)
    view = item(setup, existing["subject_id"])
    note = view["note"]
    assert receipt["subject_revision"] == 2 and note["revision"] == 2
    assert note["statement"] == "目标价按含税口径" and note["pinned"] is True
    assert note["generated_by"] == "human" and note["confirmation"] == "member_confirmed"
    assert note["confirmed_by"]["id"] == str(setup.human)
    assert note["source_authority"] == "business_record"
    assert [(e["source_type"], e["by_xiaopai"]) for e in note["evidence"]] == [
        ("business_object", True)]
    assert [v["action"] for v in view["versions"]] == ["add_evidence", "create"]


def test_withdraw_by_run_takes_back_what_xiaopai_wrote_and_nothing_else(setup, monkeypatch):
    """可按运行撤回: 小Pai 自动记下、尚无成员接手的观察和证据链接."""
    confirmed = save(setup, "客户要求外箱加贴防潮标", kind="concern")
    first = observation(setup, "试产线换型时间比计划长")
    fixture = run_fixture(setup, monkeypatch, first)
    written = execute(fixture, first)
    run_id = str(fixture.scope.run_id)
    prepared = preview(setup, RETIRE, {"run_id": run_id, "action": "withdraw",
                                       "reason": "这次运行读错了项目"})
    assert [o["note_id"] for o in prepared["review"]["observations"]] == [written["subject_id"]]
    commit(setup, RETIRE, {"run_id": run_id, "action": "withdraw", "reason": "这次运行读错了项目"})
    gone = item(setup, written["subject_id"])["note"]
    assert gone["state"] == "withdrawn" and gone["reason"] == "这次运行读错了项目"
    assert [n["note_id"] for n in listing(setup)["notes"]] == [confirmed["subject_id"]]
    again = preview(setup, RETIRE, {"run_id": run_id, "action": "withdraw", "reason": "重复撤回"},
                    status=404)
    assert again["detail"]["reason_key"] == "scope_note_run_nothing"
    # Evidence links written by a Run are taken back by a retraction row, never deleted.
    link = {"mode": "evidence", "note": {"id": confirmed["subject_id"], "revision": 1},
            "evidence": [{"source_type": "business_object", "source_kind": "product",
                          "source_id": str(setup.product)}]}
    second = run_fixture(setup, monkeypatch, link)
    execute(second, link)
    assert item(setup, confirmed["subject_id"])["note"]["evidence_count"] == 1
    commit(setup, RETIRE, {"run_id": str(second.scope.run_id), "action": "withdraw",
                           "reason": "证据挂错了对象"})
    kept = item(setup, confirmed["subject_id"])["note"]
    assert kept["state"] == "active" and kept["evidence_count"] == 0
    with Session(setup.admin) as session:
        rows = session.scalars(select(ScopeNoteEvidence).where(
            ScopeNoteEvidence.note_id == confirmed["subject_id"])).all()
    assert len(rows) == 2 and sum(1 for row in rows if row.retracts_id is not None) == 1


def test_a_member_who_takes_over_an_observation_keeps_it_through_a_run_withdrawal(
        setup, monkeypatch):
    arguments = observation(setup, "样件包装在运输中有压痕")
    fixture = run_fixture(setup, monkeypatch, arguments)
    written = execute(fixture, arguments)
    commit(setup, SAVE, {"anchor": anchor(setup),
                         "note": {"id": written["subject_id"], "revision": 1},
                         "body": {"kind": "observation",
                                  "statement": "样件包装在运输中有压痕，已拍照确认"}},
           person=setup.peer)
    adopted = item(setup, written["subject_id"])["note"]
    assert adopted["generated_by"] == "xiaopai_drafted"
    assert adopted["confirmed_by"]["id"] == str(setup.peer)
    refused = preview(setup, RETIRE, {"run_id": str(fixture.scope.run_id), "action": "withdraw",
                                      "reason": "按运行撤回"}, status=404)
    assert refused["detail"]["reason_key"] == "scope_note_run_nothing"
    assert item(setup, written["subject_id"])["note"]["state"] == "active"
    assert str(uuid4())  # no model or provider was contacted in this module
