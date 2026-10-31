"""Native HTTP/state recovery; admission event is an explicit local host fixture.

No provider is dispatched. These checks exercise control/provenance and do not
claim that a language model completed a long conversation correctly.
"""

import json
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import execution_key
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.models import AgentRun, AgentSession
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.agent_kernel.work_state_models import AgentWorkState
from pdos_next.errors import DomainError
from pdos_next.models import Artifact
from tests.agent_kernel.test_run_continuation import path, scope, start


def stopped(setup):
    parent, original = start(setup)
    store = KernelStore(setup.engine)
    actual_scope = scope(setup, parent)
    # This is the same append-only technical event consumed by eligibility,
    # deliberately authored as a synthetic host fixture, never model JSON.
    store.emit(actual_scope, {"type": "context_incomplete", "missing": ["history"]})
    store.finish(actual_scope, {"status": "partial", "summary": "上下文预算停止。",
        "unfinished": ["继续核对"], "questions": [], "result": {
            "context_incomplete": True,
            "context_proposals": {"constraints": [
                {"run_id": str(parent), "text": "保留压力单位未知"},
                {"run_id": str(parent), "text": "不建立虚拟项目"},
            ]},
        }})
    return parent, original


def work_path(setup, sid):
    return f"/v1/categories/{setup.category}/agent-sessions/{sid}/work-state"


def test_budget_recovery_creates_fresh_session_preserves_proof_and_latest_human_deletion(setup):
    parent, original = stopped(setup)
    before = setup.client.get(work_path(setup, original["session_id"]),
                              headers=setup.headers).json()
    removed = before["constraints"][0]
    change = setup.client.post(work_path(setup, original["session_id"]), headers=setup.headers,
                              json={"expected_revision": before["revision"],
                                    "request_key": str(uuid4()), "action": "remove_constraint",
                                    "item_id": removed["id"]})
    assert change.status_code == 200, change.text
    revision = change.json()["revision"]
    stale = setup.client.post(path(setup), headers=setup.headers, json={
        "goal": "保留工作状态，继续核对。", "idempotency_key": str(uuid4()),
        "restart_from_run_id": str(parent), "context_revision": before["revision"],
    })
    assert stale.status_code == 409, stale.text
    request = {"goal": "保留工作状态，继续核对。", "idempotency_key": str(uuid4()),
               "restart_from_run_id": str(parent), "context_revision": revision}
    response = setup.client.post(path(setup), headers=setup.headers, json=request)
    assert response.status_code == 202, response.text
    value = response.json()
    assert value["session_id"] != original["session_id"]
    assert value["continued_from_id"] is None and value["restarted_from_id"] == str(parent)
    replay = setup.client.post(path(setup), headers=setup.headers, json=request)
    assert replay.status_code == 202 and replay.json()["run_id"] == value["run_id"]
    identity = UUID(value["run_id"])
    host = Bootstrap(setup.engine)
    actual = host.project_context(scope(setup, identity), request["goal"])
    assert not actual.get("conversation", {}).get("turns")
    carry = actual["work_state"]
    assert carry["root_goal"]["run_id"] == str(parent)
    assert carry["constraints"] == [before["constraints"][1]]
    assert carry["current_goal"] == {"run_id": str(identity), "text": request["goal"]}
    host.check_conversation(scope(setup, identity))
    KernelStore(setup.engine).finish(scope(setup, identity), {
        "status": "completed", "summary": "机械恢复检查。", "unfinished": [], "questions": [],
        "result": {"context_proposals": {"constraints": [
            {"run_id": str(parent), "text": removed["text"]},
        ]}},
    })
    after = setup.client.get(work_path(setup, value["session_id"]), headers=setup.headers).json()
    assert after["constraints"] == [before["constraints"][1]]
    with Session(setup.admin) as session:
        stored = session.scalar(select(AgentWorkState).where(
            AgentWorkState.session_id == UUID(value["session_id"]),
        ).order_by(AgentWorkState.revision.desc()))
        assert removed["id"] in stored.body["removed_constraints"]
        assert session.get(AgentRun, identity).continued_from_id is None
        assert session.get(AgentSession, UUID(original["session_id"])) is not None


