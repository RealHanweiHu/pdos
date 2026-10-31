"""Offline validation and authorization ordering; no database or runtime calls."""

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from pdos_next.agent_kernel import session_presentation as service
from pdos_next.agent_kernel import session_presentation_api as api
from pdos_next.errors import DomainError
from pdos_next.service import Context


def context():
    owner = uuid4()
    return Context(uuid4(), owner, owner, category_id=uuid4())


def request(action="rename", **changes):
    value = {"expected_revision": 0, "request_key": uuid4(), "action": action}
    if action == "rename":
        value["title"] = "  我的会话  "
    return service.PresentationInput.model_validate({**value, **changes})


@pytest.mark.parametrize("changes", [
    {"expected_revision": -1}, {"expected_revision": True}, {"expected_revision": "0"},
    {"owner_id": str(uuid4())}, {"run_id": str(uuid4())}, {"request_key": "bad"},
    {"title": " "}, {"title": "x" * 161}, {"action": "delete"},
])
def test_write_contract_rejects_authority_injection_and_invalid_values(changes):
    with pytest.raises(ValidationError):
        request(**changes)


def test_only_rename_accepts_and_requires_a_nullable_title():
    assert request().title == "我的会话"
    assert request(title=None).title is None
    with pytest.raises(ValidationError):
        service.PresentationInput(expected_revision=0, request_key=uuid4(), action="rename")
    for action in ("pin", "unpin", "archive", "restore"):
        assert "title" not in request(action).model_fields_set
        with pytest.raises(ValidationError):
            request(action, title=None)


@pytest.mark.parametrize("value", [
    {"view": "all"}, {"q": "x" * 161}, {"page_size": 0}, {"page_size": 51},
    {"owner_id": str(uuid4())}, {"cursor": "bad"},
])
def test_list_query_bounds_and_exact_filter_contract(value):
    with pytest.raises(ValidationError):
        service.ConversationPage.model_validate(value)


def test_search_compiles_with_current_actual_parents_and_project_before_pagination():
    compiled = select(service._eligible(
        context(), service.ConversationPage(q="50%_\\", view="archived")
    )).compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "EXISTS (SELECT products.id" in sql
    assert "EXISTS (SELECT proposals.id" in sql
    assert "EXISTS (SELECT projects.id" in sql
    assert (
        "agent_runs.project_id IS NOT DISTINCT FROM presentation_readable_sessions.project_id"
        in sql
    )
    assert "DISTINCT ON (agent_session_presentations.session_id)" in sql
    assert "latest_session_presentation.title ILIKE" in sql
    assert "LEFT OUTER JOIN matching_run_heads" in sql
    assert "%50\\%\\_\\\\%" in compiled.params.values()
    assert "LIMIT" not in sql and "OFFSET" not in sql
    assert "agent_runs.result" not in sql and "agent_runs.read_sources" not in sql


def test_project_conversation_selector_precedes_title_search_counts_and_cursor():
    project = uuid4()
    page = service.ConversationPage(project_id=project, q="saved discussion")
    compiled = select(service._eligible(context(), page)).compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert project in compiled.params.values()
    assert "agent_sessions.project_id =" in sql
    assert "EXISTS (SELECT projects.id" in sql
    assert (
        "agent_runs.project_id IS NOT DISTINCT FROM presentation_readable_sessions.project_id"
        in sql
    )
    assert "LIMIT" not in sql
    assert "agent_runs.result" not in sql
    # Read filtering does not change the original presentation write/receipt contract.
    assert "project_id" not in service.PresentationScope.model_fields


class WriteSession:
    def __init__(self, previous=None):
        self.previous = previous
        self.added = []
        self.locks = []

    def execute(self, statement, params):
        assert "pg_advisory_xact_lock" in str(statement)
        self.locks.append(params["key"])

    def scalar(self, _statement):
        return self.previous

    def add(self, row):
        self.added.append(row)

    def flush(self):
        for row in self.added:
            row.id, row.created_at = uuid4(), datetime(2026, 10, 19, tzinfo=UTC)


def target():
    return SimpleNamespace(
        id=uuid4(), category_id=uuid4(), product_id=uuid4(), proposal_id=None, project_id=uuid4()
    )


def prepare_change(monkeypatch, selected, previous_request=None):
    checks = []
    monkeypatch.setattr(service, "_human", lambda *_: checks.append("human"))

    def checked_target(*_args, **kwargs):
        assert kwargs.get("lock") is True
        checks.append("current_session_and_parents")
        return selected

    monkeypatch.setattr(service, "_target", checked_target)

    def lookup(*_args):
        checks.append("request_lookup")
        return previous_request

    monkeypatch.setattr(service, "_request", lookup)
    return checks


