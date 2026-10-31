"""Actual HTTP/CAS/RLS/SQL drafts. Root runs only on its verified isolated pdos_test.

No real model/embedding call is required. API patch and preceding stages must be
applied before these tests; no provider inference is started by this file.
"""

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.agent_kernel.work_state_models import AgentWorkState
from pdos_next.database import tenant_session
from pdos_next.enterprise_search.assistant_schemas import AssistantSearchInput
from pdos_next.enterprise_search.assistant_scope import retrieve
from tests.agent_kernel.test_run_continuation import path, scope, start
from tests.enterprise_search.test_retrieval_pg import index, register


def finish(setup, identity, *, proposed_run=None, personal=False):
    KernelStore(setup.engine).finish(
        scope(setup, identity, personal=personal),
        {
            "status": "completed",
            "summary": "合成案例核对结果，压力单位未知。",
            "unfinished": [],
            "questions": [],
            "result": {
                "context_proposals": {
                    "constraints": [
                        {"run_id": str(proposed_run or identity), "text": "压力单位未知"},
                    ]
                }
            },
        },
    )


def work_path(setup, session_id):
    return f"/v1/categories/{setup.category}/agent-sessions/{session_id}/work-state"


def read_state(setup, session_id):
    response = setup.client.get(work_path(setup, session_id), headers=setup.headers)
    assert response.status_code == 200, response.text
    return response.json()


def edit(setup, session_id, state, kind, refs=(), *, key=None):
    body = {
        "expected_revision": state["revision"],
        "request_key": str(key or uuid4()),
        "action": "correct_context",
        "context_change": {"kind": kind, "sources": list(refs)},
    }
    response = setup.client.post(work_path(setup, session_id), headers=setup.headers, json=body)
    return response, body


def search_run(setup, identity):
    host = Bootstrap(setup.engine)
    actual_scope = scope(setup, identity)
    host.project_context(actual_scope, "按选定资料核对漏气，压力单位未知。")
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
        read_snapshot=True,
    ) as session:
        return retrieve(
            session,
            setup.ctx,
            actual_scope,
            AssistantSearchInput(query="漏气", source_types=["artifact"], limit=1),
        )


def test_private_source_selection_replay_sql_limit_clear_and_deleted_constraint(setup):
    first = register(setup, "原漏气资料", "漏气处理参考。", visibility="private")
    second = register(setup, "正确漏气资料", "漏气处理参考。", visibility="private")
    for identity in (first, second):
        index(setup, identity)
    parent, accepted = start(
        setup,
        goal="核对漏气，压力单位未知。",
        sources=[
            {
                "artifact_id": str(first),
                "expected_revision": 1,
            }
        ],
    )
    finish(setup, parent)
    session_id = accepted["session_id"]
    state = read_state(setup, session_id)
    assert state["context_selection"]["sources"][0]["source_id"] == str(first)
    constraint = state["constraints"][0]["id"]
    removed = setup.client.post(
        work_path(setup, session_id),
        headers=setup.headers,
        json={
            "expected_revision": state["revision"],
            "request_key": str(uuid4()),
            "action": "remove_constraint",
            "item_id": constraint,
        },
    )
    assert removed.status_code == 200, removed.text
    state = removed.json()
    response, original = edit(
        setup,
        session_id,
        state,
        "limit_sources",
        [
            {
                "source_type": "artifact",
                "source_id": str(second),
                "expected_revision": 1,
            }
        ],
    )
    assert response.status_code == 200, response.text
    assert (
        setup.client.post(work_path(setup, session_id), headers=setup.headers, json=original).json()
        == response.json()
    )
    saved_revision = response.json()["revision"]
    changed = setup.client.post(
        work_path(setup, session_id),
        headers=setup.headers,
        json={
            "expected_revision": saved_revision,
            "request_key": str(uuid4()),
            "action": "set_search_scope",
            "search_preferences": {
                "scope": "current",
                "include_customer_private": False,
            },
        },
    )
    assert changed.status_code == 200, changed.text
    stale = setup.client.post(
        path(setup),
        headers=setup.headers,
        json={
            "continue_from_run_id": str(parent),
            "goal": "继续核对漏气。",
            "idempotency_key": str(uuid4()),
            "context_revision": saved_revision,
        },
    )
    assert stale.status_code == 409
    accepted_revision, child_key = changed.json()["revision"], str(uuid4())
    child, _ = start(
        setup,
        continue_from_run_id=str(parent),
        goal="继续核对漏气。",
        idempotency_key=child_key,
        context_revision=accepted_revision,
    )
    found = search_run(setup, child)
    assert found["returned"] == 1 and not found["truncated"]
    assert {item["source_id"] for item in found["items"]} == {str(second)}
    with Session(setup.admin) as session:
        old, new = session.get(AgentRun, parent), session.get(AgentRun, child)
        assert old.read_sources[0]["artifact_id"] == str(first)
        assert {ref["artifact_id"] for ref in new.read_sources} == {str(second)}
        assert (
            session.scalar(
                select(func.count())
                .select_from(AgentWorkState)
                .where(
                    AgentWorkState.session_id == UUID(session_id),
                    AgentWorkState.request_key == UUID(original["request_key"]),
                )
            )
            == 1
        )
    finish(setup, child, proposed_run=parent)
    state = read_state(setup, session_id)
    assert state["constraints"] == []
    cleared, _ = edit(setup, session_id, state, "clear")
    assert cleared.status_code == 200 and "context_selection" not in cleared.json()
    replay = setup.client.post(
        path(setup),
        headers=setup.headers,
        json={
            "continue_from_run_id": str(parent),
            "goal": "继续核对漏气。",
            "idempotency_key": child_key,
            "context_revision": accepted_revision,
        },
    )
    assert replay.status_code == 202 and replay.json()["run_id"] == str(child)
    next_run, _ = start(setup, continue_from_run_id=str(child), goal="解除限定后继续核对漏气。")
    next_result = search_run(setup, next_run)
    assert next_result["returned"] == 1 and next_result["truncated"]
    assert len(next_result["items"]) == 1  # both sources exist before LIMIT 1, so it truncates


def test_context_options_are_owner_only_and_made_up_artifact_history_is_rejected(setup):
    artifact = register(setup, "本人私有选定资料", "漏气。", visibility="private")
    parent, accepted = start(setup, goal="核对资料，压力单位未知。")
    finish(setup, parent)
    session_id = accepted["session_id"]
    options = work_path(setup, session_id) + "/context-options"
    own = setup.client.get(options, params={"query": "本人私有选定资料"}, headers=setup.headers)
    assert own.status_code == 200 and str(artifact) in own.text
    for actor in (setup.peer, setup.other_human):
        denied = setup.client.get(
            options,
            params={"query": "本人私有选定资料"},
            headers={"Authorization": f"Bearer {setup.tokens[actor]}"},
        )
        assert denied.status_code in {403, 404}
        assert str(artifact) not in denied.text and "本人私有选定资料" not in denied.text
    state = read_state(setup, session_id)
    response, _ = edit(
        setup,
        session_id,
        state,
        "fixed_versions",
        [
            {
                "source_type": "artifact",
                "source_id": str(artifact),
                "expected_revision": 99,
            }
        ],
    )
    assert response.status_code == 403
    assert read_state(setup, session_id)["revision"] == state["revision"]
    original = setup.client.get(path(setup) + f"/{parent}", headers=setup.headers)
    assert original.status_code == 200 and original.json()["status"] == "completed"
