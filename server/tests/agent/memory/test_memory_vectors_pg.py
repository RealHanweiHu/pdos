"""Optional episode vectors (P85 第 3 项, AT-74 降级): “本人会话记录” only, synthetic provider.

The synthetic embedding transport never leaves the process. No chat model calls.
"""

from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
from pdos_agent_runtime.graph import registered_graph_context
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent.enterprise_search.embedding_models import EmbeddingBudget
from pdos_next.agent.kernel.models import AgentRun
from pdos_next.agent.kernel.persistence import KernelStore
from pdos_next.agent.memory import vectors
from pdos_next.agent.memory.models import MemoryEmbeddingCall, MemoryEpisodeVector
from pdos_next.agent.memory.recall import MemorySearchInput, search
from pdos_next.agent.memory.tool import memory_search
from pdos_next.core.database import tenant_session
from pdos_next.errors import DomainError
from tests.agent.enterprise_search.embedding_harness import command_for, ports_for, save_profile
from tests.agent.memory.support import episode, finish, scope, start


def profile(setup, categories):
    provider, ports = ports_for(setup)
    command = command_for(setup)
    command["payload"]["metadata"]["data_categories"] = categories
    receipt, _ = save_profile(setup, ports, command)
    return provider, ports, UUID(receipt["subject_id"])


def pending(setup):
    with tenant_session(setup.dispatch, setup.tenant) as session:
        return session.execute(text("SELECT * FROM memory_pending_vector_references(:t,200)"),
                               {"t": setup.tenant}).mappings().all()


def owner_transaction(setup):
    @contextmanager
    def transaction(ctx):
        with tenant_session(setup.engine, ctx.tenant_id, actor_id=ctx.actor_id,
                            requester_id=ctx.requester_id, repeatable_read=True) as session:
            yield session
    return transaction


def embed(setup, provider, ports, rows):
    value = {"tenant_id": str(setup.tenant), "owner_id": str(rows[0]["owner_id"]),
             "profile_version_id": str(rows[0]["profile_version_id"]),
             "episode_ids": [str(row["episode_id"]) for row in rows]}
    ref = vectors.reference(value)
    with registered_graph_context("xiaopai"):
        return vectors.execute(owner_transaction(setup), vectors.owner_context(ref), value,
                               secrets=provider, pricing_for=ports.pricing_for, client=provider)


def finished(setup, goal):
    run_id, _ = start(setup, goal=goal)
    finish(setup, run_id)
    return run_id


def test_nothing_goes_out_unless_owner_session_is_selected(setup):
    finished(setup, "比较三家气泵供应商的报价")
    provider, _ports, _profile = profile(setup, ["internal"])
    assert pending(setup) == []
    current, _ = start(setup, goal="气泵供应商")
    result = memory_search(KernelStore(setup.engine), query_embedding=None)(
        scope(setup, current), {"query": "气泵供应商"})
    assert result["retrieval"]["semantic"]["status"] == "not_enabled"
    assert provider.calls == []


def test_owner_words_are_embedded_with_a_receipt_and_recalled_by_vector(setup):
    earlier = finished(setup, "比较三家气泵供应商的报价和交期")
    private, _ = start(setup, goal="私有提案的报价")
    with Session(setup.admin) as session, session.begin():
        # Synthetic fixture only: mark this Run as private, as a private-proposal Run is.
        session.execute(text("SET LOCAL session_replication_role = replica"))
        session.get(AgentRun, private).private_context = True
    finish(setup, private)
    provider, ports, version = profile(setup, ["internal", "owner_session"])
    rows = pending(setup)
    assert [row["episode_id"] for row in rows] == [episode(setup, earlier).id]
    assert rows[0]["profile_version_id"] == version
    result = embed(setup, provider, ports, rows)
    assert result["embedded"] == 1 and len(provider.calls) == 1
    with Session(setup.admin) as session:
        call = session.scalar(select(MemoryEmbeddingCall).where(
            MemoryEmbeddingCall.tenant_id == setup.tenant))
        vector = session.scalar(select(MemoryEpisodeVector).where(
            MemoryEpisodeVector.tenant_id == setup.tenant))
        budget = session.get(EmbeddingBudget, setup.tenant)
    assert call.state == "completed" and call.owner_id == setup.human
    assert call.data_categories == ["owner_session"]
    assert call.egress["provider"] == "embedding.invalid"
    assert call.egress["data_categories"] == ["owner_session"]
    assert "报价" not in str(call.egress) and call.episode_ids == [str(vector.episode_id)]
    assert vector.profile_version_id == version and budget.spent_micro_usd > 0
    assert pending(setup) == []  # The private Run's episode stays keyword-only.
    # Recall fuses the vector ranking into the keyword ranking (RRF).
    current, _ = start(setup, goal="上次那几家")
    with KernelStore(setup.engine).transaction(scope(setup, current), lock=True) as (s, run):
        found = search(s, run, MemorySearchInput(query="完全不同的说法"), semantic={
            "status": "ready", "vector": (1.0, 0.0), "profile_version_id": version})
    assert [item["run_id"] for item in found["items"]] == [str(earlier)]
    assert found["retrieval"]["channels"] == ["keyword", "vector"]
    assert found["retrieval"]["semantic"]["status"] == "queried"
    # Selected but the query cannot be embedded: says 仅关键词, never a silent empty.
    later, _ = start(setup, goal="气泵供应商")
    degraded = memory_search(KernelStore(setup.engine), query_embedding=None)(
        scope(setup, later), {"query": "气泵供应商"})
    assert degraded["retrieval"]["semantic"]["status"] == "unavailable"
    assert "只做了关键词" in degraded["retrieval"]["semantic"]["message"]
    assert [item["run_id"] for item in degraded["items"]] == [str(earlier)]


