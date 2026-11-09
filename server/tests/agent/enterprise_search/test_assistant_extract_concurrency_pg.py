"""D257: the isolated children of one assistant.extract run side by side, bounded.

Offline provider only. The run keeps the actual registry, gateway, ledger, price card,
validation budget and read bindings, so each child's reservations and receipts are the
real ones. Barriers inside the provider prove that the children really overlap.
"""

import json
import os
import re
import threading
from contextlib import ExitStack, nullcontext
from dataclasses import replace
from threading import Barrier, Event, Lock
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from pdos_next.agent.enterprise_search.assistant_graph import AssistantExtractGraph
from pdos_next.agent.kernel.bootstrap import Bootstrap, RuntimePorts
from pdos_next.agent.kernel.graph import AgentKernel
from pdos_next.agent.kernel.host import BoundHost
from pdos_next.agent.kernel.models import AgentRun, AgentToolCall, ValidationBudget
from pdos_next.agent.kernel.persistence import cancel_run, create_run
from pdos_next.agent.kernel.run_lease import AttemptSuperseded, attempt_scope
from pdos_next.agent.kernel.types import ModelTurn, ToolCall
from pdos_next.core.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.providers.types import ProviderError, ProviderUsage
from tests.agent.enterprise_search.test_retrieval_pg import index, register
from tests.agent.kernel.test_cost_budget import rate, wallet
from tests.agent.kernel.test_gateway import configured_route

PROVIDER = "synthetic-assistant-no-egress"


def final(result):
    return ModelTurn(
        structured={"status": "completed", "summary": "参考固定记录。", "result": result,
                    "questions": [], "unfinished": []},
        usage=ProviderUsage(10, 2),
    )


class Client:
    """Main: search, extract every hit, answer. Child: read the passage once, quote it.

    ``hook(citation_id, step)`` runs inside a child's provider call, where the
    real HTTP request would be in flight (no transaction is open there).
    """

    def __init__(self, hook=None):
        self.lock, self.hook = Lock(), hook
        self.main = self.child = self.active = self.peak = 0
        self.extracted = None

    def close(self):
        pass

    def turn(self, _route, **kwargs):
        messages = kwargs["messages"]
        names = {row["name"] for row in kwargs["tools"]}
        values = [json.loads(row["content"]) for row in messages if row["role"] == "tool"]
        if names == {"assistant.passage.read", "result.read"}:
            cid = json.loads(messages[0]["content"])["context"]["citation_id"]
            with self.lock:
                self.child += 1
                self.active += 1
                self.peak = max(self.peak, self.active)
            try:
                if self.hook:
                    self.hook(cid, len(values))
            finally:
                with self.lock:
                    self.active -= 1
            if not values:
                return ModelTurn(calls=(ToolCall(
                    id="child-read", name="assistant.passage.read",
                    arguments={"citation_id": cid, "cursor": 0, "page_chars": 2000},
                ),), usage=ProviderUsage(10, 2))
            quote = re.search(r"更换密封圈\d", values[-1]["text"]).group(0)
            return final({"rows": [
                {"citation_id": cid, "statement": f"措施为{quote}。", "quote": quote},
            ]})
        with self.lock:
            self.main += 1
        if not values:
            return ModelTurn(calls=(ToolCall(
                id="main-search", name="assistant.search", arguments={"query": "漏气"},
            ),), usage=ProviderUsage(10, 2))
        if "items" in values[-1]:
            self.extracted = [item["citation_id"] for item in values[-1]["items"]]
            return ModelTurn(calls=(ToolCall(
                id="main-extract", name="assistant.extract",
                arguments={"citation_ids": self.extracted},
            ),), usage=ProviderUsage(10, 2))
        ids = [row["citation_id"] for row in values[-1].get("rows", [])]
        return final({"assistant": {"citation_ids": list(dict.fromkeys(ids)),
                                    "sources": [], "matched_count": len(ids)}})


class Saver(InMemorySaver):
    """Checkpoints kept across attempts, as PostgresSaver keeps them in production.

    Children write from their own threads, so every access takes one lock.
    """

    def __init__(self):
        super().__init__()
        self.lock = threading.RLock()

    def get_tuple(self, config):
        with self.lock:
            return super().get_tuple(config)

    def list(self, *args, **kwargs):
        with self.lock:
            return iter(list(super().list(*args, **kwargs)))

    def put(self, *args, **kwargs):
        with self.lock:
            return super().put(*args, **kwargs)

    def put_writes(self, *args, **kwargs):
        with self.lock:
            return super().put_writes(*args, **kwargs)


@pytest.fixture
def postgres_checkpoints(setup):
    """Production's checkpointer: one PostgresSaver connection per child.

    Kept in a throwaway schema of this isolated pdos_test, dropped afterwards.
    """
    schema = "d257_checkpoints_" + uuid4().hex[:8]
    with setup.admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    url = (os.environ["TEST_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
           + f"?options=-csearch_path%3D{schema}")
    with PostgresSaver.from_conn_string(url) as saver:
        saver.setup()
    yield lambda: PostgresSaver.from_conn_string(url)
    with setup.admin.begin() as connection:
        connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))


