"""Participant orchestration with explicit fake host ports; no database transaction claims."""

from dataclasses import dataclass, field
from datetime import timedelta

import pytest

from pdos_next.domain.supply_cost import Ports, SupplyBusinessError, SupplyCostHandler
from pdos_next.domain.supply_cost.handlers import semantic_digest
from pdos_next.engines.supply_cost.common import digest
from pdos_next.engines.supply_cost.dto import ExchangeRate
from pdos_next.schemas.supply_cost.dto import (
    CalculateCoveragePayload,
    CommandBinding,
    CommandReceipt,
    Confirmation,
    EstimateCostPayload,
    Intent,
    Preview,
    RecordSupplyPayload,
)

from .helpers import AS_OF, SCOPE, bound_demand, cost_inputs, price, ref, supply


@dataclass
class UnitOfWork:
    calls: list[str] = field(default_factory=list)
    staged: list = field(default_factory=list)

    def commit(self):
        raise AssertionError("The domain participant must not commit the common transaction")


class FakeCommand:
    """Test host enforces token/expiry. Real locking/atomicity is mainline DB coverage."""

    def __init__(self):
        self.binding = CommandBinding(scope=SCOPE, as_of=AS_OF, current_time=AS_OF)
        self.denied = False
        self.saved_preview = None
        self.replayed = None
        self.preview_update = {}
        self.receipt_update = {}

    def bind(self, uow, context, intent, confirmation):
        assert context is CONTEXT
        uow.calls.append("bind")
        return self.binding

    def authorize(self, uow, context, binding, intent, *, apply):
        uow.calls.append("authorize.apply" if apply else "authorize.preview")
        if self.denied:
            raise SupplyBusinessError("FORBIDDEN", "Server refused the current principal")

    def replay(self, uow, binding, intent, confirmation):
        uow.calls.append("replay")
        return self.replayed

    def preview(self, uow, binding, intent, plan):
        uow.calls.append("preview")
        self.saved_preview = Preview(
            review_id="review",
            confirmation_token="server-token-that-is-at-least-20",
            plan_sha256=digest(plan),
            expires_at=AS_OF + timedelta(minutes=15),
            as_of=plan.as_of,
            review=plan,
        ).model_copy(update=self.preview_update)
        return self.saved_preview

    def stage_once(self, uow, context, binding, intent, confirmation, plan):
        uow.calls.append("stage")
        preview = self.saved_preview
        if (
            preview is None
            or confirmation.review_id != preview.review_id
            or (confirmation.token != preview.confirmation_token)
        ):
            raise SupplyBusinessError("CONFIRMATION_REJECTED", "Host token binding failed")
        if binding.current_time >= preview.expires_at:
            raise SupplyBusinessError("CONFIRMATION_EXPIRED", "Host one-use review expired")
        uow.staged.append(plan)
        subject = {
            "supply.snapshot.record": "supply_snapshot",
            "supply.coverage.calculate": "supply_coverage",
            "supply.cost.estimate": "cost_estimate",
        }[intent.operation]
        receipt = CommandReceipt(
            receipt_id="receipt",
            subject_id="saved",
            subject_type=subject,
            revision=1,
            plan_sha256=digest(plan),
        ).model_copy(update=self.receipt_update)
        self.replayed = receipt.model_copy(update={"replayed": True})
        return receipt


CONTEXT = object()


class FakeDemand:
    def __init__(self, value):
        self.value = value
        self.denied = False

    def load(self, uow, scope, build_id, expected_revision, as_of):
        uow.calls.append("demand")
        assert as_of == AS_OF
        if self.denied:
            raise SupplyBusinessError("SOURCE_UNAVAILABLE", "Evidence port denied current source")
        return self.value


class FakeSupply:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.current_snapshot = snapshot
        self.alternates = ()
        self.denied = False

    def current(self, uow, scope, build_id):
        uow.calls.append("supply.current")
        return self.current_snapshot

    def capture(self, uow, scope, capture_id, binding, as_of):
        uow.calls.append("supply.capture")
        assert capture_id == "capture"
        return self.snapshot

    def get(self, uow, scope, snapshot_id, expected_revision):
        uow.calls.append("supply.get")
        if self.denied:
            raise SupplyBusinessError("SOURCE_UNAVAILABLE", "Import port refused its source")
        return self.snapshot

    def verified_alternates(self, uow, scope, binding, as_of):
        uow.calls.append("supply.alternates")
        return self.alternates


