"""Actual private conversation turns; synthetic outcomes and no real provider/network calls."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.conversation import memory
from pdos_next.agent_kernel.models import AgentRun, AgentSession
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import Grant
from pdos_next.service import digest
from tests.preproject.test_g0 import post, request


def path(setup, *, personal=False):
    return "/v1/personal/agent-runs" if personal else f"/v1/categories/{setup.category}/agent-runs"


def start(setup, *, personal=False, **body):
    response = setup.client.post(path(setup, personal=personal), headers=setup.headers, json={
        "goal": "先核对汽车充气泵，保留压力单位未知，不建立虚拟项目。",
        "idempotency_key": str(uuid4()), **body,
    })
    assert response.status_code == 202, response.text
    return UUID(response.json()["run_id"]), response.json()


def finish(
    setup, identity, *, status="completed", summary="合成结果：已核对第一项，压力工况仍未知。"
):
    with Session(setup.admin) as session, session.begin():
        row = session.get(AgentRun, identity)
        row.state = status
        row.result = {"summary": summary,
                      "unfinished": ["核对适用工况"], "result": {"not_memory": "原始结果不复制"}}


def scope(setup, identity, *, personal=False):
    return KernelStore(setup.engine).scope(tenant_id=setup.tenant, requester_id=setup.human,
        writer_id=setup.agent, category_id=None if personal else setup.category, run_id=identity)


def test_followup_keeps_actual_session_goal_outcome_sources_and_no_old_authority(setup):
    parent, original = start(setup)
    finish(setup, parent)
    child, result = start(setup, goal="继续核对工况，再给下一步安排。",
                          continue_from_run_id=str(parent))
    assert result["session_id"] == original["session_id"]
    assert result["continued_from_id"] == str(parent)
    with Session(setup.admin) as session:
        old, new = session.get(AgentRun, parent), session.get(AgentRun, child)
        assert old.state == "completed" and new.state == "queued"
        assert new.continued_from_id == parent
        assert new.versions == {
            "checkpoint_layout": "session-run-ns/v1",
            "assistant_depth": {"version": 1, "mode": "quick", "parent_run_id": str(parent)},
            "requested_context_selection": None,
            "requested_context_selection_digest": digest(None),
            "context_selection_start_revision": 0,
        }
        assert new.session_id == old.session_id and new.requester_id == old.requester_id
        assert new.held_tokens == new.used_tokens == 0
    host = Bootstrap(setup.engine)
    context = host.project_context(scope(setup, child), "继续核对工况，再给下一步安排。")
    prior = context["conversation"]["turns"][0]
    assert "保留压力单位未知" in context["conversation"]["root_goal"]
    assert prior["historical_outcome"]["unfinished"] == ["核对适用工况"]
    assert "not_memory" not in str(context)
    host.check_conversation(scope(setup, child))
    history = host.conversation_history(scope(setup, child), {"page_size": 1})
    assert history["turns"][0]["run_id"] == str(parent)
    host.check_conversation(scope(setup, child))
    for identity, expected in [(parent, {"previous_run_id": None, "next_run_id": str(child)}),
                               (child, {"previous_run_id": str(parent), "next_run_id": None})]:
        read = setup.client.get(path(setup) + f"/{identity}", headers=setup.headers)
        assert read.json()["conversation"] == expected


def test_same_original_followup_is_serialized_and_recovers_without_current_binding(setup):
    parent, _ = start(setup)
    finish(setup, parent)
    body = {"goal": "继续核对同一个目标。", "idempotency_key": str(uuid4()),
            "continue_from_run_id": str(parent)}
    def submit(_):
        return setup.client.post(path(setup), headers=setup.headers, json=body)
    with ThreadPoolExecutor(2) as pool:
        replies = list(pool.map(submit, range(2)))
    assert [r.status_code for r in replies] == [202, 202]
    assert replies[0].json()["run_id"] == replies[1].json()["run_id"]
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(select(Grant).where(Grant.category_id == setup.category,
                                                  Grant.principal_id == setup.human))
        grant.can_write = False
        assert session.scalar(select(func.count()).select_from(AgentRun).where(
            AgentRun.continued_from_id == parent)) == 1
    assert submit(0).json()["run_id"] == replies[0].json()["run_id"]
    conflict = setup.client.post(path(setup), headers=setup.headers,
                                json={**body, "goal": "不同目标不覆盖"})
    assert conflict.status_code == 409
    new = setup.client.post(path(setup), headers=setup.headers,
                           json={**body, "idempotency_key": str(uuid4())})
    assert new.status_code == 409
    found = setup.client.get(path(setup) + f"/{parent}/continuation", headers=setup.headers)
    assert found.json()["existing"]["idempotency_key"] == body["idempotency_key"]
    assert found.json()["can_continue"] is False


def test_followup_refuses_scope_changes_peer_and_unfinished_parent(setup):
    parent, _ = start(setup)
    body = {"goal": "继续当前工作。", "idempotency_key": str(uuid4()),
            "continue_from_run_id": str(parent)}
    assert setup.client.post(path(setup), headers=setup.headers, json=body).status_code == 409
    finish(setup, parent)
    for extra in [{"product_id": str(setup.product)}, {"proposal_id": str(uuid4())},
                  {"session_id": str(uuid4())}]:
        assert setup.client.post(path(setup), headers=setup.headers,
                                 json={**body, **extra}).status_code == 422
    headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    assert setup.client.post(path(setup), headers=headers, json=body).status_code == 403
    assert setup.client.post(path(setup, personal=True), headers=setup.headers,
                             json=body).status_code == 403


def synthetic_artifact(setup, title):
    response = post(setup, request(setup, "evidence.artifact.register", {
        "title": title, "source_label": "续接合成来源",
        "content": "续聊需要保留的真实固定原文", "visibility": "private",
    }))
    assert response.status_code == 200, response.text
    return response.json()["subject_id"]


def test_followup_appends_current_sources_without_replacing_original_versions(setup):
    original = synthetic_artifact(setup, "原固定来源")
    additional = synthetic_artifact(setup, "续聊新增来源")
    parent, _ = start(setup, sources=[{"artifact_id": original, "expected_revision": 1}])
    finish(setup, parent)
    child, _ = start(setup, continue_from_run_id=str(parent),
                     sources=[{"artifact_id": additional, "expected_revision": 1}])
    with Session(setup.admin) as session:
        row = session.get(AgentRun, child)
        assert row.proposal_id is None
        assert {ref["artifact_id"] for ref in row.read_sources} == {original, additional}
        assert all(ref["expected_revision"] == 1 for ref in row.read_sources)
    other_parent, _ = start(setup, sources=[{"artifact_id": original, "expected_revision": 1}])
    finish(setup, other_parent)
    conflict = setup.client.post(path(setup), headers=setup.headers, json={
        "goal": "试图替换原固定版本", "idempotency_key": str(uuid4()),
        "continue_from_run_id": str(other_parent),
        "sources": [{"artifact_id": original, "expected_revision": 2}],
    })
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "VERSION_CONFLICT"


def test_private_personal_continuation_is_same_session_without_category_authority(setup):
    parent, original = start(setup, personal=True)
    finish(setup, parent, status="cancelled")
    child, result = start(setup, personal=True, continue_from_run_id=str(parent))
    assert original["session_id"] == result["session_id"]
    with Session(setup.admin) as session:
        row = session.get(AgentRun, child)
        assert row.category_id is row.product_id is row.proposal_id is None
    assert Bootstrap(setup.engine).project_context(scope(setup, child, personal=True), "继续")[
        "conversation"]["turns"][0]["status"] == "cancelled"


def test_full_memory_pagination_retains_root_constraints_and_is_not_recent_raw_chat(setup):
    root, _ = start(setup)
    previous = root
    for index in range(4):
        finish(setup, previous)
        previous, _ = start(setup, goal=f"合成后续约束 {index}，不补造未知数值。",
                            continue_from_run_id=str(previous))
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        requester_id=setup.human, category_id=setup.category) as session:
        current = session.get(AgentRun, previous)
        first = memory(session, current, readers={}, page_size=2)
        second = memory(session, current, readers={}, page_size=2,
                        before=UUID(first["next_before"]))
        assert len(first["turns"]) == len(second["turns"]) == 2
        assert second["next_before"] is None
        assert first["root_run_id"] == second["root_run_id"] == str(root)
        assert "保留压力单位未知" in second["root_goal"]
        assert len({t["run_id"] for t in first["turns"] + second["turns"]}) == 4
        with pytest.raises(DomainError):
            memory(session, current, readers={}, before=uuid4())


def test_append_failure_rolls_back_new_turn_and_keeps_original_result(setup):
    parent, _ = start(setup)
    finish(setup, parent)
    def fail(mapper, connection, target):
        if target.continued_from_id == parent:
            raise RuntimeError("Synthetic continuation insert failure")
    event.listen(AgentRun, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="Synthetic continuation"):
            start(setup, continue_from_run_id=str(parent))
    finally:
        event.remove(AgentRun, "before_insert", fail)
    with Session(setup.admin) as session:
        assert session.scalar(select(func.count()).select_from(AgentRun).where(
            AgentRun.continued_from_id == parent)) == 0
        assert session.get(AgentRun, parent).state == "completed"
        assert session.scalar(select(func.count()).select_from(AgentSession).where(
            AgentSession.owner_id == setup.human)) == 1
    start(setup, continue_from_run_id=str(parent))


def test_sql_continuation_cannot_rebind_existing_turn(setup):
    parent, _ = start(setup)
    finish(setup, parent)
    child, _ = start(setup, continue_from_run_id=str(parent))
    with pytest.raises(DBAPIError):
        with Session(setup.admin) as session, session.begin():
            session.execute(text("UPDATE agent_runs SET continued_from_id=NULL WHERE id=:id"),
                            {"id": child})


def test_revoking_parent_scope_hides_memory_before_model_egress(setup):
    parent, _ = start(setup)
    finish(setup, parent)
    child, _ = start(setup, continue_from_run_id=str(parent))
    bound = scope(setup, child)
    host = Bootstrap(setup.engine)
    host.project_context(bound, "继续")
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(select(Grant).where(Grant.category_id == setup.category,
                                                  Grant.principal_id == setup.human))
        session.delete(grant)
    with pytest.raises(DomainError) as failure:
        host.check_conversation(bound)
    assert failure.value.reason == "CONVERSATION_HISTORY_REVOKED"


def test_registered_graph_receives_persisted_task_memory_and_replay_does_not_call_model(setup):
    import json
    from dataclasses import replace

    from langgraph.checkpoint.memory import MemorySaver

    from pdos_next.agent_kernel.graph import AgentKernel
    from pdos_next.agent_kernel.host import BoundHost
    from pdos_next.agent_kernel.types import ModelTurn
    from pdos_next.providers.types import ProviderUsage
    from tests.agent_kernel.test_api import client
    from tests.agent_kernel.test_gateway import Client, configured_route

    api, _ = client(setup, binding_state={"token_limit": 2_000_000})
    first = api.post(path(setup), json={"goal": "原目标：单位未知必须保留。",
                                      "idempotency_key": str(uuid4())}).json()
    finish(setup, UUID(first["run_id"]))
    second = api.post(path(setup), json={"goal": "继续核对工况。", "idempotency_key": str(uuid4()),
        "continue_from_run_id": first["run_id"]}).json()
    bound = scope(setup, UUID(second["run_id"]))
    def reply(request):
        context = json.loads(request["messages"][0]["content"])["context"]["conversation"]
        assert context["root_goal"] == "原目标：单位未知必须保留。"
        assert context["turns"][0]["historical_outcome"]["unfinished"] == ["核对适用工况"]
        return ModelTurn(usage=ProviderUsage(20, 10), structured={
            "status": "completed", "summary": "合成续接成功，未知仍然保留。",
            "result": {}, "questions": [], "unfinished": [],
        })
    provider = Client(reply)
    host = Bootstrap(setup.engine)
    adapters = replace(host.adapters(), route_for=lambda *_: configured_route(),
                       provider_for=lambda *_: "synthetic", provider_client=provider,
                       cost_required=False)
    kernel = AgentKernel(BoundHost(KernelStore(setup.engine), adapters), host.registry)
    saver = MemorySaver()
    result = kernel.execute(bound, goal="继续核对工况。", checkpointer=saver)
    assert result["output"]["summary"] == "合成续接成功，未知仍然保留。"
    replay = kernel.execute(bound, goal="继续核对工况。", checkpointer=saver)
    assert replay["output"] == result["output"]
    assert provider.calls == 1
    with Session(setup.admin) as session:
        assert session.get(AgentRun, bound.run_id).state == "completed"
        assert session.get(AgentRun, UUID(first["run_id"])).state == "completed"
    api.close()


def test_cached_read_summary_keeps_frozen_view_and_next_history_observes_metadata_update(setup):
    from pdos_next.models import Artifact

    identity = synthetic_artifact(setup, "历史metadata更新，不重放读工具")
    parent, _ = start(setup, sources=[{"artifact_id": identity, "expected_revision": 1}])
    finish(setup, parent)
    child, _ = start(setup, continue_from_run_id=str(parent))
    host, bound = Bootstrap(setup.engine), scope(setup, child)
    host.adapters()
    context = host.project_context(bound, "继续")
    assert context["conversation"]["turns"][0]["outcome_state"] == "current"
    with Session(setup.admin) as session, session.begin():
        source = session.get(Artifact, UUID(identity))
        source.revision += 1  # Existing supported synthetic version drift; body/hash unchanged.
    host._history_readers["calc.cost_subtotal"] = lambda *_: pytest.fail("old reader replayed")
    host.check_conversation(bound)
    assert host.project_context(bound, "继续")["conversation"] == context["conversation"]
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        requester_id=setup.human, category_id=setup.category) as session:
        changed = memory(session, session.get(AgentRun, child), readers={})
        assert changed["turns"][0]["outcome_state"] == "updated"
        assert "资料已更新" in str(changed["turns"][0]["historical_outcome"]["notes"])
        assert changed["turns"][0]["historical_outcome"]["summary"] == context[
            "conversation"]["turns"][0]["historical_outcome"]["summary"]


def test_newly_revoked_actual_private_source_hides_answer_and_stops_frozen_history(setup):
    from pdos_next.models import ObjectAudience

    registered = post(setup, request(setup, "evidence.artifact.register", {
        "title": "别人按受众共享的历史资料", "content": "只用于授权撤回验证。",
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
    parent, _ = start(setup, sources=[{"artifact_id": str(identity), "expected_revision": 1}])
    # Production completion persists the source-independent user goal in the
    # append-only work state; bypassing it with the old admin finish helper
    # cannot exercise the owner's post-revocation history projection.
    Bootstrap(setup.engine).store.finish(scope(setup, parent), {
        "status": "completed", "summary": "合成结果：已核对第一项，压力工况仍未知。",
        "result": {}, "questions": [], "unfinished": ["核对适用工况"],
    })
    child, _ = start(setup, continue_from_run_id=str(parent))
    host, bound = Bootstrap(setup.engine), scope(setup, child)
    host.adapters()
    frozen = host.project_context(bound, "继续")
    assert frozen["conversation"]["turns"][0]["historical_outcome"] is not None
    with Session(setup.admin) as session, session.begin():
        session.delete(session.get(ObjectAudience, audience_id))
    with pytest.raises(DomainError) as failure:
        host.check_conversation(bound)
    assert failure.value.reason == "CONVERSATION_HISTORY_REVOKED"
    # The explicit-source audience hides the whole Run from normal RLS. Only
    # the authenticated owner's source-independent goal projection is readable;
    # it must not recover the old result, events, or a usable execution scope.
    response = setup.client.get(path(setup) + f"/{parent}", headers=setup.headers)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["history_hidden"] and value["status"] == "hidden"
    assert value["result"] is None and value["versions"] == {}
    assert value["goal"] == frozen["conversation"]["turns"][0]["goal"]
    assert "合成结果：" not in response.text


def test_prepared_candidate_turn_keeps_answer(setup):
    from pdos_next.agent_kernel.models import AgentToolCall
    from pdos_next.service import digest

    parent, _ = start(setup)
    with Session(setup.admin) as session, session.begin():
        session.add(AgentToolCall(
            tenant_id=setup.tenant, run_id=parent,
            call_key="synthetic-prepared-candidate", tool="work.task.assign",
            input_digest=digest({}), execution_binding={"kind": "unbound"},
            state="completed", result={"candidate": True},
        ))
    finish(setup, parent)
    child, _ = start(setup, continue_from_run_id=str(parent))
    value = Bootstrap(setup.engine).project_context(scope(setup, child), "继续")
    outcome = value["conversation"]["turns"][0]["historical_outcome"]
    assert "合成结果" in outcome["summary"]
    assert "准备过候选" in str(outcome["notes"])


def test_thirty_turn_history_stays_bounded_and_full_history_is_available(setup):
    import json

    from pdos_next.agent_kernel.context_budget import estimate_tokens

    previous, _ = start(setup)
    for _ in range(30):
        finish(setup, previous, summary="长" * 1000)
        previous, _ = start(setup, continue_from_run_id=str(previous))
    host = Bootstrap(setup.engine)
    bound = scope(setup, previous)
    history = host.project_context(bound, "继续")["conversation"]
    assert estimate_tokens(json.dumps(history, ensure_ascii=False)) <= 4000
    assert all(t["historical_outcome"]["truncated"] for t in history["turns"])
    assert all(len(t["historical_outcome"]["summary"]) <= 60 for t in history["turns"][3:])
    full = host.conversation_history(bound, {"page_size": 10})
    assert all(t["historical_outcome"]["summary"] == "长" * 1000 for t in full["turns"])
