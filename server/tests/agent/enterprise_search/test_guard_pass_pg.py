"""D268: one guard pass proves each earlier round's sealed reads once, never O(rounds²).

A long session used to re-prove the same ancestor's search reads once per later
round in every guard pass. The pass memo lives in one transaction only, so the
next pass still sees a revocation or withdrawal at once.
"""

from collections import Counter

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from pdos_next.agent.enterprise_search import assistant_ledger as ledger
from pdos_next.agent.kernel import deterministic_proofs
from pdos_next.agent.kernel.conversation import lineage
from pdos_next.agent.kernel.execution import scope_for_run
from pdos_next.agent.kernel.models import AgentRun
from pdos_next.core.models import Artifact
from pdos_next.errors import DomainError
from tests.agent.enterprise_search.test_assistant_pg import SyntheticClient, execute, fixture
from tests.agent.enterprise_search.test_retrieval_pg import index, register

ROUNDS = 4


def session_of(setup, rounds):
    """``rounds`` completed continued rounds, then the next round's frozen scope."""
    previous = session_id = None
    for _number in range(rounds):
        owner, scope, host, _adapter = fixture(
            setup, SyntheticClient(), session_id=session_id, continued_from_id=previous)
        owner.project_context(scope, "继续核对")
        assert execute(owner, scope, host)["status"] == "completed"
        with owner.store.transaction(scope) as (_session, run):
            session_id = run.session_id
        previous = scope.run_id
    owner, scope, host, adapter = fixture(
        setup, SyntheticClient(), session_id=session_id, continued_from_id=previous)
    owner.project_context(scope, "继续核对")
    return owner, scope, adapter


class Proofs:
    """How often each sealed call is proven while the block runs."""

    def __init__(self, monkeypatch):
        self.counts, original = Counter(), deterministic_proofs._completed_read

        def counted(session, run, scope, call_id, *args, **kwargs):
            self.counts[call_id] += 1
            return original(session, run, scope, call_id, *args, **kwargs)

        monkeypatch.setattr(deterministic_proofs, "_completed_read", counted)


class Statements:
    def __init__(self, engine):
        self.engine, self.count = engine, 0

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self.hit)
        return self

    def hit(self, *_args):
        self.count += 1

    def __exit__(self, *_):
        event.remove(self.engine, "before_cursor_execute", self.hit)


@pytest.fixture
def documents(setup):
    identities = []
    for number in range(2):
        identity = register(setup, f"漏气记录 {number}", f"接口漏气。措施：更换密封圈{number}。")
        index(setup, identity)
        identities.append(identity)
    return identities


def test_one_guard_pass_proves_each_sealed_read_once(setup, documents, monkeypatch):
    owner, scope, adapter = session_of(setup, ROUNDS)
    assert len(adapter._carried(scope)[0]) > 0  # Earlier rounds' citations are carried.
    proofs = Proofs(monkeypatch)
    assert adapter.guard(scope) == frozenset({"internal"})
    assert proofs.counts and max(proofs.counts.values()) == 1, proofs.counts
    guarded = set(proofs.counts)
    proofs.counts.clear()
    owner.check_conversation(scope)
    assert max(proofs.counts.values()) == 1, proofs.counts
    # A new pass proves everything again: nothing is carried between passes.
    proofs.counts.clear()
    adapter.guard(scope)
    assert set(proofs.counts) == guarded


def test_guard_statements_grow_by_a_constant_per_round(setup, documents):
    counts = []
    previous = session_id = None
    for _number in range(ROUNDS + 1):
        owner, scope, host, adapter = fixture(
            setup, SyntheticClient(), session_id=session_id, continued_from_id=previous)
        owner.project_context(scope, "继续核对")
        with Statements(setup.engine) as statements:
            adapter.guard(scope)
        counts.append(statements.count)
        assert execute(owner, scope, host)["status"] == "completed"
        with owner.store.transaction(scope) as (_session, run):
            session_id = run.session_id
        previous = scope.run_id
    steps = [later - earlier for earlier, later in zip(counts[1:], counts[2:], strict=False)]
    # Before D268 each step was 4 statements larger than the one before (O(rounds²)).
    assert max(steps) - min(steps) <= 1, counts


def test_withdrawal_between_passes_is_seen_by_the_next_pass(setup, documents):
    owner, scope, adapter = session_of(setup, ROUNDS)
    assert adapter.guard(scope) == frozenset({"internal"})
    owner.check_conversation(scope)
    with Session(setup.admin) as session, session.begin():
        for identity in documents:
            session.get(Artifact, identity).status = "withdrawn"
    with pytest.raises(DomainError):
        adapter.guard(scope)
    with pytest.raises(DomainError):
        owner.check_conversation(scope)


def test_the_memo_is_this_transaction_only_and_hands_out_copies(setup, documents):
    owner, scope, _adapter = session_of(setup, 2)
    with owner.store.transaction(scope) as (session, run):
        ancestor = scope_for_run(session.get(AgentRun, lineage(session, run)[0].id))
        with ledger.one_pass(session):
            first = ledger.search_issued(session, ancestor, archive=True)
            assert first
            first.clear()  # A caller's change never reaches the memo.
            assert ledger.search_issued(session, ancestor, archive=True)
            with ledger.one_pass(session):  # Nested passes share the outer one.
                assert ledger.pass_memo(session, "search")
        assert ledger.pass_memo(session, "search") is None
        ledger.carried(session, scope)
        assert ledger.pass_memo(session, "runs") is None
