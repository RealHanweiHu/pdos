from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.gateway import AgentGateway
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall, ValidationBudget
from pdos_next.agent_kernel.persistence import cancel_run
from pdos_next.agent_kernel.pricing import CostUsage, RateCard
from pdos_next.agent_kernel.types import ModelTurn
from pdos_next.errors import DomainError
from pdos_next.models import Grant, now
from pdos_next.providers.types import ProviderError, ProviderUsage
from tests.agent_kernel.test_gateway import Client, configured_route, turn
from tests.agent_kernel.test_transactions import human_session, run


def rate():
    return RateCard(
        "synthetic@1",
        "synthetic-model",
        "synthetic@1",
        "synthetic fixture, not real prices",
        now() - timedelta(minutes=1),
        now() + timedelta(hours=1),
        Decimal("2"),
        Decimal("8"),
        Decimal("0.5"),
        Decimal("4"),
        text_tokens_per_utf8_byte=Decimal(1),
        text_framing_tokens=4096,
        text_billing_source="Synthetic fixture token bound, not a real model qualification",
        output_cap_covers_all_billing=True,
        covers_all_fees=True,
    )


def wallet(setup, **limits):
    identity = uuid4()
    with Session(setup.admin) as s, s.begin():
        s.add(
            ValidationBudget(
                id=identity,
                tenant_id=setup.tenant,
                requester_id=setup.human,
                limit_micro_usd=limits.get("micro", 10000000),
                input_token_limit=limits.get("input", 1200000),
                output_token_limit=limits.get("output", 122880),
                call_limit=limits.get("calls", 60),
            )
        )
    return identity


def gateway(store, client, card):
    return AgentGateway(
        store, route_for=lambda _: configured_route(), rate_card_for=lambda *_: card, client=client
    )


def test_cache_usage_is_priced_by_exact_decimal_with_separate_creation_and_read():
    assert rate().actual(ProviderUsage(100, 10, 30, 20)) == 275
    assert rate().reserve(100, 10) == 480  # Worst input price is cache creation, not uncached rate.


def test_missing_expired_or_wrong_model_price_stops_before_any_http_call(setup):
    identity = wallet(setup)
    store, scope = run(setup, token_limit=500000, validation_budget_id=identity)
    client = Client(lambda _: pytest.fail("No current price permits this request"))
    for card in (
        None,
        replace(rate(), valid_until=now() - timedelta(seconds=1)),
        replace(rate(), model="different"),
        replace(rate(), text_tokens_per_utf8_byte=None),
        replace(rate(), output_cap_covers_all_billing=False),
        replace(rate(), covers_all_fees=False),
    ):
        with pytest.raises(DomainError) as e:
            turn(gateway(store, client, card), scope)
        assert e.value.code == "SOURCE_UNAVAILABLE"
    assert client.calls == 0
    with Session(setup.admin) as s:
        assert s.get(ValidationBudget, identity).calls == 0


def test_budget_total_is_shared_across_runs_and_actual_cost_is_atomic(setup):
    identity = wallet(setup, calls=1)
    store, first = run(setup, token_limit=500000, validation_budget_id=identity)
    _, second = run(setup, token_limit=500000, validation_budget_id=identity)
    card = rate()
    client = Client(
        lambda _: ModelTurn(usage=ProviderUsage(100, 10, 30, 20), structured={"ok": True})
    )
    port = gateway(store, client, card)
    turn(port, first)
    replay = turn(port, first)
    assert replay.usage == ProviderUsage(100, 10, 30, 20) and client.calls == 1
    with pytest.raises(DomainError) as e:
        turn(port, second)
    assert e.value.code == "RATE_LIMITED" and client.calls == 1
    with Session(setup.admin) as s:
        budget = s.get(ValidationBudget, identity)
        call = s.scalar(select(AgentToolCall).where(AgentToolCall.run_id == first.run_id))
        assert budget.spent_micro_usd == 275 and budget.held_micro_usd == 0 and budget.calls == 1
        assert budget.used_input_tokens == 100 and budget.used_output_tokens == 10
        assert (
            call.cost_state == "actual"
            and call.cost_pricing["source"] == "synthetic fixture, not real prices"
        )


