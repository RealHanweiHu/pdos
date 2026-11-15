"""Cross-session recall and its gates (AT-71, AT-74 降级部分, P85). No provider calls."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.bootstrap import Bootstrap
from pdos_next.agent.kernel.models import AgentRun
from pdos_next.agent.kernel.persistence import KernelStore
from pdos_next.agent.memory.index import index_episode
from pdos_next.agent.memory.recall import catalog, frozen_catalog
from pdos_next.agent.memory.tool import memory_search
from pdos_next.errors import DomainError
from tests.agent.memory.support import episode, finish, scope, start

PEER = "比较三家气泵供应商的报价和交期（同事的会话）"


def search(setup, run_id, *, requester=None, personal=False, **arguments):
    return memory_search(KernelStore(setup.engine))(
        scope(setup, run_id, requester=requester, personal=personal),
        {"query": "气泵供应商报价", **arguments},
    )


def indexed(setup, run_id):
    row = episode(setup, run_id)
    index_episode(setup.engine, {"tenant_id": str(setup.tenant), "owner_id": str(row.owner_id),
                                 "episode_id": str(row.id)})
    return row


def peer_headers(setup):
    return {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}


def test_last_weeks_plan_is_found_and_other_peoples_memory_never_appears(setup):
    earlier, first = start(setup)
    finish(setup, earlier)
    indexed(setup, earlier)
    other, _ = answered(setup, "整理样件编号规则", "编号规则已整理成表。", unfinished=())
    indexed(setup, other)
    peer_run, _ = start(setup, headers=peer_headers(setup), goal=PEER)
    finish(setup, peer_run, requester=setup.peer)
    indexed(setup, peer_run)
    current, second = start(setup, goal="上次那三家供应商后来定了哪家？")
    assert second["session_id"] != first["session_id"]
    result = search(setup, current)
    ids = [item["run_id"] for item in result["items"]]
    assert result["status"] == "completed" and ids[:5].count(str(earlier)) == 1
    assert str(peer_run) not in ids and str(current) not in ids and str(other) not in ids
    card = result["items"][0]
    assert card["session_id"] == first["session_id"]
    assert card["scope"] == {"kind": "category", "id": str(setup.category), "title": "汽车充气泵"}
    assert card["goal"] == "比较三家气泵供应商的报价和交期"
    assert result["retrieval"]["channels"] == ["keyword"]
    assert result["retrieval"]["semantic"]["status"] == "not_enabled"
    assert "不是业务事实" in result["fact_policy"]
    # The usage list is a server fact on the Run, not a model claim.
    with Session(setup.admin) as session:
        usage = session.get(AgentRun, current).versions["memory_usage"]
    assert usage["episodes"] == [str(earlier)] and str(earlier) in usage["access"]
    # The colleague sees only their own record, and never the owner's.
    peer_current, _ = start(setup, headers=peer_headers(setup), goal="气泵供应商")
    peer_found = search(setup, peer_current, requester=setup.peer)
    peer_ids = [item["run_id"] for item in peer_found["items"]]
    assert peer_ids == [str(peer_run)]


def test_index_lag_is_not_a_fake_zero_result(setup):
    earlier, _ = start(setup)
    finish(setup, earlier)  # Not indexed: the background activity has not run yet.
    current, _ = start(setup, goal="气泵供应商")
    result = search(setup, current)
    assert [item["run_id"] for item in result["items"]] == [str(earlier)]
    assert result["retrieval"]["index_pending"] >= 1
    # Indexing is idempotent on source + version + profile version.
    row = episode(setup, earlier)
    reference = {"tenant_id": str(setup.tenant), "owner_id": str(setup.human),
                 "episode_id": str(row.id)}
    assert index_episode(setup.engine, reference)["indexed"] is True
    assert index_episode(setup.engine, reference)["indexed"] is False
    # The AI writer identity cannot index on the owner's behalf.
    with pytest.raises(DomainError):
        index_episode(setup.engine, {**reference, "owner_id": str(setup.agent)})


def test_archived_session_and_hidden_episode_leave_recall(setup):
    earlier, first = start(setup)
    finish(setup, earlier)
    indexed(setup, earlier)
    current, _ = start(setup, goal="气泵供应商")
    assert search(setup, current)["returned"] == 1
    path = f"/v1/categories/{setup.category}/agent-sessions/{first['session_id']}/presentation"
    response = setup.client.post(path, headers=setup.headers, json={
        "expected_revision": 0, "request_key": str(uuid4()), "action": "archive"})
    assert response.status_code == 200, response.text
    later, _ = start(setup, goal="气泵供应商")
    assert search(setup, later)["returned"] == 0
    response = setup.client.post(path, headers=setup.headers, json={
        "expected_revision": 1, "request_key": str(uuid4()), "action": "restore"})
    assert response.status_code == 200, response.text
    marks = f"/v1/categories/{setup.category}/memory/episodes/{earlier}/marks"
    response = setup.client.post(marks, headers=setup.headers, json={
        "request_key": str(uuid4()), "kind": "hide"})
    assert response.status_code == 200, response.text
    last, _ = start(setup, goal="气泵供应商")
    assert search(setup, last)["returned"] == 0


def test_memory_off_session_reads_nothing_and_writes_nothing(setup):
    earlier, first = start(setup)
    finish(setup, earlier)
    indexed(setup, earlier)
    current, second = start(setup, goal="气泵供应商", memory_off=True)
    result = search(setup, current)
    assert result["status"] == "memory_off" and result["items"] == []
    host = Bootstrap(setup.engine)
    history = host.conversation_history(
        scope(setup, current), {"session_id": first["session_id"], "page_size": 5})
    assert history["status"] == "memory_off" and history["turns"] == []
    with KernelStore(setup.engine).transaction(scope(setup, current), lock=True) as (s, run):
        assert catalog(s, run) is None
    with Session(setup.admin) as session:
        assert "memory_usage" not in session.get(AgentRun, current).versions
    finish(setup, current)
    assert episode(setup, current) is None
    # The off Session cannot be pulled into another Session either.
    later, _ = start(setup, goal="气泵供应商")
    with pytest.raises(DomainError) as refused:
        host.conversation_history(scope(setup, later),
                                  {"session_id": second["session_id"], "page_size": 5})
    assert refused.value.code == "FORBIDDEN_SCOPE"


def test_switching_memory_off_through_the_session_setting(setup):
    run_id, started = start(setup)
    path = f"/v1/categories/{setup.category}/agent-sessions/{started['session_id']}/memory-mode"
    assert setup.client.get(path, headers=setup.headers).json()["memory_off"] is False
    data = {"expected_revision": 0, "request_key": str(uuid4()), "memory_off": True}
    response = setup.client.post(path, headers=setup.headers, json=data)
    assert response.status_code == 200, response.text
    assert response.json()["memory_off"] is True and response.json()["revision"] == 1
    assert setup.client.post(path, headers=setup.headers, json=data).json()["revision"] == 1
    stale = setup.client.post(
        path, headers=setup.headers, json={**data, "request_key": str(uuid4())})
    assert stale.status_code == 409
    other = setup.client.post(path, headers=peer_headers(setup), json={
        "expected_revision": 1, "request_key": str(uuid4()), "memory_off": False})
    assert other.status_code in {403, 404}
    finish(setup, run_id)  # Switched off mid-run: this Run records nothing either.
    assert episode(setup, run_id) is None


def test_cross_session_history_reads_only_own_sessions(setup):
    earlier, first = start(setup)
    finish(setup, earlier)
    peer_run, peer = start(setup, headers=peer_headers(setup), goal=PEER)
    finish(setup, peer_run, requester=setup.peer)
    current, _ = start(setup, goal="上次那三家供应商")
    host = Bootstrap(setup.engine)
    page = host.conversation_history(scope(setup, current),
                                     {"session_id": first["session_id"], "page_size": 5})
    assert page["memory_record"] is True and page["session_id"] == first["session_id"]
    assert [turn["run_id"] for turn in page["turns"]] == [str(earlier)]
    assert page["turns"][0]["outcome_state"] == "current"
    assert "已比较报价" in page["turns"][0]["historical_outcome"]["summary"]
    with pytest.raises(DomainError) as refused:
        host.conversation_history(scope(setup, current),
                                  {"session_id": peer["session_id"], "page_size": 5})
    assert refused.value.code == "FORBIDDEN_SCOPE"
    with Session(setup.admin) as session:
        usage = session.get(AgentRun, current).versions["memory_usage"]
    assert usage["sessions"] == [first["session_id"]]


def test_cross_session_history_returns_no_page_material_and_no_words_of_an_uncovered_turn(setup):
    """D483: what the registered tool hands back is what the model is sent."""
    import json

    from sqlalchemy import text

    from pdos_next.agent.kernel.work_state import PAGE_MATERIAL_BOUNDARY

    marker, private_words = "PAGE-MATERIAL-7F3A", "私有提案的目标成本"
    earlier, first = start(setup, goal="比较三家气泵供应商的报价和交期"
                           + PAGE_MATERIAL_BOUNDARY + marker)
    finish(setup, earlier)
    private, second = start(setup, goal=private_words + PAGE_MATERIAL_BOUNDARY + marker)
    with Session(setup.admin) as session, session.begin():
        # Synthetic fixture only: mark this Run as private, as a private-proposal Run is.
        session.execute(text("SET LOCAL session_replication_role = replica"))
        session.get(AgentRun, private).private_context = True
    finish(setup, private)
    current, _ = start(setup, goal="上次那三家供应商")
    host = Bootstrap(setup.engine)
    covered = host.conversation_history(scope(setup, current),
                                        {"session_id": first["session_id"], "page_size": 5})
    assert covered["turns"][0]["goal"] == "比较三家气泵供应商的报价和交期"
    assert covered["turns"][0]["outcome_state"] == "current"
    withheld = host.conversation_history(scope(setup, current),
                                         {"session_id": second["session_id"], "page_size": 5})
    turn = withheld["turns"][0]
    assert turn["outcome_state"] == "hidden" and turn["historical_outcome"] is None
    assert set(turn) == {"run_id", "status", "historical_outcome", "outcome_state", "note",
                         "sources", "original_record"}
    sent = json.dumps([covered, withheld], ensure_ascii=False)
    assert marker not in sent and private_words not in sent


def test_recent_catalog_is_background_same_scope_and_never_for_personal_runs(setup):
    for goal in ("比较三家气泵供应商的报价和交期", "整理气泵样件编号", "核对气泵噪音测试工况",
                 "汇总气泵客户关注点"):
        identity, _ = start(setup, goal=goal)
        finish(setup, identity)
    current, _ = start(setup, goal="继续")
    with KernelStore(setup.engine).transaction(scope(setup, current), lock=True) as (s, run):
        value = frozen_catalog(s, run)
    assert value["zone"] == "background" and "不是业务事实" in value["label"]
    assert [item["goal"] for item in value["recent_episodes"]] == [
        "汇总气泵客户关注点", "核对气泵噪音测试工况", "整理气泵样件编号"]
    import json

    from pdos_next.agent.kernel.context_budget import estimate_tokens

    assert estimate_tokens(json.dumps(value, ensure_ascii=False)) <= 300
    with KernelStore(setup.engine).transaction(scope(setup, current), lock=True) as (s, run):
        assert frozen_catalog(s, run) == value  # Frozen for the Run.
    personal, _ = start(setup, personal=True, goal="继续")
    with KernelStore(setup.engine).transaction(
        scope(setup, personal, personal=True), lock=True,
    ) as (s, run):
        assert catalog(s, run) is None
    # The catalog fits the combined context contract and lands in the envelope.
    from pdos_next.agent.kernel.context_projection import project
    from pdos_next.agent.memory.recall import CONTEXT_SCHEMA

    schema = {"type": "object", "properties": {"memory": CONTEXT_SCHEMA},
              "additionalProperties": False, "$defs": {}}
    projected, omitted, issues = project({"memory": value}, schema)
    assert projected == {"memory": value} and omitted == issues == []
    host = Bootstrap(setup.engine)
    from pdos_next.agent.kernel.host import BoundHost

    envelope = BoundHost(host.store, host.adapters()).skill_context(
        scope(setup, current), "继续", bindings=())
    assert envelope["context"]["memory"] == value


def test_dingtalk_and_automation_runs_read_no_personal_memory():
    from types import SimpleNamespace

    from pdos_next.agent.memory.recall import unavailable

    base = dict(project_id=None, proposal_id=None, product_id=None, category_id=uuid4())
    channel = SimpleNamespace(trigger="conversation", versions={"dingtalk": {"x": 1}}, **base)
    assert unavailable(channel, None)[0] == "channel_excluded"
    assert catalog(None, channel) is None  # Decided before any query.
    service = SimpleNamespace(trigger="automation_service", versions={}, **base)
    assert unavailable(service, None)[0] == "not_conversation"


def test_revoked_source_hides_the_episode_and_stops_further_sending(setup):
    from pdos_next.core.models import ObjectAudience
    from tests.agent.enterprise_search.test_assistant_pg import SyntheticClient, execute, fixture
    from tests.agent.enterprise_search.test_retrieval_pg import index
    from tests.categories.preproject.test_g0 import post, request

    registered = post(setup, request(setup, "evidence.artifact.register", {
        "title": "漏气受众共享历史记录", "content": "更换密封圈。RAW_ONLY_CHILD_MARKER",
        "source_label": "合成当前受众", "visibility": "audience",
    }), actor=setup.peer)
    assert registered.status_code == 200, registered.text
    identity = UUID(registered.json()["subject_id"])
    with Session(setup.admin) as session, session.begin():
        audience = ObjectAudience(tenant_id=setup.tenant, category_id=setup.category,
            object_type="artifact_versions", subject_id=identity, owner_id=setup.peer,
            principal_id=setup.human)
        session.add(audience)
        session.flush()
        audience_id = audience.id
    index(setup, identity)
    _reader, actual, main_host, _adapter = fixture(setup, SyntheticClient())
    assert execute(_reader, actual, main_host)["status"] == "completed"
    origin = indexed(setup, actual.run_id)
    assert origin.goal == "以前漏气怎么处理？"
    current, _ = start(setup, personal=True, goal="漏气")
    found = memory_search(KernelStore(setup.engine))(
        scope(setup, current, personal=True), {"query": "漏气"})
    assert [item["run_id"] for item in found["items"]] == [str(actual.run_id)]
    owner = Bootstrap(setup.engine)
    owner.check_conversation(scope(setup, current, personal=True))
    with Session(setup.admin) as session, session.begin():
        session.delete(session.get(ObjectAudience, audience_id))
    with pytest.raises(DomainError) as failure:
        owner.check_conversation(scope(setup, current, personal=True))
    assert failure.value.reason == "CONVERSATION_HISTORY_REVOKED"
    later, _ = start(setup, personal=True, goal="漏气")
    again = memory_search(KernelStore(setup.engine))(
        scope(setup, later, personal=True), {"query": "漏气"})
    assert again["items"] == [] and "密封圈" not in str(again)


def test_session_list_search_uses_the_same_keyword_index(setup):
    earlier, first = start(setup)
    finish(setup, earlier)
    path = f"/v1/categories/{setup.category}/agent-conversations"

    def found(q):
        response = setup.client.get(path, headers=setup.headers, params={"q": q})
        assert response.status_code == 200, response.text
        return [item["session_id"] for item in response.json()["items"]]

    # Not a contiguous substring, so only the episode index can match it.
    assert found("气泵 供应商") == []  # Not indexed yet: plain title/goal search only.
    indexed(setup, earlier)
    assert found("气泵 供应商") == [first["session_id"]]
    assert found("气泵 帐篷") == []  # Every word must match.
    peer_run, _ = start(setup, headers=peer_headers(setup), goal=PEER)
    finish(setup, peer_run, requester=setup.peer)
    indexed(setup, peer_run)
    assert found("同事") == []  # Another person's words never match my list.


# --- D482 (P121 第 1 项): an old conclusion is found by the words of its conclusion. ---

CAUSE = "结论：外壳缩水来自保压不足，建议把保压时间加到 8 秒。"


def answered(setup, goal, summary=CAUSE, *, unfinished=("复测翘曲",), **kwargs):
    run_id, body = start(setup, goal=goal, **kwargs)
    KernelStore(setup.engine).finish(scope(setup, run_id), {
        "status": "completed", "summary": summary, "questions": [],
        "unfinished": list(unfinished), "result": {"context_proposals": {"constraints": []}},
    })
    return run_id, body


def reference(setup, run_id):
    row = episode(setup, run_id)
    return {"tenant_id": str(setup.tenant), "owner_id": str(row.owner_id),
            "episode_id": str(row.id)}


@pytest.mark.parametrize("index_first", [True, False])
def test_an_old_conclusion_is_found_by_the_words_of_its_answer(setup, index_first):
    earlier, first = answered(setup, "分析注塑件不良的原因")
    other, _ = answered(setup, "整理样件编号规则", "编号规则已整理成表。", unfinished=())
    if index_first:
        assert index_episode(setup.engine, reference(setup, earlier))["rows"] == [
            "episode", "answer", "object"]
        index_episode(setup.engine, reference(setup, other))
    current, _ = start(setup, goal="上次外壳缩水是什么原因？")
    result = search(setup, current, query="外壳缩水 保压")
    assert [item["run_id"] for item in result["items"]] == [str(earlier)]
    assert result["retrieval"]["index_pending"] == (0 if index_first else 2)
    card = result["items"][0]
    assert card["goal"] == "分析注塑件不良的原因" and card["matched_in"] == ["answer"]
    assert card["answer"]["excerpt"] == CAUSE and card["answer"]["truncated"] is False
    assert "不能作为依据引用" in card["answer"]["label"]
    assert "不能作为回答依据引用" in result["fact_policy"]
    # The unfinished items are on the answer side too; the shared scope title is not indexed.
    assert search(setup, current, query="复测翘曲")["items"][0]["matched_in"] == ["answer"]
    assert search(setup, current, query="汽车充气泵")["items"] == []
    # Own words still match as before, and say so.
    own = search(setup, current, query="注塑件不良")
    assert own["items"][0]["run_id"] == str(earlier)
    assert own["items"][0]["matched_in"] == ["own_words"]


def test_the_session_list_search_still_matches_own_words_only(setup):
    earlier, first = answered(setup, "分析注塑件不良的原因")
    index_episode(setup.engine, reference(setup, earlier))
    path = f"/v1/categories/{setup.category}/agent-conversations"

    def found(q):
        response = setup.client.get(path, headers=setup.headers, params={"q": q})
        assert response.status_code == 200, response.text
        return [item["session_id"] for item in response.json()["items"]]

    assert found("注塑件 原因") == [first["session_id"]]
    assert found("缩水 保压") == []


def test_no_answer_of_the_models_own_is_indexed_or_shown(setup):
    withheld, _ = answered(setup, "分析注塑件不良的原因", "结果未通过完整核对。", unfinished=())
    spent, _ = answered(setup, "核对气泵噪音", "运行预算已用完，保留已完成动作与已核对结果。",
                        unfinished=())
    for run_id in (withheld, spent):
        index_episode(setup.engine, reference(setup, run_id))
    current, _ = start(setup, goal="继续")
    assert search(setup, current, query="核对 结果 预算")["items"][0]["run_id"] == str(spent)
    found = search(setup, current, query="注塑件 核对")
    assert all("answer" not in item for item in found["items"])
    assert all(item["matched_in"] == ["own_words"] for item in found["items"])


def test_an_answer_of_a_wider_outbound_class_is_not_found_by_its_words(setup):
    from sqlalchemy import text

    private, _ = start(setup, goal="私有提案的目标成本")
    with Session(setup.admin) as session, session.begin():
        # Synthetic fixture only: mark this Run as private, as a private-proposal Run is.
        session.execute(text("SET LOCAL session_replication_role = replica"))
        session.get(AgentRun, private).private_context = True
    KernelStore(setup.engine).finish(scope(setup, private), {
        "status": "completed", "summary": CAUSE, "questions": [], "unfinished": [],
        "result": {"context_proposals": {"constraints": []}}})
    index_episode(setup.engine, reference(setup, private))
    current, _ = start(setup, goal="上次外壳缩水是什么原因？")
    result = search(setup, current, query="外壳缩水 保压")
    assert result["items"] == [] and "缩水" not in str(result["items"])


# Episodes indexed before s0_0888 (own words only) and before s0_0890 (no object row).
@pytest.mark.parametrize("older", [("episode",), ("episode", "answer")])
def test_an_episode_indexed_before_the_answer_row_existed_is_pending_until_it_has_one(
        setup, monkeypatch, older):
    from sqlalchemy import text

    from pdos_next.agent.enterprise_search.tokenizer import version
    from pdos_next.agent.memory import index

    earlier, _ = answered(setup, "分析注塑件不良的原因")
    monkeypatch.setattr(index, "KINDS", older)
    assert index_episode(setup.engine, reference(setup, earlier))["rows"] == list(older)
    monkeypatch.undo()

    def pending():
        with Session(setup.admin) as session, session.begin():
            session.execute(text("SELECT set_config('pdos.tenant_id',:t,true)"),
                            {"t": str(setup.tenant)})
            return [row.episode_id for row in session.execute(text(
                "SELECT * FROM memory_pending_index_references(:t,:v,100)"),
                {"t": setup.tenant, "v": version()})]

    row = episode(setup, earlier)
    assert pending() == [row.id]
    current, _ = start(setup, goal="上次外壳缩水是什么原因？")
    lagging = search(setup, current, query="外壳缩水")  # Found by the lag scan meanwhile.
    assert [item["run_id"] for item in lagging["items"]] == [str(earlier)]
    assert lagging["retrieval"]["index_pending"] == 1
    assert index_episode(setup.engine, reference(setup, earlier))["rows"] == [
        kind for kind in index.KINDS if kind not in older]
    assert pending() == []
    assert search(setup, current, query="外壳缩水")["retrieval"]["index_pending"] == 0


# --- D482 余项 ① (P121 第 1 项): titles of the specific objects a Run focused on. ---

TITLE = "注塑模具冷却水路图纸（第三版）"


def material(setup, title=TITLE):
    """A synthetic category material a peer registered; the owner can read it."""
    from tests.categories.preproject.test_g0 import post, request

    registered = post(setup, request(setup, "evidence.artifact.register", {
        "title": title, "content": "合成正文，仅用于对象标题索引验证。",
        "source_label": "合成资料", "visibility": "category",
    }), actor=setup.peer)
    assert registered.status_code == 200, registered.text
    return UUID(registered.json()["subject_id"])


def withdraw(setup, artifact):
    from sqlalchemy import text

    from pdos_next.core.models import Artifact

    with Session(setup.admin) as session, session.begin():
        # Synthetic fixture only: the material is withdrawn, as a withdrawal leaves it.
        session.execute(text("SET LOCAL session_replication_role = replica"))
        session.get(Artifact, artifact).status = "withdrawn"


def object_row(setup, run_id):
    from sqlalchemy import select

    from pdos_next.agent.memory.models import MemoryIndexEntry

    with Session(setup.admin) as session:
        return session.scalar(select(MemoryIndexEntry).where(
            MemoryIndexEntry.episode_id == episode(setup, run_id).id,
            MemoryIndexEntry.source_kind == "object"))


def read_material(setup, goal, artifact):
    return answered(setup, goal, "已核对，没有发现问题。", unfinished=(),
                    sources=[{"artifact_id": str(artifact), "expected_revision": 1}])


@pytest.mark.parametrize("index_first", [True, False])
def test_a_run_is_found_by_the_title_of_the_material_it_read(setup, index_first):
    artifact = material(setup)
    earlier, first = read_material(setup, "帮我看一下这份资料有没有问题", artifact)
    other, _ = answered(setup, "整理样件编号规则", "编号规则已整理成表。", unfinished=())
    assert [item["kind"] for item in episode(setup, earlier).body["focus_objects"]].count(
        "artifact") == 1
    if index_first:
        for run_id in (earlier, other):
            assert index_episode(setup.engine, reference(setup, run_id))["rows"] == [
                "episode", "answer", "object"]
        assert object_row(setup, earlier).token_count > 0
        assert object_row(setup, other).token_count == 0  # Scope titles are not indexed.
    current, _ = start(setup, goal="上次看冷却水路图纸的那次")
    result = search(setup, current, query="冷却水路图纸")
    assert [item["run_id"] for item in result["items"]] == [str(earlier)]
    assert result["items"][0]["matched_in"] == ["object_title"]
    assert result["retrieval"]["index_pending"] == (0 if index_first else 2)
    assert TITLE not in str(result)  # The card says what matched, not the title itself.
    # The owner's Session list search still matches own words only.
    path = f"/v1/categories/{setup.category}/agent-conversations"
    listed = setup.client.get(path, headers=setup.headers, params={"q": "冷却 水路 图纸"})
    assert listed.status_code == 200, listed.text
    assert first["session_id"] not in [item["session_id"] for item in listed.json()["items"]]


def test_an_unreadable_object_title_is_not_indexed_and_a_revoked_one_hides_the_episode(setup):
    hidden = material(setup, "密封圈供应商对比表")
    unread, _ = read_material(setup, "看看这份对比表", hidden)
    withdraw(setup, hidden)
    # Gone before indexing: the owner cannot read it, so its title is not taken in.
    index_episode(setup.engine, reference(setup, unread))
    assert object_row(setup, unread).token_count == 0
    artifact = material(setup)
    earlier, _ = read_material(setup, "帮我看一下这份资料有没有问题", artifact)
    index_episode(setup.engine, reference(setup, earlier))
    assert object_row(setup, earlier).token_count > 0
    current, _ = start(setup, goal="冷却水路图纸")
    assert [item["run_id"] for item in search(setup, current, query="冷却水路图纸")["items"]] == [
        str(earlier)]
    # Gone after indexing: the title is still in the row, but memory.search's
    # per-item recheck against the dependency manifest drops the episode, unannounced.
    withdraw(setup, artifact)
    later, _ = start(setup, goal="冷却水路图纸")
    again = search(setup, later, query="冷却水路图纸")
    assert again["items"] == [] and again["returned"] == 0
    assert "冷却水路" not in str(again) and str(earlier) not in str(again)
    assert search(setup, later, query="密封圈供应商对比表")["items"] == []
