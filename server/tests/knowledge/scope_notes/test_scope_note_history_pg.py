"""D514: team notes are history dependencies, hidden like a revoked source (P32; P87).

A turn that carried a team note in its envelope, or got one back from
``memory.search``, is hidden in later history once that note is retired,
withdrawn or out of the reader's reach; a revision only annotates. A
continued Run that already took such a turn is stopped before its next model
call. The registered ``conversation.history`` and ``memory.search`` handlers
are what the model is sent, so the negative cases read through them.

Real Runs, real roles and row-level security; no model or embedding calls.
"""

import json
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.bootstrap import Bootstrap
from pdos_next.agent.kernel.models import AgentRun
from pdos_next.agent.kernel.persistence import KernelStore
from pdos_next.agent.memory import scope_assemble
from pdos_next.agent.memory.tool import memory_search
from pdos_next.core.models import Product
from pdos_next.errors import DomainError
from tests.agent.memory.support import scope, start
from tests.knowledge.scope_notes.support import RETIRE, SAVE, anchor, body, commit, headers, save

ANSWER = "合成结果：按团队约定，报告用英文。HISTORY-NOTE-MARKER"


def assemble(setup, run_id, *, requester=None):
    with KernelStore(setup.engine).transaction(
            scope(setup, run_id, requester=requester), lock=True) as (session, run):
        return scope_assemble.frozen(session, run)


def search(setup, run_id, query, *, requester=None, kinds=("scope_note",)):
    return memory_search(KernelStore(setup.engine))(
        scope(setup, run_id, requester=requester), {"query": query, "kinds": list(kinds)})


def finish(setup, run_id):
    with Session(setup.admin) as session, session.begin():
        row = session.get(AgentRun, run_id)
        row.state = "completed"
        row.result = {"summary": ANSWER, "unfinished": [], "result": {}}


def follow(setup, parent, *, person=None, goal="继续"):
    return start(setup, headers=headers(setup, person), goal=goal,
                 continue_from_run_id=str(parent))[0]


def turns(setup, run_id, *, requester=None):
    return Bootstrap(setup.engine).project_context(
        scope(setup, run_id, requester=requester), "继续")["conversation"]["turns"]


def read(setup, reader, session_id, *, requester=None):
    """Another Session's turns by Run, through the registered conversation.history tool."""
    value = Bootstrap(setup.engine).conversation_history(
        scope(setup, reader, requester=requester), {"session_id": session_id, "page_size": 10})
    return {turn["run_id"]: turn for turn in value["turns"]}


def session_of(setup, run_id):
    with Session(setup.admin) as session:
        return str(session.get(AgentRun, run_id).session_id)


def check(setup, run_id, *, requester=None):
    Bootstrap(setup.engine).check_conversation(scope(setup, run_id, requester=requester))


def test_a_retired_note_hides_the_turns_that_used_it_and_stops_the_continued_run(setup):
    carried = save(setup, "给该客户的报告一律英文")
    other = save(setup, "周报每周五发", kept=[carried["subject_id"]])
    # Turn one carried two notes in its envelope; turn two got a later one back from
    # memory.search (it assembled no envelope of its own).
    first, opened = start(setup, goal="起草评审报告")
    team, _recent = assemble(setup, first)
    assert len(team["conventions"]) == 2 and team["background"] == []
    finish(setup, first)
    found = save(setup, "跌落测试高度按 1.2 米执行", kind="concern")
    second = follow(setup, first, goal="跌落测试怎么做")
    assert [card["note_id"] for card in search(setup, second, "跌落测试 高度")[
        "scope_notes"]] == [found["subject_id"]]
    finish(setup, second)
    third = follow(setup, second)
    assert [turn["outcome_state"] for turn in turns(setup, third)] == ["current", "current"]
    check(setup, third)
    # The history manifest lists the notes, IDs and revisions only.
    with Session(setup.admin) as session:
        access = session.get(AgentRun, third).versions["conversation_access"]
    deps = {(item["id"], item.get("version")) for value in access.values()
            for item in value["dependencies"] if item["kind"] == "scope_note"}
    assert {(carried["subject_id"], 1), (found["subject_id"], 1),
            (other["subject_id"], 1)} <= deps
    assert "英文" not in json.dumps(access, ensure_ascii=False)
    # Later reads go through the registered conversation.history tool from another
    # Session: it classifies the same frozen manifests again at every call.
    reader = start(setup, goal="上次的评审报告")[0]

    def states():
        value = read(setup, reader, opened["session_id"])
        return [value[str(first)]["outcome_state"], value[str(second)]["outcome_state"]], value

    assert states()[0] == ["current", "current"]
    # A revision only annotates: the turn stays readable and the Run goes on.
    commit(setup, SAVE, {"anchor": anchor(setup), "note": {"id": other["subject_id"],
                                                           "revision": 1},
                         "body": body("周报每周五下班前发")})
    assert states()[0] == ["updated", "current"]
    check(setup, third)
    # Withdrawing the searched note hides the turn that got it back; the continued
    # Run that already took that turn stops before its next model call.
    commit(setup, RETIRE, {"note": {"id": found["subject_id"], "revision": 1},
                           "action": "withdraw", "reason": "记错了"})
    shown, value = states()
    assert shown == ["updated", "hidden"] and value[str(second)]["historical_outcome"] is None
    with pytest.raises(DomainError) as stop:
        check(setup, third)
    assert stop.value.reason == "CONVERSATION_HISTORY_REVOKED"
    assert stop.value.detail["run_ids"] == [str(second)]
    # Retiring the carried note hides the first turn too.
    commit(setup, RETIRE, {"note": {"id": carried["subject_id"], "revision": 1},
                           "action": "retire", "reason": "客户改用中文"})
    shown, value = states()
    assert shown == ["hidden", "hidden"]
    assert all(value[str(run)]["historical_outcome"] is None for run in (first, second))
    # Negative case through the registered tools: what conversation.history and
    # memory.search hand back is what the model is sent; nothing of it is there.
    history = Bootstrap(setup.engine).conversation_history(
        scope(setup, reader), {"session_id": opened["session_id"], "page_size": 5})
    recalled = search(setup, reader, "评审报告 英文", kinds=("episode", "scope_note"))
    assert recalled["scope_notes"] == []
    sent = json.dumps([history, recalled], ensure_ascii=False)
    assert "HISTORY-NOTE-MARKER" not in sent
    assert "给该客户的报告一律英文" not in sent and "1.2 米" not in sent


