from __future__ import annotations

import pytest

from app.events.catalog import (
    EVENT_REGISTRY,
    SPEC_EVENT_TYPES,
    UnknownEventTypeError,
    definition_for,
)

EXPECTED_SPEC_EVENT_TYPES = {
    "PROJECT_CREATED",
    "PROJECT_STAGE_CHANGED",
    "GATE_APPROVED",
    "DOCUMENT_UPLOADED",
    "TEST_FAILED",
    "ISSUE_CREATED",
    "SUPPLIER_DELAY_REPORTED",
    "COMPLAINT_CREATED",
    "AI_FINDING_CREATED",
    "AI_FEEDBACK_RECEIVED",
}


def test_spec_event_catalog_is_complete_and_versioned() -> None:
    assert SPEC_EVENT_TYPES == EXPECTED_SPEC_EVENT_TYPES
    assert EVENT_REGISTRY.keys() >= SPEC_EVENT_TYPES

    for event_type in SPEC_EVENT_TYPES:
        definition = definition_for(event_type)
        assert definition.event_type == event_type
        assert definition.version == 1
        assert definition.producer
        assert definition.consumers
        assert definition.idempotency == "unique(source,event_id); reuse event_id on retry"
        assert definition.payload_schema["type"] == "object"
        assert set(definition.payload_schema["required"]) <= set(
            definition.payload_schema["properties"]
        )
        assert definition.payload_schema["additionalProperties"] is False


def test_auth_write_events_are_registered_without_changing_the_spec_catalog() -> None:
    assert {"TENANT_BOOTSTRAPPED", "USER_SIGNED_IN"} <= EVENT_REGISTRY.keys()
    assert "TENANT_BOOTSTRAPPED" not in SPEC_EVENT_TYPES
    assert "USER_SIGNED_IN" not in SPEC_EVENT_TYPES


def test_unknown_event_types_fail_closed() -> None:
    with pytest.raises(UnknownEventTypeError):
        definition_for("NOT_REGISTERED")
