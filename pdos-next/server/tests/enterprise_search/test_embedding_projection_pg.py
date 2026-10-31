"""Actual PostgreSQL/COMMON/LangGraph drafts. Root runs after assigning the migration.

Synthetic vectors establish mechanics only; they are not a retrieval quality dataset.
"""

import os
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import AgentEvent
from pdos_next.api import create_app
from pdos_next.enterprise_search.embedding_activities import EmbeddingActivities
from pdos_next.enterprise_search.embedding_hybrid import hybrid_search
from pdos_next.enterprise_search.embedding_models import (
    ChunkEmbedding,
    EmbeddingBatch,
    EmbeddingBudget,
    EmbeddingCall,
)
from pdos_next.enterprise_search.schemas import SearchInput
from pdos_next.models import Audit, Outbox
from tests.enterprise_search.embedding_harness import (
    command_for,
    ports_for,
    reference_for,
    save_profile,
)
from tests.enterprise_search.test_retrieval_pg import index, register, session_for

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL") or not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
    reason="Explicit verified PostgreSQL and actual checkpoint store required",
)


def execute_saved(setup, ports, receipt):
    activities = EmbeddingActivities(
        setup.engine, ports, checkpoint_url=os.environ["PDOS_CHECKPOINT_DATABASE_URL"]
    )
    plan = activities.plan(reference_for(setup, receipt))
    assert plan["batches"] and not plan["truncated"]
    for identity in plan["batches"]:
        ref = {"context": plan["context"], "batch_id": identity}
        assert activities.embed(ref)["status"] == "ready"
    return activities, plan


def test_actual_t1_background_rls_exact_ann_profile_version_and_disable(setup):
    shared = register(setup, "Synthetic A", "SYNTHETIC_VECTOR_BODY_A")
    private = register(setup, "Synthetic private", "SYNTHETIC_VECTOR_BODY_PRIVATE", "private")
    for identity in (shared, private):
        index(setup, identity)
    provider, ports = ports_for(setup)
    command = command_for(setup)
    path = f"/v1/categories/{setup.category}/commands"
    with TestClient(create_app(setup.engine, setup.auth, embedding_ports=ports)) as client:
        denied = client.post(path, json=command, headers=setup.headers)
        assert denied.status_code == 409 and not provider.calls
        preview = client.post(path + "/preview", json=command, headers=setup.headers)
        assert preview.status_code == 200, preview.text
        assert preview.json()["review"]["expected_sources"] == 2
        assert not provider.calls  # Neither save preview nor unconfirmed attempt sends anything.
    receipt, _preview = save_profile(setup, ports, command)
    assert not provider.calls
    with TestClient(create_app(setup.engine, setup.auth, embedding_ports=ports)) as client:
        status = client.get(
            f"/v1/categories/{setup.category}/embedding-profile", headers=setup.headers
        )
        assert status.status_code == 200, status.text
        assert status.json()["budget"]["revision"] == 1
        assert status.json()["profiles"][0]["profile_version_id"] == receipt["subject_id"]
        assert not provider.calls and "secret_json" not in status.text
    activities, plan = execute_saved(setup, ports, receipt)
    count = len(provider.calls)
    for identity in plan["batches"]:
        assert activities.embed({"context": plan["context"], "batch_id": identity})["replayed"]
    assert len(provider.calls) == count
    version = UUID(receipt["subject_id"])
    data = SearchInput(query="完全不相干词", source_types=["artifact"])
    with session_for(setup) as session:
        owner = hybrid_search(
            session, setup.ctx, data, profile_version_id=version, vector=(1.0, 0.0)
        )
    assert {row["source_id"] for row in owner["items"]} == {str(shared), str(private)}
    peer_ctx = replace(setup.ctx, actor_id=setup.peer, requester_id=setup.peer)
    with session_for(setup, actor=setup.peer) as session:
        exact = hybrid_search(
            session, peer_ctx, data, profile_version_id=version, vector=(1.0, 0.0)
        )
        ann = hybrid_search(
            session,
            peer_ctx,
            data,
            profile_version_id=version,
            vector=(1.0, 0.0),
            strategy="iterative",
        )
    assert {row["source_id"] for row in exact["items"]} == {str(shared)}
    assert {row["source_id"] for row in ann["items"]} == {str(shared)}
    assert str(private) not in str(exact) and "SYNTHETIC_VECTOR_BODY_PRIVATE" not in str(exact)
    assert len(provider.calls) == count  # Page/offline shadow recall never embeds a query.
    # A different dimension/profile version can coexist but never mix query spaces.
    second = command_for(setup, budget_revision=1, dimensions=3)
    second_receipt, _ = save_profile(setup, ports, second)
    provider.dimensions = 3
    execute_saved(setup, ports, second_receipt)
    with Session(setup.admin) as session:
        assert set(
            session.scalars(
                select(ChunkEmbedding.dimensions).where(ChunkEmbedding.tenant_id == setup.tenant)
            )
        ) == {2, 3}
        budget = session.get(EmbeddingBudget, setup.tenant)
        assert budget.held_micro_usd == 0 and budget.spent_micro_usd > 0
        assert session.scalar(
            select(func.count())
            .select_from(EmbeddingCall)
            .where(EmbeddingCall.tenant_id == setup.tenant)
        ) == len(provider.calls)
        for model in (Audit, Outbox, AgentEvent):
            rows = session.scalars(select(model).where(model.tenant_id == setup.tenant))
            assert "synthetic-embedding-only" not in str([row.__dict__ for row in rows])
    disabled = command_for(
        setup,
        profile_id=UUID(command["payload"]["profile_id"]),
        revision=1,
        budget_revision=2,
        enabled=False,
    )
    save_profile(setup, ports, disabled)
    with Session(setup.admin) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ChunkEmbedding)
                .where(
                    ChunkEmbedding.tenant_id == setup.tenant,
                    ChunkEmbedding.profile_version_id == version,
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(EmbeddingBatch)
                .where(EmbeddingBatch.tenant_id == setup.tenant)
            )
            > 0
        )
    with session_for(setup) as session:
        fallback = hybrid_search(
            session, setup.ctx, data, profile_version_id=version, vector=(1.0, 0.0)
        )
    assert fallback["semantic"]["status"] == "unavailable"
    assert len(provider.calls) == count + 1


