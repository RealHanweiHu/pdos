"""Session-level memory controls (P121 第 8 项; D475 第 1 条): delete a Session, “本轮不记”.

No model or embedding provider calls. Every write goes through the real roles and
row-level security of the isolated pdos_test database.
"""

import json
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.bootstrap import Bootstrap
from pdos_next.agent.kernel.models import AgentRun
from pdos_next.agent.kernel.persistence import KernelStore
from pdos_next.agent.memory import assemble, candidates
from pdos_next.agent.memory.index import index_episode
from pdos_next.agent.memory.mode import latest
from pdos_next.agent.memory.models import (
    MemoryCandidate,
    MemoryEpisode,
    MemoryEpisodeMark,
    MemoryEpisodeVector,
    MemoryIndexEntry,
    MemorySessionDeletion,
)
from pdos_next.agent.memory.recall import catalog
from pdos_next.agent.memory.tool import memory_search
from pdos_next.core.database import tenant_session
from pdos_next.errors import DomainError
from tests.agent.memory.support import episode, finish, scope, start

GOAL = "比较三家气泵供应商的报价和交期"
TABLES = (MemoryEpisode, MemoryEpisodeMark, MemoryIndexEntry, MemoryEpisodeVector,
          MemoryCandidate)


def peer_headers(setup):
    return {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}


def search(setup, run_id, query="气泵供应商报价", **arguments):
    return memory_search(KernelStore(setup.engine))(
        scope(setup, run_id), {"query": query, **arguments})


def indexed(setup, run_id):
    row = episode(setup, run_id)
    index_episode(setup.engine, {"tenant_id": str(setup.tenant), "owner_id": str(row.owner_id),
                                 "episode_id": str(row.id)})
    return row


def deletion_path(setup, session_id):
    return f"/v1/categories/{setup.category}/agent-sessions/{session_id}/deletion"


def delete(setup, session_id, *, headers=None, key=None, status=200):
    response = setup.client.post(deletion_path(setup, session_id), headers=headers or setup.headers,
                                 json={"request_key": key or str(uuid4())})
    assert response.status_code == status, response.text
    return response.json()


def counts(setup, session_id):
    with Session(setup.admin) as session:
        return {model.__tablename__: session.scalar(
            select(func.count()).select_from(model).where(model.session_id == session_id))
            for model in TABLES}


def call_function(setup, session_id, *, actor, requester):
    with tenant_session(setup.engine, setup.tenant, actor_id=actor, requester_id=requester,
                        category_id=setup.category) as session:
        session.execute(text("SELECT id FROM memory_delete_session(:t,:s,:k,repeat('a',64))"),
                        {"t": setup.tenant, "s": session_id, "k": uuid4()})


def second_index_row(setup, row):
    """Another index row for the same episode, as a second source kind will be."""
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        category_id=setup.category) as session:
        session.execute(text(
            "INSERT INTO memory_index(id,tenant_id,created_at,owner_id,session_id,episode_id,"
            "source_kind,source_version,profile_version,idempotency_key,terms,term_counts,codes,"
            "token_count,tokenizer_version,code_rule_version) VALUES (:id,:tenant,now(),:owner,"
            ":session,:episode,'episode',1,'none',:key,to_tsvector('simple','交期'),"
            "CAST('{}' AS jsonb),ARRAY[]::text[],1,'second-kind','c')"
        ), {"id": uuid4(), "tenant": setup.tenant, "owner": row.owner_id,
            "session": row.session_id, "episode": row.id, "key": uuid4().hex + uuid4().hex})


