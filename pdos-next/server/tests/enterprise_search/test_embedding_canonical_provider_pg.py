"""Native P26 alias boundaries; root alone runs on the verified isolated PG stores.

Sources, profile confirmation, Outbox batches and agreements use their original
owners. The query uses actual_query's complete persisted model READ binding;
only its synthetic pre-persistence ledger seed and trusted provider port vary.
"""

import json
import os
from dataclasses import replace
from urllib.parse import urlsplit
from uuid import UUID

import pytest
from pdos_agent_runtime.graph import registered_graph_context
from pdos_next.agent_kernel.management import register_agreement
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall, ValidationBudget
from pdos_next.agent_kernel.read_execution import ReadBinding
from pdos_next.enterprise_search.assistant_adapter import AssistantReadAdapter
from pdos_next.enterprise_search.assistant_schemas import AssistantSearchInput
from pdos_next.enterprise_search.embedding_activities import EmbeddingActivities
from pdos_next.enterprise_search.embedding_hybrid import RANKING
from pdos_next.enterprise_search.embedding_models import (
    EmbeddingBatch,
    EmbeddingBudget,
    EmbeddingCall,
    EmbeddingProfile,
)
from pdos_next.enterprise_search.embedding_query_binding import TOOL
from pdos_next.enterprise_search.query import search
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation, Receipt
from pdos_next.service import Context, digest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.agent_kernel import test_domain_adapter_transactions as native
from tests.agent_kernel.test_transactions import agreement, human_session
from tests.enterprise_search import test_embedding_query_pg as query_pg
from tests.enterprise_search.embedding_harness import (
    command_for,
    ports_for,
    reference_for,
    save_profile,
)
from tests.enterprise_search.test_retrieval_pg import index, register, session_for

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL") or not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
    reason="Explicit verified isolated PostgreSQL and checkpoint store required",
)
CANONICAL = "registered-embedding-provider"


def canonical_ports(setup):
    provider, backend = ports_for(setup)
    provider.provider_for = lambda *_: CANONICAL
    price = backend.pricing_for
    return provider, replace(
        backend, pricing_for=lambda tenant, metadata: replace(
            price(tenant, metadata), provider=CANONICAL
        )
    )


def register_policy(setup, categories, *, revision=0):
    data = agreement(setup).model_copy(update={
        "provider": CANONICAL, "data_categories": list(categories),
        "expected_revision": revision,
    })
    with human_session(setup) as session:
        result = register_agreement(session, setup.ctx, data)
    assert result["operation"] == "provider.agreement.register"
    assert result["result"]["provider"] == CANONICAL
    assert result["subject_revision"] == revision + 1
    return result


def activities_for(setup, backend):
    return EmbeddingActivities(
        setup.engine, backend, checkpoint_url=os.environ["PDOS_CHECKPOINT_DATABASE_URL"]
    )


def index_budget_snapshot(session, setup):
    budget = session.get(EmbeddingBudget, setup.tenant)
    return budget.limit_micro_usd, budget.held_micro_usd, budget.spent_micro_usd


def test_profile_confirms_canonical_identity_and_plan_excludes_internal_under_its_agreement(setup):
    source = register(setup, "Canonical plan source", "SYNTHETIC_CANONICAL_INTERNAL")
    index(setup, source)
    provider, backend = canonical_ports(setup)
    policy = register_policy(setup, ["public"])
    command = command_for(setup)
    assert urlsplit(command["payload"]["metadata"]["base_url"]).hostname != CANONICAL
    receipt, preview = save_profile(setup, backend, command)
    assert preview["review"]["provider"] == CANONICAL
    assert preview["command"]["payload"]["confirmation_token"]
    assert provider.calls == []
    version_id = UUID(receipt["subject_id"])
    with Session(setup.admin) as session:
        stored = session.get(EmbeddingProfile, version_id)
        assert stored.binding_digest == preview["review"]["binding_digest"]
        confirmed = session.scalar(select(Confirmation).where(
            Confirmation.tenant_id == setup.tenant,
            Confirmation.actor_id == setup.human,
            Confirmation.operation == "embedding.profile.save",
            Confirmation.token_hash == digest(
                preview["command"]["payload"]["confirmation_token"]
            ),
        ))
        assert confirmed is not None
        assert confirmed.consumed is True
        assert confirmed.snapshot["provider"] == CANONICAL
        assert session.get(Receipt, UUID(policy["id"])).result["provider"] == CANONICAL
    plan = activities_for(setup, backend).plan(reference_for(setup, receipt))
    assert plan["batches"] == [] and plan["uncovered_chunks"] >= 1
    assert not provider.calls
    with Session(setup.admin) as session:
        assert session.scalar(select(func.count()).select_from(EmbeddingBatch).where(
            EmbeddingBatch.tenant_id == setup.tenant,
            EmbeddingBatch.profile_version_id == version_id,
        )) == 0
        assert session.scalar(select(func.count()).select_from(EmbeddingCall).where(
            EmbeddingCall.tenant_id == setup.tenant,
        )) == 0
        assert index_budget_snapshot(session, setup)[1:] == (0, 0)


