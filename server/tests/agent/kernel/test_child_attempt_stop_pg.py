"""D269: the stop signal reaches the research, MCP, comparison and extraction children.

Each child kind runs on the production host built at startup, with the actual gateway,
ledger and read bindings and a scripted provider (no real model, no real network).

Three cases per child, as in D243/D257:
- given up: Temporal gives the attempt up while a child request is in flight. That
  request settles as usual (it was already claimed and is real), the child claims
  nothing after the signal, and the parent call stays open, so its partial result is
  never written. The next attempt resumes and replays the settled request, so nothing
  is sent twice.
- cancelled: the run is cancelled while a child request is in flight. Its late result
  is not written, the call stays recorded as cancelled, and nothing new is claimed.
- the late result itself is checked in both: settled and replayable when given up,
  not written when cancelled.
"""
# ruff: noqa: F811 -- pytest uses the explicitly imported marked database fixtures

import asyncio
import json
from contextlib import nullcontext
from dataclasses import replace
from threading import Event, Lock
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent.enterprise_search.comparison_graph import AssistantComparisonGraph
from pdos_next.agent.kernel.bootstrap import Bootstrap, RuntimePorts
from pdos_next.agent.kernel.extract_adapter import ExtractReadAdapter
from pdos_next.agent.kernel.extract_graph import ExtractGraph
from pdos_next.agent.kernel.extract_service import ExtractionService
from pdos_next.agent.kernel.graph import AgentKernel
from pdos_next.agent.kernel.host import BoundHost
from pdos_next.agent.kernel.models import AgentRun, AgentToolCall, ValidationBudget
from pdos_next.agent.kernel.persistence import cancel_run, create_run
from pdos_next.agent.kernel.research_graph import ResearchGraph
from pdos_next.agent.kernel.run_lease import AttemptSuperseded, attempt_scope
from pdos_next.agent.kernel.types import ModelTurn, ToolCall
from pdos_next.agent.research import ResearchTask
from pdos_next.core.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.providers.types import ProviderUsage
from tests.agent.enterprise_search.test_assistant_extract_concurrency_pg import Saver
from tests.agent.enterprise_search.test_comparison_pg import starting
from tests.agent.kernel import test_mcp_graph_transactions as mcp
from tests.agent.kernel.research.test_research import Search, Transport
from tests.agent.kernel.research.test_research import service as research_service
from tests.agent.kernel.test_cost_budget import rate, wallet
from tests.agent.kernel.test_extract_dispatch_pg import extract, quote_row
from tests.agent.kernel.test_extract_dispatch_pg import fixture as extract_fixture
from tests.agent.kernel.test_gateway import configured_route
from tests.agent.kernel.test_m3_original_binding_pg import QUOTE
from tests.agent.kernel.test_transactions import human_session
from tests.categories.preproject.test_g0 import work as work
from tests.originals.test_original_security import security_work as security_work

PROVIDER = "synthetic-child-stop-no-egress"


def ledger(admin, run_id, budget=None):
    with Session(admin) as session:
        run = session.get(AgentRun, run_id)
        calls = session.scalars(select(AgentToolCall).where(
            AgentToolCall.run_id == run_id).order_by(AgentToolCall.created_at)).all()
        purse = session.get(ValidationBudget, budget) if budget else None
        session.expunge_all()
    return run, calls, purse


def of(calls, tool, isolation=None):
    return [row for row in calls if row.tool == tool and (
        isolation is None or row.execution_binding.get("isolation") == isolation)]


def no_open_reservation(run, calls, purse=None):
    assert run.held_tokens == 0
    assert all(row.reserved_tokens == 0 for row in calls)
    if purse is not None:
        assert purse.held_micro_usd == 0 and purse.held_input_tokens == 0
        assert purse.held_output_tokens == 0


def cancelled_mid_call(row):
    """The truthful record of a request whose result arrived after the cancel."""
    return row.state == "unknown" and row.error_code == "CANCELLED_RUN" and row.result is None