def test_human_and_current_parent_checks_precede_idempotent_replay(monkeypatch):
    ctx, selected, data = context(), target(), request()
    session = WriteSession()
    checks = prepare_change(monkeypatch, selected)
    original = service.change(session, ctx, selected.id, data)
    assert checks == ["human", "current_session_and_parents", "request_lookup"]
    assert "session-presentation-request:" in session.locks[0]
    assert "session-presentation-session:" in session.locks[1]
    assert len(session.added) == 1
    saved = session.added[0]
    prepare_change(monkeypatch, selected, saved)
    session.previous = SimpleNamespace(revision=12)
    assert service.change(session, ctx, selected.id, data) == original
    assert len(session.added) == 1
    assert not {"current", "as_of", "can_continue"} & original.keys()
    assert original["presentation"]["revision"] == 1


def test_original_request_cannot_be_reused_with_a_different_body(monkeypatch):
    ctx, selected, data = context(), target(), request()
    session = WriteSession()
    prepare_change(monkeypatch, selected)
    service.change(session, ctx, selected.id, data)
    prepare_change(monkeypatch, selected, session.added[0])
    with pytest.raises(DomainError) as raised:
        service.change(session, ctx, selected.id, request(
            title="另一个标题", request_key=data.request_key
        ))
    assert (raised.value.code, raised.value.status) == ("DUPLICATE_INTENT_CONFLICT", 409)
    assert len(session.added) == 1


def test_stale_revision_refuses_append_and_each_action_preserves_other_presentation(monkeypatch):
    ctx, selected = context(), target()
    previous = SimpleNamespace(id=uuid4(), revision=4, title="保留标题", pinned=True, archived=True)
    session = WriteSession(previous)
    prepare_change(monkeypatch, selected)
    with pytest.raises(DomainError) as raised:
        service.change(session, ctx, selected.id, request("restore", expected_revision=3))
    assert (raised.value.code, raised.value.status) == ("VERSION_CONFLICT", 409)
    assert not session.added
    value = service.change(session, ctx, selected.id, request("restore", expected_revision=4))
    assert value["presentation"]["title"] == "保留标题"
    assert value["presentation"]["pinned"] is True
    assert value["presentation"]["archived"] is False
    assert session.added[0].previous_id == previous.id
    assert previous.revision == 4 and previous.archived is True


def test_recovery_refuses_reading_a_request_until_parent_access_is_checked(monkeypatch):
    seen = []
    monkeypatch.setattr(service, "_human", lambda *_: seen.append("human"))

    def denied(*_args):
        seen.append("current_parents")
        raise DomainError("FORBIDDEN_SCOPE", "项目已不可读。", 403)

    monkeypatch.setattr(service, "_target", denied)
    monkeypatch.setattr(service, "_request", lambda *_: pytest.fail("request leaked before ACL"))
    with pytest.raises(DomainError) as raised:
        service.read_request(object(), context(), uuid4(), uuid4())
    assert raised.value.status == 403
    assert seen == ["human", "current_parents"]


def test_router_exposes_only_frozen_routes_and_uses_write_or_read_transactions(monkeypatch):
    transactions = []

    @contextmanager
    def transaction(_ctx, *, read_snapshot=False):
        transactions.append(read_snapshot)
        yield object()

    monkeypatch.setattr(api, "read_list", lambda *_: {"kind": "list"})
    monkeypatch.setattr(api, "change", lambda *_: {"kind": "change"})
    monkeypatch.setattr(api, "read_request", lambda *_: {"kind": "recovery"})
    app = FastAPI()
    router = api.router(transaction=transaction, context_dependency=Depends(context))
    app.include_router(router)
    routes = {route.path: route for route in router.routes if hasattr(route, "methods")}
    prefix = "/v1/personal/agent-sessions/{session_id}/presentation"
    assert routes[prefix].methods == {"POST"}
    assert routes[prefix + "/requests/{request_key}"].methods == {"GET"}
    assert not any("DELETE" in route.methods for route in routes.values())
    ctx = context()
    assert routes["/v1/personal/agent-conversations"].endpoint(
        page=service.ConversationPage(), ctx=ctx
    ) == {"kind": "list"}
    assert routes[prefix].endpoint(
        session_id=uuid4(), data=request(), page=service.PresentationScope(), ctx=ctx
    ) == {"kind": "change"}
    assert routes[prefix + "/requests/{request_key}"].endpoint(
        session_id=uuid4(), request_key=uuid4(), page=service.PresentationScope(), ctx=ctx
    ) == {"kind": "recovery"}
    assert transactions == [True, False, True]
    schema = app.openapi()
    assert {p["name"] for p in schema["paths"][prefix]["post"]["parameters"]} == {
        "session_id", "proposal_id"
    }