def test_actual_started_unknown_is_conservatively_charged_then_native_t1_reconciled(
    setup, monkeypatch
):
    identity = register(setup, "Synthetic crash boundary", "SYNTHETIC_CRASH_INPUT")
    index(setup, identity)
    provider, ports = ports_for(setup)
    command = command_for(setup)
    receipt, _ = save_profile(setup, ports, command)
    activities = EmbeddingActivities(
        setup.engine, ports, checkpoint_url=os.environ["PDOS_CHECKPOINT_DATABASE_URL"]
    )
    plan = activities.plan(reference_for(setup, receipt))
    assert len(plan["batches"]) == 1
    ref = {"context": plan["context"], "batch_id": plan["batches"][0]}
    original = provider.embed

    class SyntheticProcessCrash(BaseException):
        pass

    def reply_then_crash(*args, **kwargs):
        original(*args, **kwargs)
        raise SyntheticProcessCrash("Synthetic process loss before settlement")

    monkeypatch.setattr(provider, "embed", reply_then_crash)
    with pytest.raises(SyntheticProcessCrash):
        activities.embed(ref)
    with Session(setup.admin) as session:
        budget = session.get(EmbeddingBudget, setup.tenant)
        assert budget.held_micro_usd > 0 and budget.spent_micro_usd == 0
    monkeypatch.setattr(provider, "embed", original)
    assert activities.embed(ref)["status"] == "ready"
    assert len(provider.calls) == 2
    with Session(setup.admin) as session:
        calls = list(
            session.scalars(
                select(EmbeddingCall)
                .where(EmbeddingCall.tenant_id == setup.tenant)
                .order_by(EmbeddingCall.attempt)
            )
        )
        assert [call.state for call in calls] == ["unknown", "completed"]
        assert calls[0].input_tokens is None
        assert calls[0].charged_micro_usd == calls[0].reserved_micro_usd > 0
        unknown_id = str(calls[0].id)
        budget = session.get(EmbeddingBudget, setup.tenant)
        assert budget.held_micro_usd == 0
        assert budget.spent_micro_usd == sum(call.charged_micro_usd for call in calls)
    assert activities.embed(ref)["replayed"] and len(provider.calls) == 2
    command["command_id"], command["idempotency_key"] = str(uuid4()), str(uuid4())
    command["operation"] = "embedding.call.reconcile"
    command["payload"] = {
        "call_id": unknown_id,
        "expected_revision": 1,
        "input_tokens": 5,
        "actual_micro_usd": 3,
        "evidence_ref": "synthetic invoice fixture",
    }
    saved, _ = save_profile(setup, ports, command)
    assert saved["result"]["result_reissued"] is False
    with Session(setup.admin) as session:
        unknown = session.get(EmbeddingCall, UUID(unknown_id))
        assert unknown.state == "reconciled" and unknown.revision == 2
        assert unknown.charged_micro_usd == 3
    assert len(provider.calls) == 2