def test_usd_cap_rejects_conservative_lease_before_sending(setup):
    identity = wallet(setup, micro=1)
    store, scope = run(setup, token_limit=500000, validation_budget_id=identity)
    client = Client(lambda _: pytest.fail("USD cap must prevent this request"))
    with pytest.raises(DomainError) as e:
        turn(gateway(store, client, rate()), scope)
    assert e.value.code == "RATE_LIMITED" and client.calls == 0


def test_unknown_cost_is_estimated_and_retained_after_slot_release_and_final_close(setup):
    identity = wallet(setup)
    store, scope = run(setup, token_limit=500000, validation_budget_id=identity)

    def unknown(_):
        raise ProviderError("PROVIDER_RESULT_UNKNOWN", unknown=True)

    port = gateway(store, Client(unknown), rate())
    with pytest.raises(DomainError):
        turn(port, scope)
    with Session(setup.admin) as s:
        budget = s.get(ValidationBudget, identity)
        call = s.scalar(select(AgentToolCall).where(AgentToolCall.run_id == scope.run_id))
        call_id, estimate = call.id, call.cost_charged_micro_usd
        assert budget.held_micro_usd == 0 and budget.spent_micro_usd == estimate > 0
        assert call.cost_state == "estimated_unknown" and call.cost_reserved_micro_usd == 0
    store.reconcile(scope, call_id, receipt_lookup=lambda *_: None, final=True)
    with Session(setup.admin) as s:
        assert s.get(ValidationBudget, identity).spent_micro_usd == estimate
        assert s.get(AgentToolCall, call_id).cost_state == "estimated_unknown"


def test_crash_recovery_marks_started_call_unknown_and_frees_reserved_cost(setup):
    identity = wallet(setup)
    store, scope = run(setup, token_limit=500000, validation_budget_id=identity)
    card = rate()
    call, _ = store.claim(
        scope,
        "crashed",
        "model",
        {},
        reservation=200,
        cost_lease=(card.reserve(100, 100), 100, 100, card.snapshot()),
    )
    with pytest.raises(DomainError):
        store.claim(scope, "crashed", "model", {}, reservation=200)
    with Session(setup.admin) as s:
        budget = s.get(ValidationBudget, identity)
        assert budget.held_micro_usd == 0 and budget.spent_micro_usd > 0
        assert s.get(AgentToolCall, call).cost_state == "estimated_unknown"


def test_cancellation_retains_conservative_cost_and_late_usage_cannot_double_charge(setup):
    identity = wallet(setup)
    store, scope = run(setup, token_limit=500000, validation_budget_id=identity)
    card = rate()
    call, _ = store.claim(
        scope,
        "inflight",
        "model",
        {},
        reservation=200,
        cost_lease=(card.reserve(100, 100), 100, 100, card.snapshot()),
    )
    with human_session(setup) as s:
        cancel_run(s, setup.ctx, scope.run_id)
    assert not store.release_call(scope, call, error="CANCELLED_RUN", unknown=True, usage=12)
    with Session(setup.admin) as s:
        budget = s.get(ValidationBudget, identity)
        assert budget.spent_micro_usd == card.reserve(100, 100)
        assert budget.held_micro_usd == 0
        assert budget.used_input_tokens == 100 and budget.used_output_tokens == 100
        assert s.get(AgentRun, scope.run_id).held_tokens == 0
        assert s.get(AgentToolCall, call).cost_state == "estimated_unknown"


def test_concurrent_runs_cannot_reserve_more_than_global_wallet_cap(setup):
    card = rate()
    ceiling = card.reserve(100, 100)
    identity = wallet(setup, micro=ceiling)
    store, first = run(setup, validation_budget_id=identity)
    _, second = run(setup, validation_budget_id=identity)
    ready = Barrier(2)

    def reserve(scope):
        ready.wait(timeout=5)
        try:
            return store.claim(
                scope,
                "parallel",
                "model",
                {},
                reservation=200,
                cost_lease=(ceiling, 100, 100, card.snapshot()),
            )[0]
        except DomainError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(reserve, (first, second)))
    assert results.count("RATE_LIMITED") == 1
    with Session(setup.admin) as s:
        budget = s.get(ValidationBudget, identity)
        assert budget.calls == 1 and budget.held_micro_usd == ceiling
        assert budget.spent_micro_usd == 0