# --- Research: the child graph driven directly, as ResearchService.fanout runs it ---


class ResearchClient:
    """Child steps: search, read the first hit, return one quoted ledger row."""

    def __init__(self):
        self.lock, self.calls = Lock(), 0

    def close(self):
        pass

    def turn(self, _route, **kwargs):
        assert {row["name"] for row in kwargs["tools"]} == {
            "research.search", "research.read", "result.read"}
        values = [json.loads(m["content"]) for m in kwargs["messages"] if m["role"] == "tool"]
        with self.lock:
            self.calls += 1
        if not values:
            return ModelTurn(calls=(ToolCall(
                id="search", name="research.search", arguments={"query": "pump pressure"},
            ),), usage=ProviderUsage(10, 2))
        if len(values) == 1:
            return ModelTurn(calls=(ToolCall(
                id="read", name="research.read",
                arguments={"url": values[0]["hits"][0]["url"]},
            ),), usage=ProviderUsage(10, 2))
        page = values[-1]
        row = {"brand": "Maker", "model": "P1", "free_key": "pressure", "value": 20,
               "unit": "psi", "quote": "Pressure: 20 psi", "snapshot_id": page["snapshot_id"],
               "locator": page["locator"]}
        return ModelTurn(structured={
            "status": "completed", "summary": "合成研究", "result": {"rows": [row]},
            "questions": [], "unfinished": [],
        }, usage=ProviderUsage(10, 2))


class HookedSearch(Search):
    """The search request is in flight when ``hook`` runs."""

    def __init__(self):
        super().__init__()
        self.hook = None

    async def search(self, query):
        hits = await super().search(query)
        if self.hook:
            self.hook()
        return hits


def research_fixture(setup):
    client = ResearchClient()
    owner = Bootstrap(setup.engine, ports=RuntimePorts(provider_client=client,
                                                       preload=lambda _: ()))
    owner.route_for = lambda _scope: replace(configured_route(), context_window_tokens=200_000)
    owner.provider_for = lambda *_args: PROVIDER
    card = replace(rate(), provider=PROVIDER)
    budget = wallet(setup, micro=50_000_000, input=5_000_000, output=1_000_000, calls=100)
    ctx = replace(setup.ctx, category_id=None)
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        requester_id=setup.human, category_id=None) as session:
        identity = create_run(
            session, ctx, goal="查公开泵压参数", writer_id=setup.agent,
            intent_key=str(uuid4()), token_limit=2_000_000, data_categories=("internal",),
            validation_budget_id=budget,
        ).id
    scope = owner.store.scope(tenant_id=setup.tenant, requester_id=setup.human,
                              writer_id=setup.agent, category_id=None, run_id=identity)
    adapters = replace(owner.adapters(), rate_card_for=lambda *_: card, cost_required=True)
    return SimpleFixture(owner=owner, scope=scope, adapters=adapters, client=client,
                         budget=budget, ctx=ctx, search=HookedSearch(), transport=Transport(),
                         saver=Saver(), job_id=uuid4())


class SimpleFixture:
    def __init__(self, **values):
        self.__dict__.update(values)


def research(f):
    """One fan-out with one task, on a host built as Bootstrap builds it (a new Worker)."""
    graph = ResearchGraph(BoundHost(f.owner.store, f.adapters),
                          checkpointer_factory=lambda: nullcontext(f.saver))
    service = research_service(search=f.search, transport=f.transport)
    return asyncio.run(service.fanout(
        f.scope, [ResearchTask("maker", "public pump pressure")], graph, job_id=f.job_id,
    ))


