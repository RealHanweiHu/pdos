"""Real G0 project scope and current upload/scan proofs, using only offline providers."""
# ruff: noqa: F811 -- the actual scan fixture is explicitly registered

import statistics
import time
from dataclasses import replace
from uuid import UUID

import pytest
from sqlalchemy import event

from pdos_next.agent_kernel.search_preferences import SearchPreferences, configure_start
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.errors import DomainError
from pdos_next.original_security import configure
from tests.enterprise_search.test_assistant_pg import SyntheticClient, execute, fixture
from tests.enterprise_search.test_retrieval_pg import index, register, session_for
from tests.g0_fixture import create_g0_project
from tests.test_original_security import parsed, uploaded
from tests.test_original_security import security_work as security_work


class ScopeClient(SyntheticClient):
    def __init__(self, query="漏气"):
        super().__init__()
        self.query = query

    def turn(self, route, **kwargs):
        turn = super().turn(route, **kwargs)
        if turn.calls and turn.calls[0].name == "assistant.search":
            return ModelTurn(calls=(ToolCall(id=turn.calls[0].id, name="assistant.search",
                                            arguments={"query": self.query}),), usage=turn.usage)
        return turn


def test_category_fallback_keeps_internal_private_but_customer_private_needs_human_choice(
    security_work, record_property,
):
    work, setup = security_work, security_work.setup
    project = UUID(create_g0_project(setup, visibility="category").project_id)
    internal = [register(setup, "漏气公开经验", "更换密封圈。RAW_ONLY_CHILD_MARKER"),
                register(setup, "漏气本人内部资料", "更换密封圈。RAW_ONLY_CHILD_MARKER",
                         visibility="private")]
    customer = parsed(work, uploaded(work, content=(
        "PRIVATESCOPE-9101 漏气处理：更换密封圈。RAW_ONLY_CHILD_MARKER\n"
    ).encode()))
    for identity in [*internal, customer]:
        index(setup, identity)
    scans = work.scanner.calls
    client = ScopeClient()
    owner, scope, host, _adapter = fixture(setup, client, project_id=project)
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    answer = output["result"]["assistant"]
    assert answer["matched_count"] == 2
    assert answer["sources"][0]["group"] == "same_category"
    assert [group["returned"] for group in answer["search_groups"]] == [0, 2]
    assert str(customer) not in str(client.messages)
    from pdos_next.enterprise_search.assistant_scope import retrieve
    from pdos_next.enterprise_search.assistant_sources import human_snapshot
    from pdos_next.enterprise_search.schemas import SearchInput

    durations, queries, current_count = [], [], []
    def statement(*_args):
        current_count.append(True)
    event.listen(setup.engine, "before_cursor_execute", statement)
    try:
        for _ in range(12):
            with human_snapshot(setup.engine, scope) as session:
                current_count.clear()
                begin = time.perf_counter()
                found = retrieve(session, setup.ctx, scope, SearchInput(
                    query="漏气", source_types=["artifact"], product_id=setup.product,
                    project_id=project,
                ))
                durations.append(time.perf_counter()-begin)
                queries.append(len(current_count))
                assert found["returned"] == 2 and found["scope_policy"]["fallback_performed"]
    finally:
        event.remove(setup.engine, "before_cursor_execute", statement)
    p95 = statistics.quantiles(durations, n=20)[18]
    record_property("scope_warm_p95_seconds", p95)
    record_property("scope_queries_per_request", str(sorted(set(queries))))
    record_property("scope_samples", len(durations))
    record_property("scope_returned_sources", 2)
    assert len(set(queries)) == 1 and p95 < 1.0
    denied_client = ScopeClient("PRIVATESCOPE-9101")
    before, hidden_scope, hidden_host, _ = fixture(setup, denied_client, project_id=project)
    hidden = execute(before, hidden_scope, hidden_host)
    assert hidden["result"]["assistant"]["lookup"] == "no_match"
    assert str(customer) not in str(denied_client.messages)
    assert denied_client.child_calls == 0
    chosen = ScopeClient("PRIVATESCOPE-9101")
    owner, scope, host, adapter = fixture(setup, chosen, project_id=project)
    with session_for(setup) as session:
        from pdos_next.agent_kernel.models import AgentRun

        run = session.get(AgentRun, scope.run_id)
        configure_start(session, setup.ctx, run,
                        SearchPreferences(include_customer_private=True))
    selected = execute(owner, scope, host)
    assert selected["status"] == "completed", selected
    assert selected["result"]["assistant"]["sources"][0]["source_id"] == str(customer)
    assert adapter.guard(scope) == frozenset({"internal", "customer_original"})
    assert work.scanner.calls == scans
    changed = replace(work.runtime.configuration, scanner=replace(
        work.runtime.configuration.scanner, rules_version="scope-changed@2"))
    configure(setup.engine, replace(work.runtime, configuration=changed))
    with pytest.raises(DomainError):
        adapter.guard(scope)
    assert work.scanner.calls == scans
