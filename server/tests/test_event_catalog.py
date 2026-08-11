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


def test_domain_write_events_are_registered_without_changing_the_spec_catalog() -> None:
    assert {
        "TENANT_BOOTSTRAPPED",
        "USER_SIGNED_IN",
        "REQUIREMENT_CREATED",
        "REQUIREMENT_UPDATED",
        "REQUIREMENT_CONVERTED",
        "DEVELOPMENT_CASE_CREATED",
        "DEVELOPMENT_CASE_UPDATED",
        "DEVELOPMENT_CASE_STATUS_CHANGED",
        "DECISION_RECORDED",
        "PROJECT_UPDATED",
        "PROJECT_STATUS_CHANGED",
        "TASK_CREATED",
        "TASK_UPDATED",
        "TASK_STATUS_CHANGED",
        "ISSUE_UPDATED",
        "ISSUE_STATUS_CHANGED",
        "RISK_CREATED",
        "RISK_UPDATED",
        "RISK_STATUS_CHANGED",
    } <= EVENT_REGISTRY.keys()
    assert "TENANT_BOOTSTRAPPED" not in SPEC_EVENT_TYPES
    assert "USER_SIGNED_IN" not in SPEC_EVENT_TYPES
    assert "REQUIREMENT_CREATED" not in SPEC_EVENT_TYPES
    assert "REQUIREMENT_UPDATED" not in SPEC_EVENT_TYPES

    created = definition_for("REQUIREMENT_CREATED")
    assert created.entity == "requirement"
    assert created.producer == "requirement_service"
    assert created.payload_schema["required"] == ["requirement_code", "status", "priority"]

    updated = definition_for("REQUIREMENT_UPDATED")
    assert updated.entity == "requirement"
    assert updated.producer == "requirement_service"
    assert updated.payload_schema["properties"]["changed_fields"] == {"type": "array"}

    converted = definition_for("REQUIREMENT_CONVERTED")
    assert converted.entity == "requirement"
    assert converted.producer == "development_case_service"

    case_created = definition_for("DEVELOPMENT_CASE_CREATED")
    assert case_created.entity == "development_case"
    assert case_created.payload_schema["required"] == [
        "case_code",
        "requirement_id",
        "status",
    ]

    decision = definition_for("DECISION_RECORDED")
    assert decision.entity == "decision"
    assert decision.payload_schema["required"] == ["decision_kind", "outcome"]

    issue_created = definition_for("ISSUE_CREATED")
    assert issue_created.payload_schema["required"] == ["issue_id", "severity"]
    task_status = definition_for("TASK_STATUS_CHANGED")
    assert task_status.payload_schema["required"] == ["from_status", "to_status"]
    risk_created = definition_for("RISK_CREATED")
    assert risk_created.payload_schema["required"] == ["risk_id", "score", "status"]


def test_unknown_event_types_fail_closed() -> None:
    with pytest.raises(UnknownEventTypeError):
        definition_for("NOT_REGISTERED")