def test_recovery_is_explicit_owner_only_and_rejects_client_state_or_scope(setup):
    parent, original = stopped(setup)
    request = {"goal": "继续核对。", "idempotency_key": str(uuid4()),
               "restart_from_run_id": str(parent), "context_revision": 1}
    peer = setup.client.post(path(setup), json=request,
                            headers={"Authorization": f"Bearer {setup.tokens[setup.peer]}"})
    assert peer.status_code in {403, 404}, peer.text
    for extra in ({"work_state": {}}, {"session_id": original["session_id"]},
                  {"continue_from_run_id": str(parent)}, {"context_revision": None}):
        refused = setup.client.post(path(setup), headers=setup.headers,
                                    json={**request, **extra, "idempotency_key": str(uuid4())})
        assert refused.status_code == 422, refused.text
    ordinary, fresh = start(setup, goal="普通新建仍为空。")
    assert fresh["session_id"] != original["session_id"]
    context = Bootstrap(setup.engine).project_context(scope(setup, ordinary), "普通新建仍为空。")
    assert context["work_state"]["constraints"] == []
    assert context["work_state"]["root_goal"]["run_id"] == str(ordinary)


def recover(setup, identity, *, personal=False):
    root = "/v1/personal" if personal else f"/v1/categories/{setup.category}"
    reading = setup.client.get(f"{root}/agent-runs/{identity}/continuation",
                               headers=setup.headers)
    assert reading.status_code == 200, reading.text
    recovery = reading.json()["context_restart"]
    response = setup.client.post(f"{root}/agent-runs", headers=setup.headers, json={
        "goal": "保留已核对状态，继续处理。", "idempotency_key": str(uuid4()),
        "restart_from_run_id": str(identity), "context_revision": recovery["expected_revision"],
    })
    assert response.status_code == 202, response.text
    return UUID(response.json()["run_id"]), response.json()


def stop_again(store, actual_scope):
    store.emit(actual_scope, {"type": "context_incomplete", "missing": ["synthetic_history"]})
    store.finish(actual_scope, {"status": "partial", "summary": "合成预算停止。",
                               "questions": [], "unfinished": ["继续核对"], "result": {}})


def test_two_restarts_reauthorize_original_candidate_metadata_and_actual_receipt(setup):
    from tests.agent_kernel.test_read_proof_transactions import read_fixture
    from tests.agent_kernel.test_snapshot_proof_transactions import model_for
    from tests.products.test_definition_item_commands_pg import confirmed
    from tests.products.test_platform_links_pg import payload

    f = read_fixture(setup, skill_key="derivative_diff")
    owner = Bootstrap(setup.engine)
    owner.route = lambda *_: f.route
    arguments = payload(setup)
    source = model_for(f, "platform.link.create", arguments)
    prepared = owner.prepare_candidate(
        f.scope, f.registry.get("platform.link.create"), arguments,
        execution_key(f.scope.run_id, source.model_call_id, 0),
    )
    stop_again(f.store, f.scope)
    first, _ = recover(setup, f.scope.run_id)
    first_scope = scope(setup, first)
    frozen = owner.project_context(first_scope, "继续")["work_state"]
    pending = next(item for item in frozen["candidates"]
                   if item["event_id"] == prepared["event_id"])
    assert pending["run_id"] == str(f.scope.run_id) and pending["state"] == "pending"
    receipt, _command = confirmed(setup, prepared["command"])
    assert owner.project_context(first_scope, "继续")["work_state"] == frozen
    owner.check_conversation(first_scope)
    stop_again(f.store, first_scope)
    second, _ = recover(setup, first)
    second_scope = scope(setup, second)
    context = owner.project_context(second_scope, "继续")
    actual = next(item for item in context["work_state"]["candidates"]
                  if item["event_id"] == prepared["event_id"])
    assert actual == {**pending, "state": "adopted", "receipt_id": receipt["id"]}
    assert not context.get("conversation", {}).get("turns")
    owner.check_conversation(second_scope)


