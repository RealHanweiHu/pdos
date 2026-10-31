"""PG verification draft: actual exclusions/ledger, RLS, atomicity and lock ordering.

Not run by the staging author. Use only the root-verified isolated TEST_DATABASE_URL.
Provider/scanner ports in imported samples are synthetic; no real model or egress.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, current_thread
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel import work_state
from pdos_next.agent_kernel.models import AgentEvent, AgentToolCall
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.agent_kernel.retrieval_feedback import KIND
from pdos_next.agent_kernel.work_state_models import AgentWorkState
from pdos_next.database import tenant_session
from pdos_next.models import Receipt
from tests.agent_kernel.test_run_continuation import scope, start, synthetic_artifact
from tests.agent_kernel.test_work_state_pg import complete, path, read
from tests.enterprise_search.test_assistant_pg import SyntheticClient, execute, fixture
from tests.enterprise_search.test_comparison_pg import starting
from tests.enterprise_search.test_retrieval_pg import index, register


def excluded(setup, session_id, state, identity, *, key=None):
    return setup.client.post(
        path(setup, session_id),
        headers=setup.headers,
        json={
            "request_key": str(key or uuid4()),
            "expected_revision": state["revision"],
            "action": "exclude_source",
            "item_id": str(identity),
        },
    )


def feedbacks(setup, run_id):
    with Session(setup.admin) as session:
        return [
            row.body
            for row in session.scalars(
                select(AgentEvent)
                .where(
                    AgentEvent.run_id == run_id,
                    AgentEvent.body["type"].astext == KIND,
                )
                .order_by(AgentEvent.sequence)
            )
        ]


def bound(setup):
    artifact = synthetic_artifact(setup, "合成资料，未检索时不能虚构排名。")
    run_id, response = start(setup, sources=[{"artifact_id": artifact, "expected_revision": 1}])
    result = complete(setup, run_id)
    return artifact, run_id, response["session_id"], result


def test_bound_exclusion_replays_one_private_event_and_one_memory_version(setup):
    artifact, run_id, session_id, _result = bound(setup)
    before = read(setup, session_id)
    key = uuid4()
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(
            pool.map(
                lambda _: excluded(setup, session_id, before, artifact, key=key),
                range(2),
            )
        )
    assert [response.status_code for response in replies] == [200, 200]
    assert replies[0].json() == replies[1].json()
    values = feedbacks(setup, run_id)
    assert len(values) == 1
    saved = values[0]
    assert saved["origin"] == "bound_source" and saved["origin_call_id"] is None
    assert saved["candidate"] == {
        "chunk_id": None,
        "rank": None,
        "ranking_version": None,
    }
    assert saved["source"]["source_id"] == artifact
    assert saved["recorded_by"] == str(setup.human) and saved["request_key"] == str(key)
    with Session(setup.admin) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AgentWorkState)
                .where(AgentWorkState.session_id == UUID(session_id))
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AgentToolCall)
                .where(AgentToolCall.run_id == run_id)
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count()).select_from(Receipt).where(Receipt.agent_run_id == run_id)
            )
            == 0
        )
    # Event reads use existing owner-only Run API/RLS; same category alone is insufficient.
    url = f"/v1/categories/{setup.category}/agent-runs/{run_id}/events"
    for principal in (setup.peer, setup.other_human):
        response = setup.client.get(
            url, headers={"Authorization": "Bearer " + setup.tokens[principal]}
        )
        assert response.status_code in {403, 404}
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.peer,
        requester_id=setup.peer,
        category_id=setup.category,
    ) as session:
        assert (
            session.scalar(
                select(AgentEvent.id).where(
                    AgentEvent.run_id == run_id, AgentEvent.body["type"].astext == KIND
                )
            )
            is None
        )


@pytest.mark.parametrize("kind", ["search", "materials"])
def test_actual_search_or_material_citation_preserves_real_origin_and_ranking(setup, kind):
    if kind == "search":
        artifact = register(setup, "D16 漏气处理", "漏气措施：更换密封圈。RAW_ONLY_CHILD_MARKER")
        index(setup, artifact)
        owner, run_scope, host, _adapter = fixture(setup, SyntheticClient())
    else:
        _ids, _client, (owner, run_scope, host, _adapter) = starting(
            setup,
            "压力 10 kPa。\n\nUNCHANGED_RAW_ONLY",
            "压力 12 kPa。\n\nUNCHANGED_RAW_ONLY",
        )
    execute(owner, run_scope, host)
    with owner.store.transaction(run_scope) as (session, run):
        session_id = str(run.session_id)
        call = session.scalar(
            select(AgentToolCall).where(
                AgentToolCall.run_id == run.id,
                AgentToolCall.tool
                == ("assistant.search" if kind == "search" else "assistant.materials.read"),
                AgentToolCall.state == "completed",
            )
        )
        actual = call.result["items"][0]
        expected_ranking = call.result.get("ranking_version") if kind == "search" else None
        expected_rank = actual.get("rank") if kind == "search" else None
        call_id = call.id
    root = f"/v1/categories/{setup.category}" if run_scope.category_id else "/v1/personal"
    url = f"{root}/agent-sessions/{session_id}/work-state"
    state = setup.client.get(url, headers=setup.headers).json()
    response = setup.client.post(
        url,
        headers=setup.headers,
        json={
            "request_key": str(uuid4()),
            "expected_revision": state["revision"],
            "action": "exclude_source",
            "item_id": actual["citation_id"],
        },
    )
    assert response.status_code == 200, response.text
    saved = feedbacks(setup, run_scope.run_id)[0]
    assert saved["origin"] == kind and saved["origin_call_id"] == str(call_id)
    assert saved["citation_id"] == actual["citation_id"]
    assert saved["candidate"]["ranking_version"] == expected_ranking
    assert saved["candidate"]["rank"] == expected_rank
    assert saved["source"]["source_revision"] == actual["source_revision"]
    assert all(word not in str(saved) for word in ("RAW_ONLY", "更换密封圈", "UNCHANGED"))


def test_event_append_failure_rolls_back_exclusion_and_replay_saves_both(setup):
    artifact, run_id, session_id, _result = bound(setup)
    before = read(setup, session_id)
    key = uuid4()

    def fail(_mapper, _connection, target):
        if target.body.get("type") == KIND:
            raise RuntimeError("synthetic feedback append failed")

    event.listen(AgentEvent, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="synthetic feedback"):
            excluded(setup, session_id, before, artifact, key=key)
    finally:
        event.remove(AgentEvent, "before_insert", fail)
    assert read(setup, session_id)["revision"] == before["revision"]
    assert read(setup, session_id)["exclusions"] == [] and feedbacks(setup, run_id) == []
    assert excluded(setup, session_id, before, artifact, key=key).status_code == 200
    assert len(feedbacks(setup, run_id)) == 1


def test_exclusion_does_not_change_process_business_truth_or_model_context(setup):
    artifact, run_id, session_id, _result = bound(setup)
    run_url = f"/v1/categories/{setup.category}/agent-runs/{run_id}"
    before = setup.client.get(run_url, headers=setup.headers).json()["process"]
    assert excluded(setup, session_id, read(setup, session_id), artifact).status_code == 200
    after = setup.client.get(run_url, headers=setup.headers).json()["process"]
    for field in (
        "ended_at",
        "last_recorded_at",
        "call_counts",
        "business_receipt_count",
    ):
        assert after[field] == before[field]
    assert all(step["kind"] != KIND for step in after["steps"])
    child, _response = start(setup, continue_from_run_id=str(run_id), goal="继续核对。")
    from pdos_next.agent_kernel.bootstrap import Bootstrap

    context = Bootstrap(setup.engine).project_context(scope(setup, child), "继续核对。")
    assert context["work_state"]["exclusions"][0]["id"] == artifact
    assert KIND not in str(context)
    assert feedbacks(setup, run_id)[0]["feedback_id"] not in str(context)


def test_finish_and_exclusion_share_run_then_memory_lock_order_without_deadlock(setup, monkeypatch):
    artifact, run_id, session_id, original = bound(setup)
    before = read(setup, session_id)
    finish_holds_run, allow_finish, feedback_attempt, feedback_advisory = (
        Event() for _ in range(4)
    )
    real_lock = work_state._lock

    def gated_lock(session, tenant_id, identity):
        if current_thread().name.startswith("finish"):
            finish_holds_run.set()
            assert allow_finish.wait(5), "finish gate timed out"
        elif current_thread().name.startswith("feedback"):
            feedback_advisory.set()
        return real_lock(session, tenant_id, identity)

    def query_started(_connection, _cursor, statement, _parameters, _context, _many):
        if (
            current_thread().name.startswith("feedback")
            and "agent_runs" in statement
            and "FOR UPDATE" in statement.upper()
        ):
            feedback_attempt.set()

    monkeypatch.setattr(work_state, "_lock", gated_lock)
    event.listen(setup.engine, "before_cursor_execute", query_started)

    def change():
        with tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            requester_id=setup.human,
            category_id=setup.category,
        ) as session:
            session.execute(text("SET LOCAL lock_timeout = '5s'"))
            return work_state.change(
                session,
                setup.ctx,
                UUID(session_id),
                work_state.ChangeInput(
                    expected_revision=before["revision"],
                    request_key=uuid4(),
                    action="exclude_source",
                    item_id=artifact,
                ),
            )

    try:
        with ThreadPoolExecutor(1, thread_name_prefix="finish") as finisher:
            finished = finisher.submit(
                KernelStore(setup.engine).finish, scope(setup, run_id), original
            )
            assert finish_holds_run.wait(5)
            with ThreadPoolExecutor(1, thread_name_prefix="feedback") as editor:
                changed = editor.submit(change)
                try:
                    assert feedback_attempt.wait(5)
                    assert not feedback_advisory.is_set()
                finally:
                    allow_finish.set()
                finished.result(timeout=10)
                assert changed.result(timeout=10)["exclusions"][0]["id"] == artifact
    finally:
        allow_finish.set()
        event.remove(setup.engine, "before_cursor_execute", query_started)
    assert len(feedbacks(setup, run_id)) == 1
    with Session(setup.admin) as session:
        sequences = list(
            session.scalars(select(AgentEvent.sequence).where(AgentEvent.run_id == run_id))
        )
        assert len(sequences) == len(set(sequences))


def test_event_sequence_serializes_exclusion_with_existing_kernel_emitter(setup):
    artifact, run_id, session_id, _result = bound(setup)
    before = read(setup, session_id)
    run_scope = scope(setup, run_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        emitted = pool.submit(
            KernelStore(setup.engine).emit,
            run_scope,
            {"type": "synthetic_feedback_concurrency"},
        )
        changed = pool.submit(excluded, setup, session_id, before, artifact)
        assert changed.result(timeout=10).status_code == 200
        assert emitted.result(timeout=10) is not None
    with Session(setup.admin) as session:
        sequences = list(
            session.scalars(
                select(AgentEvent.sequence)
                .where(AgentEvent.run_id == run_id)
                .order_by(AgentEvent.sequence)
            )
        )
        assert len(sequences) == len(set(sequences))
        assert sequences == list(range(1, max(sequences) + 1))
    assert len(feedbacks(setup, run_id)) == 1


def test_feedback_cross_tenant_hidden_and_agent_has_no_direct_sql_write(setup):
    artifact, run_id, session_id, _result = bound(setup)
    assert excluded(setup, session_id, read(setup, session_id), artifact).status_code == 200
    with tenant_session(
        setup.engine,
        setup.other_tenant,
        actor_id=setup.other_human,
        requester_id=setup.other_human,
    ) as session:
        assert (
            session.scalar(
                select(AgentEvent.id).where(
                    AgentEvent.run_id == run_id, AgentEvent.body["type"].astext == KIND
                )
            )
            is None
        )
    with pytest.raises(DBAPIError) as caught:
        with Session(setup.admin) as session, session.begin():
            session.execute(text("SET LOCAL ROLE pdos_agent"))
            session.execute(
                text("""INSERT INTO public.agent_run_events
                (id,tenant_id,run_id,sequence,body,created_at)
                VALUES (:id,:tenant,:run,999,'{}'::jsonb,now())"""),
                {"id": uuid4(), "tenant": setup.tenant, "run": run_id},
            )
    assert getattr(caught.value.orig, "sqlstate", None) == "42501"


def test_app_ai_writer_and_wrong_recorded_by_cannot_insert_feedback(setup):
    from copy import deepcopy

    artifact, run_id, session_id, _result = bound(setup)
    assert excluded(setup, session_id, read(setup, session_id), artifact).status_code == 200
    saved = feedbacks(setup, run_id)[0]
    for actor, recorded_by in ((setup.agent, setup.human), (setup.human, setup.agent)):
        body = deepcopy(saved)
        identity = uuid4()
        body.update(feedback_id=str(identity), recorded_by=str(recorded_by))
        with pytest.raises(DBAPIError) as caught:
            with tenant_session(
                setup.engine,
                setup.tenant,
                actor_id=actor,
                requester_id=setup.human,
                category_id=setup.category,
            ) as session:
                sequence = (
                    session.scalar(
                        select(func.max(AgentEvent.sequence)).where(AgentEvent.run_id == run_id)
                    )
                    + 1
                )
                session.add(
                    AgentEvent(
                        id=identity,
                        tenant_id=setup.tenant,
                        run_id=run_id,
                        sequence=sequence,
                        body=body,
                    )
                )
                session.flush()
        assert getattr(caught.value.orig, "sqlstate", None) == "42501"
    assert len(feedbacks(setup, run_id)) == 1


def test_committed_exclusion_cannot_be_reused_for_a_new_human_feedback_event(setup):
    from copy import deepcopy

    artifact, run_id, session_id, _result = bound(setup)
    before = read(setup, session_id)
    request_key = uuid4()
    assert excluded(setup, session_id, before, artifact, key=request_key).status_code == 200
    # The normal original-key replay reads history and writes no new event.
    assert excluded(setup, session_id, before, artifact, key=request_key).status_code == 200
    body = deepcopy(feedbacks(setup, run_id)[0])
    identity = uuid4()
    body["feedback_id"] = str(identity)
    with pytest.raises(DBAPIError) as caught:
        with tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            requester_id=setup.human,
            category_id=setup.category,
        ) as session:
            sequence = (
                session.scalar(
                    select(func.max(AgentEvent.sequence)).where(AgentEvent.run_id == run_id)
                )
                + 1
            )
            session.add(
                AgentEvent(
                    id=identity,
                    tenant_id=setup.tenant,
                    run_id=run_id,
                    sequence=sequence,
                    body=body,
                )
            )
            session.flush()
    assert getattr(caught.value.orig, "sqlstate", None) == "23514"
    assert len(feedbacks(setup, run_id)) == 1
