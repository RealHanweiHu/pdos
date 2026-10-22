"""Fact timestamps remain exact; decisions sample the clock after authoritative reads."""

from dataclasses import replace
from datetime import timedelta

import pytest

from pdos_next.original_lifecycle.types import DecisionReason, LifecycleFailure
from tests.original_lifecycle.helpers import confirm, fixture, preview, record, start

pytestmark = pytest.mark.usefixtures("pure_guard")


class AdvancingClock:
    def __init__(self, value):
        self.value = value

    def now(self):
        self.value += timedelta(milliseconds=1)
        return self.value


def test_advancing_time_through_preview_confirm_permit_validation_and_record_is_not_future():
    original_clock, store, _, service, physical = fixture()
    clock = AdvancingClock(original_clock.now())
    store.clock = service.clock = clock
    candidate = preview(store, service)
    assert candidate.decision.eligible
    assert candidate.captured_at >= candidate.original.observed_at
    assert candidate.captured_at >= candidate.references.observed_at
    intent = confirm(store, service, candidate)
    permit = start(store, service, intent)
    with store.command_transaction():
        service.validate_effect("service", permit)
    completed = record(store, service, intent, physical.apply_once(permit))
    assert completed.state.value == "applied"
    assert completed.recovery_required is False and completed.protection_reasons == ()


def test_actually_future_reference_observation_remains_protected(monkeypatch):
    original_clock, store, _, service, _ = fixture()
    clock = AdvancingClock(original_clock.now())
    store.clock = service.clock = clock
    read = service.references.read_current

    def future(reference):
        result = read(reference)
        return replace(result, observed_at=clock.now() + timedelta(seconds=10))

    monkeypatch.setattr(service.references, "read_current", future)
    candidate = preview(store, service)
    assert not candidate.decision.eligible
    assert DecisionReason.FACT_TIME_INVALID in candidate.decision.reasons


def test_candidate_has_no_material_deadline_after_authoritative_read(monkeypatch):
    clock, store, _, service, _ = fixture()
    candidate = preview(store, service)
    read = service.references.read_under_fence

    def expires(fence):
        result = read(fence)
        clock.value = candidate.captured_at + timedelta(minutes=30)
        return result

    monkeypatch.setattr(service.references, "read_under_fence", expires)
    assert confirm(store, service, candidate).state.value == "pending"


def test_current_authority_is_rechecked_after_fact_read(monkeypatch):
    _, store, authority, service, _ = fixture()
    candidate = preview(store, service)
    read = service.references.read_under_fence

    def revoked(fence):
        result = read(fence)
        authority.denied = True
        return result

    monkeypatch.setattr(service.references, "read_under_fence", revoked)
    with pytest.raises(LifecycleFailure) as error:
        confirm(store, service, candidate)
    assert error.value.code == "FORBIDDEN_SCOPE"
    assert not store.intents
