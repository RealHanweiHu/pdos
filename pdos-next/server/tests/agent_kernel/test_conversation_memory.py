"""History semantics using local query doubles; PostgreSQL coverage is separate."""

import json
from contextlib import contextmanager
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from pdos_next.agent_kernel import conversation
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.context_budget import estimate_tokens
from pdos_next.errors import DomainError


class Session:
    def __init__(self, calls=(), values=()):
        self.calls, self.values = calls, iter(values)

    def execute(self, _):
        return NS(all=lambda: self.calls)

    def scalar(self, _):
        return next(self.values)


def row():
    return NS(id=uuid4(), session_id=uuid4(), goal="用户原话", state="completed",
              result={"summary": "回答" * 500, "unfinished": ["核对工况"]}, read_sources=[
                  {"artifact_id": str(uuid4()), "expected_revision": 1}])


def call(kind="read", tool="category.read", **kwargs):
    return NS(id=uuid4(), tool=tool, state="completed", receipt_id=None,
              execution_binding={"kind": kind, "model_call_id": str(uuid4()),
                                 "response_index": 0, **kwargs})


@pytest.fixture(autouse=True)
def scope_stub(monkeypatch):
    monkeypatch.setattr(conversation, "scope_for_run", lambda _: "synthetic scope")


@pytest.mark.parametrize("state", ["current", "updated", "hidden"])
def test_classify_preserves_dated_answer_and_only_hides_revocation(state):
    original = row()
    access = {str(original.id): {"prepared": False, "unverified": [], "research": []}}
    def forbidden(*_):
        pytest.fail("A history view must not replay the full reader")
    value = conversation.classify_turn(None, original, {"category.read": forbidden}, None,
                                      access=access, states={str(original.id): state})
    assert value["state"] == state
    if state == "hidden":
        assert value["outcome"] is None
    else:
        assert value["outcome"]["summary"] == original.result["summary"]
        assert ("资料已更新" in str(value["outcome"]["notes"])) == (state == "updated")


def test_candidate_and_unverified_read_keep_answer():
    original = row()
    access = {str(original.id): {"prepared": True, "unverified": ["custom.read"], "research": []}}
    value = conversation.classify_turn(None, original, {}, None, access=access,
                                      states={str(original.id): "current"})
    assert value["state"] == "current"
    assert value["outcome"]["summary"] == original.result["summary"]
    assert "准备过候选" in str(value["outcome"]["notes"])
    assert "未复核：custom.read" in str(value["outcome"]["notes"])


def test_thirty_turn_layering_full_history_and_hidden_sources(monkeypatch):
    rows = [row() for _ in range(30)]
    monkeypatch.setattr(conversation, "lineage", lambda *_: rows)
    from pdos_next.agent_kernel import conversation_acl
    monkeypatch.setattr(conversation_acl, "manifests", lambda _s, selected, **_k: {
        str(item.id): {"prepared": False, "unverified": [], "research": []}
        for item in selected})
    monkeypatch.setattr(conversation_acl, "classify", lambda _s, access, **_k: {
        identity: "current" for identity in access})
    current = row()
    value = conversation.memory(Session(), current, readers={})
    assert len(value["turns"]) == 10
    for turn in value["turns"][:3]:
        assert len(turn["historical_outcome"]["summary"]) < 660
        assert turn["historical_outcome"]["truncated"]
        assert turn["historical_outcome"]["unfinished"] == ["核对工况"]
    for turn in value["turns"][3:]:
        assert len(turn["historical_outcome"]["summary"]) <= 60
        assert "仅显示目录" in turn["historical_outcome"]["notes"]
        assert turn["historical_outcome"]["unfinished"] == []
    assert estimate_tokens(json.dumps(value, ensure_ascii=False)) <= 4000
    from pdos_next.agent_kernel.context_projection import combine_contracts, project
    from pdos_next.agent_kernel.skills import SkillCatalog

    raw = {"goal": "继续", "sources": [], "conversation": value}
    projected, omitted, issues = project(raw, combine_contracts(SkillCatalog(), []))
    assert not omitted and not issues
    assert projected == raw
    full = conversation.memory(Session(), current, readers={}, layered=False)
    assert full["turns"][0]["historical_outcome"]["summary"] == rows[0].result["summary"]
    rows[0].result["summary"] = "长" * 9000
    capped = conversation.memory(Session(), current, readers={}, layered=False)
    assert capped["turns"][0]["historical_outcome"]["summary"] == "长" * 8000
    monkeypatch.setattr(conversation, "classify_turn", lambda *_args, **_kwargs: {
        "state": "hidden", "outcome": None,
    })
    hidden = conversation.memory(Session(), current, readers={})
    assert all(t["sources"] == [] and t["historical_outcome"] is None for t in hidden["turns"])


@pytest.mark.parametrize("state, revoked", [("updated", False), ("hidden", True)])
def test_running_guard_only_stops_newly_hidden_turns(monkeypatch, state, revoked):
    host = Bootstrap.__new__(Bootstrap)
    run = NS(continued_from_id=uuid4(), versions={"conversation_memory": {
        "turns": [{"run_id": "parent", "outcome_state": "current"}],
    }, "conversation_access": {"parent": {"projects": [], "project_dependencies": [],
                                           "project_unavailable": False}}})

    @contextmanager
    def transaction(_):
        yield None, run

    host.store = NS(transaction=transaction)
    from pdos_next.agent_kernel import conversation_acl
    monkeypatch.setattr(conversation_acl, "classify", lambda *_a, **_k: {"parent": state})
    if revoked:
        with pytest.raises(DomainError) as failure:
            host.check_conversation(NS(project_id=None, isolation="main"))
        assert failure.value.reason == "CONVERSATION_HISTORY_REVOKED"
    else:
        host.check_conversation(NS(project_id=None, isolation="main"))