class FakeCost:
    def __init__(self, inputs):
        self.inputs = inputs

    def get(self, uow, scope, input_id, expected_revision, binding):
        uow.calls.append("cost.get")
        return self.inputs


@pytest.fixture
def host(bound, snapshot, costs):
    command, demand, supplier, cost = (
        FakeCommand(),
        FakeDemand(bound),
        FakeSupply(snapshot),
        FakeCost(costs),
    )
    return (
        command,
        demand,
        supplier,
        cost,
        SupplyCostHandler(Ports(command, demand, supplier, cost)),
    )


def intent(operation="supply.coverage.calculate", **updates):
    payload = {
        "supply.coverage.calculate": CalculateCoveragePayload(
            build_id="build",
            expected_build_revision=1,
            supply_snapshot_id="supply-1",
            expected_supply_revision=1,
        ),
        "supply.cost.estimate": EstimateCostPayload(
            build_id="build",
            expected_build_revision=1,
            cost_input_id="cost-1",
            expected_cost_input_revision=1,
        ),
        "supply.snapshot.record": RecordSupplyPayload(
            build_id="build",
            expected_build_revision=1,
            capture_id="capture",
            reason="Reviewed importer evidence and current balances",
        ),
    }[operation]
    return Intent(
        command_id="command",
        idempotency_key="idempotency-key",
        operation=operation,
        payload=payload,
    ).model_copy(update=updates)


def confirmation(preview):
    return Confirmation(
        review_id=preview.review_id,
        token=preview.confirmation_token,
        plan_sha256=preview.plan_sha256,
    )


def rejects(code, call):
    with pytest.raises(SupplyBusinessError) as error:
        call()
    assert error.value.code == code


@pytest.mark.parametrize(
    "operation,subject",
    [
        ("supply.coverage.calculate", "supply_coverage"),
        ("supply.cost.estimate", "cost_estimate"),
        ("supply.snapshot.record", "supply_snapshot"),
    ],
)
def test_substantive_t1_preview_then_stage_in_same_host_uow(host, operation, subject):
    command, _, supplier, _, handler = host
    if operation == "supply.snapshot.record":
        supplier.current_snapshot = None
    uow, request = UnitOfWork(), intent(operation)
    preview = handler.preview(uow, CONTEXT, request)
    assert preview.review.write_tier == "T1"
    assert preview.review.effect and preview.review.value
    assert len(preview.review.sources) >= 6
    assert preview.plan_sha256 == digest(preview.review)
    assert uow.staged == []
    receipt = handler.apply(uow, CONTEXT, request, confirmation(preview))
    assert receipt.subject_type == subject and receipt.plan_sha256 == preview.plan_sha256
    assert uow.staged == [preview.review]
    assert uow.calls.index("authorize.preview") < uow.calls.index("demand")
    assert uow.calls.index("replay") < uow.calls.index("stage")
    assert command.binding.scope == SCOPE


@pytest.mark.parametrize("apply", [False, True])
def test_current_authorization_refusal_happens_before_any_domain_reads_or_stage(host, apply):
    command, _, _, _, handler = host
    command.denied = True
    uow, request = UnitOfWork(), intent()
    if apply:
        confirm = Confirmation(
            review_id="review", token="token-with-at-least-20-chars", plan_sha256="a" * 64
        )
        rejects("FORBIDDEN", lambda: handler.apply(uow, CONTEXT, request, confirm))
    else:
        rejects("FORBIDDEN", lambda: handler.preview(uow, CONTEXT, request))
    assert uow.calls == ["bind", "authorize.apply" if apply else "authorize.preview"]
    assert not uow.staged


@pytest.mark.parametrize(
    "missing,operation",
    [
        ("demand", "supply.coverage.calculate"),
        ("supply", "supply.coverage.calculate"),
        ("cost", "supply.cost.estimate"),
    ],
)
def test_absent_port_is_explicit_pending_integration(host, missing, operation):
    command, demand, supplier, cost, _ = host
    ports = {"demand": demand, "supply": supplier, "cost": cost}
    ports[missing] = None
    handler = SupplyCostHandler(Ports(command, **ports))
    uow = UnitOfWork()
    rejects("PORT_UNCONNECTED", lambda: handler.preview(uow, CONTEXT, intent(operation)))
    assert "stage" not in uow.calls and "preview" not in uow.calls


