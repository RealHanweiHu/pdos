"""A GET memo preserves identity, expiry and live consumer source guards; no database."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.domain.sample_handoff import service
from pdos_next.errors import DomainError
from pdos_next.service import Context

AT = datetime(2026, 10, 2, 16, tzinfo=UTC)


class MemorySession:
    def __init__(self):
        self.transaction = object()
        self.engine = SimpleNamespace()
        self.new, self.dirty, self.deleted = set(), set(), set()

    def get_transaction(self):
        return self.transaction

    def get_bind(self):
        return self.engine


def setup(monkeypatch):
    session, tenant, product, person, build = MemorySession(), uuid4(), uuid4(), uuid4(), uuid4()
    context = Context(tenant, person, person)
    start = SimpleNamespace(
        id=uuid4(),
        owner_id=person,
        snapshot_sha256="a" * 64,
        visibility="category",
        required_source_read_set=[],
    )
    clock = [AT]
    monkeypatch.setattr(service, "now", lambda: clock[0])
    calls = []

    def projection(*args):
        calls.append(args)
        return {
            "execution_status": "executing",
            "execution_qualification": "limited_current",
            "stop_required": False,
            "required_source_read_set": [],
            "authority": {"start": {"valid_until": (AT + timedelta(hours=1)).isoformat()}},
            "fact_refs": [{"valid_from": (AT + timedelta(seconds=3)).isoformat()}],
        }

    monkeypatch.setattr(service, "execution_projection", projection)
    return session, context, product, build, start, clock, calls


def test_same_get_start_projection_reuses_proof_and_detaches_mutable_output(monkeypatch):
    session, ctx, product, build, start, _, calls = setup(monkeypatch)
    cache = service.ReadContext(session, ctx, product)
    original = cache.projection(session, ctx, product, start, build)
    original["required_source_read_set"].append({"untrusted_edit": True})
    repeated = cache.projection(session, ctx, product, start, build)
    assert len(calls) == 1
    assert repeated["required_source_read_set"] == []
    assert repeated["execution_qualification"] == "limited_current"


def test_one_get_uses_one_snapshot_despite_nested_time_fields(monkeypatch):
    session, ctx, product, build, start, clock, calls = setup(monkeypatch)
    cache = service.ReadContext(session, ctx, product)
    cache.projection(session, ctx, product, start, build)
    clock[0] = AT + timedelta(seconds=3)
    cache.projection(session, ctx, product, start, build)
    assert len(calls) == 1


def test_nested_material_deadlines_do_not_trigger_a_second_projection(monkeypatch):
    session, ctx, product, build, start, clock, calls = setup(monkeypatch)

    def slow_projection(*args):
        calls.append(args)
        clock[0] = AT + timedelta(seconds=2)
        return {
            "execution_status": "executing",
            "execution_qualification": "limited_current",
            "stop_required": False,
            "authority": {"start": {"valid_until": (AT + timedelta(seconds=1)).isoformat()}},
            "window_end": (AT + timedelta(hours=1)).isoformat(),
        }

    monkeypatch.setattr(service, "execution_projection", slow_projection)
    cache = service.ReadContext(session, ctx, product)
    cache.projection(session, ctx, product, start, build)
    cache.projection(session, ctx, product, start, build)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "change", ["professional_flag", "operational_flag", "professional_epoch", "operational_epoch"]
)
def test_server_runtime_profile_and_registry_epoch_changes_recheck_cache(monkeypatch, change):
    session, ctx, product, build, start, _, calls = setup(monkeypatch)
    cache = service.ReadContext(session, ctx, product)
    cache.projection(session, ctx, product, start, build)
    names = {
        "professional_flag": "_pdos_professional_synthetic",
        "operational_flag": "_pdos_operational_synthetic",
        "professional_epoch": "_pdos_professional_issuer_epochs",
        "operational_epoch": "_pdos_operational_issuer_epochs",
    }
    setattr(session.engine, names[change], {"issuer": 2} if "epoch" in change else True)
    cache.projection(session, ctx, product, start, build)
    assert len(calls) == 2


@pytest.mark.parametrize(
    "change", ["session", "transaction", "actor", "requester", "run", "product", "write", "dirty"]
)
def test_read_context_cannot_cross_session_transaction_identity_product_or_mutation(
    monkeypatch, change
):
    session, ctx, product, _, _, _, _ = setup(monkeypatch)
    cache = service.ReadContext(session, ctx, product)
    arguments = {"write": False}
    if change == "session":
        session = MemorySession()
    elif change == "transaction":
        session.transaction = object()
    elif change == "product":
        product = uuid4()
    elif change == "write":
        arguments["write"] = True
    elif change == "dirty":
        session.dirty.add(object())
    else:
        ctx = Context(
            ctx.tenant_id,
            uuid4() if change == "actor" else ctx.actor_id,
            uuid4() if change == "requester" else ctx.requester_id,
            uuid4() if change == "run" else None,
        )
    with pytest.raises(DomainError) as error:
        cache.check(session, ctx, product, **arguments)
    assert error.value.reason == "INVALID_READ_CONTEXT"


def test_failure_reuse_is_fail_closed_and_runtime_change_rechecks(monkeypatch):
    session, ctx, product, build, start, _, calls = setup(monkeypatch)

    def failure(*args):
        calls.append(args)
        raise DomainError("SOURCE_UNAVAILABLE", "Synthetic unavailable proof", 403)

    monkeypatch.setattr(service, "execution_projection", failure)
    cache = service.ReadContext(session, ctx, product)
    for _ in range(2):
        with pytest.raises(DomainError) as error:
            cache.projection(session, ctx, product, start, build)
        assert error.value.reason == "SOURCE_UNAVAILABLE"
    assert len(calls) == 1
    session.engine._pdos_operational_issuer_epochs = {"issuer": 3}
    with pytest.raises(DomainError):
        cache.projection(session, ctx, product, start, build)
    assert len(calls) == 2


def test_cached_start_projection_never_bypasses_live_consumer_source_acl(monkeypatch):
    session, ctx, product, build, start, _, calls = setup(monkeypatch)
    session.scalar = lambda _: start
    monkeypatch.setattr(service, "execution_row", lambda *args: start)
    source_calls = []

    def source_gate(*args):
        source_calls.append(args)
        if len(source_calls) == 2:
            raise DomainError("FORBIDDEN_SCOPE", "Synthetic consumer lost source access", 403)

    monkeypatch.setattr(service, "_sources", source_gate)
    cache = service.ReadContext(session, ctx, product)
    chain = {"build": SimpleNamespace(id=build)}
    service._start_context(session, ctx, product, chain, read_context=cache)
    with pytest.raises(DomainError) as error:
        service._start_context(session, ctx, product, chain, read_context=cache)
    assert error.value.reason == "FORBIDDEN_SCOPE"
    assert len(calls) == 1 and len(source_calls) == 2


def test_optimized_chain_checks_ancestor_sources_even_without_inherited_sample_readset(monkeypatch):
    session, ctx, product, build_id, _, _, _ = setup(monkeypatch)
    sample_id, actual_id, lot_id, project_id = uuid4(), uuid4(), uuid4(), uuid4()
    ancestor = {"artifact_id": str(uuid4()), "expected_revision": 1}
    sample = SimpleNamespace(
        id=sample_id,
        tenant_id=ctx.tenant_id,
        product_id=product,
        visibility="category",
        owner_id=ctx.requester_id,
        actual_configuration_id=actual_id,
        lot_id=lot_id,
        build_id=build_id,
        project_id=project_id,
        build_revision=1,
        required_source_read_set=[],
    )
    lot = SimpleNamespace(
        actual_configuration_id=actual_id,
        actual_configuration_revision=1,
        build_id=build_id,
        project_id=project_id,
        required_source_read_set=[ancestor],
    )
    actual = SimpleNamespace(
        id=actual_id,
        revision=1,
        project_id=project_id,
        build_id=build_id,
        required_source_read_set=[ancestor],
    )
    build = SimpleNamespace(id=build_id, revision=1, project_id=project_id)
    session.scalar = lambda _: sample
    monkeypatch.setattr(service, "_human", lambda *args, **kwargs: None)
    contexts = []

    def lot_context(*args):
        contexts.append(args)
        return {"lot": lot, "actual_row": actual, "build": build, "reads": [ancestor]}

    monkeypatch.setattr(service, "_lot_context", lot_context)
    monkeypatch.setattr(service, "sample_view", lambda *args: {"source_status": "current"})
    checked = []

    def private_ancestor(*args):
        checked.extend(deepcopy(args[-1].required_source_read_set))
        raise DomainError("SOURCE_UNAVAILABLE", "Synthetic ancestor source outside audience", 403)

    monkeypatch.setattr(service, "_read_evidence", private_ancestor)
    with pytest.raises(DomainError) as error:
        service._chain(session, ctx, product, sample_id)
    assert error.value.status == 403
    assert checked == [ancestor] and len(contexts) == 1
