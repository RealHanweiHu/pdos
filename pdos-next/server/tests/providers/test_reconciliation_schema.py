from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.model_gateway.reconciliation import semantic
from pdos_next.model_gateway.reconciliation_schema import NormalizedUsage, ReconciliationPayload


def payload(**changes):
    result = {
        "call_id": str(uuid4()),
        "expected_revision": 2,
        "resolution": "known",
        "usage": {"input_tokens": 50, "output_tokens": 30},
        "request_id": "synthetic-provider-request-1",
        "reason_code": "provider_usage_verified",
        "evidence_ref": "synthetic-statement:20261002",
    }
    result.update(changes)
    return result


@pytest.mark.parametrize(
    "changes",
    [
        {"tenant_id": str(uuid4())},
        {"actor_id": str(uuid4())},
        {"run_id": str(uuid4())},
        {"qualification": "passed"},
        {"resolution": "known", "usage": None},
        {"reason_code": "provider_usage_unavailable"},
        {"request_id": "another\nrequest"},
        {"evidence_ref": "https://private.invalid?token=credential"},
        {"expected_revision": True},
        {"expected_revision": 0},
    ],
)
def test_reconciliation_rejects_identity_policy_and_incomplete_fee_input(changes):
    with pytest.raises(ValidationError):
        ReconciliationPayload.model_validate(payload(**changes))


def test_unknown_review_keeps_usage_absent():
    unknown = ReconciliationPayload.model_validate(
        payload(resolution="unknown", usage=None, reason_code="provider_usage_unavailable")
    )
    assert unknown.usage is None and unknown.confirmation_token is None
    with pytest.raises(ValidationError):
        ReconciliationPayload.model_validate(
            payload(resolution="unknown", reason_code="provider_usage_unavailable")
        )


@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": True, "output_tokens": 0},
        {"input_tokens": -1, "output_tokens": 0},
        {"input_tokens": 10, "output_tokens": 5, "cache_read_tokens": 11},
        {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_tokens": 6,
            "cache_creation_tokens": 5,
        },
        {"input_tokens": 2_147_483_647, "output_tokens": 1},
        {"input_tokens": 10, "output_tokens": 5, "raw_request": "source body"},
    ],
)
def test_usage_is_exact_nonnegative_typed_breakdown(usage):
    with pytest.raises(ValidationError):
        NormalizedUsage.model_validate(usage)


def test_cache_breakdown_does_not_add_to_total_fee():
    usage = NormalizedUsage(
        input_tokens=100, output_tokens=30, cache_read_tokens=50, cache_creation_tokens=10
    )
    model_usage = usage.provider_usage()
    assert model_usage.input_tokens + model_usage.output_tokens == 130


def test_semantic_replay_excludes_token_but_binds_original_call_usage_and_evidence():
    original = payload()
    first = ReconciliationPayload.model_validate(
        {**original, "confirmation_token": "synthetic-confirmation-token-1"}
    )
    second = ReconciliationPayload.model_validate(
        {**original, "confirmation_token": "synthetic-confirmation-token-2"}
    )
    assert semantic(first) == semantic(second)
    assert "confirmation_token" not in semantic(first)
    changed = ReconciliationPayload.model_validate(
        {**original, "evidence_ref": "synthetic-other-statement:20261002"}
    )
    assert semantic(first) != semantic(changed)