def remembered_session(setup):
    """A finished Session with an episode, a pin, both index rows, a vector and a proposal."""
    from tests.agent.memory.test_memory_candidates_pg import explicit, finish_with
    from tests.agent.memory.test_memory_vectors_pg import embed, pending, profile

    run_id, started = start(setup, goal=f"记住：给这个客户的报告一律用英文。{GOAL}")
    with Session(setup.admin) as session:
        version = (session.get(AgentRun, run_id).versions.get("prompt_identities", {})
                   .get("main", {}).get("version"))
    original = candidates.MEMORY_CANDIDATE_PROMPT_VERSIONS
    candidates.MEMORY_CANDIDATE_PROMPT_VERSIONS = frozenset({version})
    try:
        assert finish_with(setup, run_id, [explicit(
            trigger="记住：给这个客户的报告一律用英文")]) == []
    finally:
        candidates.MEMORY_CANDIDATE_PROMPT_VERSIONS = original
    row = indexed(setup, run_id)  # Writes both index rows: own words, and the answer side.
    marks = f"/v1/categories/{setup.category}/memory/episodes/{run_id}/marks"
    assert setup.client.post(marks, headers=setup.headers, json={
        "request_key": str(uuid4()), "kind": "pin"}).status_code == 200
    provider, ports, _version = profile(setup, ["internal", "owner_session"])
    rows = [item for item in pending(setup) if item["episode_id"] == row.id]
    assert embed(setup, provider, ports, rows)["embedded"] == 1
    return run_id, started["session_id"], row


def test_owner_deletes_a_session_and_its_memory_rows_are_gone(setup):
    run_id, session_id, row = remembered_session(setup)
    assert counts(setup, session_id) == {
        "memory_episodes": 1, "memory_episode_marks": 1, "memory_index": 3,
        "memory_episode_vectors": 1, "memory_candidates": 1}
    with Session(setup.admin) as session:
        # s0_0888: own words and answer summary; s0_0894: focus-object titles.
        assert sorted(session.scalars(select(MemoryIndexEntry.source_kind).where(
            MemoryIndexEntry.episode_id == row.id))) == ["answer", "episode", "object"]
        assert session.scalar(select(MemoryIndexEntry.token_count).where(
            MemoryIndexEntry.episode_id == row.id,
            MemoryIndexEntry.source_kind == "answer")) > 0
    preview = setup.client.get(deletion_path(setup, session_id), headers=setup.headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["deleted"] is False and preview.json()["blocked"] is None
    assert preview.json()["will_remove"] == {
        "episodes": 1, "marks": 1, "index_rows": 3, "vectors": 1, "candidates": 1}
    assert preview.json()["kept"] == {"runs": 1, "receipts": 0, "adopted_notes": 0}
    key = str(uuid4())
    done = delete(setup, session_id, key=key)
    assert done["deleted"] is True and done["session_id"] == session_id
    assert done["removed"] == preview.json()["will_remove"]
    # The confirmation and the result say what is gone now, what expires, what stays.
    assert "立即清除" in done["notice"]["now"] and "30 天" in done["notice"]["by_retention"]
    assert "运行记录" in done["notice"]["kept"] and "还没有定" in done["notice"]["kept"]
    assert done["notice"] == preview.json()["notice"]
    assert set(counts(setup, session_id).values()) == {0}
    with Session(setup.admin) as session:
        stored = json.dumps([item.body for item in session.execute(text(
            "SELECT to_jsonb(d) AS body FROM memory_session_deletions d")).all()], default=str)
        assert session.scalar(select(func.count()).select_from(MemorySessionDeletion).where(
            MemorySessionDeletion.session_id == session_id)) == 1
        # Nothing of the owner's words is left in the memory layer.
        assert session.scalar(select(func.count()).select_from(MemoryIndexEntry).where(
            MemoryIndexEntry.episode_id == row.id,
            MemoryIndexEntry.source_kind.in_(["episode", "answer"]))) == 0
        for table in ("memory_episodes", "memory_index", "memory_episode_marks",
                      "memory_episode_vectors", "memory_candidates"):
            assert "供应商" not in json.dumps([item.body for item in session.execute(text(
                f"SELECT to_jsonb(x) AS body FROM {table} x WHERE x.tenant_id=:t"),
                {"t": setup.tenant}).all()], default=str)
        # The Run record stays (I17, P83 D193); the notice says so.
        assert session.get(AgentRun, run_id).state == "completed"
    assert "供应商" not in stored and "英文" not in stored
    assert delete(setup, session_id, key=key) == done  # Same request: same answer.
    assert delete(setup, session_id, status=404)["code"] == "NOT_FOUND"
    assert setup.client.get(deletion_path(setup, session_id),
                            headers=setup.headers).status_code == 404


def test_only_the_human_owner_deletes_their_own_session(setup):
    run_id, started = start(setup)
    finish(setup, run_id)
    row = indexed(setup, run_id)
    session_id = started["session_id"]
    assert delete(setup, session_id, headers=peer_headers(setup), status=404)["code"] == "NOT_FOUND"
    # The database function refuses the AI writer identity acting for the owner,
    # a colleague, and the AI identity on its own.
    for actor, requester in ((setup.agent, setup.human), (setup.peer, setup.peer),
                             (setup.agent, setup.agent), (setup.peer, setup.human)):
        with pytest.raises(DBAPIError, match="Only the human owner"):
            call_function(setup, session_id, actor=actor, requester=requester)
    # Nobody deletes memory rows or writes a deletion record directly.
    for actor in (setup.agent, setup.human):
        for statement in (
            "DELETE FROM memory_episodes WHERE id=:id",
            "DELETE FROM memory_index WHERE episode_id=:id",
            "INSERT INTO memory_session_deletions(id,tenant_id,created_at,owner_id,session_id,"
            "purged_episodes,purged_marks,purged_index_rows,purged_vectors,purged_candidates,"
            "request_key,request_sha256) VALUES (gen_random_uuid(),:t,now(),:o,:s,0,0,0,0,0,"
            "gen_random_uuid(),repeat('a',64))",
        ):
            with pytest.raises(DBAPIError, match="permission denied"):
                with tenant_session(setup.engine, setup.tenant, actor_id=actor,
                                    requester_id=setup.human,
                                    category_id=setup.category) as session:
                    session.execute(text(statement), {"id": row.id, "t": setup.tenant,
                                                      "o": setup.human, "s": session_id})
    # Even the table owner cannot delete rows of a Session that has no deletion record.
    with pytest.raises(DBAPIError, match="append-only"):
        with Session(setup.admin) as session, session.begin():
            session.execute(text("DELETE FROM memory_episodes WHERE id=:id"), {"id": row.id})
    assert counts(setup, session_id)["memory_episodes"] == 1
    # A deletion record itself cannot be changed or removed.
    delete(setup, session_id)
    for statement in ("UPDATE memory_session_deletions SET purged_episodes=0 WHERE session_id=:s",
                      "DELETE FROM memory_session_deletions WHERE session_id=:s"):
        with pytest.raises(DBAPIError, match="append-only"):
            with Session(setup.admin) as session, session.begin():
                session.execute(text(statement), {"s": session_id})
    # Other people never see that the owner deleted something.
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.peer,
                        category_id=setup.category) as session:
        assert session.scalar(select(func.count()).select_from(MemorySessionDeletion)) == 0


