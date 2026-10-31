"""Actual native profile and source boundaries with a local synthetic provider."""

import os
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.api import create_app
from pdos_next.enterprise_search.embedding_activities import EmbeddingActivities
from pdos_next.enterprise_search.embedding_models import (
    EmbeddingBudget,
    EmbeddingCall,
)
from pdos_next.enterprise_search.embedding_schemas import EmbeddingResponse
from pdos_next.errors import DomainError
from pdos_next.models import Artifact
from pdos_next.providers.types import ProviderError, ProviderUsage
from tests.enterprise_search.embedding_harness import (
    command_for,
    ports_for,
    reference_for,
    save_profile,
)
from tests.enterprise_search.test_embedding_projection_pg import execute_saved
from tests.enterprise_search.test_retrieval_pg import index, register
from tests.test_original_security import parsed, uploaded
from tests.test_original_security import security_work as security_work

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL") or not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
    reason="Explicit verified local PostgreSQL and checkpoint store required",
)


@pytest.mark.parametrize("boundary", ["credential_rotated", "budget_empty", "source_withdrawn"])
def test_current_batch_admission_stops_before_any_provider_call(setup, boundary):
    source = register(setup, "Synthetic current batch", "SYNTHETIC_CURRENT_BATCH")
    index(setup, source)
    provider, ports = ports_for(setup)
    command = command_for(setup)
    if boundary == "budget_empty":
        command["payload"]["index_budget_micro_usd"] = 0
    receipt, _ = save_profile(setup, ports, command)
    activities = EmbeddingActivities(
        setup.engine, ports, checkpoint_url=os.environ["PDOS_CHECKPOINT_DATABASE_URL"]
    )
    plan = activities.plan(reference_for(setup, receipt))
    assert len(plan["batches"]) == 1
    if boundary == "credential_rotated":
        provider.binding = replace(provider.binding, version=uuid4())
    elif boundary == "source_withdrawn":
        # Only the allowed status transition of this synthetic immutable source;
        # neither source text, hash, scope nor the stored batch is changed.
        with Session(setup.admin) as session, session.begin():
            session.get(Artifact, source).status = "withdrawn"
    with pytest.raises(DomainError) as failure:
        activities.embed({"context": plan["context"], "batch_id": plan["batches"][0]})
    expected = {
        "credential_rotated": "VERSION_CONFLICT",
        "budget_empty": "RATE_LIMITED",
        "source_withdrawn": "SOURCE_STALE",
    }
    assert failure.value.code == expected[boundary]
    assert provider.calls == []
    with Session(setup.admin) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(EmbeddingCall)
                .where(EmbeddingCall.tenant_id == setup.tenant)
            )
            == 0
        )
        budget = session.get(EmbeddingBudget, setup.tenant)
        assert budget.spent_micro_usd == budget.held_micro_usd == 0


@pytest.mark.parametrize("reply", ["unknown_partial_usage", "overreported_usage", "known_error"])
def test_provider_failure_or_usage_bounds_keep_exact_original_accounting(setup, monkeypatch, reply):
    index(setup, register(setup, "Synthetic accounting", "SYNTHETIC_ACCOUNTING_INPUT"))
    provider, ports = ports_for(setup)
    receipt, _ = save_profile(setup, ports, command_for(setup))
    activities = EmbeddingActivities(
        setup.engine, ports, checkpoint_url=os.environ["PDOS_CHECKPOINT_DATABASE_URL"]
    )
    plan = activities.plan(reference_for(setup, receipt))
    ref = {"context": plan["context"], "batch_id": plan["batches"][0]}
    original = provider.embed

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        if reply == "overreported_usage":
            return EmbeddingResponse(((1.0, 0.0),), input_tokens=2_147_483_647)
        raise ProviderError(
            "SYNTHETIC_FAILURE", unknown=reply == "unknown_partial_usage", usage=ProviderUsage(5, 0)
        )

    monkeypatch.setattr(provider, "embed", fail)
    with pytest.raises(DomainError):
        activities.embed(ref)
    assert len(provider.calls) == 1
    with Session(setup.admin) as session:
        call = session.scalar(select(EmbeddingCall).where(EmbeddingCall.tenant_id == setup.tenant))
        budget = session.get(EmbeddingBudget, setup.tenant)
        assert budget.held_micro_usd == 0 and budget.spent_micro_usd == call.charged_micro_usd
        if reply == "known_error":
            assert call.state == "completed" and call.input_tokens == 5
            assert call.charged_micro_usd < call.reserved_micro_usd
        else:
            assert call.state == "unknown" and call.input_tokens is None
            assert call.charged_micro_usd == call.reserved_micro_usd > 0


def test_metadata_get_and_profile_preview_require_actual_current_human_admin(setup):
    provider, ports = ports_for(setup)
    headers = {"Authorization": "Bearer " + setup.tokens[setup.peer]}
    with TestClient(create_app(setup.engine, setup.auth, embedding_ports=ports)) as client:
        path = f"/v1/categories/{setup.category}"
        assert client.get(path + "/embedding-profile", headers=headers).status_code == 403
        assert (
            client.post(
                path + "/commands/preview", json=command_for(setup), headers=headers
            ).status_code
            == 403
        )
    assert provider.calls == []


def test_customer_originals_are_excluded_until_separately_confirmed(security_work):
    setup = security_work.setup
    internal = register(setup, "Synthetic internal", "SYNTHETIC_INTERNAL_ONLY")
    customer = parsed(security_work, uploaded(security_work, content=b"SYNTHETIC_CUSTOMER_ONLY\n"))
    for source in (internal, customer):
        index(setup, source)
    provider, ports = ports_for(setup)
    receipt, preview = save_profile(setup, ports, command_for(setup))
    assert preview["review"]["expected_sources"] == 1
    _, plan = execute_saved(setup, ports, receipt)
    with Session(setup.admin) as session:
        from pdos_next.enterprise_search.embedding_models import EmbeddingBatch

        batch = session.get(EmbeddingBatch, UUID(plan["batches"][0]))
        assert {row["source_id"] for row in batch.manifest["chunks"]} == {str(internal)}
    explicit = command_for(setup, budget_revision=1)
    metadata = explicit["payload"]["metadata"]
    metadata.update(
        data_categories=["internal", "customer_original"], include_customer_original=True
    )
    receipt, preview = save_profile(setup, ports, explicit)
    assert preview["review"]["expected_sources"] == 2
    _, plan = execute_saved(setup, ports, receipt)
    with Session(setup.admin) as session:
        batch = session.get(EmbeddingBatch, UUID(plan["batches"][0]))
        assert {row["source_id"] for row in batch.manifest["chunks"]} == {
            str(internal),
            str(customer),
        }
    assert len(provider.calls) == 2