def test_research_child_stops_when_the_attempt_is_given_up_and_the_next_one_resumes(setup):
    f = research_fixture(setup)
    signal = Event()
    f.search.hook = signal.set  # Temporal gives the attempt up while the search is out.
    with attempt_scope(signal), pytest.raises(AttemptSuperseded):
        research(f)
    run, calls, purse = ledger(setup.admin, f.scope.run_id, f.budget)
    # The in-flight search settled with its real result; nothing was claimed after it.
    assert f.search.queries == ["pump pressure"] and f.transport.requests == []
    assert f.client.calls == 1 and len(of(calls, "model", "research")) == 1
    (search,) = of(calls, "research.search")
    assert search.state == "completed" and search.result["hits"]
    assert not of(calls, "research.read")
    assert run.state not in {"failed", "cancelled"}
    no_open_reservation(run, calls, purse)

    f.search.hook = None  # The next attempt, on a new Worker with the saved checkpoint.
    result = research(f)
    assert result.status == "completed" and result.ledger[0].quote == "Pressure: 20 psi"
    run, calls, purse = ledger(setup.admin, f.scope.run_id, f.budget)
    # The settled search replayed from the ledger: no second search, no repeated model call.
    assert f.search.queries == ["pump pressure"] and len(f.transport.requests) == 1
    assert f.client.calls == 3 and len(of(calls, "model", "research")) == 3
    assert all(row.state == "completed" for row in calls)
    no_open_reservation(run, calls, purse)


def test_research_child_cancelled_mid_search_writes_no_late_result(setup):
    f = research_fixture(setup)

    def cancel():
        with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                            requester_id=setup.human, category_id=None) as session:
            cancel_run(session, f.ctx, f.scope.run_id)

    f.search.hook = cancel
    with pytest.raises(DomainError) as failure:
        research(f)
    assert failure.value.code == "CANCELLED_RUN"
    run, calls, purse = ledger(setup.admin, f.scope.run_id, f.budget)
    assert run.state == "cancelled"
    (search,) = of(calls, "research.search")
    assert cancelled_mid_call(search)  # The late hits were not written.
    assert f.client.calls == 1 and f.transport.requests == []
    assert not of(calls, "research.read")
    no_open_reservation(run, calls, purse)


# --- MCP: the main loop calls mcp.read; the isolated child reads the fixed reply ---


def mcp_fixture(setup, tmp_path, hook):
    f = mcp.fixture(setup, tmp_path)
    original = f.model.turn

    def turn(route, **request):
        result = original(route, **request)
        if f.model.calls[-1][0] and hook[0]:  # A child model request is in flight.
            hook[0]()
        return result

    f.model.turn = turn
    f.main_saver = InMemorySaver()
    return f


def mcp_execute(f):
    return AgentKernel(f.host, f.bootstrap.registry).execute(
        f.scope, goal="合成 MCP 只读查询", preload=("proposal_drafting",),
        execution_key={"synthetic": str(f.scope.run_id)}, checkpointer=f.main_saver,
    )


def children(f):
    return sum(1 for child, _ in f.model.calls if child)


def test_mcp_child_stops_when_the_attempt_is_given_up_and_the_next_one_resumes(setup, tmp_path):
    signal, hook = Event(), [None]
    f = mcp_fixture(setup, tmp_path, hook)
    hook[0] = signal.set
    f.host.superseded = signal  # As the Activity sets it on the main host.
    with attempt_scope(signal), pytest.raises(AttemptSuperseded):
        mcp_execute(f)
    run, calls, _ = ledger(setup.admin, f.scope.run_id)
    assert len(f.network) == 1 and children(f) == 1
    (child_model,) = of(calls, "model", "mcp")
    assert child_model.state == "completed"  # The in-flight request settled as usual.
    assert not of(calls, "mcp.result.read")  # Nothing claimed after the signal.
    (parent,) = of(calls, "mcp.read")
    assert parent.state == "started" and parent.result is None  # Resumable, unwritten.
    assert run.state not in {"failed", "cancelled"}
    no_open_reservation(run, calls)

    hook[0], f.host.superseded = None, None  # The next attempt.
    state = mcp_execute(f)
    value = next(item["value"] for item in state["tool_results"] if item["tool"] == "mcp.read")
    assert value["rows"][0]["quote"] == "synthetic factual value", value
    run, calls, _ = ledger(setup.admin, f.scope.run_id)
    assert len(f.network) == 1 and children(f) == 2  # Neither the MCP call nor a model resent.
    assert all(row.state == "completed" for row in calls)
    no_open_reservation(run, calls)