def test_vectors_and_receipts_are_owner_only_and_never_written_by_ai(setup):
    earlier = finished(setup, "比较三家气泵供应商的报价和交期")
    provider, ports, _version = profile(setup, ["internal", "owner_session"])
    embed(setup, provider, ports, pending(setup))
    with Session(setup.admin) as session:
        vector = session.scalar(select(MemoryEpisodeVector).where(
            MemoryEpisodeVector.tenant_id == setup.tenant))
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.peer,
                        requester_id=setup.peer) as session:
        assert session.scalar(text("SELECT count(*) FROM memory_episode_vectors")) == 0
    values = {"id": uuid4(), "tenant": setup.tenant, "owner": setup.human,
              "session": vector.session_id, "episode": vector.episode_id,
              "profile": vector.profile_version_id, "call": vector.call_id}
    with pytest.raises(DBAPIError, match="row-level security|permission denied"):
        with tenant_session(setup.engine, setup.tenant, actor_id=setup.agent,
                            requester_id=setup.human) as session:
            session.execute(text(
                "INSERT INTO memory_episode_vectors(id,tenant_id,created_at,owner_id,session_id,"
                "episode_id,profile_version_id,call_id,text_digest,dimensions,vector,norm) VALUES "
                "(:id,:tenant,now(),:owner,:session,:episode,:profile,:call,repeat('a',64),2,"
                "'[0,1]',1)"), values)
    # Someone else's identity cannot embed the owner's episodes.
    with pytest.raises(DomainError, match="记录本人"):
        with registered_graph_context("xiaopai"):
            vectors.execute(owner_transaction(setup),
                            vectors.owner_context({"tenant_id": setup.tenant,
                                                   "owner_id": setup.peer}),
                            {"tenant_id": str(setup.tenant), "owner_id": str(setup.human),
                             "profile_version_id": str(vector.profile_version_id),
                             "episode_ids": [str(episode(setup, earlier).id)]},
                            secrets=provider, pricing_for=ports.pricing_for, client=provider)
    # Outside the registered graph nothing is sent.
    with pytest.raises(Exception, match="已注册执行图"):
        vectors.execute(owner_transaction(setup), vectors.owner_context(
            vectors.reference({"tenant_id": str(setup.tenant), "owner_id": str(setup.human),
                               "profile_version_id": str(vector.profile_version_id),
                               "episode_ids": [str(vector.episode_id)]})), {},
            secrets=provider, pricing_for=ports.pricing_for, client=provider)


# --- D300 (design §14.9 嵌入版本): a new model is built beside the old one, then switched to. ---


def second_profile(setup, ports, *, budget_revision, model="synthetic-embed-2", profile_id=None,
                   revision=0, enabled=True):
    command = command_for(setup, profile_id=profile_id, revision=revision,
                          budget_revision=budget_revision, enabled=enabled)
    command["payload"]["metadata"].update(
        model=model, model_version=model + "@1", data_categories=["internal", "owner_session"])
    receipt, _ = save_profile(setup, ports, command)
    return UUID(receipt["subject_id"]), UUID(command["payload"]["profile_id"])


def serving_now(setup, run_id):
    with KernelStore(setup.engine).transaction(scope(setup, run_id), lock=True) as (s, run):
        return vectors.serving(s, run.requester_id)


def recalled(setup, version, query="完全不同的说法"):
    current, _ = start(setup, goal="上次那几家")
    with KernelStore(setup.engine).transaction(scope(setup, current), lock=True) as (s, run):
        return search(s, run, MemorySearchInput(query=query), semantic={
            "status": "ready", "vector": (1.0, 0.0), "profile_version_id": version})