def documents(setup, count):
    quotes = {}
    for number in range(1, count + 1):
        identity = register(setup, f"D16 气密记录 {number}",
                            f"接口漏气。措施：更换密封圈{number}。\n批次 {number} 已复测。\n")
        index(setup, identity)
        quotes[str(identity)] = f"更换密封圈{number}"
    return quotes


def fixture(setup, client, *, concurrency, saver=None, checkpoints=None):
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
            session, ctx, goal="以前漏气怎么处理？", writer_id=setup.agent,
            intent_key=str(uuid4()), token_limit=2_000_000, data_categories=("internal",),
            validation_budget_id=budget,
        ).id
    scope = owner.store.scope(tenant_id=setup.tenant, requester_id=setup.human,
                              writer_id=setup.agent, category_id=None, run_id=identity)
    # Real fee leases: every model call, main or child, reserves against the budget.
    adapters = replace(owner.adapters(), rate_card_for=lambda *_: card, cost_required=True)
    host = BoundHost(owner.store, adapters)
    adapter = owner._assistant_adapter
    # As in Bootstrap, the children get their own host, which the Activity never
    # hands its stop signal; they must see it through the attempt scope.
    adapter.graph = AssistantExtractGraph(
        BoundHost(owner.store, adapters), adapter, concurrency=concurrency,
        checkpointer_factory=checkpoints or (
            (lambda: nullcontext(saver)) if saver is not None else None),
    )
    return owner, scope, host, adapter, budget, ctx


def execute(owner, scope, host, saver=None):
    return AgentKernel(host, owner.registry).execute(
        scope, goal="以前漏气怎么处理？", execution_key={"synthetic": str(scope.run_id)},
        checkpointer=saver,
    )


def ledger(setup, scope, budget):
    with Session(setup.admin) as session:
        run = session.get(AgentRun, scope.run_id)
        calls = session.scalars(select(AgentToolCall).where(
            AgentToolCall.run_id == scope.run_id).order_by(AgentToolCall.created_at)).all()
        wallet_row = session.get(ValidationBudget, budget)
        session.expunge_all()
    return run, calls, wallet_row


def extraction(calls):
    return next(row for row in calls if row.tool == "assistant.extract")


def no_child_threads():
    return not any(t.name.startswith("assistant-extract") for t in threading.enumerate())


def test_children_overlap_merge_in_citation_order_and_keep_their_own_ledger_and_fees(setup):
    quotes = documents(setup, 3)
    gate = Barrier(3, timeout=20)

    def together(_cid, step):
        if step == 0:
            gate.wait()  # Fails unless all three first child calls are in flight at once.

    results = {}
    for limit, client in ((3, Client(together)), (1, Client())):
        owner, scope, host, _adapter, budget, _ctx = fixture(setup, client, concurrency=limit)
        output = execute(owner, scope, host)["output"]
        assert output["status"] == "completed", output
        run, calls, purse = ledger(setup, scope, budget)
        saved = extraction(calls).result
        assert [row["citation_id"] for row in saved["rows"]] == client.extracted
        search = next(row for row in calls if row.tool == "assistant.search")
        source_of = {item["citation_id"]: item["source_id"] for item in search.result["items"]}
        assert [row["quote"] for row in saved["rows"]] == [
            quotes[source_of[cid]] for cid in client.extracted]
        assert saved["failures"] == [] and saved["partial"] is False
        models = [row for row in calls if row.tool == "model"]
        children = [row for row in models
                    if row.execution_binding["isolation"] == "assistant_extract"]
        assert client.main == 3 and client.child == 6 and len(models) == 9
        assert len(children) == 6 and all(row.state == "completed" for row in calls)
        # Each child call leased its own tokens and fee, then settled at actual use.
        assert all(row.input_token_reservation > 0 and row.output_token_reservation > 0
                   and row.cost_state == "actual" and row.cost_reserved_micro_usd == 0
                   and row.cost_charged_micro_usd > 0 and row.reserved_tokens == 0
                   and row.charged_tokens > 0 for row in children)
        assert run.held_tokens == 0
        assert run.used_tokens == sum(row.charged_tokens for row in calls)
        assert purse.calls == 9 and purse.held_micro_usd == 0
        assert purse.held_input_tokens == 0 and purse.held_output_tokens == 0
        assert purse.spent_micro_usd == sum(row.cost_charged_micro_usd for row in models)
        reads = [row for row in calls if row.tool == "assistant.passage.read"]
        assert len({row.result["citation_id"] for row in reads}) == 3
        results[limit] = (client.peak, [row["quote"] for row in saved["rows"]], saved)
        # The saved result restores without any model call (idempotent replay).
        args = {"citation_ids": client.extracted}
        assert _adapter.restore_extract(scope, args, saved) == saved
        assert client.main + client.child == 9
    assert results[3][0] == 3 and results[1][0] == 1
    assert results[3][1] == results[1][1]  # Same hits, same merged order.
    assert no_child_threads()