@pytest.mark.parametrize("limits", [{"input": 1}, {"output": 1}])
def test_global_token_caps_prevent_outbound_even_with_sufficient_usd(setup, limits):
    identity = wallet(setup, **limits)
    store, scope = run(setup, token_limit=500000, validation_budget_id=identity)
    client = Client(lambda _: pytest.fail("Global token cap must prevent this request"))
    with pytest.raises(DomainError) as error:
        turn(gateway(store, client, rate()), scope)
    assert error.value.code == "RATE_LIMITED" and client.calls == 0


def test_known_error_usage_is_charged_and_ai_has_no_wallet_dml(setup):
    identity = wallet(setup)
    store, scope = run(setup, token_limit=500000, validation_budget_id=identity)

    def fail(_):
        raise ProviderError("PROVIDER_UNAVAILABLE", usage=ProviderUsage(100, 10, 30, 20))

    with pytest.raises(DomainError):
        turn(gateway(store, Client(fail), rate()), scope)
    with Session(setup.admin) as s:
        budget = s.get(ValidationBudget, identity)
        assert budget.spent_micro_usd == 275 and budget.held_micro_usd == 0
        call = s.scalar(select(AgentToolCall).where(AgentToolCall.run_id == scope.run_id))
        assert call.cost_state == "actual" and call.state == "failed"
    with setup.engine.connect() as c:
        for privilege in ("INSERT", "UPDATE", "DELETE"):
            assert not c.execute(
                text("SELECT has_table_privilege('pdos_agent','agent_validation_budgets',:p)"),
                {"p": privilege},
            ).scalar_one()


def test_known_rejection_still_retains_flat_request_fee_and_overreported_usage_is_unknown(setup):
    identity = wallet(setup)
    store, first = run(setup, token_limit=500000, validation_budget_id=identity)
    _, second = run(setup, token_limit=500000, validation_budget_id=identity)
    card = replace(rate(), request_fee=Decimal("0.01"))

    def reject(_):
        raise ProviderError("PROVIDER_RATE_LIMITED")

    with pytest.raises(DomainError):
        turn(gateway(store, Client(reject), card), first)
    with Session(setup.admin) as s:
        assert s.get(ValidationBudget, identity).spent_micro_usd == 10000

    def oversized(_):
        raise ProviderError("PROVIDER_OUTPUT_TRUNCATED", usage=ProviderUsage(1000000, 2048))

    with pytest.raises(DomainError) as error:
        turn(gateway(store, Client(oversized), card), second)
    assert error.value.code == "EXTERNAL_OUTCOME_UNKNOWN"
    with Session(setup.admin) as s:
        budget = s.get(ValidationBudget, identity)
        call = s.scalar(select(AgentToolCall).where(AgentToolCall.run_id == second.run_id))
        assert call.state == "unknown" and call.cost_state == "estimated_unknown"
        assert budget.spent_micro_usd == 10000 + call.cost_charged_micro_usd
        assert budget.held_micro_usd == 0


def test_started_call_direct_final_reconciliation_never_refunds_unknown_fees(setup):
    identity = wallet(setup)
    store, scope = run(setup, validation_budget_id=identity)
    card = rate()
    estimate = card.reserve(100, 100)
    call, _ = store.claim(
        scope,
        "worker-lost",
        "model",
        {},
        reservation=200,
        cost_lease=(estimate, 100, 100, card.snapshot()),
    )
    assert (
        store.reconcile(scope, call, receipt_lookup=lambda *_: None, final=True)["state"]
        == "failed"
    )
    with Session(setup.admin) as s:
        budget = s.get(ValidationBudget, identity)
        assert budget.spent_micro_usd == estimate and budget.held_micro_usd == 0
        assert s.get(AgentToolCall, call).cost_state == "estimated_unknown"
        assert s.get(AgentRun, scope.run_id).used_tokens == 200


