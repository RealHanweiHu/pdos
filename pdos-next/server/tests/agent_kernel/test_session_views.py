"""Offline contract/SQL-shape checks; no database or runtime/model invocation."""

from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from pdos_next.agent_kernel import session_views as views
from pdos_next.service import Context


def context(category=True):
    actor = uuid4()
    return Context(uuid4(), actor, actor, category_id=uuid4() if category else None)


@pytest.mark.parametrize("page_size", [0, 51, -1])
def test_page_limits_are_validated_instead_of_silently_clamped(page_size):
    for model in (views.SessionPage, views.RunPage):
        with pytest.raises(ValidationError):
            model(page_size=page_size)


def test_query_contract_rejects_unknown_and_malformed_fields():
    assert views.SessionPage(q="  50%_\\  ").q == "50%_\\"
    for value in ({"q": "x" * 161}, {"cursor": "bad"}, {"owner_id": str(uuid4())}):
        with pytest.raises(ValidationError):
            views.SessionPage.model_validate(value)
    with pytest.raises(ValidationError):
        views.RunPage(q="not a detail parameter")


def test_goal_search_is_literal_and_bound_instead_of_sql_wildcards():
    assert views._pattern("50%_\\") == "%50\\%\\_\\\\%"
    base = views._runs(views._sessions(context(), None))
    compiled = select(views._matched(base, "50%_\\")).compile(dialect=postgresql.dialect())
    assert "%50\\%\\_\\\\%" in compiled.params.values()
    assert "50%" not in str(compiled)
    assert "ESCAPE" in str(compiled)


def test_run_projection_keeps_scope_and_parents_in_sql_without_loading_body():
    ctx = context()
    sql = str(
        select(views._runs(views._sessions(ctx, uuid4()))).compile(dialect=postgresql.dialect())
    )
    assert "EXISTS (SELECT products.id" in sql
    assert "EXISTS (SELECT proposals.id" in sql
    for name in ("category_id", "product_id", "proposal_id"):
        assert f"agent_runs.{name} IS NOT DISTINCT FROM readable_sessions.{name}" in sql
    for column in ("result", "read_sources", "versions", "customer_identities", "intent_key"):
        assert f"agent_runs.{column}" not in sql
    personal = str(select(views._sessions(context(False), None)))
    assert "agent_sessions.product_id IS NULL" in personal
    assert "agent_sessions.proposal_id) IS NULL" in personal


def test_head_preserves_saved_goal_clock_and_revert_without_session_status():
    identity, parent = uuid4(), uuid4()
    at = datetime(2026, 10, 17, tzinfo=UTC)
    head = views._head(
        {
            "run_id": identity,
            "goal": "An actual original goal",
            "status": "cancelled",
            "error_code": None,
            "created_at": at,
            "continued_from_id": parent,
            "reverted_at": at,
        }
    )
    assert head == {
        "run_id": str(identity),
        "goal": "An actual original goal",
        "status": "cancelled",
        "error_code": None,
        "created_at": at.isoformat(),
        "continued_from_id": str(parent),
        "reverted": True,
    }
    assert not {"title", "archived", "pinned", "session_status"} & head.keys()


def test_project_filter_binds_actual_session_and_run_before_any_search_or_paging():
    ctx, project = context(), uuid4()
    sessions = views._sessions(ctx, None, project)
    compiled = select(views._matched(views._runs(sessions), "original goal")).compile(
        dialect=postgresql.dialect()
    )
    sql = str(compiled)
    assert project in compiled.params.values()
    assert "agent_sessions.project_id =" in sql
    assert "EXISTS (SELECT projects.id" in sql
    assert "agent_runs.project_id IS NOT DISTINCT FROM readable_sessions.project_id" in sql
    assert "agent_sessions.owner_id =" in sql
    assert "LIMIT" not in sql
    assert "agent_runs.result" not in sql
    assert views._scope(ctx, None) == {"category_id": str(ctx.category_id), "proposal_id": None}
    assert views._scope(ctx, None, project)["project_id"] == str(project)
    for model in (views.SessionPage, views.RunPage):
        assert model(project_id=project).project_id == project
        with pytest.raises(ValidationError):
            model(project_id="not-a-project")


def test_router_query_models_and_read_snapshot_are_wired_without_a_database(monkeypatch):
    seen = []

    @contextmanager
    def transaction(ctx, *, read_snapshot=False):
        assert read_snapshot is True
        yield object()

    def listing(_session, ctx, page):
        seen.append((ctx, page))
        return {"version": "agent-session-list/v1"}

    def details(_session, ctx, identity, page):
        seen.append((ctx, identity, page))
        return {"version": "agent-session-runs/v1"}

    monkeypatch.setattr(views, "read_list", listing)
    monkeypatch.setattr(views, "read_runs", details)
    ctx = context(False)
    app = FastAPI()
    from fastapi import Depends

    app.include_router(
        views.router(transaction=transaction, context_dependency=Depends(lambda: ctx))
    )
    with TestClient(app) as client:
        assert (
            client.get("/v1/personal/agent-sessions", params={"q": "  literal%_  "}).status_code
            == 200
        )
        assert seen[-1][1].q == "literal%_"
        assert client.get(f"/v1/personal/agent-sessions/{uuid4()}/runs").status_code == 200
        assert (
            client.get("/v1/personal/agent-sessions", params={"page_size": 51}).status_code == 422
        )
        assert (
            client.get("/v1/personal/agent-sessions", params={"unexpected": "x"}).status_code == 422
        )
        assert (
            client.get(f"/v1/personal/agent-sessions/{uuid4()}/runs", params={"q": "x"}).status_code
            == 422
        )
        assert client.post("/v1/personal/agent-sessions").status_code == 405