def test_deleted_session_is_gone_from_every_read(setup):
    earlier, first = start(setup)
    finish(setup, earlier)
    indexed(setup, earlier)
    session_id = first["session_id"]
    lists = (f"/v1/categories/{setup.category}/agent-conversations",
             f"/v1/categories/{setup.category}/agent-sessions")

    def listed(path, **params):
        response = setup.client.get(path, headers=setup.headers, params=params)
        assert response.status_code == 200, response.text
        return [item["session_id"] for item in response.json()["items"]]

    before, _ = start(setup, goal="上次那三家供应商后来定了哪家？")
    assert [item["run_id"] for item in search(setup, before)["items"]] == [str(earlier)]
    assert all(session_id in listed(path) for path in lists)
    assert listed(lists[0], q="气泵 供应商") == [session_id]
    assert listed(lists[0], q="比较三家") == [session_id]
    finish(setup, before)
    delete(setup, session_id)
    current, _ = start(setup, goal="气泵供应商")
    # memory.search: neither the index nor the scan of unindexed episodes finds it.
    found = search(setup, current)
    assert found["status"] == "completed"
    assert [item["run_id"] for item in found["items"]] == [str(before)]  # Another Session.
    assert GOAL not in json.dumps(found, ensure_ascii=False)
    with KernelStore(setup.engine).transaction(scope(setup, current), lock=True) as (s, run):
        value = catalog(s, run)
    assert value is None or str(earlier) not in json.dumps(value)
    with pytest.raises(DomainError) as refused:
        Bootstrap(setup.engine).conversation_history(
            scope(setup, current), {"session_id": session_id, "page_size": 5})
    assert refused.value.code == "FORBIDDEN_SCOPE"
    for path in lists:
        assert session_id not in listed(path)
        assert session_id not in listed(path, q="比较三家")  # Plain goal search.
        assert session_id not in listed(path, q="气泵 供应商")  # Keyword index search.
        assert session_id not in listed(path, q=session_id)
    assert session_id not in listed(lists[0], view="archived")
    base = f"/v1/categories/{setup.category}/agent-sessions/{session_id}"
    for path in ("/runs", "/memory-mode", "/work-state"):
        assert setup.client.get(base + path, headers=setup.headers).status_code == 404
    assert setup.client.post(base + "/presentation", headers=setup.headers, json={
        "expected_revision": 0, "request_key": str(uuid4()), "action": "pin"}).status_code == 404
    # It cannot be continued.
    response = setup.client.post(
        f"/v1/categories/{setup.category}/agent-runs", headers=setup.headers,
        json={"goal": "继续比较交期", "idempotency_key": str(uuid4()),
              "continue_from_run_id": str(earlier)})
    assert response.status_code == 404, response.text