@pytest.mark.parametrize(
    "kind,code",
    [
        ("build_scope", "FORBIDDEN_SCOPE"),
        ("build_version", "BUILD_VERSION_CONFLICT"),
        ("supply_version", "SNAPSHOT_VERSION_CONFLICT"),
        ("cost_version", "COST_INPUT_VERSION_CONFLICT"),
    ],
)
def test_wrong_scope_or_version_from_port_is_rejected(host, kind, code):
    _, demand, supplier, cost, handler = host
    operation = "supply.coverage.calculate"
    if kind == "build_scope":
        demand.value = demand.value.model_copy(
            update={"scope": SCOPE.model_copy(update={"tenant_id": "other"})}
        )
    elif kind == "build_version":
        demand.value = bound_demand(build_ref=ref("build", version="2"))
    elif kind == "supply_version":
        supplier.snapshot = supplier.snapshot.model_copy(update={"revision": 2})
    else:
        operation = "supply.cost.estimate"
        cost.inputs = cost.inputs.model_copy(update={"revision": 2})
    rejects(code, lambda: handler.preview(UnitOfWork(), CONTEXT, intent(operation)))


@pytest.mark.parametrize("change", ["none", "different"])
def test_selected_supply_must_still_be_current(host, change):
    _, _, supplier, _, handler = host
    supplier.current_snapshot = (
        None if change == "none" else supplier.snapshot.model_copy(update={"note": "New source"})
    )
    rejects(
        "PORT_UNCONNECTED" if change == "none" else "SNAPSHOT_VERSION_CONFLICT",
        lambda: handler.preview(UnitOfWork(), CONTEXT, intent()),
    )


def test_capture_optimistic_previous_pointer_fails_before_capture(host):
    _, _, _, _, handler = host
    uow = UnitOfWork()
    rejects(
        "SNAPSHOT_VERSION_CONFLICT",
        lambda: handler.preview(uow, CONTEXT, intent("supply.snapshot.record")),
    )
    assert "supply.capture" not in uow.calls


@pytest.mark.parametrize("port", ["demand", "supply"])
def test_source_port_refusal_is_not_converted_into_empty_success(host, port):
    _, demand, supplier, _, handler = host
    (demand if port == "demand" else supplier).denied = True
    uow = UnitOfWork()
    rejects("SOURCE_UNAVAILABLE", lambda: handler.preview(uow, CONTEXT, intent()))
    assert not uow.staged and "preview" not in uow.calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("plan_sha256", "a" * 64),
        ("expires_at", AS_OF),
        ("as_of", AS_OF - timedelta(seconds=1)),
    ],
)
def test_host_preview_must_bind_exact_substantive_plan_and_validity(host, field, value):
    command, _, _, _, handler = host
    command.preview_update = {field: value}
    rejects("PREVIEW_PORT_REJECTED", lambda: handler.preview(UnitOfWork(), CONTEXT, intent()))


def test_changed_source_between_preview_and_apply_requires_new_confirmation(host):
    _, _, supplier, _, handler = host
    uow, request = UnitOfWork(), intent()
    preview = handler.preview(uow, CONTEXT, request)
    changed = supplier.snapshot.model_copy(update={"ref": ref("supply-1", version="2")})
    supplier.snapshot = supplier.current_snapshot = changed
    rejects("PREVIEW_CHANGED", lambda: handler.apply(uow, CONTEXT, request, confirmation(preview)))
    assert not uow.staged