@pytest.mark.parametrize("store", ["memory", "postgres"])
def test_a_superseded_attempt_stops_children_before_their_next_call_and_the_next_resumes(
    setup, request, store,
):
    stack = ExitStack()
    if store == "postgres":
        checkpoints = request.getfixturevalue("postgres_checkpoints")
        saver = stack.enter_context(checkpoints())
    else:
        checkpoints, saver = None, Saver()
    with stack:
        superseded_then_resumed(setup, saver, checkpoints)


def superseded_then_resumed(setup, saver, checkpoints):
    documents(setup, 3)
    superseded, gate = Event(), Barrier(2, timeout=20)

    def give_up(_cid, step):
        if step == 0 and not superseded.is_set():
            gate.wait()  # Two children are in their first model call ...
            superseded.set()  # ... when Temporal gives the attempt up.

    client = Client(give_up)
    owner, scope, host, _adapter, budget, _ctx = fixture(
        setup, client, concurrency=2, saver=saver, checkpoints=checkpoints)
    host.superseded = superseded  # As the Activity sets it on the main host.
    with attempt_scope(superseded), pytest.raises(AttemptSuperseded):
        execute(owner, scope, host, saver)
    assert no_child_threads()
    run, calls, purse = ledger(setup, scope, budget)
    # Both in-flight calls settled; nothing new was claimed after the signal, and the
    # third (queued) child never started.
    children = [row for row in calls if row.execution_binding.get("isolation")
                == "assistant_extract"]
    assert client.child == 2 and len(children) == 2
    assert all(row.tool == "model" and row.state == "completed" for row in children)
    assert extraction(calls).state == "started"  # Resumable by the next attempt.
    assert run.held_tokens == 0 and purse.held_micro_usd == 0
    assert run.state not in {"failed", "cancelled"}

    host.superseded = None  # The next attempt, from the saved checkpoints.
    client.hook = None
    output = execute(owner, scope, host, saver)["output"]
    assert output["status"] == "completed", output
    run, calls, purse = ledger(setup, scope, budget)
    # Completed calls replayed from the ledger; none was sent twice.
    assert client.main == 3 and client.child == 6
    models = [row for row in calls if row.tool == "model"]
    assert len(models) == 9 and all(row.state == "completed" for row in calls)
    saved = extraction(calls).result
    assert [row["citation_id"] for row in saved["rows"]] == client.extracted
    assert run.held_tokens == 0 and purse.held_micro_usd == 0 and purse.calls == 9


def test_cancelling_the_run_stops_every_child_and_leaves_no_open_reservation(setup):
    documents(setup, 3)
    gate, cancelled = Barrier(3, timeout=20), Event()
    state = {}

    def cancel(_cid, step):
        if step == 0:
            if gate.wait() == 0:  # One of the three in-flight children cancels the run.
                with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                                    requester_id=setup.human, category_id=None) as session:
                    cancel_run(session, state["ctx"], state["run_id"])
                cancelled.set()
            cancelled.wait(10)

    client = Client(cancel)
    owner, scope, host, _adapter, budget, ctx = fixture(setup, client, concurrency=3)
    state.update(ctx=ctx, run_id=scope.run_id)
    with pytest.raises(DomainError) as failure:
        execute(owner, scope, host)
    assert failure.value.code == "CANCELLED_RUN"
    assert no_child_threads()
    run, calls, purse = ledger(setup, scope, budget)
    assert run.state == "cancelled" and client.child == 3  # No call after the cancel.
    assert not [row for row in calls if row.state == "started" and row.tool == "model"]
    assert run.held_tokens == 0 and purse.held_input_tokens == 0


def test_one_child_failure_is_that_citation_failure_and_the_others_complete(setup):
    quotes = documents(setup, 3)
    gate, failing = Barrier(3, timeout=20), {}

    def reject_one(cid, step):
        if step == 0:
            gate.wait()
            if cid == failing.setdefault("cid", cid):
                raise ProviderError("PROVIDER_REJECTED")

    client = Client(reject_one)
    owner, scope, host, _adapter, budget, _ctx = fixture(setup, client, concurrency=3)
    output = execute(owner, scope, host)["output"]
    assert output["status"] in {"completed", "partial"}, output
    run, calls, purse = ledger(setup, scope, budget)
    saved = extraction(calls).result
    assert saved["failures"] == [{"citation_id": failing["cid"], "code": "SOURCE_UNAVAILABLE"}]
    others = [cid for cid in client.extracted if cid != failing["cid"]]
    assert [row["citation_id"] for row in saved["rows"]] == others and saved["partial"] is True
    assert {row["quote"] for row in saved["rows"]} <= set(quotes.values())
    failed = [row for row in calls if row.tool == "model" and row.state != "completed"]
    assert len(failed) == 1 and failed[0].error_code == "SOURCE_UNAVAILABLE"
    assert failed[0].execution_binding["isolation"] == "assistant_extract"
    assert run.held_tokens == 0 and purse.held_micro_usd == 0
    assert purse.held_input_tokens == 0 and purse.held_output_tokens == 0
    assert no_child_threads()