def test_scope_revoked_before_transaction_yields_is_mapped():
    host = Bootstrap.__new__(Bootstrap)

    @contextmanager
    def transaction(_):
        raise DomainError("FORBIDDEN_SCOPE", "scope revoked")
        yield  # pragma: no cover

    host.store = NS(transaction=transaction)
    with pytest.raises(DomainError) as failure:
        host.check_conversation(NS(project_id=None, isolation="main"))
    assert failure.value.reason == "CONVERSATION_HISTORY_REVOKED"


@pytest.mark.parametrize("state", ["running", "completed"])
def test_history_freezes_active_context_once_and_never_rewrites_terminal_run(monkeypatch, state):
    from pdos_next.agent_kernel import bootstrap, execution, work_state

    host = Bootstrap.__new__(Bootstrap)
    run = NS(continued_from_id=uuid4(), versions={}, read_sources=[], trigger="conversation",
             state=state)
    session = NS(get=lambda *_: run)
    scope = NS(tenant_id=uuid4(), writer_id=uuid4(), requester_id=uuid4(), category_id=None,
               product_id=None, proposal_id=None, project_id=None, run_id=uuid4(), isolation="main")

    @contextmanager
    def transaction(*_args, **_kwargs):
        yield session

    @contextmanager
    def locked(*_args, **_kwargs):
        yield session, run

    monkeypatch.setattr(bootstrap, "tenant_session", transaction)
    monkeypatch.setattr(execution, "check_run_binding", lambda *_args, **_kwargs: None)
    calls = []

    def memory(*_args, **_kwargs):
        calls.append(True)
        return {"turns": [{"run_id": "parent", "outcome_state": "current"}]}

    monkeypatch.setattr(conversation, "memory", memory)
    host.engine = None
    host.commands = NS(context=lambda *_: None)
    monkeypatch.setattr(work_state, "frozen", lambda *_: {})
    host.store = NS(transaction=locked, authority=lambda *_: None)
    first = host.project_context(scope, "继续")
    second = host.project_context(scope, "加载技能后")
    assert first["conversation"] == second["conversation"]
    if state == "running":
        assert first["conversation"] == run.versions["conversation_memory"]
        assert len(calls) == 1
    else:
        assert "conversation_memory" not in run.versions
        assert "conversation_access" not in run.versions
        assert len(calls) == 2


def test_paged_history_revocation_is_checked_beyond_initial_window(monkeypatch):
    host = Bootstrap.__new__(Bootstrap)
    run = NS(continued_from_id=uuid4(), versions={"conversation_memory": {"turns": []},
        "conversation_access": {}, "conversation_history_pages": {"page": {
            "access": {"older": {"projects": [], "project_dependencies": [],
                                  "project_unavailable": False}},
            "before": str(uuid4()), "page_size": 5, "include_research_rows": True, "hidden": [],
        }}})

    @contextmanager
    def transaction(_):
        yield None, run

    host.store = NS(transaction=transaction)

    def current(*_args, **kwargs):
        return {"turns": [] if kwargs.get("layered", True) else [
            {"run_id": "older", "outcome_state": "hidden"}]}

    from pdos_next.agent_kernel import conversation_acl
    monkeypatch.setattr(conversation_acl, "classify", lambda *_a, **_k: {"older": "hidden"})
    monkeypatch.setattr(conversation, "memory", lambda *_a, **_k: pytest.fail("history rebuilt"))
    with pytest.raises(DomainError) as failure:
        host.check_conversation(NS(project_id=None, isolation="main"))
    assert failure.value.reason == "CONVERSATION_HISTORY_REVOKED"


@pytest.mark.parametrize("enabled, exclude, expected", [
    (True, set(), ("public_research", "gap_check")),
    (True, {"public_research", "gap_check"}, ()),
    (False, set(), None),
])
def test_continued_skills_are_bounded_deduplicated_and_currently_enabled(
    monkeypatch, enabled, exclude, expected
):
    from pdos_next.agent_kernel import requested_skills
    from pdos_next.agent_kernel.skills import SkillCatalog

    keys = ["option_comparison", "public_research", "public_research", "gap_check",
            "proposal_drafting"]
    catalog = SkillCatalog()
    events = [{"type": "skill_loaded", "key": key,
               "version": catalog.configuration(key).version,
               "digest": catalog.configuration(key).digest,
               "isolation": "research" if index == 0 else "main"}
              for index, key in enumerate(keys)]
    monkeypatch.setattr(requested_skills, "skill_enabled", lambda *_: enabled)
    session = NS(scalars=lambda *_: events)
    if not enabled:
        with pytest.raises(DomainError) as rejected:
            requested_skills.continued(session, None, NS(continued_from_id=uuid4()),
                                       exclude=exclude)
        assert rejected.value.code == "FORBIDDEN_SCOPE"
        assert rejected.value.detail["reason"] == "requested_skill_unavailable"
        return
    assert requested_skills.continued(session, None, NS(continued_from_id=uuid4()),
                                      exclude=exclude) == expected