@pytest.mark.parametrize("source", ["build", "original", "supply", "quote", "rate"])
def test_current_expiry_between_preview_and_apply_is_blocking(host, source):
    command, demand, supplier, cost, handler = host
    expires = AS_OF + timedelta(minutes=1)
    operation = "supply.coverage.calculate"
    if source == "build":
        demand.value = bound_demand(build_ref=ref("build", valid_until=expires))
        supplier.snapshot = supplier.current_snapshot = supply(demand.value)
    elif source == "original":
        demand.value = demand.value.model_copy(
            update={"source_read_set": (ref("original-evidence", valid_until=expires),)}
        )
        supplier.snapshot = supplier.current_snapshot = supply(demand.value)
    elif source == "supply":
        supplier.snapshot = supplier.current_snapshot = supply(
            demand.value, ref=ref("supply-1", valid_until=expires)
        )
    else:
        operation = "supply.cost.estimate"
        if source == "quote":
            cost.inputs = cost_inputs(demand.value, prices=(price(valid_until=expires),))
        else:
            rate = ExchangeRate(
                rate_id="rate",
                ref=ref("rate", captured_at=AS_OF - timedelta(days=7)),
                from_currency="EUR",
                to_currency="USD",
                rate="1.2",
                purpose="budget",
            )
            cost.inputs = cost_inputs(demand.value, prices=(price(currency="EUR"),), rates=(rate,))
    uow, request = UnitOfWork(), intent(operation)
    preview = handler.preview(uow, CONTEXT, request)
    command.binding = command.binding.model_copy(update={"current_time": expires})
    rejects("SOURCE_STALE", lambda: handler.apply(uow, CONTEXT, request, confirmation(preview)))
    assert not uow.staged


def test_duplicate_completed_receipt_replays_before_now_stale_domain_reads(host):
    command, demand, supplier, _, handler = host
    uow, request = UnitOfWork(), intent()
    preview = handler.preview(uow, CONTEXT, request)
    original = handler.apply(uow, CONTEXT, request, confirmation(preview))
    demand.denied = supplier.denied = True
    command.binding = command.binding.model_copy(
        update={"current_time": AS_OF + timedelta(days=30)}
    )
    uow.calls.clear()
    repeated = handler.apply(uow, CONTEXT, request, confirmation(preview))
    assert repeated.receipt_id == original.receipt_id and repeated.replayed
    assert uow.calls == ["bind", "authorize.apply", "replay"]
    assert len(uow.staged) == 1


def test_confirmation_token_and_expiry_are_enforced_by_host_stage_port(host):
    command, _, _, _, handler = host
    uow, request = UnitOfWork(), intent()
    preview = handler.preview(uow, CONTEXT, request)
    wrong = confirmation(preview).model_copy(update={"token": "other-token-at-least-20-chars"})
    rejects("CONFIRMATION_REJECTED", lambda: handler.apply(uow, CONTEXT, request, wrong))
    command.binding = command.binding.model_copy(update={"current_time": preview.expires_at})
    rejects(
        "CONFIRMATION_EXPIRED", lambda: handler.apply(uow, CONTEXT, request, confirmation(preview))
    )
    assert uow.staged == []


@pytest.mark.parametrize(
    "field,value", [("subject_type", "cost_estimate"), ("plan_sha256", "f" * 64)]
)
def test_replay_receipt_must_match_operation_and_confirmed_hash(host, field, value):
    command, _, _, _, handler = host
    confirmed = Confirmation(
        review_id="review", token="token-at-least-20-characters", plan_sha256="a" * 64
    )
    command.replayed = CommandReceipt(
        receipt_id="receipt",
        subject_id="saved",
        subject_type="supply_coverage",
        revision=1,
        plan_sha256=confirmed.plan_sha256,
        replayed=True,
    ).model_copy(update={field: value})
    rejects(
        "RECEIPT_PORT_REJECTED", lambda: handler.apply(UnitOfWork(), CONTEXT, intent(), confirmed)
    )


def test_conflicting_source_versions_in_server_read_set_are_blocked(host):
    _, demand, supplier, _, handler = host
    demand.value = demand.value.model_copy(update={"source_read_set": (ref("build", version="2"),)})
    supplier.snapshot = supplier.current_snapshot = supply(demand.value)
    rejects("SOURCE_VERSION_CONFLICT", lambda: handler.preview(UnitOfWork(), CONTEXT, intent()))


def test_semantic_digest_deduplicates_command_keys_but_not_payload():
    original = intent()
    different_keys = original.model_copy(
        update={"command_id": "retry", "idempotency_key": "another-idempotency"}
    )
    changed = original.model_copy(
        update={"payload": original.payload.model_copy(update={"expected_supply_revision": 2})}
    )
    assert semantic_digest(original) == semantic_digest(different_keys)
    assert semantic_digest(original) != semantic_digest(changed)