def test_a_note_put_out_of_reach_hides_the_peers_turn_but_not_the_owners(setup):
    target = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(Product(id=target, tenant_id=setup.tenant, category_id=setup.category,
                            name="Synthetic shared product", purpose="Scope note subject",
                            owner_id=setup.human, visibility="category"))
    save(setup, "这个型号的规格书以英文版为准", subject={"kind": "product", "id": str(target)})
    peer = start(setup, headers=headers(setup, setup.peer), goal="规格书用哪版")[0]
    assert len(assemble(setup, peer, requester=setup.peer)[0]["conventions"]) == 1
    finish(setup, peer)
    mine = start(setup, goal="规格书用哪版")[0]
    assert len(assemble(setup, mine)[0]["conventions"]) == 1
    finish(setup, mine)
    peer_next = follow(setup, peer, person=setup.peer)
    assert [t["outcome_state"] for t in turns(setup, peer_next, requester=setup.peer)] == [
        "current"]
    check(setup, peer_next, requester=setup.peer)
    with Session(setup.admin) as session, session.begin():
        session.get(Product, target).visibility = "private"
    # 撤权才隐藏: the peer can no longer read the note's subject, so the turn hides.
    with pytest.raises(DomainError) as stop:
        check(setup, peer_next, requester=setup.peer)
    assert stop.value.reason == "CONVERSATION_HISTORY_REVOKED"
    peer_reader = start(setup, headers=headers(setup, setup.peer), goal="另一个会话")[0]
    peer_session = session_of(setup, peer)
    assert read(setup, peer_reader, peer_session, requester=setup.peer)[str(peer)][
        "outcome_state"] == "hidden"
    # The owner still reads the subject and the note: their own history is unchanged.
    check(setup, follow(setup, mine))
    owner_reader = start(setup, goal="另一个会话")[0]
    assert read(setup, owner_reader, session_of(setup, mine))[str(mine)][
        "outcome_state"] == "current"


def test_the_shared_audience_check_counts_team_notes_as_read_sources(setup):
    """P62 第 3 项: one reader of the thread who cannot read a used note keeps it private."""
    from pdos_next.agent.kernel.conversation_acl import manifests
    from pdos_next.core.database import tenant_session
    from pdos_next.core.service import Context
    from pdos_next.domain.projects.discussions.agent_delivery import audience_check

    target = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(Product(id=target, tenant_id=setup.tenant, category_id=setup.category,
                            name="Synthetic owner-only product", purpose="Scope note subject",
                            owner_id=setup.human, visibility="private"))
    save(setup, "这个型号只发英文规格书", subject={"kind": "product", "id": str(target)})
    open_note = save(setup, "周报每周五发")
    run_id = start(setup, goal="规格书和周报")[0]
    assert len(assemble(setup, run_id)[0]["conventions"]) == 2
    finish(setup, run_id)
    ctx = Context(setup.tenant, setup.human, setup.human, category_id=setup.category)
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        requester_id=setup.human, category_id=setup.category,
                        read_snapshot=True) as session:
        run = session.get(AgentRun, run_id)
        manifest = manifests(session, [run])[str(run_id)]
        facts = type("RunFacts", (), {"requester_id": run.requester_id,
                                      "customer_identities": [], "data_categories": []})()
    assert {item["id"] for item in manifest["dependencies"]
            if item["kind"] == "scope_note"} >= {open_note["subject_id"]}
    covered, receipt = audience_check(setup.engine, ctx, facts, manifest,
                                      [setup.human, setup.peer])
    assert not covered and receipt["uncovered_members"] == 1
    assert receipt["uncovered_source_kinds"] == ["scope_note"]
    # The receipt names the kind of source only, never the note or its words.
    assert "英文" not in json.dumps(receipt, ensure_ascii=False)
    assert audience_check(setup.engine, ctx, facts, manifest, [setup.human])[0]