def test_real_queued_batch_is_denied_after_canonical_agreement_tightens_without_spend(setup):
    source = register(setup, "Canonical queued source", "SYNTHETIC_CANONICAL_QUEUED")
    index(setup, source)
    provider, backend = canonical_ports(setup)
    register_policy(setup, ["public", "internal"])
    receipt, _preview = save_profile(setup, backend, command_for(setup))
    activities = activities_for(setup, backend)
    plan = activities.plan(reference_for(setup, receipt))
    assert len(plan["batches"]) == 1 and provider.calls == []
    batch_id = UUID(plan["batches"][0])
    with Session(setup.admin) as session:
        batch = session.get(EmbeddingBatch, batch_id)
        before = batch.state, batch.attempts, index_budget_snapshot(session, setup)
        assert before[0] == "queued" and before[2][1:] == (0, 0)
    tightened = register_policy(setup, ["public"], revision=1)
    assert tightened["subject_revision"] == 2
    provider.resolve = lambda *_: pytest.fail("Denied batch must not decrypt the independent key")
    reference = {"context": plan["context"], "batch_id": str(batch_id)}
    for _attempt in range(2):
        with pytest.raises(DomainError) as denied:
            activities.embed(reference)
        assert denied.value.code == "FORBIDDEN_SCOPE"
        assert denied.value.detail["reason_key"] == "provider_agreement_category"
    assert provider.calls == []
    with Session(setup.admin) as session:
        batch = session.get(EmbeddingBatch, batch_id)
        assert (batch.state, batch.attempts, index_budget_snapshot(session, setup)) == before
        assert session.scalar(select(func.count()).select_from(EmbeddingCall).where(
            EmbeddingCall.tenant_id == setup.tenant, EmbeddingCall.batch_id == batch_id,
        )) == 0
        # Admission failed before a reservation existed; neither charge nor hold is invented.
        assert index_budget_snapshot(session, setup)[1:] == (0, 0)


def test_native_main_read_uses_canonical_agreement_and_honest_keyword_fallback_without_fee(
    setup, monkeypatch,
):
    seed = native.ledger

    def internal_seed():
        value = seed()
        # This is the established synthetic fixture's creation seam, before any
        # AgentRun/model row is saved. Never rewrite persisted READ history.
        value.scope = replace(value.scope, data_categories=frozenset({"internal"}))
        value.run.data_categories = ["internal"]
        return value

    monkeypatch.setattr(native, "ledger", internal_seed)
    monkeypatch.setattr(query_pg, "ports_for", canonical_ports)
    f, runtime, provider, budget_id, parent_id = query_pg.actual_query(setup, monkeypatch)
    assert runtime.ports.backend.secrets.provider_for(setup.tenant, None) == CANONICAL
    assert "internal" in runtime.source_guard(f.scope)
    policy = register_policy(setup, ["public"])
    index(setup, UUID(f.arguments["artifact_id"]))
    with Session(setup.admin) as session:
        run = session.get(AgentRun, f.scope.run_id)
        assert run.data_categories == ["internal"]
        parent = session.get(AgentToolCall, parent_id)
        proof = ReadBinding.model_validate_json(json.dumps(parent.execution_binding))
        assert proof.model_call_id == f.read_source.model_call_id and proof.response_index == 0
        assert proof.graph == "xiaopai" and proof.tool == "assistant.search"
        assert proof.data_categories == ("internal",)
        assert proof.requester_id == setup.human and proof.writer_id == setup.agent
        budget = session.get(ValidationBudget, budget_id)
        before = budget.calls, budget.spent_micro_usd, budget.held_micro_usd
        assert before == (0, 0, 0)
        assert session.get(Receipt, UUID(policy["id"])).result["provider"] == CANONICAL
    provider.resolve = lambda *_: pytest.fail("Denied query must not decrypt the independent key")
    adapter = AssistantReadAdapter(f.store, f.adapter, query_embedding=runtime)
    data = AssistantSearchInput.model_validate(f.read_arguments).model_copy(update={
        "product_id": f.scope.product_id,
    })
    ctx = Context(setup.tenant, setup.human, setup.human, category_id=setup.category)
    with session_for(setup) as session:
        keyword = search(session, ctx, data)
    expected_sources = {(r["source_type"], r["source_id"], r["source_revision"])
                        for r in keyword["items"]}
    for _attempt in range(2):
        with registered_graph_context("xiaopai"):
            result = adapter.search(f.scope, f.read_arguments, intent_key=f.read_key)
        assert result["semantic"] == {
            "status": "unavailable", "reason": "query_egress_not_permitted",
        }
        assert {(r["source_type"], r["source_id"], r["source_revision"])
                for r in result["items"]} == expected_sources
        assert result.get("ranking_version") != RANKING
        assert result.get("ranking_version") == keyword.get("ranking_version")
    assert provider.calls == []
    with Session(setup.admin) as session:
        assert session.scalar(select(func.count()).select_from(AgentToolCall).where(
            AgentToolCall.run_id == f.scope.run_id, AgentToolCall.tool == TOOL,
        )) == 0
        budget = session.get(ValidationBudget, budget_id)
        assert (budget.calls, budget.spent_micro_usd, budget.held_micro_usd) == before
