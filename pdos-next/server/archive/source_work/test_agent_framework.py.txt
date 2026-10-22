"""The next host must actually bind its model factory inside the shared execution graph."""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pdos_agent_runtime.graph import in_agent_graph

from pdos_next.agent_execution import (
    ConfiguredProviderFactory,
    configured_provider_factory,
)
from pdos_next.errors import DomainError
from pdos_next.workflows.worker import Activities


def work_scope(monkeypatch):
    tenant, product, work, requester = (uuid4() for _ in range(4))
    row = SimpleNamespace(product_id=product, accountable_owner_id=requester, status="accepted")

    @contextmanager
    def session(*args):
        yield SimpleNamespace(get=lambda *args: row)

    monkeypatch.setattr("pdos_next.workflows.worker.tenant_session", session)
    return tenant, product, work, requester


def test_worker_uses_its_host_factory_then_a_real_graph_and_closes_provider(monkeypatch):
    tenant, product, work, requester = work_scope(monkeypatch)
    calls = []
    provider = SimpleNamespace(close=lambda: calls.append("closed"))

    def factory(ctx, work_id):
        calls.append((ctx.tenant_id, ctx.requester_id, work_id))
        return provider

    def resume(engine, ctx, work_id, actual, **kwargs):
        assert in_agent_graph()
        assert actual is provider
        assert work_id == work
        assert kwargs["checkpoint_url"] == "private-checkpoint-target"
        return {"status": "completed", "result_id": "domain-receipt"}

    monkeypatch.setattr("pdos_next.workflows.worker.resume", resume)
    activities = Activities(object(), None, "private-checkpoint-target", provider_factory=factory)
    assert (
        activities.advance(
            {"tenant_id": str(tenant), "product_id": str(product), "subject_id": str(work)}
        )["status"]
        == "completed"
    )
    assert calls == [(tenant, requester, work), "closed"]
    assert not in_agent_graph()


def test_missing_independent_ports_records_an_explicit_wait_without_model(monkeypatch):
    tenant, product, work, requester = work_scope(monkeypatch)
    observed = []

    def unavailable(engine, ctx, work_id, code):
        observed.append((work_id, code))
        return {"status": "waiting_input", "error_code": code}

    monkeypatch.setattr("pdos_next.runtime.model_unavailable", unavailable)
    activities = Activities(object(), None, "private-checkpoint-target")
    assert isinstance(activities.provider_factory, ConfiguredProviderFactory)
    result = activities.advance(
        {"tenant_id": str(tenant), "product_id": str(product), "subject_id": str(work)}
    )
    assert result == {"status": "waiting_input", "error_code": "MODEL_RUNTIME_PORTS_MISSING"}
    assert observed == [(work, "MODEL_RUNTIME_PORTS_MISSING")]


def test_default_factory_cannot_fall_back_to_original_pdos_credentials():
    with pytest.raises(DomainError) as error:
        configured_provider_factory(object())(None, uuid4())
    assert error.value.code == "MODEL_RUNTIME_PORTS_MISSING"