def test_mcp_child_cancelled_mid_call_writes_no_late_result(setup, tmp_path):
    hook = [None]
    f = mcp_fixture(setup, tmp_path, hook)

    def cancel():
        hook[0] = None
        with human_session(setup) as session:
            cancel_run(session, setup.ctx, f.scope.run_id)

    hook[0] = cancel
    with pytest.raises(DomainError) as failure:
        mcp_execute(f)
    assert failure.value.code == "CANCELLED_RUN"
    run, calls, _ = ledger(setup.admin, f.scope.run_id)
    assert run.state == "cancelled" and len(f.network) == 1 and children(f) == 1
    (child_model,) = of(calls, "model", "mcp")
    assert cancelled_mid_call(child_model)
    assert not of(calls, "mcp.result.read")
    (parent,) = of(calls, "mcp.read")
    assert cancelled_mid_call(parent)
    no_open_reservation(run, calls)


# --- Comparison: assistant.compare in the main loop, its child on the startup host ---


def compare_fixture(setup, hook):
    ids, client, (owner, scope, host, adapter) = starting(
        setup, "共同标题\n\n压力 10 bar\n", "共同标题\n\n压力 12 bar\n",
    )
    # As Bootstrap builds it: the child's host is not the Activity's host.
    adapter.comparison_graph = AssistantComparisonGraph(
        BoundHost(owner.store, host.adapters), adapter)
    original = client.turn

    def turn(route, **kwargs):
        result = original(route, **kwargs)
        names = {row["name"] for row in kwargs["tools"]}
        if "assistant.comparison.read" in names and hook[0]:
            hook[0]()
        return result

    client.turn = turn
    return SimpleFixture(owner=owner, scope=scope, host=host, client=client,
                         saver=InMemorySaver())


def compare_execute(f):
    return AgentKernel(f.host, f.owner.registry).execute(
        f.scope, goal="以前漏气怎么处理？", execution_key={"synthetic": str(f.scope.run_id)},
        checkpointer=f.saver,
    )["output"]


def test_comparison_child_stops_when_the_attempt_is_given_up_and_the_next_one_resumes(setup):
    signal, hook = Event(), [None]
    f = compare_fixture(setup, hook)
    hook[0] = signal.set
    f.host.superseded = signal
    with attempt_scope(signal), pytest.raises(AttemptSuperseded):
        compare_execute(f)
    run, calls, _ = ledger(setup.admin, f.scope.run_id)
    assert f.client.child_calls == 1
    (child_model,) = of(calls, "model", "assistant_compare")
    assert child_model.state == "completed"
    assert not of(calls, "assistant.comparison.read")
    (parent,) = of(calls, "assistant.compare")
    assert parent.state == "started" and parent.result is None
    no_open_reservation(run, calls)

    hook[0], f.host.superseded = None, None
    output = compare_execute(f)
    assert output["status"] == "completed", output
    assert output["result"]["assistant"]["comparison"]["stats"]["changes"] == 1
    run, calls, _ = ledger(setup.admin, f.scope.run_id)
    assert f.client.child_calls == 2 and len(of(calls, "model", "assistant_compare")) == 2
    assert all(row.state == "completed" for row in calls)
    no_open_reservation(run, calls)


