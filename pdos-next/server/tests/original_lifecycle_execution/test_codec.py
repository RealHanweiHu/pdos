"""Strict codecs preserve unknown facts and exact internal byte bindings."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.original_lifecycle_execution.codec import (
    decode_candidate,
    decode_intent,
    decode_state,
    encode_candidate,
    encode_intent,
    encode_state,
)
from pdos_next.domain.original_lifecycle_execution.schemas import (
    LifecycleCancelPayload,
    LifecycleCommandPayload,
    LifecycleProtectionPayload,
)
from pdos_next.original_lifecycle.types import LifecycleFailure
from tests.original_lifecycle.helpers import confirm, fixture, preview, record, start

pytestmark = pytest.mark.usefixtures("pure_guard")


def test_full_intent_round_trip_including_exact_permit_and_trusted_receipt():
    _, store, _, service, physical = fixture()
    candidate = preview(store, service)
    intent = confirm(store, service, candidate)
    permit = start(store, service, intent)
    completed = record(store, service, intent, physical.apply_once(permit))
    assert decode_state(encode_state(store.original)) == store.original
    assert decode_candidate(encode_candidate(candidate)) == candidate
    assert decode_intent(encode_intent(completed)) == completed
    assert "scan_status" not in repr(encode_intent(completed))


def test_unknown_is_preserved_and_no_constructor_default_is_inferred():
    _, store, _, _, _ = fixture()
    state = replace(store.original, registered=None, manual_hold=None, retention_until=None)
    decoded = decode_state(encode_state(state))
    assert decoded.registered is None and decoded.manual_hold is None
    assert decoded.retention_until is None
    missing = encode_state(state)
    del missing["value"]["disposition"]
    with pytest.raises(LifecycleFailure, match="持久记录"):
        decode_state(missing)


@pytest.mark.parametrize(
    "field,value",
    [
        ("registered", 0),
        ("manual_hold", "false"),
        ("revision", True),
        ("upload_state", "unsupported"),
        ("observed_at", "2026-10-02T12:00:00"),
        ("pending_intent_id", "not-a-uuid"),
    ],
)
def test_state_strict_types_reject_coercions(field, value):
    _, store, _, _, _ = fixture()
    document = encode_state(store.original)
    document["value"][field] = value
    with pytest.raises(LifecycleFailure) as error:
        decode_state(document)
    assert error.value.code == "LIFECYCLE_DOCUMENT_INVALID"


@pytest.mark.parametrize(
    "mutation", ["version_bool", "unknown_field", "wrong_kind", "key", "scope"]
)
def test_internal_binding_and_document_shape_reject_tampering(mutation):
    _, store, _, service, _ = fixture()
    candidate = preview(store, service)
    document = encode_candidate(candidate)
    if mutation == "version_bool":
        document["schema_version"] = True
    elif mutation == "unknown_field":
        document["value"]["actor_id"] = str(uuid4())
    elif mutation == "wrong_kind":
        document["kind"] = "original_state"
    elif mutation == "key":
        document["value"]["original"]["reference"]["server_storage_key"] = "../private"
    else:
        document["value"]["references"]["scope"]["product_id"] = str(uuid4())
    with pytest.raises(LifecycleFailure):
        decode_candidate(document)


def test_mutating_one_document_does_not_alias_the_typed_original_or_new_encoding():
    _, store, _, _, _ = fixture()
    document = encode_state(store.original)
    copy = deepcopy(document)
    copy["value"]["manual_hold"] = True
    assert encode_state(store.original) == document
    assert decode_state(copy).manual_hold is True


@pytest.mark.parametrize(
    "payload",
    [
        {"candidate_id": uuid4(), "digest": "a" * 64, "reason": "review", "tenant_id": uuid4()},
        {"candidate_id": uuid4(), "digest": "A" * 64, "reason": "review"},
    ],
)
def test_confirmation_payload_cannot_supply_policy_identity_or_noncanonical_digest(payload):
    with pytest.raises(ValidationError):
        LifecycleCommandPayload.model_validate(payload)


def test_protection_and_cancel_payloads_require_explicit_typed_facts():
    clock, _, _, _, _ = fixture()
    valid = {
        "object_id": uuid4(),
        "expected_revision": 1,
        "manual_hold": False,
        "retention_until": clock.now() + timedelta(days=7),
        "reason": "named fact",
    }
    assert LifecycleProtectionPayload.model_validate(valid).manual_hold is False
    for patch in (
        {"manual_hold": "false"},
        {"expected_revision": True},
        {"retention_until": "2026-10-09T12:00:00"},
    ):
        with pytest.raises(ValidationError):
            LifecycleProtectionPayload.model_validate({**valid, **patch})
    with pytest.raises(ValidationError):
        LifecycleCancelPayload(intent_id=uuid4(), expected_revision=True, reason="cancel")
