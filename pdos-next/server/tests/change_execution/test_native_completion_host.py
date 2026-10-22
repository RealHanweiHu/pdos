"""Common human consumption and historical reads across native completion states."""

import pytest

from pdos_next import change_order_integration as integration
from pdos_next import change_order_service as orders
from pdos_next import command_handlers as commands
from pdos_next import contracts, service
from pdos_next.change_order_consumption import TIERS
from pdos_next.domain.change_control.rules import replace
from pdos_next.errors import DomainError

from . import kernel_helpers as helper
from .test_field_implementation_owner import bind_substitute, case


@pytest.mark.parametrize(
    "operation,tier,event",
    (
        ("change.effectivity.record", "T1", "change.effectivity_recorded"),
        ("change.verification.record", "T2", "change.verification_recorded"),
        ("change.close", "T2", "change.closed"),
    ),
)
def test_native_operations_use_the_actual_human_common_consumer(operation, tier, event):
    assert contracts.PAYLOADS[operation] is orders.PAYLOADS[operation]
    assert commands.handler(operation) is integration
    assert operation in commands.LIVE_CONSUMPTION_OPERATIONS & commands.PHASED_MATERIAL_OPERATIONS
    assert commands.tier_of(operation) == TIERS[operation] == tier
    assert service.EVENTS[operation] == orders.EVENTS[operation] == event


@pytest.mark.parametrize("status", ("verifying", "closed"))
def test_later_state_can_reprove_old_implementation_but_cannot_create_another(monkeypatch, status):
    value = case()
    value.request = replace(value.request, status=status)
    calls = bind_substitute(monkeypatch, value)
    from pdos_next import change_implementation_owner as owner

    basis, item = owner.validate_binding(
        None,
        value.ctx,
        helper.SCOPE.product_id,
        value.request,
        value.order,
        value.occurrence,
        new_write=False,
    )
    assert basis is value.basis and item == value.item
    assert calls == ["native-current-selection", "native-field-basis"]
    calls.clear()
    with pytest.raises(DomainError) as error:
        owner.validate_binding(
            None,
            value.ctx,
            helper.SCOPE.product_id,
            value.request,
            value.order,
            value.occurrence,
            new_write=True,
        )
    assert error.value.reason == "INVALID_STATE" and not calls


def test_named_verification_and_close_previews_label_only_the_new_save_clocks():
    host = helper.FakeHost()
    host.effective()
    before = host.request_value
    fact = host.verification_fact()
    host.run(
        "change.verification.record", {"fact_id": fact.id, "text": "Independent actual review"}
    )
    after = host.request_value
    proposed = orders._proposed_snapshot(after, before, "change.verification.record")
    assert (
        proposed["orders"][-1]["effectivity"]
        == before.model_dump(mode="json")["orders"][-1]["effectivity"]
    )
    verification = proposed["orders"][-1]["verifications"][-1]
    assert verification["fact"] == fact.model_dump(mode="json")
    assert verification["at"] == "server_on_save"
    assert verification["decision_id"] == "actual_consumed_named_proof_on_save"
    host.run("change.close", {"text": "Separate named close"})
    closed = orders._proposed_snapshot(host.request_value, after, "change.close")
    assert closed["status"] == "closed"
    assert closed["orders"][-1]["closure"]["at"] == "server_on_save"
    assert (
        closed["orders"][-1]["verifications"]
        == after.model_dump(mode="json")["orders"][-1]["verifications"]
    )


def test_completion_directory_checks_write_access_without_mutation_locks(monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4

    from pdos_next import change_completion_view as view
    from pdos_next import change_controlled_owner as controlled

    identity, product = uuid4(), uuid4()
    request = SimpleNamespace(
        id=identity,
        revision=4,
        orders=(),
        status="analysis",
        scope=SimpleNamespace(project_id=uuid4()),
    )
    row = SimpleNamespace(visibility="category", required_source_read_set=[])
    monkeypatch.setattr(view, "_current", lambda *args: (row, request, "actual-purpose"))
    monkeypatch.setattr(view, "_one", lambda *args: SimpleNamespace(revision=2))
    calls = []
    monkeypatch.setattr(controlled, "_caller", lambda *a, **kw: calls.append(("access", kw)))
    monkeypatch.setattr(view, "require_access", lambda *a, **kw: calls.append(("write_access", kw)))
    monkeypatch.setattr(controlled, "authority", lambda *a, **kw: calls.append((a[-2], kw)))
    value = view.completion_context(None, SimpleNamespace(tenant_id=uuid4()), product, identity)
    assert len(calls) == 9
    assert all(
        options == ({"write": True, "lock": False} if name == "write_access" else {"write": False})
        for name, options in calls
    )
    assert all(not value["allowed"] for value in value["capabilities"].values())