def test_two_restarts_keep_exact_citation_roots_and_current_withdrawal_stops_disclosure(setup):
    from pdos_next.enterprise_search.assistant_inheritance import page
    from pdos_next.enterprise_search.assistant_schemas import CitationsInput
    from tests.enterprise_search.test_assistant_pg import SyntheticClient, execute, fixture
    from tests.enterprise_search.test_retrieval_pg import index, register

    class BudgetClient(SyntheticClient):
        def turn(self, route, **kwargs):
            response = super().turn(route, **kwargs)
            if response.structured and "status" in response.structured:
                response = replace(
                    response, structured={**response.structured, "status": "partial"},
                )
            return response

    artifact = register(setup, "漏气恢复记录", "措施：更换密封圈。RAW_ONLY_CHILD_MARKER")
    index(setup, artifact)
    scripted = BudgetClient()
    owner, original, host, _adapter = fixture(setup, scripted)
    scripted.after_extract = lambda: host.emit(original, {
        "type": "context_incomplete", "missing": ["synthetic_history"],
    })
    output = execute(owner, original, host)
    assert output["status"] == "partial", output
    cid = output["result"]["assistant"]["sources"][0]["citation_id"]
    first, _ = recover(setup, original.run_id, personal=True)
    first_scope = scope(setup, first, personal=True)
    carried = owner.project_context(first_scope, "继续")["work_state"]["citations"]
    assert carried[0]["origin_run_id"] == str(original.run_id)
    assert carried[0]["origin_citation_id"] == cid
    with owner.store.transaction(first_scope) as (session, run):
        assert page(session, run, CitationsInput(reference_id=UUID(cid)))["items"] == carried
    owner.check_conversation(first_scope)
    stop_again(owner.store, first_scope)
    followup, _ = start(setup, personal=True, continue_from_run_id=str(first),
                        goal="在恢复会话中继续核对旧引用。")
    followup_scope = scope(setup, followup, personal=True)
    owner.project_context(followup_scope, "继续")
    with owner.store.transaction(followup_scope) as (session, run):
        aliased = page(session, run, CitationsInput(reference_id=UUID(carried[0]["citation_id"])))
        assert aliased["items"][0]["origin_citation_id"] == cid
    stop_again(owner.store, followup_scope)
    second, _ = recover(setup, followup, personal=True)
    second_scope = scope(setup, second, personal=True)
    context = owner.project_context(second_scope, "继续")
    assert not context.get("conversation", {}).get("turns")
    again = context["work_state"]["citations"]
    assert again[0]["origin_run_id"] == str(original.run_id)
    assert again[0]["origin_citation_id"] == cid
    with Session(setup.admin) as session, session.begin():
        session.get(Artifact, artifact).status = "withdrawn"
    with pytest.raises(DomainError):
        owner.check_conversation(second_scope)
    view = setup.client.get(f"/v1/personal/agent-sessions/{second_scope.session_id}/work-state",
                            headers=setup.headers)
    assert view.status_code == 200, view.text
    assert view.json()["citations"] == [] and "更换密封圈" not in view.text


def unquoted_note_client(marker, note):
    from tests.enterprise_search.test_assistant_pg import SyntheticClient

    class NoteClient(SyntheticClient):
        def __init__(self, marker):
            super().__init__()
            self.marker = marker

        def turn(self, route, **kwargs):
            response = super().turn(route, **kwargs)
            if response.calls:
                response = replace(response, calls=tuple(
                    call.model_copy(update={"arguments": {**call.arguments, "query": self.marker}})
                    if call.name == "assistant.search" else call for call in response.calls
                ))
            if response.structured and "status" in response.structured:
                response = replace(response, structured={
                    **response.structured, "status": "partial", "unfinished": [note],
                })
            return response

    return NoteClient(marker)


