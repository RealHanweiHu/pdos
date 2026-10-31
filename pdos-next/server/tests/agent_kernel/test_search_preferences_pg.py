"""Human choices are versioned, immutable per Run, idempotent, and not model proposals."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID, uuid4

from pdos_next.agent_kernel.bootstrap import Bootstrap
from tests.agent_kernel.test_run_continuation import path as run_path
from tests.agent_kernel.test_run_continuation import scope, start
from tests.agent_kernel.test_work_state_pg import complete, path, read


def test_scope_choice_freezes_and_human_edits_win_over_finish_and_model_proposals(setup):
    preference = {"scope": "same_category", "include_customer_private": True}
    key = str(uuid4())
    first, accepted = start(setup, goal="核对本人查找范围", idempotency_key=key,
                            search_preferences=preference)
    replay_id, _ = start(setup, goal="核对本人查找范围", idempotency_key=key,
                         search_preferences=preference)
    assert replay_id == first
    conflict = setup.client.post(run_path(setup), headers=setup.headers, json={
        "goal": "核对本人查找范围", "idempotency_key": key,
        "search_preferences": {"scope": "current", "include_customer_private": False},
    })
    assert conflict.status_code == 409
    session_id = accepted["session_id"]
    before = read(setup, session_id)
    assert before["revision"] == 1 and before["search_preferences"] == preference
    frozen = Bootstrap(setup.engine).project_context(scope(setup, first), "继续核对")["work_state"]
    body = {"expected_revision": 1, "request_key": str(uuid4()), "action": "set_search_scope",
            "search_preferences": {"scope": "current", "include_customer_private": False}}
    edited = setup.client.post(path(setup, session_id), headers=setup.headers, json=body)
    assert edited.status_code == 200, edited.text
    replay = setup.client.post(path(setup, session_id), headers=setup.headers, json=body)
    assert replay.json() == edited.json() and edited.json()["revision"] == 2
    assert frozen["search_preferences"] == preference
    again = Bootstrap(setup.engine).project_context(scope(setup, first), "继续核对")["work_state"]
    assert again == frozen
    complete(setup, first)
    assert read(setup, session_id)["search_preferences"] == body["search_preferences"]
    child, _ = start(setup, continue_from_run_id=str(first), goal="沿用本人查找范围。")
    actual = Bootstrap(setup.engine).project_context(scope(setup, child), "继续核对")["work_state"]
    assert actual["search_preferences"] == body["search_preferences"]
    denied = setup.client.post(path(setup, session_id), json={**body, "request_key": str(uuid4())},
                              headers={"Authorization": f"Bearer {setup.tokens[setup.peer]}"})
    assert denied.status_code in {403, 404}
    from pdos_next.agent_kernel.persistence import KernelStore

    KernelStore(setup.engine).finish(scope(setup, child), {
        "status": "completed", "summary": "合成完成", "questions": [], "unfinished": [],
        "result": {"context_proposals": {"search_preferences": preference}},
    })
    assert read(setup, session_id)["search_preferences"] == body["search_preferences"]
    assert UUID(session_id)


def test_scope_edit_and_continuation_do_not_deadlock_on_the_session_foreign_key(setup, monkeypatch):
    from pdos_next.agent_kernel import work_state

    parent, accepted = start(setup)
    complete(setup, parent)
    session_id = accepted["session_id"]
    held, entered = Event(), Event()
    original = work_state._lock
    calls = []

    def staged_lock(session, tenant_id, identity):
        calls.append(True)
        if len(calls) == 1:
            original(session, tenant_id, identity)
            held.set()
            assert entered.wait(8)
        else:
            entered.set()
            original(session, tenant_id, identity)

    monkeypatch.setattr(work_state, "_lock", staged_lock)
    request = {"expected_revision": 1, "request_key": str(uuid4()),
               "action": "set_search_scope", "search_preferences": {
                   "scope": "current", "include_customer_private": False}}
    with ThreadPoolExecutor(max_workers=2) as pool:
        changing = pool.submit(setup.client.post, path(setup, session_id),
                               headers=setup.headers, json=request)
        assert held.wait(8)
        following = pool.submit(start, setup, continue_from_run_id=str(parent),
                                search_preferences={"scope": "same_category",
                                                    "include_customer_private": False})
        response = changing.result(timeout=20)
        child, _accepted = following.result(timeout=20)
    assert response.status_code == 200, response.text
    assert child != parent and read(setup, session_id)["revision"] == 3