def test_over_reservation_record_is_rejected_atomically_and_late_cost_is_ignored(setup):
    identity = wallet(setup)
    store, scope = run(setup, validation_budget_id=identity)
    card = rate()
    call, _ = store.claim(
        scope,
        "bound-cost",
        "model",
        {},
        reservation=200,
        cost_lease=(card.reserve(100, 100), 100, 100, card.snapshot()),
    )
    with pytest.raises(DBAPIError, match="Cost usage exceeds reservation"):
        store.release_call(scope, call, error="SOURCE_UNAVAILABLE", cost_usage=CostUsage(101, 0, 0))
    with Session(setup.admin) as s:
        assert s.get(AgentToolCall, call).state == "started"
        assert s.get(ValidationBudget, identity).held_micro_usd == card.reserve(100, 100)
    store.release_call(scope, call, error="EXTERNAL_OUTCOME_UNKNOWN", unknown=True)
    assert not store.release_call(
        scope, call, error="SOURCE_UNAVAILABLE", cost_usage=CostUsage(1, 1, 1)
    )
    with Session(setup.admin) as s:
        assert s.get(ValidationBudget, identity).spent_micro_usd == card.reserve(100, 100)


def test_scope_revocation_in_stream_callback_after_dispatch_retains_unknown_cost(setup):
    identity = wallet(setup)
    store, scope = run(setup, token_limit=500000, validation_budget_id=identity)

    def revoke(args):
        with Session(setup.admin) as s, s.begin():
            grant = s.scalar(select(Grant).where(Grant.principal_id == setup.agent))
            grant.expires_at = now() - timedelta(seconds=1)
        args["emit"]({"type": "text_delta", "text": "synthetic chunk"})
        pytest.fail("Revoked callback must not publish the received chunk")

    from pdos_agent_runtime.graph import registered_graph_context

    with registered_graph_context("xiaopai"), pytest.raises(DomainError) as error:
        gateway(store, Client(revoke), rate()).turn(
            scope,
            system="frozen",
            messages=[],
            tools=[],
            output_schema={},
            emit=lambda event: store.emit(scope, event),
        )
    assert error.value.code == "FORBIDDEN_SCOPE"
    with Session(setup.admin) as s:
        budget = s.get(ValidationBudget, identity)
        call = s.scalar(select(AgentToolCall).where(AgentToolCall.run_id == scope.run_id))
        assert call.state == "unknown" and call.cost_state == "estimated_unknown"
        assert budget.held_micro_usd == 0 and budget.spent_micro_usd > 0
        assert call.result is None


def test_multimedia_and_unverified_text_billing_stop_before_any_reservation_or_http(setup):
    identity = wallet(setup)
    store, scope = run(setup, validation_budget_id=identity)
    client = Client(lambda _: pytest.fail("Image tokens have no approved conservative price bound"))
    from pdos_agent_runtime.graph import registered_graph_context

    with registered_graph_context("xiaopai"), pytest.raises(DomainError) as error:
        gateway(store, client, rate()).turn(
            scope,
            system="frozen",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": "https://synthetic.test/image"}}
                    ],
                }
            ],
            tools=[],
            output_schema={},
        )
    assert error.value.code == "VALIDATION_FAILED" and client.calls == 0
    with Session(setup.admin) as s:
        assert s.get(ValidationBudget, identity).calls == 0


def test_error_settlement_and_cancel_use_consistent_lock_order_and_charge_once(setup):
    identity = wallet(setup)
    store, scope = run(setup, validation_budget_id=identity)
    card = rate()
    estimate = card.reserve(100, 100)
    call, _ = store.claim(
        scope,
        "cancel-race",
        "model",
        {},
        reservation=200,
        cost_lease=(estimate, 100, 100, card.snapshot()),
    )
    ready = Barrier(2)

    def settle():
        ready.wait(timeout=5)
        store.release_call(scope, call, error="SOURCE_UNAVAILABLE", cost_usage=CostUsage(1, 1, 10))

    def cancel():
        ready.wait(timeout=5)
        with human_session(setup) as s:
            cancel_run(s, setup.ctx, scope.run_id)

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = [workers.submit(settle), workers.submit(cancel)]
        for outcome in outcomes:
            outcome.result(timeout=10)
    with Session(setup.admin) as s:
        budget = s.get(ValidationBudget, identity)
        assert budget.held_micro_usd == 0 and budget.spent_micro_usd in {10, estimate}
        assert s.get(AgentRun, scope.run_id).held_tokens == 0
