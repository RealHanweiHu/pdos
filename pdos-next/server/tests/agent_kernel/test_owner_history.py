"""Pure owner-goal projection contracts; no database, model or provider access."""

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from pdos_next.agent_kernel import api, owner_history, session_views
from pdos_next.agent_kernel.work_state import PAGE_MATERIAL_BOUNDARY
from pdos_next.errors import DomainError
from pdos_next.service import Context


def recorded():
    return {
        "run_id": uuid4(), "session_id": uuid4(), "revision": 3,
        "recorded_at": datetime(2026, 10, 29, tzinfo=UTC), "goal": "本人原话 50%_\\",
        "session_category_id": uuid4(), "session_product_id": None,
        "session_proposal_id": None, "session_project_id": None,
        "summary": "PRIVATE_REPLY", "read_sources": ["PRIVATE_SOURCE"],
        "versions": {"private": "PRIVATE_VERSION"}, "result": {"secret": True},
    }


def context():
    human = uuid4()
    return Context(uuid4(), human, human, category_id=uuid4())


def test_projection_selects_only_recorded_goal_and_current_owned_parent_scope():
    ctx = context()
    query = owner_history.goal_rows(session_views._sessions(ctx, None))
    compiled = query.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert len(query.selected_columns) == 9
    assert "agent_work_states.owner_id = readable_sessions.owner_id" in sql
    assert "agent_work_states.tenant_id = readable_sessions.tenant_id" in sql
    assert "agent_work_states.session_id = readable_sessions.session_id" in sql
    assert "agent_sessions.owner_id =" in sql
    assert ctx.requester_id in compiled.params.values()
    for table in ("products", "proposals", "projects"):
        assert f"EXISTS (SELECT {table}.id" in sql
    assert "split_part(" in sql and PAGE_MATERIAL_BOUNDARY in compiled.params.values()
    assert "jsonb_typeof(" in sql and "CAST(agent_work_states.run_id AS VARCHAR)" in sql
    assert "run" in compiled.params.values()
    assert {"current_goal", "text", "run_id"}.issubset(compiled.params.values())
    for forbidden in ("agent_runs.", "summary", "read_sources", "versions", "SECURITY DEFINER"):
        assert forbidden not in sql
    assert all(str(column) != "agent_work_states.body" for column in query.selected_columns)


def test_hidden_union_keeps_normal_run_rls_and_never_projects_hidden_run_body():
    sql = str(select(session_views._runs(session_views._sessions(context(), None))).compile(
        dialect=postgresql.dialect()))
    assert "UNION ALL" in sql and "NOT (EXISTS (SELECT agent_runs.id" in sql
    for forbidden in ("result", "read_sources", "versions", "customer_identities", "intent_key"):
        assert f"agent_runs.{forbidden}" not in sql
    assert "agent_runs.goal" in sql


def test_hidden_detail_has_no_original_status_clock_lineage_or_private_body():
    goal = recorded()
    value = owner_history.hidden_detail(goal)
    assert value["goal"] == goal["goal"]
    assert value["status"] == "hidden" and value["history_hidden"] is True
    assert value["result"] is None and value["versions"] == {}
    assert value["recorded_at"] == goal["recorded_at"].isoformat()
    for key in ("created_at", "reverted", "cancel_epoch", "process", "reconciliation"):
        assert value[key] is None
    assert value["conversation"] == {
        "previous_run_id": None, "next_run_id": None, "links_unavailable": True,
    }
    assert not {"read_sources", "summary", "revision", "continued_from_id"} & value.keys()
    assert "PRIVATE_" not in str(value)


def test_hidden_head_labels_record_clock_without_faking_run_clock():
    goal = recorded()
    head = session_views._head({**goal, "status": "hidden",
                               "created_at": goal["recorded_at"]})
    assert head["goal"] == goal["goal"] and head["history_hidden"] is True
    assert head["created_at"] is None
    assert head["recorded_at"] == goal["recorded_at"].isoformat()
    assert head["continued_from_id"] is head["reverted"] is None
    assert "PRIVATE_" not in str(head)


@pytest.mark.parametrize("changed", ["requester", "agent", "inactive", "tenant", "run"])
def test_goal_reader_rejects_non_current_human_before_query(changed):
    ctx = context()
    actor = SimpleNamespace(tenant_id=ctx.tenant_id, active=True, kind="human")
    if changed == "requester":
        ctx = Context(ctx.tenant_id, ctx.actor_id, uuid4(), category_id=ctx.category_id)
    elif changed == "agent":
        actor.kind = "agent"
    elif changed == "inactive":
        actor.active = False
    elif changed == "tenant":
        actor.tenant_id = uuid4()
    else:
        ctx = Context(ctx.tenant_id, ctx.actor_id, ctx.requester_id,
                      category_id=ctx.category_id, run_id=uuid4())
    session = SimpleNamespace(get=lambda *_: actor)
    with pytest.raises(DomainError) as failure:
        owner_history.goals(session, ctx, run_id=uuid4())
    assert failure.value.status == 403


def test_authenticated_get_fallback_stops_before_result_process_or_execution(monkeypatch):
    ctx, goal, calls = context(), recorded(), []

    @contextmanager
    def transaction(_engine, _tenant, **kwargs):
        assert kwargs["read_snapshot"] is True
        yield SimpleNamespace(get=lambda *_: None, scalar=lambda *_: None)

    def goals(_session, actual, *, run_id):
        assert actual == ctx and run_id == goal["run_id"]
        calls.append(run_id)
        return [goal]

    monkeypatch.setattr(api, "tenant_session", transaction)
    monkeypatch.setattr(owner_history, "goals", goals)
    app = FastAPI()

    @app.exception_handler(DomainError)
    async def failure(_, error):
        return JSONResponse(error.payload(), status_code=error.status)

    app.include_router(api.router(object(), context_dependency=lambda: ctx,
                                  ports=api.ApiPorts(None, None, None, None, None)))
    root = f"/v1/categories/{ctx.category_id}/agent-runs/{goal['run_id']}"
    with TestClient(app) as client:
        response = client.get(root)
        assert response.status_code == 200, response.text
        assert response.json() == owner_history.hidden_detail(goal)
        for suffix in ("process", "events", "candidates", "continuation"):
            assert client.get(f"{root}/{suffix}").status_code == 403
        assert calls == [goal["run_id"]]
        monkeypatch.setattr(owner_history, "goals", lambda *_args, **_kwargs: [])
        assert client.get(root).status_code == 403