def test_runs_that_drew_on_a_deleted_session_stop_before_the_next_model_call(setup):
    earlier, first = start(setup)
    finish(setup, earlier)
    indexed(setup, earlier)
    other, second = start(setup, goal="核对帐篷面料清单")
    # Its own answer text, so the answer-side index (s0_0888) does not match the query below.
    KernelStore(setup.engine).finish(scope(setup, other), {
        "status": "completed", "summary": "面料清单已核对。", "questions": [], "unfinished": [],
        "result": {"context_proposals": {"constraints": []}}})
    by_search, _ = start(setup, goal="上次那三家供应商后来定了哪家？")
    assert [item["run_id"] for item in search(setup, by_search)["items"]] == [str(earlier)]
    by_history, _ = start(setup, goal="上次怎么答的")
    host = Bootstrap(setup.engine)
    page = host.conversation_history(
        scope(setup, by_history), {"session_id": first["session_id"], "page_size": 5})
    assert [turn["run_id"] for turn in page["turns"]] == [str(earlier)]
    untouched, _ = start(setup, goal="另一件事")
    for run_id in (by_search, by_history, untouched):
        host.check_conversation(scope(setup, run_id))
    delete(setup, second["session_id"])  # An unrelated Session: nothing stops.
    for run_id in (by_search, by_history, untouched):
        host.check_conversation(scope(setup, run_id))
    delete(setup, first["session_id"])
    for run_id in (by_search, by_history):
        with pytest.raises(DomainError) as stopped:
            host.check_conversation(scope(setup, run_id))
        assert stopped.value.reason == "CONVERSATION_HISTORY_REVOKED"
        assert stopped.value.detail["session_ids"] == [first["session_id"]]
    host.check_conversation(scope(setup, untouched))
    # What the Run used is now reported as withheld, not shown.
    finish(setup, by_search)
    usage = setup.client.get(
        f"/v1/categories/{setup.category}/agent-runs/{by_search}/memory-usage",
        headers=setup.headers).json()
    assert usage["items"] == [] and usage["withheld"] == 1


def test_a_session_with_a_run_in_progress_is_not_deleted(setup):
    run_id, started = start(setup)
    session_id = started["session_id"]
    preview = setup.client.get(deletion_path(setup, session_id), headers=setup.headers).json()
    assert preview["blocked"]["reason_key"] == "session_run_active"
    refused = delete(setup, session_id, status=409)
    assert refused["detail"]["reason_key"] == "session_run_active"
    with pytest.raises(DBAPIError, match="Run in progress"):
        call_function(setup, session_id, actor=setup.human, requester=setup.human)
    finish(setup, run_id)
    assert delete(setup, session_id)["removed"]["episodes"] == 1