def test_comparison_child_cancelled_mid_call_writes_no_late_result(setup):
    hook = [None]
    f = compare_fixture(setup, hook)

    def cancel():
        hook[0] = None
        with human_session(setup) as session:
            cancel_run(session, setup.ctx, f.scope.run_id)

    hook[0] = cancel
    with pytest.raises(DomainError) as failure:
        compare_execute(f)
    assert failure.value.code == "CANCELLED_RUN"
    run, calls, _ = ledger(setup.admin, f.scope.run_id)
    assert run.state == "cancelled" and f.client.child_calls == 1
    (child_model,) = of(calls, "model", "assistant_compare")
    assert cancelled_mid_call(child_model)
    assert not of(calls, "assistant.comparison.read")
    (parent,) = of(calls, "assistant.compare")
    assert cancelled_mid_call(parent)
    no_open_reservation(run, calls)


# --- evidence.extract: children on their own threads, on the startup host ---


def extract_case(work, security_work, hook):
    owner, scope, host, client, kinds, source, _version, _second, args = extract_fixture(
        work, security_work, rows_factory=quote_row)
    adapters = host.adapters
    # As Bootstrap wires it: a startup host for the children, and a resumable call.
    adapter = ExtractReadAdapter(
        ExtractionService(owner.store, owner.commands, owner.catalog),
        ExtractGraph(BoundHost(owner.store, adapters),
                     artifact_read=adapters.read_tools["evidence.artifact.read"]),
    )
    adapters.read_tools.update(adapter.handlers())
    adapters.read_restores.update(adapter.restores())
    adapters.read_resumes.update(adapter.resumes())
    original = client.callback

    def callback(kwargs):
        result = original(kwargs)
        if kinds[-1][0] == "child-read" and hook[0]:  # The child's first request.
            hook[0]()
        return result

    client.callback = callback
    return SimpleFixture(owner=owner, scope=scope, host=host, kinds=kinds, source=source,
                         args=args)


def test_extract_child_stops_when_the_attempt_is_given_up_and_the_next_one_resumes(
    work, security_work,
):
    signal, hook = Event(), [None]
    f = extract_case(work, security_work, hook)
    hook[0] = signal.set
    f.host.superseded = signal
    with attempt_scope(signal), pytest.raises(AttemptSuperseded):
        extract(f.host, f.scope, f.source, f.args)
    run, calls, _ = ledger(work.admin, f.scope.run_id)
    assert [kind for kind, _ in f.kinds] == ["main", "child-read"]
    (child_model,) = of(calls, "model", "extract")
    assert child_model.state == "completed"
    assert not of(calls, "evidence.artifact.read")
    (parent,) = of(calls, "evidence.extract")
    assert parent.state == "started" and parent.result is None
    no_open_reservation(run, calls)

    hook[0], f.host.superseded = None, None
    result = extract(f.host, f.scope, f.source, f.args)
    assert [row["quote"] for row in result["rows"]] == [QUOTE] and result["failures"] == []
    assert [kind for kind, _ in f.kinds] == ["main", "child-read", "child-answer"]
    run, calls, _ = ledger(work.admin, f.scope.run_id)
    assert all(row.state == "completed" for row in calls)
    no_open_reservation(run, calls)


def test_extract_child_cancelled_mid_call_writes_no_late_result(work, security_work):
    hook = [None]
    f = extract_case(work, security_work, hook)

    def cancel():
        hook[0] = None
        with tenant_session(work.engine, work.tenant, actor_id=work.human,
                            requester_id=work.human, category_id=work.category) as session:
            cancel_run(session, work.ctx, f.scope.run_id)

    hook[0] = cancel
    with pytest.raises(DomainError) as failure:
        extract(f.host, f.scope, f.source, f.args)
    assert failure.value.code == "CANCELLED_RUN"
    run, calls, _ = ledger(work.admin, f.scope.run_id)
    assert run.state == "cancelled"
    assert [kind for kind, _ in f.kinds] == ["main", "child-read"]
    (child_model,) = of(calls, "model", "extract")
    assert cancelled_mid_call(child_model)
    assert not of(calls, "evidence.artifact.read")
    (parent,) = of(calls, "evidence.extract")
    assert cancelled_mid_call(parent)
    no_open_reservation(run, calls)
