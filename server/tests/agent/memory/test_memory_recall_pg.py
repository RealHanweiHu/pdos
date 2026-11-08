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
    other, _ = start(setup, goal="整理样件编号规则")
    finish(setup, other)
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