def test_background_work_never_writes_a_deleted_session_back(setup):
    run_id, started = start(setup)
    finish(setup, run_id)
    row = episode(setup, run_id)  # Not indexed yet: the background activity is late.
    session_id = started["session_id"]
    reference = {"tenant_id": str(setup.tenant), "owner_id": str(setup.human),
                 "episode_id": str(row.id)}
    with tenant_session(setup.dispatch, setup.tenant) as session:
        assert row.id in {item["episode_id"] for item in session.execute(text(
            "SELECT * FROM memory_pending_index_references(:t,'never-indexed',200)"),
            {"t": setup.tenant}).mappings()}
    delete(setup, session_id)
    with pytest.raises(DomainError):
        index_episode(setup.engine, reference)
    with tenant_session(setup.dispatch, setup.tenant) as session:
        pending_index = session.execute(text(
            "SELECT * FROM memory_pending_index_references(:t,'never-indexed',200)"),
            {"t": setup.tenant}).mappings().all()
        pending_vectors = session.execute(text(
            "SELECT * FROM memory_pending_vector_references(:t,200)"),
            {"t": setup.tenant}).mappings().all()
    assert row.id not in {item["episode_id"] for item in (*pending_index, *pending_vectors)}
    # The owner cannot put a mark or an index row back either: the episode is gone.
    with pytest.raises(DBAPIError):
        second_index_row(setup, row)
    assert set(counts(setup, session_id).values()) == {0}


def test_a_run_finishing_in_a_deleted_session_records_no_episode(setup):
    """The projection's own check, for a Run that slipped past the start check."""
    run_id, started = start(setup)
    with Session(setup.admin) as session, session.begin():
        # Synthetic fixture only: a deletion record while a Run is still active,
        # which memory_delete_session itself refuses.
        session.execute(text(
            "INSERT INTO memory_session_deletions(id,tenant_id,created_at,owner_id,session_id,"
            "purged_episodes,purged_marks,purged_index_rows,purged_vectors,purged_candidates,"
            "request_key,request_sha256) VALUES (gen_random_uuid(),:t,now(),:o,:s,0,0,0,0,0,"
            "gen_random_uuid(),repeat('a',64))"),
            {"t": setup.tenant, "o": setup.human, "s": started["session_id"]})
    finish(setup, run_id)
    assert episode(setup, run_id) is None


def add_note(setup, text_value):
    response = setup.client.post("/v1/personal/memory/notes", headers=setup.headers, json={
        "request_key": str(uuid4()),
        "note": {"kind": "convention", "text": text_value, "scope": {"kind": "global"}}})
    assert response.status_code == 200, response.text
    return response.json()["note"]


def frozen_notes(setup, run_id):
    with KernelStore(setup.engine).transaction(scope(setup, run_id), lock=True) as (s, run):
        return assemble.frozen(s, run)


def test_a_turn_marked_not_remembered_reads_and_leaves_nothing(setup, monkeypatch):
    from tests.agent.memory.test_memory_candidates_pg import explicit, finish_with

    add_note(setup, "回答先给结论，再列依据")
    earlier, first = start(setup)
    finish(setup, earlier)
    indexed(setup, earlier)
    other, second = start(setup, goal="整理气泵样件编号")
    finish(setup, other)
    off, started = start(setup, continue_from_run_id=str(other), memory_turn_off=True,
                         goal="记住：给这个客户的报告一律用英文。气泵供应商报价")
    assert started["session_id"] == second["session_id"]
    with Session(setup.admin) as session:
        run = session.get(AgentRun, off)
        assert run.versions["memory_mode"] == {"off": True, "turn": True}
        monkeypatch.setattr(candidates, "MEMORY_CANDIDATE_PROMPT_VERSIONS", frozenset({
            run.versions.get("prompt_identities", {}).get("main", {}).get("version")}))
        # The Session's own switch is untouched.
        assert latest(session, started["session_id"]) is None
    found = search(setup, off)
    assert found["status"] == "memory_off" and found["items"] == []
    assert "本轮" in found["message"] and "本会话" not in found["message"]
    assert frozen_notes(setup, off) is None
    host = Bootstrap(setup.engine)
    history = host.conversation_history(
        scope(setup, off), {"session_id": first["session_id"], "page_size": 5})
    assert history["status"] == "memory_off" and history["turns"] == []
    assert "本轮" in history["message"]
    with KernelStore(setup.engine).transaction(scope(setup, off), lock=True) as (s, run):
        assert catalog(s, run) is None
    with Session(setup.admin) as session:
        assert "memory_usage" not in session.get(AgentRun, off).versions
    rejected = finish_with(setup, off, [explicit(
        trigger="记住：给这个客户的报告一律用英文")])
    assert rejected and episode(setup, off) is None
    with Session(setup.admin) as session:
        assert session.scalar(select(func.count()).select_from(MemoryCandidate).where(
            MemoryCandidate.run_id == off)) == 0
    # The next turn follows the Session again: it reads memory and is recorded.
    following, _ = start(setup, continue_from_run_id=str(off), goal="气泵供应商报价对比")
    with Session(setup.admin) as session:
        assert "memory_mode" not in session.get(AgentRun, following).versions
    assert str(earlier) in [item["run_id"] for item in search(setup, following)["items"]]
    assert frozen_notes(setup, following)["constraints"]
    finish(setup, following)
    assert episode(setup, following) is not None
    # Other Sessions never see the turn that was not remembered.
    reader, _ = start(setup, goal="上次怎么答的")
    page = host.conversation_history(
        scope(setup, reader), {"session_id": second["session_id"], "page_size": 5})
    assert [turn["run_id"] for turn in page["turns"]] == [str(following), str(other)]
    assert off not in [item["run_id"] for item in search(setup, reader)["items"]]