def test_old_vectors_serve_until_the_new_model_has_caught_up_then_the_search_switches(setup):
    first = finished(setup, "比较三家气泵供应商的报价和交期")
    second = finished(setup, "整理密封圈的来料检验记录")
    provider, ports, old = profile(setup, ["internal", "owner_session"])
    with Session(setup.admin) as session:
        from pdos_next.agent.enterprise_search.embedding_models import EmbeddingProfile

        old_profile = session.get(EmbeddingProfile, old).profile_id
    embed(setup, provider, ports, pending(setup))
    probe, _ = start(setup, goal="探测")
    state = serving_now(setup, probe)
    assert state["profile_version_id"] == old and state["coverage"] == "complete"
    assert state["switching"] is False
    expected = {str(first), str(second)}

    # A new model is saved as a second profile beside the old one (both active).
    new, _new_profile = second_profile(setup, ports, budget_revision=1)
    rows = pending(setup)
    assert {row["profile_version_id"] for row in rows} == {new}
    assert {row["episode_id"] for row in rows} == {episode(setup, first).id,
                                                   episode(setup, second).id}
    state = serving_now(setup, probe)
    assert state["profile_version_id"] == old and state["switching"] is True
    assert state["active_versions"] == [str(new), str(old)]
    # While the new space is empty the old one keeps serving: no fake empty result.
    found = recalled(setup, old)
    assert {item["run_id"] for item in found["items"]} == expected
    assert found["retrieval"]["channels"] == ["keyword", "vector"]

    # New work meanwhile is written to both spaces.
    third = finished(setup, "复核外壳缩水的保压参数")
    rows = pending(setup)
    assert {(row["episode_id"], row["profile_version_id"]) for row in rows} >= {
        (episode(setup, third).id, old), (episode(setup, third).id, new)}

    # Half built: still the old space (one space per query, never fused across spaces).
    partial = [row for row in rows if row["profile_version_id"] == new
               and row["episode_id"] == episode(setup, first).id]
    embed(setup, provider, ports, partial)
    assert serving_now(setup, probe)["profile_version_id"] == old

    # Fully built for everything the owner had when the new version was saved: switch.
    embed(setup, provider, ports, [row for row in pending(setup)
                                   if row["profile_version_id"] == new])
    state = serving_now(setup, probe)
    assert state["profile_version_id"] == new and state["coverage"] == "complete"
    found = recalled(setup, new)
    assert {item["run_id"] for item in found["items"]} == expected | {str(third)}

    # The old profile is disabled: it is neither dispatched nor queried any more.
    second_profile(setup, ports, budget_revision=2, model="synthetic-embed", enabled=False,
                   profile_id=old_profile, revision=1)
    fourth = finished(setup, "复核气泵噪音")
    assert {row["profile_version_id"] for row in pending(setup)} == {new}
    assert {row["episode_id"] for row in pending(setup)} == {episode(setup, fourth).id}
    state = serving_now(setup, probe)
    assert state["active_versions"] == [str(new)] and state["switching"] is False
    assert state["profile_version_id"] == new
    # The fourth episode has no vector yet; keyword retrieval still finds it.
    lagging = recalled(setup, new, query="气泵噪音")
    assert str(fourth) in {item["run_id"] for item in lagging["items"]}


def test_a_run_keeps_the_space_it_started_with_and_says_when_that_space_went_away(setup):
    from types import SimpleNamespace

    from pdos_next.agent.enterprise_search.embedding_query import QueryEmbedding, QueryPorts
    from pdos_next.agent.memory.tool import MEMORY_SNAPSHOT, semantic_query

    finished(setup, "比较三家气泵供应商的报价和交期")
    provider, ports, old = profile(setup, ["internal", "owner_session"])
    with Session(setup.admin) as session:
        from pdos_next.agent.enterprise_search.embedding_models import EmbeddingProfile

        old_profile = session.get(EmbeddingProfile, old).profile_id
    embed(setup, provider, ports, pending(setup))
    embedder = QueryEmbedding(KernelStore(setup.engine),
                              QueryPorts(ports, vectors.select_profile, run_selector=True),
                              source_guard=lambda _scope: frozenset({"internal"}),
                              snapshot=MEMORY_SNAPSHOT)
    calls = []
    embedder.prepare = lambda *args: calls.append(args) or SimpleNamespace(
        status="ready", vector=(1.0, 0.0))
    current, _ = start(setup, goal="气泵供应商")
    bound = scope(setup, current)
    # Without an actual started memory.search call nothing is embedded.
    assert semantic_query(KernelStore(setup.engine), embedder, bound,
                          {"query": "气泵"}) == {"status": "query_unavailable"}
    assert calls == []
    with Session(setup.admin) as session:
        frozen = session.get(AgentRun, current).versions[MEMORY_SNAPSHOT]
    assert frozen["profile_version_id"] == str(old)
    # The old space is disabled mid-run: this Run says so instead of switching spaces.
    second_profile(setup, ports, budget_revision=1, model="synthetic-embed", enabled=False,
                   profile_id=old_profile, revision=1)
    assert semantic_query(KernelStore(setup.engine), embedder, bound, {"query": "气泵"}) is None
    new, _ = second_profile(setup, ports, budget_revision=2)
    assert semantic_query(KernelStore(setup.engine), embedder, bound, {"query": "气泵"}) == {
        "status": "query_profile_mismatch"}
    degraded = memory_search(KernelStore(setup.engine), query_embedding=embedder)(
        bound, {"query": "气泵供应商"})
    assert degraded["retrieval"]["semantic"]["status"] == "unavailable"
    assert degraded["retrieval"]["semantic"]["reason"] == "query_profile_mismatch"
    assert len(degraded["items"]) == 1  # Keyword retrieval still answers.
