from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.errors import DomainError
from pdos_next.model_gateway import CallPermit, Reservation
from pdos_next.model_gateway.persistent_budget import (
    _apply_settlement,
    _metadata,
    _permit_shape,
    _reservation_shape,
    _settlement,
)
from pdos_next.providers import ProviderUsage
from pdos_next.service import Context


def bound():
    ctx = Context(uuid4(), uuid4(), uuid4(), uuid4(), 0)
    permit = CallPermit(
        call_id=uuid4(),
        request_digest="a" * 64,
        route_digest="b" * 64,
        writer_id=ctx.actor_id,
        provider_version="synthetic-v1",
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
        egress_allowed=True,
    )
    return ctx, permit


@pytest.mark.parametrize(
    "change",
    [
        lambda p: replace(p, egress_allowed=False),
        lambda p: replace(p, expires_at=datetime.now()),
        lambda p: replace(p, expires_at=datetime.now(UTC) - timedelta(seconds=1)),
        lambda p: replace(p, purpose="publish"),
        lambda p: replace(p, request_digest="raw private source"),
        lambda p: replace(p, route_digest="http://untrusted.invalid"),
        lambda p: replace(p, writer_id=uuid4()),
        lambda p: replace(p, protocol="undocumented-protocol"),
    ],
)
def test_budget_permit_rejects_mismatch_before_database(change):
    ctx, permit = bound()
    with pytest.raises(DomainError) as error:
        _permit_shape(change(permit), ctx)
    assert error.value.reason == "MODEL_EGRESS_DENIED"


@pytest.mark.parametrize(
    "code", ["Private source statement", "ERROR\nAPI_KEY=secret", "A" * 81, "lowercase", ""]
)
def test_error_storage_uses_bounded_registered_codes_only(code):
    with pytest.raises(DomainError):
        _metadata(code, None)


def test_valid_protocol_port_metadata_and_hash_shaped_permit():
    ctx, permit = bound()
    _permit_shape(permit, ctx)
    _metadata("PROVIDER_RESULT_UNKNOWN", "synthetic-call_1")
    _reservation_shape(Reservation(permit.call_id, "synthetic-random-token-1"))


@pytest.mark.parametrize("status", ["reserved", "unknown"])
def test_actual_settlement_releases_reservation_and_charges_exactly_once(status):
    run = SimpleNamespace(reserved_tokens=500, used_tokens=20, token_limit=1000)
    row = SimpleNamespace(status=status, reserved=300, charged=None, error_code="MODEL_UNKNOWN")
    final = _settlement(ProviderUsage(100, 30, 60, 10), "completed", None, None)
    assert _apply_settlement(run, row, final) is False
    assert (run.reserved_tokens, run.used_tokens) == (200, 150)
    assert (row.status, row.charged, row.error_code) == ("completed", 130, None)
    assert _apply_settlement(run, row, final) is False
    assert (run.reserved_tokens, run.used_tokens) == (200, 150)


def test_repeat_settlement_with_changed_usage_or_outcome_is_conflict():
    run = SimpleNamespace(reserved_tokens=0, used_tokens=130, token_limit=1000)
    row = SimpleNamespace(status="completed", reserved=300, charged=130, error_code=None)
    for final in [
        _settlement(ProviderUsage(100, 31), "completed", None, None),
        _settlement(ProviderUsage(100, 30), "rejected", None, None),
    ]:
        with pytest.raises(DomainError) as error:
            _apply_settlement(run, row, final)
        assert error.value.reason == "MODEL_BUDGET_CONFLICT"
        assert run.used_tokens == 130 and row.status == "completed"


def test_over_budget_preserves_real_cost_and_marks_followup_stopped():
    run = SimpleNamespace(reserved_tokens=300, used_tokens=0, token_limit=300)
    row = SimpleNamespace(status="reserved", reserved=300, charged=None, error_code=None)
    final = _settlement(ProviderUsage(320, 30), "completed", None, None)
    assert _apply_settlement(run, row, final) is True
    assert run.reserved_tokens == 0 and run.used_tokens == 350
    assert row.charged == 350 and row.status == "completed"


def test_counter_underflow_does_not_release_or_charge():
    run = SimpleNamespace(reserved_tokens=100, used_tokens=0, token_limit=300)
    row = SimpleNamespace(status="reserved", reserved=300, charged=None, error_code=None)
    final = _settlement(ProviderUsage(30, 10), "completed", None, None)
    with pytest.raises(DomainError):
        _apply_settlement(run, row, final)
    assert (run.reserved_tokens, run.used_tokens, row.status) == (100, 0, "reserved")


def test_repeated_trace_and_usage_are_idempotent_but_breakdown_is_immutable():
    run = SimpleNamespace(reserved_tokens=130, used_tokens=0, token_limit=1000)
    row = SimpleNamespace(status="unknown", reserved=130, charged=None, error_code="MODEL_UNKNOWN")
    final = _settlement(ProviderUsage(50, 30, 20, 10), "completed", None, "synthetic-request-1")
    _apply_settlement(run, row, final)
    revision = row.revision
    settled_at = row.settled_at
    _apply_settlement(run, row, final)
    assert run.used_tokens == 80 and run.reserved_tokens == 0
    assert row.revision == revision and row.settled_at == settled_at
    with pytest.raises(DomainError) as changed:
        _apply_settlement(
            run,
            row,
            _settlement(ProviderUsage(50, 30, 21, 9), "completed", None, "synthetic-request-1"),
        )
    assert changed.value.reason == "MODEL_BUDGET_CONFLICT"
    assert row.normalized_usage["cache_read_tokens"] == 20


def test_original_unknown_request_id_cannot_be_replaced_during_settlement():
    run = SimpleNamespace(reserved_tokens=130, used_tokens=0, token_limit=1000)
    row = SimpleNamespace(
        status="unknown",
        reserved=130,
        charged=None,
        error_code="MODEL_UNKNOWN",
        request_id="synthetic-original-request",
        revision=2,
    )
    with pytest.raises(DomainError) as replaced:
        _apply_settlement(
            run,
            row,
            _settlement(ProviderUsage(50, 30), "completed", None, "synthetic-other-request"),
        )
    assert replaced.value.reason == "MODEL_BUDGET_CONFLICT"
    assert run.used_tokens == 0 and run.reserved_tokens == 130 and row.revision == 2


def test_existing_fee_can_add_missing_trace_once_without_recharging():
    run = SimpleNamespace(reserved_tokens=0, used_tokens=80, token_limit=1000)
    row = SimpleNamespace(
        status="completed",
        reserved=130,
        charged=80,
        error_code=None,
        revision=1,
        request_id=None,
        normalized_usage=None,
    )
    final = _settlement(ProviderUsage(50, 30), "completed", None, "synthetic-request-1")
    _apply_settlement(run, row, final)
    assert run.used_tokens == 80 and row.revision == 2
    assert row.request_id == "synthetic-request-1"
    _apply_settlement(run, row, final)
    assert run.used_tokens == 80 and row.revision == 2