def test_unquoted_note_client_search_and_final_output_models_offline(monkeypatch):
    from pdos_agent_runtime import graph

    from pdos_next.agent_kernel.types import ModelTurn, ToolCall

    # Only the graph-context predicate is substituted. Both actual scripted
    # turn methods and the production ModelTurn/ToolCall types execute directly.
    monkeypatch.setattr(graph, "in_registered_agent_graph", lambda: True)
    note, cid = "未引用候选中的合成待办", str(uuid4())
    client = unquoted_note_client("UNQADMIT01", note)
    search = client.turn(None, messages=[{"role": "user", "content": "{}"}],
                         tools=[{"name": "assistant.search"}])
    assert isinstance(search, ModelTurn) and isinstance(search.calls[0], ToolCall)
    assert search.calls[0].name == "assistant.search"
    assert search.calls[0].arguments == {"query": "UNQADMIT01"}
    final = client.turn(None, messages=[{"role": "tool", "content": json.dumps({
        "rows": [{"citation_id": cid}],
    })}], tools=[{"name": "assistant.search"}])
    assert isinstance(final, ModelTurn) and final.structured["status"] == "partial"
    assert final.structured["unfinished"] == [note]
    assert final.structured["result"]["assistant"]["citation_ids"] == [cid]


def test_unquoted_search_candidate_guards_restored_notes_at_admission_and_before_model(setup):
    from pdos_next.agent_kernel.models import AgentToolCall
    from tests.enterprise_search.test_assistant_pg import execute, fixture
    from tests.enterprise_search.test_retrieval_pg import index, register

    note = "未引用候选中的合成待办"

    def unquoted_case(marker):
        sources = {
            register(setup, f"{marker} 漏气恢复候选{ordinal}",
                     "接口漏气。措施：更换密封圈。RAW_ONLY_CHILD_MARKER")
            for ordinal in (1, 2)
        }
        for source in sources:
            index(setup, source)
        client = unquoted_note_client(marker, note)
        owner, original, host, _adapter = fixture(setup, client)
        client.after_extract = lambda: host.emit(original, {
            "type": "context_incomplete", "missing": ["synthetic_history"],
        })
        output = execute(owner, original, host)
        assert output["status"] == "partial" and output["unfinished"] == [note]
        quoted = UUID(output["result"]["assistant"]["sources"][0]["source_id"])
        unquoted = next(source for source in sources if source != quoted)
        with Session(setup.admin) as session:
            search = session.scalar(select(AgentToolCall).where(
                AgentToolCall.run_id == original.run_id, AgentToolCall.tool == "assistant.search",
            ))
            assert {item["source_id"] for item in search.result["items"]} == {
                str(source) for source in sources}
        return owner, original, unquoted

    # Each withdrawal is terminal. Separate native sources/Runs exercise
    # admission and in-flight disclosure without reviving a withdrawn Artifact.
    _admission_owner, admission, admission_source = unquoted_case("UNQADMIT01")
    with Session(setup.admin) as session, session.begin():
        session.get(Artifact, admission_source).status = "withdrawn"
    original_state = setup.client.get(
        f"/v1/personal/agent-sessions/{admission.session_id}/work-state", headers=setup.headers,
    ).json()
    rejected = setup.client.post("/v1/personal/agent-runs", headers=setup.headers, json={
        "goal": "保留状态继续", "idempotency_key": str(uuid4()),
        "restart_from_run_id": str(admission.run_id),
        "context_revision": original_state["revision"],
    })
    assert rejected.status_code >= 400 and rejected.json()["code"] == "SOURCE_UNAVAILABLE"

    owner, original, unquoted = unquoted_case("UNQRUNTIME02")
    with Session(setup.admin) as session:
        assert session.get(Artifact, admission_source).status == "withdrawn"
    identity, _value = recover(setup, original.run_id, personal=True)
    current_scope = scope(setup, identity, personal=True)
    state = owner.project_context(current_scope, "继续")["work_state"]
    assert state["unfinished"] == [note] and "_restart_access" not in state
    with Session(setup.admin) as session, session.begin():
        session.get(Artifact, unquoted).status = "withdrawn"
    with pytest.raises(DomainError) as revoked:
        owner.check_conversation(current_scope)
    assert revoked.value.code == "FORBIDDEN_SCOPE"
    assert revoked.value.reason == "CONVERSATION_HISTORY_REVOKED"
    hidden = setup.client.get(
        f"/v1/personal/agent-sessions/{current_scope.session_id}/work-state", headers=setup.headers,
    )
    assert hidden.status_code == 200 and hidden.json()["unfinished"] == []
    assert note not in hidden.text and "_restart_access" not in hidden.text