def test_turn_switch_accepts_only_true_and_works_on_a_first_turn(setup):
    response = setup.client.post(
        f"/v1/categories/{setup.category}/agent-runs", headers=setup.headers,
        json={"goal": GOAL, "idempotency_key": str(uuid4()), "memory_turn_off": False})
    assert response.status_code == 422, response.text
    run_id, started = start(setup, memory_turn_off=True)
    finish(setup, run_id)
    assert episode(setup, run_id) is None
    mode = setup.client.get(
        f"/v1/categories/{setup.category}/agent-sessions/{started['session_id']}/memory-mode",
        headers=setup.headers).json()
    assert mode["memory_off"] is False and mode["revision"] == 0
    # With the Session switch as well, the Session switch is what is frozen.
    both, _ = start(setup, memory_off=True, memory_turn_off=True)
    with Session(setup.admin) as session:
        assert session.get(AgentRun, both).versions["memory_mode"] == {"off": True}


def test_episode_usage_lists_the_personal_notes_used_without_their_text(setup):
    note = add_note(setup, "气泵报价按含税价比较")
    run_id, _ = start(setup, goal="气泵报价")
    assert frozen_notes(setup, run_id)["constraints"][0]["note_id"] == note["note_id"]
    finish(setup, run_id)
    row = episode(setup, run_id)
    assert row.projection_version == "memory-episode/v2"
    assert row.body["usage"] == {"episodes": [], "sessions": [], "notes": [
        {"note_id": note["note_id"], "revision": 1, "zone": "constraints"}]}
    assert "含税价" not in json.dumps(row.body, ensure_ascii=False)
    plain, _ = start(setup, personal=True, goal="没有用到条目", memory_turn_off=True)
    finish(setup, plain, personal=True)
    assert episode(setup, plain) is None


def test_scope_options_list_only_readable_products_and_proposals(setup):
    """D301: the “我的记忆” page offers product and proposal scopes from this list."""
    path = "/v1/personal/memory/scope-options"
    listed = setup.client.get(path, headers=setup.headers, params={"kind": "product"})
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == [
        {"id": str(setup.product), "label": "Synthetic product · 汽车充气泵"}]
    assert setup.client.get(path, headers=setup.headers, params={
        "kind": "product", "query": "没有这个产品"}).json()["items"] == []
    assert setup.client.get(path, headers=setup.headers,
                            params={"kind": "proposal"}).json()["items"] == []
    other = {"Authorization": f"Bearer {setup.tokens[setup.other_human]}"}
    assert setup.client.get(path, headers=other, params={"kind": "product"}).json()["items"] == []
    assert setup.client.get(path, headers=setup.headers,
                            params={"kind": "category"}).status_code == 422
    # The listed product is accepted as a note's scope.
    saved = setup.client.post("/v1/personal/memory/notes", headers=setup.headers, json={
        "request_key": str(uuid4()), "note": {
            "kind": "background", "text": "这个型号的客户最看重噪音",
            "scope": {"kind": "product", "id": str(setup.product)}}})
    assert saved.status_code == 200, saved.text
    assert saved.json()["note"]["scope"]["kind"] == "product"
